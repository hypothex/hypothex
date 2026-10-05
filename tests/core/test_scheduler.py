import json
import os
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hypothex.api import app as app_module
from hypothex.api.app import create_app
from hypothex.cli.main import app, resolve_serve_kind
from hypothex.core import execution
from hypothex.core import scheduler as scheduler_module
from hypothex.core.context import Context
from hypothex.core.control import launch_run, repair_runs, stop_run, wait_for_run
from hypothex.core.errors import ConfigError, RunError
from hypothex.core.execution import (
    EXECUTION_CLAIM,
    QUEUE_FILE,
    RunRequest,
    execute_run,
    prepare_run,
)
from hypothex.core.gpus import free_gpus, gpu_status
from hypothex.core.ids import utcnow
from hypothex.core.records import ExecutorInfo, RunRecord, RunStatus
from hypothex.core.scheduler import Scheduler, run_scheduler_loop
from tests.factories import git, make_record, write_toy_project

PY = sys.executable
CUDA = "import os; print(os.environ.get('CUDA_VISIBLE_DEVICES', 'unset'))"
FOUR_GPUS = [{"index": 0}, {"index": 1}, {"index": 2}, {"index": 3}]
SetGpus = Callable[[list[dict]], None]


def cmd(code: str) -> list[str]:
    return [PY, "-c", code]


@pytest.fixture
def gpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SetGpus:
    """Point HYPOTHEX_FAKE_GPUS at a file; call the fixture to set the host's GPUs."""
    path = tmp_path / "fake-gpus.json"
    monkeypatch.setenv("HYPOTHEX_FAKE_GPUS", str(path))

    def write(entries: list[dict]) -> None:
        path.write_text(json.dumps(entries))

    write([])
    return write


def stdout_of(ctx: Context, run_id: str) -> str:
    return (ctx.run_dir(ctx.find_record(run_id)) / "logs" / "stdout.log").read_text().strip()


def with_gpus(indices: list[int]) -> Callable[[RunRecord], RunRecord]:
    def mutate(r: RunRecord) -> RunRecord:
        return r.model_copy(update={"executor": r.executor.model_copy(update={"gpus": indices})})

    return mutate


# launch options: gpus, queue marker, CUDA_VISIBLE_DEVICES -------------------------------
def test_prepare_run_records_gpus_requested_and_host(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    gpus(FOUR_GPUS)
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=2))
    assert rec.gpus_requested == 2
    assert rec.executor.host == ctx.descriptor.label
    assert rec.executor.gpus == []
    assert not (ctx.run_dir(rec) / QUEUE_FILE).exists()
    assert ctx.find_record(rec.run_id).gpus_requested == 2


def test_prepare_run_rejects_impossible_gpu_counts(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    gpus(FOUR_GPUS[:2])
    with pytest.raises(RunError, match="asked for 3 GPUs; this host has 2"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=3))
    with pytest.raises(RunError, match="gpus must be 0 or more, got -1"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=-1))
    assert ctx.store.list_run_ids() == {}


def test_prepare_run_never_writes_the_queue_marker(ctx: Context, toy_repo: Path) -> None:
    # only Scheduler.enqueue (under the scheduler lock) puts a run in the queue
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), queue=True))
    assert not (ctx.run_dir(rec) / QUEUE_FILE).exists()
    assert rec.status == RunStatus.QUEUED


def test_a_run_executes_at_most_once(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    # two supervisors for one run (a crashed start that was retried): one claim wins
    import threading

    out = tmp_path / "executions.txt"
    code = f"open({str(out)!r}, 'a').write('ran\\n')"
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(code)))
    barrier = threading.Barrier(2)
    results: list[object] = []

    def run() -> None:
        barrier.wait()
        try:
            results.append(execute_run(ctx, rec.run_id).status)
        except RunError as exc:
            results.append(str(exc))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert out.read_text() == "ran\n"
    assert RunStatus.FINISHED in results
    assert any(isinstance(r, str) and ("already being executed" in r or "not queued" in r)
               for r in results)  # fmt: skip
    assert (ctx.run_dir(rec) / EXECUTION_CLAIM).is_file()


def test_supervisor_that_does_not_own_the_run_never_executes_it(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    # its spawner died before writing supervisor.pid: the start never committed
    import subprocess

    out = tmp_path / "ran.txt"
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(f"open({str(out)!r}, 'w')")))
    done = subprocess.run(
        [PY, "-m", "hypothex.core.supervisor", rec.run_id, "--home", str(ctx.layout.home)],
        env={**os.environ, "HYPOTHEX_SUPERVISOR_WAIT": "0.5"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 1 and "supervisor.pid does not name this process" in done.stderr
    assert not out.exists()
    assert ctx.find_record(rec.run_id).status == RunStatus.QUEUED


def test_execute_run_sets_cuda_visible_devices_and_keeps_gpus(ctx: Context, toy_repo: Path) -> None:
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(CUDA)))
    ctx.update_run(rec.run_id, "run.gpus_assigned", with_gpus([1, 3]), {"gpus": [1, 3]})
    done = execute_run(ctx, rec.run_id)
    assert done.status == RunStatus.FINISHED
    assert stdout_of(ctx, rec.run_id) == "1,3"
    assert done.executor.gpus == [1, 3]
    assert done.executor.host == ctx.descriptor.label
    assert done.executor.pid == os.getpid() and done.executor.child_pid is not None


GATE_CRASH = """
import os
import sys
from pathlib import Path

from hypothex.core import execution
from hypothex.core.context import Context

home, run_id, point = sys.argv[1:4]
if point == "before_go":
    execution._open_gate = lambda proc: os._exit(9)  # child_pid is saved; no "go" yet
else:
    real = Context.update_run

    def update_run(self, rid, event_type, *args, **kwargs):
        if event_type == "run.started":
            os._exit(9)  # killed right after the spawn, before child_pid is saved
        return real(self, rid, event_type, *args, **kwargs)

    Context.update_run = update_run
execution.execute_run(Context.open(Path(home)), run_id)
"""


