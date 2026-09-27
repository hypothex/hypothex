"""Tests for hypothex.core.stats.

Reference values marked "scipy" were computed with scipy 1.18.1 (``scipy.stats``):
``binomtest(k, n, 0.5).pvalue``, ``2 * t.sf(|t|, df)``, ``beta.cdf(x, a, b)``,
and ``ttest_ind(a, b, equal_var=False).pvalue``. Values marked "statsmodels"
come from statsmodels 0.15 ``proportion_confint(method="wilson")``.
Values marked "numpy" come from numpy 2.5 ``numpy.quantile`` (default ``"linear"``).
"""

import math

import pytest

from hypothex.core.stats import (
    Z95,
    binom_two_sided_p,
    bootstrap_mean_interval,
    ecdf_points,
    examples_needed,
    paired_bootstrap_p,
    quantile,
    sign_test,
    wilson_interval,
)


@pytest.mark.parametrize(
    ("successes", "n", "lo", "hi"),
    [
        (8, 10, 0.49016247153664183, 0.9433178485456247),  # statsmodels
        (45, 50, 0.7863976856252034, 0.9565242350681095),  # statsmodels
        (0, 10, 0.0, Z95**2 / (10 + Z95**2)),  # closed form for 0 successes
    ],
)
def test_wilson_interval_known_values(successes: int, n: int, lo: float, hi: float) -> None:
    got_lo, got_hi = wilson_interval(successes, n)
    assert got_lo == pytest.approx(lo, abs=1e-12)
    assert got_hi == pytest.approx(hi, abs=1e-12)


def test_wilson_interval_is_symmetric_and_handles_edges() -> None:
    lo, hi = wilson_interval(3, 10)
    mirror_lo, mirror_hi = wilson_interval(7, 10)
    assert lo == pytest.approx(1 - mirror_hi, abs=1e-12)
    assert hi == pytest.approx(1 - mirror_lo, abs=1e-12)
    assert wilson_interval(10, 10)[1] == 1.0
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError, match="successes"):
        wilson_interval(11, 10)
    with pytest.raises(ValueError, match="successes"):
        wilson_interval(-1, 10)


@pytest.mark.parametrize(
    ("k", "n", "expected"),
    [
        (2, 10, 0.109375),  # 2 * (1 + 10 + 45) / 1024
        (8, 10, 0.109375),  # symmetric
        (0, 5, 0.0625),  # 2 / 32
        (1, 6, 0.21875),  # 2 * (1 + 6) / 64
        (5, 10, 1.0),  # the mode: every outcome is as extreme
        (40, 100, 0.05688793364098089),  # scipy
        (450, 1000, 0.0017305360849763033),  # scipy
        (4900, 10000, 0.04658552770494646),  # scipy (log-space path, n > 1000)
    ],
)
def test_binom_two_sided_p_known_values(k: int, n: int, expected: float) -> None:
    assert binom_two_sided_p(k, n) == pytest.approx(expected, rel=1e-9)


def test_binom_two_sided_p_edges() -> None:
    assert binom_two_sided_p(0, 0) == 1.0
    assert binom_two_sided_p(0, 2000) == 0.0  # true value ~1e-602 underflows
    with pytest.raises(ValueError, match="k"):
        binom_two_sided_p(3, 2)


def test_sign_test() -> None:
    assert sign_test(8, 2) == 0.109375
    assert sign_test(2, 8) == 0.109375
    assert sign_test(15, 3) == pytest.approx(0.007537841796875, rel=1e-12)  # scipy
    assert sign_test(0, 0) == 1.0
    assert sign_test(4, 4) == 1.0
    with pytest.raises(ValueError, match="counts"):
        sign_test(-1, 2)


def test_quantile_matches_numpy_linear() -> None:
    assert quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert quantile([4.0, 1.0, 3.0, 2.0], 0.25) == 1.75
    values = [float(i) for i in range(1, 101)]
    assert quantile(values, 0.95) == pytest.approx(95.05)  # numpy
    assert quantile(values, 0.99) == pytest.approx(99.01)  # numpy
    assert quantile(values, 0.0) == 1.0
    assert quantile(values, 1.0) == 100.0
    assert quantile([7.0], 0.3) == 7.0
    assert quantile([1.0, math.nan, 3.0], 0.5) == 2.0


def test_quantile_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="empty"):
        quantile([], 0.5)
    with pytest.raises(ValueError, match="empty"):
        quantile([math.nan], 0.5)
    with pytest.raises(ValueError, match="q must be"):
        quantile([1.0], 1.5)


def test_bootstrap_mean_interval_is_near_normal_theory_and_deterministic() -> None:
    values = [0.0] * 50 + [1.0] * 50
    lo, hi = bootstrap_mean_interval(values)
    # normal theory: 0.5 +- 1.96 * sqrt(0.25 / 100) = [0.402, 0.598]
    assert 0.38 <= lo <= 0.42
    assert 0.58 <= hi <= 0.62
    assert bootstrap_mean_interval(values) == (lo, hi)
    assert bootstrap_mean_interval([0.5, 0.5, 0.5]) == (0.5, 0.5)
    assert bootstrap_mean_interval([2.0]) == (2.0, 2.0)
    assert bootstrap_mean_interval([2.0, math.nan]) == (2.0, 2.0)


