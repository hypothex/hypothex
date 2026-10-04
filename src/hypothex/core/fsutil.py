"""Small, crash-safe file helpers."""

from __future__ import annotations

import errno
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

# libyaml's C loader and dumper parse about 7x faster than the pure-Python ones
# and give the same data; fall back to the pure ones when PyYAML has no libyaml.
_YAML_LOADER: type[yaml.SafeLoader] = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_YAML_DUMPER: type[yaml.SafeDumper] = getattr(yaml, "CSafeDumper", yaml.SafeDumper)


def atomic_write_text(path: Path, text: str) -> None:
    """
    Write text so readers never see a partial file.

    Parameters
    ----------
    path : Path
        Destination file. Parent directories are created.
    text : str
        Full file content, written as UTF-8.
    """
    atomic_write_bytes(path, text.encode("utf-8"))


TEMP_NAME_KEEP = 200
"""Most bytes of a file name kept in its temp file's name (the rest is cut)."""


def temp_prefix(name: str) -> str:
    """
    Return a ``tempfile.mkstemp`` prefix for a hidden temp file next to ``name``.

    The prefix is ``.<name>.`` with ``name`` cut to ``TEMP_NAME_KEEP`` bytes, so
    the prefix, mkstemp's 8 random characters and a short suffix stay within
    the 255-byte name limit even when ``name`` itself uses all of it.

    Parameters
    ----------
    name : str
        Name of the file the temp file will replace.

    Returns
    -------
    str
        The prefix, at most ``TEMP_NAME_KEEP + 2`` bytes.

    Examples
    --------
    >>> temp_prefix("a.jsonl")
    '.a.jsonl.'
    >>> len(temp_prefix("x" * 255))
    202
    """
    keep = name[:TEMP_NAME_KEEP]
    while len(os.fsencode(keep)) > TEMP_NAME_KEEP:
        keep = keep[:-1]
    return f".{keep}."


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """
    Write bytes so readers never see a partial file, and keep them after a crash.

    The data goes to a temp file in the same folder, which is flushed
    (``os.fsync``) and renamed over ``path``; then the folder is flushed
    (``fsync_dir``) so the rename itself survives a crash.

    On macOS, ``os.fsync`` hands the data to the drive but does not flush
    the drive's own cache (``F_FULLFSYNC`` does). That is not used here: it
    makes each write about 40x slower (0.2 ms to 9.4 ms; one per trace
    example, mirrored file, or ``run.yaml`` change), and the SQLite index and
    event log already run without it, so it would not make the stores agree
    after a power cut either.

    Parameters
    ----------
    path : Path
        Destination file. Parent directories are created.
    data : bytes
        Full file content.

    Examples
    --------
    >>> import tempfile
    >>> target = Path(tempfile.mkdtemp()) / "blob.bin"
    >>> atomic_write_bytes(target, b"caf\xe9")
    >>> target.read_bytes()
    b'caf\xe9'
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=temp_prefix(path.name), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    fsync_dir(path.parent)


def fsync_dir(path: Path) -> None:
    """
    Make the entries of a folder (a create, rename, or delete in it) durable.

    Parameters
    ----------
    path : Path
        Folder to flush. File systems that cannot fsync a folder are skipped.

    Examples
    --------
    >>> import tempfile
    >>> fsync_dir(Path(tempfile.mkdtemp()))
    """
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError as exc:
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EBADF):
            raise
    finally:
        os.close(fd)


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomically write a mapping as YAML, keeping key order (libyaml when present)."""
    text = yaml.dump(data, Dumper=_YAML_DUMPER, sort_keys=False, allow_unicode=True)
    atomic_write_text(path, text)


def read_yaml(path: Path) -> dict[str, Any]:
    """
    Read a YAML file whose top level is a mapping.

    Uses libyaml's safe loader when PyYAML has it (same data, about 7x faster).

    Returns
    -------
    dict
        Parsed mapping; ``{}`` for an empty file.

    Raises
    ------
    ValueError
        If the top level is not a mapping.
    """
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_YAML_LOADER)
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


def iter_jsonl(path: Path, max_line_bytes: int | None = None) -> Iterator[dict[str, Any]]:
    """
    Yield the objects of a JSONL file one line at a time, skipping bad lines.

    Exact reads accept universal newlines (LF, CRLF, and CR); bounded reads
    split on LF. Blank lines and lines that are not a JSON object
    (malformed or partial) are skipped. A *bounded* read (``max_line_bytes``
    given) also skips lines longer than that, read in pieces and never held,
    and lines that are not UTF-8: it serves live files a view must survive. An
    exact read (``None``) holds each line whole and raises on bytes that are
    not UTF-8, as reading the file as text would: a row it skips is malformed
    JSON, never a row the caller could not see.

    Parameters
    ----------
    path : Path
        JSONL file; a missing file yields nothing.
    max_line_bytes : int, optional
        Longest line to parse, in bytes; ``None`` parses every line.

    Yields
    ------
    dict
        The parsed objects, in file order.

    Raises
    ------
    UnicodeDecodeError
        If ``max_line_bytes`` is ``None`` and a line is not UTF-8.

    Examples
    --------
    >>> list(iter_jsonl(Path("missing.jsonl")))
    []
    """
    if not path.is_file():
        return
    if max_line_bytes is None:
        with path.open(encoding="utf-8") as text_file:
            for text_line in text_file:
                try:
                    obj = json.loads(text_line.strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
        return
    cap = max_line_bytes + 1
    with path.open("rb") as fh:
        while line := fh.readline(cap):
            if cap > 0 and len(line) == cap and not line.endswith(b"\n"):
                while (rest := fh.readline(cap)) and not rest.endswith(b"\n"):
                    pass
                continue
            if not line.strip():
                continue
            try:
                text = line.decode("utf-8")
            except UnicodeDecodeError:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """
    Read a JSONL file, skipping blank, malformed, and partial lines (``iter_jsonl``).

    Returns
    -------
    list of dict
        Parsed objects; ``[]`` if the file does not exist.
    """
    return list(iter_jsonl(path))


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
