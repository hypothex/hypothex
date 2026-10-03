"""Model-based test of the GPU queue (FIFO, first fit) against a small reference model."""

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,
)

from hypothex.core import scheduler as scheduler_module
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.execution import SUPERVISOR_PID_FILE
from hypothex.core.records import ACTIVE_STATUSES, RunRecord, RunStatus
from hypothex.core.scheduler import Scheduler
from tests.factories import make_record


def _fake_spawn(ctx: Context, record: RunRecord) -> int:
    """Commit the start like ``spawn_supervisor`` (pid file), then mark the run running."""
    (ctx.run_dir(record) / SUPERVISOR_PID_FILE).write_text(json.dumps({"pid": 1}))

    def running(r: RunRecord) -> RunRecord:
        return r.model_copy(update={"status": RunStatus.RUNNING})

    ctx.update_run(record.run_id, "run.launched", running)
    return 1


def _set_status(status: RunStatus):  # noqa: ANN202 - small local mutator factory
    def mutate(r: RunRecord) -> RunRecord:
        return r.model_copy(update={"status": status})

    return mutate


class GpuQueueMachine(RuleBasedStateMachine):
    """Drive a real ``Scheduler`` (tmp home, fake GPUs, fake supervisor) next to a model."""

    gpu_file: Path

    def __init__(self) -> None:
        super().__init__()
        self._tmp = tempfile.TemporaryDirectory()
        self.ctx = Context.open(Path(self._tmp.name) / "home")
        self.scheduler = Scheduler(self.ctx)
        self.total = 0
        self.external: set[int] = set()
        self.queue: list[str] = []  # waiting runs, FIFO
        self.need: dict[str, int] = {}
        self.running: dict[str, list[int]] = {}
        self.count = 0

    def teardown(self) -> None:
        self._tmp.cleanup()

    def _write_gpus(self) -> None:
        entries = [{"index": i, "external": i in self.external} for i in range(self.total)]
        self.gpu_file.write_text(json.dumps(entries))

    @initialize(total=st.integers(1, 4), external=st.sets(st.integers(0, 3), max_size=2))
    def gpus(self, total: int, external: set[int]) -> None:
        self.total = total
        self.external = {i for i in external if i < total}
        self._write_gpus()

    @rule(need=st.integers(0, 5))
    def enqueue(self, need: int) -> None:
        self.count += 1
        run_id = f"r{self.count:03d}"
        env = self.ctx.descriptor.environment_id
        self.ctx.create_run(make_record(run_id, environment_id=env, gpus_requested=need))
        if need > self.total:
            with pytest.raises(RunError, match="GPUs; this host has"):
                self.scheduler.enqueue(run_id)
            # it never joined the queue; end it so it does not linger as queued
            self.ctx.update_run(run_id, "run.killed", _set_status(RunStatus.KILLED))
            return
        position = self.scheduler.enqueue(run_id)
        self.queue.append(run_id)
        self.need[run_id] = need
        assert position == len(self.queue)
        assert self.ctx.find_record(run_id).executor.queue_position == position

    @rule()
    def tick(self) -> None:
        held = {g for gpus in self.running.values() for g in gpus}
        free = sorted(set(range(self.total)) - held - self.external)
        expected: list[str] = []
        for run_id in list(self.queue):
            if self.need[run_id] <= len(free):
                chosen, free = free[: self.need[run_id]], free[self.need[run_id] :]
                self.running[run_id] = chosen
                self.queue.remove(run_id)
                expected.append(run_id)
        assert self.scheduler.tick() == expected
        for run_id in expected:
            record = self.ctx.find_record(run_id)
            assert record.executor.gpus == self.running[run_id]
            assert record.executor.queue_position is None
            assert record.status == RunStatus.RUNNING
        for i, run_id in enumerate(self.queue, start=1):
            assert self.ctx.find_record(run_id).executor.queue_position == i

    @precondition(lambda self: bool(self.running))
    @rule(data=st.data())
    def finish(self, data: st.DataObject) -> None:
        run_id = data.draw(st.sampled_from(sorted(self.running)))
        self.ctx.update_run(run_id, "run.finished", _set_status(RunStatus.FINISHED))
        del self.running[run_id]

    @precondition(lambda self: bool(self.queue))
    @rule(data=st.data())
    def cancel_waiting(self, data: st.DataObject) -> None:
        run_id = data.draw(st.sampled_from(self.queue))
        self.ctx.update_run(run_id, "run.killed", _set_status(RunStatus.KILLED))
        self.queue.remove(run_id)

    @precondition(lambda self: self.total > 0)
    @rule(data=st.data())
    def toggle_external(self, data: st.DataObject) -> None:
        index = data.draw(st.integers(0, self.total - 1))
        self.external ^= {index}
        self._write_gpus()

    @invariant()
    def no_gpu_is_double_assigned(self) -> None:
        seen: list[int] = []
        for status in ACTIVE_STATUSES:
            for run in self.ctx.index.list_runs(status=status, include_archived=True, limit=None):
                seen.extend(run.executor.gpus)
        assert len(seen) == len(set(seen))
        assert all(0 <= g < self.total for g in seen)

    @invariant()
    def queue_order_is_fifo(self) -> None:
        assert self.scheduler.positions() == {r: i for i, r in enumerate(self.queue, start=1)}


def test_gpu_queue_matches_the_fifo_first_fit_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpu_file = tmp_path / "fake-gpus.json"
    monkeypatch.setenv("HYPOTHEX_FAKE_GPUS", str(gpu_file))
    monkeypatch.setattr(scheduler_module, "spawn_supervisor", _fake_spawn)
    GpuQueueMachine.gpu_file = gpu_file
    run_state_machine_as_test(
        GpuQueueMachine,
        settings=settings(
            max_examples=20,
            stateful_step_count=20,
            deadline=None,
            suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
        ),
    )
