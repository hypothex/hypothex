"""Bounded, read-only readers for CSV and JSON metric history exports."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import Lock
from typing import Any, BinaryIO, Literal

from hypothex.core.errors import RunError

_MAX_BYTES = 64 * 1024 * 1024
_INTEGER = re.compile(r"[+-]?[0-9]+\Z")
_CSV_PARSE_LOCK = Lock()


class _CsvLines:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.used = 0
        self.first = True

    def __iter__(self) -> _CsvLines:
        return self

    def __next__(self) -> str:
        raw = self.stream.readline(_MAX_BYTES - self.used + 1)
        if not raw:
            raise StopIteration
        self.used += len(raw)
        if self.used > _MAX_BYTES:
            raise RunError("CSV history row exceeds the 64 MiB read limit")
        encoding = "utf-8-sig" if self.first else "utf-8"
        self.first = False
        return raw.decode(encoding)


def _csv_rows(stream: BinaryIO) -> Iterator[list[str]]:
    lines = _CsvLines(stream)
    reader = csv.reader(lines, strict=True)
    while True:
        lines.used = 0
        # csv's limit is global. Change it only during this synchronous parse,
        # restoring it before yielding to the caller or propagating an error.
        with _CSV_PARSE_LOCK:
            previous_limit = csv.field_size_limit()
            try:
                csv.field_size_limit(_MAX_BYTES)
                row = next(reader)
            except StopIteration:
                return
            finally:
                csv.field_size_limit(previous_limit)
        if row:
            yield row


def _cell(value: str, name: str) -> Any:
    stripped = value.strip()
    if stripped.lower() in ("true", "false"):
        return stripped.lower() == "true"
    if _INTEGER.fullmatch(stripped):
        try:
            return int(stripped)
        except ValueError:
            raise RunError("CSV history integer exceeds the supported numeric limit") from None
    if name in ("_step", "Step"):
        try:
            return Decimal(stripped)
        except InvalidOperation:
            return value
    try:
        return float(stripped)
    except ValueError:
        return value


def _csv(stream: BinaryIO) -> Iterator[dict[str, Any]]:
    rows = _csv_rows(stream)
    header = next(rows, None)
    if header is None:
        raise RunError("CSV history has no header")
    header = [name.strip() for name in header]
    index = header[0] in ("", "Unnamed: 0", "Unnamed:0")
    names = header[1:] if index else header
    if not names or any(not name for name in names):
        raise RunError("CSV history requires nonempty metric column headers")
    if len(set(names)) != len(names):
        raise RunError("CSV history has duplicate column headers")
    for cells in rows:
        if len(cells) != len(header):
            raise RunError("CSV history row does not match the header column count")
        if index:
            cells = cells[1:]
        yield {
            name: _cell(value, name)
            for name, value in zip(names, cells, strict=True)
            if value.strip()
        }


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RunError("JSON history contains a duplicate object key")
        result[key] = (
            float(value) if isinstance(value, Decimal) and key not in ("_step", "Step") else value
        )
    return result


def _json_load(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object, parse_float=Decimal)
    except (ValueError, RecursionError, InvalidOperation):
        raise RunError("Exported history contains invalid JSON") from None


def _jsonl(stream: BinaryIO) -> Iterator[dict[str, Any]]:
    first = True
    while raw := stream.readline(_MAX_BYTES + 1):
        if len(raw) > _MAX_BYTES:
            raise RunError("JSONL history row exceeds the 64 MiB read limit")
        if first:
            raw = raw.removeprefix(b"\xef\xbb\xbf")
            first = False
        if not raw.strip():
            continue
        row = _json_load(raw)
        if not isinstance(row, dict):
            raise RunError("Each JSONL history row must be an object")
        yield row


def _json(stream: BinaryIO) -> Iterator[dict[str, Any]]:
    raw = stream.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise RunError("JSON history file exceeds the 64 MiB read limit; use JSONL instead")
    rows = _json_load(raw)
    if not isinstance(rows, list):
        raise RunError("JSON history must contain an array of row objects")
    for row in rows:
        if not isinstance(row, dict):
            raise RunError("Each JSON history row must be an object")
        yield row


def iter_history_rows(
    path: Path, format: Literal["csv", "jsonl", "json"]
) -> Iterator[dict[str, Any]]:
    """
    Read metric history rows from an exported CSV, JSONL, or JSON file.

    Parameters
    ----------
    path : pathlib.Path
        UTF-8 source file. A UTF-8 byte-order mark is supported.
    format : {'csv', 'jsonl', 'json'}
        Explicit input format. JSON must be an array of row objects; pandas
        column-oriented objects are not supported.

    Yields
    ------
    dict of str to Any
        One row, preserving integer precision. CSV numeric cells become
        numbers, boolean cells become booleans, and blank cells are omitted.
        The first blank or ``Unnamed: 0`` CSV index column is discarded.
        Decimal or exponent forms of ``_step`` and ``Step`` remain exact
        ``decimal.Decimal`` values for the caller to validate as integers.

    Raises
    ------
    RunError
        On invalid UTF-8, invalid or empty input, duplicate keys or headers,
        mismatched CSV columns, unreadable files, or exceeded read limits.

    Notes
    -----
    CSV and JSONL stream at most 64 MiB of encoded input per logical row,
    including line terminators. Quoted CSV multiline cells count toward the
    same row limit. JSON arrays have a 64 MiB whole-file limit. Parsing adds
    Python object overhead. Consume all rows before publishing an import:
    a later row can be malformed. Nonfinite numbers and nonnumeric values
    are retained for the caller to filter.

    Examples
    --------
    >>> rows = iter_history_rows(Path("history.csv"), "csv")
    >>> next(rows)  # doctest: +SKIP
    {'Step': 1, 'loss': 0.25}
    """
    if format not in ("csv", "jsonl", "json"):
        raise RunError("Unsupported history format; choose csv, jsonl, or json")
    readers = {"csv": _csv, "jsonl": _jsonl, "json": _json}
    count = 0
    try:
        with path.open("rb") as stream:
            for row in readers[format](stream):
                count += 1
                yield row
    except UnicodeError:
        raise RunError("Exported history must be valid UTF-8") from None
    except csv.Error:
        raise RunError("Exported history contains invalid CSV") from None
    except OSError:
        raise RunError("Cannot read exported history file") from None
    if count == 0:
        raise RunError("Exported history contains no records")
