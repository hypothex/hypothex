"""Hub supervisors and the run mirror (spec 5.3, 5.5, 5.6, 8A.2-8A.3).

Every host here is an in-process env server (``create_app`` under uvicorn on a
random loopback port, in a thread) or a fake; nothing connects to a real host.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hypothex.core.events import EventLog
from hypothex.core.index import SCHEMA_VERSION, Index
from hypothex.remote.hub import Backoff, wanted_path

# index cursors -----------------------------------------------------------------------


def test_cursor_roundtrip_per_host_and_environment(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    assert idx.get_cursor("a", "env-1") == 0
    idx.set_cursor("a", "env-1", 5)
    idx.set_cursor("a", "env-2", 9)
    idx.set_cursor("b", "env-1", 1)
    idx.set_cursor("a", "env-1", 7)
    assert (idx.get_cursor("a", "env-1"), idx.get_cursor("a", "env-2")) == (7, 9)
    assert idx.get_cursor("b", "env-1") == 1


def test_cursor_never_moves_back(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    idx.set_cursor("a", "env-1", 7)
    idx.set_cursor("a", "env-1", 3)  # a late, older apply
    assert idx.get_cursor("a", "env-1") == 7


def test_clear_keeps_cursors(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    idx.set_cursor("a", "env-1", 5)
    idx.clear()
    assert idx.get_cursor("a", "env-1") == 5


def test_old_schema_version_is_rebuilt_with_cursor_table(tmp_path: Path) -> None:
    assert SCHEMA_VERSION == 2
    path = tmp_path / "i.db"
    Index(path).set_cursor("a", "env-1", 5)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION - 1),)
        )
    again = Index(path)
    assert again.rebuilt_schema is True
    assert again.get_cursor("a", "env-1") == 0


def test_append_once_writes_one_event_per_key(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.db")
    first = log.append_once("mirror:gpu1:env-1:7", "mirror.run_updated", run_id="r1")
    assert first is not None and first.sequence == 1
    assert log.append_once("mirror:gpu1:env-1:7", "mirror.run_updated", run_id="r1") is None
    again = EventLog(tmp_path / "e.db")  # another process, same file
    assert again.append_once("mirror:gpu1:env-1:7", "mirror.run_updated", run_id="r1") is None
    assert again.append_once("mirror:gpu1:env-1:8", "mirror.run_updated", run_id="r1") is not None
    assert [e.sequence for e in log.since(0)] == [1, 2]


# pure helpers ------------------------------------------------------------------------


def test_backoff_sequence_caps_and_resets_after_stable_connection() -> None:
    b = Backoff()
    assert [b.next_delay(0.0) for _ in range(6)] == [3.0, 4.0, 8.0, 16.0, 16.0, 16.0]
    b.connected(100.0)
    assert b.next_delay(129.0) == 16.0  # 29 s is not stable yet
    b.connected(200.0)
    assert b.next_delay(230.0) == 3.0
    assert b.next_delay(231.0) == 4.0


def test_backoff_rejects_empty_delays() -> None:
    with pytest.raises(ValueError, match="delays"):
        Backoff(())


@pytest.mark.parametrize(
    ("rel", "ok"),
    [
        ("run.yaml", True),
        ("scores.jsonl", True),
        ("git.diff", True),
        ("predictions/predictions.jsonl", True),
        ("traces/e1.jsonl", True),
        ("logs/stdout.log", True),
        ("artifacts/model.pt", False),
        ("predictions", False),
        ("random.txt", False),
        ("../run.yaml", False),
        ("logs/../../etc/passwd", False),
        ("/etc/passwd", False),
        ("logs//x", False),
        ("logs\\x", False),
        ("", False),
    ],
)
def test_wanted_path(rel: str, ok: bool) -> None:
    assert wanted_path(rel) is ok
