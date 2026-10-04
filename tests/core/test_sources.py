import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.ids import utcnow
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord, UsageTotals
from hypothex.core.sources import group_id_for, group_labels, iter_rows, select_fields
from tests.factories import make_record

T0 = utcnow()


def _run(ctx: Context, repo: Path, run_id: str, *, minute: int = 0, **kw: Any) -> RunRecord:
    """Register the toy project and create a finished toy-acc run in group ``aaaa@c1``."""
    ctx.register_project(repo)
    fields: dict[str, Any] = {
        "task": "toy-acc",
        "status": RunStatus.FINISHED,
        "config_hash": "sha256:aaaa",
        "git": GitInfo(commit="c1"),
        "created_at": T0 + timedelta(minutes=minute),
        "cwd": str(repo),
        "environment_id": ctx.descriptor.environment_id,
    }
    fields.update(kw)
    return ctx.create_run(make_record(run_id, project="toy", **fields))


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_group_id_matches_leaderboard_format() -> None:
    rec = make_record(config_hash="sha256:0123456789abcdef", git=GitInfo(commit="9f3c2e1abc"))
    assert group_id_for(rec) == "01234567@9f3c2e1"
    assert group_id_for(make_record(config_hash="sha256:ab")) == "ab@nogit"


def test_runs_source_flattens_record(ctx: Context, toy_repo: Path) -> None:
    rec = _run(
        ctx,
        toy_repo,
        "r1",
        seed=3,
        params={"model": "svm"},
        vars={"lr": "0.1"},
        tags=["baseline"],
        created_by="agent:claude",
        hypothesis="svm",
        usage=UsageTotals(tokens_in=10, tokens_out=4, usd=0.5, seconds=2.0, calls=1),
    )
    rows = list(iter_rows(ctx, [rec], "runs"))
    assert rows == [
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "label": "svm",
            "seed": 3,
            "status": "finished",
            "created_at": rec.created_at.isoformat(),
            "created_by": "agent:claude",
            "hypothesis": "svm",
            "tags": ["baseline"],
            "host": "mac",
            "exit_code": None,
            "params.model": "svm",
            "vars.lr": "0.1",
            "usage.tokens_in": 10,
            "usage.tokens_out": 4,
            "usage.usd": 0.5,
            "usage.seconds": 2.0,
            "usage.calls": 1,
        }
    ]


def test_runs_source_omits_usage_when_absent(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    (row,) = iter_rows(ctx, [rec], "runs")
    assert not any(k.startswith("usage.") for k in row)


def test_scores_source_skips_errors(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", seed=1)
    ctx.add_score(
        rec, ScoreRecord(metric="accuracy", version="v1", key="value", value=0.75, created_at=T0)
    )
    ctx.add_score(
        rec, ScoreRecord(metric="accuracy", version="v2", key="value", error="boom", created_at=T0)
    )
    assert list(iter_rows(ctx, [rec], "scores")) == [
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "label": "group aaaa@c1",
            "seed": 1,
            "metric": "accuracy",
            "version": "v1",
            "key": "value",
            "value": 0.75,
        }
    ]


def test_metrics_source_reads_full_history(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    _jsonl(
        ctx.run_dir(rec) / "metrics.jsonl",
        [{"name": "loss", "step": s, "value": 1.0 / (s + 1), "t": 100.0 + s} for s in range(3)],
    )
    rows = list(iter_rows(ctx, [rec], "metrics", fields=["step", "value"]))
    assert rows == [
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "label": "group aaaa@c1",
            "seed": None,
            "step": 0,
            "value": 1.0,
        },
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "label": "group aaaa@c1",
            "seed": None,
            "step": 1,
            "value": 0.5,
        },
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "label": "group aaaa@c1",
            "seed": None,
            "step": 2,
            "value": 1.0 / 3,
        },
    ]


def test_predictions_source_joins_references_meta_and_scores(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    pred = ctx.run_dir(rec) / "predictions"
    _jsonl(
        pred / "predictions.jsonl",
        [
            {"id": "ex-0", "prediction": 0, "meta": {"category": "ok", "difficulty": 1}},
            {"id": "ex-1", "prediction": 0, "reference": 7},
        ],
    )
    _jsonl(pred / "scores.accuracy@v1.jsonl", [{"id": "ex-0", "correct": True}])
    rows = list(iter_rows(ctx, [rec], "predictions"))
    # toy dataset references are [0, 1, 0, 0]; ex-1 keeps its own reference 7
    assert rows == [
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "label": "group aaaa@c1",
            "seed": None,
            "id": "ex-0",
            "prediction": 0,
            "reference": 0,
            "meta.category": "ok",
            "meta.difficulty": 1,
            "accuracy@v1.correct": True,
        },
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "label": "group aaaa@c1",
            "seed": None,
            "id": "ex-1",
            "prediction": 0,
            "reference": 7,
        },
    ]


