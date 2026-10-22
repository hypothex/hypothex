"""Read real SDK logs and reject malformed framing without touching the source."""

from __future__ import annotations

import base64
import builtins
import io
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import IO, Any

import pytest

from hypothex.core.context import Context
from hypothex.core.fsutil import read_yaml
from hypothex.importers import wandb_reader
from hypothex.importers.wandb import import_wandb
from hypothex.importers.wandb_reader import WandbReadError, iter_wandb_records

_HEADER = b":W&B\xe1\xbe\x00"
# Generated with the official W&B 0.25.0 DataStore writer, containing the
# three records asserted below (including a 100,000-character output line).
# Embedded compression keeps the genuine multi-block fixture small.
_SDK_LOG = (
    "eJztzjEKQWEAAOD3PD3FoIxGxWw2ugGLshkoK48svF0pOYFBjiFXMBoog0PYXEL9pe87wdcZtLqvSzSsXO+1KN7G1X"
    "JpMl1li9m4W8zG86x9uI3ueaFx2qX14y5dAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMA/2q+fy0+ehG4A"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQFD79XP5yZPQDQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAIqtlPeo+0GLoBAD93fmebJIoPcfQFqsJCjQ=="
)


def _chunk(payload: bytes, kind: int = 1) -> bytes:
    crc = zlib.crc32(bytes([kind]) + payload) & 0xFFFFFFFF
    return struct.pack("<IHB", crc, len(payload), kind) + payload


def _write(tmp_path: Path, contents: bytes) -> Path:
    path = tmp_path / "run-test.wandb"
    path.write_bytes(contents)
    return path


def test_import_does_not_load_optional_sdk(tmp_path: Path) -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import hypothex.importers.wandb_reader; "
            "assert not any(k == 'wandb' or k.startswith('wandb.') for k in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert done.returncode == 0, done.stderr


def test_missing_optional_dependency_has_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = builtins.__import__

    def refuse(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("wandb"):
            raise ModuleNotFoundError("synthetic missing SDK")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(ImportError, match=r"hypothex\[wandb\]"):
        list(iter_wandb_records(tmp_path / "unused.wandb"))


def test_sdk_fragmented_log_is_read_only_and_streamed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pb = pytest.importorskip("wandb.proto.wandb_internal_pb2")
    expected = [
        pb.Record(run=pb.RunRecord(run_id="fixture", display_name="test")),
        pb.Record(output=pb.OutputRecord(line="x" * 100_000)),
        pb.Record(exit=pb.RunExitRecord(exit_code=0)),
    ]
    path = tmp_path / "run-fixture.wandb"
    path.write_bytes(zlib.decompress(base64.b64decode(_SDK_LOG)))
    before = path.read_bytes()
    path.chmod(0o444)
    modes: list[str] = []
    handles: list[IO[Any]] = []
    real_open = io.open

    def observe(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        handle = real_open(file, mode, *args, **kwargs)
        if Path(file) == path:
            modes.append(mode)
            handles.append(handle)
        return handle

    monkeypatch.setattr(io, "open", observe)
    records = iter_wandb_records(path)
    assert next(records) == expected[0]
    assert not handles[0].closed
    assert list(records) == expected[1:]
    assert handles[0].closed
    assert modes == ["rb"]
    assert path.read_bytes() == before


def test_early_close_releases_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pb = pytest.importorskip("wandb.proto.wandb_internal_pb2")
    path = _write(tmp_path, _HEADER + _chunk(pb.Record(num=1).SerializeToString()) * 2)
    handles: list[IO[Any]] = []
    real_open = Path.open

    def observe(self: Path, *args: Any, **kwargs: Any) -> Any:
        handle = real_open(self, *args, **kwargs)
        handles.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", observe)
    records = iter_wandb_records(path)
    next(records)
    records.close()
    assert handles[0].closed


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        (b"", "file header"),
        (_HEADER[:4], "file header"),
        (b"garbage", "file header"),
        (_HEADER[:6] + b"\x01", "version"),
        (_HEADER + b"\x00", "chunk header"),
        (_HEADER + struct.pack("<IHB", 0, 2, 1) + b"x", "payload"),
        (_HEADER + struct.pack("<IHB", 0, 0, 5), "chunk type"),
        (_HEADER + struct.pack("<IHB", 0, 32768, 1), "boundary"),
        (_HEADER + _chunk(b"\x08\x01")[:-1] + b"\x02", "checksum"),
        (_HEADER + _chunk(b"x", 2), "fragmented record"),
        (_HEADER + _chunk(b"x", 3), "no initial chunk"),
        (_HEADER + _chunk(b"x", 4), "no initial chunk"),
        (_HEADER + _chunk(b"x", 2) + _chunk(b"y", 2), "before next record"),
        (_HEADER + _chunk(b"x", 2) + _chunk(b"y", 1), "before next record"),
        (_HEADER + _chunk(b"\xff"), "protobuf"),
    ],
)
def test_malformed_file_is_rejected(tmp_path: Path, contents: bytes, message: str) -> None:
    pytest.importorskip("wandb")
    with pytest.raises(WandbReadError, match=message):
        list(iter_wandb_records(_write(tmp_path, contents)))


