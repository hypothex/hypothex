import random
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from hypothex.core import leaderboard, stats
from hypothex.core.config import ProjectConfig
from hypothex.core.context import Context
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import (
    Leaderboard,
    build_leaderboard,
    cached_leaderboard,
    clear_caches,
    distinct_labels,
    group_label,
    pick_field,
    seed_group_labels,
)
from hypothex.core.records import (
    CostTotals,
    GitInfo,
    RunRecord,
    RunStatus,
    ScoreRecord,
    UsageTotals,
)
from hypothex.core.sources import group_labels
from tests.factories import make_record

CFG = ProjectConfig.model_validate(
    {
        "project": "toy",
        "datasets": {"d": {"version": "v1", "path": "x"}},
        "metrics": {
            "acc": {"version": "v2", "fn": "m:acc"},
            "loss": {"version": "v1", "fn": "m:loss", "higher_is_better": False},
        },
        "tasks": {
            "t": {"dataset": "d", "metrics": ["acc"], "primary": "acc"},
            "tl": {"dataset": "d", "metrics": ["loss"], "primary": "loss"},
        },
    }
)
T0 = utcnow()


def run(
    rid: str,
    group: str,
    *,
    task: str = "t",
    status: RunStatus = RunStatus.FINISHED,
    archived: bool = False,
    minute: int = 0,
) -> RunRecord:
    return make_record(
        rid,
        task=task,
        status=status,
        archived=archived,
        config_hash=f"sha256:{group}",
        git=GitInfo(commit="c1"),
        created_at=T0 + timedelta(minutes=minute),
    )


def score(
    metric: str, value: float | None, version: str = "v2", error: str | None = None
) -> ScoreRecord:
    return ScoreRecord(
        metric=metric, version=version, key="value", value=value, error=error, created_at=utcnow()
    )


def test_groups_sorts_and_flags() -> None:
    runs, scores = [], {}
    for i, v in enumerate([0.80, 0.82, 0.81]):
        runs.append(run(f"a{i}", "a", minute=i))
        scores[f"a{i}"] = [score("acc", v)]
    for i, v in enumerate([0.800, 0.805, 0.810]):  # mean 0.805, CI overlaps group a
        runs.append(run(f"b{i}", "b"))
        scores[f"b{i}"] = [score("acc", v)]
    for i, v in enumerate([0.70, 0.71, 0.69]):
        runs.append(run(f"c{i}", "c"))
        scores[f"c{i}"] = [score("acc", v)]
    runs += [
        run("stale", "d"),
        run("none", "e"),
        run("fail", "f", status=RunStatus.FAILED),
        run("arch", "g", archived=True),
    ]
    scores["stale"] = [score("acc", 0.99, version="v1")]
    scores["fail"] = [score("acc", 1.0)]
    scores["arch"] = [score("acc", 1.0)]

    board = build_leaderboard("toy", "t", CFG, runs, scores)

    assert board.metric_versions == {"acc": "v2"} and board.primary == "acc/value"
    assert [r.config_hash for r in board.rows] == ["sha256:a", "sha256:b", "sha256:c"]
    best, second, third = board.rows
    assert best.n == 3 and best.latest_run_id == "a2" and not best.single_seed
    assert best.scores["acc/value"].mean == pytest.approx(0.81)
    assert second.within_noise_of_best is True
    assert third.within_noise_of_best is False
    assert board.needs_reeval == ["stale"]
    assert board.unscored == ["none"]


def test_lower_is_better() -> None:
    runs = [run("x", "x", task="tl"), run("y", "y", task="tl")]
    scores = {"x": [score("loss", 0.2, version="v1")], "y": [score("loss", 0.1, version="v1")]}
    board = build_leaderboard("toy", "tl", CFG, runs, scores)
    assert [r.run_ids for r in board.rows] == [["y"], ["x"]]
    assert board.rows[0].single_seed and board.rows[1].within_noise_of_best is None


def test_leaderboard_ignores_error_scores() -> None:
    runs = [run("ok", "a"), run("err", "b")]
    scores = {"ok": [score("acc", 0.5)], "err": [score("acc", None, error="Traceback...")]}
    board = build_leaderboard("toy", "t", CFG, runs, scores)
    assert [r.run_ids for r in board.rows] == [["ok"]]
    assert board.unscored == ["err"]


