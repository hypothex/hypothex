from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from hypothex.core.config import TaskKind
from hypothex.core.headlines import (
    fmt_delta,
    fmt_metric,
    fmt_metric_delta,
    fmt_p,
    fmt_pct,
    fmt_sig3,
    fmt_value,
    metric_unit,
    overview_headline,
    paired_gain_interval,
    percentile_of,
    task_headline,
    task_stat_strip,
    value_format,
    welch_interval,
)
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import Leaderboard, LeaderboardRow, NoiseInterval, VersusBest
from hypothex.core.records import UsageTotals
from hypothex.core.seeds import Stats, summarize


def row(
    label: str,
    seeds: list[float],
    *,
    vs: VersusBest | None = None,
    ti: NoiseInterval | None = None,
    usage: UsageTotals | None = None,
    extra: dict[str, list[float]] | None = None,
    primary: str = "acc/value",
) -> LeaderboardRow:
    values = {primary: seeds, **(extra or {})}
    return LeaderboardRow(
        group_id=f"{label}@c1",
        run_ids=[f"{label}-{i}" for i in range(len(seeds))],
        latest_run_id=f"{label}-{len(seeds) - 1}",
        hypothesis=label,
        commit="c1",
        config_hash=f"sha256:{label}",
        n=len(seeds),
        scores={k: summarize(v) for k, v in values.items()},
        primary=summarize(seeds),
        single_seed=len(seeds) == 1,
        label=label,
        seed_values=values,
        identical_seeds=len(seeds) > 1 and len(set(seeds)) == 1,
        test_interval=ti,
        vs_best=vs,
        created_by=["human"],
        usage=usage,
    )


def board(
    kind: TaskKind, rows: list[LeaderboardRow], primary: str = "acc/value", higher: bool = True
) -> Leaderboard:
    return Leaderboard(
        project="toy",
        task="toy-test",
        primary=primary,
        higher_is_better=higher,
        metric_versions={primary.split("/")[0]: "v1"},
        rows=rows,
        needs_reeval=[],
        unscored=[],
        headline="",
        kind=kind,
        stat_strip=[],
    )


def sign(delta: float, fixed: int, broken: int, p: float, needed: int | None = None) -> VersusBest:
    return VersusBest(
        delta=delta, p=p, fixed=fixed, broken=broken, test="sign", examples_needed=needed
    )


def welch(delta: float, p: float | None) -> VersusBest:
    return VersusBest(delta=delta, p=p, fixed=None, broken=None, test="welch", examples_needed=None)


# formatting -----------------------------------------------------------------------
def test_fmt_value_and_delta() -> None:
    assert fmt_value(0.03712) == "0.037"
    assert fmt_value(-0.4) == "−0.400"
    assert fmt_value(-0.0001) == "0.000"
    assert fmt_value(3.14159) == "3.14"
    assert fmt_value(12.345) == "12.3"
    assert fmt_value(1234.4) == "1,234"
    assert fmt_delta(0.0371) == "+0.037"
    assert fmt_delta(-0.4) == "−0.400"
    assert fmt_delta(0.0001) == "0.000"


def test_fmt_p_and_pct() -> None:
    assert fmt_p(0.1467) == "p = 0.15"
    assert fmt_p(1.0) == "p = 1.00"
    assert fmt_p(0.0042) == "p = 0.004"
    assert fmt_p(0.0004) == "p < 0.001"
    assert fmt_pct(-0.2956) == "−30%"
    assert fmt_pct(0.041) == "+4%"
    assert fmt_pct(0.004) == "0%"


def test_fmt_sig3() -> None:
    cases = {
        165.6221: "166",
        0.5519: "0.552",
        0.55: "0.55",
        12.345: "12.3",
        45.0: "45",
        1234.4: "1,230",
        999.6: "1,000",
        0.0161: "0.0161",
        -2.8011: "−2.8",
        0.0: "0",
    }
    assert {x: fmt_sig3(x) for x in cases} == cases


