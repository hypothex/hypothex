"""Public import, storage and CLI contracts for local W&B logs."""

from __future__ import annotations

import json
import shutil
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hypothex.api.app import create_app
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.index import rebuild_index
from hypothex.core.records import RunStatus
from hypothex.importers.wandb import import_wandb

wandb = pytest.importorskip("wandb")
from wandb.proto import wandb_internal_pb2 as pb  # noqa: E402


def _write_records(path: Path, records: list[Any]) -> None:
    output = bytearray(b":W&B\xe1\xbe\x00")
    for record in records:
        payload = record.SerializeToString()
        first = True
        while payload:
            remaining = 32768 - len(output) % 32768
            if remaining < 7:
                output.extend(bytes(remaining))
                remaining = 32768
            chunk, payload = payload[: remaining - 7], payload[remaining - 7 :]
            kind = (1 if first else 4) if not payload else (2 if first else 3)
            crc = zlib.crc32(chunk, zlib.crc32(bytes([kind]))) & 0xFFFFFFFF
            output.extend(struct.pack("<IHB", crc, len(chunk), kind))
            output.extend(chunk)
            first = False
    path.write_bytes(output)


def _log(path: Path, *, finished: bool = True, exit_code: int = 0, count: int = 3) -> Path:
    records: list[Any] = []
    run = pb.Record()
    run.run.run_id = "original-abc"
    run.run.display_name = "Baseline"
    run.run.project = "upstream-project"
    run.run.entity = "upstream-team"
    run.run.tags.append("offline")
    run.run.start_time.FromSeconds(1700000000)
    run.run.config.update.add(key="learning_rate", value_json="0.001")
    records.append(run)
    for step in range(count):
        history = pb.Record()
        for key, value in {
            "_step": step * 2,
            "_timestamp": 1700000000 + step,
            "loss": 1 / (step + 1),
            "ok": True,
            "nan": float("nan"),
            "media": {"_type": "image"},
        }.items():
            history.history.item.add(key=key, value_json=json.dumps(value))
        history.history.item.add(nested_key=["val", "accuracy"], value_json="0.8")
        records.append(history)
    config = pb.Record()
    config.config.update.add(nested_key=["optimizer", "beta"], value_json="0.9")
    records.append(config)
    summary = pb.Record()
    summary.summary.update.add(key="best_loss", value_json="0.3")
    records.append(summary)
    if finished:
        end = pb.Record()
        end.exit.exit_code = exit_code
        records.append(end)
    _write_records(path, records)
    return path


