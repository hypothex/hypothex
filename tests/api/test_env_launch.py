from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.execution import RunRequest
from hypothex.core.records import RunRecord, RunStatus
from hypothex.remote.config import SlurmDefaults
from tests.factories import make_record

BASE = "http://127.0.0.1:7777"


@pytest.fixture
def client(home: Path) -> Iterator[TestClient]:
    with TestClient(create_app(home, background_repair=False), base_url=BASE) as c:
        yield c


def test_launch_passes_phase2_fields_and_marks_the_sweep(
    client: TestClient, ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.register_project(toy_repo)
    seen: list[RunRequest] = []

    def fake_launch(c: Context, req: RunRequest) -> RunRecord:
        seen.append(req)
        return c.create_run(make_record("fake1", environment_id=c.descriptor.environment_id))

    monkeypatch.setattr(control, "launch_run", fake_launch)
    body = {
        "repo": str(toy_repo),
        "task": "toy-acc",
        "command": ["true"],
        "hypothesis": "h",
        "gpus": 2,
        "queue": True,
        "slurm": {"partition": "gpu", "time": "01:00:00"},
        "commit": "0a1b2c3d",
        "diff": "diff --git a/x b/x\n",
        "sweep_id": "s-abc123",
        "command_id": "L1",
    }
    out = client.post("/api/v1/runs", json=body).json()
    assert out["run_id"] == "fake1" and out["sweep_id"] == "s-abc123"
    [req] = seen
    assert (req.gpus, req.queue, req.diff) == (2, True, "diff --git a/x b/x\n")
    assert req.commit == "0a1b2c3d"
    assert req.slurm == SlurmDefaults(partition="gpu", time="01:00:00")
    assert client.post("/api/v1/runs", json=body).json()["run_id"] == "fake1"
    assert len(seen) == 1
    assert ctx.find_record("fake1").sweep_id == "s-abc123"


def test_agent_launch_needs_a_hypothesis(client: TestClient, toy_repo: Path) -> None:
    resp = client.post(
        "/api/v1/runs",
        json={"repo": str(toy_repo), "command": ["true"], "created_by": "agent:x"},
    )
    assert resp.status_code == 400 and "hypothesis" in resp.json()["error"]


def test_negative_gpus_are_rejected(client: TestClient, toy_repo: Path) -> None:
    body = {"repo": str(toy_repo), "command": ["true"], "gpus": -1}
    resp = client.post("/api/v1/runs", json=body)
    assert resp.status_code == 422


def test_stop_only_queued_leaves_started_runs_alone(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    ctx.register_project(toy_repo)
    mine = ctx.descriptor.environment_id  # this server's own runs (others are forwarded)
    ctx.create_run(make_record("q1", status=RunStatus.QUEUED, environment_id=mine))
    ctx.create_run(make_record("u1", status=RunStatus.RUNNING, environment_id=mine))
    out = client.post("/api/v1/runs/u1/stop", json={"only_queued": True}).json()
    assert out["status"] == "running"
    assert ctx.find_record("u1").status == RunStatus.RUNNING
    out = client.post("/api/v1/runs/q1/stop", json={"only_queued": True}).json()
    assert out["status"] == "killed"