def test_version_override_and_latest_score_wins() -> None:
    runs = [run("r", "a")]
    scores = {"r": [score("acc", 0.1, version="v1"), score("acc", 0.3, version="v1")]}
    board = build_leaderboard("toy", "t", CFG, runs, scores, versions={"acc": "v1"})
    assert board.rows[0].scores["acc/value"].mean == 0.3
    assert board.metric_versions == {"acc": "v1"}


# phase 1b: task kinds, labels, seed values, launchers, usage -----------------------------
KINDS = ProjectConfig.model_validate(
    {
        "project": "toy",
        "datasets": {"d": {"version": "v1", "path": "x"}},
        "metrics": {
            "acc": {"version": "v2", "fn": "m:acc"},
            "lat": {"version": "v1", "fn": "m:lat"},
        },
        "tasks": {
            "t": {"dataset": "d", "metrics": ["acc"], "primary": "acc"},
            "ai": {
                "dataset": "d",
                "metrics": ["acc"],
                "primary": "acc",
                "kind": "agent_iteration",
            },
            "sb": {
                "dataset": "d",
                "metrics": ["lat"],
                "primary": "lat/p95",
                "kind": "system_bench",
                "baseline": "tag:baseline",
            },
        },
    }
)


def krun(rid: str, group: str, *, task: str = "t", minute: int = 0, **extra: Any) -> RunRecord:
    return make_record(
        rid,
        task=task,
        status=RunStatus.FINISHED,
        config_hash=f"sha256:{group}",
        git=GitInfo(commit="c1"),
        created_at=T0 + timedelta(minutes=minute),
        **extra,
    )


def acc(value: float) -> list[ScoreRecord]:
    return [score("acc", value)]


def bench_runs() -> tuple[list[RunRecord], dict[str, list[ScoreRecord]]]:
    """Baseline p95 440/430/450 ms (tagged), candidate 300/310/320 ms; 3 repeats each."""
    runs: list[RunRecord] = []
    scores: dict[str, list[ScoreRecord]] = {}
    groups = {"base": ([440, 430, 450], ["baseline"]), "fast": ([300, 310, 320], [])}
    for g, (values, tags) in groups.items():
        for i, v in enumerate(values):
            rid = f"{g}{i}"
            runs.append(krun(rid, g, task="sb", minute=i, hypothesis=g, tags=tags))
            scores[rid] = [
                ScoreRecord(metric="lat", version="v1", key="p95", value=float(v), created_at=T0)
            ]
    return runs, scores


def test_group_label() -> None:
    assert group_label("RBF-kernel SVM should beat RF because x", [], "g") == "RBF-kernel SVM"
    assert group_label("baseline rf", ["x"], "g") == "baseline rf"
    assert group_label("warmup 500, cosine decay", [], "g") == "warmup 500"
    assert group_label("(ablation) no dropout", [], "g") == "ablation"
    assert group_label("", ["svm", "best"], "g") == "best"
    assert group_label("  ", [], "63c2ec5f@8f4cac4") == "group 63c2ec5f@8f4cac4"
    long = "increase the learning rate warmup schedule length for the larger model"
    assert group_label(long, [], "g") == "increase the learning rate…"


def test_rows_carry_seed_values_launchers_usage_and_labels() -> None:
    runs = [
        krun(
            "a0",
            "a",
            hypothesis="svm wins",
            created_by="human",
            usage=UsageTotals(tokens_in=100, usd=0.5, calls=2),
        ),
        krun(
            "a1",
            "a",
            minute=1,
            hypothesis="svm wins",
            created_by="agent:claude",
            usage=UsageTotals(tokens_in=50, tokens_out=7, usd=0.25, seconds=1.5, calls=1),
        ),
        krun("b0", "b", tags=["rf"]),
    ]
    scores = {"a0": acc(0.9), "a1": acc(0.9), "b0": acc(0.7)}
    board = build_leaderboard("toy", "t", KINDS, runs, scores)
    a, b = board.rows
    assert board.kind == "generic"
    assert a.label == "svm wins" and b.label == "rf"
    assert a.seed_values == {"acc/value": [0.9, 0.9]} and a.identical_seeds
    assert not b.identical_seeds  # n = 1 is never "identical"
    assert a.created_by == ["agent:claude", "human"]
    assert a.usage == UsageTotals(tokens_in=150, tokens_out=7, usd=0.75, seconds=1.5, calls=3)
    assert b.usage is None
    assert a.test_interval is None and a.vs_best is None


