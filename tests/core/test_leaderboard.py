from datetime import timedelta
from typing import Any

import pytest

from hypothex.core.config import ProjectConfig
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import build_leaderboard, group_label
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord, UsageTotals
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
