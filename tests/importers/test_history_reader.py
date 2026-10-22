"""Bounded exported-history parsing without the optional W&B SDK."""

from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from hypothex.core.errors import RunError
from hypothex.importers import history_reader
from hypothex.importers.history_reader import iter_history_rows

Format = Literal["csv", "jsonl", "json"]


def _read(tmp_path: Path, contents: str | bytes, format: Format) -> list[dict[str, Any]]:
    path = tmp_path / "history"
    path.write_bytes(contents.encode() if isinstance(contents, str) else contents)
    return list(iter_history_rows(path, format))


def test_csv_bom_pandas_index_numbers_and_blank_cells(tmp_path: Path) -> None:
    rows = _read(
        tmp_path,
        "\ufeff,Step,_step,loss,accuracy,flag,media\n"
        '0,1,9007199254740993,0.125,,true,"{""_type"":""image""}"\n'
        "1,2,9007199254740994,2e-3,0.9,false,\n",
        "csv",
    )
    assert rows == [
        {
            "Step": 1,
            "_step": 9007199254740993,
            "loss": 0.125,
            "flag": True,
            "media": '{"_type":"image"}',
        },
        {"Step": 2, "_step": 9007199254740994, "loss": 0.002, "accuracy": 0.9, "flag": False},
    ]
    assert isinstance(rows[0]["_step"], int)


@pytest.mark.parametrize("index", ["Unnamed: 0", "Unnamed:0"])
def test_csv_named_pandas_index_is_ignored(tmp_path: Path, index: str) -> None:
    assert _read(tmp_path, f"{index},loss\r\n0,1\r\n", "csv") == [{"loss": 1}]


def test_csv_quoted_multiline_values_and_nonfinite_numbers(tmp_path: Path) -> None:
    rows = _read(tmp_path, 'loss,note,a,b\n1,"line one\nline two",NaN,-Infinity\n', "csv")
    assert rows[0]["note"] == "line one\nline two"
    assert math.isnan(rows[0]["a"])
    assert rows[0]["b"] == -math.inf


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("", "no header"),
        ("\n\n", "no header"),
        ("loss\n", "no records"),
        ("loss,loss\n1,2\n", "duplicate"),
        ("loss, loss \n1,2\n", "duplicate"),
        ("Step,,loss\n1,2,3\n", "nonempty"),
        ('""\n0\n', "nonempty"),
        ("Step,loss\n1\n", "column count"),
        ("Step,loss\n1,2,3\n", "column count"),
        ('Step,loss\n1,"unterminated', "invalid CSV"),
        (b"Step,loss\n1,\xff", "UTF-8"),
    ],
)
def test_bad_csv_is_rejected(tmp_path: Path, contents: str | bytes, message: str) -> None:
    with pytest.raises(RunError, match=message):
        _read(tmp_path, contents, "csv")


@pytest.mark.parametrize("format", ["json", "jsonl"])
def test_json_rows_preserve_nested_data_and_precision(tmp_path: Path, format: Format) -> None:
    expected = [
        {"_step": 9007199254740993, "loss": 0.25, "nested": {"accuracy": 0.9}, "flag": True},
        {"_step": 9007199254740994, "media": {"_type": "image", "width": 10}},
    ]
    contents = json.dumps(expected) if format == "json" else "\n\n".join(map(json.dumps, expected))
    assert _read(tmp_path, "\ufeff" + contents, format) == expected


@pytest.mark.parametrize("format", ["csv", "json", "jsonl"])
@pytest.mark.parametrize("key", ["_step", "Step"])
@pytest.mark.parametrize(
    "literal",
    [
        "9007199254740993.0",
        "9.007199254740993e15",
        "1.0000000000000001",
        "9223372036854775807.0",
        "9223372036854775808.0",
        "-9223372036854775808.0",
    ],
)
def test_decimal_steps_are_exact_until_validation(
    tmp_path: Path, format: Format, key: str, literal: str
) -> None:
    row = '{"' + key + '":' + literal + ',"loss":0.1}'
    content = f"{key},loss\n{literal},0.1\n" if format == "csv" else row
    if format == "json":
        content = "[" + row + "]"
    result = _read(tmp_path, content, format)[0]
    assert isinstance(result[key], Decimal)
    assert result[key] == Decimal(literal)
    assert isinstance(result["loss"], float)
    assert result["loss"] == 0.1


@pytest.mark.parametrize("prefix", ["\ufeff\n", "\ufeff  \r\n", "\ufeff\n\n"])
def test_jsonl_bom_before_blank_first_line(tmp_path: Path, prefix: str) -> None:
    assert _read(tmp_path, prefix + '{"_step":1,"loss":0.5}\n', "jsonl") == [
        {"_step": 1, "loss": 0.5}
    ]