@pytest.mark.parametrize("point", ["before_child_pid", "before_go"])
def test_a_supervisor_killed_before_the_gate_opens_runs_nothing(
    ctx: Context,
    toy_repo: Path,
    tmp_path: Path,
    gpus: SetGpus,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    import subprocess
    import time

    import psutil

    from hypothex.core import control
    from hypothex.core.execution import SUPERVISOR_PID_FILE
    from hypothex.core.gpus import held_gpus

    gpus(FOUR_GPUS)
    out = tmp_path / "ran.txt"
    rec = prepare_run(
        ctx, RunRequest(repo=toy_repo, command=cmd(f"open({str(out)!r}, 'w')"), gpus=1)
    )
    ctx.update_run(rec.run_id, "run.gpus_assigned", with_gpus([0]), {"gpus": [0]})
    supervisor = subprocess.Popen([PY, "-c", GATE_CRASH, str(ctx.layout.home), rec.run_id, point])
    pid_file = ctx.run_dir(rec) / SUPERVISOR_PID_FILE  # as spawn_supervisor writes it
    pid_file.write_text(json.dumps({"pid": supervisor.pid, "create_time": None}))
    assert supervisor.wait(timeout=60) == 9

    def gated() -> list[psutil.Process]:
        found = []
        for proc in psutil.process_iter(["cmdline"]):
            if str(out) in " ".join(proc.info["cmdline"] or []):
                found.append(proc)
        return found

    deadline = time.monotonic() + 10
    while gated() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert gated() == []  # the gate read end-of-file and exited 97
    assert not out.exists()  # the command never ran
    assert held_gpus(ctx) == {0: rec.run_id}  # reserved until repair
    monkeypatch.setattr(control, "QUEUED_GRACE_SECONDS", 0.0)
    assert [r.run_id for r in control.repair_runs(ctx)] == [rec.run_id]
    assert ctx.find_record(rec.run_id).status == RunStatus.LOST
    assert held_gpus(ctx) == {}  # released safely: nothing runs on GPU 0
    assert not out.exists()


def test_execute_run_without_gpus_leaves_cuda_visible_devices_alone(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "7")
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(CUDA)))
    execute_run(ctx, rec.run_id)
    assert stdout_of(ctx, rec.run_id) == "7"


# commit pin and hub diff (spec 8A.4) ---------------------------------------------------
READ_MARKER = "print(open('marker.txt').read())"
BAD_DIFF = "diff --git a/nope.txt b/nope.txt\n--- a/nope.txt\n+++ b/nope.txt\n@@ -1 +1 @@\n-a\n+b\n"


def git_diff(repo: Path) -> str:
    # not tests.factories.git: that strips the trailing newline a patch needs
    out = subprocess.run(
        ["git", "-C", str(repo), "diff", "HEAD", "--binary"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def commit_marker(repo: Path, text: str) -> str:
    (repo / "marker.txt").write_text(text)
    git(repo, "add", "marker.txt")
    git(repo, "commit", "-qm", f"marker {text}")
    return git(repo, "rev-parse", "HEAD")


def worktrees(ctx: Context) -> list[Path]:
    folder = ctx.layout.worktrees_dir("toy")
    return sorted(folder.iterdir()) if folder.is_dir() else []


def test_hub_diff_is_applied_in_a_worktree(ctx: Context, toy_repo: Path) -> None:
    head = commit_marker(toy_repo, "old")
    (toy_repo / "marker.txt").write_text("patched")
    diff = git_diff(toy_repo)
    git(toy_repo, "checkout", "--", "marker.txt")
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(READ_MARKER), diff=diff))
    assert rec.cwd == str(ctx.layout.worktrees_dir("toy") / rec.run_id)
    assert rec.git.commit == head and rec.git.dirty
    assert (ctx.run_dir(rec) / "git.diff").read_text() == diff
    done = execute_run(ctx, rec.run_id)
    assert done.status == RunStatus.FINISHED
    assert stdout_of(ctx, rec.run_id) == "patched"
    assert (toy_repo / "marker.txt").read_text() == "old"


def test_same_commit_and_same_diff_runs_in_place(ctx: Context, toy_repo: Path) -> None:
    head = commit_marker(toy_repo, "old")
    (toy_repo / "marker.txt").write_text("dirty")
    req = RunRequest(repo=toy_repo, command=cmd(READ_MARKER), commit=head, diff=git_diff(toy_repo))
    rec = prepare_run(ctx, req)
    assert rec.cwd == str(toy_repo.resolve())
    assert worktrees(ctx) == []
    execute_run(ctx, rec.run_id)
    assert stdout_of(ctx, rec.run_id) == "dirty"


def test_pinned_commit_without_diff_ignores_local_edits(ctx: Context, toy_repo: Path) -> None:
    head = commit_marker(toy_repo, "old")
    (toy_repo / "marker.txt").write_text("local edit")
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(READ_MARKER), commit=head))
    assert rec.cwd == str(ctx.layout.worktrees_dir("toy") / rec.run_id)
    assert not rec.git.dirty
    execute_run(ctx, rec.run_id)
    assert stdout_of(ctx, rec.run_id) == "old"


def test_missing_commit_is_fetched_from_the_remote(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "-q", "--bare", str(toy_repo), str(remote))
    git(toy_repo, "remote", "add", "origin", str(remote))
    hub = tmp_path / "hub"
    git(tmp_path, "clone", "-q", str(remote), str(hub))
    sha = commit_marker(hub, "from hub")
    git(hub, "push", "-q", "origin", "HEAD:main")
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(READ_MARKER), commit=sha[:10]))
    assert rec.git.commit == sha
    execute_run(ctx, rec.run_id)
    assert stdout_of(ctx, rec.run_id) == "from hub"


def test_unknown_commit_fails_cleanly(ctx: Context, toy_repo: Path) -> None:
    missing = "0123456789abcdef0123456789abcdef01234567"
    with pytest.raises(RunError, match=r"0123456789ab is not in .*even after `git fetch`"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), commit=missing))
    assert ctx.store.list_run_ids() == {}
    assert worktrees(ctx) == []


