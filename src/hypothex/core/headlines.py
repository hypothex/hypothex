"""One-line findings and stat strips generated from leaderboard data."""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence

from hypothex.core.seeds import t_critical

MINUS = "−"
NO_RUNS = "No scored runs yet"
_PERCENTILE = re.compile(r"(?<![A-Za-z0-9])p(\d{1,2}(?:\.\d+)?)(?![0-9])")


# formatting ------------------------------------------------------------------
def fmt_value(x: float) -> str:
    """
    Format a metric value: 3 decimals in [-1, 1], fewer for larger values.

    Parameters
    ----------
    x : float
        Value to format.

    Returns
    -------
    str
        The value; negatives use the Unicode minus sign.

    Examples
    --------
    >>> fmt_value(0.03712)
    '0.037'
    >>> fmt_value(1234.4)
    '1,234'
    """
    a = abs(x)
    if a <= 1:
        body = f"{a:.3f}"
    elif a < 10:
        body = f"{a:.2f}"
    elif a < 100:
        body = f"{a:.1f}"
    else:
        body = f"{a:,.0f}"
    return MINUS + body if x < 0 and body.strip("0.,") else body


def fmt_delta(x: float) -> str:
    """
    Format a signed difference with an explicit ``+`` or ``−``.

    Parameters
    ----------
    x : float
        Difference to format.

    Returns
    -------
    str
        Signed value; a difference that rounds to zero has no sign.

    Examples
    --------
    >>> fmt_delta(0.0371)
    '+0.037'
    """
    body = fmt_value(abs(x))
    if not body.strip("0.,"):
        return body
    return ("+" if x > 0 else MINUS) + body


def fmt_p(p: float) -> str:
    """
    Format a p-value for a headline.

    Parameters
    ----------
    p : float
        The p-value.

    Returns
    -------
    str
        ``p < 0.001`` when tiny, 3 decimals below 0.01, else 2 decimals.

    Examples
    --------
    >>> fmt_p(0.1467)
    'p = 0.15'
    """
    if p < 0.001:
        return "p < 0.001"
    return f"p = {p:.3f}" if p < 0.01 else f"p = {p:.2f}"


def fmt_pct(ratio: float) -> str:
    """
    Format a relative change as a signed whole percent.

    Parameters
    ----------
    ratio : float
        Relative change, e.g. ``-0.2956`` for 29.56 % lower.

    Returns
    -------
    str
        For example ``−30%``.

    Examples
    --------
    >>> fmt_pct(0.041)
    '+4%'
    """
    return _signed_int(ratio * 100) + "%"


def _signed_int(x: float) -> str:
    n = math.floor(abs(x) + 0.5)
    if n == 0:
        return "0"
    return ("+" if x > 0 else MINUS) + str(n)


def _p_value(p: float) -> str:
    if p < 0.001:
        return "<0.001"
    return f"{p:.3f}" if p < 0.01 else f"{p:.2f}"


def percentile_of(ref: str) -> str | None:
    """
    Return the percentile named in a metric reference, if any.

    Parameters
    ----------
    ref : str
        Metric reference such as ``latency/p95`` or ``p99_ms``.

    Returns
    -------
    str or None
        For example ``p95``; the last match wins; ``None`` if there is none.

    Examples
    --------
    >>> percentile_of("latency/p95")
    'p95'
    >>> percentile_of("top1/value") is None
    True
    """
    found = _PERCENTILE.findall(ref)
    return f"p{found[-1]}" if found else None


# intervals from seed values ------------------------------------------------------
def welch_interval(
    a: Sequence[float], b: Sequence[float], log: bool = False
) -> tuple[float, float | None, float | None] | None:
    """
    Difference of means ``a − b`` with a Welch 95% interval over seed values.

    Parameters
    ----------
    a, b : sequence of float
        Seed (or repeat) values of the two groups.
    log : bool
        Compare ``log`` values and return relative changes ``exp(d) − 1``.

    Returns
    -------
    tuple or None
        ``(estimate, lo, hi)``; ``lo``/``hi`` are None when either group has
        fewer than 2 values. None when a group is empty, or ``log`` is set and
        a value is not positive. The t critical value uses the Welch degrees of
        freedom rounded down (conservative).
    """
    if not a or not b or (log and min(*a, *b) <= 0):
        return None
    xa = [math.log(v) for v in a] if log else list(a)
    xb = [math.log(v) for v in b] if log else list(b)
    d = statistics.fmean(xa) - statistics.fmean(xb)

    def out(x: float) -> float:
        return math.exp(x) - 1 if log else x

    if len(xa) < 2 or len(xb) < 2:
        return out(d), None, None
    va = statistics.variance(xa) / len(xa)
    vb = statistics.variance(xb) / len(xb)
    se = math.sqrt(va + vb)
    if se == 0:
        return out(d), out(d), out(d)
    df = (va + vb) ** 2 / (va**2 / (len(xa) - 1) + vb**2 / (len(xb) - 1))
    half = t_critical(max(1, math.floor(df + 1e-9))) * se
    return out(d), out(d - half), out(d + half)
