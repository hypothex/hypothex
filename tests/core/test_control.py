import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.control import launch_run, reinfer, repair_runs, rerun, stop_run, wait_for_run
from hypothex.core.errors import RunError
from hypothex.core.execution import (
    STOP_MARKER,
    RunRequest,
    execute_run,
    prepare_run,
    process_alive,
    process_create_time,
)
from hypothex.core.ids import utcnow
from hypothex.core.records import ExecutorInfo, RunKind, RunRecord, RunStatus
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


def test_non_utf8_dirty_tree_is_captured_and_rerun_in_place(ctx: Context, toy_repo: Path) -> None:
    latin = toy_repo / "latin.txt"
    latin.write_bytes("caf\xe9 old\n".encode("latin-1"))
    git(toy_repo, "add", "latin.txt")
    git(toy_repo, "commit", "-qm", "latin")
    latin.write_bytes("caf\xe9 new\n".encode("latin-1"))
    parent = execute_run(
        ctx, prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"))).run_id
    )
    assert parent.status == RunStatus.FINISHED
    assert b"+caf\xe9 new" in (ctx.run_dir(parent) / "git.diff").read_bytes()
    child = rerun(ctx, parent.run_id, background=False)
    assert child.status == RunStatus.FINISHED and child.cwd == parent.cwd


def test_rerun_applies_non_utf8_diff_in_worktree(ctx: Context, toy_repo: Path) -> None:
    latin = toy_repo / "latin.txt"
    latin.write_bytes("caf\xe9 old\n".encode("latin-1"))
    git(toy_repo, "add", "latin.txt")
    git(toy_repo, "commit", "-qm", "latin")
    latin.write_bytes("caf\xe9 dirty\n".encode("latin-1"))
    read = cmd("import sys; sys.stdout.write(open('latin.txt', 'rb').read().hex())")
    parent = execute_run(ctx, prepare_run(ctx, RunRequest(repo=toy_repo, command=read)).run_id)
    git(toy_repo, "checkout", "--", "latin.txt")
    child = rerun(ctx, parent.run_id, background=False)
    assert "worktrees" in child.cwd and child.status == RunStatus.FINISHED
    out = (ctx.run_dir(child) / "logs" / "stdout.log").read_text()
    assert bytes.fromhex(out) == "caf\xe9 dirty\n".encode("latin-1")


def test_stop_requested_while_child_starts_kills_the_child(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # stop_run writes the marker after the pre-start check but before the run
    # is recorded as running: the executor must still signal the child.
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("import time; time.sleep(20)")))
    real_popen = subprocess.Popen

    def popen_then_stop(*args: object, **kwargs: object) -> subprocess.Popen:
        proc = real_popen(*args, **kwargs)  # type: ignore[call-overload]
        (ctx.run_dir(rec) / STOP_MARKER).write_text("now")
        return proc

    monkeypatch.setattr(subprocess, "Popen", popen_then_stop)
    start = time.monotonic()
    done = execute_run(ctx, rec.run_id)
    assert done.status == RunStatus.KILLED
    assert time.monotonic() - start < 10
    assert not process_alive(done.executor.child_pid, None)


PRINT_CWD = cmd("import os; print(os.getcwd())")


def _moved_repo_parent(ctx: Context, toy_repo: Path, tmp_path: Path) -> tuple[str, Path]:
    """Run PRINT_CWD in an untracked ``sub/`` of the repo, then move the repo."""
    (toy_repo / "sub").mkdir()
    (toy_repo / "sub" / "scratch.txt").write_text("untracked\n")
    req = RunRequest(repo=toy_repo, command=PRINT_CWD, cwd=toy_repo / "sub")
    parent = execute_run(ctx, prepare_run(ctx, req).run_id)
    assert parent.status == RunStatus.FINISHED
    moved = tmp_path / "moved" / "toy-renamed"
    moved.parent.mkdir()
    shutil.move(toy_repo, moved)
    ctx.register_project(moved)
    return parent.run_id, moved