def test_bootstrap_mean_interval_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        bootstrap_mean_interval([])
    with pytest.raises(ValueError, match="resamples"):
        bootstrap_mean_interval([1.0], resamples=0)


def test_paired_bootstrap_p() -> None:
    assert paired_bootstrap_p([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0
    # a always beats b: no resample reaches 0, so p = 2 * (0 + 1) / 1001
    assert paired_bootstrap_p([1.0] * 20, [0.0] * 20) == pytest.approx(2 / 1001)
    # mean diff 0.1, sd 1.0, n = 400 -> z = 2, normal-theory two-sided p = 0.0455
    diffs = [1.1, -0.9] * 200
    p = paired_bootstrap_p(diffs, [0.0] * 400)
    assert 0.02 < p < 0.09
    assert paired_bootstrap_p(diffs, [0.0] * 400) == p
    assert paired_bootstrap_p([], []) == 1.0
    assert paired_bootstrap_p([1.0, math.nan], [0.0, 5.0]) == pytest.approx(2 / 1001)


def test_paired_bootstrap_p_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="length"):
        paired_bootstrap_p([1.0, 2.0], [1.0])


def test_examples_needed_matches_linear_scan() -> None:
    # at 100 examples, 6 fixed vs 2 broken gives p = 0.289; scaling the rates up,
    # 209 examples (13 fixed, 4 broken: p = 0.049) is the first n below 0.05
    assert examples_needed(6, 2, 100) == 209
    assert sign_test(13, 4) < 0.05 <= sign_test(12, 4)
    scan = next(n for n in range(1, 5000) if sign_test(round(n * 0.06), round(n * 0.02)) < 0.05)
    assert scan == 209
    assert examples_needed(60, 20, 1000) == 209


def test_examples_needed_none_cases() -> None:
    assert examples_needed(3, 3, 100) is None  # no difference to detect
    assert examples_needed(0, 0, 100) is None
    assert examples_needed(1, 0, 0) is None
    assert examples_needed(501, 499, 1000) is None  # needs more than max_n


def test_examples_needed_is_the_true_minimum_when_p_is_not_monotone() -> None:
    # 96,500 examples at rates 0.051 / 0.049: 4922 fixed vs 4728 broken
    assert examples_needed(51, 49, 1000) == 96500
    assert examples_needed(49, 51, 1000) == 96500  # symmetric in fixed and broken
    assert sign_test(4922, 4728) == pytest.approx(0.049444708448976166, rel=1e-9)  # scipy
    # one example fewer rounds fixed down to 4921: p = 0.0506, not significant
    assert sign_test(4921, 4728) == pytest.approx(0.05062351738864937, rel=1e-9)  # scipy
    # one example more rounds broken up to 4729: p = 0.0506 again. p is not monotone in n,
    # so a binary search can land later (it returned 96,677 here); the scan cannot.
    assert sign_test(4922, 4729) == pytest.approx(0.050647447534179824, rel=1e-9)  # scipy


@pytest.mark.parametrize(
    ("fixed", "broken", "n_total", "expected"),
    [
        (6, 2, 100, 209),
        (2, 6, 100, 209),
        (5, 1, 10, 19),
        (3, 0, 5, 10),
        (9, 3, 180, 251),
        (7, 4, 50, 254),
        (13, 9, 120, 670),
    ],
)
def test_examples_needed_matches_a_full_scan(
    fixed: int, broken: int, n_total: int, expected: int
) -> None:
    fixed_rate, broken_rate = fixed / n_total, broken / n_total
    scan = next(
        n
        for n in range(1, 20_001)
        if sign_test(round(n * fixed_rate), round(n * broken_rate)) < 0.05
    )
    assert scan == expected
    assert examples_needed(fixed, broken, n_total, max_n=20_000) == expected


def test_ecdf_points_small_sample() -> None:
    assert ecdf_points([3.0, 1.0, 2.0, 2.0]) == [(1.0, 0.25), (2.0, 0.75), (3.0, 1.0)]
    assert ecdf_points([]) == []
    assert ecdf_points([1.0, math.nan, 2.0]) == [(1.0, 0.5), (2.0, 1.0)]


def test_ecdf_points_downsamples_and_keeps_max() -> None:
    points = ecdf_points([float(i) for i in range(1000)], max_points=200)
    assert len(points) == 200
    assert points[0] == (4.0, 0.005)
    assert points[1] == (9.0, 0.01)
    assert points[-1] == (999.0, 1.0)
    assert all(a[0] < b[0] and a[1] < b[1] for a, b in zip(points, points[1:], strict=False))
    with pytest.raises(ValueError, match="max_points"):
        ecdf_points([1.0], max_points=0)
