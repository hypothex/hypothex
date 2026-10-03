"""Background launch, stop, rerun, re-infer, and startup repair."""

from __future__ import annotations

import dataclasses
import json
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from hypothex.core import slurm
from hypothex.core.config import load_project_config
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.execution import (
    QUEUE_FILE,
    STOP_MARKER,
    SUPERVISOR_PID_FILE,
    TERM_GRACE_SECONDS,
    RunRequest,
    execute_run,
    prepare_run,
    process_alive,
    spawn_supervisor,
    terminate_group,
)
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.gitinfo import capture_diff, create_worktree, head_commit
from hypothex.core.gpus import free_gpus, gpu_status
from hypothex.core.ids import utcnow
from hypothex.core.records import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    RunKind,
    RunRecord,
    RunStatus,
)
from hypothex.core.scheduler import Scheduler, assign_gpus, scheduler_lock
from hypothex.remote.config import SlurmDefaults

QUEUED_GRACE_SECONDS = 60.0
WAIT_REPAIR_SECONDS = 5.0


def launch_run(ctx: Context, req: RunRequest) -> RunRecord:
    """
    Create a run and execute it in a detached supervisor process, or queue it.

    With ``req.queue`` the run waits in this host's GPU queue; the scheduler
    (``hx serve --kind ssh``) starts it once ``req.gpus`` GPUs are free
    (spec 8A.5). Without it, ``req.gpus > 0`` takes the lowest free GPUs now.

    Parameters
    ----------
    ctx : Context
    req : RunRequest

    Returns
    -------
    RunRecord
        The run as recorded right after launch (``queued``; with
        ``executor.queue_position`` when it waits in the queue).

    Raises
    ------
    RunError
        Invalid request, more GPUs than this host has, or (without
        ``req.queue``) fewer free GPUs than ``req.gpus``: nothing is created.
        GPUs taken while the run was prepared, or a supervisor that could not
        be started: the run is created and marked ``failed``.

    Notes
    -----
    On a SLURM environment (``req.slurm`` set, or ``hx serve --kind slurm``)
    the run is submitted with ``sbatch`` instead. SLURM's own queue holds it,
    so ``req.queue`` is ignored there and no host GPUs are checked.
    """
    defaults = _slurm_defaults(ctx, req)
    if defaults is not None:
        slurm.validate_defaults(defaults)
        if req.slurm is not None:
            slurm.remember_slurm_defaults(ctx.layout, defaults)
        # no host queue marker: a queue.json would make the GPU scheduler start it here
        submitted = dataclasses.replace(req, slurm=defaults, queue=False)
        return slurm.submit_run(ctx, prepare_run(ctx, submitted), defaults)
    if req.queue:
        record = prepare_run(ctx, req)
        try:  # the only place a run joins the queue: marker, FIFO place, position at once
            Scheduler(ctx).enqueue(record.run_id)
        except RunError as exc:
            ctx.update_run(record.run_id, "run.failed", _fail_unstarted, {"reason": str(exc)})
            raise
        return ctx.find_record(record.run_id)
    if req.gpus > 0:
        with scheduler_lock(ctx):  # early error only; released before the slow part
            gpus = gpu_status(ctx)
            free = free_gpus(gpus)
            # more than the host has at all: prepare_run raises the clearer error
            if len(free) < req.gpus <= len(gpus):
                raise RunError(
                    f"{req.gpus} GPUs requested; {len(free)} of {len(gpus)} free; "
                    "add --queue to wait for them"
                )
        # git info, capture_env, dataset fingerprints: never under the host-wide lock
        record = prepare_run(ctx, req)
        with scheduler_lock(ctx):
            gpus = gpu_status(ctx)  # a fresh nvidia-smi: sees processes started meanwhile
            free = free_gpus(gpus)
            if len(free) < req.gpus:
                message = (
                    f"{req.gpus} GPUs requested; {len(free)} of {len(gpus)} free now "
                    "(taken while the run was prepared); add --queue to wait for them"
                )
                ctx.update_run(record.run_id, "run.failed", _fail_unstarted, {"reason": message})
                raise RunError(message)
            chosen = free[: req.gpus]
            record = ctx.update_run(
                record.run_id, "run.gpus_assigned", assign_gpus(chosen), {"gpus": chosen}
            )
            _start_supervisor(ctx, record)  # under the lock: GPUs never wait without one
        return ctx.find_record(record.run_id)
    record = prepare_run(ctx, req)
    _start_supervisor(ctx, record)
    return ctx.find_record(record.run_id)


