"""Property tests for ``hypothex.core.stats`` against scipy and numpy oracles."""

import decimal
import math
import sys
from fractions import Fraction

import numpy as np
import pytest
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st
from scipy import stats as sps

from hypothex.core.stats import (
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

FAST = settings(max_examples=60, deadline=None)
# metric-sized values: finite, so sums of a few hundred never overflow
moderate = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)
finite = st.floats(allow_nan=False, allow_infinity=False)
any_float = st.floats(allow_nan=True, allow_infinity=True)


@st.composite
def binom_counts(draw: st.DrawFn, max_n: int = 3000) -> tuple[int, int]:
    n = draw(st.integers(0, max_n))
    return draw(st.integers(0, n)), n


# Wilson --------------------------------------------------------------------------------
@FAST
@given(binom_counts())
def test_wilson_matches_scipy_and_is_bounded(kn: tuple[int, int]) -> None:
    k, n = kn
    lo, hi = wilson_interval(k, n)
    assert 0.0 <= lo <= hi <= 1.0
    if n == 0:
        assert (lo, hi) == (0.0, 1.0)
        return
    assert lo <= k / n <= hi
    ref = sps.binomtest(k, n).proportion_ci(method="wilson")
    assert lo == pytest.approx(ref.low, abs=1e-9)
    assert hi == pytest.approx(ref.high, abs=1e-9)


@FAST
@given(binom_counts())
def test_wilson_is_symmetric_and_monotone_in_successes(kn: tuple[int, int]) -> None:
    k, n = kn
    lo, hi = wilson_interval(k, n)
    mlo, mhi = wilson_interval(n - k, n)
    assert lo == pytest.approx(1.0 - mhi, abs=1e-12)
    assert hi == pytest.approx(1.0 - mlo, abs=1e-12)
    if k < n:
        nlo, nhi = wilson_interval(k + 1, n)
        assert nlo >= lo and nhi >= hi


@FAST
@given(binom_counts(max_n=1000))
def test_wilson_narrows_with_more_data_at_the_same_rate(kn: tuple[int, int]) -> None:
    k, n = kn
    assume(n > 0)
    lo, hi = wilson_interval(k, n)
    lo4, hi4 = wilson_interval(4 * k, 4 * n)
    assert hi4 - lo4 <= hi - lo + 1e-12


@FAST
@given(st.integers(-5, 50), st.integers(-5, 50))
def test_wilson_rejects_impossible_counts(k: int, n: int) -> None:
    assume(not (0 <= k <= n))
    with pytest.raises(ValueError):
        wilson_interval(k, n)


# exact binomial / sign test ------------------------------------------------------------
@FAST
@given(binom_counts())
@example((0, 1001))
@example((3, 2999))
@example((10, 1075))
def test_binom_p_matches_scipy(kn: tuple[int, int]) -> None:
    k, n = kn
    p = binom_two_sided_p(k, n)
    assert 0.0 <= p <= 1.0
    ref = 1.0 if n == 0 else sps.binomtest(k, n, 0.5).pvalue
    if ref < 1e-290:
        # scipy underflows near the float floor (0.0 for k=10, n=1075); check
        # against the exact rational tail instead, rounded once to a float
        tail = sum(math.comb(n, i) for i in range(min(k, n - k) + 1))
        ref = min(1.0, float(Fraction(2 * tail, 2**n)))
        # subnormals carry fewer bits, hence the tiny absolute slack
        assert p == pytest.approx(ref, rel=1e-9, abs=1e-310)
    else:
        assert p == pytest.approx(ref, rel=1e-9)


@FAST
@given(binom_counts())
def test_binom_p_is_symmetric_and_falls_away_from_the_center(kn: tuple[int, int]) -> None:
    k, n = kn
    assert binom_two_sided_p(k, n) == binom_two_sided_p(n - k, n)
    if 2 * (k + 1) <= n:  # k + 1 is still at or below the center
        assert binom_two_sided_p(k, n) <= binom_two_sided_p(k + 1, n)