def test_rerun_after_repo_moved_rebases_cwd(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    parent_id, moved = _moved_repo_parent(ctx, toy_repo, tmp_path)
    child = rerun(ctx, parent_id, background=False)
    assert child.status == RunStatus.FINISHED
    assert Path(child.cwd) == (moved / "sub").resolve()
    out = (ctx.run_dir(child) / "logs" / "stdout.log").read_text().strip()
    assert Path(out).resolve() == (moved / "sub").resolve()


def test_rerun_after_repo_moved_with_missing_cwd_is_clear_error(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    parent_id, moved = _moved_repo_parent(ctx, toy_repo, tmp_path)
    shutil.rmtree(moved / "sub")
    with pytest.raises(RunError, match="working directory .*sub.* does not exist"):
        rerun(ctx, parent_id, background=False)


def test_rerun_after_repo_moved_without_history_uses_repo_root(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    parent_id, moved = _moved_repo_parent(ctx, toy_repo, tmp_path)
    # a project.json written before repo history was kept
    project_file = ctx.layout.project_dir("toy") / "project.json"
    data = json.loads(project_file.read_text())
    data.pop("previous_repos", None)
    project_file.write_text(json.dumps(data))
    child = rerun(ctx, parent_id, background=False)
    assert child.status == RunStatus.FINISHED
    assert Path(child.cwd) == moved.resolve()


SLEEPER = cmd("import time; print('ready', flush=True); time.sleep(60)")


def _launch_running(ctx: Context, toy_repo: Path) -> tuple[str, int]:
    """Launch SLEEPER in a supervisor; return the run id and the supervisor pid."""
    rec = launch_run(ctx, RunRequest(repo=toy_repo, command=SLEEPER))
    running = wait_for_run(ctx, rec.run_id, timeout=30, statuses=frozenset({RunStatus.RUNNING}))
    info = json.loads((ctx.run_dir(running) / "supervisor.pid").read_text())
    assert running.executor.pid == info["pid"] and running.executor.child_pid is not None
    log = ctx.run_dir(running) / "logs" / "stdout.log"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and "ready" not in (log.read_text() if log.exists() else ""):
        time.sleep(0.01)  # `running` is saved just before the gate opens (gated spawn)
    return rec.run_id, info["pid"]


def test_sigterm_to_supervisor_ends_run_killed(ctx: Context, toy_repo: Path) -> None:
    run_id, supervisor = _launch_running(ctx, toy_repo)
    child = ctx.find_record(run_id).executor.child_pid
    os.kill(supervisor, signal.SIGTERM)
    done = wait_for_run(ctx, run_id, timeout=20)
    assert done.status == RunStatus.KILLED
    assert not process_alive(child, None)


def test_sigterm_before_child_starts_is_forwarded(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # SIGTERM arriving while the child is being started must still end the run
    # as killed. A stand-in handler keeps the test process alive if it leaks.
    leaked: list[int] = []
    previous = signal.signal(signal.SIGTERM, lambda signum, frame: leaked.append(signum))
    try:
        rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=SLEEPER))
        real_popen = subprocess.Popen

        def popen_after_sigterm(*args: object, **kwargs: object) -> subprocess.Popen:
            os.kill(os.getpid(), signal.SIGTERM)
            return real_popen(*args, **kwargs)  # type: ignore[call-overload]

        monkeypatch.setattr(subprocess, "Popen", popen_after_sigterm)
        start = time.monotonic()
        done = execute_run(ctx, rec.run_id)
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert leaked == []
    assert done.status == RunStatus.KILLED
    assert time.monotonic() - start < 15
    assert not process_alive(done.executor.child_pid, None)


def test_sigkill_of_supervisor_then_repair_marks_lost_and_kills_orphan(
    ctx: Context, toy_repo: Path
) -> None:
    run_id, supervisor = _launch_running(ctx, toy_repo)
    child = ctx.find_record(run_id).executor.child_pid
    os.kill(supervisor, signal.SIGKILL)
    deadline = time.monotonic() + 10
    while process_alive(supervisor, None) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert process_alive(child, None)  # the orphan keeps running until repaired
    assert [r.run_id for r in repair_runs(ctx)] == [run_id]
    lost = ctx.find_record(run_id)
    assert lost.status == RunStatus.LOST
    assert not process_alive(child, None)
    reasons = [e.payload.get("reason", "") for e in ctx.events.since(0) if e.type == "run.lost"]
    assert reasons and "orphaned process terminated" in reasons[-1]


def test_stop_marker_before_start_ends_killed_without_starting(
    ctx: Context, toy_repo: Path
) -> None:
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=SLEEPER))
    (ctx.run_dir(rec) / STOP_MARKER).write_text("now")
    done = execute_run(ctx, rec.run_id)
    assert done.status == RunStatus.KILLED
    assert done.started_at is None and done.executor.child_pid is None
    killed = [e for e in ctx.events.since(0) if e.type == "run.killed"]
    assert killed[-1].payload.get("reason") == "stopped before start"