def _fail_unstarted(r: RunRecord) -> RunRecord:
    """Mark a prepared run that never started as failed (frees any GPUs it held)."""
    if r.status in TERMINAL_STATUSES:
        return r
    return r.model_copy(update={"status": RunStatus.FAILED, "ended_at": utcnow()})


def _start_supervisor(ctx: Context, record: RunRecord) -> None:
    """Spawn the run's supervisor; a start that never committed fails the run."""
    try:
        spawn_supervisor(ctx, record)
    except OSError as exc:  # nothing will execute it (Task 18), so its GPUs go back
        message = f"could not start the supervisor: {exc}"
        ctx.update_run(record.run_id, "run.failed", _fail_unstarted, {"reason": message})
        raise RunError(message) from exc


def _slurm_defaults(ctx: Context, req: RunRequest) -> SlurmDefaults | None:
    """
    SLURM settings for a launch, or None for a launch that is not submitted to SLURM.

    The request's own settings win; on a SLURM env without them, the last
    settings a launch sent (normally the hub's ``slurm:`` block, so partition
    and account survive), else bare ``SlurmDefaults()``.
    """
    if req.slurm is not None:
        return req.slurm
    if ctx.descriptor.kind != "slurm":
        return None
    return slurm.last_slurm_defaults(ctx.layout) or SlurmDefaults()


def wait_for_run(
    ctx: Context,
    run_id: str,
    *,
    timeout: float = 60.0,
    statuses: frozenset[RunStatus] = TERMINAL_STATUSES,
) -> RunRecord:
    """
    Poll until the run reaches one of ``statuses``.

    Parameters
    ----------
    ctx : Context
    run_id : str
    timeout : float
        Seconds to wait before giving up.
    statuses : frozenset of RunStatus
        Statuses to wait for; terminal statuses always end the wait.

    Returns
    -------
    RunRecord
        The run's record once it reached one of ``statuses``, or once it was
        marked ``lost`` because its supervisor died (checked every
        ``WAIT_REPAIR_SECONDS``).

    Raises
    ------
    RunError
        On timeout.
    """
    deadline = time.monotonic() + timeout
    next_repair = time.monotonic() + WAIT_REPAIR_SECONDS
    while True:
        record = ctx.find_record(run_id)
        if record.status in statuses or record.status in TERMINAL_STATUSES:
            return record
        if time.monotonic() >= next_repair:
            next_repair = time.monotonic() + WAIT_REPAIR_SECONDS
            lost = _repair_one(ctx, record)
            if lost is not None:
                return lost
        if time.monotonic() > deadline:
            raise RunError(f"run {run_id} still {record.status.value} after {timeout}s")
        time.sleep(0.1)


def _supervisor_alive(run_dir: Path, record: RunRecord) -> bool:
    # A queued run's executor.pid is the launching process (API/MCP server,
    # ``hx launch --wait``), which outlives a crashed supervisor. When a
    # detached supervisor was started, only its pid file tells the truth.
    # Without a pid file (foreground ``hx run``) the launcher is the executor.
    pid_file = run_dir / SUPERVISOR_PID_FILE
    if record.status == RunStatus.QUEUED and pid_file.is_file():
        info = json.loads(pid_file.read_text(encoding="utf-8"))
        return process_alive(info["pid"], info.get("create_time"))
    return process_alive(record.executor.pid, record.executor.pid_create_time)


