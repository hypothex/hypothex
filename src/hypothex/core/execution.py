"""Create runs and execute them with full capture."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, BinaryIO

import psutil

from hypothex.core.config import (
    BUILTIN_TEMPLATE_VARS,
    ProjectConfig,
    load_project_config,
    render_template,
)
from hypothex.core.context import Context
from hypothex.core.cost import compute_cost
from hypothex.core.datasets import FingerprintCache, dataset_ref, resolve_dataset_path
from hypothex.core.envcapture import capture_env
from hypothex.core.errors import GitError, HypothexError, RunError, StoreError, TemplateError
from hypothex.core.evalrunner import default_python_cmd
from hypothex.core.evaluation import evaluate_run, run_checkout
from hypothex.core.fsutil import atomic_write_bytes, atomic_write_text, read_yaml, write_yaml
from hypothex.core.gitinfo import capture_diff, create_worktree, git_info, head_commit
from hypothex.core.gpus import query_gpus
from hypothex.core.ids import new_run_id, utcnow
from hypothex.core.layout import HX_DIR
from hypothex.core.records import (
    TERMINAL_STATUSES,
    Artifact,
    ExecutorInfo,
    RunKind,
    RunRecord,
    RunStatus,
    UsageTotals,
)
from hypothex.core.seeds import config_hash, run_fingerprint
from hypothex.core.store import dir_lock, sum_usage
from hypothex.remote.config import SlurmDefaults

STOP_MARKER = "stop_requested"
TERM_GRACE_SECONDS = 10.0
STOP_POLL_SECONDS = 0.5
"""How often a supervisor checks the stop marker while its child runs."""
SUPERVISOR_PID_FILE = "supervisor.pid"
QUEUE_FILE = "queue.json"
GIT_FETCH_TIMEOUT_SECONDS = 120.0
COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{4,40}$")
"""A pinned commit is a full or abbreviated hex sha; nothing else reaches ``git``."""
EXECUTION_CLAIM = "execution.claim"
GATE_EXIT = 97
GATE_ARGV = ("sh", "-c", 'IFS= read -r _ || exit 97; exec "$@"', "hx-gate")
"""Run commands behind this gate: they start only after the supervisor writes ``go``."""
PUMP_DRAIN_SECONDS = 5.0
"""After the command exits, how long its output may still flow before the run ends.

A process the command left running in the background (``cmd &``, a daemon) keeps
the output pipes open; past this the run is recorded anyway (``run.warning``)."""
PROVIDED_TEMPLATE_VARS = BUILTIN_TEMPLATE_VARS - {"checkpoint"}
"""Template values Hypothex fills in itself; ``--var`` cannot set them."""
RUN_ID_ATTEMPTS = 8
"""How many fresh run ids ``prepare_run`` draws before it gives up (ids clash very rarely)."""
STAGING_DIR = "staging"
"""Per project: checkouts that queued pinned runs are prepared from (spec 8A.4)."""
CHECKOUT_FILE = "checkout.json"
CHECKOUT_DIFF = "checkout.diff"
"""In a pinned run's ``.hx/``: the repo, commit, and diff of the worktree it starts in."""


class _RunIdTakenError(Exception):
    """``ctx.create_run`` found a run folder with the new id; it wrote nothing."""


@dataclass
class RunRequest:
    """
    Everything needed to create a run.

    ``command`` is an argv template that may contain ``{vars}``; if it is None
    the ``stage`` template from ``hypothex.yaml`` is used.

    ``gpus`` is how many GPUs the run needs on this host. ``queue`` puts the
    run in this host's GPU queue instead of starting it now (spec 8A.5).
    ``slurm`` holds ``sbatch`` settings; a request with it is submitted to
    SLURM (``control.launch_run``), and SLURM's queue holds it.
    ``commit`` pins the commit to run and ``diff`` is uncommitted changes to
    apply on top of it (``git diff HEAD --binary``: text from the hub, raw bytes
    from a rerun's ``git.diff``); when the repo is not already at exactly that
    state the run uses a git worktree (spec 8A.4).
    """

    repo: Path
    command: list[str] | None = None
    stage: str | None = None
    task: str | None = None
    hypothesis: str = ""
    seed: int | None = None
    tags: list[str] = field(default_factory=list)
    config_path: Path | None = None
    params: dict[str, str] = field(default_factory=dict)
    vars: dict[str, str] = field(default_factory=dict)
    kind: RunKind = RunKind.FULL
    parent: str | None = None
    cwd: Path | None = None
    created_by: str = "human"
    gpus: int = 0
    queue: bool = False
    slurm: SlurmDefaults | None = None
    commit: str | None = None
    diff: str | bytes | None = None


def process_create_time(pid: int) -> float | None:
    """Return a process's start time, or None if it does not exist."""
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


def process_alive(pid: int | None, create_time: float | None) -> bool:
    """
    Return True if ``pid`` is running (not a zombie) and matches ``create_time``.

    Parameters
    ----------
    pid : int or None
    create_time : float or None
        Expected start time; guards against pid reuse. None skips the check.
    """
    if pid is None:
        return False
    try:
        proc = psutil.Process(pid)
        if create_time is not None and abs(proc.create_time() - create_time) > 1.0:
            return False
        return proc.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def _signal_group(pid: int, sig: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)