def test_label_skips_an_empty_latest_hypothesis_like_group_labels() -> None:
    runs = [
        krun("a0", "a", hypothesis="svm, rbf kernel"),
        krun("a1", "a", minute=1, hypothesis=""),  # latest run: empty hypothesis
        krun("b0", "b", tags=["rf"]),
        krun("b1", "b", minute=1, hypothesis="  "),
        krun("c0", "c"),
    ]
    scores = {"a0": acc(0.9), "a1": acc(0.9), "b0": acc(0.8), "b1": acc(0.8), "c0": acc(0.1)}
    board = build_leaderboard("toy", "t", KINDS, runs, scores)
    labels = {r.group_id: r.label for r in board.rows}
    assert list(labels.values()) == ["svm", "rf", "group c@c1"]
    assert group_labels(runs) == labels  # one rule for the board and the sources


def test_system_bench_percentile_is_lower_is_better() -> None:
    runs, scores = bench_runs()
    board = build_leaderboard("toy", "sb", KINDS, runs, scores)
    assert board.kind == "system_bench" and board.higher_is_better is False
    assert board.primary == "lat/p95"
    assert [r.label for r in board.rows] == ["fast", "base"]
    assert board.rows[0].seed_values == {"lat/p95": [300.0, 310.0, 320.0]}


def test_agent_iteration_labels_are_versions() -> None:
    runs = [
        krun("v9", "v9", task="ai", params={"version": "v9"}, hypothesis="add retry"),
        krun("v10", "v10", task="ai", params={"version": "v10"}, hypothesis="add cache"),
        krun("n", "n", task="ai", hypothesis="no version param"),
    ]
    scores = {"v9": acc(0.4), "v10": acc(0.5), "n": acc(0.3)}
    board = build_leaderboard("toy", "ai", KINDS, runs, scores)
    assert [r.label for r in board.rows] == ["v10", "v9", "no version param"]


def test_nan_score_is_ignored_like_an_error() -> None:
    # a metric that divides by zero returns NaN; it must not rank, lead, or reach JSON
    runs = [krun("a0", "a", hypothesis="nan run"), krun("b0", "b", hypothesis="ok run")]
    scores = {"a0": acc(float("nan")), "b0": acc(0.5)}
    board = build_leaderboard("toy", "t", KINDS, runs, scores)
    assert [r.label for r in board.rows] == ["ok run"]
    assert board.unscored == ["a0"]
    assert "nan" not in board.model_dump_json().lower()


# phase 1b: test-set noise and paired tests ---------------------------------------------
def binary(n: int, right: set[int]) -> dict[str, dict[str, Any]]:
    return {f"e{i}": {"correct": i in right} for i in range(n)}


def test_pick_field() -> None:
    assert pick_field([{"correct": True, "loss": 0.2}]) == ("correct", True)
    assert pick_field([{"solved": 1}, {"solved": 0}]) == ("solved", True)
    assert pick_field([{"hit": 1}, {"hit": 0}]) == ("hit", False)
    assert pick_field([{"ok": False, "f1": 0.5}]) == ("ok", True)
    assert pick_field([{"a": 0.1, "f1": 0.5}], key="f1") == ("f1", False)
    assert pick_field([{"a": 0.1, "f1": None}], key="f1") == ("a", False)
    assert pick_field([{"note": "x"}]) is None
    assert pick_field([]) is None


