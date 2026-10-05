"""Pure statistics helpers for leaderboards and views (no scipy)."""

from __future__ import annotations

import math
import random
from bisect import bisect_right
from collections.abc import Callable, Iterator, Sequence
from functools import lru_cache
from operator import itemgetter

Z95 = 1.959963984540054
_EXACT_BINOM_MAX_N = 1000
RESAMPLE_CACHE_MAX = 1_000_000
"""Largest ``n * resamples`` whose bootstrap positions are kept between calls (8 bytes each)."""

_Draw = Callable[[Sequence[float]], tuple[float, ...]]


def _clean(values: Sequence[float]) -> list[float]:
    """Return ``values`` as floats with NaN entries removed."""
    return [float(v) for v in values if not math.isnan(float(v))]


def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """
    Wilson score interval for a binomial proportion.

    Parameters
    ----------
    successes : int
        Number of successes, ``0 <= successes <= n``.
    n : int
        Number of trials.
    z : float
        Normal quantile; the default gives a 95% interval.

    Returns
    -------
    tuple of (float, float)
        Lower and upper bound, both in ``[0, 1]``. ``(0.0, 1.0)`` when ``n == 0``.

    Raises
    ------
    ValueError
        If ``successes`` is outside ``[0, n]``.

    Examples
    --------
    >>> lo, hi = wilson_interval(8, 10)
    >>> round(lo, 4), round(hi, 4)
    (0.4902, 0.9433)
    """
    if n < 0 or not 0 <= successes <= n:
        raise ValueError(f"need 0 <= successes <= n, got successes={successes}, n={n}")
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = z / denom * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    lo = 0.0 if successes == 0 else max(0.0, center - half)
    hi = 1.0 if successes == n else min(1.0, center + half)
    return (lo, hi)


def _log_binom_pmf_half(i: int, n: int) -> float:
    """Log of ``C(n, i) / 2**n``."""
    return math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) - n * math.log(2.0)


def binom_two_sided_p(k: int, n: int) -> float:
    """
    Exact two-sided binomial test p-value with success probability 0.5.

    The distribution is symmetric, so the p-value is
    ``min(1, 2 * P(X <= min(k, n - k)))`` for ``X ~ Binomial(n, 0.5)``. Up to
    ``n = 1000`` the tail is an exact integer sum; above that it is summed
    from its largest term down, scaled by that term's log-space value, so it
    stays accurate and fast. Tails below the smallest float return 0.0.

    Parameters
    ----------
    k : int
        Observed number of successes, ``0 <= k <= n``.
    n : int
        Number of trials.

    Returns
    -------
    float
        The p-value in ``[0, 1]``; 1.0 when ``n == 0``.

    Raises
    ------
    ValueError
        If ``k`` is outside ``[0, n]``.

    Examples
    --------
    >>> binom_two_sided_p(2, 10)
    0.109375
    """
    if n < 0 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    m = min(k, n - k)
    if n == 0 or 2 * m >= n:
        return 1.0
    if n <= _EXACT_BINOM_MAX_N:
        return min(1.0, 2 * sum(math.comb(n, i) for i in range(m + 1)) / 2**n)
    total = 1.0
    term = 1.0
    for i in range(m, 0, -1):
        term *= i / (n - i + 1)
        total += term
        if term < 1e-17 * total:
            break
    return min(1.0, 2.0 * math.exp(_log_binom_pmf_half(m, n)) * total)


def sign_test(fixed: int, broken: int) -> float:
    """
    Exact two-sided sign test on discordant pairs.

    Parameters
    ----------
    fixed : int
        Examples the candidate gets right and the reference gets wrong.
    broken : int
        Examples the candidate gets wrong and the reference gets right.

    Returns
    -------
    float
        The p-value; 1.0 when there are no discordant pairs.

    Examples
    --------
    >>> sign_test(8, 2)
    0.109375
    """
    if fixed < 0 or broken < 0:
        raise ValueError(f"counts must be >= 0, got fixed={fixed}, broken={broken}")
    return binom_two_sided_p(fixed, fixed + broken)


