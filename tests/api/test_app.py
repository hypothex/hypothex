import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from hypothex.core.views import get_view, load_preset
from tests.factories import PREDS_075, seed_finished_run

WS_URL = "ws://127.0.0.1:7777/api/v1/ws"  # TestClient defaults to Host "testserver"

VIEWS = "/api/v1/tasks/toy/toy-acc/views"
GOOD_VIEW = """\
title: acc only
panels:
  - type: leaderboard
    title: board
    data: {metrics: [accuracy]}
"""
# "acuracy" is one letter off; difflib.get_close_matches("acuracy", ["accuracy"]) ->
# ["accuracy"]. The bad name sits on line 5 (1-based) of the text.
BAD_VIEW = GOOD_VIEW.replace("[accuracy]", "[acuracy]")


def _scored(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")


def _view_path(toy_repo: Path, name: str) -> Path:
    return toy_repo.resolve() / ".hypothex" / "views" / "toy-acc" / f"{name}.yaml"


@pytest.fixture
def client(home: Path) -> Iterator[TestClient]:
    app = create_app(home, background_repair=False)
    with TestClient(app, base_url="http://127.0.0.1:7777") as c:
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


@pytest.mark.parametrize("content", ["status: [unclosed\n", "run_id: r1\n", "- a list\n"])
def test_corrupt_run_file_is_json_error_not_500(
    client: TestClient, ctx: Context, toy_repo: Path, content: str
) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    run_yaml = ctx.run_dir(rec) / "run.yaml"
    run_yaml.write_text(content)
    resp = client.get("/api/v1/runs/r1")
    assert resp.status_code == 404
    assert resp.json()["type"] == "StoreError" and str(run_yaml) in resp.json()["error"]


def test_corrupt_project_file_is_json_error_not_500(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    project_file = ctx.layout.project_dir("toy") / "project.json"
    project_file.write_text("{not json")
    resp = client.post("/api/v1/runs/r1/reeval", json={"force": True})
    assert resp.status_code == 404
    assert resp.json()["type"] == "StoreError" and str(project_file) in resp.json()["error"]


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
    with client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "subscribe", "after_sequence": 0})
        seen = [ws.receive_json() for _ in range(last)]
        assert [m["event"]["sequence"] for m in seen] == list(range(1, last + 1))
        assert ws.receive_json() == {"type": "ready", "last_sequence": last}
        ctx.events.append("test.live")
        live = ws.receive_json()
        assert live["type"] == "event" and live["event"]["type"] == "test.live"
    with client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "subscribe", "after_sequence": last - 1})
        assert ws.receive_json()["event"]["sequence"] == last


def test_foreign_host_is_rejected(client: TestClient) -> None:
    evil = {"Host": "attacker.example:7777", "Origin": "http://attacker.example:7777"}
    assert client.get("/api/v1/runs", headers={"Host": "attacker.example:7777"}).status_code == 400
    launch = client.post("/api/v1/runs", headers=evil, json={"repo": "/", "command": ["true"]})
    assert launch.status_code == 400 and "Invalid host" in launch.text
    for host in ("127.0.0.1:7777", "localhost:7777", "[::1]:7777"):
        assert client.get("/api/v1/runs", headers={"Host": host}).status_code == 200


def test_bind_host_is_allowed_but_wildcard_is_not(home: Path) -> None:
    with TestClient(create_app(home, background_repair=False, host="10.1.2.3")) as c:
        assert c.get("/api/v1/runs", headers={"Host": "10.1.2.3:7777"}).status_code == 200
    with TestClient(create_app(home, background_repair=False, host="0.0.0.0")) as c:
        assert c.get("/api/v1/runs", headers={"Host": "0.0.0.0:7777"}).status_code == 400


def test_cross_origin_writes_and_ws_are_rejected(client: TestClient) -> None:
    evil = {"Origin": "http://attacker.example"}
    body = {"repo": "/", "command": ["true"]}
    resp = client.post("/api/v1/runs", headers=evil, json=body)
    assert resp.status_code == 403
    assert client.post("/api/v1/runs", headers={"Origin": "null"}, json=body).status_code == 403
    assert client.get("/api/v1/runs", headers=evil).status_code == 200
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(WS_URL, headers=evil):
        pass
    local = {"Origin": "http://localhost:5173"}
    note = client.post("/api/v1/runs/nope/notes", headers=local, json={"text": "x"})
    assert note.status_code == 404
    with client.websocket_connect(WS_URL, headers=local) as ws:
        ws.send_json({"type": "subscribe", "after_sequence": 0})
        assert ws.receive_json()["type"] == "ready"


