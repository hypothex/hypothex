"""Property tests for temp file names next to files that use the whole name limit."""

import json
import os
import tempfile
from pathlib import Path

import httpx
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

import hypothex as hx
from hypothex import sdk
from hypothex.core.fsutil import TEMP_NAME_KEEP, atomic_write_bytes, temp_prefix
from hypothex.core.store import MAX_STEM, safe_stem
from hypothex.remote.client import EnvClient

NAME_MAX = 255
# file names a file system takes: no "/" or NUL, at most 255 bytes, not "." or ".."
file_names = st.text(
    st.characters(blacklist_characters="/\x00", blacklist_categories=["Cs"]), min_size=1
).filter(lambda s: s not in (".", "..") and len(os.fsencode(s)) <= NAME_MAX)


@settings(max_examples=150, deadline=None)
@given(file_names)
@example("x" * NAME_MAX)
@example("é" * 127)
def test_temp_prefix_fits_next_to_any_file_name(name: str) -> None:
    prefix = temp_prefix(name)
    assert prefix.startswith(".") and prefix.endswith(".")  # hidden, like before
    assert len(os.fsencode(prefix)) <= TEMP_NAME_KEEP + 2
    # mkstemp adds 8 random characters, then the suffix
    assert len(os.fsencode(prefix)) + 8 + len(".part") <= NAME_MAX
    assert name.startswith(prefix[1:-1])  # a cut of the name, never a changed name


@settings(max_examples=40, deadline=None)
@given(st.sampled_from(["x" * NAME_MAX, "y" * 249 + ".jsonl", "é" * 127]), st.binary(max_size=64))
def test_atomic_write_of_a_name_at_the_limit(name: str, data: bytes) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / name
        atomic_write_bytes(target, data)
        assert target.read_bytes() == data
        assert [p.name for p in Path(tmp).iterdir()] == [name]  # no temp file left


@pytest.fixture
def run_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "predictions").mkdir(parents=True)
    monkeypatch.setenv("HYPOTHEX_RUN_DIR", str(run_dir))
    monkeypatch.setenv("HYPOTHEX_RUN_ID", "r1")
    monkeypatch.setenv("HYPOTHEX_PROJECT", "toy")
    monkeypatch.setattr(sdk, "_current", None)
    return run_dir


def test_regression_sdk_logs_a_trace_and_samples_with_a_very_long_id(run_env: Path) -> None:
    # was ENAMETOOLONG: the stem filled 255 bytes and the temp name added 14
    long_id = "x" * 300
    run = hx.current()
    run.log_trace(long_id, [{"tool": "t"}])
    run.log_samples(long_id, [1.0])
    stem = safe_stem(long_id)
    assert len(stem) == MAX_STEM
    rows = (run_env / "traces" / f"{stem}.jsonl").read_text().splitlines()
    assert json.loads(rows[0])["example_id"] == long_id
    assert (run_env / "samples" / f"{stem}.jsonl").exists()


def test_regression_mirror_writes_a_file_whose_name_uses_the_whole_limit(tmp_path: Path) -> None:
    # was ENAMETOOLONG: the ".part" temp name added 15 bytes to a 255-byte name
    dest = tmp_path / ("y" * MAX_STEM + ".jsonl")
    resp = httpx.Response(200, content=b'{"a": 1}\n')
    assert EnvClient._write_stream(resp, dest, max_bytes=1024)
    assert dest.read_bytes() == b'{"a": 1}\n'
    assert [p.name for p in tmp_path.iterdir()] == [dest.name]
