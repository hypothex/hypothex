import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest

from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.control import launch_run, reinfer, repair_runs, rerun, stop_run, wait_for_run
from hypothex.core.errors import RunError
from hypothex.core.execution import RunRequest, execute_run, prepare_run, process_create_time
from hypothex.core.ids import utcnow
from hypothex.core.records import ExecutorInfo, RunKind, RunStatus
from tests.factories import git, make_record

PY = sys.executable


def cmd(code: str) -> list[str]:
    return [PY, "-c", code]


def dead_pid() -> int:
    proc = subprocess.Popen([PY, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_launch_run_in_background_finishes(ctx: Context, toy_repo: Path) -> None:
    rec = launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("print('bg')"), hypothesis="bg"))
    done = wait_for_run(ctx, rec.run_id, timeout=60)
    assert done.status == RunStatus.FINISHED
    run_dir = ctx.run_dir(done)
    assert (run_dir / "logs" / "stdout.log").read_text().strip() == "bg"
    assert (run_dir / "supervisor.pid").is_file()


def test_stop_run_kills_background_run(ctx: Context, toy_repo: Path) -> None:
    rec = launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("import time; time.sleep(60)")))
    wait_for_run(ctx, rec.run_id, timeout=30, statuses=frozenset({RunStatus.RUNNING}))
    start = time.monotonic()
    stopped = stop_run(ctx, rec.run_id)
    assert stopped.status == RunStatus.KILLED
    assert time.monotonic() - start < 15
    with pytest.raises(RunError, match="only queued or running"):
        stop_run(ctx, rec.run_id)


def test_rerun_same_commit_runs_in_place(ctx: Context, toy_repo: Path) -> None:
    parent = execute_run(
        ctx,
        prepare_run(
            ctx, RunRequest(repo=toy_repo, command=cmd("print('hi')"), hypothesis="h")
        ).run_id,
    )
    child = rerun(ctx, parent.run_id, background=False)
    assert child.parent == parent.run_id and child.status == RunStatus.FINISHED
    assert child.cwd == parent.cwd and child.config_hash == parent.config_hash
    assert child.hypothesis.startswith(f"Rerun of {parent.run_id}")


def test_rerun_after_new_commit_uses_worktree(ctx: Context, toy_repo: Path) -> None:
    (toy_repo / "marker.txt").write_text("old")
    git(toy_repo, "add", "marker.txt")
    git(toy_repo, "commit", "-qm", "marker old")
    parent = execute_run(
        ctx,
        prepare_run(
            ctx, RunRequest(repo=toy_repo, command=cmd("print(open('marker.txt').read())"))
        ).run_id,
    )
    (toy_repo / "marker.txt").write_text("new")
    git(toy_repo, "commit", "-qam", "marker new")
    child = rerun(ctx, parent.run_id, background=False)
    assert "worktrees" in child.cwd
    assert (ctx.run_dir(child) / "logs" / "stdout.log").read_text().strip() == "old"
    assert child.git.commit == parent.git.commit


def test_reinfer_uses_checkpoint_artifact(ctx: Context, toy_repo: Path) -> None:
    code = (
        "import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
        "open(d + '/artifacts.jsonl', 'a').write(json.dumps("
        "{'kind': 'checkpoint', 'path': '/tmp/model.pt'}) + '\\n')"
    )
    parent = execute_run(
        ctx, prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(code), task="toy-acc")).run_id
    )
    child = reinfer(ctx, parent.run_id, background=False)
    assert child.kind == RunKind.INFER and child.vars["checkpoint"] == "/tmp/model.pt"
    assert "inferred with /tmp/model.pt" in (ctx.run_dir(child) / "logs" / "stdout.log").read_text()
    assert [s.value for s in ctx.store.read_scores("toy", child.run_id)] == [0.75]


def test_reinfer_without_checkpoint_errors(ctx: Context, toy_repo: Path) -> None:
    parent = execute_run(
        ctx, prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"))).run_id
    )
    with pytest.raises(RunError, match="no checkpoint"):
        reinfer(ctx, parent.run_id, background=False)


def _active(ctx: Context, rid: str, status: RunStatus, pid: int, **kw: object) -> None:
    ctx.create_run(
        make_record(
            rid,
            status=status,
            environment_id=ctx.descriptor.environment_id,
            executor=ExecutorInfo(pid=pid, pid_create_time=process_create_time(pid)),
            **kw,
        )
    )


def test_repair_marks_dead_running_as_lost(ctx: Context) -> None:
    _active(ctx, "dead", RunStatus.RUNNING, dead_pid())
    _active(ctx, "alive", RunStatus.RUNNING, os.getpid())
    lost = repair_runs(ctx)
    assert [r.run_id for r in lost] == ["dead"]
    assert ctx.find_record("dead").status == RunStatus.LOST
    assert ctx.find_record("alive").status == RunStatus.RUNNING


def test_repair_queued_uses_grace_period(ctx: Context) -> None:
    _active(ctx, "old", RunStatus.QUEUED, dead_pid(), created_at=utcnow() - timedelta(minutes=5))
    _active(ctx, "new", RunStatus.QUEUED, dead_pid())
    assert [r.run_id for r in repair_runs(ctx)] == ["old"]


def _write_supervisor_pid(ctx: Context, rid: str, pid: int) -> None:
    run_dir = ctx.run_dir(ctx.find_record(rid))
    info = {"pid": pid, "create_time": process_create_time(pid)}
    (run_dir / "supervisor.pid").write_text(json.dumps(info))


def test_repair_queued_uses_supervisor_pid_not_live_launcher(ctx: Context) -> None:
    # Launched from a long-lived process (API/MCP server): executor.pid is alive,
    # but the detached supervisor died before starting the child.
    old = utcnow() - timedelta(minutes=5)
    _active(ctx, "crashed", RunStatus.QUEUED, os.getpid(), created_at=old)
    _write_supervisor_pid(ctx, "crashed", dead_pid())
    _active(ctx, "starting", RunStatus.QUEUED, dead_pid(), created_at=old)
    _write_supervisor_pid(ctx, "starting", os.getpid())
    _active(ctx, "foreground", RunStatus.QUEUED, os.getpid(), created_at=old)
    assert [r.run_id for r in repair_runs(ctx)] == ["crashed"]
    assert ctx.find_record("crashed").status == RunStatus.LOST
    assert ctx.find_record("starting").status == RunStatus.QUEUED
    assert ctx.find_record("foreground").status == RunStatus.QUEUED


def test_wait_for_run_returns_when_supervisor_dies(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(control, "WAIT_REPAIR_SECONDS", 0.0)
    old = utcnow() - timedelta(minutes=5)
    _active(ctx, "crashed", RunStatus.QUEUED, os.getpid(), created_at=old)
    _write_supervisor_pid(ctx, "crashed", dead_pid())
    assert wait_for_run(ctx, "crashed", timeout=10).status == RunStatus.LOST


def test_repair_ignores_other_environments(ctx: Context) -> None:
    ctx.create_run(
        make_record(
            "other",
            status=RunStatus.RUNNING,
            environment_id="elsewhere",
            executor=ExecutorInfo(pid=dead_pid()),
        )
    )
    assert repair_runs(ctx) == []