def quantile(values: Sequence[float], q: float) -> float:
    """
    Quantile with linear interpolation (numpy's default ``"linear"`` method).

    NaN values are ignored. The result always lies between the two values it
    interpolates: equal neighbours give that value (``inf`` for two ``inf``),
    and a gap too wide for a float (``-1e308`` to ``1e308``) does not overflow.
    Only a step from ``-inf`` to ``inf`` gives NaN.

    Parameters
    ----------
    values : sequence of float
        Sample values.
    q : float
        Quantile in ``[0, 1]``.

    Returns
    -------
    float
        The interpolated quantile.

    Raises
    ------
    ValueError
        If ``q`` is outside ``[0, 1]`` or no non-NaN values are given.

    Examples
    --------
    >>> quantile([1.0, 2.0, 3.0, 4.0], 0.25)
    1.75
    """
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"q must be in [0, 1], got {q}")
    xs = sorted(_clean(values))
    if not xs:
        raise ValueError("quantile of an empty sample")
    h = (len(xs) - 1) * q
    lo = math.floor(h)
    if lo + 1 >= len(xs):
        return xs[-1]
    a, b, frac = xs[lo], xs[lo + 1], h - lo
    if frac == 0.0 or a == b:
        return a  # also inf for two equal infinities, where the step below gives NaN
    gap = b - a
    if math.isfinite(gap):
        return a + frac * gap
    return a * (1.0 - frac) + b * frac  # the gap overflowed, or one side is infinite


@lru_cache(maxsize=4)
def _draws(n: int, resamples: int, seed: int) -> tuple[_Draw, ...]:
    """
    One draw per bootstrap resample of a sample of size ``n``, kept for 4 sizes.

    A draw picks the positions ``rng.choices(xs, k=n)`` picks (``floor(u * n)``
    for each ``u`` of ``random.Random(seed).random()``), so applying the draws in
    order equals a ``choices`` loop bit for bit. The positions depend only on
    ``(n, resamples, seed)``, never on the values: a leaderboard bootstraps every
    seed group over the same examples, so they are drawn once per sample size
    and not once per row. Draws are ``itemgetter`` objects, so applying one runs
    in C.
    """
    rng = random.Random(seed)
    u = rng.random
    size = float(n)
    positions = list(range(n))  # shared int objects keep the kept draws small
    draws: list[_Draw] = []
    for _ in range(resamples):
        picked = [positions[math.floor(u() * size)] for _ in range(n)]
        if n == 1:
            draws.append(lambda xs, i=picked[0]: (xs[i],))
        else:
            draws.append(itemgetter(*picked))
    return tuple(draws)


def _resample_sums(xs: list[float], resamples: int, seed: int) -> Iterator[float]:
    """
    Sum of each bootstrap resample of ``xs`` (``sum(rng.choices(xs, k=len(xs)))``).

    Samples up to ``RESAMPLE_CACHE_MAX`` total draws reuse ``_draws``; larger ones
    draw from ``random.Random(seed)`` directly. Both give the same sums.
    """
    n = len(xs)
    if n * resamples <= RESAMPLE_CACHE_MAX:
        for draw in _draws(n, resamples, seed):
            yield sum(draw(xs))
        return
    rng = random.Random(seed)
    for _ in range(resamples):
        yield sum(rng.choices(xs, k=n))