def test_diff_that_does_not_apply_leaves_nothing_behind(ctx: Context, toy_repo: Path) -> None:
    with pytest.raises(RunError, match="could not apply the saved diff"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), diff=BAD_DIFF))
    assert ctx.store.list_run_ids() == {}
    assert worktrees(ctx) == []
    assert git(toy_repo, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_missing_command_in_the_worktree_removes_it(ctx: Context, toy_repo: Path) -> None:
    head = commit_marker(toy_repo, "old")
    with pytest.raises(RunError, match=r"command not found: \./nope\.sh"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=["./nope.sh"], commit=head, diff=""))
    (toy_repo / "marker.txt").write_text("edit")
    with pytest.raises(RunError, match=r"command not found: \./nope\.sh"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=["./nope.sh"], commit=head))
    assert ctx.store.list_run_ids() == {}
    assert worktrees(ctx) == []
    assert git(toy_repo, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_diff_needs_a_git_repo(ctx: Context, tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "plain", use_git=False)
    with pytest.raises(RunError, match="is not a git repository with a commit"):
        prepare_run(ctx, RunRequest(repo=repo, command=cmd("pass"), diff=BAD_DIFF))
    assert ctx.store.list_run_ids() == {}


@pytest.mark.parametrize("commit", ["--upload-pack=touch /tmp/x", "HEAD~1", "main", "abc", "g123"])
def test_commit_must_be_a_hex_sha(ctx: Context, toy_repo: Path, commit: str) -> None:
    with pytest.raises(RunError, match="is not a hex sha"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), commit=commit))
    assert ctx.store.list_run_ids() == {}
    assert worktrees(ctx) == []


def test_failure_after_the_worktree_exists_removes_it(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core import execution

    head = commit_marker(toy_repo, "old")
    (toy_repo / "marker.txt").write_text("local edit")  # dirty: a worktree is needed

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("env capture failed")

    monkeypatch.setattr(execution, "capture_env", boom)
    with pytest.raises(OSError, match="env capture failed"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(READ_MARKER), commit=head))
    assert worktrees(ctx) == []
    assert git(toy_repo, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_pinned_commit_supplies_config_stages_datasets_and_repo(
    ctx: Context, toy_repo: Path
) -> None:
    # the host checkout is behind the hub: the stage, the task, the dataset, and
    # train.py exist only at the pinned commit
    base = git(toy_repo, "rev-parse", "HEAD")
    config = yaml.safe_load((toy_repo / "hypothex.yaml").read_text())
    config["stages"]["fit"] = f"{shlex.quote(PY)} {{repo}}/train.py {{dataset.path}}"
    config["datasets"]["newset"] = {
        "version": "v2",
        "path": "data/new.jsonl",
        "splits": {"test": "data/new.jsonl"},
    }
    config["tasks"]["new-task"] = {
        "dataset": "newset",
        "split": "test",
        "metrics": ["accuracy"],
        "primary": "accuracy",
    }
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    (toy_repo / "data" / "new.jsonl").write_text('{"id": "ex-0", "reference": 1}\n')
    (toy_repo / "train.py").write_text(
        "import sys\nprint('pinned', open(sys.argv[1]).read().strip())\n"
    )
    git(toy_repo, "add", "-A")
    git(toy_repo, "commit", "-qm", "new stage, task, and dataset")
    pinned = git(toy_repo, "rev-parse", "HEAD")
    git(toy_repo, "checkout", "-q", base)  # the host checkout stays at the old commit
    assert not (toy_repo / "train.py").exists()
    req = RunRequest(repo=toy_repo, stage="fit", task="new-task", commit=pinned)
    rec = prepare_run(ctx, req)
    tree = ctx.layout.worktrees_dir("toy") / rec.run_id
    assert rec.cwd == str(tree)
    assert rec.command[1:] == [f"{tree}/train.py", str(tree / "data" / "new.jsonl")]
    assert [(d.name, d.version) for d in rec.datasets] == [("newset", "v2")]
    assert rec.git.commit == pinned
    assert ctx.store.load_project("toy").repo == str(toy_repo.resolve())
    assert execute_run(ctx, rec.run_id).status == RunStatus.FINISHED
    assert stdout_of(ctx, rec.run_id) == 'pinned {"id": "ex-0", "reference": 1}'


def test_pinned_commit_of_another_project_is_refused(ctx: Context, toy_repo: Path) -> None:
    config = yaml.safe_load((toy_repo / "hypothex.yaml").read_text())
    config["project"] = "other"
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    git(toy_repo, "commit", "-qam", "rename the project")
    renamed = git(toy_repo, "rev-parse", "HEAD")
    git(toy_repo, "checkout", "-q", "HEAD~1")
    with pytest.raises(RunError, match="names project 'other', not 'toy'"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), commit=renamed))
    assert ctx.store.list_run_ids() == {}
    assert worktrees(ctx) == []


# scheduler: FIFO first fit --------------------------------------------------------------
def queue_run(ctx: Context, repo: Path, n: int, code: str = CUDA) -> str:
    rec = prepare_run(
        ctx,
        RunRequest(repo=repo, command=cmd(code), gpus=n, queue=True, hypothesis=f"needs {n}"),
    )
    Scheduler(ctx).enqueue(rec.run_id)
    return rec.run_id


def test_enqueue_returns_fifo_positions(ctx: Context, toy_repo: Path, gpus: SetGpus) -> None:
    gpus(FOUR_GPUS)
    first = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=1))
    assert Scheduler(ctx).enqueue(first.run_id) == 1  # writes the marker itself
    assert (ctx.run_dir(first) / QUEUE_FILE).is_file()
    rest = [queue_run(ctx, toy_repo, 1) for _ in range(2)]
    ids = [first.run_id, *rest]
    assert Scheduler(ctx).positions() == {ids[0]: 1, ids[1]: 2, ids[2]: 3}
    assert [ctx.find_record(r).executor.queue_position for r in ids] == [1, 2, 3]
    assert [e.run_id for e in ctx.events.since(0) if e.type == "run.enqueued"] == ids


