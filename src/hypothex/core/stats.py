"""Pure statistics helpers for leaderboards and views (no scipy)."""

from __future__ import annotations

import math
import random
from bisect import bisect_right
from collections.abc import Sequence

Z95 = 1.959963984540054
_EXACT_BINOM_MAX_N = 1000


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

    NaN values are ignored.

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
    return xs[lo] + (h - lo) * (xs[lo + 1] - xs[lo])


def bootstrap_mean_interval(
    values: Sequence[float], resamples: int = 1000, seed: int = 0
) -> tuple[float, float]:
    """
    Percentile bootstrap 95% interval for the mean.

    NaN values are ignored. Resampling uses ``random.Random(seed)``, so the
    result is deterministic for a given input.

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
        The 2.5th and 97.5th percentiles of the resampled means.

    Raises
    ------
    ValueError
        If no non-NaN values are given or ``resamples < 1``.

    Examples
    --------
    >>> bootstrap_mean_interval([0.5, 0.5, 0.5])
    (0.5, 0.5)
    """
    xs = _clean(values)
    if not xs:
        raise ValueError("bootstrap of an empty sample")
    if resamples < 1:
        raise ValueError(f"resamples must be >= 1, got {resamples}")
    n = len(xs)
    rng = random.Random(seed)
    means = [sum(rng.choices(xs, k=n)) / n for _ in range(resamples)]
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
    rng = random.Random(seed)
    at_or_below = 0
    at_or_above = 0
    for _ in range(resamples):
        m = sum(rng.choices(diffs, k=n)) / n
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