def bootstrap_mean_interval(
    values: Sequence[float], resamples: int = 1000, seed: int = 0
) -> tuple[float, float]:
    """
    Percentile bootstrap 95% interval for the mean.

    NaN values are ignored. Resampling uses ``random.Random(seed)``, so the
    result is deterministic for a given input. If any resample holds both
    ``inf`` and ``-inf``, its mean is undefined, so the interval is undefined
    too and ``(nan, nan)`` is returned (dropping those resamples would bias
    the interval).

    Parameters
    ----------
    values : sequence of float
        Per-example values.
    resamples : int
        Number of bootstrap resamples.
    seed : int
        Seed of the resampling generator.

    Returns
    -------
    tuple of (float, float)
        The 2.5th and 97.5th percentiles of the resampled means;
        ``(nan, nan)`` when a resampled mean is undefined.

    Raises
    ------
    ValueError
        If no non-NaN values are given or ``resamples < 1``.

    Examples
    --------
    >>> bootstrap_mean_interval([0.5, 0.5, 0.5])
    (0.5, 0.5)
    >>> bootstrap_mean_interval([math.inf, -math.inf])
    (nan, nan)
    """
    xs = _clean(values)
    if not xs:
        raise ValueError("bootstrap of an empty sample")
    if resamples < 1:
        raise ValueError(f"resamples must be >= 1, got {resamples}")
    n = len(xs)
    means = [total / n for total in _resample_sums(xs, resamples, seed)]
    if any(math.isnan(m) for m in means):
        return (math.nan, math.nan)
    return (quantile(means, 0.025), quantile(means, 0.975))


def paired_bootstrap_p(
    a: Sequence[float], b: Sequence[float], resamples: int = 1000, seed: int = 0
) -> float:
    """
    Two-sided paired bootstrap p-value for ``mean(a - b) != 0``.

    Pairs are resampled together. The p-value is
    ``min(1, 2 * (min(#(m <= 0), #(m >= 0)) + 1) / (resamples + 1))`` where
    ``m`` runs over the resampled mean differences; the ``+ 1`` keeps it
    above zero. Pairs with a NaN on either side are dropped.

    Parameters
    ----------
    a, b : sequence of float
        Per-example values of the two runs, in the same example order.
    resamples : int
        Number of bootstrap resamples.
    seed : int
        Seed of the resampling generator.

    Returns
    -------
    float
        The p-value in ``(0, 1]``; 1.0 when no pairs remain.

    Raises
    ------
    ValueError
        If ``a`` and ``b`` differ in length or ``resamples < 1``.

    Examples
    --------
    >>> paired_bootstrap_p([1.0, 2.0], [1.0, 2.0])
    1.0
    """
    if len(a) != len(b):
        raise ValueError(f"paired samples differ in length: {len(a)} != {len(b)}")
    if resamples < 1:
        raise ValueError(f"resamples must be >= 1, got {resamples}")
    diffs = [
        float(x) - float(y)
        for x, y in zip(a, b, strict=True)
        if not (math.isnan(float(x)) or math.isnan(float(y)))
    ]
    if not diffs:
        return 1.0
    n = len(diffs)
    at_or_below = 0
    at_or_above = 0
    for total in _resample_sums(diffs, resamples, seed):
        m = total / n
        at_or_below += m <= 0.0
        at_or_above += m >= 0.0
    return min(1.0, 2.0 * (min(at_or_below, at_or_above) + 1) / (resamples + 1))