def test_binary_examples_give_wilson_interval_and_sign_test() -> None:
    runs = [krun("a0", "a", hypothesis="svm"), krun("b0", "b", hypothesis="rf")]
    scores = {"a0": acc(0.8), "b0": acc(0.4)}
    per_example = {"a0": binary(10, set(range(8))), "b0": binary(10, {0, 1, 2, 8})}
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    best, other = board.rows
    # Reference: statsmodels proportion_confint(8, 10, method="wilson")
    ti = best.test_interval
    assert ti is not None and (ti.method, ti.n) == ("wilson", 10)
    assert ti.lo == pytest.approx(0.49016247153664183)
    assert ti.hi == pytest.approx(0.9433178485456247)
    # Reference: statsmodels proportion_confint(4, 10, method="wilson")
    assert other.test_interval is not None
    assert other.test_interval.lo == pytest.approx(0.16818032970623614)
    assert other.test_interval.hi == pytest.approx(0.6873262302663417)
    assert best.vs_best is None
    vs = other.vs_best
    assert vs is not None and vs.test == "sign"
    assert vs.delta == pytest.approx(-0.4)
    assert (vs.fixed, vs.broken) == (5, 1)  # e3..e7 only svm; e8 only rf
    assert vs.p == pytest.approx(0.21875)  # scipy.stats.binomtest(1, 6).pvalue = 14/64
    assert vs.examples_needed == stats.examples_needed(5, 1, 10)
    assert vs.examples_needed is not None


def test_seeds_pooled_per_example_by_majority() -> None:
    runs = [krun(f"a{i}", "a", minute=i) for i in range(3)] + [krun("b0", "b")]
    scores = {"a0": acc(0.5), "a1": acc(0.5), "a2": acc(0.5), "b0": acc(0.25)}
    per_example = {
        "a0": binary(4, {0, 1}),
        "a1": binary(4, {0, 2}),
        "a2": binary(4, {0, 1}),
        "b0": binary(4, {2}),
    }
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    best, other = board.rows
    assert best.identical_seeds and best.seed_values == {"acc/value": [0.5, 0.5, 0.5]}
    # pooled per example: 1, 2/3, 1/3, 0 -> 2 of 4; statsmodels wilson(2, 4)
    assert best.test_interval is not None and best.test_interval.n == 4
    assert best.test_interval.lo == pytest.approx(0.15003898915214947)
    assert best.test_interval.hi == pytest.approx(0.8499610108478506)
    vs = other.vs_best
    assert vs is not None and (vs.fixed, vs.broken) == (2, 1)  # majority: a passes e0, e1
    assert vs.p == pytest.approx(1.0)  # scipy.stats.binomtest(1, 3).pvalue


def test_continuous_examples_use_bootstrap() -> None:
    runs = [krun("a0", "a"), krun("b0", "b")]
    scores = {"a0": acc(0.75), "b0": acc(0.5)}
    a_vals, b_vals = [0.9, 0.8, 0.7, 0.6], [0.5, 0.6, 0.4, 0.5]
    per_example = {
        "a0": {f"e{i}": {"score": v} for i, v in enumerate(a_vals)},
        "b0": {f"e{i}": {"score": v} for i, v in enumerate(b_vals)},
    }
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    best, other = board.rows
    ti = best.test_interval
    assert ti is not None and ti.method == "bootstrap" and ti.n == 4
    assert (ti.lo, ti.hi) == stats.bootstrap_mean_interval(a_vals)
    assert 0.6 <= ti.lo <= 0.75 <= ti.hi <= 0.9
    vs = other.vs_best
    assert vs is not None and vs.test == "paired_bootstrap"
    assert vs.p == stats.paired_bootstrap_p(b_vals, a_vals)
    assert vs.fixed is None and vs.broken is None and vs.examples_needed is None


def test_without_examples_seed_groups_use_welch() -> None:
    runs, scores = [], {}
    for g, values in {"a": [0.80, 0.82, 0.81], "b": [0.70, 0.71, 0.69], "c": [0.5]}.items():
        for i, v in enumerate(values):
            runs.append(krun(f"{g}{i}", g, minute=i))
            scores[f"{g}{i}"] = acc(v)
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example={})
    _, b, c = board.rows
    assert b.test_interval is None
    assert b.vs_best is not None and b.vs_best.test == "welch"
    # Reference: scipy.stats.ttest_ind(b, a, equal_var=False).pvalue
    assert b.vs_best.p == pytest.approx(0.00017563538261646214, rel=1e-6)
    assert c.vs_best is not None and c.vs_best.test is None and c.vs_best.p is None
    assert c.vs_best.delta == pytest.approx(-0.31)


