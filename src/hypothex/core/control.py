"""Background launch, stop, rerun, re-infer, and startup repair."""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from hypothex.core.config import load_project_config
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.execution import (
    STOP_MARKER,
    TERM_GRACE_SECONDS,
    RunRequest,
    execute_run,
    prepare_run,
    process_alive,
    process_create_time,
    terminate_group,
)
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.gitinfo import capture_diff, create_worktree, head_commit
from hypothex.core.ids import utcnow
from hypothex.core.records import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    RunKind,
    RunRecord,
    RunStatus,
)

QUEUED_GRACE_SECONDS = 60.0
SUPERVISOR_PID_FILE = "supervisor.pid"


def launch_run(ctx: Context, req: RunRequest) -> RunRecord:
    """
    Create a run and execute it in a detached supervisor process.

    Parameters
    ----------
    ctx : Context
    req : RunRequest

    Returns
    -------
    RunRecord
        The run as recorded right after launch.
    """
    record = prepare_run(ctx, req)
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
    atomic_write_text(
        run_dir / SUPERVISOR_PID_FILE,
        json.dumps({"pid": proc.pid, "create_time": process_create_time(proc.pid)}),
    )
    ctx.emit("run.launched", record, {"supervisor_pid": proc.pid})
    return ctx.find_record(record.run_id)


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
        The run's record once it reached one of ``statuses``.

    Raises
    ------
    RunError
        On timeout.
    """
    deadline = time.monotonic() + timeout
    while True:
        record = ctx.find_record(run_id)
        if record.status in statuses or record.status in TERMINAL_STATUSES:
            return record
        if time.monotonic() > deadline:
            raise RunError(f"run {run_id} still {record.status.value} after {timeout}s")
        time.sleep(0.1)


def _supervisor_alive(run_dir: Path, record: RunRecord) -> bool:
    if process_alive(record.executor.pid, record.executor.pid_create_time):
        return True
    pid_file = run_dir / SUPERVISOR_PID_FILE
    if record.status == RunStatus.QUEUED and pid_file.is_file():
        info = json.loads(pid_file.read_text(encoding="utf-8"))
        return process_alive(info["pid"], info.get("create_time"))
    return False


def _mark(status: RunStatus) -> Callable[[RunRecord], RunRecord]:
    def mutate(r: RunRecord) -> RunRecord:
        if r.status in TERMINAL_STATUSES:
            return r
        return r.model_copy(update={"status": status, "ended_at": utcnow()})

    return mutate


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


def _start(
    ctx: Context,
    req: RunRequest,
    background: bool,
    stdout_sink: BinaryIO | None,
    stderr_sink: BinaryIO | None,
) -> RunRecord:
    if background:
        return launch_run(ctx, req)
    record = prepare_run(ctx, req)
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
    with the saved diff applied.

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
        If the saved diff was too large to reproduce.
    """
    parent = ctx.find_record(run_id)
    repo = Path(ctx.store.load_project(parent.project).repo)
    parent_dir = ctx.run_dir(parent)
    if (parent_dir / "git.diff.too_large").exists():
        raise RunError(
            f"run {run_id} had an uncommitted diff too large to save; "
            "it cannot be reproduced exactly"
        )
    diff_file = parent_dir / "git.diff"
    saved_diff = diff_file.read_text(encoding="utf-8") if diff_file.is_file() else None
    cwd = Path(parent.cwd)
    if parent.git.commit is not None:
        same_tree = head_commit(repo) == parent.git.commit and capture_diff(repo).diff == saved_diff
        if not same_tree:
            worktree = ctx.layout.worktrees_dir(parent.project) / (
                f"{parent.run_id}-{secrets.token_hex(3)}"
            )
            create_worktree(repo, parent.git.commit, worktree, saved_diff)
            try:
                relative = cwd.relative_to(repo)
            except ValueError:
                relative = Path()
            cwd = worktree / relative
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
    )
    return _start(ctx, req, background, stdout_sink, stderr_sink)


def repair_runs(ctx: Context) -> list[RunRecord]:
    """
    Mark this environment's orphaned queued/running runs as ``lost``.

    A run is orphaned when its supervisor is gone (queued runs get a
    ``QUEUED_GRACE_SECONDS`` grace period). An orphaned child process is
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
        if _supervisor_alive(ctx.run_dir(current), current):
            continue
        age = (utcnow() - current.created_at).total_seconds()
        if current.status == RunStatus.QUEUED and age < QUEUED_GRACE_SECONDS:
            continue
        reason = "supervisor exited without recording a result"
        child = current.executor.child_pid
        if child is not None and process_alive(child, None):
            terminate_group(child)
            reason += "; orphaned process terminated"
        lost.append(
            ctx.update_run(current.run_id, "run.lost", _mark(RunStatus.LOST), {"reason": reason})
        )
    return sorted(lost, key=lambda r: r.run_id)