def examples_needed(
    fixed: int, broken: int, n_total: int, alpha: float = 0.05, max_n: int = 100_000
) -> int | None:
    """
    Smallest test-set size at which the observed discordant rates would be significant.

    The fixed and broken rates (``fixed / n_total``, ``broken / n_total``) are
    held constant and scaled to ``n`` examples (counts rounded to the nearest
    integer, ``round``). The result is the true minimum ``n <= max_n`` with
    ``sign_test(round(n * fixed_rate), round(n * broken_rate)) < alpha``.
    Rounded counts make the p-value non-monotone in ``n`` (a larger ``n`` can
    round the smaller count up and lose significance), so a binary search could
    miss the minimum. Instead every ``n`` is scanned: the p-value changes only
    when a count changes (by one), and the tail ``P(X <= small)`` of
    ``X ~ Binomial(small + large, 1/2)`` is updated in O(1) per change with

    - larger count + 1: ``F(s; d + 1) = F(s; d) - pmf(s; d) / 2``
    - smaller count + 1: ``F(s + 1; d + 1) = F(s; d) + pmf(s + 1; d) / 2``

    (``pmf`` from ``lgamma``). A candidate below ``alpha`` is confirmed with the
    exact ``binom_two_sided_p`` before it is returned, so float drift in the
    running tail never changes the answer. The scan to ``max_n = 100_000`` takes
    about 0.1 s in the worst case.

    Parameters
    ----------
    fixed : int
        Discordant examples in favour of the candidate.
    broken : int
        Discordant examples against the candidate.
    n_total : int
        Examples scored for both runs.
    alpha : float
        Significance level.
    max_n : int
        Search limit.

    Returns
    -------
    int or None
        The number of examples, or None when ``fixed == broken``,
        ``n_total <= 0``, or ``max_n`` examples would not be enough.

    Examples
    --------
    >>> examples_needed(6, 2, 100)
    209
    """
    if n_total <= 0 or fixed == broken:
        return None
    small_rate = min(fixed, broken) / n_total
    large_rate = max(fixed, broken) / n_total
    small = large = 0
    cdf = 1.0  # P(X <= small) for X ~ Binomial(small + large, 1/2)
    for n in range(1, max_n + 1):
        new_small, new_large = round(n * small_rate), round(n * large_rate)
        if (new_small, new_large) == (small, large):
            continue
        if new_large != large:
            cdf -= 0.5 * math.exp(_log_binom_pmf_half(small, small + large))
            large += 1
        if new_small != small:
            cdf += 0.5 * math.exp(_log_binom_pmf_half(small + 1, small + large))
            small += 1
        total = small + large
        if 2 * min(small, large) >= total:
            continue  # p = 1
        # rounding can briefly put the smaller rate's count above the larger one
        tail = cdf if small < large else 1.0 - cdf + math.exp(_log_binom_pmf_half(small, total))
        if 2.0 * tail < alpha + 1e-9 and binom_two_sided_p(small, total) < alpha:
            return n
    return None