def test_view_list_put_get_delete(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    _scored(ctx, toy_repo)
    listed = client.get(VIEWS).json()
    assert [(v["name"], v["origin"], v["kind"]) for v in listed] == [
        ("overview", "preset", "generic")
    ]
    put = client.put(f"{VIEWS}/acc", json={"text": GOOD_VIEW})
    assert put.status_code == 200
    info = put.json()["info"]
    path = _view_path(toy_repo, "acc")
    assert (info["name"], info["title"], info["origin"], info["path"]) == (
        "acc",
        "acc only",
        "file",
        str(path),
    )
    assert path.read_text() == GOOD_VIEW
    assert put.json()["view"]["panels"][0]["data"]["metrics"] == ["accuracy"]
    got = client.get(f"{VIEWS}/acc").json()
    assert got["text"] == GOOD_VIEW and got["info"]["name"] == "acc"
    assert "from_" not in got["view"]
    assert [v["name"] for v in client.get(VIEWS).json()] == ["overview", "acc"]
    assert client.delete(f"{VIEWS}/acc").json() == {"ok": True}
    assert not path.exists()
    assert [v["name"] for v in client.get(VIEWS).json()] == ["overview"]
    missing = client.get(f"{VIEWS}/acc")
    assert missing.status_code == 404 and missing.json()["type"] == "StoreError"


def test_put_invalid_view_is_400_with_issues_and_not_saved(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    _scored(ctx, toy_repo)
    resp = client.put(f"{VIEWS}/acc", json={"text": BAD_VIEW})
    assert resp.status_code == 400
    body = resp.json()
    assert body["type"] == "ViewValidationError" and "acc" in body["error"]
    assert (body["issues"][0]["line"], body["issues"][0]["suggestion"]) == (5, "accuracy")
    assert not _view_path(toy_repo, "acc").exists()
    for bad_name in ("overview", "Bad Name", "-x"):
        resp = client.put(f"{VIEWS}/{bad_name}", json={"text": GOOD_VIEW})
        assert resp.status_code == 400 and resp.json()["type"] == "ConfigError"
    assert client.delete(f"{VIEWS}/overview").status_code == 400
    assert client.put("/api/v1/tasks/toy/nope/views/x", json={"text": GOOD_VIEW}).status_code == 400


def test_put_view_is_idempotent_by_command_id(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    _scored(ctx, toy_repo)
    changed = GOOD_VIEW.replace("acc only", "changed")
    first = client.put(f"{VIEWS}/acc", json={"text": GOOD_VIEW, "command_id": "view-1"}).json()
    second = client.put(f"{VIEWS}/acc", json={"text": changed, "command_id": "view-1"}).json()
    assert second == first
    assert _view_path(toy_repo, "acc").read_text() == GOOD_VIEW
    third = client.put(f"{VIEWS}/acc", json={"text": changed, "command_id": "view-2"}).json()
    assert third["info"]["title"] == "changed"
    assert _view_path(toy_repo, "acc").read_text() == changed


def test_validate_view_endpoint(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    _scored(ctx, toy_repo)
    ok = client.post(f"{VIEWS}/validate", json={"text": GOOD_VIEW}).json()
    assert ok["ok"] is True and ok["issues"] == [] and ok["view"]["title"] == "acc only"
    bad = client.post(f"{VIEWS}/validate", json={"text": BAD_VIEW}).json()
    assert bad["ok"] is False and bad["issues"][0]["suggestion"] == "accuracy"
    broken = client.post(f"{VIEWS}/validate", json={"text": "title: [unclosed\n"}).json()
    assert broken["ok"] is False and broken["issues"] != [] and "view" not in broken
    assert not _view_path(toy_repo, "acc").exists()


def test_validate_returns_the_resolved_view(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    _scored(ctx, toy_repo)
    # toy-acc is a generic task; `from: agent_eval` must still resolve the agent_eval preset
    text = (
        "title: mine\nfrom: agent_eval\n"
        "panels:\n  - type: markdown\n    title: Note\n    text: hi\n"
    )
    body = client.post(f"{VIEWS}/validate", json={"text": text}).json()
    assert body["ok"] is True and body["issues"] == []
    view = body["view"]
    preset = load_preset("agent_eval")
    assert [p["title"] for p in view["panels"]] == [p.title for p in preset.panels] + ["Note"]
    assert [p["layout"] for p in view["panels"][:-1]] == [
        p.layout.model_dump() for p in preset.panels
    ]
    assert view["title"] == "mine" and view["from"] is None  # resolved: `from` is applied


def test_inline_and_preset_views(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    config_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(config_path.read_text())
    inline = {"title": "Inline", "panels": [{"type": "markdown", "text": "hi"}]}
    cfg["tasks"]["toy-acc"]["views"] = {"inl": inline}
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    _scored(ctx, toy_repo)
    listed = client.get(VIEWS).json()
    assert [(v["name"], v["origin"]) for v in listed] == [("overview", "preset"), ("inl", "inline")]
    assert yaml.safe_load(client.get(f"{VIEWS}/inl").json()["text"]) == inline
    assert client.delete(f"{VIEWS}/inl").status_code == 400
    preset = client.get(f"{VIEWS}/overview").json()
    expected = load_preset("generic")
    assert yaml.safe_load(preset["text"])["title"] == expected.title
    assert [p["type"] for p in preset["view"]["panels"]] == [p.type for p in expected.panels]


def test_query_views(client: TestClient, ctx: Context, toy_repo: Path) -> None:
    _scored(ctx, toy_repo)
    config = ctx.register_project(toy_repo).config
    preset = get_view(toy_repo.resolve(), config, "toy-acc", "overview")
    by_name = client.post(f"{VIEWS}/query", json={"name": "overview"}).json()["panels"]
    assert [(p["type"], p["title"]) for p in by_name] == [(p.type, p.title) for p in preset.panels]
    default = client.post(f"{VIEWS}/query", json={}).json()["panels"]
    assert [p["type"] for p in default] == [p.type for p in preset.panels]
    one = client.post(f"{VIEWS}/query", json={"panel": {"type": "markdown", "text": "hi"}})
    (panel,) = one.json()["panels"]
    assert (panel["type"], panel["rows"], panel["meta"]["text"]) == ("markdown", [], "hi")
    view = yaml.safe_load(GOOD_VIEW)
    rows = client.post(f"{VIEWS}/query", json={"view": view}).json()["panels"][0]["rows"]
    assert [r["run_ids"] for r in rows] == [["r1"]]
    assert client.post(f"{VIEWS}/query", json={"name": "nope"}).status_code == 404
    bad_panel = client.post(f"{VIEWS}/query", json={"panel": {"type": "pie"}})
    assert bad_panel.status_code == 422


def test_view_anchors_and_huge_specs_are_issues_never_500(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    _scored(ctx, toy_repo)
    # regression: this spec refers to itself; validating it raised RecursionError (a 500)
    looped = (
        "title: loop\npanels:\n  - type: vega_lite\n    data: {source: runs}\n"
        "    spec: &s {mark: point, layer: [*s]}\n"
    )
    anchors = {
        "line": 5,
        "path": "",
        "message": "YAML anchors and aliases are not allowed",
        "suggestion": None,
    }
    put = client.put(f"{VIEWS}/loop", json={"text": looped})
    assert put.status_code == 400
    assert put.json()["type"] == "ViewValidationError" and put.json()["issues"] == [anchors]
    checked = client.post(f"{VIEWS}/validate", json={"text": looped})
    assert checked.status_code == 200 and checked.json() == {"ok": False, "issues": [anchors]}
    # regression: 600 nested lists (no alias) raised RecursionError inside yaml.compose
    deep = looped.replace(
        "&s {mark: point, layer: [*s]}", "{mark: point, x: " + "[" * 600 + "]" * 600 + "}"
    )
    too_deep = {
        "line": 5,
        "path": "",
        "message": "YAML nested too deeply (over 64 levels)",
        "suggestion": None,
    }
    put = client.put(f"{VIEWS}/loop", json={"text": deep})
    assert put.status_code == 400 and put.json()["type"] == "ViewValidationError"
    assert put.json()["issues"] == [too_deep]
    checked = client.post(f"{VIEWS}/validate", json={"text": deep})
    assert checked.status_code == 200 and checked.json() == {"ok": False, "issues": [too_deep]}
    assert not _view_path(toy_repo, "loop").exists()


def test_inline_view_with_anchors_is_a_config_error_not_500(
    client: TestClient, ctx: Context, toy_repo: Path
) -> None:
    _scored(ctx, toy_repo)
    config_path = toy_repo / "hypothex.yaml"
    cfg = yaml.safe_load(config_path.read_text())
    spec: dict = {"mark": "point"}
    spec["layer"] = [spec]  # safe_dump writes the loop as &id001 ... *id001
    cfg["tasks"]["toy-acc"]["views"] = {
        "loop": {"title": "loop", "panels": [{"type": "vega_lite", "spec": spec}]}
    }
    text = yaml.safe_dump(cfg, sort_keys=False)
    config_path.write_text(text)
    line = next(i for i, row in enumerate(text.splitlines(), 1) if "&id001" in row)
    resp = client.get(f"{VIEWS}/loop")
    assert resp.status_code == 400 and resp.json()["type"] == "ConfigError"
    assert (
        f"YAML anchors and aliases are not allowed in views (line {line})" in resp.json()["error"]
    )