def terminate_group(pid: int, grace: float = TERM_GRACE_SECONDS) -> None:
    """Send SIGTERM to a process group, then SIGKILL after ``grace`` seconds."""
    _signal_group(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not process_alive(pid, None):
            return
        time.sleep(0.1)
    _signal_group(pid, signal.SIGKILL)


def _executable_exists(argv0: str, cwd: Path) -> bool:
    if os.sep in argv0:
        path = Path(argv0)
        path = path if path.is_absolute() else cwd / path
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(argv0) is not None


def seed_warning(template: list[str], seed: int | None) -> str | None:
    """
    Warn when ``--seed`` is set but the command template never uses it.

    A run started with ``--seed N`` but no ``{seed}`` anywhere in its command
    template silently drops the seed from the child's argv — a shell that
    swallows a bare ``{seed}`` word (unquoted, so it looks like an empty
    match) is a common cause. The child can still read ``$HYPOTHEX_SEED`` or
    call ``hx.seed()``, so this is a warning, not a blocking error.

    Parameters
    ----------
    template : list of str
        The command template before rendering (``record.command_template``).
    seed : int or None
        ``req.seed`` / ``record.seed``.

    Returns
    -------
    str or None
        A warning message, or None if the seed is unset or already wired in.

    Examples
    --------
    >>> seed_warning(["python", "train.py", "--seed", "{seed}"], 3) is None
    True
    >>> seed_warning(["python", "train.py", "--seed"], 3) is not None
    True
    >>> seed_warning(["python", "train.py"], None) is None
    True
    """
    if seed is None:
        return None
    if any("{seed}" in part for part in template):
        return None
    return (
        f"--seed {seed} is not passed to the command; put {{seed}} in it "
        "(quote it: '{seed}') or read hx.seed() / $HYPOTHEX_SEED"
    )


def _resolve_commit(repo: Path, commit: str) -> str | None:
    """Return the full sha of ``commit`` in ``repo``, or None if it is not there."""
    if not COMMIT_PATTERN.fullmatch(commit):
        raise RunError(f"commit {commit[:40]!r} is not a hex sha (4 to 40 hex characters)")
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else None


def _fetch(repo: Path) -> str:
    """Run ``git fetch --all`` in ``repo``; return its error text ("" on success)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "fetch", "--quiet", "--all"],
            capture_output=True,
            text=True,
            timeout=GIT_FETCH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return f"git fetch timed out after {GIT_FETCH_TIMEOUT_SECONDS:.0f}s"
    return out.stderr.strip() if out.returncode != 0 else ""


def _discard_worktree(repo: Path, path: Path) -> None:
    """Remove a worktree made for a run that was never created."""
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(path)], capture_output=True
    )
    shutil.rmtree(path, ignore_errors=True)
    subprocess.run(["git", "-C", str(repo), "worktree", "prune"], capture_output=True)


@dataclass(frozen=True)
class _Pin:
    """The code a pinned run executes: a resolved commit and the diff applied on top."""

    commit: str
    patch: bytes | None

    @property
    def key(self) -> str:
        """Name of the shared staging checkout of this commit and diff."""
        return f"{self.commit}-{hashlib.sha256(self.patch or b'').hexdigest()[:16]}"


def _pin(repo: Path, commit: str | None, diff: str | bytes | None) -> _Pin | None:
    """
    Resolve the code a request pins with ``commit`` and/or ``diff`` (spec 8A.4).

    Parameters
    ----------
    repo : Path
        The project repo on this host.
    commit : str or None
        Commit to run (full or abbreviated sha); None means the repo's HEAD.
    diff : str, bytes, or None
        Uncommitted changes to apply on top of ``commit``; empty or None means none.

    Returns
    -------
    _Pin or None
        The full sha and the diff, or None when the repo already is at
        ``commit`` with exactly ``diff`` (or nothing was pinned): the run
        then needs no worktree.

    Raises
    ------
    RunError
        Not a git repo, or the commit is missing even after ``git fetch``.
    """
    if commit is None and diff is None:
        return None
    head = head_commit(repo)
    if head is None:
        raise RunError(
            f"{repo} is not a git repository with a commit; "
            "pinning a commit or sending a diff needs git"
        )
    wanted = commit or head
    resolved = _resolve_commit(repo, wanted)
    if resolved is None:
        fetch_error = _fetch(repo)
        resolved = _resolve_commit(repo, wanted)
        if resolved is None:
            detail = f" ({fetch_error})" if fetch_error else ""
            raise RunError(
                f"commit {wanted[:12]} is not in {repo}, even after `git fetch`{detail}; "
                "push it to a remote this host can fetch"
            )
    patch = (diff if isinstance(diff, bytes) else diff.encode("utf-8")) if diff else None
    if head == resolved and capture_diff(repo).diff == patch:
        return None
    return _Pin(resolved, patch)


def _staging_root(ctx: Context, project: str) -> Path:
    """The folder of a project's staging checkouts (``<store>/<project>/staging``)."""
    return ctx.layout.project_dir(project) / STAGING_DIR


def _join_staging(ctx: Context, project: str, repo: Path, pin: _Pin, run_id: str) -> Path:
    """
    Return the shared staging checkout of ``pin``, made once; ``run_id`` now uses it.

    Pinned runs are prepared (config, captures, fingerprints) from this
    checkout. It stays while a queued run uses it, so a sweep of N queued runs
    makes one checkout at launch, not N (``_leave_staging``).

    Raises
    ------
    RunError
        The commit is missing or the diff does not apply (nothing is left behind).
    """
    root = _staging_root(ctx, project)
    tree, ready = root / pin.key, root / f"{pin.key}.ready"
    with dir_lock(root):
        if not ready.is_file():  # none yet, or a creator died half-way
            _discard_worktree(repo, tree)
            try:
                create_worktree(repo, pin.commit, tree, pin.patch)
            except GitError as exc:
                _discard_worktree(repo, tree)
                raise RunError(str(exc)) from exc
            ready.touch()
        users = root / f"{pin.key}.users"
        users.mkdir(exist_ok=True)
        (users / run_id).touch()
    return tree


def _leave_staging(ctx: Context, project: str, repo: Path, key: str, run_id: str) -> None:
    """Stop ``run_id`` using a staging checkout; the last user removes it."""
    root = _staging_root(ctx, project)
    users = root / f"{key}.users"
    if not (users / run_id).exists():
        return  # left already (no lock: a SLURM compute node gets here too)
    with dir_lock(root):
        if not (users / run_id).exists():
            return  # another release of this run came first
        (users / run_id).unlink()
        if any(users.iterdir()):
            return
        users.rmdir()
        (root / f"{key}.ready").unlink(missing_ok=True)
        _discard_worktree(repo, root / key)


def _leave_staging_of(ctx: Context, record: RunRecord) -> None:
    """Release the staging checkout a pinned run was prepared from, if it still uses one."""
    info_file = ctx.run_dir(record) / HX_DIR / CHECKOUT_FILE
    if info_file.is_file():
        info = json.loads(info_file.read_text(encoding="utf-8"))
        _leave_staging(ctx, record.project, Path(info["repo"]), info["staging"], record.run_id)


def checkout_run_tree(ctx: Context, record: RunRecord) -> Path | None:
    """
    Make the git worktree a pinned run executes in, when it starts (spec 8A.4).

    A pinned run is prepared from a shared staging checkout; its own worktree
    at ``<store>/<project>/worktrees/<run_id>`` (its recorded ``cwd`` and
    ``{repo}``) is made only now, from ``.hx/checkout.json`` and
    ``.hx/checkout.diff``, so queued runs hold no checkout. Execution trees are
    never shared. The run then stops using the staging checkout.

    Parameters
    ----------
    ctx : Context
    record : RunRecord
        A run about to start.

    Returns
    -------
    Path or None
        The run's worktree, or None for a run that is not pinned.

    Raises
    ------
    RunError
        The commit is gone or the diff no longer applies (nothing is left behind).

    Examples
    --------
    >>> checkout_run_tree(ctx, ctx.find_record(run_id))  # doctest: +SKIP
    PosixPath('/home/me/.hypothex/store/toy/worktrees/20261003-101500-toy-acc-1a2b')
    """
    run_dir = ctx.run_dir(record)
    info_file = run_dir / HX_DIR / CHECKOUT_FILE
    if not info_file.is_file():
        return None
    info = json.loads(info_file.read_text(encoding="utf-8"))
    repo = Path(info["repo"])
    tree = ctx.layout.worktrees_dir(record.project) / record.run_id
    if not tree.is_dir():
        diff_file = run_dir / HX_DIR / CHECKOUT_DIFF
        patch = diff_file.read_bytes() if diff_file.is_file() else None
        try:
            create_worktree(repo, info["commit"], tree, patch)
        except GitError as exc:
            _discard_worktree(repo, tree)
            raise RunError(f"could not check out the run's code: {exc}") from exc
    _leave_staging(ctx, record.project, repo, info["staging"], record.run_id)
    return tree


def _write_pin(run_dir: Path, repo: Path, pin: _Pin) -> None:
    """Record in ``.hx/`` what ``checkout_run_tree`` checks out when the run starts."""
    hx = run_dir / HX_DIR
    hx.mkdir(exist_ok=True)
    if pin.patch:
        atomic_write_bytes(hx / CHECKOUT_DIFF, pin.patch)
    info = {"repo": str(repo), "commit": pin.commit, "staging": pin.key}
    atomic_write_text(hx / CHECKOUT_FILE, json.dumps(info))


def write_queue_marker(run_dir: Path) -> None:
    """
    Mark a queued run as waiting in this host's GPU queue.

    Parameters
    ----------
    run_dir : Path
        The run folder; ``queue.json`` records when the run joined the queue.
    """
    atomic_write_text(run_dir / QUEUE_FILE, json.dumps({"enqueued_at": utcnow().isoformat()}))


def spawn_supervisor(ctx: Context, record: RunRecord) -> int:
    """
    Start a detached supervisor process that executes a queued run.

    Writing ``supervisor.pid`` commits the start: the supervisor waits until
    that file names its own pid before it executes anything
    (``hypothex.core.supervisor``). If ``Popen`` or that write fails, the new
    process is killed and ``OSError`` is raised: nothing will run, so the
    caller may release the run's GPUs. An error after the commit (emitting
    ``run.launched``) is raised as it is, and the run counts as started.

    Parameters
    ----------
    ctx : Context
    record : RunRecord
        A run with status ``queued``.

    Returns
    -------
    int
        The supervisor's pid (also written to ``supervisor.pid``).

    Raises
    ------
    OSError
        The supervisor could not be started; nothing will execute the run.
    """
    run_dir = ctx.run_dir(record)
    with (run_dir / "logs" / "supervisor.log").open("ab") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "hypothex.core.supervisor",
                record.run_id,
                "--home",
                str(ctx.layout.home),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    try:
        atomic_write_text(
            run_dir / SUPERVISOR_PID_FILE,
            json.dumps({"pid": proc.pid, "create_time": process_create_time(proc.pid)}),
        )
    except BaseException:
        # not committed: the supervisor never claims a run whose pid file is not its own
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        raise
    ctx.emit("run.launched", record, {"supervisor_pid": proc.pid})
    return proc.pid


def _open_gate(proc: subprocess.Popen[bytes]) -> None:
    """
    Let a gated command start: write ``go`` to its stdin, then close the pipe.

    Called only after the run's ``child_pid`` is saved. If the supervisor dies
    before this, the pipe closes unwritten and the gate exits ``GATE_EXIT``
    without running the command.
    """
    assert proc.stdin is not None
    with contextlib.suppress(BrokenPipeError):  # the gate already died (killed by a stop)
        proc.stdin.write(b"go\n")
        proc.stdin.flush()
    with contextlib.suppress(BrokenPipeError):
        proc.stdin.close()


def prepare_run(ctx: Context, req: RunRequest) -> RunRecord:
    """
    Validate a request, create the run folder, and capture git/env/dataset state.

    Nothing is created when the request is invalid. With ``req.commit`` or
    ``req.diff`` (spec 8A.4) the run executes in place when the repo already is
    at that commit with that diff, else in its own worktree at
    ``<store>/<project>/worktrees/<run_id>``: its ``cwd``, ``{repo}``, and
    ``{dataset.path}`` point there. That worktree is made only when the run
    starts (``checkout_run_tree``); until then the run is prepared from a
    staging checkout of the same commit and diff, shared by all queued runs
    that pin them (``<store>/<project>/staging``). ``hypothex.yaml`` (tasks,
    stages, datasets), the working directory, git info, and the environment
    are read from that checkout.

    The run id is drawn again when its run folder or worktree already exists,
    also when another launcher creates the same id while this one prepares
    (``RUN_ID_ATTEMPTS`` tries).

    Parameters
    ----------
    ctx : Context
    req : RunRequest

    Returns
    -------
    RunRecord
        The new run with status ``queued``.

    Raises
    ------
    RunError
        Unknown task/stage, missing template value, a ``--var`` that sets a
        value Hypothex provides (``run_dir``, ``repo``, ...), a working
        directory that does not exist, command not found, an agent run
        without a hypothesis, more GPUs than this host has, a pinned
        commit/diff that cannot be checked out (spec 8A.4), or no free run id.
    """
    repo = req.repo.resolve()
    host_config = load_project_config(repo)  # the host checkout names the project
    if os.environ.get("HYPOTHEX_AGENT") and not req.hypothesis.strip():
        raise RunError("agents must give a hypothesis (--hypothesis): why does this run exist?")
    provided = sorted(set(req.vars) & PROVIDED_TEMPLATE_VARS)
    if provided:
        raise RunError(
            f"--var {provided[0]} is set by Hypothex and cannot be overridden "
            f"(Hypothex sets: {', '.join(sorted(PROVIDED_TEMPLATE_VARS))})"
        )
    if req.config_path is not None and not req.config_path.is_file():
        raise RunError(f"config file not found: {req.config_path}")
    if req.gpus < 0:
        raise RunError(f"gpus must be 0 or more, got {req.gpus}")
    if req.gpus > 0 and req.slurm is None:  # SLURM allocates GPUs on the compute node
        total = len(query_gpus())
        if req.gpus > total:
            raise RunError(f"asked for {req.gpus} GPUs; this host has {total}")
    project = host_config.project
    pin = _pin(repo, req.commit, req.diff)
    for _ in range(RUN_ID_ATTEMPTS):
        run_id = new_run_id(req.task)
        dest = ctx.layout.worktrees_dir(project) / run_id
        if ctx.layout.run_dir(project, run_id).exists() or dest.exists():
            continue  # taken already: draw another id before any work
        staging = _join_staging(ctx, project, repo, pin, run_id) if pin is not None else None
        try:
            return _prepare_in(ctx, req, repo, host_config, pin, staging, run_id)
        except _RunIdTakenError:
            pass  # another launcher created the same id meanwhile: retry with a new one
        except BaseException:
            # a failed run leaves the staging checkout: its last user removes it (spec 8A.4)
            if pin is not None:
                _leave_staging(ctx, project, repo, pin.key, run_id)
            raise
        if pin is not None:
            _leave_staging(ctx, project, repo, pin.key, run_id)
    raise RunError(f"could not pick a free run id in {RUN_ID_ATTEMPTS} tries")


def _reroot(path: str, old: Path, new: Path) -> str:
    """
    Move an absolute path under ``old`` to the same place under ``new``.

    Examples
    --------
    >>> _reroot("/wt/run-1/train.py", Path("/wt/run-1"), Path("/staging/abc"))
    '/staging/abc/train.py'
    >>> _reroot("python", Path("/wt/run-1"), Path("/staging/abc"))
    'python'
    """
    p = Path(path)
    return str(new / p.relative_to(old)) if p.is_absolute() and p.is_relative_to(old) else path


def dataset_base(checkout: Path, repo: Path, raw: str) -> Path:
    """
    Pick the folder a run's relative dataset path resolves in.

    A pinned run's checkout (a git worktree, spec 8A.4) holds only tracked
    files. Data that git ignores lives only in the project repo, so the
    checkout is used only when the dataset is there.

    Parameters
    ----------
    checkout : Path
        Where the run's code is checked out (the repo itself or a worktree).
    repo : Path
        The project repo on this host.
    raw : str
        The dataset path from ``hypothex.yaml`` (relative or absolute).

    Returns
    -------
    Path
        ``checkout`` when the dataset exists there, else ``repo``.

    Examples
    --------
    >>> dataset_base(Path("/no/such/worktree"), Path("/repo"), "data/test.jsonl")
    PosixPath('/repo')
    """
    return checkout if resolve_dataset_path(checkout, raw).exists() else repo


def _prepare_in(
    ctx: Context,
    req: RunRequest,
    repo: Path,
    host_config: ProjectConfig,
    pin: _Pin | None,
    staging: Path | None,
    run_id: str,
) -> RunRecord:
    """
    Create the run from its checkout: ``staging`` when it is pinned, else ``repo``.

    ``repo`` is the host checkout and ``host_config`` its ``hypothex.yaml``:
    they name the project and are what is registered for it, so a run pinned
    to an older commit never changes the project's stored tasks. Config,
    commands, and captures of the run read the checkout; a relative dataset
    path uses it only when the dataset is there (``dataset_base``). The paths
    a pinned run records (``cwd``, ``{repo}``, ``{dataset.path}``) name its own
    worktree, which ``checkout_run_tree`` makes when it starts.
    """
    src = staging or repo  # read now
    run_root = repo if staging is None else ctx.layout.worktrees_dir(host_config.project) / run_id
    config = load_project_config(staging) if staging is not None else host_config
    project = host_config.project
    if config.project != project:
        raise RunError(
            f"the pinned commit's hypothex.yaml names project {config.project!r}, not {project!r}"
        )
    if req.task is not None and req.task not in config.tasks:
        raise RunError(f"unknown task {req.task!r}; known tasks: {sorted(config.tasks)}")
    if req.command is None:
        if req.stage is None:
            raise RunError("give a command or a stage")
        if req.stage not in config.stages:
            raise RunError(
                f"project has no stage {req.stage!r}; known stages: {sorted(config.stages)}"
            )
        template = shlex.split(config.stages[req.stage])
    else:
        template = list(req.command)
    if not template:
        raise RunError("empty command")
    user_config = read_yaml(req.config_path) if req.config_path is not None else None

    cwd = (req.cwd or repo).resolve()
    read_cwd = cwd
    if staging is not None:
        relative = cwd.relative_to(repo) if cwd.is_relative_to(repo) else Path()
        read_cwd, cwd = staging / relative, run_root / relative
        if not read_cwd.is_dir():
            raise RunError(f"working directory {cwd} does not exist at the pinned commit")
    elif not cwd.is_dir():
        raise RunError(f"working directory {cwd} does not exist")
    run_dir = ctx.layout.run_dir(config.project, run_id)
    values = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "repo": str(run_root),
        "task": req.task or "",
    }
    if req.seed is not None:
        values["seed"] = str(req.seed)
    if req.config_path is not None:
        values["config"] = str(run_dir / "config.yaml")
    task_spec = config.tasks.get(req.task) if req.task else None
    ds_read = ds_base = src
    if task_spec is not None:
        ds = config.datasets[task_spec.dataset]
        ds_read = dataset_base(src, repo, ds.path_for(task_spec.split))
        ds_base = run_root if ds_read == src else repo  # the checkout's copy, where it runs
        values.update(
            {
                "dataset.name": task_spec.dataset,
                "dataset.version": ds.version,
                "dataset.path": str(resolve_dataset_path(ds_base, ds.path_for(task_spec.split))),
            }
        )
    values.update(req.vars)
    try:
        argv = [render_template(part, values) for part in template]
    except TemplateError as exc:
        raise RunError(str(exc)) from exc
    if not _executable_exists(_reroot(argv[0], run_root, src), read_cwd):
        raise RunError(f"command not found: {argv[0]}")

    entry = ctx.store.register_project(host_config, repo)
    ctx.index.upsert_project(entry)
    datasets = []
    if task_spec is not None:
        cache = FingerprintCache(ctx.layout.dataset_cache)
        ref = dataset_ref(
            task_spec.dataset,
            config.datasets[task_spec.dataset],
            task_spec.split,
            ds_read,
            cache,
            ctx.descriptor.label,
        )
        if ref.hash_mode != "remote-unchecked":  # the same file, where the run will read it
            ref = ref.model_copy(update={"path": _reroot(ref.path, src, run_root)})
        datasets.append(ref)
    fingerprint = run_fingerprint(
        command_template=template,
        stage=req.stage,
        user_config=user_config,
        params=req.params,
        vars=req.vars,
    )
    record = RunRecord(
        run_id=run_id,
        project=config.project,
        task=req.task,
        hypothesis=req.hypothesis.strip(),
        kind=req.kind,
        parent=req.parent,
        stage=req.stage,
        command=argv,
        command_template=template,
        vars=dict(req.vars),
        params=dict(req.params),
        cwd=str(cwd),
        environment_id=ctx.descriptor.environment_id,
        host=ctx.descriptor.label,
        executor=ExecutorInfo(
            pid=os.getpid(),
            pid_create_time=process_create_time(os.getpid()),
            host=ctx.descriptor.label,
        ),
        git=git_info(read_cwd),
        datasets=datasets,
        seed=req.seed,
        config_hash=config_hash(fingerprint),
        status=RunStatus.QUEUED,
        created_at=utcnow(),
        tags=sorted(set(req.tags)),
        created_by=req.created_by,
        gpus_requested=req.gpus,
    )
    try:
        ctx.create_run(record)
    except StoreError as exc:
        if isinstance(exc.__cause__, FileExistsError):  # the run folder exists: id clash
            raise _RunIdTakenError(run_id) from exc
        raise
    if pin is not None:
        _write_pin(run_dir, repo, pin)
    if user_config is not None:
        write_yaml(run_dir / "config.yaml", user_config)
    diff = capture_diff(read_cwd)
    if diff.diff:
        atomic_write_bytes(run_dir / "git.diff", diff.diff)
    if diff.stat:
        atomic_write_text(run_dir / "git.stat", diff.stat)
    if diff.too_large:
        atomic_write_text(run_dir / "git.diff.too_large", "diff larger than the capture limit\n")
    capture_env(src, run_dir / "env", default_python_cmd(src, config))
    warning = seed_warning(template, req.seed)
    if warning is not None:
        ctx.emit("run.warning", record, {"message": warning})
    return record