@FAST
@given(st.integers(0, 2000), st.integers(0, 2000))
def test_sign_test_is_symmetric(fixed: int, broken: int) -> None:
    p = sign_test(fixed, broken)
    assert p == sign_test(broken, fixed)
    assert 0.0 <= p <= 1.0
    if fixed == broken:
        assert p == 1.0


@FAST
@given(st.integers(-100, -1), st.integers(0, 100))
def test_sign_test_rejects_negative_counts(neg: int, other: int) -> None:
    with pytest.raises(ValueError):
        sign_test(neg, other)
    with pytest.raises(ValueError):
        sign_test(other, neg)


# quantile --------------------------------------------------------------------------------
@FAST
@given(st.lists(moderate, min_size=1, max_size=50), st.floats(0.0, 1.0))
def test_quantile_matches_numpy(values: list[float], q: float) -> None:
    got = quantile(values, q)
    assert got == pytest.approx(float(np.quantile(values, q)), rel=1e-9, abs=1e-9)


@FAST
@given(st.lists(finite, min_size=1, max_size=30), st.floats(0.0, 1.0), st.floats(0.0, 1.0))
@example([-1e308, 1e308], 0.5, 0.5)
@example([1.7e308, 1.7e308], 0.3, 0.3)
def test_quantile_stays_in_range_and_is_monotone(values: list[float], q1: float, q2: float) -> None:
    lo_q, hi_q = sorted((q1, q2))
    a, b = quantile(values, lo_q), quantile(values, hi_q)
    assert min(values) <= a <= b <= max(values)
    assert quantile(values, 0.0) == min(values)
    assert quantile(values, 1.0) == max(values)


@FAST
@given(st.lists(any_float, max_size=30), st.floats(0.0, 1.0))
@example([math.inf, math.inf], 0.5)
@example([-math.inf, -math.inf, 1.0], 0.4)
def test_quantile_ignores_nan_and_handles_infinities(values: list[float], q: float) -> None:
    clean = [v for v in values if not math.isnan(v)]
    if not clean:
        with pytest.raises(ValueError):
            quantile(values, q)
        return
    got = quantile(values, q)
    assert got == quantile(clean, q) or (math.isnan(got) and math.isnan(quantile(clean, q)))
    if math.isnan(got):
        # only "between -inf and +inf" has no value
        assert -math.inf in clean and math.inf in clean
    else:
        assert min(clean) <= got <= max(clean)


@FAST
@given(st.lists(moderate, min_size=1, max_size=5), st.floats(allow_nan=True))
def test_quantile_rejects_q_outside_unit_interval(values: list[float], q: float) -> None:
    assume(not 0.0 <= q <= 1.0)
    with pytest.raises(ValueError):
        quantile(values, q)


# bootstrap intervals ----------------------------------------------------------------------
@settings(max_examples=40, deadline=None)
@given(
    st.lists(moderate, min_size=1, max_size=30),
    st.lists(st.just(math.nan), max_size=3),
    st.integers(1, 200),
    st.integers(0, 2**32),
)
def test_bootstrap_interval_bounds_and_nan_handling(
    values: list[float], nans: list[float], resamples: int, seed: int
) -> None:
    lo, hi = bootstrap_mean_interval(values, resamples=resamples, seed=seed)
    tol = 1e-9 * max(1.0, max(abs(v) for v in values))
    assert min(values) - tol <= lo <= hi <= max(values) + tol
    assert bootstrap_mean_interval(values + nans, resamples, seed) == (lo, hi)
    assert bootstrap_mean_interval(values, resamples, seed) == (lo, hi)  # deterministic


@settings(max_examples=30, deadline=None)
@given(st.floats(-1e6, 1e6), st.integers(1, 20))
def test_bootstrap_of_a_constant_is_that_constant(c: float, n: int) -> None:
    lo, hi = bootstrap_mean_interval([c] * n, resamples=50)
    assert lo == pytest.approx(c, abs=1e-9) and hi == pytest.approx(c, abs=1e-9)