def _mark(status: RunStatus) -> Callable[[RunRecord], RunRecord]:
    def mutate(r: RunRecord) -> RunRecord:
        if r.status in TERMINAL_STATUSES:
            return r
        return r.model_copy(update={"status": status, "ended_at": utcnow()})

    return mutate


def _scheduler_held(run_dir: Path) -> bool:
    """True when a queued run waits in the GPU queue (no supervisor yet)."""
    return (run_dir / QUEUE_FILE).is_file() and not (run_dir / SUPERVISOR_PID_FILE).is_file()


def _unqueue(r: RunRecord) -> RunRecord:
    if r.status in TERMINAL_STATUSES:
        return r
    executor = r.executor.model_copy(update={"queue_position": None})
    return r.model_copy(
        update={"status": RunStatus.KILLED, "ended_at": utcnow(), "executor": executor}
    )


def _remove_from_queue(ctx: Context, run_id: str, run_dir: Path) -> RunRecord | None:
    """Kill a run still waiting in the GPU queue; None if the scheduler started it."""
    with scheduler_lock(ctx):
        if not _scheduler_held(run_dir):
            return None
        (run_dir / QUEUE_FILE).unlink()
        killed = ctx.update_run(run_id, "run.killed", _unqueue, {"reason": "removed from queue"})
    Scheduler(ctx).refresh_positions()
    return killed


def stop_run(ctx: Context, run_id: str, *, grace: float = TERM_GRACE_SECONDS) -> RunRecord:
    """
    Stop a queued or running run; it ends as ``killed``.

    Parameters
    ----------
    ctx : Context
    run_id : str
    grace : float
        Seconds to wait after SIGTERM before SIGKILL.

    Returns
    -------
    RunRecord
        The run's final record.

    Raises
    ------
    RunError
        If the run is not queued or running.
    """
    record = ctx.find_record(run_id)
    if record.status not in ACTIVE_STATUSES:
        raise RunError(
            f"run {run_id} is {record.status.value}; only queued or running runs can be stopped"
        )
    run_dir = ctx.run_dir(record)
    if record.status == RunStatus.QUEUED and _scheduler_held(run_dir):
        removed = _remove_from_queue(ctx, run_id, run_dir)
        if removed is not None:
            return removed
    if record.executor.type == slurm.SLURM_EXECUTOR:
        # child_pid lives on a compute node: never signal it from here. The stop
        # marker is written by stop_slurm_run, only once scancel worked.
        return slurm.stop_slurm_run(ctx, record, grace=grace)
    atomic_write_text(run_dir / STOP_MARKER, utcnow().isoformat())
    child = record.executor.child_pid
    if record.status == RunStatus.RUNNING and child is not None and process_alive(child, None):
        terminate_group(child, grace)
    deadline = time.monotonic() + grace + 5
    while time.monotonic() < deadline:
        current = ctx.find_record(run_id)
        if current.status in TERMINAL_STATUSES:
            return current
        if not _supervisor_alive(run_dir, current):
            break
        time.sleep(0.1)
    return ctx.update_run(run_id, "run.killed", _mark(RunStatus.KILLED), {"reason": "stopped"})


def _relative_cwd(cwd: Path, repo: Path, previous_repos: list[Path]) -> Path:
    """
    Return a run's working directory relative to the repo it ran in.

    Parameters
    ----------
    cwd : Path
        The run's recorded working directory.
    repo : Path
        The project's current repo root.
    previous_repos : list of Path
        Earlier repo roots of the project (it was re-registered after a move).

    Returns
    -------
    Path
        ``cwd`` relative to ``repo``, else to the deepest previous repo that
        contains it, else ``Path()`` (the repo root).
    """
    for root in [repo, *sorted(previous_repos, key=lambda p: len(p.parts), reverse=True)]:
        if cwd.is_relative_to(root):
            return cwd.relative_to(root)
    return Path()