def _pump(
    src: IO[bytes] | None,
    log_path: Path,
    sink: BinaryIO | None,
    stop: threading.Event,
    failures: list[str],
) -> threading.Thread:
    """
    Copy a pipe to a log file (and ``sink``) until EOF or until ``stop`` is set.

    ``stop`` lets the run end when a process the command left behind still
    holds the pipe open, so EOF never comes. The pipe is read to the end even
    when the log cannot be written (a full disk): the bytes are dropped and the
    first error is appended to ``failures``, so the command never blocks on a
    full pipe.

    Parameters
    ----------
    src : binary file or None
        The child's stdout or stderr pipe; None does nothing.
    log_path : Path
        The log file, opened for append.
    sink : binary file or None
        Where to echo the output as well (a terminal); dropped once it fails.
    stop : threading.Event
        Set to stop reading before EOF.
    failures : list of str
        Gets ``"<log name>: <error>"`` when the log could not be opened or
        written; nothing more is written to that log.

    Returns
    -------
    threading.Thread
        The started daemon thread.
    """

    def run() -> None:
        if src is None:
            return
        out = sink
        fd = src.fileno()
        try:
            fh: BinaryIO | None = log_path.open("ab")
        except OSError as exc:
            failures.append(f"{log_path.name}: {exc}")
            fh = None
        try:
            # a selector (poll/epoll/kqueue), not select(): that fails for fds >= 1024
            with selectors.DefaultSelector() as sel:
                sel.register(fd, selectors.EVENT_READ)
                while not stop.is_set():
                    if not sel.select(0.1):
                        continue
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        return
                    if fh is not None:
                        try:
                            fh.write(chunk)
                            fh.flush()
                        except OSError as exc:  # keep draining: a full pipe blocks the child
                            failures.append(f"{log_path.name}: {exc}")
                            with contextlib.suppress(OSError):
                                fh.close()
                            fh = None
                    if out is not None:
                        try:
                            out.write(chunk)
                            out.flush()
                        except (OSError, ValueError):
                            out = None
        finally:
            if fh is not None:
                with contextlib.suppress(OSError):
                    fh.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _forward(pid: int) -> None:
    """SIGTERM the child group now and SIGKILL it after the grace period."""
    _signal_group(pid, signal.SIGTERM)
    timer = threading.Timer(TERM_GRACE_SECONDS, _signal_group, args=(pid, signal.SIGKILL))
    timer.daemon = True
    timer.start()


