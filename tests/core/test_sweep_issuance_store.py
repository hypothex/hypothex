"""Durable acceptance must be atomic with its existing command receipt."""

import sqlite3
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.errors import StoreError
from hypothex.core.events import EventLog
from hypothex.core.sweeps import SweepParam, create_sweep, list_sweeps, summarize_sweep


def operation(key: str = "create-1", sweep_id: str | None = None) -> dict:
    return {
        "schema_version": 1,
        "operation_key": key,
        "project": "toy",
        "sweep_id": sweep_id,
        "episode": 1,
        "request": {"hypothesis": "keep original", "gpus": 2},
        "issuance": {
            "state": "preparing",
            "episode": 1,
            "revision": 0,
            "planned": 2,
            "accepted_at": None,
            "updated_at": "2026-10-05T00:00:00+00:00",
            "cancel_requested": False,
            "reason": None,
            "error": None,
            "resume": None,
        },
        "run_ids": [],
        "inflight": None,
    }


def test_preparation_claim_preserves_receipts_events_and_original_request(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    old = EventLog(path)
    old.append("existing", payload={"value": 1})
    assert old.run_once("ordinary", lambda: {"ok": True}) == {"ok": True}
    assert old.prepare_sweep("create-1", operation()) is True
    changed = operation()
    changed["request"] = {"gpus": 99}
    assert EventLog(path).prepare_sweep("create-1", changed) is False
    assert old.sweep_operation_by_key("create-1")["request"]["gpus"] == 2
    assert old.command_result("ordinary") == {"ok": True}
    assert old.command_result("absent") is None
    assert [event.type for event in old.since(0)] == ["existing"]
    assert old.prepare_sweep("ordinary", operation("ordinary")) is False
    assert old.sweep_operation_by_key("ordinary") is None


def test_acceptance_receipt_state_and_event_commit_together(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.db")
    op = operation(sweep_id="s-1234")
    assert log.prepare_sweep("create-1", op)
    queued = {**op["issuance"], "state": "queued", "accepted_at": "2026-10-05T00:00:01+00:00"}
    receipt = {"spec": {"id": "s-1234"}, "issuance": {**queued, "revision": 1}}
    assert log.update_sweep("create-1", 0, {"issuance": queued}, receipt=receipt) is not None
    second = EventLog(log.path)
    assert second.command_result("create-1") == receipt
    assert second.sweep_operation("toy", "s-1234")["issuance"]["state"] == "queued"
    assert [row["operation_key"] for row in second.sweep_operations({"queued"})] == ["create-1"]
    event = second.since(0)[0]
    assert (event.type, event.project, event.run_id) == ("sweep.issuance", "toy", None)
    assert event.payload == {
        "project": "toy",
        "sweep_id": "s-1234",
        "episode": 1,
        "revision": 1,
        "state": "queued",
        "cancel_requested": False,
        "error_type": None,
    }
    assert second.update_sweep("create-1", 0, {"inflight": "stale"}) is None
    assert second.sweep_operation_by_key("create-1")["inflight"] is None
    assert second.command_result("create-1") == receipt


def test_failed_acceptance_transaction_cannot_leave_a_receipt_or_ready_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = EventLog(tmp_path / "events.db")
    op = operation(sweep_id="s-1234")
    log.prepare_sweep("create-1", op)

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("event storage failed")

    monkeypatch.setattr(log, "_append_sweep_event", fail)
    with pytest.raises(RuntimeError, match="event storage failed"):
        log.update_sweep(
            "create-1",
            0,
            {"issuance": {**op["issuance"], "state": "queued"}},
            receipt={"accepted": True},
        )
    assert log.sweep_operations({"queued"}) == []
    assert log.sweep_operation_by_key("create-1")["issuance"]["revision"] == 0
    with sqlite3.connect(log.path) as conn:
        assert (
            conn.execute("SELECT result FROM receipts WHERE command_id='create-1'")
            .fetchone()[0]
            .startswith("__pending__")
        )
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_unknown_issuance_schema_is_refused_without_destroying_data(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sweep_issuance (sentinel TEXT)")
        conn.execute("INSERT INTO sweep_issuance VALUES ('keep')")
    with pytest.raises(StoreError, match="sweep issuance schema"):
        EventLog(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT sentinel FROM sweep_issuance").fetchone()[0] == "keep"


def test_sweep_summaries_expose_typed_current_issuance_and_legacy_null(
    ctx: Context, toy_repo: Path
) -> None:
    ctx.register_project(toy_repo)
    spec = create_sweep(
        ctx,
        project="toy",
        grid=[SweepParam(name="x", values=["1", "2"])],
        seeds=[1],
        command=["true", "{x}"],
    )
    assert summarize_sweep(ctx, "toy", spec.id).issuance is None
    assert list_sweeps(ctx, "toy")[0]["issuance"] is None
    ctx.events.prepare_sweep("create-1", operation(sweep_id=spec.id))
    summary = summarize_sweep(ctx, "toy", spec.id)
    assert summary.issuance is not None
    assert summary.issuance.state == "preparing" and summary.issuance.planned == 2
    assert summary.counts["total"] == 0 and summary.issuance.accepted_at is None
    assert list_sweeps(ctx, "toy")[0]["issuance"]["state"] == "preparing"