def test_samples_usage_and_traces_sources(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", seed=2)
    run_dir = ctx.run_dir(rec)
    _jsonl(run_dir / "samples" / "latency_ms.jsonl", [{"value": 12}, {"value": 15.5}, {}])
    _jsonl(
        run_dir / "usage.jsonl",
        [{"example_id": "ex-0", "tokens_in": 100, "tokens_out": 20, "usd": 0.01, "seconds": 1.5}],
    )
    _jsonl(
        run_dir / "traces" / "ex_0.jsonl",
        [
            {"turn": 1, "tool": "search", "args": {"q": "a"}, "result": "hit", "tokens_in": 9},
            {"turn": 2, "tool": "edit", "error": "patch failed"},
        ],
    )
    base = {"run_id": "r1", "group_id": "aaaa@c1", "label": "group aaaa@c1", "seed": 2}
    assert list(iter_rows(ctx, [rec], "samples")) == [
        {**base, "name": "latency_ms", "value": 12.0},
        {**base, "name": "latency_ms", "value": 15.5},
    ]
    assert list(iter_rows(ctx, [rec], "usage")) == [
        {
            **base,
            "example_id": "ex-0",
            "tokens_in": 100,
            "tokens_out": 20,
            "usd": 0.01,
            "seconds": 1.5,
        }
    ]
    traces = list(iter_rows(ctx, [rec], "traces", fields=["example_id", "turn", "tool", "error"]))
    assert traces == [
        {**base, "example_id": "ex_0", "turn": 1, "tool": "search", "error": None},
        {**base, "example_id": "ex_0", "turn": 2, "tool": "edit", "error": "patch failed"},
    ]


def test_missing_files_yield_no_rows(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    for source in ("scores", "metrics", "predictions", "samples", "usage", "traces"):
        assert list(iter_rows(ctx, [rec], source)) == []


def test_fields_that_name_row_keys_keep_their_values(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", seed=7)
    ctx.add_score(
        rec, ScoreRecord(metric="accuracy", version="v1", key="value", value=0.75, created_at=T0)
    )
    fields = ["run_id", "group_id", "label", "seed", "value"]
    assert list(iter_rows(ctx, [rec], "scores", fields=fields)) == [
        {"run_id": "r1", "group_id": "aaaa@c1", "label": "group aaaa@c1", "seed": 7, "value": 0.75}
    ]
    row = {"run_id": "r1", "group_id": "g", "label": "x", "seed": 1, "metric": "m", "value": 2.0}
    assert select_fields(row, ["seed", "value", "nope"]) == {
        "run_id": "r1",
        "group_id": "g",
        "label": "x",
        "seed": 1,
        "value": 2.0,
        "nope": None,
    }
    assert select_fields(row, None) is row


def test_fields_restriction_fills_missing_with_none(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1", params={"model": "rf"})
    rows = list(iter_rows(ctx, [rec], "runs", fields=["params.model", "params.nope"]))
    assert rows == [
        {
            "run_id": "r1",
            "group_id": "aaaa@c1",
            "label": "group aaaa@c1",
            "seed": None,
            "params.model": "rf",
            "params.nope": None,
        }
    ]


def test_rows_follow_run_order(ctx: Context, toy_repo: Path) -> None:
    a = _run(ctx, toy_repo, "a", minute=0)
    b = _run(ctx, toy_repo, "b", minute=1, config_hash="sha256:bbbb")
    rows = list(iter_rows(ctx, [b, a], "runs", fields=[]))
    assert [(r["run_id"], r["group_id"]) for r in rows] == [("b", "bbbb@c1"), ("a", "aaaa@c1")]


def test_unknown_source_raises(ctx: Context, toy_repo: Path) -> None:
    rec = _run(ctx, toy_repo, "r1")
    with pytest.raises(ConfigError, match="unknown source 'nope'"):
        list(iter_rows(ctx, [rec], "nope"))  # ty: ignore[invalid-argument-type]


def test_group_labels_follow_the_leaderboard_rule() -> None:
    older = make_record("a", config_hash="sha256:aaaa", hypothesis="svm, rbf kernel")
    newer = make_record(
        "b", config_hash="sha256:aaaa", hypothesis="", created_at=older.created_at + timedelta(1)
    )
    tagged = make_record("c", config_hash="sha256:bbbb", tags=["rf", "base"])
    versioned = make_record("d", config_hash="sha256:cccc", params={"version": "v3"})
    labels = group_labels([newer, older, tagged, versioned])
    # newest non-empty hypothesis, else first tag, else "group <id>"
    assert labels == {"aaaa@nogit": "svm", "bbbb@nogit": "base", "cccc@nogit": "group cccc@nogit"}
    assert group_labels([versioned], version_param="version") == {"cccc@nogit": "v3"}


def test_rows_carry_group_labels_and_accept_overrides(ctx: Context, toy_repo: Path) -> None:
    a = _run(ctx, toy_repo, "a", hypothesis="svm; rbf")
    b = _run(ctx, toy_repo, "b", minute=1, config_hash="sha256:bbbb", tags=["rf"])
    rows = list(iter_rows(ctx, [a, b], "runs", fields=[]))
    assert [(r["group_id"], r["label"]) for r in rows] == [("aaaa@c1", "svm"), ("bbbb@c1", "rf")]
    rows = list(iter_rows(ctx, [a, b], "runs", fields=[], labels={"bbbb@c1": "forest"}))
    assert [r["label"] for r in rows] == ["svm", "forest"]


def test_predictions_of_a_host_copy_never_read_its_repo_path(ctx: Context, toy_repo: Path) -> None:
    # the repo path of a project copied from a host is the host's: no references from it
    rec = _run(ctx, toy_repo, "r1")
    entry = ctx.store.load_project("toy")
    ctx.store.save_project(entry.model_copy(update={"remote_host": "gpu1"}))
    _jsonl(
        ctx.run_dir(rec) / "predictions" / "predictions.jsonl", [{"id": "ex-1", "prediction": 0}]
    )
    [row] = list(iter_rows(ctx, [rec], "predictions"))
    assert row["reference"] is None