def test_metric_unit_and_value_format() -> None:
    assert metric_unit("latency/p95") == "ms"
    assert metric_unit("p95_ms") == "ms"
    assert metric_unit("usage.usd/solved") == "$"
    assert metric_unit("cost_usd") == "$"
    assert metric_unit("usage.tokens_in") == "tokens"
    assert metric_unit("usage.seconds") == "s"
    assert metric_unit("wall_s") == "s"
    for plain in ("top1", "val/loss", "sweep/rps", "errors/rate", "solved"):
        assert metric_unit(plain) == "", plain
    assert metric_unit("top1", "pts") == "pts"  # MetricSpec.unit wins
    assert value_format("ms", [166.0], higher_is_better=False) == "percent_delta"
    assert value_format("ms", [166.0], higher_is_better=True) == "number"
    assert value_format("", [0.2, 1.5], higher_is_better=True) == "number"
    assert value_format("$", [0.5], higher_is_better=False) == "number"
    assert value_format("", [0.0, 0.74, 1.0], higher_is_better=True) == "fraction"


def test_fmt_metric_and_delta() -> None:
    assert fmt_metric(165.62, "ms") == "166 ms"
    assert fmt_metric(165.62, "ms", suffix=False) == "166"
    assert fmt_metric(0.5519, "$") == "$0.55"
    assert fmt_metric(1.3, "$") == "$1.30"
    assert fmt_metric(332.25, "$") == "$332"
    assert fmt_metric(-1.5, "$") == "−$1.50"
    assert fmt_metric(12_300.0, "tokens") == "12,300 tokens"
    assert fmt_metric(0.7417) == "0.742"
    assert fmt_metric(45.04) == "45"  # outside [0, 1]: 3 significant figures
    assert fmt_metric_delta(45.0, 166.0, "ms", "percent_delta") == "+27%"
    assert fmt_metric_delta(-45.0, 166.0, "ms", "number") == "−45 ms"
    assert fmt_metric_delta(-45.0, 166.0, "ms", "number", suffix=False) == "−45"
    assert fmt_metric_delta(0.017, 0.72) == "+0.017"
    assert fmt_metric_delta(0.0, 0.0, "ms", "percent_delta") == "0 ms"


def test_headlines_follow_the_board_format() -> None:
    fast = row("fast", [166.0], primary="lat/value")
    slow = row("slow", [211.0], vs=welch(45.0, 0.09), primary="lat/value")
    b = board("generic", [fast, slow], primary="lat/value", higher=False)
    b.unit, b.value_format = "ms", "percent_delta"
    assert task_headline(b) == "fast −21% over slow, p = 0.09"
    assert overview_headline(Summary(), board=b) == "Idle. fast leads toy-test by 21%, p = 0.09"
    strip = task_stat_strip(b)
    assert (strip[0]["value"], strip[0]["unit"]) == ("−21%", "")
    b.value_format = "number"
    assert task_headline(b) == "fast −45 ms over slow, p = 0.09"
    assert overview_headline(Summary(), board=b) == "Idle. fast leads toy-test by 45 ms, p = 0.09"
    strip = task_stat_strip(b)
    assert (strip[0]["value"], strip[0]["unit"]) == ("−45", "ms")


def test_percentile_of() -> None:
    assert percentile_of("latency/p95") == "p95"
    assert percentile_of("p99_ms/value") == "p99"
    assert percentile_of("lat/p99.9") == "p99.9"
    assert percentile_of("top1/value") is None
    assert percentile_of("p100/value") is None


