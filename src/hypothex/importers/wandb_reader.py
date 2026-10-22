"""Stream W&B version-zero transaction logs without opening them for writing.

The format is documented by W&B's ``core/pkg/leveldb/record.go`` and
``wandb/sdk/internal/datastore.py``: 32 KiB blocks, seven-byte headers,
and IEEE CRC32 over each chunk's type byte and payload. Protobuf decoding
uses the optional W&B dependency; importing this module does not load it.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Generator, Iterator
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    # W&B selects generated classes dynamically for the protobuf major version.
    from wandb.proto.wandb_internal_pb2 import Record  # ty: ignore[unresolved-import]

_BLOCK_BYTES = 32768
_HEADER_BYTES = 7
_FILE_HEADER = b":W&B\xe1\xbe\x00"
_MAX_RECORD_BYTES = 64 * 1024 * 1024


class WandbReadError(ValueError):
    """A W&B log is malformed, truncated, unsupported, or exceeds a read limit."""


def _chunks(stream: BinaryIO) -> Iterator[tuple[int, bytes]]:
    offset = _HEADER_BYTES
    while True:
        remaining = _BLOCK_BYTES - offset % _BLOCK_BYTES
        if remaining < _HEADER_BYTES:
            padding = stream.read(remaining)
            # A finished file can end immediately after its final record.
            if not padding:
                return
            if len(padding) != remaining:
                raise WandbReadError(f"Truncated W&B block padding at byte {offset}")
            if padding != bytes(remaining):
                raise WandbReadError(f"Invalid W&B block padding at byte {offset}")
            offset += remaining
            remaining = _BLOCK_BYTES
        header = stream.read(_HEADER_BYTES)
        if not header:
            return
        if len(header) != _HEADER_BYTES:
            raise WandbReadError(f"Truncated W&B chunk header at byte {offset}")
        checksum, length, kind = struct.unpack("<IHB", header)
        if kind not in (1, 2, 3, 4):
            raise WandbReadError(f"Invalid W&B chunk type at byte {offset}")
        if length + _HEADER_BYTES > remaining:
            raise WandbReadError(f"W&B chunk crosses a block boundary at byte {offset}")
        payload = stream.read(length)
        if len(payload) != length:
            raise WandbReadError(f"Truncated W&B chunk payload at byte {offset}")
        if zlib.crc32(payload, zlib.crc32(bytes([kind]))) & 0xFFFFFFFF != checksum:
            raise WandbReadError(f"Invalid W&B chunk checksum at byte {offset}")
        offset += _HEADER_BYTES + length
        yield kind, payload


def _payloads(stream: BinaryIO) -> Iterator[bytes]:
    header = stream.read(_HEADER_BYTES)
    if len(header) != _HEADER_BYTES:
        raise WandbReadError("Truncated W&B file header")
    if header[:6] != _FILE_HEADER[:6]:
        raise WandbReadError("Invalid W&B file header")
    if header[6] != 0:
        raise WandbReadError("Unsupported W&B file version; expected version 0")
    assembled: bytearray | None = None
    for kind, chunk in _chunks(stream):
        if kind in (1, 2):
            if assembled is not None:
                raise WandbReadError("Unfinished W&B fragmented record before next record")
            if kind == 1:
                if len(chunk) > _MAX_RECORD_BYTES:
                    raise WandbReadError("W&B record exceeds the 64 MiB read limit")
                yield chunk
                continue
            assembled = bytearray()
        elif assembled is None:
            raise WandbReadError("W&B continuation chunk has no initial chunk")
        if assembled is None:  # All valid branches above establish an assembly.
            raise WandbReadError("Invalid W&B fragment sequence")
        if len(assembled) + len(chunk) > _MAX_RECORD_BYTES:
            raise WandbReadError("W&B record exceeds the 64 MiB read limit")
        assembled.extend(chunk)
        if kind == 4:
            yield bytes(assembled)
            assembled = None
    if assembled is not None:
        raise WandbReadError("Truncated W&B fragmented record")


def iter_wandb_records(path: Path) -> Generator[Record, None, None]:
    """
    Read complete protobuf records from a W&B version-zero log.

    Parameters
    ----------
    path : pathlib.Path
        Path to a completed, immutable ``.wandb`` file.

    Yields
    ------
    wandb.proto.wandb_internal_pb2.Record
        Records in file order. Only one logical record (up to 64 MiB of
        serialized data) is buffered at a time, independent of file size.

    Raises
    ------
    WandbReadError
        If framing, checksum, protobuf data, or the record size is invalid.
        Incomplete tails are rejected, including unfinished fragments.
    ImportError
        If the optional ``hypothex[wandb]`` dependency is unavailable.
    OSError
        If the source file cannot be opened or read.

    Notes
    -----
    The source is opened in binary read-only mode. Consume the iterator fully
    before publishing imported data: a later record can be corrupt. Framing
    validation does not establish that the run finished; callers must check
    the run's exit record. Close the iterator if stopping consumption early.

    Examples
    --------
    >>> from pathlib import Path
    >>> records = iter_wandb_records(Path("run-example.wandb"))
    >>> records.close()
    """
    try:
        # Resolve the optional decoder at runtime so base installs can type-check.
        DecodeError = import_module("google.protobuf.message").DecodeError
        from wandb.proto.wandb_internal_pb2 import Record  # ty: ignore[unresolved-import]
    except ImportError as exc:
        raise ImportError(
            "W&B import requires the optional dependency; install hypothex[wandb] "
            "(or run uv sync --extra wandb in a source checkout)"
        ) from exc

    with path.open("rb") as stream:
        for payload in _payloads(stream):
            record = Record()
            try:
                record.ParseFromString(payload)
            except DecodeError as exc:
                raise WandbReadError("Invalid W&B protobuf record") from exc
            yield record
