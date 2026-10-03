"""The ``hx`` command-line interface. Every command supports ``--json``."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import re
import secrets
import socket
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast, get_args

import typer
import yaml
from pydantic import ValidationError
from typer.core import TyperGroup

from hypothex._version import __version__
from hypothex.core import queries as q
from hypothex.core.config import (
    CONFIG_FILENAME,
    TaskKind,
    find_repo_root,
    load_project_config,
    parse_metric_version,
    starter_config,
)
from hypothex.core.context import Context
from hypothex.core.control import launch_run, reinfer, repair_runs, rerun, stop_run, wait_for_run
from hypothex.core.environment import load_descriptor
from hypothex.core.errors import ConfigError, HypothexError, RunError, StoreError
from hypothex.core.evaluation import reeval, validate_project
from hypothex.core.execution import RunRequest, execute_run, prepare_run, seed_warning
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.gitinfo import git_state_label
from hypothex.core.ids import new_command_id
from hypothex.core.index import rebuild_index
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.layout import Layout, default_home
from hypothex.core.records import TERMINAL_STATUSES, RunRecord, RunStatus
from hypothex.remote.config import (
    HOST_NAME,
    EnvironmentsFile,
    HostSpec,
    SlurmDefaults,
    environments_path,
    load_hosts,
    save_hosts,
)

if TYPE_CHECKING:
    from hypothex.remote.bootstrap import ServerInfo

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Hypothex: experiment tracker and control panel for AI researchers and their agents.",
)
task_app = typer.Typer(no_args_is_help=True, help="Inspect tasks.")
datasets_app = typer.Typer(no_args_is_help=True, help="Dataset fingerprints and checks.")
app.add_typer(task_app, name="task")
app.add_typer(datasets_app, name="datasets")
view_app = typer.Typer(no_args_is_help=True, help="Task views: dashboards written as YAML.")
app.add_typer(view_app, name="view")
service_app = typer.Typer(
    no_args_is_help=True,
    help="Keep an env server running on this machine (systemd user unit or launchd agent).",
)
app.add_typer(service_app, name="service")
hosts_app = typer.Typer(
    no_args_is_help=True,
    help="Remote hosts (SSH GPU boxes, SLURM clusters) that the hub runs on.",
)
app.add_typer(hosts_app, name="hosts")
KindOpt = Annotated[
    str | None, typer.Option("--kind", help="What this machine is to the hub: ssh or slurm.")
]

JsonFlag = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]
ProjectOpt = Annotated[str | None, typer.Option("--project", "-p", help="Project name.")]
WAIT_FOREVER = 7 * 24 * 3600.0


class _State:
    home: Path | None = None


_state = _State()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    home: Annotated[
        Path | None, typer.Option("--home", envvar="HYPOTHEX_HOME", help="Hypothex home directory.")
    ] = None,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show the version."
        ),
    ] = False,
) -> None:
    """Hypothex: experiment tracker and control panel for AI researchers and their agents."""
    _state.home = home


# helpers --------------------------------------------------------------------------
def _ctx() -> Context:
    return Context.open(_state.home)


def _home_path() -> Path:
    return (_state.home or default_home()).expanduser().resolve()


def _listen(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        sock.close()
        raise ConfigError(f"cannot listen on {host}:{port}: {exc.strerror or exc}") from exc
    return sock


def _url(host: str, port: int) -> str:
    reach = {"0.0.0.0": "127.0.0.1", "": "127.0.0.1", "::": "::1"}.get(host, host)
    return f"http://[{reach}]:{port}" if ":" in reach else f"http://{reach}:{port}"


def _write_private(path: Path, text: str) -> None:
    """Atomically write ``path`` as mode 0600 inside a 0700 folder (it holds a token)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)  # a stale tmp keeps its old mode, which os.replace carries
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # another user's process: alive
    except (OverflowError, ValueError):
        return False
    return True


def _refuse_live_owner(home: Path, path: Path) -> None:
    """
    Raise ``ConfigError`` when ``server.json`` names a server that may still own ``home``.

    One server per home, as the bootstrap start script keeps it: a record on
    another host (a shared home), or of a live process here, is never replaced.
    A record whose process is gone (or that cannot be read) is stale.
    """
    import httpx

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(record, dict) or not isinstance(record.get("pid"), int):
        return
    pid, port = record["pid"], record.get("port")
    where = record.get("hostname")
    if isinstance(where, str) and where and where != socket.gethostname():
        raise ConfigError(
            f"{path} names an hx server on {where} (pid {pid}), not {socket.gethostname()}; "
            f"stop it there (or remove {path} if it is gone), then retry"
        )
    if pid == os.getpid() or not _pid_alive(pid):
        return
    own_id = load_descriptor(Layout(home)).environment_id
    answered: str | None = None
    with contextlib.suppress(httpx.HTTPError, ValueError, TypeError, AttributeError):
        url = f"http://127.0.0.1:{int(port)}/.well-known/hypothex/environment"
        answered = httpx.get(url, timeout=2.0).json().get("environment_id")
    if answered == own_id:
        raise ConfigError(
            f"an hx server already serves this home on port {port} (pid {pid}); "
            "use it, or stop it first"
        )
    raise ConfigError(
        f"pid {pid} from {path} is alive but does not answer for this home on port {port}; "
        f"stop it if it is an hx server, or remove {path} if it is not, then retry"
    )


