import random

import pytest

from hypothex.core.records import MetricPoint
from hypothex.core.thin import MAX_POINTS_PER_METRIC, HistoryThinner, thin_history


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
    kept = thinner.points()
    assert [p.name for p in kept].count("a") == 10
    assert [p.step for p in kept if p.name == "b"] == [0, 1, 2, 3, 4]


def test_thinner_rejects_a_limit_too_small_for_ends_and_extremes() -> None:
    with pytest.raises(ValueError, match="at least 5"):
        HistoryThinner(limit=4)