@settings(max_examples=30, deadline=None)
@given(st.lists(st.just(math.nan), max_size=4), st.integers(-3, 0))
def test_bootstrap_rejects_empty_samples_and_no_resamples(nans: list[float], bad: int) -> None:
    with pytest.raises(ValueError):
        bootstrap_mean_interval(nans)
    with pytest.raises(ValueError):
        bootstrap_mean_interval([1.0], resamples=bad)


@settings(max_examples=30, deadline=None)
@given(st.lists(st.sampled_from([math.inf, -math.inf, 1.0, -2.0]), min_size=1, max_size=8))
@example([math.inf, math.inf, math.inf, -math.inf, -math.inf, -math.inf])
def test_bootstrap_with_infinities_never_raises(values: list[float]) -> None:
    lo, hi = bootstrap_mean_interval(values, resamples=50)
    if math.inf in values and -math.inf in values:
        # some resample may mix both signs: then the whole interval is undefined
        assert (math.isnan(lo) and math.isnan(hi)) or lo <= hi
    else:
        assert lo <= hi


def test_bootstrap_with_mixed_infinities_is_undefined_not_an_error() -> None:
    # regression: every resample mixed inf and -inf, all means were NaN, and
    # quantile raised "quantile of an empty sample"
    mixed = [math.inf, math.inf, math.inf, -math.inf, -math.inf, -math.inf]
    lo, hi = bootstrap_mean_interval(mixed, resamples=50)
    assert math.isnan(lo) and math.isnan(hi)
    lo, hi = bootstrap_mean_interval([math.inf, -math.inf, 1.0])
    assert math.isnan(lo) and math.isnan(hi)


@st.composite
def pairs(draw: st.DrawFn) -> tuple[list[float], list[float]]:
    n = draw(st.integers(0, 25))
    cell = st.one_of(moderate, st.just(math.nan))
    return draw(st.lists(cell, min_size=n, max_size=n)), draw(
        st.lists(cell, min_size=n, max_size=n)
    )


@settings(max_examples=40, deadline=None)
@given(pairs(), st.integers(1, 200), st.integers(0, 1000))
def test_paired_bootstrap_p_is_a_symmetric_probability(
    ab: tuple[list[float], list[float]], resamples: int, seed: int
) -> None:
    a, b = ab
    p = paired_bootstrap_p(a, b, resamples=resamples, seed=seed)
    assert 0.0 < p <= 1.0
    assert paired_bootstrap_p(b, a, resamples=resamples, seed=seed) == p
    assert p >= 2.0 / (resamples + 1) or p == 1.0
    assert paired_bootstrap_p(a, a, resamples=resamples, seed=seed) == 1.0


@settings(max_examples=30, deadline=None)
@given(st.lists(moderate, max_size=5), st.lists(moderate, max_size=5))
def test_paired_bootstrap_rejects_unequal_lengths(a: list[float], b: list[float]) -> None:
    assume(len(a) != len(b))
    with pytest.raises(ValueError):
        paired_bootstrap_p(a, b)


@settings(max_examples=30, deadline=None)
@given(st.lists(moderate, min_size=2, max_size=20), st.floats(0.5, 1e3))
def test_paired_bootstrap_detects_a_uniform_shift(a: list[float], shift: float) -> None:
    # every difference is the same positive number: every resampled mean is > 0
    b = [x - shift for x in a]
    assume(all(x - y > 0 for x, y in zip(a, b, strict=True)))
    assert paired_bootstrap_p(a, b, resamples=99) == pytest.approx(2.0 / 100)


# Welch ------------------------------------------------------------------------------------
@pytest.mark.filterwarnings("ignore:Precision loss occurred:RuntimeWarning")
@FAST
@given(
    st.lists(moderate, min_size=2, max_size=15),
    st.lists(moderate, min_size=2, max_size=15),
)
@example([0.0, 0.0], [699050.9501341588] * 3)
def test_welch_matches_scipy(a: list[float], b: list[float]) -> None:
    p = welch_p(a, b)
    if len(set(a)) == 1 and len(set(b)) == 1:
        assert p is None
        return
    # scipy loses everything to cancellation when the spread is ~1e-10 of the values
    spread = max(max(a) - min(a), max(b) - min(b))
    scale = max(map(abs, a + b))
    # and its variance underflows for spreads near the float minimum
    assume(spread > 1e-6 * scale and spread > 1e-100)
    assert p is not None and 0.0 <= p <= 1.0
    ref = float(sps.ttest_ind(a, b, equal_var=False).pvalue)
    assert p == pytest.approx(ref, rel=1e-6, abs=1e-12)


