from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from hypothex.core.notebook import NOTEBOOK_MAX_BYTES, hub_today
from tests.api.authkit import BASE, auth_app, bearer, token_for
from tests.factories import PREDS_075, seed_finished_run

PREDS_025 = [{"id": f"ex-{i}", "prediction": 1} for i in range(4)]
NOTEBOOK = "/api/v1/projects/toy/notebook"


@pytest.fixture
def team(home: Path, toy_repo: Path) -> Iterator[tuple[FastAPI, TestClient, Context]]:
    ctx = Context.open(home)
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "r2", predictions=PREDS_025)
    evaluate_run(ctx, "r1")
    evaluate_run(ctx, "r2")
    app = auth_app(home)
    with TestClient(app, base_url=BASE) as client:
        yield app, client, ctx


def test_notebook_round_trip(team: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = team
    alice = bearer(token_for(app.state.auth, "alice", "launch"))
    day = client.post(f"{NOTEBOOK}/2026-10-04", json={"text": "see [[run:r1]]"}, headers=alice)
    assert day.status_code == 200 and "— human:alice" in day.json()["text"]
    assert day.json()["runs"][0]["primary"] == 0.75
    assert client.get(NOTEBOOK, headers=alice).json() == [
        {"day": "2026-10-04", "bytes": len(day.json()["text"].encode()), "entries": 1}
    ]
    saved = client.put(
        f"{NOTEBOOK}/2026-10-04",
        json={"text": "# rewritten\n", "base_hash": day.json()["hash"]},
        headers=alice,
    )
    assert saved.json()["text"] == "# rewritten\n"
    stale = client.put(
        f"{NOTEBOOK}/2026-10-04",
        json={"text": "mine", "base_hash": day.json()["hash"]},
        headers=alice,
    )
    assert stale.status_code == 409 and stale.json()["type"] == "NotebookConflictError"
    assert stale.json()["current"]["text"] == "# rewritten\n"
    big = client.put(
        f"{NOTEBOOK}/2026-10-05",
        json={"text": "x" * (NOTEBOOK_MAX_BYTES + 1), "base_hash": ""},
        headers=alice,
    )
    assert big.status_code == 413
    assert client.get(f"{NOTEBOOK}/04-10-2026", headers=alice).status_code == 400
    now_day = client.get(f"{NOTEBOOK}/today", headers=alice).json()["day"]
    assert now_day == hub_today(ctx).isoformat()  # the hub names "today", not the caller


def test_task_export_downloads(team: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, _ = team
    reader = bearer(token_for(app.state.auth, "reader", "read"))
    md = client.get("/api/v1/tasks/toy/toy-acc/export", headers=reader)
    assert md.headers["content-type"] == "text/plain; charset=utf-8"
    assert md.headers["content-disposition"] == 'attachment; filename="toy-acc.md"'
    assert md.text.startswith("| group | n | accuracy/value ↑ |")
    tex = client.get("/api/v1/tasks/toy/toy-acc/export?format=latex&digits=2", headers=reader)
    assert tex.text.startswith("% requires \\usepackage{booktabs}")
    assert tex.headers["content-disposition"].endswith('filename="toy-acc.tex"')
    csv = client.get("/api/v1/tasks/toy/toy-acc/export?format=csv&noise=seed", headers=reader)
    assert csv.headers["content-type"] == "text/csv; charset=utf-8"
    assert csv.text.splitlines()[0].startswith("kind,label,key,n,metric,mean")


def test_export_http_uses_selected_ranking_and_retains_columns(
    team: tuple[FastAPI, TestClient, Context],
) -> None:
    import csv
    import io

    from tests.core.test_backlog_backend import indexed

    app, client, ctx = team
    indexed(ctx, ctx.local_repo("toy"))
    reader = bearer(token_for(app.state.auth, "reader", "read"))
    url = "/api/v1/tasks/toy/t/export"
    base = {"format": "csv", "metrics": "acc/value", "baselines": "false"}
    default = client.get(url, params=base, headers=reader)
    selected = client.get(url, params={**base, "primary": "latency/p95"}, headers=reader)
    assert default.status_code == selected.status_code == 200
    first = list(csv.DictReader(io.StringIO(default.text)))
    second = list(csv.DictReader(io.StringIO(selected.text)))
    assert [row["label"] for row in first] == ["A", "B"]
    assert [row["label"] for row in second] == ["B", "A"]
    assert {row["metric"] for row in first + second} == {"acc/value"}


def test_export_http_primary_validation(team: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, _ = team
    reader = bearer(token_for(app.state.auth, "reader", "read"))
    selected = client.get("/api/v1/tasks/toy/toy-acc/export?primary=accuracy/value", headers=reader)
    assert selected.status_code == 200 and "accuracy/value" in selected.text
    assert (
        client.get(
            "/api/v1/tasks/toy/toy-acc/export?primary=accuracy/typo", headers=reader
        ).status_code
        == 400
    )
    refused = client.get(
        "/api/v1/compare/export?run_ids=r1,r2&primary=accuracy/value", headers=reader
    )
    assert refused.status_code == 400 and refused.json()["type"] == "RunError"


def test_compare_export(team: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, _ = team
    reader = bearer(token_for(app.state.auth, "reader", "read"))
    resp = client.get("/api/v1/compare/export?run_ids=r1,r2&format=csv", headers=reader)
    assert resp.headers["content-disposition"] == 'attachment; filename="compare.csv"'
    assert resp.text.splitlines()[1].startswith("run,r1,r1,1,accuracy/value,0.75")
    assert client.get("/api/v1/compare/export?run_ids=r1", headers=reader).status_code == 400


def test_leaderboard_and_run_detail_carry_phase_3_fields(
    team: tuple[FastAPI, TestClient, Context],
) -> None:
    app, client, _ = team
    reader = bearer(token_for(app.state.auth, "reader", "read"))
    board = client.get("/api/v1/tasks/toy/toy-acc/leaderboard", headers=reader).json()
    assert board["baselines"] == []
    detail = client.get("/api/v1/runs/r1", headers=reader).json()
    assert detail["cleaned"] == [] and detail["record"]["owner"] is None


def test_digest_routes(team: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = team
    admin = bearer(token_for(app.state.auth, "sv", "admin"))
    digest = client.get("/api/v1/projects/toy/digest", headers=admin).json()
    assert digest["project"] == "toy" and digest["counts"]["started"] == 2
    sent = client.post("/api/v1/projects/toy/digest/send", json={}, headers=admin).json()
    assert sent["channels"] == [] and sent["notebook_day"] is not None  # no channel configured
    day = client.get(f"{NOTEBOOK}/{sent['notebook_day']}", headers=admin).json()
    assert "— digest" in day["text"]
    launcher = bearer(token_for(app.state.auth, "alice", "launch"))
    assert (
        client.post("/api/v1/projects/toy/digest/send", json={}, headers=launcher).status_code
        == 403
    )
