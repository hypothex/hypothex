"""Create runs and execute them with full capture."""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, BinaryIO

import psutil

from hypothex.core.config import load_project_config, render_template
from hypothex.core.context import Context
from hypothex.core.datasets import FingerprintCache, dataset_ref, resolve_dataset_path
from hypothex.core.envcapture import capture_env
from hypothex.core.errors import HypothexError, RunError, TemplateError
from hypothex.core.evalrunner import default_python_cmd
from hypothex.core.evaluation import evaluate_run
from hypothex.core.fsutil import atomic_write_bytes, atomic_write_text, read_yaml, write_yaml
from hypothex.core.gitinfo import capture_diff, git_info
from hypothex.core.ids import new_run_id, utcnow
from hypothex.core.records import ExecutorInfo, RunKind, RunRecord, RunStatus
from hypothex.core.seeds import config_hash, run_fingerprint
from hypothex.core.store import sum_usage

STOP_MARKER = "stop_requested"
TERM_GRACE_SECONDS = 10.0


@dataclass
class RunRequest:
    """
    Everything needed to create a run.

    ``command`` is an argv template that may contain ``{vars}``; if it is None
    the ``stage`` template from ``hypothex.yaml`` is used.
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


def prepare_run(ctx: Context, req: RunRequest) -> RunRecord:
    """
    Validate a request, create the run folder, and capture git/env/dataset state.

    Nothing is created when the request is invalid.

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
        Unknown task/stage, missing template value, command not found, or an
        agent run without a hypothesis.
    """
    repo = req.repo.resolve()
    config = load_project_config(repo)
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
    if os.environ.get("HYPOTHEX_AGENT") and not req.hypothesis.strip():
        raise RunError("agents must give a hypothesis (--hypothesis): why does this run exist?")
    if req.config_path is not None and not req.config_path.is_file():
        raise RunError(f"config file not found: {req.config_path}")
    user_config = read_yaml(req.config_path) if req.config_path is not None else None

    cwd = (req.cwd or repo).resolve()
    run_id = new_run_id(req.task)
    run_dir = ctx.layout.run_dir(config.project, run_id)
    values = {"run_id": run_id, "run_dir": str(run_dir), "repo": str(repo), "task": req.task or ""}
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
                "dataset.path": str(resolve_dataset_path(repo, ds.path_for(task_spec.split))),
            }
        )
    values.update(req.vars)
    try:
        argv = [render_template(part, values) for part in template]
    except TemplateError as exc:
        raise RunError(str(exc)) from exc
    if not _executable_exists(argv[0], cwd):
        raise RunError(f"command not found: {argv[0]}")

    entry = ctx.store.register_project(config, repo)
    ctx.index.upsert_project(entry)
    datasets = []
    if task_spec is not None:
        cache = FingerprintCache(ctx.layout.dataset_cache)
        datasets.append(
            dataset_ref(
                task_spec.dataset,
                config.datasets[task_spec.dataset],
                task_spec.split,
                repo,
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
        executor=ExecutorInfo(pid=os.getpid(), pid_create_time=process_create_time(os.getpid())),
        git=git_info(cwd),
        datasets=datasets,
        seed=req.seed,
        config_hash=config_hash(fingerprint),
        status=RunStatus.QUEUED,
        created_at=utcnow(),
        tags=sorted(set(req.tags)),
        created_by=req.created_by,
    )
    ctx.create_run(record)
    if user_config is not None:
        write_yaml(run_dir / "config.yaml", user_config)
    diff = capture_diff(cwd)
    if diff.diff:
        atomic_write_bytes(run_dir / "git.diff", diff.diff)
    if diff.stat:
        atomic_write_text(run_dir / "git.stat", diff.stat)
    if diff.too_large:
        atomic_write_text(run_dir / "git.diff.too_large", "diff larger than the capture limit\n")
    capture_env(repo, run_dir / "env", default_python_cmd(repo, config))
    warning = seed_warning(template, req.seed)
    if warning is not None:
        ctx.emit("run.warning", record, {"message": warning})
    return record


def _pump(src: IO[bytes] | None, log_path: Path, sink: BinaryIO | None) -> threading.Thread:
    def run() -> None:
        if src is None:
            return
        out = sink
        fd = src.fileno()
        with log_path.open("ab") as fh:
            while chunk := os.read(fd, 65536):
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
    task run with predictions is scored automatically.

    Parameters
    ----------
    ctx : Context
    run_id : str
    stdout_sink, stderr_sink : binary file, optional
        Where to echo the child's output.
    auto_evaluate : bool
        Score finished task runs.

    Returns
    -------
    RunRecord
        The final record.
    """
    record = ctx.find_record(run_id)
    if record.status != RunStatus.QUEUED:
        raise RunError(f"run {run_id} is {record.status.value}, not queued")
    run_dir = ctx.run_dir(record)
    me = ExecutorInfo(pid=os.getpid(), pid_create_time=process_create_time(os.getpid()))
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
    with _forward_termination() as term:
        try:
            proc = subprocess.Popen(
                record.command,
                cwd=record.cwd,
                env=env,
                stdin=subprocess.DEVNULL,
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
        ctx.update_run(
            run_id,
            "run.started",
            lambda r: r.model_copy(
                update={"status": RunStatus.RUNNING, "started_at": utcnow(), "executor": started}
            ),
        )
        pumps = [
            _pump(proc.stdout, run_dir / "logs" / "stdout.log", stdout_sink),
            _pump(proc.stderr, run_dir / "logs" / "stderr.log", stderr_sink),
        ]
        interrupted = False
        # stop_run may have written the marker after the pre-start check but
        # before the child pid was recorded, so it could not signal the child.
        if (run_dir / STOP_MARKER).exists():
            terminate_group(proc.pid)
        try:
            exit_code = proc.wait()
        except KeyboardInterrupt:
            interrupted = True
            terminate_group(proc.pid)
            exit_code = proc.wait()
    for pump in pumps:
        pump.join()

    stopped = interrupted or term.signalled or (run_dir / STOP_MARKER).exists()
    if stopped:
        status = RunStatus.KILLED
    elif exit_code == 0:
        status = RunStatus.FINISHED
    else:
        status = RunStatus.FAILED
    logged = ctx.store.read_artifacts(record.project, record.run_id)
    usage = sum_usage(ctx.store.read_usage(record.project, record.run_id))
    ctx.index.replace_metric_points(
        record.run_id, ctx.store.read_metric_points(record.project, record.run_id)
    )

    def finish(r: RunRecord) -> RunRecord:
        # A path logged twice (e.g. an overwritten last.pt) keeps its latest step/metrics.
        merged = {(a.kind, a.path): a for a in [*r.artifacts, *logged]}
        return r.model_copy(
            update={
                "status": status,
                "ended_at": utcnow(),
                "exit_code": exit_code,
                "artifacts": list(merged.values()),
                "usage": usage,
            }
        )

    final = ctx.update_run(run_id, f"run.{status.value}", finish, {"exit_code": exit_code})
    if auto_evaluate and status == RunStatus.FINISHED and final.task:
        try:
            evaluate_run(ctx, run_id)
        except HypothexError as exc:  # the run itself finished; scoring can be retried
            ctx.emit("run.eval_skipped", final, {"reason": str(exc)[:500]})
    return ctx.find_record(run_id)