def test_welch_interval() -> None:
    # Reference: scipy.stats.ttest_ind(a, b, equal_var=False).confidence_interval()
    # = (0.0873304206, 0.1326695794) with df = 4. We use the t table value 2.776
    # (seeds.t_critical) instead of 2.7764451, so the bounds differ by < 1e-5.
    res = welch_interval([0.80, 0.82, 0.81], [0.70, 0.71, 0.69])
    assert res is not None
    d, lo, hi = res
    assert d == pytest.approx(0.11)
    assert lo == pytest.approx(0.0873304206, abs=1e-5)
    assert hi == pytest.approx(0.1326695794, abs=1e-5)
    # Log scale: exp(mean log a - mean log b) - 1; Welch df = 3.59, floored to 3 -> t = 3.182.
    # Hand check: d = -0.3503773, se = 0.0227898, exp(d -/+ 3.182 * se) - 1.
    res = welch_interval([300, 310, 320], [440, 430, 450], log=True)
    assert res is not None
    d, lo, hi = res
    assert d == pytest.approx(-0.2955777038, rel=1e-8)
    assert lo == pytest.approx(-0.3448521777, rel=1e-8)
    assert hi == pytest.approx(-0.2425972361, rel=1e-8)
    assert welch_interval([300], [430], log=True) == (pytest.approx(300 / 430 - 1), None, None)
    assert welch_interval([0.5, 0.5], [0.4, 0.4]) == (
        pytest.approx(0.1),
        pytest.approx(0.1),
        pytest.approx(0.1),
    )
    assert welch_interval([], [0.4]) is None
    assert welch_interval([0.0, 1.0], [1.0, 2.0], log=True) is None


# task headline ----------------------------------------------------------------------
def test_task_headline_generic() -> None:
    svm = row("SVM", [0.922])
    rf = row("rf", [0.885], vs=sign(-0.037, 9, 3, 0.1467))
    assert task_headline(board("generic", [])) == "No scored runs yet"
    assert task_headline(board("generic", [svm])) == "SVM 0.922"
    assert task_headline(board("generic", [svm, rf])) == "SVM +0.037 over rf, p = 0.15"
    rf_no_p = row("rf", [0.885], vs=welch(-0.037, None))
    assert task_headline(board("training", [svm, rf_no_p])) == "SVM +0.037 over rf"


def test_task_headline_lower_is_better() -> None:
    small = row("small", [0.1, 0.1, 0.1])
    big = row("big", [0.2, 0.21, 0.19], vs=welch(0.1, 0.0004))
    text = task_headline(board("training", [small, big], primary="loss/value", higher=False))
    assert text == "small −0.100 over big, p < 0.001"


def test_task_headline_agent_iteration() -> None:
    ti = NoiseInterval(lo=0.0, hi=1.0, method="wilson", n=10)
    best = row("v11", [0.7], ti=ti)
    first = row("v9", [0.4], ti=ti, vs=sign(-0.3, 3, 0, 0.25))
    b = board("agent_iteration", [best, first])
    # paired CI from discordant counts on 10 shared examples:
    # 0.3 +/- 1.959964 * sqrt((0.3 - 0.3**2) / 10)
    paired = paired_gain_interval(0.3, 3, 0, 10)
    text = task_headline(b, reference="v9@c1", gain_interval=paired)
    assert text == "v11 0.700, +0.300 over v9 [0.016, 0.584]"
    # no paired interval given: Welch over seed values, and one seed each gives none
    assert task_headline(b, reference="v9@c1") == "v11 0.700, +0.300 over v9"
    assert task_headline(b) == "v11 0.700"
    assert task_headline(b, reference="v11@c1") == "v11 0.700"
    # no per-example data: Welch interval over seeds (scipy CI 0.0873-0.1327, see above)
    best = row("v2", [0.6, 0.62, 0.61])
    first = row("v1", [0.5, 0.51, 0.49], vs=welch(-0.11, 0.001))
    text = task_headline(board("agent_iteration", [best, first]), reference="v1@c1")
    assert text == "v2 0.610, +0.110 over v1 [0.087, 0.133]"


def test_paired_gain_interval_uses_the_shared_example_count() -> None:
    # 6 fixed, 0 broken on 10 shared examples: 0.6 +/- 1.959964 * sqrt((0.6 - 0.36) / 10)
    assert paired_gain_interval(0.6, 6, 0, 10) == pytest.approx(
        (0.29636368514840156, 0.9036363148515985)
    )
    # the same counts over 100 paired examples: the far narrower interval the old min(n) gave
    assert paired_gain_interval(0.6, 6, 0, 100) == pytest.approx(
        (0.553453434338595, 0.646546565661405)
    )
    assert paired_gain_interval(0.6, 6, 0, 0) is None


