"""Strict opt-in comparisons require current complete evaluation evidence."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.errors import EvalError
from hypothex.core.evaluation import evaluate_run
from hypothex.core.records import DatasetRef, ScoreRecord
from tests.factories import PREDS_075, seed_finished_run


def bound_pair(ctx: Context, repo: Path) -> tuple[Path, Path]:
    """Evaluate a known fixed example using real workers and recorded dataset identity."""
    paths = []
    for rid, predictions in (
        ("a", PREDS_075),
        ("b", [{"id": f"ex-{i}", "prediction": v} for i, v in enumerate([0, 1, 0, 0])]),
    ):
        record = seed_finished_run(ctx, repo, rid, predictions=predictions)
        record.datasets = [
            DatasetRef(
                name="toyset",
                version="v1",
                split="test",
                path="data/test.jsonl",
                hash="sha256:"
                + hashlib.sha256((repo / "data/test.jsonl").read_bytes()).hexdigest(),
                hash_mode="full",
            )
        ]
        ctx.store.write_record(record)
        ctx.index.upsert_run(record)
        evaluate_run(ctx, rid)
        paths.append(ctx.run_dir(record) / "predictions" / "scores.accuracy@v1.jsonl")
    return paths[0], paths[1]


def test_bound_comparison_real_worker_and_http_opt_in(ctx: Context, toy_repo: Path) -> None:
    bound_pair(ctx, toy_repo)
    result = q.compare_examples(ctx, "a", "b", "accuracy", require_bound=True)
    assert result.fixed == ["ex-3"] and result.broken == [] and result.both_pass == 3
    evaluate_run(ctx, "b")
    assert q.compare_examples(ctx, "a", "b", "accuracy@v1", require_bound=True) == result
    with TestClient(
        create_app(ctx.layout.home, background_repair=False, hub=False), base_url="http://localhost"
    ) as client:
        args = {"a": "a", "b": "b", "metric": "accuracy", "require_bound": "true"}
        assert client.get("/api/v1/compare/examples", params=args).json()["fixed"] == ["ex-3"]
        (toy_repo / "toymetrics.py").write_text("def accuracy(examples):\n    return 1.0\n")
        evaluate_run(ctx, "b")
        stale = client.get("/api/v1/compare/examples", params=args)
        assert stale.status_code == 400 and stale.json()["type"] == "EvalError"
        args.pop("require_bound")
        assert client.get("/api/v1/compare/examples", params=args).json()["fixed"] == ["ex-3"]


@pytest.mark.parametrize(
    "problem",
    ["wildcard", "source", "dataset", "unknown_source", "unbound", "count", "ids", "tampered"],
)
def test_bound_comparison_refuses_incoherent_current_evidence(
    ctx: Context, toy_repo: Path, problem: str
) -> None:
    _, path = bound_pair(ctx, toy_repo)
    rec = ctx.find_record("b")
    old = ctx.index.scores_for(["b"])["b"][-1]
    if problem == "dataset":
        rec.datasets[0].hash = "sha256:different"
        ctx.store.write_record(rec)
        ctx.index.upsert_run(rec)
    elif problem == "tampered":
        path.write_text(path.read_text().replace("true", "false"))
    else:
        changed = old.model_copy(update={"created_at": old.created_at + timedelta(seconds=1)})
        if problem == "wildcard":
            changed = ScoreRecord(
                metric="accuracy",
                version="v1",
                key="*",
                error="failed",
                created_at=changed.created_at,
            )
        elif problem == "source":
            changed.source_hash = "sha256:other"
        elif problem == "unknown_source":
            changed.source_hash = None
        elif problem == "unbound":
            changed.per_example_hash = None
        elif problem == "count":
            changed.evaluation_examples = 100
        elif problem == "ids":
            changed.evaluation_ids_hash = "sha256:other"
        ctx.add_score(rec, changed)
    with pytest.raises(EvalError):
        q.compare_examples(ctx, "a", "b", "accuracy", require_bound=True)


def test_bound_comparison_rejects_file_replacement_during_read(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, target = bound_pair(ctx, toy_repo)
    read = Path.read_bytes
    replaced = False

    def racing_read(path: Path) -> bytes:
        nonlocal replaced
        raw = read(path)
        if path == target and not replaced:
            replaced = True
            path.write_bytes(raw.replace(b"true", b"false"))
        return raw

    monkeypatch.setattr(Path, "read_bytes", racing_read)
    with pytest.raises(EvalError, match="changed|bound"):
        q.compare_examples(ctx, "a", "b", "accuracy", require_bound=True)


def test_bound_comparison_uses_exact_shared_intersection_of_complete_cohorts(
    ctx: Context, toy_repo: Path
) -> None:
    import json

    bound_pair(ctx, toy_repo)
    rec = ctx.find_record("b")
    predictions = ctx.run_dir(rec) / "predictions" / "predictions.jsonl"
    rows = [json.loads(line) for line in predictions.read_text().splitlines()]
    predictions.write_text("".join(json.dumps(row) + "\n" for row in rows if row["id"] != "ex-0"))
    evaluate_run(ctx, "b")
    result = q.compare_examples(ctx, "a", "b", "accuracy", require_bound=True)
    assert result.fixed == ["ex-3"] and result.broken == []
    assert result.both_pass == 2 and result.both_fail == 0


def test_bound_comparison_rejects_new_evaluation_during_query(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Iterable

    bound_pair(ctx, toy_repo)
    read = ctx.index.scores_for
    calls = 0

    def racing_scores(run_ids: Iterable[str]) -> dict[str, list[ScoreRecord]]:
        nonlocal calls
        calls += 1
        if calls == 2:
            old = read(["b"])["b"][-1]
            ctx.add_score(
                ctx.find_record("b"),
                old.model_copy(
                    update={
                        "created_at": old.created_at + timedelta(seconds=1),
                        "per_example_hash": None,
                    }
                ),
            )
        return read(run_ids)

    monkeypatch.setattr(ctx.index, "scores_for", racing_scores)
    with pytest.raises(EvalError, match="changed"):
        q.compare_examples(ctx, "a", "b", "accuracy", require_bound=True)


@pytest.mark.parametrize("invalid", ["yes", None, 0.5])
def test_bound_comparison_rejects_nonbinary_or_missing_outcome_fields(
    ctx: Context, toy_repo: Path, invalid: object
) -> None:
    import json

    _, path = bound_pair(ctx, toy_repo)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if invalid is None:
        rows[-1].pop("correct")
    else:
        rows[-1]["correct"] = invalid
    raw = "".join(json.dumps(row) + "\n" for row in rows).encode()
    path.write_bytes(raw)
    rec = ctx.find_record("b")
    old = ctx.index.scores_for(["b"])["b"][-1]
    ctx.add_score(
        rec,
        old.model_copy(
            update={
                "created_at": old.created_at + timedelta(seconds=1),
                "per_example_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
            }
        ),
    )
    with pytest.raises(EvalError, match="binary"):
        q.compare_examples(ctx, "a", "b", "accuracy", require_bound=True)


def test_bound_comparison_requires_same_task_and_skips_legacy_file_reader(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bound_pair(ctx, toy_repo)

    def reject_legacy_reader(*args: object) -> object:
        raise AssertionError("strict comparisons must not parse unrelated legacy files")

    monkeypatch.setattr(q, "_per_example", reject_legacy_reader)
    assert q.compare_examples(ctx, "a", "b", "accuracy@v1", require_bound=True).fixed == ["ex-3"]
    rec = ctx.find_record("b")
    rec.task = "toy-broken"  # Same metric, source, split and dataset; different task.
    ctx.store.write_record(rec)
    ctx.index.upsert_run(rec)
    with pytest.raises(EvalError, match="identity"):
        q.compare_examples(ctx, "a", "b", "accuracy@v1", require_bound=True)
