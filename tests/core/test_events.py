import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from hypothex.core import events
from hypothex.core.environment import PROTOCOL_VERSION, load_descriptor
from hypothex.core.events import EventLog
from hypothex.core.layout import Layout


def test_append_and_since(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.db")
    a = log.append("run.created", project="p", run_id="r1", payload={"status": "queued"})
    b = log.append("run.started", project="p", run_id="r1")
    assert b.sequence == a.sequence + 1
    assert [e.type for e in log.since(0)] == ["run.created", "run.started"]
    assert [e.sequence for e in log.since(a.sequence)] == [b.sequence]
    assert log.last_sequence() == b.sequence
    assert log.since(0)[0].payload == {"status": "queued"}


def test_two_handles_share_one_log(tmp_path: Path) -> None:
    one = EventLog(tmp_path / "e.db")
    two = EventLog(tmp_path / "e.db")
    one.append("x")
    assert [e.type for e in two.since(0)] == ["x"]


def test_run_once_is_idempotent(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.db")
    calls: list[int] = []

    def fn() -> dict:
        calls.append(1)
        return {"run_id": f"r{len(calls)}"}

    assert log.run_once("cmd-1", fn) == {"run_id": "r1"}
    assert log.run_once("cmd-1", fn) == {"run_id": "r1"}
    assert log.run_once(None, fn) == {"run_id": "r2"}
    assert len(calls) == 2


def test_run_once_releases_claim_on_failure(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.db")

    def boom() -> dict:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        log.run_once("c", boom)
    assert log.run_once("c", lambda: {"ok": True}) == {"ok": True}


def test_run_once_concurrent_same_command_runs_once(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.db")
    calls: list[int] = []
    results: list[dict] = []

    def slow() -> dict:
        calls.append(1)
        time.sleep(0.3)
        return {"n": len(calls)}

    threads = [
        threading.Thread(target=lambda: results.append(log.run_once("same", slow)))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert results == [{"n": 1}] * 4


def test_descriptor_is_stable(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    layout.ensure()
    first = load_descriptor(layout)
    second = load_descriptor(layout)
    assert first.environment_id == second.environment_id
    assert len(first.environment_id) == 32
    assert first.protocol_version == PROTOCOL_VERSION == 1
    assert first.kind == "local"
    assert "reeval" in first.capabilities


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


@pytest.mark.parametrize("claim", ["__pending__", "__pending__:{pid}:12.5"])
def test_run_once_never_replays_a_claim_whose_claimant_died(tmp_path: Path, claim: str) -> None:
    log = EventLog(tmp_path / "e.db")
    with log._conn() as conn:  # a claimant that died before it stored a result
        conn.execute(
            "INSERT INTO receipts(command_id, result, created_at) VALUES (?,?,?)",
            ("c1", claim.format(pid=_dead_pid()), "2026-01-01T00:00:00+00:00"),
        )
    ran: list[str] = []
    start = time.monotonic()
    # the dead claimant may have launched a run already: its outcome is unknown, never redone
    with pytest.raises(events.CommandInterruptedError, match="outcome is unknown"):
        log.run_once("c1", lambda: ran.append("again") or {"ran": True})
    assert time.monotonic() - start < 5
    with pytest.raises(events.CommandInterruptedError):  # every later retry says the same
        log.run_once("c1", lambda: ran.append("again") or {"ran": True})
    assert ran == []
    assert log.run_once("c2", lambda: {"ran": True}) == {"ran": True}  # a new id runs


def test_an_interrupted_command_is_a_conflict_over_http(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from hypothex.api.app import create_app
    from hypothex.core.context import Context

    ctx = Context.open(tmp_path / "home")
    with ctx.events._conn() as conn:
        conn.execute(
            "INSERT INTO receipts(command_id, result, created_at) VALUES (?,?,?)",
            ("c1", f"__pending__:{_dead_pid()}:1.0", "2026-01-01T00:00:00+00:00"),
        )
    app = create_app(tmp_path / "home", background_repair=False)
    with TestClient(app, base_url="http://127.0.0.1:7777") as client:
        res = client.post("/api/v1/runs/nope/stop", json={"command_id": "c1"})
    assert res.status_code == 409
    assert res.json()["type"] == "CommandInterruptedError"


def test_run_once_waits_for_a_live_claimant(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.db")
    started = threading.Event()

    def slow() -> dict:
        started.set()
        time.sleep(0.5)
        return {"first": True}

    worker = threading.Thread(target=lambda: log.run_once("c2", slow))
    worker.start()
    started.wait(5)
    assert log.run_once("c2", lambda: {"first": False}) == {"first": True}
    worker.join()


def test_claim_marker_without_a_readable_start_time_counts_as_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoStartTime(psutil.Process):
        def create_time(self) -> float:
            raise psutil.AccessDenied(self.pid)

    monkeypatch.setattr(events.psutil, "Process", NoStartTime)
    marker = events._claim_marker()
    assert marker == f"__pending__:{os.getpid()}:none"
    # alive: the start time is unknown, but the pid still runs
    assert events._claimant_gone(marker) is False
    # gone: the pid no longer exists
    assert events._claimant_gone(f"__pending__:{_dead_pid()}:none") is True


def test_run_once_reports_a_claim_with_no_start_time_whose_pid_is_gone(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.db")
    with log._conn() as conn:
        conn.execute(
            "INSERT INTO receipts(command_id, result, created_at) VALUES (?,?,?)",
            ("c1", f"__pending__:{_dead_pid()}:none", "2026-01-01T00:00:00+00:00"),
        )
    with pytest.raises(events.CommandInterruptedError):
        log.run_once("c1", lambda: {"ran": True})