@contextmanager
def _server_file(home: Path, info: ServerInfo) -> Iterator[None]:
    # <home>/serve/server.json says which server owns this home (bootstrap reuses it);
    # the hostname tells login nodes that share a home apart (Task 11); the token is
    # why it is owner-only. A live owner keeps it: checked and written under a lock
    # of its own (start.sh holds serve/.lock while the `hx serve` it starts runs)
    import fcntl

    path = home / "serve" / "server.json"
    record = {
        **info.model_dump(mode="json"),
        "hostname": socket.gethostname(),
        "token": info.token,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    with (path.parent / ".owner.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        _refuse_live_owner(home, path)
        _write_private(path, json.dumps(record, indent=2))
    try:
        yield
    finally:
        _drop_server_file(home, info.pid)


def _drop_server_file(home: Path, pid: int) -> None:
    """Remove ``<home>/serve/server.json`` if it still names process ``pid``."""
    path = home / "serve" / "server.json"
    with contextlib.suppress(OSError, ValueError, KeyError):
        if json.loads(path.read_text(encoding="utf-8"))["pid"] == pid:
            path.unlink()


def _print_json(obj: Any) -> None:
    typer.echo(json.dumps(to_jsonable(obj), indent=2, default=str))


def _table(headers: list[str], rows: list[list[Any]]) -> None:
    cells = [[str(c) if c is not None else "—" for c in row] for row in rows]
    widths = [
        max(len(h), *(len(r[i]) for r in cells)) if cells else len(h) for i, h in enumerate(headers)
    ]
    typer.secho("  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)), bold=True)
    for row in cells:
        typer.echo("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))


def _pairs(values: list[str] | None, flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in values or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise RunError(f"{flag} must look like name=value, got {item!r}")
        out[key] = value
    return out


def _created_by() -> str:
    agent = os.environ.get("HYPOTHEX_AGENT")
    return f"agent:{agent}" if agent else "human"


def _stats(s: Any) -> str:
    if s is None:
        return "—"
    return f"{s.mean:.4f} ± {s.std:.4f} (n={s.n})"


def _request(
    argv: list[str],
    *,
    task: str | None,
    hypothesis: str | None,
    seed: int | None,
    tags: list[str] | None,
    config: Path | None,
    params: list[str] | None,
    variables: list[str] | None,
    stage: str | None,
    repo: Path | None,
    interactive: bool,
) -> RunRequest:
    root = (repo or find_repo_root(Path.cwd())).resolve()
    if not argv and stage is None:
        raise RunError("give a command after `--`, or --stage NAME")
    hyp = hypothesis
    if hyp is None and interactive and sys.stdin.isatty() and not os.environ.get("HYPOTHEX_AGENT"):
        hyp = typer.prompt("Hypothesis (why does this run exist?)", default="", show_default=False)
    return RunRequest(
        repo=root,
        command=list(argv) or None,
        stage=stage,
        task=task,
        hypothesis=hyp or "",
        seed=seed,
        tags=tags or [],
        config_path=config.resolve() if config else None,
        params=_pairs(params, "--param"),
        vars=_pairs(variables, "--var"),
        cwd=Path.cwd() if repo is None else None,
        created_by=_created_by(),
    )


def _finish(record: RunRecord, as_json: bool) -> None:
    if as_json:
        _print_json(record)
    else:
        for ref in record.datasets:
            if ref.hash_mode == "missing":
                typer.secho(
                    f"warning: dataset {ref.name} not found at {ref.path}", fg="yellow", err=True
                )
        typer.secho(
            f"{record.status.value} (exit {record.exit_code}) {record.run_id}",
            fg="green" if record.status == RunStatus.FINISHED else "red",
            err=True,
        )
    if record.status in TERMINAL_STATUSES and record.status != RunStatus.FINISHED:
        raise typer.Exit(record.exit_code or 1)


def _warn_seed(record: RunRecord) -> None:
    warning = seed_warning(record.command_template, record.seed)
    if warning is not None:
        typer.secho(f"warning: {warning}", fg="yellow", err=True)


def _issue_text(issue: dict[str, Any]) -> str:
    where = f"line {issue['line']}: " if issue.get("line") else ""
    hint = f" (did you mean {issue['suggestion']}?)" if issue.get("suggestion") else ""
    return f"{where}{issue['path']}: {issue['message']}{hint}"


RUN_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}
TaskOpt = Annotated[str | None, typer.Option("--task", "-t", help="Task this run belongs to.")]
HypOpt = Annotated[str | None, typer.Option("--hypothesis", "-H", help="Why this run exists.")]
SeedOpt = Annotated[int | None, typer.Option("--seed", help="Seed; use {seed} in the command.")]
TagOpt = Annotated[list[str] | None, typer.Option("--tag", help="Tag (repeatable).")]
ConfigOpt = Annotated[Path | None, typer.Option("--config", help="Config file; use {config}.")]
ParamOpt = Annotated[list[str] | None, typer.Option("--param", help="name=value (repeatable).")]
VarOpt = Annotated[list[str] | None, typer.Option("--var", help="Template var name=value.")]
StageOpt = Annotated[str | None, typer.Option("--stage", help="Run a stage from hypothex.yaml.")]
RepoOpt = Annotated[Path | None, typer.Option("--repo", help="Project repo (default: cwd).")]
HostOpt = Annotated[
    str | None, typer.Option("--host", help="Run on this host (`hx hosts list`); default here.")
]
GpusOpt = Annotated[int, typer.Option("--gpus", min=0, help="GPUs for each run.")]
QueueOpt = Annotated[bool, typer.Option("--queue", help="Wait in the host's queue for GPUs.")]
REMOTE_POLL_SECONDS = 2.0


class _SweepGroup(TyperGroup):
    """``hx sweep -t T --grid ... -- CMD`` creates; ``hx sweep show|cancel|extend ID`` act."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:  # typer vendors click
        if args and args[0] not in self.commands and args[0] != "--help":
            args = ["create", *args]
        return super().parse_args(ctx, args)


sweep_app = typer.Typer(
    cls=_SweepGroup,
    no_args_is_help=True,
    help=(
        "Sweeps: every grid combination x seed, launched as one group. Start one with "
        "`hx sweep -t T -H WHY --grid lr=1e-4,3e-4 --seeds 3 -- CMD '{lr}' '{seed}'`."
    ),
)
app.add_typer(sweep_app, name="sweep")


def _hub_token() -> str | None:
    # a hub that requires a token: $HYPOTHEX_HUB_TOKEN, or this home's server.json
    from hypothex.mcp.server import resolve_hub_token

    return resolve_hub_token(home=_home_path())


def _hub(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    # The hub client lives with the MCP helpers; import lazily to keep `hx` fast.
    from hypothex.mcp.server import hub_call

    return hub_call(method, path, body, token=_hub_token())


def _hub_try(method: str, path: str, body: dict[str, Any] | None = None) -> Any | None:
    from hypothex.mcp.server import HubUnavailableError

    try:
        return _hub(method, path, body)
    except HubUnavailableError:
        return None


def _client_checkout(root: Path) -> dict[str, str | None]:
    """
    The project, HEAD, and uncommitted diff of the checkout here, for a host launch.

    The hub may be another machine (spec 5.2), so the CLI sends these instead of
    its repo path; the host fetches ``commit`` and applies ``diff`` (spec 8A.4).
    Untracked files are not part of ``git diff HEAD``; a warning names them.
    """
    from hypothex.mcp.server import client_checkout

    fields, untracked = client_checkout(root)
    if untracked:
        names = ", ".join(untracked[:5]) + (" ..." if len(untracked) > 5 else "")
        typer.secho(
            f"warning: {len(untracked)} untracked file(s) are not sent to the host "
            f"(git add them first): {names}",
            fg="yellow",
            err=True,
        )
    return fields


def _through_hub(run_id: str, action: str, body: dict[str, Any]) -> Any | None:
    """
    Send a mutation of another environment's run through the hub; None for this machine's.

    The hub forwards it to the run's host with the same command id (Task 45). A run of
    this machine (or of an environment no host serves, on a hub without that run) acts
    here as in phase 1.
    """
    from hypothex.mcp.server import acts_through_hub

    if not acts_through_hub(_ctx(), run_id):
        return None
    full = {**body, "command_id": new_command_id(), "created_by": _created_by()}
    return _hub("POST", f"/api/v1/runs/{run_id}/{action}", full)


def _launch_remote(
    host: str, req: RunRequest, *, gpus: int, queue: bool, slurm: dict[str, str]
) -> RunRecord:
    if req.config_path is not None:
        raise RunError("--config is not sent to hosts; commit the file and pass it with --var")
    body = {
        **_client_checkout(req.repo),
        "task": req.task,
        "stage": req.stage,
        "command": req.command,
        "hypothesis": req.hypothesis,
        "seed": req.seed,
        "tags": req.tags,
        "params": req.params,
        "vars": req.vars,
        "gpus": gpus,
        "queue": queue,
        "slurm": slurm or None,
        "created_by": req.created_by,
        "command_id": new_command_id(),
    }
    return RunRecord.model_validate(_hub("POST", f"/api/v1/hosts/{host}/runs", body))


def _wait_remote(run_id: str) -> RunRecord:
    deadline = time.monotonic() + WAIT_FOREVER
    while time.monotonic() < deadline:
        with contextlib.suppress(StoreError):  # 404 until the hub has mirrored the run
            record = RunRecord.model_validate(_hub("GET", f"/api/v1/runs/{run_id}")["record"])
            if record.status in TERMINAL_STATUSES:
                return record
        time.sleep(REMOTE_POLL_SECONDS)
    raise RunError(f"run {run_id} did not end")


def _sweep_out(summary: dict[str, Any], as_json: bool) -> None:
    if as_json:
        _print_json(summary)
        return
    spec = summary["spec"]
    typer.secho(
        f"{spec['id']}  {spec['project']}/{spec['task'] or 'exploratory'}  "
        f"on {spec['host'] or 'local'}",
        bold=True,
    )
    typer.echo(summary["headline"])
    counts = "  ".join(f"{k} {v}" for k, v in summary["counts"].items())
    typer.echo(f"{counts}  cost ${summary['total_usd']:.2f}")
    names = [p["name"] for p in spec["grid"]]
    best = summary.get("best") or {}
    rows = []
    for cell in summary["cells"]:
        mean, lo, hi = cell.get("mean"), cell.get("lo"), cell.get("hi")
        rows.append(
            [
                *(cell["params"].get(n) for n in names),
                cell["n"],
                None if mean is None else f"{mean:.4f}",
                None if lo is None or hi is None else f"[{lo:.4f}, {hi:.4f}]",
                "best" if best and best.get("params") == cell["params"] else None,
            ]
        )
    _table([*names, "n", "mean", "95% CI", ""], rows)


def _hosts() -> tuple[Context, EnvironmentsFile]:
    c = _ctx()
    return c, load_hosts(c.layout)


def _known_host(hosts: EnvironmentsFile, name: str) -> HostSpec:
    spec = hosts.environments.get(name)
    if spec is None:
        raise ConfigError(f"unknown host {name}; see `hx hosts list`")
    return spec


def _bootstrap(c: Context, name: str, spec: HostSpec) -> ServerInfo:
    # spec 8A.2 steps 1-3 over the user's own ssh: probe, install this hx, start the server
    from hypothex.mcp.server import ssh_target
    from hypothex.remote import bootstrap

    target = ssh_target(spec)
    facts = bootstrap.probe(target, spec.home)
    if spec.kind == "slurm" and facts.slurm is None:
        raise ConfigError(f"{name} has no sbatch on PATH; drop --slurm or use the login node")
    wheel = bootstrap.build_wheel(c.layout.home / "cache" / "wheels")
    bootstrap.install(target, facts.home, wheel)
    return bootstrap.ensure_server(target, facts.home, kind=spec.kind)


def _status_cells(row: dict[str, Any]) -> list[Any]:
    gpus = row["gpus"]
    busy = sum(1 for g in gpus if g.get("run_id") or g.get("external"))
    slurm = row["slurm"]
    state = row["state"]
    return [
        row["name"],
        row["kind"],
        state["state"],
        str(state["since"])[11:19],
        f"{busy}/{len(gpus)}" if gpus else None,
        row["queue"],
        f"{slurm['pending']}/{slurm['running']}" if slurm else None,
        f"${row['cost_today_usd']:.2f}",
        state.get("message") or None,
    ]


# project ---------------------------------------------------------------------------
@app.command()
def init(
    project: Annotated[str | None, typer.Option(help="Project name (default: folder).")] = None,
    force: Annotated[bool, typer.Option(help="Overwrite an existing file.")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Create a starter hypothex.yaml in the current directory."""
    path = Path.cwd() / CONFIG_FILENAME
    if path.exists() and not force:
        raise RunError(f"{path} exists; use --force to overwrite")
    name = project or re.sub(r"[^a-z0-9_.-]+", "-", Path.cwd().name.lower()).strip("-") or "project"
    path.write_text(starter_config(name), encoding="utf-8")
    if as_json:
        _print_json({"path": str(path), "project": name})
    else:
        typer.echo(f"wrote {path}; edit it, then run `hx validate`")


@app.command()
def validate(repo: RepoOpt = None, as_json: JsonFlag = False) -> None:
    """Check hypothex.yaml, metric imports, and dataset paths."""
    report = validate_project(_ctx(), repo or find_repo_root(Path.cwd()))
    if as_json:
        _print_json(report)
    else:
        for e in report.errors:
            typer.secho(f"error: {e}", fg="red")
        for w in report.warnings:
            typer.secho(f"warning: {w}", fg="yellow")
        if report.ok:
            typer.secho("ok", fg="green")
    if not report.ok:
        raise typer.Exit(1)


@app.command()
def projects(as_json: JsonFlag = False) -> None:
    """List projects."""
    entries = q.list_projects(_ctx())
    if as_json:
        _print_json(
            [
                {"project": e.project, "repo": e.repo, "tasks": sorted(e.config.tasks)}
                for e in entries
            ]
        )
        return
    _table(
        ["project", "repo", "tasks"],
        [[e.project, e.repo, ", ".join(sorted(e.config.tasks))] for e in entries],
    )


@app.command()
def tasks(project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """List tasks with their dataset, metric versions, and best score."""
    items = q.list_tasks(_ctx(), project)
    if as_json:
        _print_json(items)
        return
    _table(
        ["task", "dataset", "metrics", "primary", "runs", "best"],
        [
            [
                f"{t.project}/{t.name}",
                f"{t.dataset}@{t.dataset_version}",
                ", ".join(f"{m}@{v}" for m, v in t.metrics.items()),
                t.primary,
                t.n_runs,
                None if t.best is None else f"{t.best:.4f}",
            ]
            for t in items
        ],
    )


@task_app.command("show")
def task_show(ref: str, project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """Show a task: dataset, metrics, stages, repo."""
    detail = q.get_task(_ctx(), ref, project)
    if as_json:
        _print_json(detail)
    else:
        typer.echo(yaml.safe_dump(detail, sort_keys=False))


@app.command()
def leaderboard(
    ref: str,
    project: ProjectOpt = None,
    metric: Annotated[
        list[str] | None,
        typer.Option("--metric", help="Pin a metric version: name@version (repeatable)."),
    ] = None,
    as_json: JsonFlag = False,
) -> None:
    """Rank seed groups of a task (mean ± std over seeds)."""
    versions = {}
    for item in metric or []:
        name, version = parse_metric_version(item)
        if version is None:
            raise RunError(f"--metric needs name@version, got {item!r}")
        versions[name] = version
    board = q.get_leaderboard(_ctx(), ref, project, versions or None)
    if as_json:
        _print_json(board)
        return
    typer.secho(
        f"{board.project}/{board.task}  primary={board.primary}  versions={board.metric_versions}",
        bold=True,
    )
    rows = []
    for i, r in enumerate(board.rows, 1):
        noise = {True: "within noise", False: "", None: "single seed" if r.single_seed else ""}
        rows.append(
            [
                i,
                r.group_id,
                _stats(r.primary),
                noise[r.within_noise_of_best],
                r.latest_run_id,
                r.hypothesis[:50],
            ]
        )
    _table(["#", "group", board.primary, "note", "latest run", "hypothesis"], rows)
    if board.needs_reeval:
        typer.secho(
            f"{len(board.needs_reeval)} runs scored on older metric versions: "
            f"run `hx reeval --task {board.project}/{board.task}`",
            fg="yellow",
        )
    if board.unscored:
        typer.secho(f"{len(board.unscored)} finished runs have no scores", fg="yellow")


# runs ---------------------------------------------------------------------------
@app.command("runs")
def list_runs_cmd(
    project: ProjectOpt = None,
    task: TaskOpt = None,
    status: Annotated[RunStatus | None, typer.Option(help="Filter by status.")] = None,
    tag: Annotated[str | None, typer.Option(help="Filter by tag.")] = None,
    archived: Annotated[bool, typer.Option(help="Include archived runs.")] = False,
    limit: Annotated[int, typer.Option(help="Maximum rows.")] = 50,
    as_json: JsonFlag = False,
) -> None:
    """List runs, newest first."""
    records = _ctx().index.list_runs(
        project=project, task=task, status=status, tag=tag, include_archived=archived, limit=limit
    )
    if as_json:
        _print_json(records)
        return
    _table(
        ["run", "task", "status", "created", "hypothesis"],
        [
            [
                r.run_id,
                r.task,
                r.status.value,
                r.created_at.strftime("%Y-%m-%d %H:%M"),
                r.hypothesis[:50],
            ]
            for r in records
        ],
    )


@app.command()
def show(run_id: str, as_json: JsonFlag = False) -> None:
    """Show everything about a run, including where every file lives."""
    detail = q.show_run(_ctx(), run_id)
    if as_json:
        _print_json(detail)
        return
    r = detail.record
    typer.secho(f"{r.run_id}  [{r.status.value}]  {r.project}/{r.task or 'exploratory'}", bold=True)
    typer.echo(f"hypothesis: {r.hypothesis or '—'}")
    typer.echo(f"command:    {r.command_display}")
    typer.echo(f"git:        {r.git.commit or '—'}  {git_state_label(r.git)}")
    typer.secho("paths:", bold=True)
    for k, v in detail.paths.items():
        typer.echo(f"  {k:<22} {v}")
    if detail.scores:
        typer.secho("scores:", bold=True)
        for s in detail.scores:
            value = s.value if s.error is None else "ERROR"
            typer.echo(f"  {s.metric}@{s.version}/{s.key} = {value}")


@app.command(context_settings=RUN_SETTINGS)
def run(
    ctx: typer.Context,
    task: TaskOpt = None,
    hypothesis: HypOpt = None,
    seed: SeedOpt = None,
    tag: TagOpt = None,
    config: ConfigOpt = None,
    param: ParamOpt = None,
    var: VarOpt = None,
    stage: StageOpt = None,
    repo: RepoOpt = None,
    child: Annotated[
        str | None,
        typer.Option("--child", hidden=True, help="Execute a submitted run (inside a SLURM job)."),
    ] = None,
    as_json: JsonFlag = False,
) -> None:
    """Run a command in the foreground and record it: hx run -t TASK -H WHY -- CMD..."""
    if child is not None:
        from hypothex.core.slurm import run_child

        # never _ctx(): the compute node must not open index.db / events.db
        _finish(
            run_child(
                (_state.home or default_home()).expanduser().resolve(),
                child,
                stdout_sink=sys.stderr.buffer if as_json else sys.stdout.buffer,
                stderr_sink=sys.stderr.buffer,
            ),
            as_json,
        )
        return
    req = _request(
        ctx.args,
        task=task,
        hypothesis=hypothesis,
        seed=seed,
        tags=tag,
        config=config,
        params=param,
        variables=var,
        stage=stage,
        repo=repo,
        interactive=not as_json,
    )
    c = _ctx()
    record = prepare_run(c, req)
    typer.secho(f"run {record.run_id} -> {c.run_dir(record)}", fg="cyan", err=True)
    _warn_seed(record)
    final = execute_run(
        c,
        record.run_id,
        stdout_sink=sys.stderr.buffer if as_json else sys.stdout.buffer,
        stderr_sink=sys.stderr.buffer,
    )
    _finish(final, as_json)


@app.command(context_settings=RUN_SETTINGS)
def launch(
    ctx: typer.Context,
    task: TaskOpt = None,
    hypothesis: HypOpt = None,
    seed: SeedOpt = None,
    tag: TagOpt = None,
    config: ConfigOpt = None,
    param: ParamOpt = None,
    var: VarOpt = None,
    stage: StageOpt = None,
    repo: RepoOpt = None,
    host: HostOpt = None,
    gpus: GpusOpt = 0,
    queue: QueueOpt = False,
    partition: Annotated[str | None, typer.Option(help="SLURM partition.")] = None,
    time_limit: Annotated[
        str | None, typer.Option("--time", help="SLURM time limit, e.g. 04:00:00.")
    ] = None,
    account: Annotated[str | None, typer.Option(help="SLURM account.")] = None,
    wait: Annotated[bool, typer.Option(help="Block until the run ends.")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Start a run in the background, here or on a host (same options as `hx run`)."""
    req = _request(
        ctx.args,
        task=task,
        hypothesis=hypothesis,
        seed=seed,
        tags=tag,
        config=config,
        params=param,
        variables=var,
        stage=stage,
        repo=repo,
        interactive=not as_json,
    )
    slurm = {
        k: v
        for k, v in {"partition": partition, "time": time_limit, "account": account}.items()
        if v is not None
    }
    remote = False
    if host is not None:
        from hypothex.mcp.server import is_remote

        remote = is_remote(host)
    if remote:
        record = _launch_remote(str(host), req, gpus=gpus, queue=queue, slurm=slurm)
        _warn_seed(record)
        if wait:
            _finish(_wait_remote(record.run_id), as_json)
        elif as_json:
            _print_json(record)
        else:
            typer.echo(f"launched {record.run_id} on {host}; follow with `hx show {record.run_id}`")
        return
    if slurm:
        raise RunError("--partition, --time, and --account need --host <slurm host>")
    c = _ctx()
    record = launch_run(c, dataclasses.replace(req, gpus=gpus, queue=queue))
    _warn_seed(record)
    if wait:
        record = wait_for_run(c, record.run_id, timeout=WAIT_FOREVER)
        _finish(record, as_json)
    elif as_json:
        _print_json(record)
    else:
        typer.echo(f"launched {record.run_id}; follow with `hx logs {record.run_id} --follow`")


ForegroundOpt = Annotated[bool, typer.Option(help="Run here and stream output.")]


def _started(record: RunRecord, foreground: bool, as_json: bool) -> None:
    if foreground:
        _finish(record, as_json)
    elif as_json:
        _print_json(record)
    else:
        typer.echo(f"launched {record.run_id}")


def _emit(obj: Any, as_json: bool, text: str) -> None:
    if as_json:
        _print_json(obj)
    else:
        typer.echo(text)


def _not_foreground(run_id: str, foreground: bool) -> None:
    if foreground:
        raise RunError(f"run {run_id} runs on its host; drop --foreground")


@app.command("rerun")
def rerun_cmd(run_id: str, foreground: ForegroundOpt = False, as_json: JsonFlag = False) -> None:
    """Rerun with the same command, commit, config, and seed."""
    from hypothex.mcp.server import acts_through_hub

    if acts_through_hub(_ctx(), run_id):
        _not_foreground(run_id, foreground)
        out = _through_hub(run_id, "rerun", {})
        _started(RunRecord.model_validate(out), False, as_json)
        return
    record = rerun(
        _ctx(),
        run_id,
        background=not foreground,
        created_by=_created_by(),
        stdout_sink=None if as_json else sys.stdout.buffer,
        stderr_sink=sys.stderr.buffer,
    )
    _started(record, foreground, as_json)


@app.command("reinfer")
def reinfer_cmd(
    run_id: str,
    checkpoint: Annotated[str | None, typer.Option(help="Checkpoint path override.")] = None,
    foreground: ForegroundOpt = False,
    as_json: JsonFlag = False,
) -> None:
    """Run the `infer` stage again with this run's checkpoint."""
    from hypothex.mcp.server import acts_through_hub

    if acts_through_hub(_ctx(), run_id):
        _not_foreground(run_id, foreground)
        out = _through_hub(run_id, "reinfer", {"checkpoint": checkpoint})
        _started(RunRecord.model_validate(out), False, as_json)
        return
    record = reinfer(
        _ctx(),
        run_id,
        checkpoint=checkpoint,
        background=not foreground,
        created_by=_created_by(),
        stdout_sink=None if as_json else sys.stdout.buffer,
        stderr_sink=sys.stderr.buffer,
    )
    _started(record, foreground, as_json)


@app.command("reeval")
def reeval_cmd(
    run_id: Annotated[str | None, typer.Argument(help="One run; or use --task.")] = None,
    task: TaskOpt = None,
    project: ProjectOpt = None,
    metric: Annotated[str | None, typer.Option(help="name or name@version (current).")] = None,
    force: Annotated[bool, typer.Option(help="Re-score already scored runs.")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Re-score saved predictions with the current metric versions."""
    from hypothex.mcp.server import acts_through_hub

    c = _ctx()
    if run_id is not None and acts_through_hub(c, run_id):
        body = {"metric": metric, "force": force, "command_id": new_command_id()}
        out = _hub("POST", f"/api/v1/runs/{run_id}/reeval", {**body, "created_by": _created_by()})
        if as_json:
            _print_json(out)
        else:
            typer.echo(f"evaluated {len(out['evaluated'])}, skipped {len(out['skipped'])}")
        return
    if run_id is not None:
        report = reeval(c, run_id=run_id, metric=metric, force=force)
    elif task is not None:
        entry, name = q.resolve_task(c, task, project)
        report = reeval(c, project=entry.project, task=name, metric=metric, force=force)
    else:
        raise RunError("give a run id or --task")
    if as_json:
        _print_json(report)
        return
    typer.echo(f"evaluated {len(report.evaluated)}, skipped {len(report.skipped)}")
    for rid, why in report.skipped.items():
        typer.echo(f"  skipped {rid}: {why}")
    for w in report.warnings:
        typer.secho(f"warning: {w}", fg="yellow")


@app.command()
def stop(run_id: str, as_json: JsonFlag = False) -> None:
    """Stop a queued or running run."""
    out = _through_hub(run_id, "stop", {})
    record = RunRecord.model_validate(out) if out is not None else stop_run(_ctx(), run_id)
    _emit(record, as_json, f"{record.run_id} {record.status.value}")


@app.command()
def compare(run_ids: list[str], as_json: JsonFlag = False) -> None:
    """Show config and score differences between runs."""
    cmp = q.compare_runs(_ctx(), run_ids)
    if as_json:
        _print_json(cmp)
        return
    _table(["field", *cmp.run_ids], [[k, *v] for k, v in {**cmp.fields, **cmp.scores}.items()])


@app.command()
def examples(
    a: str,
    b: str,
    metric: Annotated[str, typer.Option(help="name or name@version.")],
    field: Annotated[str, typer.Option(help="Per-example success field.")] = "correct",
    as_json: JsonFlag = False,
) -> None:
    """List examples fixed or broken by run B relative to run A."""
    diff = q.compare_examples(_ctx(), a, b, metric, field)
    if as_json:
        _print_json(diff)
        return
    typer.echo(
        f"fixed {len(diff.fixed)}, broken {len(diff.broken)}, "
        f"both pass {diff.both_pass}, both fail {diff.both_fail}"
    )
    for i in diff.broken[:20]:
        typer.secho(f"  broken: {i}", fg="red")
    for i in diff.fixed[:20]:
        typer.secho(f"  fixed:  {i}", fg="green")


@app.command()
def predictions(
    run_id: str,
    metric: Annotated[str | None, typer.Option(help="name or name@version.")] = None,
    failures: Annotated[bool, typer.Option(help="Only failing examples.")] = False,
    field: Annotated[str, typer.Option(help="Per-example success field.")] = "correct",
    offset: int = 0,
    limit: int = 20,
    as_json: JsonFlag = False,
) -> None:
    """Page through a run's predictions with per-example scores."""
    page = q.get_predictions(
        _ctx(),
        run_id,
        offset=offset,
        limit=limit,
        metric=metric,
        failures_only=failures,
        field=field,
    )
    if as_json:
        _print_json(page)
        return
    _table(
        ["id", "prediction", "reference", "scores"],
        [
            [
                r.id,
                json.dumps(r.prediction)[:40],
                json.dumps(r.reference)[:40],
                json.dumps(r.scores)[:60],
            ]
            for r in page.rows
        ],
    )
    typer.echo(f"{page.offset}-{page.offset + len(page.rows)} of {page.total}")


@app.command()
def logs(
    run_id: str,
    stream: Annotated[str, typer.Option(help="stdout, stderr, or supervisor.")] = "stdout",
    follow: Annotated[bool, typer.Option(help="Keep printing until the run ends.")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Print a run's log (tail), optionally following it."""
    c = _ctx()
    chunk = q.read_log(c, run_id, stream)
    if as_json:
        _print_json(chunk)
        return
    typer.echo(chunk.text, nl=False)
    while follow:
        if c.find_record(run_id).status in TERMINAL_STATUSES:
            typer.echo(q.read_log(c, run_id, stream, chunk.offset).text, nl=False)
            return
        time.sleep(1)
        chunk = q.read_log(c, run_id, stream, chunk.offset)
        typer.echo(chunk.text, nl=False)


# curation -------------------------------------------------------------------------
@app.command()
def tag(
    run_id: str,
    add: Annotated[list[str] | None, typer.Option("--add", help="Tag to add.")] = None,
    remove: Annotated[list[str] | None, typer.Option("--remove", help="Tag to remove.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Add or remove tags."""
    out = _through_hub(run_id, "tags", {"add": add or [], "remove": remove or []})
    record = (
        RunRecord.model_validate(out)
        if out is not None
        else q.tag_run(_ctx(), run_id, add or [], remove or [])
    )
    _emit(record, as_json, ", ".join(record.tags) or "(no tags)")


OffFlag = Annotated[bool, typer.Option("--off", help="Undo.")]


@app.command()
def star(run_id: str, off: OffFlag = False, as_json: JsonFlag = False) -> None:
    """Star (or --off unstar) a run."""
    out = _through_hub(run_id, "star", {"on": not off})
    record = RunRecord.model_validate(out) if out else q.star_run(_ctx(), run_id, on=not off)
    _emit(record, as_json, f"starred={record.starred}")


@app.command()
def archive(run_id: str, off: OffFlag = False, as_json: JsonFlag = False) -> None:
    """Archive (hide) or --off unarchive a run."""
    out = _through_hub(run_id, "archive", {"on": not off})
    record = RunRecord.model_validate(out) if out else q.archive_run(_ctx(), run_id, on=not off)
    _emit(record, as_json, f"archived={record.archived}")


@app.command()
def note(
    run_id: str,
    text: str,
    author: Annotated[str | None, typer.Option(help="Author (default: human/agent).")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Add a note to a run."""
    if _through_hub(run_id, "notes", {"text": text, "author": author or _created_by()}) is None:
        q.add_note(_ctx(), run_id, text, author or _created_by())
    _emit({"ok": True}, as_json, "noted")


# sweeps ---------------------------------------------------------------------------
@sweep_app.command("create", context_settings=RUN_SETTINGS)
def sweep_create(
    ctx: typer.Context,
    task: TaskOpt = None,
    hypothesis: HypOpt = None,
    grid: Annotated[
        list[str] | None, typer.Option("--grid", help="name=v1,v2 (repeatable).")
    ] = None,
    random_n: Annotated[
        int | None, typer.Option("--random", min=1, help="Random samples from --param ranges.")
    ] = None,
    ranges: Annotated[
        list[str] | None,
        typer.Option("--param", help="name=low:high[:log], sampled by --random (repeatable)."),
    ] = None,
    seeds: Annotated[
        str, typer.Option("--seeds", help="A count (3 means 1,2,3) or a list (1,2,5).")
    ] = "3",
    host: HostOpt = None,
    gpus: GpusOpt = 0,
    queue: QueueOpt = False,
    repo: RepoOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Start a sweep (default subcommand): every combination x seed, tagged with the sweep."""
    from hypothex.core.sweeps import launch_sweep
    from hypothex.mcp.server import is_remote, parse_grid, parse_ranges, parse_seeds

    root = (repo or find_repo_root(Path.cwd())).resolve()
    project = load_project_config(root).project
    params = parse_grid(grid or []) + parse_ranges(ranges or [])
    if not params:
        raise RunError("give at least one --grid name=v1,v2 (or --random N with --param)")
    seed_list = parse_seeds(seeds)
    argv = list(ctx.args)
    if not argv:
        raise RunError("give the command after `--`")
    if is_remote(host):
        body = {
            **_client_checkout(root),
            "project": project,
            "task": task,
            "host": host,
            "grid": [p.model_dump(mode="json") for p in params],
            "random": random_n,
            "seeds": seed_list,
            "command": argv,
            "hypothesis": hypothesis or "",
            "gpus": gpus,
            "queue": queue,
            "created_by": _created_by(),
            "command_id": new_command_id(),
        }
        _sweep_out(_hub("POST", "/api/v1/sweeps", body), as_json)
        return
    c = _ctx()
    c.register_project(root)
    summary = launch_sweep(
        c,
        project=project,
        task=task,
        grid=params,
        random=random_n,
        seeds=seed_list,
        command=argv,
        hypothesis=hypothesis or "",
        gpus=gpus,
        queue=queue,
        created_by=_created_by(),
        repo=root,
    )
    _sweep_out(to_jsonable(summary), as_json)


@sweep_app.command("show")
def sweep_show(sweep_id: str, project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """Show a sweep: progress, params x primary metric, best cell, cost."""
    from hypothex.mcp.server import sweep_summary

    _sweep_out(sweep_summary(_ctx(), sweep_id, project, token=_hub_token()), as_json)


@sweep_app.command("cancel")
def sweep_cancel(sweep_id: str, project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """Stop the sweep's queued runs; running runs keep going."""
    from hypothex.core.sweeps import cancel_queued
    from hypothex.mcp.server import is_remote, locate_sweep

    c = _ctx()
    spec, here = locate_sweep(c, sweep_id, project, token=_hub_token())
    if is_remote(spec.host) or not here:
        body = {"command_id": new_command_id(), "created_by": _created_by()}
        summary = _hub("POST", f"/api/v1/sweeps/{spec.project}/{spec.id}/cancel_queued", body)
    else:
        summary = to_jsonable(cancel_queued(c, spec.project, spec.id))
    _sweep_out(summary, as_json)


@sweep_app.command("extend")
def sweep_extend(
    sweep_id: str,
    seeds: Annotated[str, typer.Option("--seeds", help="Seeds to add, e.g. 4,5.")],
    project: ProjectOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Add runs for every combination x the new seeds."""
    from hypothex.core.sweeps import extend_sweep
    from hypothex.mcp.server import is_remote, locate_sweep, parse_seeds

    c = _ctx()
    spec, here = locate_sweep(c, sweep_id, project, token=_hub_token())
    seed_list = parse_seeds(seeds, count_ok=False)
    if is_remote(spec.host) or not here:
        body = {"seeds": seed_list, "command_id": new_command_id(), "created_by": _created_by()}
        summary = _hub("POST", f"/api/v1/sweeps/{spec.project}/{spec.id}/extend", body)
    else:
        summary = to_jsonable(extend_sweep(c, spec.project, spec.id, seed_list))
    _sweep_out(summary, as_json)


@app.command("sweeps")
def sweeps_cmd(project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """List sweeps, newest first."""
    from hypothex.core.sweeps import list_sweeps

    c = _ctx()
    projects = [project] if project else [e.project for e in c.store.list_projects()]
    rows: list[dict[str, Any]] = [{"project": p, **s} for p in projects for s in list_sweeps(c, p)]
    rows.sort(key=lambda s: s["created_at"], reverse=True)
    if as_json:
        _print_json(rows)
        return
    _table(
        ["sweep", "project", "created", "runs", "best"],
        [
            [
                s["id"],
                s["project"],
                s["created_at"].strftime("%Y-%m-%d %H:%M"),
                s["n_runs"],
                None if s["best"] is None else json.dumps(s["best"].get("params"))[:40],
            ]
            for s in rows
        ],
    )


@app.command()
def pull(
    run_id: str,
    artifact: Annotated[
        str,
        typer.Option(help="Artifact kind (latest of it), artifact path, or run-folder path."),
    ] = "checkpoint",
    as_json: JsonFlag = False,
) -> None:
    """Copy a big file of a remote run to this machine, through the hub."""
    body = {"artifact": artifact, "command_id": new_command_id(), "created_by": _created_by()}
    out = _hub("POST", f"/api/v1/runs/{run_id}/pull", body)
    _emit(out, as_json, out["local_path"])


# views ----------------------------------------------------------------------------
# The helpers live in hypothex.mcp.server (shared with the API and MCP); importing it
# loads the MCP SDK, so each command imports it lazily to keep `hx` startup fast.
@view_app.command("list")
def view_list(task: str, project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """List a task's views: preset `overview`, inline views, view files."""
    from hypothex.mcp.server import list_task_views

    views = list_task_views(_ctx(), task, project)
    if as_json:
        _print_json(views)
        return
    _table(
        ["name", "title", "origin", "path"], [[v.name, v.title, v.origin, v.path] for v in views]
    )


@view_app.command("show")
def view_show(task: str, name: str, project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """Print a view's YAML."""
    from hypothex.mcp.server import view_document

    doc = view_document(_ctx(), task, name, project)
    if as_json:
        _print_json(doc)
    else:
        typer.echo(doc["text"], nl=not doc["text"].endswith("\n"))


@view_app.command("init")
def view_init(
    task: str,
    from_kind: Annotated[str, typer.Option("--from", help="Preset kind to start from.")],
    name: Annotated[str, typer.Option("--name", help="View name.")],
    project: ProjectOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Create a view file that starts from a kind's preset panels."""
    from hypothex.mcp.server import list_task_views, put_view

    c = _ctx()
    if name in {v.name for v in list_task_views(c, task, project)}:
        raise ConfigError(f"view {name!r} exists; edit it, or replace it with `hx view add`")
    text = yaml.safe_dump({"title": name, "from": from_kind, "panels": []}, sort_keys=False)
    out = put_view(c, task, name, text, project)
    _emit(out, as_json, f"wrote {out['info']['path']}")


def _read_view_file(file: Path) -> str:
    """
    Read a view YAML file as UTF-8.

    Parameters
    ----------
    file : Path
        The view file.

    Returns
    -------
    str
        The file's text.

    Raises
    ------
    ConfigError
        The file cannot be read or is not UTF-8 (``hx view show`` says the same).
    """
    try:
        return file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{file}: cannot read view file: {exc}") from exc


@view_app.command("add")
def view_add(
    task: str,
    file: Annotated[
        Path, typer.Option("--file", exists=True, dir_okay=False, help="View YAML file.")
    ],
    name: Annotated[str | None, typer.Option("--name", help="View name (default: stem).")] = None,
    project: ProjectOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Validate a view file and save it under .hypothex/views/<task>/."""
    from hypothex.mcp.server import put_view

    out = put_view(_ctx(), task, name or file.stem, _read_view_file(file), project)
    _emit(out, as_json, f"wrote {out['info']['path']}")


@view_app.command("validate")
def view_validate(
    task: str,
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="View YAML file.")],
    project: ProjectOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Check a view file against the task's metrics and fields; save nothing."""
    from hypothex.mcp.server import validate_view

    report = validate_view(_ctx(), task, _read_view_file(file), project)
    if as_json:
        _print_json(report)
    else:
        for issue in report["issues"]:
            typer.secho(f"{file}: {_issue_text(issue)}", fg="red")
        if report["ok"]:
            typer.secho("ok", fg="green")
    if not report["ok"]:
        raise typer.Exit(1)


@view_app.command("rm")
def view_rm(task: str, name: str, project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """Delete a view file."""
    from hypothex.mcp.server import remove_view

    _emit(remove_view(_ctx(), task, name, project), as_json, f"removed {name}")


# datasets & maintenance -------------------------------------------------------------
@datasets_app.command("check")
def datasets_check(project: ProjectOpt = None, as_json: JsonFlag = False) -> None:
    """Re-fingerprint datasets used by runs and report changes."""
    drift = q.check_datasets(_ctx(), project)
    if as_json:
        _print_json(drift)
        return
    _table(
        ["run", "dataset", "status", "path"],
        [[d.run_id, d.dataset, d.status, d.path] for d in drift],
    )


@datasets_app.command("overlap")
def datasets_overlap(
    project: str,
    dataset: str,
    key: Annotated[str | None, typer.Option(help="JSON field identifying an example.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Count examples shared between a dataset's splits."""
    report = q.dataset_overlap(_ctx(), project, dataset, key)
    if as_json:
        _print_json(report)
        return
    _table(["splits", "shared"], [[k, v] for k, v in report.pairs.items()])


@app.command()
def reindex(as_json: JsonFlag = False) -> None:
    """Rebuild the index from run folders."""
    c = _ctx()
    count = rebuild_index(c.index, c.store)
    _emit({"runs": count}, as_json, f"indexed {count} runs")


@app.command()
def repair(as_json: JsonFlag = False) -> None:
    """Mark runs whose supervisor died as lost."""
    lost = repair_runs(_ctx())
    if as_json:
        _print_json({"lost": [r.run_id for r in lost]})
    else:
        typer.echo(f"marked {len(lost)} runs lost")


SERVE_KINDS = ("ssh", "slurm")


def check_serve_kind(kind: str | None) -> None:
    """
    Check a ``--kind`` option.

    Parameters
    ----------
    kind : str or None
        ``ssh``, ``slurm``, or None (not given).

    Raises
    ------
    ConfigError
        For any other value.
    """
    if kind is not None and kind not in SERVE_KINDS:
        raise ConfigError(f"--kind must be ssh or slurm, got {kind!r}")


def resolve_serve_kind(home: Path, kind: str | None) -> str:
    """
    Pick the environment kind ``hx serve`` runs as, and remember it.

    Parameters
    ----------
    home : Path
        The Hypothex home of this env server.
    kind : str or None
        ``--kind``; None reuses the kind saved in ``environment.json``.

    Returns
    -------
    str
        ``local`` (the hub, or a plain machine), ``ssh`` (runs the GPU queue),
        or ``slurm`` (submits to SLURM).

    Raises
    ------
    ConfigError
        If ``kind`` is not ``ssh`` or ``slurm``.

    Examples
    --------
    >>> import tempfile
    >>> resolve_serve_kind(Path(tempfile.mkdtemp()), None)
    'local'
    """
    check_serve_kind(kind)
    layout = Layout(home.expanduser().resolve())
    layout.ensure()
    load_descriptor(layout)  # creates environment.json with a stable id on first use
    identity = json.loads(layout.environment_json.read_text(encoding="utf-8"))
    if kind is None:
        return str(identity.get("kind", "local"))
    if identity.get("kind") != kind:
        atomic_write_text(layout.environment_json, json.dumps({**identity, "kind": kind}, indent=2))
    return kind


def _serve_token(host: str, kind: str | None, no_auth: bool) -> str | None:
    """
    Take the bearer token ``hx serve`` requires, and refuse an open network bind.

    The token comes from ``HYPOTHEX_SERVE_TOKEN`` and is removed from the
    environment at once, so runs started by this server never inherit it. An env
    server (``kind`` ``ssh`` or ``slurm``) always has one, a fresh
    ``secrets.token_hex(24)`` when none is given, unless ``no_auth``: any local
    user on a shared host can reach its loopback port. The hub's own server keeps
    phase 1's rule: a token only when one is given.

    Parameters
    ----------
    host : str
        The ``--host`` to bind.
    kind : str or None
        The resolved environment kind (``local``, ``ssh``, or ``slurm``).
    no_auth : bool
        ``--no-auth``: serve without a token (demo and test hosts only).

    Returns
    -------
    str or None
        The token, or None when the server runs without one (loopback binds only).

    Raises
    ------
    ConfigError
        ``host`` is not a loopback address and there is no token: the API starts
        arbitrary commands, and the ``Host``/``Origin`` checks are no defence
        against a client on the network.

    Examples
    --------
    >>> _serve_token("127.0.0.1", "local", False) is None
    True
    """
    from hypothex.api.security import is_loopback_bind

    given = os.environ.pop("HYPOTHEX_SERVE_TOKEN", None) or None
    if no_auth:
        token = None
    elif kind in SERVE_KINDS:
        token = given or secrets.token_hex(24)
    else:
        token = given
    if token is None and not is_loopback_bind(host):
        raise ConfigError(
            f"refusing to serve on {host!r} without authentication: anyone who can reach "
            "this address could start arbitrary commands and read run files through the "
            "API. Set HYPOTHEX_SERVE_TOKEN to require 'Authorization: Bearer <token>', or "
            "keep --host 127.0.0.1 and reach it through an SSH tunnel "
            "(ssh -L 7777:127.0.0.1:7777 HOST)"
        )
    return token


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port; 0 picks a free one.")] = 7777,
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            help="Run as a host's env server: ssh (GPU queue) or slurm. Default: the saved kind.",
        ),
    ] = None,
    no_auth: Annotated[
        bool,
        typer.Option(
            "--no-auth", help="Env server without a bearer token (demo and test hosts only)."
        ),
    ] = False,
) -> None:
    """
    Serve the HTTP/WebSocket API, the UI when built, and (on the hub) the hosts.

    An env server (``--kind ssh|slurm``) requires ``Authorization: Bearer <token>``
    on every request except the environment descriptor; the token is
    ``HYPOTHEX_SERVE_TOKEN`` or a fresh one, and is kept in ``<home>/serve/server.json``
    (mode 0600). The hub's server needs a token only when ``HYPOTHEX_SERVE_TOKEN``
    is set. A non-loopback --host is refused without a token.
    """
    import uvicorn

    from hypothex.api.app import create_app
    from hypothex.core.environment import PROTOCOL_VERSION
    from hypothex.demo import demo_hosts_running
    from hypothex.remote.bootstrap import ServerInfo

    home = _home_path()
    resolved = resolve_serve_kind(home, kind)
    token = _serve_token(host, resolved, no_auth)
    sock = _listen(host, port)
    bound = sock.getsockname()[1]
    info = ServerInfo(
        pid=os.getpid(),
        port=bound,
        managed=False,
        hx_version=__version__,
        protocol_version=PROTOCOL_VERSION,
        token=token,
    )

    class _Server(uvicorn.Server):
        # uvicorn re-raises SIGTERM/SIGINT once it has shut down, which ends the
        # process before `with _server_file` cleans up: drop server.json first
        @contextmanager
        def capture_signals(self) -> Iterator[None]:
            with super().capture_signals():
                try:
                    yield
                finally:
                    _drop_server_file(home, info.pid)

    @contextmanager
    def demo_hosts() -> Iterator[None]:
        # entered and left by the app's lifespan, so SIGTERM stops the demo hosts too
        with demo_hosts_running(home) as live:
            if live:
                typer.secho(f"demo hosts up; {len(live)} sweep runs launched on gpu1", err=True)
            yield

    with _server_file(home, info):
        application = create_app(
            home,
            host=host,
            kind=resolved,
            auth_token=token,
            hub_url=_url(host, bound),
            lifespan_context=demo_hosts,
        )
        typer.secho(f"hx serve on {_url(host, bound)}", err=True)
        # the socket is bound already: uvicorn logs no "running on" line for it, so
        # the start script finds the port in server.json (written above, Task 11)
        config = uvicorn.Config(application, host=host, port=bound, log_level="info")
        _Server(config).run(sockets=[sock])


@service_app.command("install")
def service_install(kind: KindOpt = None, as_json: JsonFlag = False) -> None:
    """Write the unit file and print how to enable it (hx never runs systemctl/launchctl)."""
    from hypothex.remote.service import install_service

    check_serve_kind(kind)
    out = install_service(_home_path(), kind)
    if as_json:
        _print_json(out)
        return
    typer.echo(f"wrote {out.path}")
    typer.echo("enable it with:")
    for command in out.enable:
        typer.echo(f"  {command}")


@service_app.command("uninstall")
def service_uninstall(as_json: JsonFlag = False) -> None:
    """Remove the unit file and print how to stop the running server."""
    from hypothex.remote.service import uninstall_service

    out, removed = uninstall_service(_home_path())
    if as_json:
        _print_json({**out.model_dump(mode="json"), "removed": removed})
        return
    typer.echo(f"removed {out.path}" if removed else f"no unit file at {out.path}")
    typer.echo("stop the running server with:")
    for command in out.disable:
        typer.echo(f"  {command}")


# hosts ----------------------------------------------------------------------------
@hosts_app.command("add")
def hosts_add(
    name: Annotated[str, typer.Argument(help="Host name: a-z, 0-9, - and _.")],
    ssh: Annotated[str | None, typer.Option("--ssh", help="Host alias in ~/.ssh/config.")] = None,
    url: Annotated[str | None, typer.Option("--url", help="URL of a running env server.")] = None,
    slurm: Annotated[bool, typer.Option("--slurm", help="A SLURM cluster (login node).")] = False,
    partition: Annotated[str | None, typer.Option(help="SLURM partition.")] = None,
    account: Annotated[str | None, typer.Option(help="SLURM account.")] = None,
    time_limit: Annotated[str, typer.Option("--time", help="SLURM time limit.")] = "02:00:00",
    gpus: Annotated[int, typer.Option("--gpus", help="SLURM GPUs per job.")] = 1,
    remote_home: Annotated[
        str, typer.Option("--remote-home", help="hx home on the host.")
    ] = "~/.hypothex",
    usd: Annotated[
        float | None, typer.Option("--usd-per-gpu-hour", help="Price, for cost.")
    ] = None,
    as_json: JsonFlag = False,
) -> None:
    """Add a host: for --ssh, install hx there and start its env server; the hub connects it."""
    from hypothex.mcp.server import LOCAL_HOST

    if (ssh is None) == (url is None):
        raise ConfigError("give exactly one of --ssh ALIAS or --url URL")
    if name == LOCAL_HOST or not re.fullmatch(HOST_NAME, name):
        raise ConfigError(f"host name {name!r} must match {HOST_NAME} and not be 'local'")
    if not slurm and (partition or account):
        raise ConfigError("--partition and --account need --slurm")
    c, hosts = _hosts()
    if name in hosts.environments:
        raise ConfigError(f"host {name} exists; remove it first with `hx hosts rm {name}`")
    try:
        spec = HostSpec(
            route="ssh" if ssh else "url",
            kind="slurm" if slurm else "ssh",
            ssh_alias=ssh,
            url=url,
            home=remote_home,
            usd_per_gpu_hour=usd,
            slurm=SlurmDefaults(partition=partition, account=account, time=time_limit, gpus=gpus)
            if slurm
            else None,
        )
    except ValidationError as exc:
        raise ConfigError(f"invalid host {name}: {exc.errors()[0]['msg']}") from exc
    server = _bootstrap(c, name, spec) if spec.route == "ssh" else None
    environments = {**hosts.environments, name: spec}
    save_hosts(c.layout, hosts.model_copy(update={"environments": environments}))
    state = _hub_try("POST", f"/api/v1/hosts/{name}/connect", {})
    if as_json:
        _print_json({"name": name, "host": spec, "server": server, "state": state})
        return
    typer.echo(f"added {name} to {environments_path(c.layout)}")
    if server is not None:
        typer.echo(f"{name}: hx {server.hx_version} on port {server.port}")
    typer.echo(
        f"hub: {state['state']}" if state else "the hub is not running; `hx serve` connects it"
    )


@hosts_app.command("list")
def hosts_list(as_json: JsonFlag = False) -> None:
    """List the hosts in environments.yaml (no hub needed)."""
    _, hosts = _hosts()
    rows: list[dict[str, Any]] = [
        {"name": n, **s.model_dump(mode="json")} for n, s in hosts.environments.items()
    ]
    if as_json:
        _print_json(rows)
        return
    _table(
        ["host", "kind", "route", "target", "home", "projects"],
        [
            [
                r["name"],
                r["kind"],
                r["route"],
                r["ssh_alias"] or r["url"],
                r["home"],
                ", ".join(f"{p}={path}" for p, path in r["projects"].items()) or None,
            ]
            for r in rows
        ],
    )


@hosts_app.command("status")
def hosts_status(
    name: Annotated[str | None, typer.Argument(help="One host (default: all).")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Live state from the hub: connection, GPUs, queue, SLURM jobs, cost today."""
    rows = _hub("GET", "/api/v1/hosts")
    if name is not None:
        rows = [r for r in rows if r["name"] == name]
        if not rows:
            raise ConfigError(f"unknown host {name}; see `hx hosts list`")
    if as_json:
        _print_json(rows)
        return
    _table(
        ["host", "kind", "state", "since", "gpus busy", "queue", "slurm p/r", "today", "message"],
        [_status_cells(r) for r in rows],
    )


@hosts_app.command("map")
def hosts_map(project: str, host: str, path: str, as_json: JsonFlag = False) -> None:
    """Say where PROJECT's checkout is on HOST (runs there use it)."""
    c, hosts = _hosts()
    spec = _known_host(hosts, host)
    try:
        updated = HostSpec.model_validate(
            {**spec.model_dump(), "projects": {**spec.projects, project: path}}
        )
    except ValidationError as exc:
        raise ConfigError(
            f"invalid mapping {project} -> {path} on {host}: {exc.errors()[0]['msg']}"
        ) from exc
    environments = {**hosts.environments, host: updated}
    save_hosts(c.layout, hosts.model_copy(update={"environments": environments}))
    _hub_try("POST", "/api/v1/hosts/reload", {})  # a running hub serves the new map at once
    _emit({"host": host, "project": project, "path": path}, as_json, f"{project} on {host}: {path}")


@hosts_app.command("rm")
def hosts_rm(name: str, as_json: JsonFlag = False) -> None:
    """Remove a host; its env server and runs keep going on the host."""
    c, hosts = _hosts()
    _known_host(hosts, name)
    environments = {n: s for n, s in hosts.environments.items() if n != name}
    save_hosts(c.layout, hosts.model_copy(update={"environments": environments}))
    # then tell a running hub: reload stops the host's supervisor and forgets it
    # (a disconnect first would only mark it disabled and keep it listed)
    _hub_try("POST", "/api/v1/hosts/reload", {})
    _emit({"removed": name}, as_json, f"removed {name}")


@hosts_app.command("upgrade")
def hosts_upgrade(name: str, as_json: JsonFlag = False) -> None:
    """Install this hx version on the host and restart its env server if needed."""
    from hypothex.mcp.server import ssh_target
    from hypothex.remote import bootstrap

    c, hosts = _hosts()
    spec = _known_host(hosts, name)
    if spec.route != "ssh":
        raise ConfigError(f"host {name} is reached by {spec.route}; upgrade hx on it by hand")
    target = ssh_target(spec)
    wheel = bootstrap.build_wheel(c.layout.home / "cache" / "wheels")
    bootstrap.install(target, spec.home, wheel)
    bootstrap.stop_server(target, spec.home)  # only a server hx started; an external one stays
    info = bootstrap.ensure_server(target, spec.home, kind=spec.kind)
    if info.hx_version != __version__:
        raise ConfigError(
            f"{name} still runs hx {info.hx_version} (pid {info.pid}); stop that server "
            f"(`hx service uninstall` or kill the pid) and run `hx hosts upgrade {name}` again"
        )
    state = _hub_try("POST", f"/api/v1/hosts/{name}/connect", {})
    _emit(
        {"name": name, "server": info, "state": state},
        as_json,
        f"{name}: hx {info.hx_version} on port {info.port}",
    )


@hosts_app.command("connect")
def hosts_connect(name: str, as_json: JsonFlag = False) -> None:
    """Ask the hub to (re)connect a host."""
    state = _hub("POST", f"/api/v1/hosts/{name}/connect", {})
    _emit(state, as_json, f"{name}: {state['state']}")


@hosts_app.command("disconnect")
def hosts_disconnect(name: str, as_json: JsonFlag = False) -> None:
    """Ask the hub to stop watching a host; its runs keep going."""
    state = _hub("POST", f"/api/v1/hosts/{name}/disconnect", {})
    _emit(state, as_json, f"{name}: {state['state']}")


@app.command()
def mcp() -> None:
    """Run the MCP server over stdio (for Claude Code, Codex, ...)."""
    from hypothex.mcp.server import build_server

    build_server(_state.home).run()


@app.command(hidden=True)
def demo(
    kinds: Annotated[
        list[str] | None,
        typer.Option("--kinds", help="Kinds to seed (repeat or comma-separate; default: all)."),
    ] = None,
    with_hosts: Annotated[
        bool,
        typer.Option(
            "--with-hosts",
            help="Also seed fake hosts (8-GPU SSH box, SLURM cluster), a queue, and a "
            "sweep; `hx serve` starts them.",
        ),
    ] = False,
    as_json: JsonFlag = False,
) -> None:
    """Seed demo projects and runs into an empty home (UI tests, docs screenshots)."""
    from hypothex.demo import DEMO_TASKS, seed_demo, seed_demo_hosts

    known = get_args(TaskKind)
    chosen = [k.strip() for item in kinds or [] for k in item.split(",") if k.strip()]
    unknown = sorted(set(chosen) - set(known))
    if unknown:
        raise ConfigError(f"unknown kind(s) {', '.join(unknown)}; choose from {', '.join(known)}")
    home = _home_path()
    # a project is the demo's only when its repo is under <home>/demo-repos/: a
    # name alone is not enough (the repo's own example is also "toy-classifier")
    demo_repos = home / "demo-repos"
    theirs = sorted(
        e.project
        for e in _ctx().store.list_projects()
        if not Path(e.repo).resolve().is_relative_to(demo_repos)
    )
    if theirs:
        raise ConfigError(
            f"{home} already has projects ({', '.join(theirs)}); seed the demo into an "
            "empty home instead: hx --home /tmp/hx-demo demo"
        )
    selected = cast("list[TaskKind]", chosen or list(known))
    if with_hosts and "training" not in selected:
        try:
            _ctx().store.load_project(DEMO_TASKS["training"][0])
        except StoreError as exc:
            raise ConfigError("--with-hosts needs the training demo; add --kinds training") from exc
    made: dict[str, Any] = dict(seed_demo(home, selected))
    text = "\n".join(f"{kind}: {ref}" for kind, ref in made.items())
    if with_hosts:
        made["hosts"] = seed_demo_hosts(home)
        text += "\nhosts: gpu1 (8 GPUs), cluster (SLURM); `hx serve` starts them"
    _emit(made, as_json, text)


def cli() -> None:
    """Console entry point: expected errors print cleanly (JSON with --json)."""
    try:
        app()
    except HypothexError as exc:
        issues = [to_jsonable(i) for i in getattr(exc, "issues", [])]
        if "--json" in sys.argv:
            payload: dict[str, Any] = {"error": str(exc), "type": type(exc).__name__}
            if issues:
                payload["issues"] = issues
            print(json.dumps(payload))
        else:
            print(f"error: {exc}", file=sys.stderr)
            for issue in issues:
                print(f"  {_issue_text(issue)}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    cli()
