"""Import exported W&B histories without the optional binary reader SDK."""

from __future__ import annotations

import builtins
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hypothex.api.app import create_app
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.records import RunStatus
from hypothex.importers.wandb import import_wandb


@pytest.mark.parametrize(
    ("suffix", "contents"),
    [
        (
            "csv",
            ",_step,_timestamp,loss,val/accuracy,label\n0,4,1700000000,0.75,0.5,start\n"
            "1,8,1700000001,0.25,,end\n",
        ),
        (
            "jsonl",
            '{"_step":4,"_timestamp":1700000000,"loss":0.75,"val":{"accuracy":0.5}}\n'
            '{"_step":8,"_timestamp":1700000001,"loss":0.25}\n',
        ),
        (
            "json",
            '[{"_step":4,"_timestamp":1700000000,"loss":0.75,"val":{"accuracy":0.5}},'
            '{"_step":8,"_timestamp":1700000001,"loss":0.25}]',
        ),
    ],
)
def test_text_import_without_sdk_preserves_history_and_duplicate_identity(
    ctx: Context,
    toy_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    contents: str,
) -> None:
    original_import = builtins.__import__

    def no_sdk(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "wandb" or name.startswith("wandb."):
            raise AssertionError("text export must not import W&B")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sdk)
    source = tmp_path / f"history.{suffix}"
    source.write_text(contents)
    source.chmod(0o444)
    result = import_wandb(ctx, source, toy_repo, task="toy-acc")
    assert source.read_text() == contents
    assert result.imported and result.metric_points == 3
    assert result.record.name == "history" and result.record.status == RunStatus.FINISHED
    points = ctx.index.metric_points(result.record.run_id)
    assert {(p.name, p.step, p.value, p.t) for p in points} == {
        ("loss", 4, 0.75, 1700000000),
        ("val/accuracy", 4, 0.5, 1700000000),
        ("loss", 8, 0.25, 1700000001),
    }
    assert result.record.started_at is not None
    assert result.record.started_at.timestamp() == 1700000000
    provenance = json.loads((ctx.run_dir(result.record) / "env/wandb.json").read_text())
    assert provenance["snapshot"] and provenance["format"] == suffix
    assert not import_wandb(ctx, source, toy_repo, task="toy-acc").imported


def test_csv_step_alias_wide_series_and_missing_values(
    ctx: Context,
    toy_repo: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "chart.csv"
    source.write_text("Step,run A - loss,run B - loss,flag\n5,0.7,,True\n9,,0.4,False\n")
    result = import_wandb(ctx, source, toy_repo)
    assert {(p.name, p.step, p.value) for p in ctx.index.metric_points(result.record.run_id)} == {
        ("run A - loss", 5, 0.7),
        ("run B - loss", 9, 0.4),
    }


def test_jsonl_fallback_steps_and_omitted_media(
    ctx: Context,
    toy_repo: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "history.jsonl"
    source.write_text(
        '{"loss":0.7,"image":{"_type":"image","width":4},"flag":true}\n'
        '{"loss":0.4,"nan":NaN,"array":[1,2]}\n'
    )
    result = import_wandb(ctx, source, toy_repo)
    assert [(p.name, p.step, p.value) for p in ctx.index.metric_points(result.record.run_id)] == [
        ("loss", 0, 0.7),
        ("loss", 1, 0.4),
    ]


@pytest.mark.parametrize(
    ("suffix", "contents"),
    [
        ("jsonl", '{"loss":0.7}\n{"loss":'),
        ("csv", "_step,loss\n0,1\n1,0.5,extra\n"),
        ("json", '[{"loss":0.7}'),
        ("jsonl", '{"label":"no scalar"}\n'),
        ("jsonl", '{"a/b":1,"a":{"b":2}}\n'),
        ("csv", "_step,loss\nbad-step,0.5\n"),
    ],
)
def test_export_failure_publishes_no_partial_run(
    ctx: Context,
    toy_repo: Path,
    tmp_path: Path,
    suffix: str,
    contents: str,
) -> None:
    source = tmp_path / f"broken.{suffix}"
    source.write_text(contents)
    with pytest.raises(RunError):
        import_wandb(ctx, source, toy_repo)
    assert not list(ctx.store.iter_records())


def test_export_cli_and_metrics_api(home: Path, toy_repo: Path, tmp_path: Path) -> None:
    source = tmp_path / "history.csv"
    source.write_text("_step,loss\n3,0.7\n5,0.4\n")
    response = CliRunner().invoke(
        app,
        ["--home", str(home), "import", "wandb", str(source), "--repo", str(toy_repo), "--json"],
        catch_exceptions=False,
    )
    assert response.exit_code == 0
    run_id = json.loads(response.stdout)["record"]["run_id"]
    with TestClient(
        create_app(home, background_repair=False, auth=False), base_url="http://127.0.0.1"
    ) as client:
        response = client.get(f"/api/v1/runs/{run_id}/metrics")
        assert response.status_code == 200
        assert [(point["step"], point["value"]) for point in response.json()] == [
            (3, 0.7),
            (5, 0.4),
        ]


@pytest.mark.parametrize("suffix", ["csv", "json", "jsonl"])
@pytest.mark.parametrize("step", ["9007199254740993.0", "9.007199254740993e15"])
def test_decimal_step_preserves_exact_integer(
    ctx: Context,
    toy_repo: Path,
    tmp_path: Path,
    suffix: str,
    step: str,
) -> None:
    source = tmp_path / f"precise.{suffix}"
    row = '{"_step":' + step + ',"loss":0.5}'
    content = "_step,loss\n" + step + ",0.5\n" if suffix == "csv" else row
    source.write_text("[" + row + "]" if suffix == "json" else content)
    result = import_wandb(ctx, source, toy_repo)
    assert ctx.index.metric_points(result.record.run_id)[0].step == 9007199254740993


@pytest.mark.parametrize("suffix", ["csv", "json", "jsonl"])
@pytest.mark.parametrize("step", ["1.0000000000000001", "9223372036854775808.0"])
def test_decimal_step_fraction_and_overflow_rejected(
    ctx: Context,
    toy_repo: Path,
    tmp_path: Path,
    suffix: str,
    step: str,
) -> None:
    source = tmp_path / f"precise.{suffix}"
    row = '{"_step":' + step + ',"loss":0.5}'
    content = "_step,loss\n" + step + ",0.5\n" if suffix == "csv" else row
    source.write_text("[" + row + "]" if suffix == "json" else content)
    with pytest.raises(RunError, match="step"):
        import_wandb(ctx, source, toy_repo)
    assert not list(ctx.store.iter_records())


def test_jsonl_bom_before_blank_line(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    source = tmp_path / "bom.jsonl"
    source.write_bytes(b'\xef\xbb\xbf\n{"_step":1,"loss":0.5}\n')
    result = import_wandb(ctx, source, toy_repo)
    assert result.metric_points == 1


def test_signaling_nan_step_is_rejected_cleanly(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    source = tmp_path / "invalid.csv"
    source.write_text("_step,loss\nsNaN,0.5\n")
    with pytest.raises(RunError, match="step"):
        import_wandb(ctx, source, toy_repo)
    assert not list(ctx.store.iter_records())