def _start(
    ctx: Context,
    req: RunRequest,
    background: bool,
    stdout_sink: BinaryIO | None,
    stderr_sink: BinaryIO | None,
) -> RunRecord:
    if background:
        return launch_run(ctx, req)
    if _slurm_defaults(ctx, req) is not None:
        # a foreground run would execute here, on the login node, not in a SLURM job
        raise RunError("SLURM runs are always submitted; drop --foreground")
    # foreground: the run executes right here, so it must not also wait in the host queue
    record = prepare_run(ctx, dataclasses.replace(req, queue=False))
    return execute_run(ctx, record.run_id, stdout_sink=stdout_sink, stderr_sink=stderr_sink)


def rerun(
    ctx: Context,
    run_id: str,
    *,
    background: bool = True,
    created_by: str = "human",
    stdout_sink: BinaryIO | None = None,
    stderr_sink: BinaryIO | None = None,
) -> RunRecord:
    """
    Run the same command, commit, config, seed, and vars again as a child run.

    If the repo is no longer at the recorded commit (or its uncommitted diff
    differs), the rerun executes in a fresh git worktree at the recorded commit
    with the saved diff applied. If the repo moved since the parent ran (the
    project was re-registered at a new path), the working directory is mapped
    onto the new location.

    Parameters
    ----------
    ctx : Context
    run_id : str
        The parent run to reproduce.
    background : bool
        Run in a detached supervisor process.
    created_by : str
        Who requested the rerun.
    stdout_sink, stderr_sink : binary file, optional
        Where to echo the child's output when ``background`` is False.

    Returns
    -------
    RunRecord
        The new child run.

    Raises
    ------
    RunError
        If the saved diff was too large to reproduce, or the working
        directory does not exist in the (possibly moved) repo.
    """
    parent = ctx.find_record(run_id)
    entry = ctx.store.load_project(parent.project)
    repo = Path(entry.repo)
    parent_dir = ctx.run_dir(parent)
    if (parent_dir / "git.diff.too_large").exists():
        raise RunError(
            f"run {run_id} had an uncommitted diff too large to save; "
            "it cannot be reproduced exactly"
        )
    diff_file = parent_dir / "git.diff"
    saved_diff = diff_file.read_bytes() if diff_file.is_file() else None
    relative = _relative_cwd(Path(parent.cwd), repo, [Path(p) for p in entry.previous_repos])
    cwd = repo / relative
    if parent.git.commit is not None:
        same_tree = head_commit(repo) == parent.git.commit and capture_diff(repo).diff == saved_diff
        if not same_tree:
            worktree = ctx.layout.worktrees_dir(parent.project) / (
                f"{parent.run_id}-{secrets.token_hex(3)}"
            )
            create_worktree(repo, parent.git.commit, worktree, saved_diff)
            cwd = worktree / relative
    if not cwd.is_dir():
        raise RunError(
            f"working directory {cwd} for the rerun of {run_id} does not exist "
            f"(the run used {parent.cwd}; the project repo is now {repo})"
        )
    config_file = parent_dir / "config.yaml"
    req = RunRequest(
        repo=repo,
        command=list(parent.command_template),
        stage=parent.stage,
        task=parent.task,
        hypothesis=f"Rerun of {parent.run_id}: {parent.hypothesis}".strip(),
        seed=parent.seed,
        tags=list(parent.tags),
        config_path=config_file if config_file.is_file() else None,
        params=dict(parent.params),
        vars=dict(parent.vars),
        kind=parent.kind,
        parent=parent.run_id,
        cwd=cwd,
        created_by=created_by,
        gpus=parent.gpus_requested,
        queue=parent.gpus_requested > 0,  # wait for GPUs; never start with none
        slurm=slurm.run_slurm_settings(parent_dir),
    )
    return _start(ctx, req, background, stdout_sink, stderr_sink)