def test_enqueue_rejects_runs_that_cannot_wait(ctx: Context, toy_repo: Path, gpus: SetGpus) -> None:
    gpus(FOUR_GPUS[:2])
    done = execute_run(ctx, prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"))).run_id)
    with pytest.raises(RunError, match="only queued runs can wait"):
        Scheduler(ctx).enqueue(done.run_id)
    big = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=2))
    gpus(FOUR_GPUS[:1])
    with pytest.raises(RunError, match="asks for 2 GPUs; this host has 1"):
        Scheduler(ctx).enqueue(big.run_id)
    assert not (ctx.run_dir(big) / QUEUE_FILE).exists()


def test_tick_starts_runs_fifo_first_fit_with_their_gpus(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    gpus([{"index": 0, "external": True}, {"index": 1}, {"index": 2}, {"index": 3}])
    a = queue_run(ctx, toy_repo, 4)  # never fits while GPU 0 is busy
    b = queue_run(ctx, toy_repo, 2)
    c = queue_run(ctx, toy_repo, 1)
    d = queue_run(ctx, toy_repo, 1)
    sched = Scheduler(ctx)
    assert sched.tick() == [b, c]
    assert ctx.find_record(b).executor.gpus == [1, 2]
    assert ctx.find_record(c).executor.gpus == [3]
    assert ctx.find_record(b).executor.queue_position is None
    assert not (ctx.run_dir(ctx.find_record(b)) / QUEUE_FILE).exists()
    assert sched.positions() == {a: 1, d: 2}
    assert ctx.find_record(d).executor.queue_position == 4  # its ticket: never rewritten
    assert [wait_for_run(ctx, r, timeout=60).status for r in (b, c)] == [RunStatus.FINISHED] * 2
    assert stdout_of(ctx, b) == "1,2"
    assert stdout_of(ctx, c) == "3"
    assert sched.tick() == [d]  # a still needs 4 GPUs; only 3 are free
    assert ctx.find_record(d).executor.gpus == [1]
    assert wait_for_run(ctx, d, timeout=60).status == RunStatus.FINISHED
    assert stdout_of(ctx, d) == "1"
    assert ctx.find_record(a).status == RunStatus.QUEUED
    assert sched.positions() == {a: 1}
    types = [e.type for e in ctx.events.since(0) if e.run_id == b]
    assert types.index("run.gpus_assigned") < types.index("run.launched")


def test_gpu_held_by_a_running_hx_run_is_not_free(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    gpus([{"index": 0}])  # nvidia-smi shows nothing on it: the hx run has not touched it yet
    ctx.create_run(
        make_record(
            "holder",
            status=RunStatus.RUNNING,
            environment_id=ctx.descriptor.environment_id,
            executor=ExecutorInfo(pid=os.getpid(), gpus=[0]),
        )
    )
    waiting = queue_run(ctx, toy_repo, 1)
    sched = Scheduler(ctx)
    assert sched.tick() == []
    assert sched.positions() == {waiting: 1}
    ctx.update_run(
        "holder", "run.finished", lambda r: r.model_copy(update={"status": RunStatus.FINISHED})
    )
    assert sched.tick() == [waiting]
    assert wait_for_run(ctx, waiting, timeout=60).status == RunStatus.FINISHED
    assert stdout_of(ctx, waiting) == "0"


def test_fifo_survives_the_host_clock_stepping_back(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review Focus: NTP or a VM resume steps the host clock back between two launches.
    gpus([{"index": 0, "external": True}])  # nothing can start
    first = queue_run(ctx, toy_repo, 1)
    real_now = execution.utcnow
    monkeypatch.setattr(execution, "utcnow", lambda: real_now() - timedelta(hours=1))
    second = queue_run(ctx, toy_repo, 1)
    assert Scheduler(ctx).positions() == {first: 1, second: 2}
    assert ctx.find_record(second).executor.queue_position == 2
    assert ctx.find_record(first).executor.queue_position == 1


def test_cpu_only_queued_run_starts_on_a_host_without_gpus(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    gpus([])
    rid = queue_run(ctx, toy_repo, 0, code="print('cpu')")
    assert Scheduler(ctx).tick() == [rid]
    done = wait_for_run(ctx, rid, timeout=60)
    assert done.status == RunStatus.FINISHED and done.executor.gpus == []
    assert stdout_of(ctx, rid) == "cpu"


def test_scheduler_loop_ticks_until_stopped(ctx: Context, toy_repo: Path, gpus: SetGpus) -> None:
    gpus([])
    rid = queue_run(ctx, toy_repo, 0, code="print('looped')")
    stop = threading.Event()
    thread = threading.Thread(
        target=run_scheduler_loop, args=(ctx, stop), kwargs={"interval": 0.05}
    )
    thread.start()
    try:
        assert wait_for_run(ctx, rid, timeout=60).status == RunStatus.FINISHED
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert stdout_of(ctx, rid) == "looped"


def test_scheduler_loop_survives_a_failing_tick(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = threading.Event()
    calls: list[int] = []

    def flaky(self: Scheduler) -> list[str]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("nvidia-smi exploded")
        if len(calls) == 3:
            stop.set()
        return []

    monkeypatch.setattr(Scheduler, "tick", flaky)
    run_scheduler_loop(ctx, stop, interval=0.01)
    assert len(calls) == 3


class Crash(BaseException):
    """The env server dies right here (a BaseException: nothing on the way catches it)."""


def counting(out: Path) -> str:
    """Code that appends one line to ``out`` per execution."""
    return f"open({str(out)!r}, 'a').write('ran\\n')"


def test_crash_between_gpu_assignment_and_spawn_frees_the_gpus(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpus([{"index": 0}])
    rid = queue_run(ctx, toy_repo, 1)
    real = scheduler_module.spawn_supervisor

    def crash(c: Context, r: RunRecord) -> int:
        raise Crash

    monkeypatch.setattr(scheduler_module, "spawn_supervisor", crash)
    with pytest.raises(Crash):
        Scheduler(ctx).tick()
    assert ctx.find_record(rid).executor.gpus == [0]  # the reservation the crash left
    assert free_gpus(gpu_status(ctx)) == []
    monkeypatch.setattr(scheduler_module, "spawn_supervisor", real)  # the server restarts
    assert Scheduler(ctx).tick() == [rid]  # released, then assigned again, then started
    assert wait_for_run(ctx, rid, timeout=60).status == RunStatus.FINISHED
    assert stdout_of(ctx, rid) == "0"
    types = [e.type for e in ctx.events.since(0) if e.run_id == rid]
    assert types.count("run.gpus_released") == 1 and types.count("run.launched") == 1


def test_a_run_whose_start_was_cut_short_gets_a_ticket_ahead_of_later_runs(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpus([{"index": 0}])
    first = queue_run(ctx, toy_repo, 1)
    second = queue_run(ctx, toy_repo, 1)

    def crash(c: Context, r: RunRecord) -> int:
        raise Crash

    monkeypatch.setattr(scheduler_module, "spawn_supervisor", crash)
    with pytest.raises(Crash):
        Scheduler(ctx).tick()
    assert ctx.find_record(first).executor.queue_position is None  # the start cleared it
    gpus([{"index": 0, "external": True}])  # the restarted server starts nothing
    assert Scheduler(ctx).tick() == []
    assert Scheduler(ctx).positions() == {first: 1, second: 2}
    tickets = [ctx.find_record(r).executor.queue_position for r in (first, second)]
    assert tickets == [1, 2]


def test_starts_and_stops_never_rewrite_the_runs_behind(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    # DF-46: each start used to rewrite every waiting run (n(n-1)/2 events for n runs)
    gpus([{"index": 0, "external": True}])  # nothing starts while the queue fills
    ids = [queue_run(ctx, toy_repo, 1, code="pass") for _ in range(8)]
    assert [ctx.find_record(r).executor.queue_position for r in ids] == list(range(1, 9))
    stop_run(ctx, ids[0])
    gpus([{"index": 0}])
    sched = Scheduler(ctx)
    for expected in ids[1:]:
        assert sched.positions()[expected] == 1
        assert sched.tick() == [expected]
        assert wait_for_run(ctx, expected, timeout=60).status == RunStatus.FINISHED
    types = [e.type for e in ctx.events.since(0)]
    assert types.count("run.queue_moved") == 0
    assert types.count("run.enqueued") == 8
    late = queue_run(ctx, toy_repo, 1, code="pass")
    assert ctx.find_record(late).executor.queue_position == 1  # an empty queue starts over


def test_crash_after_spawn_never_starts_the_run_twice(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gpus([{"index": 0}, {"index": 1}])
    out = tmp_path / "executions.txt"
    rid = queue_run(ctx, toy_repo, 1, code=counting(out))
    real = scheduler_module.spawn_supervisor

    def spawn_then_crash(c: Context, r: RunRecord) -> int:
        real(c, r)
        raise Crash  # before queue.json is deleted

    monkeypatch.setattr(scheduler_module, "spawn_supervisor", spawn_then_crash)
    with pytest.raises(Crash):
        Scheduler(ctx).tick()
    monkeypatch.setattr(scheduler_module, "spawn_supervisor", real)
    assert Scheduler(ctx).tick() == []  # recovered as started, never spawned again
    assert wait_for_run(ctx, rid, timeout=60).status == RunStatus.FINISHED
    assert out.read_text() == "ran\n"
    launched = [e for e in ctx.events.since(0) if e.run_id == rid and e.type == "run.launched"]
    assert len(launched) == 1
    assert not (ctx.run_dir(ctx.find_record(rid)) / QUEUE_FILE).exists()
    assert (ctx.run_dir(ctx.find_record(rid)) / EXECUTION_CLAIM).is_file()


def test_a_tick_removes_the_queue_marker_of_a_run_that_ended(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    # killed while it waited, but its queue.json stayed (a crash before the removal)
    gpus([{"index": 0, "external": True}])  # busy: nothing starts
    rid = queue_run(ctx, toy_repo, 1)
    marker = ctx.run_dir(ctx.find_record(rid)) / QUEUE_FILE
    ctx.update_run(rid, "run.killed", lambda r: r.model_copy(update={"status": RunStatus.KILLED}))
    assert marker.is_file()
    assert Scheduler(ctx).tick() == []
    assert not marker.exists()
    assert Scheduler(ctx).positions() == {}


def test_a_start_that_never_committed_frees_the_gpus_and_runs_nothing(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gpus([{"index": 0}])
    out = tmp_path / "executions.txt"
    rid = queue_run(ctx, toy_repo, 1, code=counting(out))
    real_write = execution.atomic_write_text

    def no_pid_file(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path).name == "supervisor.pid":
            raise OSError(28, "No space left on device")
        real_write(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(execution, "atomic_write_text", no_pid_file)
    assert Scheduler(ctx).tick() == []
    monkeypatch.setattr(execution, "atomic_write_text", real_write)
    failed = ctx.find_record(rid)
    assert failed.status == RunStatus.FAILED
    assert free_gpus(gpu_status(ctx)) == [0]
    reasons = [e.payload["reason"] for e in ctx.events.since(0) if e.type == "run.failed"]
    assert "No space left on device" in reasons[0]
    for _ in range(30):  # the supervisor Popen made was killed and never claims the run
        assert not out.exists()
        assert not (ctx.run_dir(failed) / EXECUTION_CLAIM).exists()
        time.sleep(0.1)


def test_a_launch_event_that_fails_after_the_spawn_still_counts_as_started(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gpus([{"index": 0}])
    out = tmp_path / "executions.txt"
    rid = queue_run(ctx, toy_repo, 1, code=counting(out))
    real_emit = ctx.emit

    def emit(event_type: str, *args: object, **kwargs: object) -> object:
        if event_type == "run.launched":
            raise OSError(28, "No space left on device")
        return real_emit(event_type, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ctx, "emit", emit)
    assert Scheduler(ctx).tick() == [rid]  # the supervisor runs, so the run is started
    monkeypatch.undo()
    assert wait_for_run(ctx, rid, timeout=60).status == RunStatus.FINISHED
    assert out.read_text() == "ran\n"
    assert not (ctx.run_dir(ctx.find_record(rid)) / QUEUE_FILE).exists()
    types = [e.type for e in ctx.events.since(0) if e.run_id == rid]
    assert "run.failed" not in types


# control: queued and GPU launches, stop, repair -----------------------------------------
def dead_pid() -> int:
    proc = subprocess.Popen([PY, "-c", "pass"])
    proc.wait()
    return proc.pid


def age_and_orphan(ctx: Context, run_id: str) -> None:
    """Make a queued run look 30 min old with a launcher that has exited."""
    gone = dead_pid()

    def mutate(r: RunRecord) -> RunRecord:
        executor = r.executor.model_copy(update={"pid": gone, "pid_create_time": None})
        return r.model_copy(
            update={"created_at": utcnow() - timedelta(minutes=30), "executor": executor}
        )

    ctx.update_run(run_id, "run.test_aged", mutate)


def test_launch_with_queue_waits_for_the_scheduler(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    gpus([{"index": 0, "external": True}, {"index": 1}])
    rec = launch_run(ctx, RunRequest(repo=toy_repo, command=cmd(CUDA), gpus=1, queue=True))
    assert rec.status == RunStatus.QUEUED and rec.executor.queue_position == 1
    assert not (ctx.run_dir(rec) / "supervisor.pid").exists()
    assert Scheduler(ctx).tick() == [rec.run_id]
    assert wait_for_run(ctx, rec.run_id, timeout=60).status == RunStatus.FINISHED
    assert stdout_of(ctx, rec.run_id) == "1"


def test_launch_with_gpus_takes_free_gpus_now(ctx: Context, toy_repo: Path, gpus: SetGpus) -> None:
    gpus([{"index": 0, "external": True}, {"index": 1}, {"index": 2}])
    rec = launch_run(ctx, RunRequest(repo=toy_repo, command=cmd(CUDA), gpus=2))
    assert rec.executor.gpus == [1, 2]
    types = [e.type for e in ctx.events.since(0) if e.run_id == rec.run_id]
    assert types[0] == "run.created"
    assert types.index("run.gpus_assigned") < types.index("run.launched")
    assert wait_for_run(ctx, rec.run_id, timeout=60).status == RunStatus.FINISHED
    assert stdout_of(ctx, rec.run_id) == "1,2"


def test_launch_with_too_few_gpus_fails_before_creating_anything(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    gpus([{"index": 0, "external": True}, {"index": 1}, {"index": 2}])
    with pytest.raises(RunError, match="3 GPUs requested; 2 of 3 free; add --queue"):
        launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=3))
    with pytest.raises(RunError, match="asked for 4 GPUs; this host has 3"):
        launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=4))
    with pytest.raises(RunError, match="asked for 4 GPUs; this host has 3"):
        launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=4, queue=True))
    assert ctx.store.list_run_ids() == {}


def test_stop_removes_a_queued_run_from_the_queue(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    gpus([{"index": 0, "external": True}])
    first = launch_run(ctx, RunRequest(repo=toy_repo, command=cmd(CUDA), gpus=1, queue=True))
    second = launch_run(ctx, RunRequest(repo=toy_repo, command=cmd(CUDA), gpus=1, queue=True))
    assert ctx.find_record(second.run_id).executor.queue_position == 2
    start = time.monotonic()
    stopped = stop_run(ctx, first.run_id)
    assert time.monotonic() - start < 2
    assert stopped.status == RunStatus.KILLED and stopped.executor.queue_position is None
    assert not (ctx.run_dir(stopped) / QUEUE_FILE).exists()
    killed = [e for e in ctx.events.since(0) if e.run_id == first.run_id and e.type == "run.killed"]
    assert [e.payload["reason"] for e in killed] == ["removed from queue"]
    sched = Scheduler(ctx)
    assert sched.positions() == {second.run_id: 1}
    assert ctx.find_record(second.run_id).executor.queue_position == 2  # the ticket stays
    gpus([{"index": 0}])
    assert sched.tick() == [second.run_id]
    assert wait_for_run(ctx, second.run_id, timeout=60).status == RunStatus.FINISHED
    assert stdout_of(ctx, second.run_id) == "0"


def test_startup_repair_keeps_queued_runs_queued(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    gpus([{"index": 0, "external": True}])
    waiting = launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=1, queue=True))
    age_and_orphan(ctx, waiting.run_id)
    # the same state without the queue marker is an orphan and is lost
    orphan = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass")))
    age_and_orphan(ctx, orphan.run_id)
    assert [r.run_id for r in repair_runs(ctx)] == [orphan.run_id]
    after = ctx.find_record(waiting.run_id)
    assert after.status == RunStatus.QUEUED and after.executor.queue_position == 1
    assert Scheduler(ctx).positions() == {waiting.run_id: 1}


def test_gpu_launch_prepares_the_run_without_holding_the_scheduler_lock(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core import control
    from hypothex.core.scheduler import scheduler_lock

    gpus([{"index": 0}, {"index": 1}])
    inside = threading.Event()
    release = threading.Event()
    real = control.prepare_run

    def slow_prepare(c: Context, req: RunRequest) -> RunRecord:
        inside.set()
        assert release.wait(10)
        return real(c, req)

    monkeypatch.setattr(control, "prepare_run", slow_prepare)
    done: list[RunRecord] = []
    worker = threading.Thread(
        target=lambda: done.append(
            launch_run(ctx, RunRequest(repo=toy_repo, command=cmd(CUDA), gpus=1))
        )
    )
    worker.start()
    assert inside.wait(10)
    took = threading.Event()

    def grab() -> None:
        with scheduler_lock(ctx):  # a tick or an enqueue while the run is prepared
            took.set()

    grabber = threading.Thread(target=grab)
    grabber.start()
    assert took.wait(5), "scheduler_lock was held during prepare_run"
    release.set()
    worker.join(30)
    grabber.join(5)
    assert done[0].executor.gpus == [0]
    assert wait_for_run(ctx, done[0].run_id, timeout=60).status == RunStatus.FINISHED


def test_gpus_taken_while_preparing_fail_the_new_run(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core import control

    gpus([{"index": 0}])
    real = control.prepare_run

    def prepare_then_lose_the_gpu(c: Context, req: RunRequest) -> RunRecord:
        record = real(c, req)
        gpus([{"index": 0, "external": True}])  # another user's process took GPU 0
        return record

    monkeypatch.setattr(control, "prepare_run", prepare_then_lose_the_gpu)
    with pytest.raises(RunError, match=r"1 GPUs requested; 0 of 1 free now .*add --queue"):
        launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=1))
    [run_id] = list(ctx.index.run_ids())
    failed = ctx.find_record(run_id)
    assert failed.status == RunStatus.FAILED and failed.executor.gpus == []
    assert not (ctx.run_dir(failed) / "supervisor.pid").exists()
    reasons = [e.payload["reason"] for e in ctx.events.since(0) if e.type == "run.failed"]
    assert reasons and "taken while the run was prepared" in reasons[0]


def test_a_tick_between_prepare_and_enqueue_cannot_start_the_run(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core import control

    gpus([{"index": 0}])
    real = control.prepare_run

    def prepare_then_tick(c: Context, req: RunRequest) -> RunRecord:
        record = real(c, req)
        assert Scheduler(c).tick() == []  # the scheduler loop runs right here
        return record

    monkeypatch.setattr(control, "prepare_run", prepare_then_tick)
    rec = launch_run(ctx, RunRequest(repo=toy_repo, command=cmd(CUDA), gpus=1, queue=True))
    monkeypatch.setattr(control, "prepare_run", real)
    assert rec.status == RunStatus.QUEUED and rec.executor.queue_position == 1
    assert not (ctx.run_dir(rec) / "supervisor.pid").exists()
    types = [e.type for e in ctx.events.since(0) if e.run_id == rec.run_id]
    assert types.count("run.enqueued") == 1 and "run.launched" not in types
    assert Scheduler(ctx).tick() == [rec.run_id]
    assert wait_for_run(ctx, rec.run_id, timeout=60).status == RunStatus.FINISHED


def test_direct_gpu_launch_whose_spawn_fails_frees_the_gpus(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core import control

    gpus([{"index": 0}])

    def broken(c: Context, r: RunRecord) -> int:
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(control, "spawn_supervisor", broken)
    with pytest.raises(RunError, match="could not start the supervisor"):
        launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=1))
    [run_id] = list(ctx.index.run_ids())
    assert ctx.find_record(run_id).status == RunStatus.FAILED
    assert free_gpus(gpu_status(ctx)) == [0]


# environment kind, hx serve --kind, and the scheduler loop in the server -----------------
def test_resolve_serve_kind_defaults_saves_and_rejects(tmp_path: Path) -> None:
    home = tmp_path / "srv"
    assert resolve_serve_kind(home, None) == "local"
    env_id = json.loads((home / "environment.json").read_text())["environment_id"]
    assert resolve_serve_kind(home, "ssh") == "ssh"
    saved = json.loads((home / "environment.json").read_text())
    assert saved["kind"] == "ssh" and saved["environment_id"] == env_id
    assert resolve_serve_kind(home, None) == "ssh"
    with pytest.raises(ConfigError, match="--kind must be ssh or slurm, got 'gpu'"):
        resolve_serve_kind(home, "gpu")
    descriptor = Context.open(home).descriptor
    assert (descriptor.environment_id, descriptor.kind) == (env_id, "ssh")


def test_serve_rejects_an_unknown_kind_before_starting(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="got 'gpu'"):
        CliRunner().invoke(
            app, ["--home", str(tmp_path / "srv"), "serve", "--kind", "gpu"], catch_exceptions=False
        )


def test_server_kind_sets_the_descriptor_and_runs_the_scheduler(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks: list[int] = []

    def tick(self: Scheduler) -> list[str]:
        ticks.append(1)
        return []

    monkeypatch.setattr(Scheduler, "tick", tick)
    monkeypatch.setattr(app_module, "SCHEDULER_INTERVAL_SECONDS", 0.01)
    base = "http://127.0.0.1:7777"
    with TestClient(create_app(home, kind="ssh"), base_url=base) as client:
        assert client.get("/.well-known/hypothex/environment").json()["kind"] == "ssh"
        deadline = time.monotonic() + 5
        while len(ticks) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(ticks) >= 2
    assert not any(t.name == "hx-scheduler" for t in threading.enumerate())
    ticks.clear()
    with TestClient(create_app(home, kind="slurm"), base_url=base) as client:
        assert client.get("/.well-known/hypothex/environment").json()["kind"] == "slurm"
        time.sleep(0.2)
    assert ticks == []
    with pytest.raises(ValueError, match="kind"):
        create_app(home, kind="gpu")


def test_queued_run_starts_from_the_server_loop(
    home: Path, ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpus([])
    monkeypatch.setattr(app_module, "SCHEDULER_INTERVAL_SECONDS", 0.05)
    rid = queue_run(ctx, toy_repo, 0, code="print('served')")
    with TestClient(create_app(home, kind="ssh"), base_url="http://127.0.0.1:7777"):
        assert wait_for_run(ctx, rid, timeout=60).status == RunStatus.FINISHED
    assert stdout_of(ctx, rid) == "served"


# review fixes: pinned config snapshot, pinned scoring, unstarted runs, queue errors ------
def add_task_at_new_commit(repo: Path) -> tuple[str, str]:
    """Commit a new task and a ``fit`` stage that predicts it; return (base, new) shas."""
    base = git(repo, "rev-parse", "HEAD")
    config = yaml.safe_load((repo / "hypothex.yaml").read_text())
    config["stages"]["fit"] = f"{shlex.quote(PY)} {{repo}}/train.py"
    config["tasks"]["new-task"] = {
        "dataset": "toyset",
        "split": "test",
        "metrics": ["accuracy"],
        "primary": "accuracy",
    }
    (repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    (repo / "train.py").write_text(
        "import json, os\n"
        "d = os.environ['HYPOTHEX_RUN_DIR']\n"
        "with open(d + '/predictions/predictions.jsonl', 'w') as fh:\n"
        "    for i, p in enumerate([0, 1, 0, 0]):\n"
        "        fh.write(json.dumps({'id': f'ex-{i}', 'prediction': p}) + '\\n')\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "new task")
    return base, git(repo, "rev-parse", "HEAD")


def test_pinned_launch_keeps_the_stored_project_config(ctx: Context, toy_repo: Path) -> None:
    base, _ = add_task_at_new_commit(toy_repo)
    ctx.register_project(toy_repo)
    assert "new-task" in ctx.store.load_project("toy").config.tasks
    prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), commit=base))
    assert "new-task" in ctx.store.load_project("toy").config.tasks


def test_pinned_run_is_scored_with_its_own_checkout(ctx: Context, toy_repo: Path) -> None:
    # the task exists only at the pinned commit; the host checkout is behind
    base, new = add_task_at_new_commit(toy_repo)
    git(toy_repo, "checkout", "-q", base)
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, stage="fit", task="new-task", commit=new))
    done = execute_run(ctx, rec.run_id)
    assert done.status == RunStatus.FINISHED
    types = [e.type for e in ctx.events.since(0) if e.run_id == rec.run_id]
    assert "run.eval_skipped" not in types
    assert [s.value for s in ctx.store.read_scores("toy", rec.run_id)] == [1.0]


def test_foreground_rerun_of_a_gpu_parent_takes_free_gpus(
    ctx: Context, toy_repo: Path, gpus: SetGpus
) -> None:
    from hypothex.core.control import rerun

    gpus([{"index": 0, "external": True}, {"index": 1}])
    parent = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(CUDA), gpus=1))
    execute_run(ctx, parent.run_id)
    child = rerun(ctx, parent.run_id, background=False)
    assert child.status == RunStatus.FINISHED
    assert child.executor.gpus == [1]
    assert stdout_of(ctx, child.run_id) == "1"
    gpus([{"index": 0, "external": True}, {"index": 1, "external": True}])
    with pytest.raises(RunError, match="1 GPUs requested; 0 of 2 free"):
        rerun(ctx, parent.run_id, background=False)


def test_unstarted_failures_clear_the_gpus_they_never_used(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core import control

    gpus([{"index": 0}])
    rid = queue_run(ctx, toy_repo, 1)
    real_write = execution.atomic_write_text

    def no_pid_file(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path).name == "supervisor.pid":
            raise OSError(28, "No space left on device")
        real_write(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(execution, "atomic_write_text", no_pid_file)
    assert Scheduler(ctx).tick() == []
    failed = ctx.find_record(rid)
    assert failed.status == RunStatus.FAILED
    assert failed.executor.gpus == [] and failed.executor.queue_position is None
    monkeypatch.setattr(execution, "atomic_write_text", real_write)

    def broken(c: Context, r: RunRecord) -> int:
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(control, "spawn_supervisor", broken)
    with pytest.raises(RunError, match="could not start the supervisor"):
        launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=1))
    [other] = [r for r in ctx.index.run_ids() if r != rid]
    assert ctx.find_record(other).status == RunStatus.FAILED
    assert ctx.find_record(other).executor.gpus == []


@pytest.mark.parametrize("error", [OSError(28, "No space left on device"), ConfigError("bad")])
def test_any_enqueue_error_fails_the_queued_run(
    ctx: Context,
    toy_repo: Path,
    gpus: SetGpus,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    gpus([{"index": 0}])

    def broken(self: Scheduler, run_id: str) -> int:
        raise error

    monkeypatch.setattr(Scheduler, "enqueue", broken)
    with pytest.raises(type(error)):
        launch_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), gpus=1, queue=True))
    [run_id] = list(ctx.index.run_ids())
    assert ctx.find_record(run_id).status == RunStatus.FAILED
    reasons = [e.payload["reason"] for e in ctx.events.since(0) if e.type == "run.failed"]
    assert str(error) in reasons[0]


def test_ticks_scan_only_active_runs_after_the_first(
    ctx: Context, toy_repo: Path, gpus: SetGpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpus([{"index": 0, "external": True}])  # busy: nothing starts
    rid = queue_run(ctx, toy_repo, 1)
    marker = ctx.run_dir(ctx.find_record(rid)) / QUEUE_FILE
    ctx.update_run(rid, "run.killed", lambda r: r.model_copy(update={"status": RunStatus.KILLED}))
    globs: list[str] = []
    real_glob = Path.glob

    def counting_glob(self: Path, pattern: str, *args: object, **kwargs: object) -> object:
        if QUEUE_FILE in pattern:
            globs.append(pattern)
        return real_glob(self, pattern, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "glob", counting_glob)
    scheduler = Scheduler(ctx)
    scheduler.tick()
    assert not marker.exists()  # the first tick still sweeps stale markers
    assert len(globs) == 1
    other = queue_run(ctx, toy_repo, 1)
    for _ in range(3):
        scheduler.tick()
    assert len(globs) == 1
    assert Scheduler(ctx).positions() == {other: 1}


def test_a_clean_worktree_is_removed_when_its_run_ends(ctx: Context, toy_repo: Path) -> None:
    head = commit_marker(toy_repo, "old")
    (toy_repo / "marker.txt").write_text("patched")
    diff = git_diff(toy_repo)
    git(toy_repo, "checkout", "--", "marker.txt")
    code = "import sys; sys.dont_write_bytecode = False; print(open('marker.txt').read())"
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(code), commit=head, diff=diff))
    assert not Path(rec.cwd).exists()  # made when the run starts (DF-50)
    assert execute_run(ctx, rec.run_id).status == RunStatus.FINISHED
    assert stdout_of(ctx, rec.run_id) == "patched"
    assert worktrees(ctx) == []
    assert git(toy_repo, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_a_worktree_with_run_outputs_is_kept(ctx: Context, toy_repo: Path) -> None:
    head = commit_marker(toy_repo, "old")
    commit_marker(toy_repo, "new")
    code = "import os; os.makedirs('ckpt'); open('ckpt/last.pt', 'w').write('weights')"
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(code), commit=head))
    assert execute_run(ctx, rec.run_id).status == RunStatus.FINISHED
    assert (Path(rec.cwd) / "ckpt" / "last.pt").read_text() == "weights"
    assert worktrees(ctx) == [Path(rec.cwd)]
