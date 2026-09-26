from datetime import UTC, datetime
from pathlib import Path

import pytest

from hypothex.core.fsutil import (
    append_jsonl,
    append_note_file,
    atomic_write_text,
    read_jsonl,
    read_yaml,
    write_yaml,
)


def test_atomic_write_replaces_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "a" / "file.txt"
    atomic_write_text(target, "one")
    atomic_write_text(target, "two")
    assert target.read_text() == "two"
    assert [p.name for p in target.parent.iterdir()] == ["file.txt"]


def test_read_jsonl_skips_partial_last_line(tmp_path: Path) -> None:
    path = tmp_path / "m.jsonl"
    append_jsonl(path, {"a": 1})
    append_jsonl(path, {"a": 2})
    with path.open("a") as fh:
        fh.write('{"a": 3')  # simulated crash mid-write
    assert read_jsonl(path) == [{"a": 1}, {"a": 2}]


def test_read_jsonl_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_jsonl(tmp_path / "nope.jsonl") == []


def test_yaml_roundtrip_and_errors(tmp_path: Path) -> None:
    path = tmp_path / "x.yaml"
    write_yaml(path, {"b": 1, "a": [1, 2]})
    assert read_yaml(path) == {"b": 1, "a": [1, 2]}
    path.write_text("")
    assert read_yaml(path) == {}
    path.write_text("- 1\n- 2\n")
    with pytest.raises(ValueError, match="mapping"):
        read_yaml(path)


def test_append_note_file(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    when = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    append_note_file(path, "first", "alice", now=when)
    append_note_file(path, "second", "agent:claude", now=when)
    text = path.read_text()
    assert "## 2026-09-26T12:00:00+00:00 — alice" in text
    assert text.index("first") < text.index("second")