def ecdf_points(values: Sequence[float], max_points: int = 200) -> list[tuple[float, float]]:
    """
    Points ``(x, F(x))`` of the empirical CDF, at most ``max_points`` of them.

    ``F(x)`` is the fraction of values ``<= x``. With more distinct values
    than ``max_points``, points are taken at evenly spaced ranks; the maximum
    (``F = 1``) is always included. NaN values are ignored.

    Parameters
    ----------
    values : sequence of float
        Sample values.
    max_points : int
        Maximum number of points returned, ``>= 1``.

    Returns
    -------
    list of tuple of (float, float)
        Points sorted by ``x``; empty for an empty sample.

    Raises
    ------
    ValueError
        If ``max_points < 1``.

    Examples
    --------
    >>> ecdf_points([3.0, 1.0, 2.0, 2.0])
    [(1.0, 0.25), (2.0, 0.75), (3.0, 1.0)]
    """
    if max_points < 1:
        raise ValueError(f"max_points must be >= 1, got {max_points}")
    xs = sorted(_clean(values))
    n = len(xs)
    if n == 0:
        return []
    distinct = sorted(set(xs))
    if len(distinct) <= max_points:
        candidates = distinct
    else:
        candidates = [xs[-(-(i + 1) * n // max_points) - 1] for i in range(max_points)]
    points: list[tuple[float, float]] = []
    for x in candidates:
        if points and points[-1][0] == x:
            continue
        points.append((x, bisect_right(xs, x) / n))
    return points


def _lttb_axis(values: Sequence[float]) -> list[float]:
    """
    Center and scale a finite axis without losing large integer step differences.

    Parameters
    ----------
    values : sequence of float
        Nonempty coordinates; integer coordinates retain exact subtraction.

    Returns
    -------
    list of float
        Bounded coordinates with the same relative geometry. When subtraction
        overflows, scale the original values, whose spread is already large.
    """
    shifted = [value - values[0] for value in values]
    scale = max(abs(value) for value in shifted) or 1.0
    if math.isfinite(scale):
        return [value / scale for value in shifted]
    scale = max(abs(value) for value in values) or 1.0
    return [value / scale for value in values]


def lttb(xs: Sequence[float], ys: Sequence[float], limit: int) -> list[int]:
    """
    Indices of at most ``limit`` points that keep a line's shape (LTTB).

    Largest-Triangle-Three-Buckets: the first and last points are always kept.
    The points between them are cut into ``limit - 2`` buckets of near-equal
    size (exact integer bounds); from each bucket the point that makes the
    largest triangle with the point kept before it and the mean of the next
    bucket is kept (the first on a tie), so peaks such as a loss spike survive
    the thinning, unlike every-n-th sampling. Each axis is centered and rescaled
    before computing triangle areas, preserving large integer step differences
    and preventing overflow for finite extreme values.

    Parameters
    ----------
    xs : sequence of float
        x of each point, in drawing order.
    ys : sequence of float
        y of each point.
    limit : int
        Most points to keep, at least 2; a series that is not longer is kept whole.

    Returns
    -------
    list of int
        Increasing indices into ``xs`` / ``ys``.

    Raises
    ------
    ValueError
        If ``limit`` is less than 2.

    Examples
    --------
    >>> lttb([0, 1, 2, 3, 4], [0, 0, 9, 0, 0], 3)
    [0, 2, 4]
    >>> lttb([0, 1], [5, 6], 3)
    [0, 1]
    """
    if limit < 2:
        raise ValueError(f"lttb keeps at least 2 points, not {limit}")
    n = len(xs)
    if n <= limit:
        return list(range(n))
    xs = _lttb_axis(xs)
    ys = _lttb_axis(ys)
    inner = limit - 2
    out = [0]
    kept = 0
    for b in range(inner):
        # bucket b is [start, stop); the next bucket (the last point after the
        # last bucket) gives the mean the triangle is drawn to
        start = b * (n - 2) // inner + 1
        stop = (b + 1) * (n - 2) // inner + 1
        after = range(stop, min((b + 2) * (n - 2) // inner + 1, n)) or range(n - 1, n)
        mean_x = math.fsum(xs[j] for j in after) / len(after)
        mean_y = math.fsum(ys[j] for j in after) / len(after)
        x0, y0 = xs[kept], ys[kept]
        kept = max(
            range(start, stop),
            key=lambda j: abs((x0 - mean_x) * (ys[j] - y0) - (x0 - xs[j]) * (mean_y - y0)),
        )
        out.append(kept)
    out.append(n - 1)
    return out


_BETACF_MAX_ITER = 300
_BETACF_EPS = 3.0e-16
_BETACF_FPMIN = 1.0e-300


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical Recipes ``betacf``)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _BETACF_FPMIN:
        d = _BETACF_FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, _BETACF_MAX_ITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _BETACF_FPMIN:
            d = _BETACF_FPMIN
        c = 1.0 + aa / c
        if abs(c) < _BETACF_FPMIN:
            c = _BETACF_FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _BETACF_FPMIN:
            d = _BETACF_FPMIN
        c = 1.0 + aa / c
        if abs(c) < _BETACF_FPMIN:
            c = _BETACF_FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _BETACF_EPS:
            break
    return h


def _regularized_beta(a: float, b: float, x: float) -> float:
    """
    Regularized incomplete beta function ``I_x(a, b)``.

    Parameters
    ----------
    a, b : float
        Positive shape parameters.
    x : float
        Point in ``[0, 1]``.

    Returns
    -------
    float
        ``I_x(a, b)`` in ``[0, 1]``.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _t_two_sided_p(t: float, df: float) -> float:
    """
    Two-sided p-value ``P(|T| >= |t|)`` for Student's t with ``df`` degrees of freedom.

    Uses ``P(|T| >= |t|) = I_{df / (df + t^2)}(df / 2, 1 / 2)``.

    Parameters
    ----------
    t : float
        The t statistic.
    df : float
        Degrees of freedom (may be fractional), ``> 0``.

    Returns
    -------
    float
        The two-sided p-value.
    """
    if math.isinf(t):
        return 0.0
    return min(1.0, _regularized_beta(df / 2.0, 0.5, df / (df + t * t)))


def welch_p(a: Sequence[float], b: Sequence[float]) -> float | None:
    """
    Two-sided Welch t-test p-value for a difference in means.

    NaN values are ignored. Degrees of freedom follow Welch-Satterthwaite. Each
    sample is scaled by its own power of two (exact), so values near the float
    limits never overflow and a tiny spread never underflows to zero variance,
    even next to a sample of a very different size.

    Parameters
    ----------
    a, b : sequence of float
        The two independent samples (for example, one value per seed).

    Returns
    -------
    float or None
        The p-value, or None when either sample has fewer than 2 values,
        both samples have zero variance, or a value is infinite.

    Examples
    --------
    >>> round(welch_p([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]), 6)
    0.021312
    """
    xs = _clean(a)
    ys = _clean(b)
    if len(xs) < 2 or len(ys) < 2:
        return None
    if not all(math.isfinite(v) for v in (*xs, *ys)):
        return None  # an infinite mean or variance has no t statistic
    # Each sample is scaled by its own power of two (exact), so its sum, squares
    # and deviations neither overflow nor underflow, whatever the other sample's
    # scale. The variances and the mean difference are then put on one scale.
    ma, va, ea = _scaled_moments(xs)
    mb, vb, eb = _scaled_moments(ys)
    if va == 0.0 and vb == 0.0:
        return None  # both samples are constant
    na, nb = len(xs), len(ys)
    wa, wb = va / na, vb / nb  # var/n of each sample is w * 4**e
    f = max(math.frexp(w)[1] + 2 * e for w, e in ((wa, ea), (wb, eb)) if w > 0.0)
    f += f % 2  # even, so the square root of 2**f is exact
    sa, sb = math.ldexp(wa, 2 * ea - f), math.ldexp(wb, 2 * eb - f)  # larger in [0.25, 1)
    # a zero mean (an all-zero sample) has no scale: it must not push the
    # other mean below the smallest float
    g = max((e for m, e in ((ma, ea), (mb, eb)) if m != 0.0), default=0)
    diff = math.ldexp(ma, ea - g) - math.ldexp(mb, eb - g)  # (mean_a - mean_b) / 2**g
    u = diff / math.sqrt(sa + sb)  # t / 2**shift, |u| <= 4
    shift = g - f // 2
    if u == 0.0:
        t = 0.0
    elif math.frexp(u)[1] + shift > 1024:
        t = math.copysign(math.inf, u)  # beyond the largest float
    else:
        t = math.ldexp(u, shift)
    df = (sa + sb) ** 2 / (sa * sa / (na - 1) + sb * sb / (nb - 1))
    return _t_two_sided_p(t, df)


def _scaled_moments(xs: list[float]) -> tuple[float, float, int]:
    """
    Mean and sample variance of finite ``xs``, scaled by a power of two.

    Returns ``(m, v, e)`` with mean ``m * 2**e`` and variance ``v * 4**e``,
    where ``2**e`` is the power of two just above the largest magnitude.
    """
    biggest = max(abs(x) for x in xs)
    e = math.frexp(biggest)[1] if biggest else 0
    ys = [math.ldexp(x, -e) for x in xs]
    if all(y == ys[0] for y in ys):
        return ys[0], 0.0, e  # sum / n can miss a constant by an ulp
    m = sum(ys) / len(ys)
    v = sum((y - m) ** 2 for y in ys) / (len(ys) - 1)
    return m, v, e