# review fixes: reruns check out through prepare_run, repair skips gone runs, reinfer config
def _commit_train(repo: Path, text: str) -> None:
    (repo / "train.py").write_text(f"print({text!r})\n")
    subprocess.run(["git", "-C", str(repo), "add", "train.py"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo)]
        + ["commit", "-qm", text],
        check=True,
    )


def test_rerun_in_a_worktree_renders_repo_inside_the_checkout(ctx: Context, toy_repo: Path) -> None:
    _commit_train(toy_repo, "train v1")
    req = RunRequest(repo=toy_repo, command=[PY, "{repo}/train.py"])
    parent = execute_run(ctx, prepare_run(ctx, req).run_id)
    _commit_train(toy_repo, "train v2")
    child = rerun(ctx, parent.run_id, background=False)
    assert child.git.commit == parent.git.commit
    assert child.cwd == str(ctx.layout.worktrees_dir("toy") / child.run_id)
    assert child.command[1] == f"{child.cwd}/train.py"
    assert (ctx.run_dir(child) / "logs" / "stdout.log").read_text().strip() == "train v1"


def test_rerun_keeps_the_subdirectory_of_a_worktree_parent(ctx: Context, toy_repo: Path) -> None:
    (toy_repo / "pkg").mkdir()
    (toy_repo / "pkg" / "keep.txt").write_text("x\n")
    _commit_train(toy_repo, "train v1")
    subprocess.run(["git", "-C", str(toy_repo), "add", "pkg"], check=True)
    _commit_train(toy_repo, "train v1b")
    head = subprocess.run(
        ["git", "-C", str(toy_repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    _commit_train(toy_repo, "train v2")
    req = RunRequest(repo=toy_repo, command=PRINT_CWD, cwd=toy_repo / "pkg", commit=head)
    parent = execute_run(ctx, prepare_run(ctx, req).run_id)
    assert Path(parent.cwd).name == "pkg"
    child = rerun(ctx, parent.run_id, background=False)
    assert child.status == RunStatus.FINISHED
    assert Path(child.cwd) == ctx.layout.worktrees_dir("toy") / child.run_id / "pkg"


def test_rerun_that_fails_after_the_checkout_leaves_no_worktree(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core import execution

    _commit_train(toy_repo, "train v1")
    parent = execute_run(
        ctx, prepare_run(ctx, RunRequest(repo=toy_repo, command=[PY, "train.py"])).run_id
    )
    _commit_train(toy_repo, "train v2")

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("env capture failed")

    monkeypatch.setattr(execution, "capture_env", boom)
    with pytest.raises(OSError, match="env capture failed"):
        rerun(ctx, parent.run_id, background=False)
    folder = ctx.layout.worktrees_dir("toy")
    assert not folder.is_dir() or list(folder.iterdir()) == []


def test_repair_skips_a_run_whose_folder_was_deleted(ctx: Context) -> None:
    _active(ctx, "gone", RunStatus.RUNNING, dead_pid())
    _active(ctx, "zdead", RunStatus.RUNNING, dead_pid())
    shutil.rmtree(ctx.run_dir(ctx.find_record("gone")))
    assert [r.run_id for r in repair_runs(ctx)] == ["zdead"]
    assert ctx.index.get_run("gone") is None


def test_reinfer_passes_the_parents_config(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    import yaml

    config = yaml.safe_load((toy_repo / "hypothex.yaml").read_text())
    config["stages"]["infer"] += " --config {config}"
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    user_config = tmp_path / "cfg.yaml"
    user_config.write_text("lr: 0.1\n")
    code = (
        "import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
        "open(d + '/artifacts.jsonl', 'a').write(json.dumps("
        "{'kind': 'checkpoint', 'path': '/tmp/model.pt'}) + '\\n')"
    )
    req = RunRequest(repo=toy_repo, command=cmd(code), config_path=user_config)
    parent = execute_run(ctx, prepare_run(ctx, req).run_id)
    child = reinfer(ctx, parent.run_id, background=False)
    assert child.status == RunStatus.FINISHED
    assert (ctx.run_dir(child) / "config.yaml").read_text() == "lr: 0.1\n"
    assert child.command[-1] == str(ctx.run_dir(child) / "config.yaml")


def _pinned_request(repo: Path, *, gpus: int = 0, queue: bool = False) -> RunRequest:
    """A request pinned to the previous commit, so it runs in its own worktree."""
    _commit_train(repo, "train v1")
    old = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    _commit_train(repo, "train v2")
    return RunRequest(repo=repo, command=[PY, "train.py"], commit=old, gpus=gpus, queue=queue)


def _staging(ctx: Context) -> list[Path]:
    """The shared staging checkouts of project toy."""
    root = ctx.layout.project_dir("toy") / "staging"
    return sorted(p for p in root.iterdir() if p.is_dir() and "." not in p.name)


def _git_worktrees(repo: Path) -> int:
    return git(repo, "worktree", "list", "--porcelain").count("worktree ")


def test_cancelling_an_unstarted_pinned_run_releases_its_staging_checkout(
    ctx: Context, toy_repo: Path
) -> None:
    rec = prepare_run(ctx, _pinned_request(toy_repo))
    tree = ctx.layout.worktrees_dir("toy") / rec.run_id
    assert not tree.exists() and len(_staging(ctx)) == 1  # its own tree waits for the start
    assert control.cancel_if_queued(ctx, rec.run_id).status == RunStatus.KILLED
    assert _staging(ctx) == [] and _git_worktrees(toy_repo) == 1


def test_removing_a_pinned_run_from_the_gpu_queue_releases_its_staging_checkout(
    ctx: Context, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_gpus = tmp_path / "gpus.json"
    fake_gpus.write_text('[{"index": 0, "external": true}]')  # busy: nothing can start
    monkeypatch.setenv("HYPOTHEX_FAKE_GPUS", str(fake_gpus))
    rec = launch_run(ctx, _pinned_request(toy_repo, gpus=1, queue=True))
    assert rec.status == RunStatus.QUEUED
    assert len(_staging(ctx)) == 1
    assert control.cancel_if_queued(ctx, rec.run_id).status == RunStatus.KILLED
    assert _staging(ctx) == [] and _git_worktrees(toy_repo) == 1


def test_queued_pinned_runs_share_one_checkout_until_they_start(
    ctx: Context, toy_repo: Path
) -> None:
    # DF-50: each queued pinned run made a full worktree at launch
    req = _pinned_request(toy_repo)
    first, second, third = (prepare_run(ctx, req) for _ in range(3))
    trees = ctx.layout.worktrees_dir("toy")
    assert len(_staging(ctx)) == 1 and _git_worktrees(toy_repo) == 2
    assert not trees.exists() or list(trees.iterdir()) == []
    assert first.cwd == str(trees / first.run_id)
    done = execute_run(ctx, first.run_id)
    assert done.status == RunStatus.FINISHED
    assert (ctx.run_dir(done) / "logs" / "stdout.log").read_text().strip() == "train v1"
    assert len(_staging(ctx)) == 1  # two runs still wait for it
    assert execute_run(ctx, second.run_id).status == RunStatus.FINISHED
    control.cancel_if_queued(ctx, third.run_id)
    assert _staging(ctx) == [] and _git_worktrees(toy_repo) == 1


def test_a_pinned_run_whose_commit_is_gone_at_start_fails(ctx: Context, toy_repo: Path) -> None:
    rec = prepare_run(ctx, _pinned_request(toy_repo))
    (ctx.run_dir(rec) / ".hx" / "checkout.json").write_text(
        json.dumps({"repo": str(toy_repo), "commit": "0" * 40, "staging": "x"})
    )
    done = execute_run(ctx, rec.run_id)
    assert done.status == RunStatus.FAILED and done.started_at is None
    assert "could not check out" in (ctx.run_dir(done) / "logs" / "stderr.log").read_text()
    assert not (ctx.layout.worktrees_dir("toy") / rec.run_id).exists()


def test_stop_run_signals_a_child_its_first_read_missed(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INT-F1: stop_run read the run while queued; the supervisor then passed its
    # last marker check and recorded run.started before the marker was written.
    # stop_run must signal the child it finds after writing the marker. The
    # "supervisor" here is this test process, which never watches the marker.
    queued = prepare_run(ctx, RunRequest(repo=toy_repo, command=SLEEPER))
    child = subprocess.Popen(SLEEPER, start_new_session=True)
    try:
        started = queued.executor.model_copy(
            update={
                "pid": os.getpid(),
                "pid_create_time": process_create_time(os.getpid()),
                "child_pid": child.pid,
            }
        )
        ctx.update_run(
            queued.run_id,
            "run.started",
            lambda r: r.model_copy(
                update={"status": RunStatus.RUNNING, "started_at": utcnow(), "executor": started}
            ),
        )
        real = ctx.find_record
        reads: list[str] = []

        def first_read_is_the_queued_snapshot(run_id: str):  # noqa: ANN202
            reads.append(run_id)
            return queued if len(reads) == 1 else real(run_id)

        monkeypatch.setattr(ctx, "find_record", first_read_is_the_queued_snapshot)
        assert stop_run(ctx, queued.run_id, grace=0.5).status == RunStatus.KILLED
        assert child.wait(timeout=5) is not None
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def _sweep_tagged_parent(ctx: Context, toy_repo: Path) -> tuple[str, str]:
    """A finished run with a checkpoint, a user tag, and a sweep tag."""
    code = (
        "import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
        "open(d + '/artifacts.jsonl', 'a').write(json.dumps("
        "{'kind': 'checkpoint', 'path': '/tmp/model.pt'}) + '\\n')"
    )
    tag = "sweep:0a1b2c3d:s-1"
    req = RunRequest(repo=toy_repo, command=cmd(code), task="toy-acc", tags=["keep", tag])
    return execute_run(ctx, prepare_run(ctx, req).run_id).run_id, tag


@pytest.mark.parametrize("make_child", [rerun, reinfer])
def test_child_runs_do_not_join_the_parents_sweep(
    ctx: Context, toy_repo: Path, make_child: Callable[..., RunRecord]
) -> None:
    # DF-2: a rerun or re-infer copied the sweep tag, so it counted in the sweep
    parent, tag = _sweep_tagged_parent(ctx, toy_repo)
    child = make_child(ctx, parent, background=False)
    assert child.tags == ["keep"]
    members = ctx.index.list_runs(project="toy", tag=tag, include_archived=True, limit=None)
    assert [r.run_id for r in members] == [parent]


def test_a_lost_queued_pinned_run_releases_its_staging_checkout(
    ctx: Context, toy_repo: Path
) -> None:
    rec = prepare_run(ctx, _pinned_request(toy_repo))
    old = utcnow() - timedelta(minutes=5)
    ctx.update_run(rec.run_id, "test.aged", lambda r: r.model_copy(update={"created_at": old}))
    _write_supervisor_pid(ctx, rec.run_id, dead_pid())
    assert [r.run_id for r in repair_runs(ctx)] == [rec.run_id]
    assert _staging(ctx) == [] and _git_worktrees(toy_repo) == 1


def test_cancel_many_repositions_the_queue_once_and_goes_past_errors(
    ctx: Context, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DF-49: a sweep cancel repositioned the whole queue once per run (n^2 events)
    fake_gpus = tmp_path / "gpus.json"
    fake_gpus.write_text('[{"index": 0, "external": true}]')  # busy: nothing can start
    monkeypatch.setenv("HYPOTHEX_FAKE_GPUS", str(fake_gpus))
    req = RunRequest(repo=toy_repo, command=cmd("pass"), gpus=1, queue=True)
    ids = [launch_run(ctx, req).run_id for _ in range(5)]
    mark = ctx.events.since(0, limit=10_000)[-1].sequence
    batch = control.cancel_many_if_queued(ctx, [*ids[:3], "no-such-run"])
    assert [r.run_id for r in batch.records] == ids[:3]
    assert all(r.status == RunStatus.KILLED for r in batch.records)
    assert list(batch.errors) == ["no-such-run"]
    moved = [e for e in ctx.events.since(mark, limit=10_000) if e.type == "run.queue_moved"]
    assert sorted(e.run_id for e in moved) == sorted(ids[3:])  # once each, not once per cancel
    assert [ctx.find_record(i).executor.queue_position for i in ids[3:]] == [1, 2]


def test_reinfer_takes_vars_for_the_infer_stage(ctx: Context, toy_repo: Path) -> None:
    # DF-22: an infer stage with a new var could not be re-inferred
    import yaml

    config = yaml.safe_load((toy_repo / "hypothex.yaml").read_text())
    config["stages"]["infer"] += " --temperature {temperature}"
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    parent, _ = _sweep_tagged_parent(ctx, toy_repo)
    with pytest.raises(RunError, match="temperature"):
        reinfer(ctx, parent, background=False)
    child = reinfer(ctx, parent, vars={"temperature": "2", "checkpoint": "x"}, background=False)
    assert child.kind == RunKind.INFER and child.parent == parent
    assert child.vars == {"temperature": "2", "checkpoint": "/tmp/model.pt"}
    assert child.command[-2:] == ["--temperature", "2"]