def test_examples_of_other_runs_are_ignored() -> None:
    runs = [krun("a0", "a"), krun("x", "x", archived=True)]
    # rows of an archived run and of an unknown run would make "correct" non-binary
    per_example = {
        "a0": binary(2, {0}),
        "x": {"e0": {"correct": 0.5}},
        "ghost": {"e1": {"correct": 0.5}},
    }
    board = build_leaderboard("toy", "t", KINDS, runs, {"a0": acc(0.5)}, per_example=per_example)
    ti = board.rows[0].test_interval
    assert ti is not None and (ti.method, ti.n) == ("wilson", 2)


def test_paired_test_uses_only_shared_examples() -> None:
    # b0 was scored on the first 5 examples only (the test split grew between runs)
    runs = [krun("a0", "a", hypothesis="svm"), krun("b0", "b", hypothesis="rf")]
    scores = {"a0": acc(0.8), "b0": acc(0.4)}
    per_example = {"a0": binary(10, set(range(8))), "b0": binary(5, {0, 1})}
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    best, other = board.rows
    assert best.test_interval is not None and best.test_interval.n == 10
    assert other.test_interval is not None and other.test_interval.n == 5
    vs = other.vs_best
    assert vs is not None and vs.test == "sign"
    assert (vs.fixed, vs.broken) == (3, 0)  # e2, e3, e4; e5..e9 are not shared
    assert vs.p == pytest.approx(0.25)  # scipy.stats.binomtest(0, 3).pvalue = 2 / 8
    assert vs.examples_needed == stats.examples_needed(3, 0, 5)


# phase 1b: headline, stat strip, baseline, version order ------------------------------
def test_board_headline_and_stat_strip_generic() -> None:
    runs = [krun("a0", "a", hypothesis="svm"), krun("b0", "b", hypothesis="rf")]
    scores = {"a0": acc(0.8), "b0": acc(0.4)}
    per_example = {"a0": binary(10, set(range(8))), "b0": binary(10, {0, 1, 2, 8})}
    board = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    assert board.headline == "svm +0.400 over rf, p = 0.22"
    assert [s["label"] for s in board.stat_strip] == [
        "Δ acc",
        "paired p",
        "fixed / broken",
        "svm 95% CI",
        "seed σ",
        "n for p < 0.05",
    ]
    assert [s["value"] for s in board.stat_strip][:5] == [
        "+0.400",
        "0.22",
        "5 / 1",
        "0.490–0.943",
        "—",
    ]
    assert build_leaderboard("toy", "t", KINDS, [], {}).headline == "No scored runs yet"


def test_system_bench_headline_vs_baseline() -> None:
    runs, scores = bench_runs()
    board = build_leaderboard("toy", "sb", KINDS, runs, scores)
    # exp(mean log fast - mean log base) - 1 = -29.6 %; Welch CI on log values [-34, -24] %
    # (same numbers as tests/core/test_headlines.py::test_welch_interval)
    assert board.headline == "fast p95 −30% vs baseline [−34, −24]"
    assert [s["label"] for s in board.stat_strip] == ["p95", "Δ p95", "repeats", "repeat σ"]
    by_id = KINDS.model_copy(deep=True)
    by_id.tasks["sb"].baseline = board.rows[1].group_id
    assert build_leaderboard("toy", "sb", by_id, runs, scores).headline == board.headline
    by_id.tasks["sb"].baseline = "tag:nothing"
    assert build_leaderboard("toy", "sb", by_id, runs, scores).headline == "fast p95 310"


def test_agent_iteration_orders_versions_naturally() -> None:
    right = {"v9": set(range(4)), "v10": set(range(5)), "v11": set(range(7))}
    runs = [krun(v, v, task="ai", params={"version": v}, hypothesis=f"try {v}") for v in right]
    scores = {v: acc(len(r) / 10) for v, r in right.items()}
    per_example = {v: binary(10, r) for v, r in right.items()}
    board = build_leaderboard("toy", "ai", KINDS, runs, scores, per_example=per_example)
    assert [r.label for r in board.rows] == ["v11", "v10", "v9"]
    # first version is v9 (natural order), not v10 (string order); CI from 3 fixed, 0 broken
    assert board.headline == "v11 0.700, +0.300 over v9 [0.016, 0.584]"
    assert board.stat_strip[0] == {
        "label": "fixed / broken vs v9",
        "value": "3 / 0",
        "unit": "",
        "tooltip": "Examples v9 missed and v11 solved, and the reverse",
    }


