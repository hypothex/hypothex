import errno
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from hypothex.core import fsutil
from hypothex.core.fsutil import (
    append_jsonl,
    append_note_file,
    atomic_write_bytes,
    atomic_write_text,
    open_jsonl_append,
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


def test_atomic_write_flushes_file_then_renames_then_flushes_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real_sync, real_replace = os.fsync, os.replace

    def sync(fd: int) -> None:
        calls.append("sync-dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "sync-file")
        real_sync(fd)

    def replace(src: str, dst: Path) -> None:
        calls.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(fsutil.os, "fsync", sync)
    monkeypatch.setattr(fsutil.os, "replace", replace)
    atomic_write_bytes(tmp_path / "run.yaml", b"a: 1\n")
    assert calls == ["sync-file", "replace", "sync-dir"]


def test_fsync_dir_skips_a_file_system_that_cannot_flush_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(fd: int) -> None:
        raise OSError(errno.EINVAL, "cannot fsync a folder here")

    monkeypatch.setattr(fsutil.os, "fsync", refuse)
    fsutil.fsync_dir(tmp_path)  # no error


def test_read_jsonl_skips_partial_last_line(tmp_path: Path) -> None:
    path = tmp_path / "m.jsonl"
    append_jsonl(path, {"a": 1})
    append_jsonl(path, {"a": 2})
    with path.open("a") as fh:
        fh.write('{"a": 3')  # simulated crash mid-write
    assert read_jsonl(path) == [{"a": 1}, {"a": 2}]


def test_append_after_partial_line_keeps_new_rows(tmp_path: Path) -> None:
    path = tmp_path / "scores.jsonl"
    append_jsonl(path, {"a": 1})
    with path.open("a") as fh:
        fh.write('{"a":2,"trunc')  # simulated crash mid-write
    append_jsonl(path, {"a": 3})
    append_jsonl(path, {"a": 4})
    assert read_jsonl(path) == [{"a": 1}, {"a": 3}, {"a": 4}]


def test_open_jsonl_append_creates_file_without_leading_newline(tmp_path: Path) -> None:
    path = tmp_path / "new" / "m.jsonl"
    with open_jsonl_append(path) as fh:
        fh.write(b'{"a":1}\n')
    assert path.read_bytes() == b'{"a":1}\n'


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


@pytest.mark.skipif(not yaml.__with_libyaml__, reason="PyYAML built without libyaml")
def test_yaml_uses_libyaml_when_present() -> None:
    assert fsutil._YAML_LOADER is yaml.CSafeLoader
    assert fsutil._YAML_DUMPER is yaml.CSafeDumper


def test_yaml_c_and_pure_paths_agree_and_stay_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = {"name": "café 日本", "n": None, "ok": True, "f": 1.5e-7, "list": [1, "a\tb"]}
    path = tmp_path / "x.yaml"
    write_yaml(path, data)
    fast = read_yaml(path)
    monkeypatch.setattr(fsutil, "_YAML_LOADER", yaml.SafeLoader)
    monkeypatch.setattr(fsutil, "_YAML_DUMPER", yaml.SafeDumper)
    assert read_yaml(path) == fast == data
    write_yaml(path, data)
    assert read_yaml(path) == data
    monkeypatch.undo()
    path.write_text("x: !!python/object/apply:os.getcwd []\n")
    with pytest.raises(yaml.YAMLError):
        read_yaml(path)


def test_append_note_file(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    when = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    append_note_file(path, "first", "alice", now=when)
    append_note_file(path, "second", "agent:claude", now=when)
    text = path.read_text()
    assert "## 2026-09-26T12:00:00+00:00 — alice" in text
    assert text.index("first") < text.index("second")


def test_atomic_write_bytes_keeps_raw_bytes(tmp_path: Path) -> None:
    target = tmp_path / "b" / "blob.bin"
    atomic_write_bytes(target, b"caf\xe9\xff\n")
    assert target.read_bytes() == b"caf\xe9\xff\n"
    assert [p.name for p in target.parent.iterdir()] == ["blob.bin"]


def test_atomic_write_follows_the_umask_like_appended_files(tmp_path: Path) -> None:
    old = os.umask(0o022)
    try:
        atomic_write_text(tmp_path / "run.yaml", "a: 1\n")
        append_jsonl(tmp_path / "metrics.jsonl", {"a": 1})
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "run.yaml").stat().st_mode) == 0o644
    assert stat.S_IMODE((tmp_path / "metrics.jsonl").stat().st_mode) == 0o644
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
