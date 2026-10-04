"""Tests for hypothex.core.stats.

Reference values marked "scipy" were computed with scipy 1.18.1 (``scipy.stats``):
``binomtest(k, n, 0.5).pvalue``, ``2 * t.sf(|t|, df)``, ``beta.cdf(x, a, b)``,
and ``ttest_ind(a, b, equal_var=False).pvalue``. Values marked "statsmodels"
come from statsmodels 0.15 ``proportion_confint(method="wilson")``.
Values marked "numpy" come from numpy 2.5 ``numpy.quantile`` (default ``"linear"``).
"""

import math
import random

import pytest

from hypothex.core import stats
from hypothex.core.stats import (
    Z95,
    _regularized_beta,
    _t_two_sided_p,
    binom_two_sided_p,
    bootstrap_mean_interval,
    ecdf_points,
    examples_needed,
    paired_bootstrap_p,
    quantile,
    sign_test,
    welch_p,
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


def _choices_interval(xs: list[float]) -> tuple[float, float]:
    """The bootstrap interval as a plain ``rng.choices`` loop (the reference)."""
    rng = random.Random(0)
    means = [sum(rng.choices(xs, k=len(xs))) / len(xs) for _ in range(1000)]
    return quantile(means, 0.025), quantile(means, 0.975)


def _choices_p(diffs: list[float]) -> float:
    """The paired bootstrap p-value as a plain ``rng.choices`` loop (the reference)."""
    rng = random.Random(0)
    sums = [sum(rng.choices(diffs, k=len(diffs))) for _ in range(1000)]
    below = sum(s / len(diffs) <= 0.0 for s in sums)
    above = sum(s / len(diffs) >= 0.0 for s in sums)
    return min(1.0, 2.0 * (min(below, above) + 1) / 1001)


@pytest.mark.parametrize("cache_max", [stats.RESAMPLE_CACHE_MAX, 0])
@pytest.mark.parametrize("n", [1, 2, 7, 500])
def test_bootstraps_equal_a_choices_loop_bit_for_bit(
    n: int, cache_max: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stats, "RESAMPLE_CACHE_MAX", cache_max)  # 0: never keep positions
    rng = random.Random(n)
    a = [rng.gauss(0.5, 0.3) for _ in range(n)]
    b = [rng.gauss(0.45, 0.3) for _ in range(n)]
    assert bootstrap_mean_interval(a) == _choices_interval(a)
    assert bootstrap_mean_interval(a) == _choices_interval(a)  # kept positions, same result
    assert paired_bootstrap_p(a, b) == _choices_p([x - y for x, y in zip(a, b, strict=True)])


def test_bootstrap_positions_are_drawn_once_per_sample_size() -> None:
    stats._draws.cache_clear()
    rng = random.Random(3)
    for _ in range(5):  # five seed groups over the same 40 examples
        a = [rng.random() for _ in range(40)]
        bootstrap_mean_interval(a)
        paired_bootstrap_p(a, [rng.random() for _ in range(40)])
    info = stats._draws.cache_info()
    assert (info.misses, info.hits) == (1, 9)
    assert info.maxsize == 4  # at most 4 sizes are kept


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


@pytest.mark.parametrize(
    ("a", "b", "x", "expected"),
    [
        (2.0, 3.0, 0.4, 0.5248),  # 6x^2(1-x)^2 + 4x^3(1-x) + x^4 at x = 0.4
        (0.5, 0.5, 0.3, 0.36901011956554536),  # scipy; also (2/pi) * asin(sqrt(0.3))
        (5.0, 0.5, 0.9, 0.3166429150200122),  # scipy
        (1.0, 1.0, 0.3, 0.3),  # uniform CDF
        (3.0, 3.0, 0.5, 0.5),  # symmetry
    ],
)
def test_regularized_beta_known_values(a: float, b: float, x: float, expected: float) -> None:
    assert _regularized_beta(a, b, x) == pytest.approx(expected, rel=1e-12)


def test_regularized_beta_closed_forms_and_bounds() -> None:
    assert _regularized_beta(0.5, 0.5, 0.3) == pytest.approx(
        2 / math.pi * math.asin(math.sqrt(0.3)), rel=1e-12
    )
    assert _regularized_beta(4.0, 1.0, 0.7) == pytest.approx(0.7**4, rel=1e-12)
    assert _regularized_beta(2.0, 2.0, 0.0) == 0.0
    assert _regularized_beta(2.0, 2.0, 1.0) == 1.0


@pytest.mark.parametrize(
    ("t", "df", "expected"),
    [
        (2.228138851986274, 10, 0.05),  # t_{0.975, 10} from standard t tables
        (12.706204736174707, 1, 0.05),  # t_{0.975, 1}
        (2.570581835636314, 5, 0.05),  # t_{0.975, 5}
        (1.0, 1, 0.5),  # Cauchy: 1 - (2/pi) * atan(1)
        (1.0, 2, 1 - 1 / math.sqrt(3)),  # df=2 closed form: 1 - t / sqrt(2 + t^2)
        (3.0, 30, 0.005389964065651945),  # scipy
        (50.0, 3, 1.761715204127197e-05),  # scipy
        (-2.228138851986274, 10, 0.05),  # sign does not matter
        (0.0, 7, 1.0),
    ],
)
def test_t_two_sided_p_known_values(t: float, df: float, expected: float) -> None:
    assert _t_two_sided_p(t, df) == pytest.approx(expected, rel=1e-9)


def test_t_two_sided_p_large_df_matches_normal() -> None:
    assert _t_two_sided_p(Z95, 1e6) == pytest.approx(0.05, abs=1e-6)
    assert _t_two_sided_p(math.inf, 5) == 0.0


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ([1.0, 2.0, 3.0], [4.0, 5.0, 6.0], 0.021311641128756713),  # scipy; t=-3.674, df=4
        ([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0], 0.10753119493062724),  # scipy
        ([0.81, 0.79, 0.80], [0.78, 0.77, 0.795], 0.12299329488698767),  # scipy
        ([1.0, 1.0, 1.0], [2.0, 3.0, 4.0], 0.07417990022744854),  # scipy; one zero variance
        ([0.7, 0.72, 0.71, 0.69], [0.65, 0.66], 0.0046605042659501085),  # scipy; unequal n
    ],
)
def test_welch_p_matches_scipy(a: list[float], b: list[float], expected: float) -> None:
    assert welch_p(a, b) == pytest.approx(expected, rel=1e-9)


def test_welch_p_none_cases_and_nan() -> None:
    assert welch_p([1.0], [2.0, 3.0]) is None
    assert welch_p([1.0, 1.0], [2.0, 2.0]) is None  # both variances zero
    assert welch_p([1.0, 2.0, 3.0, math.nan], [4.0, 5.0, 6.0]) == pytest.approx(
        0.021311641128756713, rel=1e-9
    )
    assert welch_p([1.0, math.nan], [2.0, 3.0]) is None
