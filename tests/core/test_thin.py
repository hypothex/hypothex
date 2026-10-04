import random

import pytest

from hypothex.core.records import MetricPoint
from hypothex.core.thin import (
    MAX_METRIC_NAMES,
    MAX_POINTS_PER_METRIC,
    HistoryThinner,
    thin_history,
)


def _pt(step: int, value: float, name: str = "loss") -> MetricPoint:
    return MetricPoint(name=name, step=step, value=value)


def test_thin_history_keeps_short_series_whole_ordered_by_name_then_step() -> None:
    points = [_pt(2, 1.0), _pt(0, 3.0, "acc"), _pt(1, 2.0)]
    assert [(p.name, p.step) for p in thin_history(points)] == [
        ("acc", 0),
        ("loss", 1),
        ("loss", 2),
    ]


def test_thinner_keeps_first_last_and_extremes_of_a_shuffled_long_series() -> None:
    n = 20 * MAX_POINTS_PER_METRIC
    values = [math_wave(s) for s in range(n)]
    values[7_777] = 100.0  # peak
    values[13_131] = -100.0  # trough
    points = [_pt(s, v) for s, v in enumerate(values)]
    random.Random(0).shuffle(points)  # file order is not step order
    thinner = HistoryThinner()
    for p in points:
        thinner.add(p)
        assert thinner.held() <= 2 * MAX_POINTS_PER_METRIC
    kept = thinner.points()
    steps = [p.step for p in kept]
    assert len(kept) == MAX_POINTS_PER_METRIC
    assert steps == sorted(steps)
    assert {0, 7_777, 13_131, n - 1} <= set(steps)


def math_wave(step: int) -> float:
    return float((step * 37) % 101) / 101.0


def test_thinner_bounds_each_name_on_its_own() -> None:
    thinner = HistoryThinner(limit=10)
    for s in range(1000):
        thinner.add(_pt(s, float(s % 7), "a"))
        if s < 5:
            thinner.add(_pt(s, 1.0, "b"))
        assert thinner.held() <= 2 * thinner.limit
    kept = thinner.points()
    assert [p.name for p in kept].count("a") == 10
    assert [p.step for p in kept if p.name == "b"] == [0, 1, 2, 3, 4]


def test_thinner_rejects_a_limit_too_small_for_ends_and_extremes() -> None:
    with pytest.raises(ValueError, match="at least 5"):
        HistoryThinner(limit=4)


@pytest.mark.parametrize("seed", range(40))
def test_thinner_never_keeps_more_than_limit_points_of_a_name(seed: int) -> None:
    rng = random.Random(seed)
    n, limit = rng.randint(6, 400), rng.randint(5, 40)
    points = [
        _pt(s, rng.choice([rng.random(), rng.random() * 1e3, -rng.random() * 1e3]))
        for s in range(n)
    ]
    rng.shuffle(points)
    kept = thin_history(points, limit)
    assert len(kept) <= limit
    lo, hi = min(points, key=lambda p: p.value), max(points, key=lambda p: p.value)
    assert {0, n - 1, lo.step, hi.step} <= {p.step for p in kept}


def test_thinner_keeps_the_first_max_metric_names_and_counts_the_rest() -> None:
    thinner = HistoryThinner()
    for i in range(MAX_METRIC_NAMES + 50):
        thinner.add(_pt(0, 1.0, f"m{i:04d}"))
    thinner.add(_pt(1, 2.0, "m0000"))  # a kept name goes on being read
    thinner.add(_pt(1, 2.0, f"m{MAX_METRIC_NAMES + 5:04d}"))  # a dropped one does not
    kept = thinner.points()
    assert {p.name for p in kept} == {f"m{i:04d}" for i in range(MAX_METRIC_NAMES)}
    assert [p.step for p in kept if p.name == "m0000"] == [0, 1]
    assert thinner.dropped_rows == 51
    assert thinner.held() <= 2 * MAX_POINTS_PER_METRIC


def test_thinner_rejects_a_nonpositive_metric_name_limit() -> None:
    with pytest.raises(ValueError, match="max_names must be at least 1"):
        HistoryThinner(max_names=0)