def test_import_preserves_history_metadata_and_source(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    source = _log(tmp_path / "run.wandb")
    before = source.read_bytes()
    source.chmod(0o444)
    result = import_wandb(ctx, source, toy_repo, task="toy-acc")
    assert source.read_bytes() == before
    assert result.imported and result.metric_points == 6
    record = result.record
    assert record.status == RunStatus.FINISHED
    assert record.name == "Baseline" and record.task == "toy-acc"
    assert record.tags == ["offline", "wandb"]
    assert record.params["learning_rate"] == "0.001"
    assert record.command == [] and record.executor.type == "import"
    assert record.artifacts == []
    points = ctx.store.read_metric_points(record.project, record.run_id)
    assert [(p.step, p.t) for p in points if p.name == "loss"] == [
        (0, 1700000000),
        (2, 1700000001),
        (4, 1700000002),
    ]
    assert {p.name for p in points} == {"loss", "val/accuracy"}
    provenance = json.loads((ctx.run_dir(record) / "env/wandb.json").read_text())
    assert provenance["run_id"] == "original-abc"
    assert provenance["summary"] == {"best_loss": 0.3}
    assert len(ctx.index.metric_points(record.run_id)) == 6


def test_duplicate_copy_and_changed_file(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    source = _log(tmp_path / "one.wandb")
    first = import_wandb(ctx, source, toy_repo)
    copy = tmp_path / "copy.wandb"
    shutil.copyfile(source, copy)
    second = import_wandb(ctx, copy, toy_repo)
    assert not second.imported and second.record.run_id == first.record.run_id
    changed = _log(tmp_path / "changed.wandb", count=4)
    third = import_wandb(ctx, changed, toy_repo)
    assert third.imported and third.record.run_id != first.record.run_id
    assert len(list(ctx.store.iter_records())) == 2


def test_bad_input_publishes_nothing(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    unfinished = _log(tmp_path / "unfinished.wandb", finished=False)
    with pytest.raises(RunError, match="unfinished"):
        import_wandb(ctx, unfinished, toy_repo)
    broken = tmp_path / "broken.wandb"
    broken.write_bytes(unfinished.read_bytes()[:-2])
    with pytest.raises(RunError):
        import_wandb(ctx, broken, toy_repo)
    with pytest.raises(RunError, match="exactly one"):
        import_wandb(ctx, tmp_path, toy_repo)
    with pytest.raises(RunError, match="unknown task"):
        import_wandb(ctx, unfinished, toy_repo, task="missing")
    assert not list(ctx.store.iter_records())
    assert not list(ctx.layout.home.glob(".wandb-import-*"))


def test_failed_run_and_folder_import(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    folder = tmp_path / "offline-run"
    folder.mkdir()
    _log(folder / "run.wandb", exit_code=3)
    result = import_wandb(ctx, folder, toy_repo)
    assert result.record.status == RunStatus.FAILED and result.record.exit_code == 3


def test_cli_and_public_metrics_after_rebuild(home: Path, toy_repo: Path, tmp_path: Path) -> None:
    source = _log(tmp_path / "run.wandb")
    response = CliRunner().invoke(
        app,
        ["--home", str(home), "import", "wandb", str(source), "--repo", str(toy_repo), "--json"],
        catch_exceptions=False,
    )
    assert response.exit_code == 0, response.output
    result = json.loads(response.stdout)
    run_id = result["record"]["run_id"]
    ctx = Context.open(home)
    rebuild_index(ctx.index, ctx.store)
    with TestClient(
        create_app(home, background_repair=False, auth=False), base_url="http://127.0.0.1"
    ) as client:
        response = client.get(f"/api/v1/runs/{run_id}/metrics")
        assert response.status_code == 200, response.text
        assert {p["name"] for p in response.json()} == {"loss", "val/accuracy"}
        assert len(response.json()) == 6


def test_large_history_retains_full_file_bounded_index(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    result = import_wandb(ctx, _log(tmp_path / "many.wandb", count=2500), toy_repo)
    assert result.metric_points == 5000
    assert len(ctx.store.read_metric_points("toy", result.record.run_id)) == 5000
    indexed = ctx.index.metric_points(result.record.run_id)
    assert len(indexed) <= 2000
    assert max(p.step for p in indexed) == 4998


@pytest.mark.parametrize("step", [True, 1.5, 2**63, "oops"])
def test_invalid_steps_fail_without_run(
    ctx: Context, toy_repo: Path, tmp_path: Path, step: Any
) -> None:
    from io import StringIO

    from hypothex.importers.wandb import _Data, _history

    history = pb.HistoryRecord()
    history.item.add(key="_step", value_json=json.dumps(step))
    with pytest.raises(RunError, match="step"):
        _history(_Data(), history, StringIO())


def test_typed_history_values_and_incomplete_exit(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    run = pb.Record()
    run.run.run_id = "typed"
    history = pb.Record()
    history.history.item.add(key="_step", integer=12)
    history.history.item.add(key="_timestamp", number=1700000000.5)
    history.history.item.add(key="loss", number=0.25)
    history.history.item.add(key="tokens", integer=42)
    history.history.item.add(key="flag", boolean=True)
    history.history.item.add(key="label", text="run")
    history.history.item.add(key="image", json='{"_type":"image"}')
    history.history.item.add(key="none", none=0)
    exit_record = pb.Record()
    exit_record.exit.exit_code = 0
    source = tmp_path / "typed.wandb"
    _write_records(source, [run, history, exit_record])
    result = import_wandb(ctx, source, toy_repo)
    points = ctx.store.read_metric_points("toy", result.record.run_id)
    assert {(p.name, p.step, p.value, p.t) for p in points} == {
        ("loss", 12, 0.25, 1700000000.5),
        ("tokens", 12, 42, 1700000000.5),
    }
    exit_record.exit.not_complete = True
    _write_records(source, [run, history, exit_record])
    with pytest.raises(RunError, match="unfinished"):
        import_wandb(ctx, source, toy_repo)
    assert len(list(ctx.store.iter_records())) == 1


def test_external_names_normalized_original_preserved(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    run = pb.Record()
    run.run.run_id = "long-name"
    run.run.display_name = "multiline\n" + "long name " * 20
    end = pb.Record()
    end.exit.exit_code = 0
    source = tmp_path / "long.wandb"
    _write_records(source, [run, end])
    result = import_wandb(ctx, source, toy_repo)
    assert result.record.name is not None and len(result.record.name) <= 80
    assert "\n" not in result.record.name
    provenance = json.loads((ctx.run_dir(result.record) / "env/wandb.json").read_text())
    assert provenance["name"] == run.run.display_name


@pytest.mark.parametrize("method", ["replace_metric_points", "upsert_run"])
def test_interrupted_index_write_recovers_on_open(
    ctx: Context, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    source = _log(tmp_path / "recover.wandb")

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("interrupted index write")

    with monkeypatch.context() as patch:
        patch.setattr(ctx.index, method, fail)
        with pytest.raises(RuntimeError, match="interrupted"):
            import_wandb(ctx, source, toy_repo)
    reopened = Context.open(ctx.layout.home)
    records = list(reopened.store.iter_records())
    assert len(records) == 1
    assert reopened.index.get_run(records[0].run_id) is not None
    assert len(reopened.index.metric_points(records[0].run_id)) == 6
    retry = import_wandb(reopened, source, toy_repo)
    assert not retry.imported and retry.record.run_id == records[0].run_id


@pytest.mark.parametrize("encoding", ["value_json", "json"])
@pytest.mark.parametrize(
    "step", ["9007199254740993.0", "9.007199254740993e15", "9223372036854775807.0"]
)
def test_binary_json_step_is_exact(
    ctx: Context, toy_repo: Path, tmp_path: Path, encoding: str, step: str
) -> None:
    run, history, end = pb.Record(), pb.Record(), pb.Record()
    run.run.run_id = "precise"
    run.run.config.update.add(key="lr", value_json="0.001")
    history.history.item.add(key="_step", **{encoding: step})
    history.history.item.add(key="loss", **{encoding: "0.25"})
    end.exit.exit_code = 0
    source = tmp_path / "precise.wandb"
    _write_records(source, [run, history, end])
    result = import_wandb(ctx, source, toy_repo)
    expected = 9223372036854775807 if step.startswith("922") else 9007199254740993
    assert ctx.index.metric_points(result.record.run_id)[0].step == expected
    assert ctx.store.read_metric_points("toy", result.record.run_id)[0].step == expected
    assert result.record.params["lr"] == "0.001"


@pytest.mark.parametrize("encoding", ["value_json", "json"])
@pytest.mark.parametrize("step", ["1.0000000000000001", "9223372036854775808.0"])
def test_binary_json_invalid_step_publishes_nothing(
    ctx: Context, toy_repo: Path, tmp_path: Path, encoding: str, step: str
) -> None:
    run, history, end = pb.Record(), pb.Record(), pb.Record()
    run.run.run_id = "invalid"
    history.history.item.add(key="_step", **{encoding: step})
    history.history.item.add(key="loss", **{encoding: "0.25"})
    end.exit.exit_code = 0
    source = tmp_path / "invalid.wandb"
    _write_records(source, [run, history, end])
    with pytest.raises(RunError, match="step"):
        import_wandb(ctx, source, toy_repo)
    assert not list(ctx.store.iter_records())


def test_binary_imports_group_seed_repeats(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    from hypothex.core.leaderboard import group_id_for
    from hypothex.core.seeds import config_hash
    from hypothex.core.taskruns import task_runs

    groups = []
    for i, (seed, rate) in enumerate([(1, 0.1), (2, 0.1), (1, 0.2), (1, 0.1)]):
        run, end = pb.Record(), pb.Record()
        run.run.run_id = f"repeat-{i}"
        run.run.config.update.add(key="seed", value_json=str(seed))
        run.run.config.update.add(key="lr", value_json=str(rate))
        end.exit.exit_code = 0
        source = tmp_path / "seed.wandb"
        _write_records(source, [run, end])
        result = import_wandb(ctx, source, toy_repo, task="toy-acc")
        assert result.record.config_hash == config_hash({"seed": seed, "lr": rate})
        assert result.record.params["seed"] == str(seed)
        assert result.record.seed == seed
        groups.append(group_id_for(result.record))
    assert groups[0] == groups[1]
    assert groups[0] != groups[2]
    assert groups[0] == groups[3]
    board = task_runs(ctx, "toy-acc", project="toy")
    repeats = next(group for group in board.groups if len(group.run_ids) == 3)
    assert repeats.n == 2


@pytest.mark.parametrize("seed", [None, True, "7", 7.5, {"value": 7}])
def test_noninteger_seed_is_retained_without_coercion(
    ctx: Context, toy_repo: Path, tmp_path: Path, seed: Any
) -> None:
    run, end = pb.Record(), pb.Record()
    run.run.run_id = "untyped-seed"
    run.run.config.update.add(key="seed", value_json=json.dumps(seed))
    end.exit.exit_code = 0
    source = tmp_path / "seed.wandb"
    _write_records(source, [run, end])
    result = import_wandb(ctx, source, toy_repo)
    assert result.record.seed is None
    assert result.record.params["seed"] == str(seed)


def test_binary_duplicate_does_not_decode_history(
    ctx: Context, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.importers import wandb as importer

    source = _log(tmp_path / "duplicate.wandb")
    first = import_wandb(ctx, source, toy_repo)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("duplicate must not decode or spool history")

    monkeypatch.setattr(importer, "_read", forbidden)
    second = import_wandb(ctx, source, toy_repo)
    assert not second.imported
    assert second.record.run_id == first.record.run_id
    assert second.metric_points == first.metric_points == 6
