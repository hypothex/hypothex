"""Duplicate imports avoid replay while retaining publication and recovery behavior."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any, TextIO

import pytest

from hypothex.core.context import Context
from hypothex.importers import wandb as importer


@pytest.mark.parametrize(
    ("suffix", "content"),
    [("csv", "_step,loss\n0,0.5\n"), ("json", '[{"loss":0.5}]'), ("jsonl", '{"loss":0.5}\n')],
)
def test_duplicate_skips_history_replay(
    ctx: Context,
    toy_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    content: str,
) -> None:
    source = tmp_path / f"history.{suffix}"
    source.write_text(content)
    first = importer.import_wandb(ctx, source, toy_repo)
    copy = tmp_path / f"copy.{suffix}"
    copy.write_bytes(source.read_bytes())

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("duplicate must not decode or spool history")

    monkeypatch.setattr(importer, "_read_export", forbidden)
    second = importer.import_wandb(ctx, copy, toy_repo)
    assert not second.imported
    assert second.record.run_id == first.record.run_id
    assert second.metric_points == first.metric_points == 1
    assert not list(ctx.layout.home.glob(".wandb-import-*/source"))


def test_concurrent_first_imports_publish_once(
    ctx: Context, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "history.csv"
    source.write_text("_step,loss\n0,0.5\n")
    original = importer._read_export
    ready = Barrier(2)

    def simultaneous(snapshot: Path, source: Path, output: TextIO) -> importer._Data:
        ready.wait(timeout=10)
        return original(snapshot, source, output)

    monkeypatch.setattr(importer, "_read_export", simultaneous)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(importer.import_wandb, ctx, source, toy_repo) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(result.imported for result in results) == [False, True]
    assert len({result.record.run_id for result in results}) == 1
    assert [result.metric_points for result in results] == [1, 1]
    assert len(list(ctx.store.iter_records())) == 1
    assert len(ctx.index.metric_points(results[0].record.run_id)) == 1


@pytest.mark.parametrize(
    "provenance", [None, "broken", {}, {"metric_points": True}, {"metric_points": -1}]
)
def test_incomplete_provenance_falls_back_to_parsing(
    ctx: Context, toy_repo: Path, tmp_path: Path, provenance: Any
) -> None:
    source = tmp_path / "history.csv"
    source.write_text("_step,loss\n0,0.5\n")
    first = importer.import_wandb(ctx, source, toy_repo)
    path = ctx.run_dir(first.record) / "env" / "wandb.json"
    if provenance is None:
        path.unlink()
    else:
        path.write_text(json.dumps(provenance))
    second = importer.import_wandb(ctx, source, toy_repo)
    assert not second.imported and second.metric_points == 1
    assert second.record.run_id == first.record.run_id