def test_agent_iteration_gain_interval_counts_only_shared_examples() -> None:
    # 100 examples per version, only s0..s9 shared; v2 solves s0..s5, v1 none of them
    v1 = {f"a{i}": {"correct": i < 20} for i in range(90)}
    v1 |= {f"s{i}": {"correct": False} for i in range(10)}
    v2 = {f"b{i}": {"correct": i < 74} for i in range(90)}
    v2 |= {f"s{i}": {"correct": i < 6} for i in range(10)}
    runs = [
        krun(v, v, task="ai", params={"version": v}, minute=i) for i, v in enumerate(["v1", "v2"])
    ]
    scores = {"v1": acc(0.2), "v2": acc(0.8)}
    board = build_leaderboard("toy", "ai", KINDS, runs, scores, per_example={"v1": v1, "v2": v2})
    vs = board.rows[1].vs_best
    assert vs is not None and (vs.fixed, vs.broken) == (6, 0)
    # 0.6 +/- 1.959964 * sqrt((0.6 - 0.36) / 10) = [0.296, 0.904];
    # min(group n) = 100 would give [0.553, 0.647]
    assert board.headline == "v2 0.800, +0.600 over v1 [0.296, 0.904]"


def test_agent_iteration_without_version_uses_creation_time() -> None:
    runs = [
        krun("y", "y", task="ai", minute=5, hypothesis="second try"),
        krun("x", "x", task="ai", minute=0, hypothesis="first try"),
    ]
    board = build_leaderboard("toy", "ai", KINDS, runs, {"x": acc(0.4), "y": acc(0.6)})
    assert board.headline == "second try 0.600, +0.200 over first try"


def test_board_carries_unit_value_format_and_relative_deltas() -> None:
    runs, scores = bench_runs()
    # "lat" names no unit: a number outside [0, 1], deltas absolute
    board = build_leaderboard("toy", "sb", KINDS, runs, scores)
    assert (board.unit, board.value_format) == ("", "number")
    base = board.rows[1]
    assert base.vs_best is not None
    assert base.vs_best.delta == pytest.approx(130.0)
    assert base.vs_best.delta_rel == pytest.approx(130.0 / 310.0)
    assert board.rows[0].vs_best is None
    # a configured ms unit on a lower-is-better time: relative vs-best deltas, units in text
    timed = KINDS.model_copy(deep=True)
    timed.metrics["lat"].unit = "ms"
    board = build_leaderboard("toy", "sb", timed, runs, scores)
    assert (board.unit, board.value_format) == ("ms", "percent_delta")
    assert board.stat_strip[0] == {
        "label": "p95",
        "value": "310 vs 440",
        "unit": "ms",
        "tooltip": "fast vs baseline base, mean of repeats",
    }
    timed.tasks["sb"].baseline = None
    assert build_leaderboard("toy", "sb", timed, runs, scores).headline == "fast p95 310 ms"
    # fractions stay fractions
    runs = [krun("a", "aaaa"), krun("b", "bbbb", minute=1)]
    board = build_leaderboard("toy", "t", KINDS, runs, {"a": acc(0.9), "b": acc(0.6)})
    assert (board.unit, board.value_format) == ("", "fraction")


def test_rows_sum_the_cost_of_their_runs() -> None:
    def costed(rid: str, group: str, minute: int, cost: CostTotals | None) -> RunRecord:
        return make_record(
            rid,
            task="t",
            status=RunStatus.FINISHED,
            config_hash=f"sha256:{group}",
            git=GitInfo(commit="c1"),
            created_at=T0 + timedelta(minutes=minute),
            cost=cost,
        )

    runs = [
        costed("c0", "c", 0, CostTotals(gpu_hours=1.0, gpu_usd=2.0, total_usd=2.0)),
        costed("c1", "c", 1, CostTotals(gpu_hours=0.5, gpu_usd=1.0, api_usd=0.25, total_usd=1.25)),
        costed("d0", "d", 2, None),
    ]
    scores = {"c0": [score("acc", 0.9)], "c1": [score("acc", 0.8)], "d0": [score("acc", 0.5)]}
    best, other = build_leaderboard("toy", "t", CFG, runs, scores).rows
    assert best.cost == CostTotals(gpu_hours=1.5, gpu_usd=3.0, api_usd=0.25, total_usd=3.25)
    assert other.cost is None