def reinfer(
    ctx: Context,
    run_id: str,
    *,
    checkpoint: str | None = None,
    background: bool = True,
    created_by: str = "human",
    stdout_sink: BinaryIO | None = None,
    stderr_sink: BinaryIO | None = None,
) -> RunRecord:
    """
    Run the project's ``infer`` stage with a run's checkpoint as a child run.

    Parameters
    ----------
    ctx : Context
    run_id : str
        The parent run to re-infer from.
    checkpoint : str, optional
        Checkpoint path; defaults to the parent's most recent checkpoint artifact.
    background : bool
        Run in a detached supervisor process.
    created_by : str
        Who requested the re-infer.
    stdout_sink, stderr_sink : binary file, optional
        Where to echo the child's output when ``background`` is False.

    Returns
    -------
    RunRecord
        The new child run.

    Raises
    ------
    RunError
        If there is no ``infer`` stage or no checkpoint.
    """
    parent = ctx.find_record(run_id)
    repo = Path(ctx.store.load_project(parent.project).repo)
    config = load_project_config(repo)
    if "infer" not in config.stages:
        raise RunError("project has no `infer` stage in hypothex.yaml; add one to use re-infer")
    checkpoints = [a.path for a in parent.artifacts if a.kind == "checkpoint"]
    chosen = checkpoint or (checkpoints[-1] if checkpoints else None)
    if chosen is None:
        raise RunError(f"run {run_id} has no checkpoint artifact; pass --checkpoint PATH")
    req = RunRequest(
        repo=repo,
        stage="infer",
        task=parent.task,
        hypothesis=f"Re-infer of {parent.run_id}: {parent.hypothesis}".strip(),
        seed=parent.seed,
        tags=list(parent.tags),
        vars={**parent.vars, "checkpoint": chosen},
        kind=RunKind.INFER,
        parent=parent.run_id,
        created_by=created_by,
        gpus=parent.gpus_requested,
        queue=parent.gpus_requested > 0,
        slurm=slurm.run_slurm_settings(ctx.run_dir(parent)),
    )
    return _start(ctx, req, background, stdout_sink, stderr_sink)


def repair_runs(ctx: Context) -> list[RunRecord]:
    """
    Mark this environment's orphaned queued/running runs as ``lost``.

    A run is orphaned when its supervisor is gone (queued runs get a
    ``QUEUED_GRACE_SECONDS`` grace period). Runs waiting in the GPU queue
    have no supervisor yet and stay queued. An orphaned child process is
    terminated so it does not run unrecorded.

    Parameters
    ----------
    ctx : Context

    Returns
    -------
    list of RunRecord
        Runs that were marked lost.
    """
    lost: list[RunRecord] = []
    candidates = [
        r
        for status in ACTIVE_STATUSES
        for r in ctx.index.list_runs(status=status, include_archived=True, limit=None)
    ]
    for indexed in candidates:
        if indexed.environment_id != ctx.descriptor.environment_id:
            continue
        current = ctx.find_record(indexed.run_id)
        if current.status not in ACTIVE_STATUSES:
            ctx.index.upsert_run(current)
            continue
        marked = _repair_one(ctx, current)
        if marked is not None:
            lost.append(marked)
    return sorted(lost, key=lambda r: r.run_id)


def _repair_one(ctx: Context, current: RunRecord) -> RunRecord | None:
    """Mark one active run of this environment lost if its supervisor is gone."""
    if current.environment_id != ctx.descriptor.environment_id:
        return None
    if current.executor.type == slurm.SLURM_EXECUTOR:
        return None  # squeue/sacct decide (slurm.reconcile); its pids live on a compute node
    run_dir = ctx.run_dir(current)
    if current.status == RunStatus.QUEUED and _scheduler_held(run_dir):
        return None  # waiting for GPUs: the scheduler owns it, not a supervisor
    if _supervisor_alive(run_dir, current):
        return None
    age = (utcnow() - current.created_at).total_seconds()
    if current.status == RunStatus.QUEUED and age < QUEUED_GRACE_SECONDS:
        return None
    reason = "supervisor exited without recording a result"
    child = current.executor.child_pid
    if child is not None and process_alive(child, None):
        terminate_group(child)
        reason += "; orphaned process terminated"
    return ctx.update_run(current.run_id, "run.lost", _mark(RunStatus.LOST), {"reason": reason})
