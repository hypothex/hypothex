import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from tests.factories import PREDS_075, seed_finished_run


@pytest.fixture
def client(home: Path) -> Iterator[TestClient]:
    with TestClient(create_app(home, background_repair=False)) as c:
        yield c


def test_environment_descriptor(client: TestClient) -> None:
    body = client.get("/.well-known/hypothex/environment").json()
    assert body["protocol_version"] == 1 and len(body["environment_id"]) == 32


def test_projects_tasks_leaderboard(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    assert client.get("/api/v1/projects").json()[0]["project"] == "toy"
    tasks = {t["name"]: t for t in client.get("/api/v1/tasks").json()}
    assert tasks["toy-acc"]["best"] == 0.75
    board = client.get("/api/v1/tasks/toy/toy-acc/leaderboard").json()
    assert board["rows"][0]["run_ids"] == ["r1"]
    assert client.get("/api/v1/tasks/toy/toy-acc").json()["dataset"]["name"] == "toyset"


def test_run_detail_logs_predictions_and_errors(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    (ctx.run_dir(rec) / "logs" / "stdout.log").write_text("hello\n")
    assert client.get("/api/v1/runs/r1").json()["record"]["run_id"] == "r1"
    assert client.get("/api/v1/runs/r1/logs").json()["text"] == "hello\n"
    page = client.get("/api/v1/runs/r1/predictions", params={"failures_only": True}).json()
    assert [r["id"] for r in page["rows"]] == ["ex-3"]
    missing = client.get("/api/v1/runs/nope")
    assert missing.status_code == 404 and missing.json()["type"] == "RunNotFoundError"
    bad = client.get("/api/v1/tasks/toy/nope")
    assert bad.status_code == 400 and "unknown task" in bad.json()["error"]


def test_reeval_is_idempotent(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    body = {"command_id": "cmd-123", "force": True}
    first = client.post("/api/v1/runs/r1/reeval", json=body).json()
    second = client.post("/api/v1/runs/r1/reeval", json=body).json()
    assert first == second and first["evaluated"] == ["r1"]
    added = [e for e in ctx.events.since(0) if e.type == "run.score_added"]
    assert len(added) == 1


def test_curation_endpoints(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1")
    assert client.post("/api/v1/runs/r1/tags", json={"add": ["x"]}).json()["tags"] == ["x"]
    assert client.post("/api/v1/runs/r1/star", json={"on": True}).json()["starred"] is True
    assert client.post("/api/v1/runs/r1/notes", json={"text": "hi"}).json() == {"ok": True}
    assert client.post("/api/v1/runs/r1/archive", json={"on": True}).json()["archived"] is True
    assert client.get("/api/v1/runs").json() == []
    assert len(client.get("/api/v1/runs", params={"archived": True}).json()) == 1


def test_launch_via_api(client: TestClient, toy_repo: Path) -> None:
    body = {
        "repo": str(toy_repo),
        "command": [sys.executable, "-c", "print('api')"],
        "hypothesis": "api launch",
        "command_id": "launch-1",
    }
    run_id = client.post("/api/v1/runs", json=body).json()["run_id"]
    assert client.post("/api/v1/runs", json=body).json()["run_id"] == run_id  # idempotent
    deadline = time.monotonic() + 60
    status = ""
    while time.monotonic() < deadline:
        status = client.get(f"/api/v1/runs/{run_id}").json()["record"]["status"]
        if status == "finished":
            break
        time.sleep(0.2)
    assert status == "finished"


def test_ws_replays_then_signals_ready(client: TestClient, ctx: Context) -> None:
    for i in range(3):
        ctx.events.append("test.event", payload={"i": i})
    last = ctx.events.last_sequence()
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "after_sequence": 0})
        seen = [ws.receive_json() for _ in range(last)]
        assert [m["event"]["sequence"] for m in seen] == list(range(1, last + 1))
        assert ws.receive_json() == {"type": "ready", "last_sequence": last}
        ctx.events.append("test.live")
        live = ws.receive_json()
        assert live["type"] == "event" and live["event"]["type"] == "test.live"
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "after_sequence": last - 1})
        assert ws.receive_json()["event"]["sequence"] == last