@dataclass
class _TermState:
    signalled: bool = False
    pid: int | None = None

    def attach(self, pid: int) -> None:
        """Record the child's pid; forward a signal that arrived before it started."""
        self.pid = pid
        if self.signalled:
            _forward(pid)


@contextmanager
def _forward_termination() -> Iterator[_TermState]:
    """
    Forward SIGTERM/SIGHUP to the child group (main thread only).

    Enter before starting the child so a signal is never missed; call
    ``attach`` with the child's pid once it exists.
    """
    state = _TermState()
    if threading.current_thread() is not threading.main_thread():
        yield state
        return

    def handler(signum: int, frame: object) -> None:
        state.signalled = True
        if state.pid is not None:
            _forward(state.pid)

    previous = {sig: signal.signal(sig, handler) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        yield state
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


def execute_run(
    ctx: Context,
    run_id: str,
    *,
    stdout_sink: BinaryIO | None = None,
    stderr_sink: BinaryIO | None = None,
    auto_evaluate: bool = True,
) -> RunRecord:
    """
    Execute a queued run in this process and record the outcome.

    Output is written to ``logs/`` and optionally echoed to sinks. Ctrl-C,
    SIGTERM, SIGHUP, or a stop request end the run as ``killed``. A finished
    task run with predictions is scored automatically. The executor fields set
    before start (``host``, ``gpus``, SLURM job and node) are kept, and the
    ended record carries ``cost`` (GPU hours and API spend; the hub adds the
    GPU price).

    The run ends when the command exits. Output still flowing from processes
    it left running is captured for ``PUMP_DRAIN_SECONDS`` more, then the run
    is recorded with a ``run.warning``. A failure to read or index what the
    run logged also becomes a ``run.warning``, never a run stuck ``running``,
    and so does a log file that cannot be written (a full disk): the output is
    still read, so the command never blocks, but it is dropped.

    After scoring, the git worktree the run executed in (spec 8A.4) is
    removed when the run left nothing in it (``release_worktree``).

    Parameters
    ----------
    ctx : Context
    run_id : str
    stdout_sink, stderr_sink : binary file, optional
        Where to echo the child's output.
    auto_evaluate : bool
        Score finished task runs, then remove the run's clean worktree. With
        False (a SLURM compute node) the caller scores the run and keeps the
        worktree until then.

    Returns
    -------
    RunRecord
        The final record.
    """
    final = _execute(ctx, run_id, stdout_sink, stderr_sink, auto_evaluate)
    if auto_evaluate and final.status in TERMINAL_STATUSES:
        release_worktree(ctx, final)
    return final


def release_worktree(ctx: Context, record: RunRecord) -> bool:
    """
    Remove the git worktree an ended run executed in, if the run left nothing there.

    A run that never started stops using its staging checkout here
    (``checkout_run_tree``). The worktree is kept when it holds anything the
    run may have made: an
    untracked or ignored file (other than Python bytecode caches and the
    top-level ``.venv/``, see ``_disposable``), or tracked changes other than
    the diff the run started with (``git.diff``).

    Parameters
    ----------
    ctx : Context
    record : RunRecord
        An ended run.

    Returns
    -------
    bool
        True if a worktree was removed.

    Examples
    --------
    >>> release_worktree(ctx, ctx.find_record(run_id))  # doctest: +SKIP
    True
    """
    _leave_staging_of(ctx, record)  # a run that never started still used one
    tree = run_checkout(ctx, record)
    if tree is None:
        return False
    run_dir = ctx.run_dir(record)
    if (run_dir / "git.diff.too_large").exists():
        return False
    saved = run_dir / "git.diff"
    try:
        if capture_diff(tree).diff != (saved.read_bytes() if saved.is_file() else None):
            return False
        status = subprocess.run(
            ["git", "-C", str(tree), "status", "--porcelain", "-z"]
            + ["--ignored", "--untracked-files=all"],
            capture_output=True,
        )
        if status.returncode != 0:
            return False
        for entry in status.stdout.split(b"\0"):
            code, path = entry[:2], entry[3:]
            if code[:1] in (b"R", b"C"):
                return False  # a staged rename: the run changed the tree
            if code in (b"??", b"!!") and not _disposable(path):
                return False
        _discard_worktree(Path(ctx.store.load_project(record.project).repo), tree)
    except (OSError, HypothexError):
        return False
    return True


def _disposable(path: bytes) -> bool:
    """
    True for a file a run may always leave in its worktree: it is rebuilt on demand.

    Python bytecode caches anywhere, and the project's virtual environment at
    the top of the tree (``.venv/``), which ``uv run --project <worktree>``
    creates when the environment is captured or the run is scored.

    Parameters
    ----------
    path : bytes
        A path from ``git status --porcelain -z``, relative to the tree root.

    Returns
    -------
    bool
        True when removing the worktree loses nothing the run made.

    Examples
    --------
    >>> _disposable(b".venv/bin/python"), _disposable(b"pkg/.venv/x")
    (True, False)
    """
    if path == b".venv" or path.startswith(b".venv/"):
        return True
    return b"__pycache__/" in path or path.endswith((b".pyc", b"__pycache__"))


def _execute(
    ctx: Context,
    run_id: str,
    stdout_sink: BinaryIO | None,
    stderr_sink: BinaryIO | None,
    auto_evaluate: bool,
) -> RunRecord:
    """Execute a queued run (``execute_run`` without the worktree cleanup)."""
    record = ctx.find_record(run_id)
    if record.status != RunStatus.QUEUED:
        raise RunError(f"run {run_id} is {record.status.value}, not queued")
    run_dir = ctx.run_dir(record)
    try:  # one execution per run, even when two supervisors were spawned for it
        os.close(os.open(run_dir / EXECUTION_CLAIM, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))
    except FileExistsError:
        raise RunError(f"run {run_id} is already being executed") from None
    # Keep what the scheduler or SLURM recorded (host, gpus, job id, node); the
    # run is no longer waiting, so it has no queue position.
    me = record.executor.model_copy(
        update={
            "pid": os.getpid(),
            "pid_create_time": process_create_time(os.getpid()),
            "child_pid": None,
            "queue_position": None,
        }
    )
    if (run_dir / STOP_MARKER).exists():
        return ctx.update_run(
            run_id,
            "run.killed",
            lambda r: r.model_copy(
                update={"status": RunStatus.KILLED, "ended_at": utcnow(), "executor": me}
            ),
            {"reason": "stopped before start"},
        )
    try:  # a pinned run's own worktree is made now, not while it waited (spec 8A.4)
        checkout_run_tree(ctx, record)
    except (RunError, OSError) as exc:
        (run_dir / "logs" / "stderr.log").write_text(f"hypothex: {exc}\n")
        return ctx.update_run(
            run_id,
            "run.failed",
            lambda r: r.model_copy(
                update={"status": RunStatus.FAILED, "ended_at": utcnow(), "executor": me}
            ),
            {"reason": str(exc)[:500]},
        )
    env = {
        **os.environ,
        "HYPOTHEX_RUN_DIR": str(run_dir),
        "HYPOTHEX_RUN_ID": record.run_id,
        "HYPOTHEX_PROJECT": record.project,
        "PYTHONUNBUFFERED": "1",
    }
    if record.seed is not None:
        env["HYPOTHEX_SEED"] = str(record.seed)
    if record.executor.gpus:
        env["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in record.executor.gpus)
    with _forward_termination() as term:
        try:
            proc = subprocess.Popen(
                [*GATE_ARGV, *record.command],  # waits for "go": nothing runs unowned
                cwd=record.cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            (run_dir / "logs" / "stderr.log").write_text(
                f"hypothex: could not start command: {exc}\n"
            )
            now = utcnow()
            return ctx.update_run(
                run_id,
                "run.failed",
                lambda r: r.model_copy(
                    update={
                        "status": RunStatus.FAILED,
                        "started_at": now,
                        "ended_at": now,
                        "exit_code": 127,
                        "executor": me,
                    }
                ),
                {"reason": str(exc)},
            )
        term.attach(proc.pid)

        started = me.model_copy(update={"child_pid": proc.pid})
        try:
            ctx.update_run(
                run_id,
                "run.started",
                lambda r: r.model_copy(
                    update={
                        "status": RunStatus.RUNNING,
                        "started_at": utcnow(),
                        "executor": started,
                    }
                ),
            )
        except BaseException:
            assert proc.stdin is not None
            proc.stdin.close()  # never opened: the gate exits without running the command
            proc.wait()
            raise
        _open_gate(proc)  # child_pid is saved: only now may the command run
        stop_pumps = threading.Event()
        log_failures: list[str] = []
        pumps = [
            _pump(
                proc.stdout, run_dir / "logs" / "stdout.log", stdout_sink, stop_pumps, log_failures
            ),
            _pump(
                proc.stderr, run_dir / "logs" / "stderr.log", stderr_sink, stop_pumps, log_failures
            ),
        ]
        interrupted = False
        try:
            exit_code = _wait_unless_stopped(proc, run_dir / STOP_MARKER)
        except KeyboardInterrupt:
            interrupted = True
            terminate_group(proc.pid)
            exit_code = proc.wait()
    if not _drain(pumps, stop_pumps, proc):
        ctx.emit(
            "run.warning",
            record,
            {
                "message": "the command exited but its output is still open (a process it "
                f"left running?); output after {PUMP_DRAIN_SECONDS:g}s is not captured"
            },
        )
    if log_failures:
        message = f"log write failed; later output was not saved ({'; '.join(log_failures)})"
        ctx.emit("run.warning", record, {"message": message[:500]})

    stopped = interrupted or term.signalled or (run_dir / STOP_MARKER).exists()
    if stopped:
        status = RunStatus.KILLED
    elif exit_code == 0:
        status = RunStatus.FINISHED
    else:
        status = RunStatus.FAILED
    logged: list[Artifact] = []
    usage: UsageTotals | None = None
    try:  # nothing the run logged may keep it from ending
        logged = ctx.store.read_artifacts(record.project, record.run_id)
        usage = sum_usage(ctx.store.read_usage(record.project, record.run_id))
        ctx.index.replace_metric_points(
            record.run_id, ctx.store.read_metric_points(record.project, record.run_id)
        )
    except Exception as exc:  # noqa: BLE001 - the run ends either way; the warning says why
        message = f"could not read or index what the run logged: {type(exc).__name__}: {exc}"
        ctx.emit("run.warning", record, {"message": message[:500]})

    def finish(r: RunRecord) -> RunRecord:
        # A path logged twice (e.g. an overwritten last.pt) keeps its latest step/metrics.
        merged = {(a.kind, a.path): a for a in [*r.artifacts, *logged]}
        done = r.model_copy(
            update={
                "status": status,
                "ended_at": utcnow(),
                "exit_code": exit_code,
                "artifacts": list(merged.values()),
                "usage": usage,
            }
        )
        # The price per GPU hour lives in the hub's environments.yaml; the hub
        # re-prices mirrored runs with cost.price_record.
        return done.model_copy(update={"cost": compute_cost(done, None)})

    final = ctx.update_run(run_id, f"run.{status.value}", finish, {"exit_code": exit_code})
    if auto_evaluate and status == RunStatus.FINISHED and final.task:
        score_finished_run(ctx, final)
    return ctx.find_record(run_id)


def score_finished_run(ctx: Context, record: RunRecord) -> None:
    """
    Score a finished task run once, right after it ended (auto-evaluation).

    The run itself finished, so scoring never fails it: an error becomes a
    ``run.eval_skipped`` event (scoring can be retried with ``hx reeval``),
    and each warning of the scoring (e.g. metric code changed without a
    version bump) becomes a ``run.warning`` event.

    Parameters
    ----------
    ctx : Context
    record : RunRecord
        A ``finished`` run with a task.

    Examples
    --------
    >>> score_finished_run(ctx, ctx.find_record(run_id))  # doctest: +SKIP
    """
    try:
        _, warnings = evaluate_run(ctx, record.run_id)
    except HypothexError as exc:
        ctx.emit("run.eval_skipped", record, {"reason": str(exc)[:500]})
        return
    except Exception as exc:  # noqa: BLE001 - e.g. a malformed worker result
        reason = f"{type(exc).__name__}: {exc}"
        ctx.emit("run.eval_skipped", record, {"reason": reason[:500]})
        return
    for warning in warnings:
        ctx.emit("run.warning", record, {"message": warning[:500]})


def _wait_unless_stopped(proc: subprocess.Popen[bytes], marker: Path) -> int:
    """
    Wait for ``proc``; terminate its group once ``marker`` appears.

    ``stop_run`` signals the child itself, but only if a record it read names
    the child. A stop whose reads all missed it (or a stop that died before it
    signalled) still ends the run here.

    Parameters
    ----------
    proc : subprocess.Popen
        The run's child, the leader of its own process group.
    marker : Path
        The run's stop marker.

    Returns
    -------
    int
        The child's exit code.
    """
    while True:
        if marker.exists():
            terminate_group(proc.pid)
            return proc.wait()
        try:
            return proc.wait(timeout=STOP_POLL_SECONDS)
        except subprocess.TimeoutExpired:
            pass


def _drain(
    pumps: list[threading.Thread], stop: threading.Event, proc: subprocess.Popen[bytes]
) -> bool:
    """
    Let the output pumps reach EOF for up to ``PUMP_DRAIN_SECONDS``, then stop them.

    Returns
    -------
    bool
        False when a pipe was still open at the deadline (a process the
        command left running holds it); its later output is not captured.
    """
    deadline = time.monotonic() + PUMP_DRAIN_SECONDS
    for pump in pumps:
        pump.join(max(0.0, deadline - time.monotonic()))
    drained = not any(pump.is_alive() for pump in pumps)
    stop.set()
    for pump in pumps:
        pump.join()
    for pipe in (proc.stdout, proc.stderr):
        if pipe is not None:
            pipe.close()
    return drained