@FAST
@given(
    st.lists(finite, min_size=2, max_size=10),
    st.lists(finite, min_size=2, max_size=10),
    st.integers(-40, 40),
)
@example([1e200, -1e200], [0.0, 1.0], 0)
@example([1e308, -1e308], [1.0, 2.0], 0)
@example([0.0, 1e-160], [5.0, 5.0], 0)
@example([0.0, 5e-324], [1.0, 1.0], 0)
def test_welch_never_raises_is_symmetric_and_scale_free(
    a: list[float], b: list[float], k: int
) -> None:
    p = welch_p(a, b)
    assert p is None or 0.0 <= p <= 1.0
    assert welch_p(b, a) == p
    # t and df do not change when every value is scaled; a power of two scales exactly
    factor = 2.0**k
    scaled_a, scaled_b = [x * factor for x in a], [y * factor for y in b]

    def normal(x: float) -> bool:
        return x == 0.0 or sys.float_info.min <= abs(x) <= sys.float_info.max

    exact = all(normal(x) and normal(s) for x, s in zip(a + b, scaled_a + scaled_b, strict=True))
    if exact:
        assert welch_p(scaled_a, scaled_b) == p


def _exact_welch_p(a: list[float], b: list[float]) -> float:
    """Welch p from t and df worked out in exact rationals, then scipy's t tail."""
    fa, fb = [Fraction(x) for x in a], [Fraction(y) for y in b]
    ma, mb = sum(fa) / len(fa), sum(fb) / len(fb)
    sa = sum((x - ma) ** 2 for x in fa) / (len(fa) - 1) / len(fa)
    sb = sum((y - mb) ** 2 for y in fb) / (len(fb) - 1) / len(fb)
    t2 = (ma - mb) ** 2 / (sa + sb)
    df = (sa + sb) ** 2 / (sa**2 / (len(fa) - 1) + sb**2 / (len(fb) - 1))
    with decimal.localcontext() as ctx:
        ctx.prec = 40
        t = float((decimal.Decimal(t2.numerator) / decimal.Decimal(t2.denominator)).sqrt())
    return 0.0 if math.isinf(t) else float(2.0 * sps.t.sf(t, float(df)))


small_ints = st.one_of(st.just(0), st.integers(-1000, 1000))  # zeros come up often


@FAST
@given(
    st.lists(small_ints, min_size=2, max_size=8),
    st.lists(small_ints, min_size=2, max_size=8),
    st.integers(-1074, 1000),
    st.integers(-1074, 1000),
)
@example([0, 1], [1, 1], -232, 997)  # a spread of ~1e-70 next to values of ~1e300
@example([0, 1] * 4, [0] * 8, -1074, 0)  # subnormals next to an all-zero sample
def test_welch_on_two_unrelated_scales_matches_exact_arithmetic(
    ia: list[int], ib: list[int], ka: int, kb: int
) -> None:
    # every value is an int times a power of two (down to 2**-1074): exact and finite
    a, b = [math.ldexp(i, ka) for i in ia], [math.ldexp(i, kb) for i in ib]
    p = welch_p(a, b)
    if len(set(a)) == 1 and len(set(b)) == 1:
        assert p is None
        return
    assert p is not None
    assert p == pytest.approx(_exact_welch_p(a, b), rel=1e-6, abs=1e-280)


@FAST
@given(
    st.lists(moderate, min_size=2, max_size=8),
    st.lists(moderate, min_size=2, max_size=8),
    st.sampled_from([math.inf, -math.inf]),
)
def test_welch_with_an_infinite_value_has_no_p(a: list[float], b: list[float], inf: float) -> None:
    assert welch_p([*a, inf], b) is None
    assert welch_p(a, [*b, inf]) is None


