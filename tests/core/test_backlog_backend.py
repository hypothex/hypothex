"""Selected-metric and pricing/population contracts for the bounded UI backlog."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from hypothex.core import queries as q
from hypothex.core.config import ProjectConfig
from hypothex.core.context import Context
from hypothex.core.cost import add_costs, compute_cost
from hypothex.core.errors import ConfigError
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import build_leaderboard
from hypothex.core.panels import query_panel, query_view
from hypothex.core.records import (
    CostTotals,
    DatasetRef,
    ExecutorInfo,
    RunRecord,
    RunStatus,
    ScoreRecord,
)
from hypothex.core.views import PanelSpec, ViewSpec
from tests.factories import make_record


def config(kind: str = "generic") -> ProjectConfig:
    """Return a task with opposite-direction scalar and multi-key metrics."""
    return ProjectConfig.model_validate(
        {
            "project": "toy",
            "datasets": {"d": {"version": "v1", "path": "data/test.jsonl"}},
            "metrics": {
                "acc": {"version": "v1", "fn": "toymetrics:accuracy"},
                "latency": {
                    "version": "v1",
                    "fn": "toymetrics:accuracy",
                    "higher_is_better": False,
                    "unit": "ms",
                },
            },
            "tasks": {
                "t": {"dataset": "d", "metrics": ["acc", "latency"], "primary": "acc", "kind": kind}
            },
        }
    )


def score(
    metric: str,
    value: float,
    *,
    key: str = "value",
    version: str = "v1",
    source: str = "sha256:scorer",
) -> ScoreRecord:
    """Build a score with explicit evaluator provenance."""
    return ScoreRecord(
        metric=metric,
        key=key,
        version=version,
        value=value,
        source_hash=source,
        created_at=utcnow(),
    )


def member(rid: str, *, cost: CostTotals | None = None, **changes: Any) -> RunRecord:
    """Build a finished member with an explicitly fingerprinted example cohort."""
    now = utcnow()
    fields: dict[str, Any] = {
        "task": "t",
        "status": RunStatus.FINISHED,
        "config_hash": rid,
        "hypothesis": rid.upper(),
        "seed": 1,
        "started_at": now,
        "ended_at": now + timedelta(hours=1),
        "cost": cost,
        "datasets": [
            DatasetRef(
                name="d", version="v1", path="data/test.jsonl", hash="sha256:data", hash_mode="full"
            )
        ],
    }
    fields.update(changes)
    return make_record(rid, **fields)


def indexed(ctx: Context, toy_repo: Path) -> tuple[RunRecord, RunRecord]:
    """Persist two groups with opposite rankings and deliberately different example fields."""
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(config().model_dump(mode="json")))
    ctx.register_project(toy_repo)
    records = (member("a"), member("b"))
    for rec, acc, delay in zip(records, [1.0, 0.5], [100.0, 10.0], strict=True):
        ctx.create_run(rec)
        for item in [score("acc", acc), score("latency", delay, key="p95")]:
            ctx.add_score(rec, item)
        folder = ctx.run_dir(rec) / "predictions"
        (folder / "predictions.jsonl").write_text(
            "".join(
                json.dumps({"id": name, "prediction": 1, "reference": 1}) + "\n"
                for name in ["e1", "e2"]
            )
        )
        for metric, rows in {
            "acc": [{"id": "e1", "correct": rec.run_id == "a"}, {"id": "e2", "correct": True}],
            "latency": [
                {"id": "e1", "p95": delay, "correct": rec.run_id == "a"},
                {"id": "e2", "p95": delay, "correct": rec.run_id == "a"},
            ],
        }.items():
            (folder / f"scores.{metric}@v1.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows)
            )
    return records


def test_selected_primary_recomputes_rank_direction_units_headline_and_examples(
    ctx: Context, toy_repo: Path
) -> None:
    indexed(ctx, toy_repo)
    default = q.get_leaderboard(ctx, "t", "toy")
    selected = q.get_leaderboard(ctx, "t", "toy", primary="latency/p95")
    assert default.primary == "acc/value" and default.rows[0].run_ids == ["a"]
    assert selected.primary == "latency/p95" and selected.rows[0].run_ids == ["b"]
    assert selected.higher_is_better is False and selected.unit == "ms"
    assert selected.rows[0].primary.mean == 10.0
    assert selected.rows[1].vs_best.test == "paired_bootstrap"
    assert selected.rows[0].test_interval.lo == 10.0
    assert "B −90% over A" in selected.headline
    assert q.get_leaderboard(ctx, "t", "toy").model_dump() == default.model_dump()
    assert (
        q.get_leaderboard(ctx, "t", "toy", primary="latency/p95").model_dump()
        == selected.model_dump()
    )


@pytest.mark.parametrize(
    "primary", ["missing", "acc/unknown", "latency/", "latency/p95/extra", "acc@v1"]
)
def test_unknown_selected_primary_is_not_silently_relabelled(
    ctx: Context, toy_repo: Path, primary: str
) -> None:
    indexed(ctx, toy_repo)
    with pytest.raises(ConfigError):
        q.get_leaderboard(ctx, "t", "toy", primary=primary)


def test_selected_key_validation_uses_requested_metric_version(
    ctx: Context, toy_repo: Path
) -> None:
    records = indexed(ctx, toy_repo)
    for rec in records:
        ctx.add_score(rec, score("latency", 50.0, key="p99", version="v0"))
    with pytest.raises(ConfigError):
        q.get_leaderboard(ctx, "t", "toy", primary="latency/p99")
    selected = q.get_leaderboard(ctx, "t", "toy", {"latency": "v0"}, primary="latency/p99")
    assert selected.primary == "latency/p99" and selected.metric_versions["latency"] == "v0"


def test_panel_primary_has_separate_view_cache_and_best_pick(ctx: Context, toy_repo: Path) -> None:
    indexed(ctx, toy_repo)
    panels = [
        {"type": "leaderboard", "title": "Accuracy"},
        {"type": "leaderboard", "title": "Latency", "data": {"primary": "latency/p95"}},
        {
            "type": "stat_strip",
            "title": "Latency stats",
            "data": {"primary": "latency/p95", "pick": "best"},
        },
    ]
    view = ViewSpec.model_validate({"title": "Selected metric", "panels": panels})
    default, selected, strip = query_view(ctx, "toy", "t", view)
    assert default.rows[0]["run_ids"] == ["a"] and selected.rows[0]["run_ids"] == ["b"]
    assert selected.meta["primary"] == strip.meta["primary"] == "latency/p95"
    assert strip.meta["higher_is_better"] is False and strip.meta["unit"] == "ms"
    assert "B" in strip.meta["headline"]


@pytest.mark.parametrize(
    "rate, expected", [(None, False), (0.0, True), (0.00000001, True), (2.0, True)]
)
def test_gpu_pricing_remembers_unknown_free_and_rounded_rates(
    rate: float | None, expected: bool
) -> None:
    rec = member("gpu", executor=ExecutorInfo(gpus=[0]))
    assert compute_cost(rec, rate).gpu_pricing_complete is expected
    assert compute_cost(member("cpu"), None).gpu_pricing_complete is True


def test_cost_addition_preserves_unknown_pricing_and_known_dollars() -> None:
    priced = CostTotals(
        gpu_hours=1, gpu_usd=2, api_usd=0.5, total_usd=2.5, gpu_pricing_complete=True
    )
    unpriced = CostTotals(gpu_hours=1, api_usd=0.75, total_usd=0.75, gpu_pricing_complete=False)
    total = add_costs([priced, unpriced])
    assert total.total_usd == 3.25 and total.api_usd == 1.25 and total.gpu_usd == 2
    assert total.gpu_pricing_complete is False
    assert add_costs([priced, CostTotals(gpu_hours=1)]).gpu_pricing_complete is None


def test_group_cost_requires_every_member_and_preserves_partial_known_dollars() -> None:
    a = member(
        "a",
        config_hash="same",
        cost=CostTotals(gpu_hours=1, gpu_usd=2, total_usd=2, gpu_pricing_complete=True),
    )
    b = member(
        "b",
        config_hash="same",
        cost=CostTotals(gpu_hours=1, api_usd=0.4, total_usd=0.4, gpu_pricing_complete=False),
    )
    scores = {r.run_id: [score("acc", 0.5)] for r in [a, b]}
    row = build_leaderboard("toy", "t", config(), [a, b], scores).rows[0]
    assert row.cost.total_usd == 2.4 and row.cost.api_usd == 0.4
    assert row.cost_complete is False and row.cost.gpu_pricing_complete is False
    b.cost = None
    row = build_leaderboard("toy", "t", config(), [a, b], scores).rows[0]
    assert row.cost.total_usd == 2.0 and row.cost_complete is False


def bind_examples(scores: dict[str, list[ScoreRecord]], examples: dict[str, Any]) -> dict[str, str]:
    """Construct explicit evaluation bindings for pure model fixtures."""
    hashes: dict[str, str] = {}
    for rid, values in examples.items():
        digest = "sha256:" + hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        hashes[rid] = digest
        latest = scores[rid][-1]
        latest.per_example_hash = digest
        latest.evaluation_examples = len(values)
        latest.evaluation_ids_hash = (
            "sha256:" + hashlib.sha256(json.dumps(sorted(values)).encode()).hexdigest()
        )
    return hashes


def evaluated(*, mismatch: str | None = None, kind: str = "agent_eval") -> Any:
    """Build two evidence-complete groups, optionally remove one comparability condition."""
    complete = CostTotals(api_usd=1, total_usd=1, gpu_pricing_complete=True)
    runs = [member("a", cost=complete), member("b", cost=complete)]
    scores = {"a": [score("acc", 0.5)], "b": [score("acc", 1.0)]}
    per = {
        "a": {f"e{i}": {"correct": i < 2} for i in range(4)},
        "b": {f"e{i}": {"correct": True} for i in range(4)},
    }
    if mismatch == "ids":
        per["b"] = {f"other{i}": {"correct": True} for i in range(4)}
    elif mismatch == "dataset":
        runs[1].datasets[0].hash = "sha256:different"
    elif mismatch == "source":
        scores["b"][0].source_hash = "sha256:other"
    elif mismatch == "no_source":
        scores["b"][0].source_hash = None
    elif mismatch == "partial":
        per["b"].pop("e3")
    elif mismatch == "no_price":
        runs[1].cost = CostTotals(gpu_hours=1, api_usd=1, total_usd=1)
    elif mismatch == "missing_cost":
        runs[1].cost = None
    elif mismatch == "nonbinary":
        per["b"]["e3"]["correct"] = 0.9
    elif mismatch == "mean":
        scores["b"][0].value = 0.9
    hashes = bind_examples(scores, per)
    return build_leaderboard(
        "toy", "t", config(kind), runs, scores, per_example=per, per_example_hashes=hashes
    )


def test_agent_cost_headline_uses_actual_comparable_solved_denominator() -> None:
    board = evaluated()
    assert "50% lower $/solved" in board.headline
    pop = board.rows[0].evaluation_population
    assert (pop.examples, pop.attempts, pop.solved) == (4, 4, 4)
    assert pop.example_ids_hash == board.rows[1].evaluation_population.example_ids_hash
    assert pop.dataset_fingerprint == board.rows[1].evaluation_population.dataset_fingerprint
    assert pop.source_hash == "sha256:scorer" and pop.version == "v1"


@pytest.mark.parametrize(
    "mismatch",
    [
        "ids",
        "dataset",
        "source",
        "no_source",
        "partial",
        "no_price",
        "missing_cost",
        "nonbinary",
        "mean",
    ],
)
def test_agent_cost_headline_refuses_incomparable_or_incomplete_evidence(mismatch: str) -> None:
    assert "$/solved" not in evaluated(mismatch=mismatch).headline


def test_generic_headline_never_acquires_agent_cost_claim() -> None:
    assert "$/solved" not in evaluated(kind="generic").headline


def test_curves_and_grid_expose_recorded_member_identity_and_authoritative_best(
    ctx: Context, toy_repo: Path
) -> None:
    a, b = indexed(ctx, toy_repo)
    for rec in [a, b]:
        rec.params = {"batch": "8", "model": rec.run_id}
        ctx.store.write_record(rec)
        ctx.index.upsert_run(rec)
    curves = query_panel(ctx, "toy", "t", PanelSpec(type="curves", title="Training"))
    groups = {g["run_ids"][0]: g for g in curves.meta["groups"]}
    assert groups["a"]["params"] == {"batch": "8", "model": "a"}
    assert curves.meta["best_group_id"] == groups["a"]["group_id"]
    grid = query_panel(ctx, "toy", "t", PanelSpec(type="grid", title="Examples"))
    assert {r for group in grid.meta["groups"] for r in group["run_ids"]} == {"a", "b"}


def test_raw_samples_table_filter_keeps_selected_run_and_total(
    ctx: Context, toy_repo: Path
) -> None:
    records = indexed(ctx, toy_repo)
    for rec, values in zip(records, [[11.0, 12.0], [91.0, 92.0, 93.0]], strict=True):
        folder = ctx.run_dir(rec) / "samples"
        folder.mkdir(exist_ok=True)
        (folder / "latency_ms.jsonl").write_text(
            "".join(json.dumps({"value": v}) + "\n" for v in values)
        )
    result = query_panel(
        ctx,
        "toy",
        "t",
        PanelSpec.model_validate(
            {
                "type": "table",
                "title": "Raw samples",
                "data": {
                    "source": "samples",
                    "fields": ["name", "value"],
                    "filter": {"run_id": "b"},
                },
            }
        ),
    )
    assert [row["value"] for row in result.rows] == [91.0, 92.0, 93.0]
    assert result.meta["total"] == 3


@pytest.mark.parametrize("problem", [None, "source", "dataset", "missing", "unit", "kind"])
def test_repeat_observations_keep_exact_selected_score_context(problem: str | None) -> None:
    cfg = config("system_bench")
    cfg.tasks["t"].primary = "latency/p95"
    runs = [member("a", config_hash="same"), member("b", config_hash="same")]
    scores = {"a": [score("latency", 10, key="p95")], "b": [score("latency", 12, key="p95")]}
    if problem == "source":
        scores["b"][0].source_hash = "sha256:other"
    elif problem == "dataset":
        runs[1].datasets[0].hash = "sha256:other"
    elif problem == "missing":
        scores["b"] = [score("acc", 1)]
    elif problem == "unit":
        cfg.metrics["latency"].unit = "bytes"
    elif problem == "kind":
        cfg.tasks["t"].kind = "generic"
    row = build_leaderboard("toy", "t", cfg, runs, scores).rows[0]
    if problem:
        assert row.repeat_observations == []
    else:
        assert [(o.run_id, o.value) for o in row.repeat_observations] == [("a", 10), ("b", 12)]
        assert {o.metric for o in row.repeat_observations} == {"latency"}
        assert {o.key for o in row.repeat_observations} == {"p95"}
        assert {o.version for o in row.repeat_observations} == {"v1"}
        assert len({o.dataset_fingerprint for o in row.repeat_observations}) == 1


def test_population_counts_repeated_seed_attempts_in_cost_denominator() -> None:
    complete = CostTotals(api_usd=1, total_usd=1, gpu_pricing_complete=True)
    runs = [
        member("a", cost=complete, config_hash="same"),
        member("b", cost=complete, config_hash="same"),
    ]
    scores = {r.run_id: [score("acc", 0.5)] for r in runs}
    examples = {r.run_id: {"e1": {"correct": True}, "e2": {"correct": False}} for r in runs}
    row = build_leaderboard(
        "toy",
        "t",
        config("agent_eval"),
        runs,
        scores,
        per_example=examples,
        per_example_hashes=bind_examples(scores, examples),
    ).rows[0]
    assert row.n == 1 and row.cost.total_usd == 2
    assert row.evaluation_population.attempts == 4 and row.evaluation_population.solved == 2


def test_explicit_value_key_uses_value_evidence_before_binary_helper_field() -> None:
    runs = [member("a"), member("b")]
    scores = {"a": [score("latency", 100)], "b": [score("latency", 10)]}
    per = {
        r.run_id: {"e1": {"value": value, "correct": True}, "e2": {"value": value, "correct": True}}
        for r, value in zip(runs, [100, 10], strict=True)
    }
    board = build_leaderboard(
        "toy", "t", config(), runs, scores, per_example=per, primary="latency/value"
    )
    assert board.rows[0].test_interval.lo == 10
    assert board.rows[0].test_interval.method == "bootstrap"
    assert board.rows[1].vs_best.test == "paired_bootstrap"


def test_curves_best_group_follows_selected_primary(ctx: Context, toy_repo: Path) -> None:
    indexed(ctx, toy_repo)
    result = query_panel(
        ctx,
        "toy",
        "t",
        PanelSpec.model_validate(
            {"type": "curves", "title": "Latency", "data": {"primary": "latency/p95"}}
        ),
    )
    selected = next(g for g in result.meta["groups"] if g["run_ids"] == ["b"])
    assert result.meta["best_group_id"] == selected["group_id"]


def test_unscored_finished_group_member_prevents_complete_cost_population() -> None:
    cost = CostTotals(api_usd=1, total_usd=1, gpu_pricing_complete=True)
    runs = [member("a", config_hash="same", cost=cost), member("b", config_hash="same", cost=cost)]
    scores = {"a": [score("acc", 1)], "b": []}
    per = {"a": {"e1": {"correct": True}}}
    row = build_leaderboard("toy", "t", config("agent_eval"), runs, scores, per_example=per).rows[0]
    assert row.run_ids == ["a"]  # Preserve the existing scored membership/ranking contract.
    assert not row.cost_complete and row.evaluation_population is None


def test_repeat_observations_are_bounded_without_sampling() -> None:
    cfg = config("system_bench")
    cfg.tasks["t"].primary = "latency/p95"
    runs = [member(str(i), config_hash="same") for i in range(129)]
    scores = {r.run_id: [score("latency", 10, key="p95")] for r in runs}
    assert build_leaderboard("toy", "t", cfg, runs, scores).rows[0].repeat_observations == []


@pytest.mark.parametrize("failed_key", ["value", "*"])
def test_later_failed_evaluation_cannot_reuse_old_success_population(failed_key: str) -> None:
    rec = member("a", cost=CostTotals(total_usd=1, gpu_pricing_complete=True))
    old = score("acc", 1)
    failed = ScoreRecord(
        metric="acc",
        key=failed_key,
        version="v1",
        error="failed",
        created_at=old.created_at + timedelta(seconds=1),
    )
    row = build_leaderboard(
        "toy",
        "t",
        config("agent_eval"),
        [rec],
        {"a": [old, failed]},
        per_example={"a": {"e1": {"correct": True}}},
    ).rows[0]
    assert row.evaluation_population is None


@pytest.mark.parametrize("failed_key", ["p95", "*"])
def test_later_failed_repeat_score_cannot_reuse_old_latency(failed_key: str) -> None:
    cfg = config("system_bench")
    cfg.tasks["t"].primary = "latency/p95"
    old = score("latency", 10, key="p95")
    failed = ScoreRecord(
        metric="latency",
        key=failed_key,
        version="v1",
        error="failed",
        created_at=old.created_at + timedelta(seconds=1),
    )
    row = build_leaderboard("toy", "t", cfg, [member("a")], {"a": [old, failed]}).rows[0]
    assert row.repeat_observations == []


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.RUNNING])
def test_unscored_nonfinished_attempt_invalidates_group_cost_evidence(status: RunStatus) -> None:
    cost = CostTotals(api_usd=1, total_usd=1, gpu_pricing_complete=True)
    runs = [
        member("a", config_hash="same", cost=cost),
        member("b", config_hash="same", cost=cost, status=status),
    ]
    row = build_leaderboard(
        "toy",
        "t",
        config("agent_eval"),
        runs,
        {"a": [score("acc", 1)]},
        per_example={"a": {"e1": {"correct": True}}},
    ).rows[0]
    assert not row.cost_complete and row.evaluation_population is None


def test_repeated_evaluation_without_file_binding_omits_cost_population() -> None:
    rec = member("a", cost=CostTotals(total_usd=1, gpu_pricing_complete=True))
    old = score("acc", 1)
    newer = score("acc", 1, source="sha256:new-scorer")
    row = build_leaderboard(
        "toy",
        "t",
        config("agent_eval"),
        [rec],
        {"a": [old, newer]},
        per_example={"a": {"e1": {"correct": True}}},
    ).rows[0]
    assert row.evaluation_population is None


def test_explicit_percentile_primary_respects_nonlatency_direction() -> None:
    cfg = config("system_bench")
    cfg.tasks["t"].primary = "latency/p95"
    cfg.metrics["acc"].unit = "requests/s"
    runs = [member("a"), member("b")]
    board = build_leaderboard(
        "toy",
        "t",
        cfg,
        runs,
        {"a": [score("acc", 100, key="p95")], "b": [score("acc", 200, key="p95")]},
        primary="acc/p95",
    )
    assert board.higher_is_better is True and board.rows[0].run_ids == ["b"]


def test_real_evaluation_binding_survives_reevaluation_and_rejects_stale_partial_files(
    ctx: Context, toy_repo: Path
) -> None:
    from hypothex.core.evaluation import evaluate_run
    from hypothex.core.queries import get_leaderboard
    from tests.factories import PREDS_075, seed_finished_run

    raw = yaml.safe_load((toy_repo / "hypothex.yaml").read_text())
    raw["tasks"]["toy-acc"]["kind"] = "agent_eval"
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(raw))
    seed_finished_run(ctx, toy_repo, "bound", predictions=PREDS_075)
    rec = ctx.find_record("bound")
    rec.cost = CostTotals(api_usd=1, total_usd=1, gpu_pricing_complete=True)
    rec.datasets = [
        DatasetRef(
            name="toyset",
            version="v1",
            split="test",
            path="data/test.jsonl",
            hash="sha256:"
            + hashlib.sha256((toy_repo / "data/test.jsonl").read_bytes()).hexdigest(),
            hash_mode="full",
        )
    ]
    ctx.store.write_record(rec)
    ctx.index.upsert_run(rec)
    first, _ = evaluate_run(ctx, "bound")
    second, _ = evaluate_run(ctx, "bound")
    assert second[0].per_example_hash == first[0].per_example_hash
    assert ctx.store.read_scores("toy", "bound")[-1] == second[0]
    assert ctx.index.scores_for(["bound"])["bound"][-1] == second[0]
    board = get_leaderboard(ctx, "toy-acc", "toy")
    assert board.rows[0].evaluation_population.attempts == 4
    assert any(item["label"] == "$ / attempt" for item in board.stat_strip)

    # A new worker call that emits only a scalar leaves the old file on disk,
    # but must not bind it to this new score.
    (toy_repo / "toymetrics.py").write_text("def accuracy(examples):\n    return 0.75\n")
    aggregate, _ = evaluate_run(ctx, "bound")
    assert aggregate[0].per_example_hash is None
    assert get_leaderboard(ctx, "toy-acc", "toy").rows[0].evaluation_population is None

    # Even a correct mean plus a per-example subset cannot claim full attempts.
    (toy_repo / "toymetrics.py").write_text(
        "from hypothex.metrics import MetricResult\n"
        "def accuracy(examples):\n"
        "    return MetricResult(values={'value': 1.0}, "
        "per_example={examples[0].id: {'correct': True}})\n"
    )
    partial, _ = evaluate_run(ctx, "bound")
    assert partial[0].per_example_hash is None
    assert get_leaderboard(ctx, "toy-acc", "toy").rows[0].evaluation_population is None


def test_bound_population_rejects_artifact_hash_and_population_identity_mismatch() -> None:
    examples = {"a": {"e1": {"correct": True}}}
    scores = {"a": [score("acc", 1)]}
    hashes = bind_examples(scores, examples)
    rec = member("a", cost=CostTotals(total_usd=1, gpu_pricing_complete=True))
    for update in (
        {"per_example_hash": "sha256:stale"},
        {"evaluation_examples": 2},
        {"evaluation_ids_hash": "sha256:other"},
    ):
        original = scores["a"][0]
        scores["a"] = [original.model_copy(update=update)]
        row = build_leaderboard(
            "toy",
            "t",
            config("agent_eval"),
            [rec],
            scores,
            per_example=examples,
            per_example_hashes=hashes,
        ).rows[0]
        assert row.evaluation_population is None
        scores["a"] = [original]


def test_explicit_configured_primary_preserves_default_direction() -> None:
    cfg = config("system_bench")
    cfg.tasks["t"].primary = "latency/p95"
    cfg.metrics["latency"].higher_is_better = True  # Existing percentile default convention.
    runs = [member("a"), member("b")]
    scores = {"a": [score("latency", 100, key="p95")], "b": [score("latency", 10, key="p95")]}
    original = build_leaderboard("toy", "t", cfg, runs, scores)
    selected = build_leaderboard("toy", "t", cfg, runs, scores, primary="latency/p95")
    assert selected.higher_is_better == original.higher_is_better is False
    assert selected.rows[0].run_ids == original.rows[0].run_ids == ["b"]
