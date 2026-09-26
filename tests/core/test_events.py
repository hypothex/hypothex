import threading
import time
from pathlib import Path

import pytest

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
