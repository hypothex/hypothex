import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.execution import (
    EXECUTION_CLAIM,
    QUEUE_FILE,
    RunRequest,
    execute_run,
    prepare_run,
)
from hypothex.core.records import RunRecord, RunStatus
from tests.factories import git, write_toy_project

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