def float_board_inputs(
    groups: int = 4, examples: int = 30
) -> tuple[list[RunRecord], dict[str, list[ScoreRecord]], dict[str, dict[str, dict[str, Any]]]]:
    """``groups`` seed groups of 2 runs with float per-example scores."""
    rng = random.Random(7)
    runs: list[RunRecord] = []
    scores: dict[str, list[ScoreRecord]] = {}
    per_example: dict[str, dict[str, dict[str, Any]]] = {}
    for g in range(groups):
        for s in range(2):
            rid = f"g{g}s{s}"
            runs.append(krun(rid, f"grp{g}", minute=2 * g + s))
            values = [rng.random() * (g + 1) / groups for _ in range(examples)]
            per_example[rid] = {f"e{i}": {"score": v} for i, v in enumerate(values)}
            scores[rid] = acc(sum(values) / examples)
    return runs, scores, per_example


def count_bootstraps(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    interval, paired = stats.bootstrap_mean_interval, stats.paired_bootstrap_p

    def counted_interval(*args: Any, **kwargs: Any) -> tuple[float, float]:
        calls.append("interval")
        return interval(*args, **kwargs)

    def counted_paired(*args: Any, **kwargs: Any) -> float:
        calls.append("paired")
        return paired(*args, **kwargs)

    monkeypatch.setattr(stats, "bootstrap_mean_interval", counted_interval)
    monkeypatch.setattr(stats, "paired_bootstrap_p", counted_paired)
    return calls


def test_a_rebuilt_board_reuses_bootstraps_and_equals_a_cold_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs, scores, per_example = float_board_inputs()
    calls = count_bootstraps(monkeypatch)
    clear_caches()
    cold = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    assert calls.count("interval") == 4 and calls.count("paired") == 3
    calls.clear()
    warm = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    assert calls == []  # every row interval and p-value came from the cache
    assert warm == cold
    # one group's examples change: only its interval and its p-value are recomputed
    per_example["g1s0"] = {k: {"score": v["score"] / 2} for k, v in per_example["g1s0"].items()}
    changed = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    assert sorted(calls) == ["interval", "paired"]
    clear_caches()
    assert build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example) == changed


def test_cached_leaderboard_keeps_a_board_until_the_index_changes(ctx: Context) -> None:
    runs, scores, per_example = float_board_inputs()
    builds: list[int] = []

    def build() -> Leaderboard:
        builds.append(1)
        return build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)

    direct = build_leaderboard("toy", "t", KINDS, runs, scores, per_example=per_example)
    first = cached_leaderboard(ctx, "toy", "t", KINDS, build)
    second = cached_leaderboard(ctx, "toy", "t", KINDS, build)
    assert len(builds) == 1
    assert first == second == direct
    first.rows.clear()  # each call returns its own copy
    assert cached_leaderboard(ctx, "toy", "t", KINDS, build) == direct
    # other versions, variants and configs are other boards
    cached_leaderboard(ctx, "toy", "t", KINDS, build, versions={"acc": "v1"})
    cached_leaderboard(ctx, "toy", "t", KINDS, build, variant="examples=False")
    other = KINDS.model_copy(deep=True)
    other.metrics["acc"].version = "v3"
    cached_leaderboard(ctx, "toy", "t", other, build)
    assert len(builds) == 4
    # an index write moves the generation on: the next call builds again
    ctx.index.upsert_run(krun("late", "grp9"))
    cached_leaderboard(ctx, "toy", "t", KINDS, build)
    assert len(builds) == 5


