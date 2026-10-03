import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

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