def test_task_headline_system_bench() -> None:
    fast = row("batching on", [300, 310, 320], primary="lat/p95")
    base = row("baseline", [440, 430, 450], primary="lat/p95")
    b = board("system_bench", [fast, base], primary="lat/p95", higher=False)
    assert task_headline(b, reference="baseline@c1") == (
        "batching on p95 −30% vs baseline [−34, −24]"
    )
    assert task_headline(b) == "batching on p95 310"
    one = board(
        "system_bench",
        [row("fast", [300], primary="lat/p95"), row("baseline", [430], primary="lat/p95")],
        primary="lat/p95",
        higher=False,
    )
    assert task_headline(one, reference="baseline@c1") == "fast p95 −30% vs baseline"


# stat strip ------------------------------------------------------------------------
def labels(strip: list[dict]) -> list[str]:
    return [s["label"] for s in strip]


def test_stat_strip_generic() -> None:
    ti = NoiseInterval(lo=0.8801, hi=0.9512, method="wilson", n=180)
    svm = row("SVM", [0.922, 0.922, 0.922], ti=ti)
    rf = row("rf", [0.885], vs=sign(-0.037, 9, 3, 0.1461, needed=250))
    strip = task_stat_strip(board("generic", [svm, rf]))
    assert strip == [
        {"label": "Δ acc", "value": "+0.037", "unit": "", "tooltip": "SVM minus rf, mean acc"},
        {
            "label": "paired p",
            "value": "0.15",
            "unit": "",
            "tooltip": "Exact two-sided sign test on 12 changed examples",
        },
        {
            "label": "fixed / broken",
            "value": "9 / 3",
            "unit": "",
            "tooltip": "Examples SVM gets right and rf gets wrong, and the reverse",
        },
        {
            "label": "SVM 95% CI",
            "value": "0.880–0.951",
            "unit": "",
            "tooltip": "Test-set 95% CI (Wilson, n = 180)",
        },
        {
            "label": "seed σ",
            "value": "◇×3",
            "unit": "",
            "tooltip": "SVM: all 3 seeds gave one score",
        },
        {
            "label": "n for p < 0.05",
            "value": "≈250",
            "unit": "",
            "tooltip": "Test examples needed at the same flip rate to reach p < 0.05",
        },
    ]
    assert task_stat_strip(board("generic", [])) == []


def test_stat_strip_training_and_agent_eval() -> None:
    a = row("big lr", [0.80, 0.82, 0.81])
    b = row("small lr", [0.70, 0.71, 0.69], vs=welch(-0.11, 0.00017563538))
    strip = task_stat_strip(board("training", [a, b]))
    assert labels(strip) == ["Δ acc", "p, seeds", "seed σ", "runs"]
    assert strip[1]["value"] == "<0.001" and strip[2]["value"] == "0.0100"
    assert strip[3]["value"] == "6"
    ti = NoiseInterval(lo=0.5, hi=0.7, method="wilson", n=10)
    best = row("opus", [0.6, 0.6, 0.6], ti=ti, usage=UsageTotals(usd=6.0, calls=30))
    strip = task_stat_strip(board("agent_eval", [best]))
    assert labels(strip) == ["opus 95% CI", "seed σ", "$ / attempt"]
    assert strip[2]["value"] == "$0.20"  # $6.00 over 3 seeds x 10 examples


def test_stat_strip_agent_iteration() -> None:
    ti = NoiseInterval(lo=0.0, hi=1.0, method="wilson", n=10)
    best = row("v11", [0.7], ti=ti, usage=UsageTotals(usd=1.4))
    mid = row("v10", [0.5], ti=ti, vs=sign(-0.2, 2, 0, 0.5))
    first = row("v9", [0.4], ti=ti, vs=sign(-0.3, 3, 0, 0.25))
    strip = task_stat_strip(board("agent_iteration", [best, mid, first]), reference="v9@c1")
    assert labels(strip) == ["fixed / broken vs v9", "paired p", "seed σ", "$ / solved", "versions"]
    assert [s["value"] for s in strip] == ["3 / 0", "0.25", "—", "$0.20", "3"]