def test_record_limit_is_enforced_before_assembling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("wandb")
    monkeypatch.setattr(wandb_reader, "_MAX_RECORD_BYTES", 8)
    for chunks in (_chunk(b"x" * 9), _chunk(b"x" * 5, 2) + _chunk(b"x" * 4, 4)):
        with pytest.raises(WandbReadError, match="read limit"):
            list(iter_wandb_records(_write(tmp_path, _HEADER + chunks)))


@pytest.mark.parametrize("padding", [b"\0\0\0", b"\0\0", b"\0\0x"])
def test_padding_is_validated(tmp_path: Path, padding: bytes) -> None:
    pb = pytest.importorskip("wandb.proto.wandb_internal_pb2")
    # A protobuf output with precisely three unused bytes in the initial block.
    first = pb.Record(output=pb.OutputRecord(line="x" * 32743)).SerializeToString()
    assert len(_HEADER + _chunk(first)) == 32765
    tail = _chunk(pb.Record(num=2).SerializeToString())
    path = _write(tmp_path, _HEADER + _chunk(first) + padding + tail)
    if padding == b"\0\0\0":
        assert [r.num for r in iter_wandb_records(path)] == [0, 2]
    else:
        with pytest.raises(WandbReadError, match="padding"):
            list(iter_wandb_records(path))


def test_offline_sdk_run_preserves_record_data(
    tmp_path: Path, ctx: Context, toy_repo: Path
) -> None:
    pytest.importorskip("wandb")
    # A real offline writer exercises the current Go-backed SDK, independent of
    # both our malformed-input helpers and the legacy Python DataStore writer.
    script = """
import sys
import wandb
with wandb.init(project="hypothex-test", id="offline-fixture", name="Offline fixture",
                dir=sys.argv[1], mode="offline", config={"lr": 0.125}, tags=["import"],
                settings=wandb.Settings(console="off", x_disable_stats=True,
                                        x_disable_meta=True)) as run:
    run.log({"loss": 0.75, "nested": {"accuracy": 0.5}}, step=4)
    run.log({"loss": 0.25}, step=8)
"""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("WANDB_")}
    environment.update(
        WANDB_MODE="offline",
        WANDB_BASE_URL="http://127.0.0.1:1",
        WANDB_CONFIG_DIR=str(tmp_path / "config"),
        WANDB_CACHE_DIR=str(tmp_path / "cache"),
    )
    done = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    assert done.returncode == 0, done.stderr
    logs = list(tmp_path.glob("wandb/offline-run-*/run-*.wandb"))
    assert len(logs) == 1
    records = list(iter_wandb_records(logs[0]))
    run = next(record.run for record in records if record.HasField("run"))
    assert run.run_id == "offline-fixture"
    assert run.display_name == "Offline fixture"
    assert list(run.tags) == ["import"]
    assert {item.key: json.loads(item.value_json) for item in run.config.update}["lr"] == 0.125
    histories = [record.history for record in records if record.HasField("history")]
    assert len(histories) == 2
    assert histories[0].step.num == 4
    assert histories[1].step.num == 8
    assert any(record.HasField("exit") and record.exit.exit_code == 0 for record in records)

    result = import_wandb(ctx, logs[0], toy_repo)
    assert result.imported and result.metric_points == 3
    imported = result.record
    assert imported.name == "Offline fixture"
    assert imported.params["lr"] == "0.125"
    assert read_yaml(ctx.run_dir(imported) / "config.yaml")["lr"] == 0.125
    expected = [("loss", 4, 0.75), ("loss", 8, 0.25), ("nested/accuracy", 4, 0.5)]
    points = ctx.store.read_metric_points(imported.project, imported.run_id)
    assert sorted((point.name, point.step, point.value) for point in points) == expected
    indexed = ctx.index.metric_points(imported.run_id)
    assert sorted((point.name, point.step, point.value) for point in indexed) == expected
