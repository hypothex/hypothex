"""Small, crash-safe file helpers."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

import yaml

from hypothex.core.ids import utcnow


def atomic_write_text(path: Path, text: str) -> None:
    """
    Write text so readers never see a partial file.

    Parameters
    ----------
    path : Path
        Destination file. Parent directories are created.
    text : str
        Full file content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomically write a mapping as YAML, keeping key order."""
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def read_yaml(path: Path) -> dict[str, Any]:
    """
    Read a YAML file whose top level is a mapping.

    Returns
    -------
    dict
        Parsed mapping; ``{}`` for an empty file.

    Raises
    ------
    ValueError
        If the top level is not a mapping.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return data


@contextmanager
def open_jsonl_append(path: Path) -> Iterator[BinaryIO]:
    """
    Open a JSONL file for appending whole lines.

    If a crash left a partial last line (no trailing newline), a newline is
    written first so the next row starts on its own line instead of being
    glued onto the partial one (which readers would then drop).

    Parameters
    ----------
    path : Path
        JSONL file; it and its parent directory are created if missing.

    Yields
    ------
    BinaryIO
        Binary handle positioned at the end of the file.

    Examples
    --------
    >>> with open_jsonl_append(path) as fh:  # doctest: +SKIP
    ...     fh.write(b'{"a":1}\\n')
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as fh:
        if fh.seek(0, os.SEEK_END) > 0:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                fh.write(b"\n")
        yield fh


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    """
    Append one JSON object as a line.

    A partial last line left by a crash is terminated first, so the new row is
    never lost.

    Parameters
    ----------
    path : Path
        JSONL file; created if missing.
    obj : dict
        JSON-serialisable mapping (non-JSON values use ``str``).
    """
    line = json.dumps(obj, default=str, separators=(",", ":"))
    with open_jsonl_append(path) as fh:
        fh.write((line + "\n").encode("utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """
    Read a JSONL file, skipping blank, malformed, and partial lines.

    Returns
    -------
    list of dict
        Parsed objects; ``[]`` if the file does not exist.
    """
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def append_note_file(path: Path, text: str, author: str, now: datetime | None = None) -> None:
    """
    Append a timestamped note section to a Markdown file.

    Parameters
    ----------
    path : Path
        ``notes.md`` path.
    text : str
        Note body (Markdown).
    author : str
        Who wrote it, e.g. ``human`` or ``agent:claude``.
    now : datetime, optional
        Timestamp; defaults to now.
    """
    stamp = (now or utcnow()).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## {stamp} — {author}\n\n{text.strip()}\n")