def test_cached_leaderboard_does_not_share_boards_between_homes(
    ctx: Context, tmp_path: Path
) -> None:
    runs, scores, _ = float_board_inputs()
    board = build_leaderboard("toy", "t", KINDS, runs, scores)
    other_ctx = Context.open(tmp_path / "other-home")
    assert other_ctx.index.generation() == ctx.index.generation()
    cached_leaderboard(ctx, "toy", "t", KINDS, lambda: board)
    empty = board.model_copy(update={"rows": []})
    assert cached_leaderboard(other_ctx, "toy", "t", KINDS, lambda: empty).rows == []


def test_caches_drop_the_least_recently_used_entry() -> None:
    cache: leaderboard._Lru[str, int] = leaderboard._Lru(2)
    computed: list[str] = []

    def value(key: str) -> int:
        return cache.get(key, lambda: computed.append(key) or len(computed))

    assert (value("a"), value("b"), value("a")) == (1, 2, 1)
    value("c")  # evicts b, the least recently used
    assert len(cache) == 2
    value("a")
    value("b")
    assert computed == ["a", "b", "c", "b"]
    assert leaderboard._BOARDS.size == leaderboard.BOARD_CACHE_SIZE
    assert leaderboard._INTERVALS.size == leaderboard._PAIRED_P.size == leaderboard.STATS_CACHE_SIZE


def sweep_runs() -> tuple[list[RunRecord], dict[str, list[ScoreRecord]]]:
    """Four configs of one sweep hypothesis; two share their vars (other commits)."""
    grid = [
        ("a", {"lr": "1e-3", "beam": "10"}, "c1", 0.9),
        ("b", {"lr": "1e-3", "beam": "5"}, "c1", 0.8),
        ("c", {"lr": "1e-4", "beam": "5"}, "c1", 0.7),
        ("d", {"lr": "1e-4", "beam": "5"}, "c2", 0.6),
    ]
    runs, scores = [], {}
    for i, (group, sweep_vars, commit, value) in enumerate(grid):
        runs.append(
            make_record(
                group,
                task="t",
                status=RunStatus.FINISHED,
                config_hash=f"sha256:{group * 8}",
                git=GitInfo(commit=commit),
                created_at=T0 + timedelta(minutes=i),
                hypothesis="lr x beam, a small sweep",
                vars=sweep_vars,
            )
        )
        scores[group] = acc(value)
    return runs, scores


def test_groups_that_share_a_label_get_the_vars_that_differ() -> None:
    runs, scores = sweep_runs()
    runs.append(krun("solo", "solo", minute=9, hypothesis="bigger model", vars={"lr": "1e-3"}))
    scores["solo"] = acc(0.5)
    board = build_leaderboard("toy", "t", KINDS, runs, scores)
    assert [r.label for r in board.rows] == [
        "lr x beam · lr 1e-3, beam 10",
        "lr x beam · lr 1e-3, beam 5",
        "lr x beam · lr 1e-4, beam 5 · cccccccc@c1",  # same vars as d: group id too
        "lr x beam · lr 1e-4, beam 5 · dddddddd@c2",
        "bigger model",  # a label no other group has stays as it is
    ]
    members = {r.group_id: [m for m in runs if m.run_id in r.run_ids] for r in board.rows}
    assert seed_group_labels(members) == {r.group_id: r.label for r in board.rows}
    assert group_labels(runs) == {r.group_id: r.label for r in board.rows}  # views too


def test_distinct_labels_leaves_out_vars_a_group_does_not_have() -> None:
    one = [krun("x", "x", vars={"lr": "1e-3"})]
    two = [krun("y", "y", vars={"lr": "1e-3", "beam": "5"})]
    none = [krun("z", "z")]
    labels = distinct_labels(
        {"x": "same", "y": "same", "z": "same"}, {"x": one, "y": two, "z": none}
    )
    assert labels == {"x": "same · lr 1e-3", "y": "same · lr 1e-3, beam 5", "z": "same"}


def test_group_label_keeps_the_whole_clause_without_a_limit() -> None:
    hypothesis = "40k steps with heavier augmentation lifts top-1, as in the paper"
    assert group_label(hypothesis, [], "g") == "40k steps with heavier…"
    assert group_label(hypothesis, [], "g", limit=None) == (
        "40k steps with heavier augmentation lifts top-1"
    )