@FAST
@given(st.lists(any_float, max_size=1), st.lists(any_float, max_size=10))
def test_welch_needs_two_values_per_side(a: list[float], b: list[float]) -> None:
    assert welch_p(a, b) is None
    assert welch_p(b, a) is None


# examples_needed --------------------------------------------------------------------------
def _brute_examples_needed(fixed: int, broken: int, n_total: int, max_n: int) -> int | None:
    fr, br = fixed / n_total, broken / n_total
    for n in range(1, max_n + 1):
        f, b = round(n * fr), round(n * br)
        if f + b and sps.binomtest(min(f, b), f + b, 0.5).pvalue < 0.05:
            return n
    return None


@settings(max_examples=40, deadline=None)
@given(st.integers(0, 40), st.integers(0, 40), st.integers(1, 120))
@example(6, 2, 100)
def test_examples_needed_is_the_true_minimum(fixed: int, broken: int, n_total: int) -> None:
    assume(fixed + broken <= n_total)
    max_n = 400
    got = examples_needed(fixed, broken, n_total, max_n=max_n)
    assert got == examples_needed(broken, fixed, n_total, max_n=max_n)
    if fixed == broken:
        assert got is None
        return
    assert got == _brute_examples_needed(fixed, broken, n_total, max_n)


@FAST
@given(st.integers(0, 50), st.integers(0, 50), st.integers(-10, 0))
def test_examples_needed_without_data_is_none(fixed: int, broken: int, n_total: int) -> None:
    assert examples_needed(fixed, broken, n_total) is None


# ECDF -------------------------------------------------------------------------------------
@FAST
@given(st.lists(st.one_of(finite, st.just(math.nan)), max_size=80), st.integers(1, 30))
def test_ecdf_points_are_a_true_cdf_subset(values: list[float], max_points: int) -> None:
    pts = ecdf_points(values, max_points=max_points)
    clean = sorted(v for v in values if not math.isnan(v))
    if not clean:
        assert pts == []
        return
    assert 1 <= len(pts) <= max_points
    xs = [x for x, _ in pts]
    assert xs == sorted(set(xs))
    assert pts[-1] == (clean[-1], 1.0)
    for x, f in pts:
        assert f == sum(1 for v in clean if v <= x) / len(clean)


@FAST
@given(st.integers(-5, 0))
def test_ecdf_rejects_no_points(bad: int) -> None:
    with pytest.raises(ValueError):
        ecdf_points([1.0], max_points=bad)


# regressions found by the properties above -------------------------------------------------
def test_regression_quantile_between_equal_infinities_and_across_the_float_range() -> None:
    assert quantile([math.inf, math.inf], 0.5) == math.inf  # was NaN
    assert quantile([-1e308, 1e308], 0.5) == 0.0  # was inf
    assert math.isnan(quantile([-math.inf, math.inf], 0.5))


def test_regression_welch_near_the_float_limits() -> None:
    assert welch_p([1e200, -1e200], [0.0, 1.0]) == pytest.approx(1.0)  # was OverflowError
    assert welch_p([0.0, 1e-160], [5.0, 5.0]) == pytest.approx(0.0, abs=1e-12)  # ZeroDivision
    assert welch_p([math.inf, 1.0], [0.0, 1.0]) is None  # was 1.0
    assert welch_p([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == pytest.approx(0.021312, abs=1e-6)
    # a constant whose sum / n rounds off by an ulp is still constant (was 1.4e-32)
    assert welch_p([0.0, 0.0], [699050.9501341588] * 3) is None
    # an all-zero sample set the shared scale and flushed subnormal means (gave 1.0)
    assert welch_p([0.0, 5e-324] * 4, [0.0] * 8) == pytest.approx(0.0331455, rel=1e-5)
    # one shared scale underflowed the small sample's spread to 0 (gave None)
    assert welch_p([0.0, 1e-70], [1e300, 1e300]) == 0.0
