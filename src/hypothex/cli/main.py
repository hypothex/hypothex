"""The ``hx`` command-line interface. Every command supports ``--json``."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Annotated, Any, cast, get_args

import typer
import yaml

from hypothex._version import __version__
from hypothex.core import queries as q
from hypothex.core.config import (
    CONFIG_FILENAME,
    TaskKind,
    find_repo_root,
    parse_metric_version,
    starter_config,
)
from hypothex.core.context import Context
from hypothex.core.control import launch_run, reinfer, repair_runs, rerun, stop_run, wait_for_run
from hypothex.core.environment import load_descriptor
from hypothex.core.errors import ConfigError, HypothexError, RunError
from hypothex.core.evaluation import reeval, validate_project
from hypothex.core.execution import RunRequest, execute_run, prepare_run, seed_warning
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.gitinfo import git_state_label
from hypothex.core.index import rebuild_index
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.layout import Layout, default_home
from hypothex.core.records import TERMINAL_STATUSES, RunRecord, RunStatus

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
    wait: Annotated[bool, typer.Option(help="Block until the run ends.")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Start a run in the background (same options as `hx run`)."""
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
    record = launch_run(c, req)
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


@app.command("rerun")
def rerun_cmd(run_id: str, foreground: ForegroundOpt = False, as_json: JsonFlag = False) -> None:
    """Rerun with the same command, commit, config, and seed."""
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
    c = _ctx()
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
    record = stop_run(_ctx(), run_id)
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
    record = q.tag_run(_ctx(), run_id, add or [], remove or [])
    _emit(record, as_json, ", ".join(record.tags) or "(no tags)")


OffFlag = Annotated[bool, typer.Option("--off", help="Undo.")]


@app.command()
def star(run_id: str, off: OffFlag = False, as_json: JsonFlag = False) -> None:
    """Star (or --off unstar) a run."""
    record = q.star_run(_ctx(), run_id, on=not off)
    _emit(record, as_json, f"starred={record.starred}")


@app.command()
def archive(run_id: str, off: OffFlag = False, as_json: JsonFlag = False) -> None:
    """Archive (hide) or --off unarchive a run."""
    record = q.archive_run(_ctx(), run_id, on=not off)
    _emit(record, as_json, f"archived={record.archived}")


@app.command()
def note(
    run_id: str,
    text: str,
    author: Annotated[str | None, typer.Option(help="Author (default: human/agent).")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Add a note to a run."""
    q.add_note(_ctx(), run_id, text, author or _created_by())
    _emit({"ok": True}, as_json, "noted")


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

    out = put_view(_ctx(), task, name or file.stem, file.read_text(encoding="utf-8"), project)
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

    report = validate_view(_ctx(), task, file.read_text(encoding="utf-8"), project)
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


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port.")] = 7777,
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            help="Run as a host's env server: ssh (GPU queue) or slurm. Default: the saved kind.",
        ),
    ] = None,
) -> None:
    """Serve the HTTP/WebSocket API (and the UI when built)."""
    import uvicorn

    from hypothex.api.app import create_app

    home = (_state.home or default_home()).expanduser().resolve()
    resolved = resolve_serve_kind(home, kind)
    uvicorn.run(create_app(home, host=host, kind=resolved), host=host, port=port)


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
    as_json: JsonFlag = False,
) -> None:
    """Seed demo projects and runs into an empty home (UI tests, docs screenshots)."""
    from hypothex.demo import seed_demo

    known = get_args(TaskKind)
    chosen = [k.strip() for item in kinds or [] for k in item.split(",") if k.strip()]
    unknown = sorted(set(chosen) - set(known))
    if unknown:
        raise ConfigError(f"unknown kind(s) {', '.join(unknown)}; choose from {', '.join(known)}")
    home = (_state.home or default_home()).expanduser().resolve()
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
    made = seed_demo(home, cast("list[TaskKind]", chosen or list(known)))
    _emit(made, as_json, "\n".join(f"{kind}: {ref}" for kind, ref in made.items()))


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