def test_bom_counts_toward_jsonl_row_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(history_reader, "_MAX_BYTES", 4)
    with pytest.raises(RunError, match="read limit"):
        _read(tmp_path, "\ufeff  \n", "jsonl")


@pytest.mark.parametrize("format", ["json", "jsonl"])
def test_absurd_json_exponent_is_clean_error(tmp_path: Path, format: Format) -> None:
    row = '{"_step":1e99999999999999999999999999999999999,"loss":1}'
    with pytest.raises(RunError, match="invalid JSON"):
        _read(tmp_path, "[" + row + "]" if format == "json" else row, format)


def test_csv_nonnumeric_step_stays_available_for_validation(tmp_path: Path) -> None:
    assert _read(tmp_path, "Step,loss\ninvalid,1\ntrue,2\n", "csv") == [
        {"Step": "invalid", "loss": 1},
        {"Step": True, "loss": 2},
    ]


@pytest.mark.parametrize(
    ("format", "contents", "message"),
    [
        ("json", "[]", "no records"),
        ("json", '{"loss":{"0":1}}', "array"),
        ("json", '[{"loss":1}, 2]', "object"),
        ("json", '[{"loss":1}', "invalid JSON"),
        ("json", '[{"loss":1,"loss":2}]', "duplicate"),
        ("jsonl", "\n  \n", "no records"),
        ("jsonl", '{"loss":1}\n{"loss":', "invalid JSON"),
        ("jsonl", '{"loss":1}\n[]\n', "object"),
        ("jsonl", "null\n", "object"),
        ("jsonl", '{"loss":1,"loss":2}\n', "duplicate"),
        ("jsonl", '{"loss":1}\n\xff', "invalid JSON"),
    ],
)
def test_bad_json_is_rejected(tmp_path: Path, format: Format, contents: str, message: str) -> None:
    with pytest.raises(RunError, match=message):
        _read(tmp_path, contents, format)


@pytest.mark.parametrize(
    ("format", "contents"),
    [
        ("csv", 'loss,note\n1,"' + "x" * 20 + "\n" + "x" * 20 + '"\n'),
        ("csv", "loss" * 9 + "\n1\n"),
        ("jsonl", json.dumps({"loss": "x" * 40})),
        ("json", json.dumps([{"loss": 1}] * 5)),
    ],
)
def test_limits_reject_before_unbounded_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, format: Format, contents: str
) -> None:
    monkeypatch.setattr(history_reader, "_MAX_BYTES", 32)
    previous = csv.field_size_limit()
    with pytest.raises(RunError, match="64 MiB"):
        _read(tmp_path, contents, format)
    assert csv.field_size_limit() == previous


@pytest.mark.parametrize("format", ["csv", "jsonl"])
def test_streaming_size_limit_is_per_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, format: Format
) -> None:
    monkeypatch.setattr(history_reader, "_MAX_BYTES", 20)
    contents = "loss\n" + "1\n" * 100 if format == "csv" else '{"loss":1}\n' * 100
    assert len(_read(tmp_path, contents, format)) == 100


def test_errors_do_not_expose_source_values(tmp_path: Path) -> None:
    secret = "sensitive-fixture-content"
    for format, contents in [
        ("csv", f"loss,loss\n{secret},{secret}\n"),
        ("jsonl", f'{{"loss":"{secret}"'),
        ("json", json.dumps({secret: 1})),
    ]:
        with pytest.raises(RunError) as caught:
            _read(tmp_path, contents, cast(Format, format))
        assert secret not in str(caught.value)


def test_reader_is_lazy_and_releases_file_on_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text('{"loss":1}\n{"loss":')
    handles: list[Any] = []
    original = Path.open

    def observe(self: Path, *args: Any, **kwargs: Any) -> Any:
        handle = original(self, *args, **kwargs)
        if self == path:
            assert args == ("rb",)
            handles.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", observe)
    rows = iter_history_rows(path, "jsonl")
    assert handles == []
    assert next(rows) == {"loss": 1}
    assert not handles[0].closed
    cast(Any, rows).close()
    assert handles[0].closed


def test_missing_file_and_unsupported_format(tmp_path: Path) -> None:
    with pytest.raises(RunError, match="Cannot read"):
        list(iter_history_rows(tmp_path / "missing", "jsonl"))
    with pytest.raises(RunError, match="Unsupported"):
        list(iter_history_rows(tmp_path / "missing", cast(Format, "parquet")))


def test_parser_does_not_import_wandb() -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import hypothex.importers.history_reader; "
            "assert not any(k == 'wandb' or k.startswith('wandb.') for k in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert done.returncode == 0, done.stderr
