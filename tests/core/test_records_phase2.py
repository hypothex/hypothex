from pathlib import Path

import pytest
from pydantic import ValidationError

from hypothex.core.fsutil import read_yaml
from hypothex.core.layout import Layout
from hypothex.core.records import CostTotals, ExecutorInfo, RunRecord
from hypothex.core.store import RunStore
from tests.factories import make_record

PHASE_1B_RUN = {
    "run_id": "r-1b",
    "project": "toy",
    "command": ["echo", "hi"],
    "command_template": ["echo", "hi"],
    "cwd": "/tmp",
    "environment_id": "env1",
    "host": "mac",
    "config_hash": "sha256:abc",
    "status": "finished",
    "created_at": "2026-09-30T10:00:00Z",
    "executor": {"type": "local", "pid": 41, "pid_create_time": 1.5, "child_pid": 42},
    "usage": {"tokens_in": 1, "tokens_out": 2, "usd": 0.5, "seconds": 1.0, "calls": 1},
}


def test_phase_1b_run_yaml_loads_with_phase_2_defaults() -> None:
    record = RunRecord.model_validate(PHASE_1B_RUN)
    assert record.executor.child_pid == 42
    assert record.executor.host is None and record.executor.gpus == []
    assert record.executor.slurm_job_id is None and record.executor.node is None
    assert record.executor.queue_position is None
    assert record.cost is None and record.sweep_id is None and record.gpus_requested == 0


def test_cost_totals_defaults() -> None:
    assert CostTotals().model_dump() == {
        "gpu_hours": 0.0,
        "gpu_usd": 0.0,
        "api_usd": 0.0,
        "total_usd": 0.0,
    }


def test_phase_2_fields_round_trip_through_run_yaml(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    layout.ensure()
    store = RunStore(layout)
    record = make_record(
        executor=ExecutorInfo(
            type="slurm", host="cluster", gpus=[0, 3], slurm_job_id="81234", node="gpu-n07"
        ),
        cost=CostTotals(gpu_hours=3.0, gpu_usd=6.3, api_usd=0.375, total_usd=6.675),
        sweep_id="sw-1a2b",
        gpus_requested=2,
    )
    store.create_run(record)
    raw = read_yaml(layout.run_dir("toy", "r1") / "run.yaml")
    assert raw["executor"]["gpus"] == [0, 3] and raw["executor"]["slurm_job_id"] == "81234"
    assert raw["cost"] == {"gpu_hours": 3.0, "gpu_usd": 6.3, "api_usd": 0.375, "total_usd": 6.675}
    loaded = store.read_record("toy", "r1")
    assert loaded.executor == record.executor
    assert loaded.cost == record.cost
    assert (loaded.sweep_id, loaded.gpus_requested) == ("sw-1a2b", 2)


def test_queue_position_is_one_based() -> None:
    assert ExecutorInfo(queue_position=1).queue_position == 1
    with pytest.raises(ValidationError):
        ExecutorInfo(queue_position=0)


def test_gpu_indices_and_request_are_not_negative() -> None:
    with pytest.raises(ValidationError):
        ExecutorInfo(gpus=[0, -1])
    with pytest.raises(ValidationError):
        make_record(gpus_requested=-1)
