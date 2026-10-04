"""Create runs and execute them with full capture."""

from __future__ import annotations

import contextlib
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
from hypothex.core.store import sum_usage
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


def _checkout(repo: Path, commit: str | None, diff: str | bytes | None, dest: Path) -> Path | None:
    """
    Make the working copy a request pins with ``commit`` and/or ``diff`` (spec 8A.4).

    Parameters
    ----------
    repo : Path
        The project repo on this host.
    commit : str or None
        Commit to run (full or abbreviated sha); None means the repo's HEAD.
    diff : str, bytes, or None
        Uncommitted changes to apply on top of ``commit``; empty or None means none.
    dest : Path
        Where to create the worktree when one is needed.

    Returns
    -------
    Path or None
        The new worktree, or None when the repo already is at ``commit``
        with exactly ``diff`` (or nothing was pinned).

    Raises
    ------
    RunError
        Not a git repo, commit missing even after ``git fetch``, or the diff
        does not apply (the half-made worktree is removed).
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
    try:
        return create_worktree(repo, resolved, dest, patch)
    except GitError as exc:
        _discard_worktree(repo, dest)
        raise RunError(str(exc)) from exc


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
    ``req.diff`` (spec 8A.4) the run's code is checked out first: in place when
    the repo already is at that commit with that diff, else in a worktree at
    ``<store>/<project>/worktrees/<run_id>``. Everything else is then read from
    that checkout: ``hypothex.yaml`` (tasks, stages, datasets), ``{repo}`` and
    ``{dataset.path}``, the working directory, git info, and the environment.

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
    for _ in range(RUN_ID_ATTEMPTS):
        run_id = new_run_id(req.task)
        dest = ctx.layout.worktrees_dir(host_config.project) / run_id
        if ctx.layout.run_dir(host_config.project, run_id).exists() or dest.exists():
            continue  # taken already: draw another id before any work
        worktree = _checkout(repo, req.commit, req.diff, dest)
        try:
            return _prepare_in(ctx, req, repo, host_config, worktree, run_id)
        except _RunIdTakenError:
            pass  # another launcher created the same id meanwhile: retry with a new one
        except BaseException:
            # any failure after the worktree exists removes it (spec 8A.4)
            if worktree is not None:
                _discard_worktree(repo, worktree)
            raise
        if worktree is not None:
            _discard_worktree(repo, worktree)
    raise RunError(f"could not pick a free run id in {RUN_ID_ATTEMPTS} tries")


def _prepare_in(
    ctx: Context,
    req: RunRequest,
    repo: Path,
    host_config: ProjectConfig,
    worktree: Path | None,
    run_id: str,
) -> RunRecord:
    """
    Create the run from its checkout: ``worktree`` when there is one, else ``repo``.

    ``repo`` is the host checkout and ``host_config`` its ``hypothex.yaml``:
    they name the project and are what is registered for it, so a run pinned
    to an older commit never changes the project's stored tasks. Config,
    commands, datasets, and captures of the run use the checkout.
    """
    src = worktree or repo
    config = load_project_config(worktree) if worktree is not None else host_config
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
    if worktree is not None:
        cwd = worktree / (cwd.relative_to(repo) if cwd.is_relative_to(repo) else Path())
        if not cwd.is_dir():
            raise RunError(f"working directory {cwd} does not exist at the pinned commit")
    elif not cwd.is_dir():
        raise RunError(f"working directory {cwd} does not exist")
    run_dir = ctx.layout.run_dir(config.project, run_id)
    values = {"run_id": run_id, "run_dir": str(run_dir), "repo": str(src), "task": req.task or ""}
    if req.seed is not None:
        values["seed"] = str(req.seed)
    if req.config_path is not None:
        values["config"] = str(run_dir / "config.yaml")
    task_spec = config.tasks.get(req.task) if req.task else None
    if task_spec is not None:
        ds = config.datasets[task_spec.dataset]
        values.update(
            {
                "dataset.name": task_spec.dataset,
                "dataset.version": ds.version,
                "dataset.path": str(resolve_dataset_path(src, ds.path_for(task_spec.split))),
            }
        )
    values.update(req.vars)
    try:
        argv = [render_template(part, values) for part in template]
    except TemplateError as exc:
        raise RunError(str(exc)) from exc
    if not _executable_exists(argv[0], cwd):
        raise RunError(f"command not found: {argv[0]}")

    entry = ctx.store.register_project(host_config, repo)
    ctx.index.upsert_project(entry)
    datasets = []
    if task_spec is not None:
        cache = FingerprintCache(ctx.layout.dataset_cache)
        datasets.append(
            dataset_ref(
                task_spec.dataset,
                config.datasets[task_spec.dataset],
                task_spec.split,
                src,
                cache,
                ctx.descriptor.label,
            )
        )
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
        git=git_info(cwd),
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
    if user_config is not None:
        write_yaml(run_dir / "config.yaml", user_config)
    diff = capture_diff(cwd)
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
    src: IO[bytes] | None, log_path: Path, sink: BinaryIO | None, stop: threading.Event
) -> threading.Thread:
    """
    Copy a pipe to a log file (and ``sink``) until EOF or until ``stop`` is set.

    ``stop`` lets the run end when a process the command left behind still
    holds the pipe open, so EOF never comes.
    """

    def run() -> None:
        if src is None:
            return
        out = sink
        fd = src.fileno()
        # a selector (poll/epoll/kqueue), not select(): that fails for fds >= 1024
        with selectors.DefaultSelector() as sel, log_path.open("ab") as fh:
            sel.register(fd, selectors.EVENT_READ)
            while not stop.is_set():
                if not sel.select(0.1):
                    continue
                chunk = os.read(fd, 65536)
                if not chunk:
                    return
                fh.write(chunk)
                fh.flush()
                if out is not None:
                    try:
                        out.write(chunk)
                        out.flush()
                    except (OSError, ValueError):
                        out = None

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
    run logged also becomes a ``run.warning``, never a run stuck ``running``.

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

    The worktree is kept when it holds anything the run may have made: an
    untracked or ignored file (other than Python bytecode caches), or tracked
    changes other than the diff the run started with (``git.diff``), and when
    the project is now a copy from a host (``Context.local_repo``): git never
    runs in the repo path a host reported.

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
    tree = run_checkout(ctx, record)
    if tree is None:
        return False
    run_dir = ctx.run_dir(record)
    if (run_dir / "git.diff.too_large").exists():
        return False
    saved = run_dir / "git.diff"
    try:
        repo = ctx.local_repo(record.project)  # never a host's copy: keep the tree then
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
            if code in (b"??", b"!!") and not _bytecode(path):
                return False
        _discard_worktree(repo, tree)
    except (OSError, HypothexError):
        return False
    return True


def _bytecode(path: bytes) -> bool:
    """True for a Python bytecode cache file, which a run may always leave behind."""
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
        pumps = [
            _pump(proc.stdout, run_dir / "logs" / "stdout.log", stdout_sink, stop_pumps),
            _pump(proc.stderr, run_dir / "logs" / "stderr.log", stderr_sink, stop_pumps),
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
        try:
            evaluate_run(ctx, run_id)
        except HypothexError as exc:  # the run itself finished; scoring can be retried
            ctx.emit("run.eval_skipped", final, {"reason": str(exc)[:500]})
        except Exception as exc:  # noqa: BLE001 - e.g. a malformed worker result
            reason = f"{type(exc).__name__}: {exc}"
            ctx.emit("run.eval_skipped", final, {"reason": reason[:500]})
    return ctx.find_record(run_id)


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