def test_stat_strip_system_bench() -> None:
    extra_fast = {"lat/p50": [150.0, 150.0, 150.0]}
    extra_base = {"lat/p50": [200.0, 210.0, 205.0]}
    fast = row("batching on", [300, 310, 320], primary="lat/p95", extra=extra_fast)
    base = row("baseline", [440, 430, 450], primary="lat/p95", extra=extra_base)
    b = board("system_bench", [fast, base], primary="lat/p95", higher=False)
    strip = task_stat_strip(b, reference="baseline@c1")
    assert labels(strip) == ["p95", "Δ p50", "Δ p95", "repeats", "repeat σ"]
    # p50: exp(mean log 150 - mean log {200,210,205}) - 1 = -0.2681, Welch df 2 -> t 4.303
    assert [s["value"] for s in strip] == [
        "310 vs 440",
        "−27%",
        "−30%",
        "3",
        "10.0",
    ]
    assert strip[1]["tooltip"] == "p50 change vs baseline, 95% CI −31 to −22%"
    assert labels(task_stat_strip(b)) == ["p95", "repeats", "repeat σ"]


# overview headline ----------------------------------------------------------------
T0 = utcnow()


@dataclass
class Idea:
    project: str
    task: str | None
    label: str
    primary: Stats | None
    created_at: datetime


@dataclass
class Proj:
    project: str
    task: str
    best: float | None


@dataclass
class Summary:
    running: list[object] = field(default_factory=list)
    ideas: list[Idea] = field(default_factory=list)
    projects: list[Proj] = field(default_factory=list)


def test_overview_headline_from_board() -> None:
    svm = row("SVM", [0.922])
    rf = row("rf", [0.885], vs=sign(-0.037, 9, 3, 0.1467))
    b = board("generic", [svm, rf])
    assert overview_headline(Summary(), board=b) == "Idle. SVM leads toy-test by 0.037, p = 0.15"
    busy = Summary(running=[object(), object()])
    assert overview_headline(busy, board=b) == "2 running. SVM leads toy-test by 0.037, p = 0.15"
    assert overview_headline(Summary(), board=board("generic", [svm])) == (
        "Idle. SVM leads toy-test at 0.922"
    )


def test_overview_headline_for_system_bench_uses_the_task_headline() -> None:
    fast = row("async-worker", [166.0, 168.0, 164.0], primary="lat/p95")
    base = row("baseline", [233.0, 231.0, 235.0], vs=welch(67.0, 0.001), primary="lat/p95")
    b = board("system_bench", [fast, base], primary="lat/p95", higher=False)
    b.headline = task_headline(b, reference=base.group_id)
    assert b.headline.startswith("async-worker p95 −29% vs baseline [")
    assert overview_headline(Summary(running=[object()]), board=b) == f"1 running. {b.headline}"


def test_overview_headline_from_summary() -> None:
    assert overview_headline(Summary()) == "Idle. No scored runs yet"
    ideas = [
        Idea("toy", "toy-test", "rf", summarize([0.885]), T0),
        Idea("toy", "toy-test", "SVM", summarize([0.922]), T0 + timedelta(minutes=5)),
        Idea("toy", "toy-test", "knn", summarize([0.867]), T0 + timedelta(minutes=1)),
        Idea("other", "old", "x", summarize([0.1]), T0 - timedelta(days=1)),
    ]
    projects = [Proj("toy", "toy-test", 0.922), Proj("other", "old", 0.5)]
    summary = Summary(running=[object()], ideas=ideas, projects=projects)
    assert overview_headline(summary) == "1 running. SVM leads toy-test by 0.037"
    lone = Summary(ideas=[ideas[1]], projects=projects)
    assert overview_headline(lone) == "Idle. SVM leads toy-test at 0.922"
    moved = Summary(ideas=[ideas[0]], projects=projects)
    assert overview_headline(moved) == "Idle. toy-test best 0.922"
