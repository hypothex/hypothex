import pytest

from hypothex.core.headlines import (
    fmt_delta,
    fmt_p,
    fmt_pct,
    fmt_value,
    percentile_of,
    welch_interval,
)


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
