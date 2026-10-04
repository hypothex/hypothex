"""Bounded copies of metric histories: LTTB thinning, in one pass over any number of points."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from hypothex.core.records import MetricPoint

MAX_POINTS_PER_METRIC = 1000
"""Most points per metric name the index keeps of a run, and any read of a live run's file."""
_MIN_LIMIT = 5
"""Room for the first, last, lowest and highest point plus one more."""


def lttb(xs: Sequence[float], ys: Sequence[float], limit: int) -> list[int]:
    """
    Indices of at most ``limit`` points that keep a line's shape (LTTB).

    Largest-Triangle-Three-Buckets: the first and last points are always kept.
    The points between them are cut into ``limit - 2`` buckets in order; from
    each bucket the point that makes the largest triangle with the point kept
    before it and the mean of the next bucket is kept, so peaks such as a loss
    spike survive the thinning.

    Parameters
    ----------
    xs : sequence of float
        x of each point, in drawing order.
    ys : sequence of float
        y of each point.
    limit : int
        Most points to keep; a series that is not longer is kept whole, and a
        limit below 3 keeps every point.

    Returns
    -------
    list of int
        Increasing indices into ``xs`` / ``ys``.

    Examples
    --------
    >>> lttb([0, 1, 2, 3, 4], [0, 0, 9, 0, 0], 3)
    [0, 2, 4]
    >>> lttb([0, 1], [5, 6], 3)
    [0, 1]
    """
    n = len(xs)
    if n <= limit or limit < 3:
        return list(range(n))
    out = [0]
    size = (n - 2) / (limit - 2)
    kept = 0
    for b in range(limit - 2):
        start, end = int(b * size) + 1, int((b + 1) * size) + 1
        nxt_start, nxt_end = end, min(int((b + 2) * size) + 1, n)
        if nxt_start >= nxt_end:
            nxt_start, nxt_end = n - 1, n
        # mean of the next bucket: values near the float limit make sum() inf
        # (a poor pick for absurd data), where math.fsum would raise
        k = nxt_end - nxt_start
        mx, my = sum(xs[nxt_start:nxt_end]) / k, sum(ys[nxt_start:nxt_end]) / k
        ax, ay = xs[kept], ys[kept]
        dx, dy = ax - mx, my - ay
        best, kept = -1.0, start
        for j in range(start, end):
            area = abs(dx * (ys[j] - ay) - (ax - xs[j]) * dy)
            if area > best:
                best, kept = area, j
        out.append(kept)
    out.append(n - 1)
    return out


def _thin_series(series: list[MetricPoint], limit: int) -> list[MetricPoint]:
    """
    At most ``limit`` points of one name's series, ordered by step.

    The first and last step and the lowest and highest value are always kept;
    ``lttb`` picks the rest.
    """
    series.sort(key=lambda p: p.step)
    n = len(series)
    if n <= limit:
        return series
    xs, ys = [p.step for p in series], [p.value for p in series]
    extremes = {ys.index(min(ys)), ys.index(max(ys))}
    kept = set(lttb(xs, ys, limit))
    if not extremes <= kept:  # make room for them
        kept = set(lttb(xs, ys, limit - len(extremes - kept))) | extremes
    return [series[i] for i in sorted(kept)]


class HistoryThinner:
    """
    Keep at most ``limit`` points per metric name of a history read one point at a time.

    Each name holds at most ``2 * limit`` points: when it reaches that, its points
    are thinned to ``limit`` (``_thin_series``) and reading goes on. Thinning
    always keeps the first and last step and the lowest and highest value seen
    so far, so those of the whole history survive, in any file order.

    Parameters
    ----------
    limit : int
        Most points kept per name, at least 5.

    Raises
    ------
    ValueError
        If ``limit`` is below 5.

    Examples
    --------
    >>> thinner = HistoryThinner(limit=5)
    >>> for s in range(100):
    ...     thinner.add(MetricPoint(name="loss", step=s, value=9.0 if s == 37 else 1.0))
    >>> 37 in [p.step for p in thinner.points()]
    True
    """

    def __init__(self, limit: int = MAX_POINTS_PER_METRIC) -> None:
        if limit < _MIN_LIMIT:
            raise ValueError(f"limit must be at least {_MIN_LIMIT}, not {limit}")
        self.limit = limit
        self._series: dict[str, list[MetricPoint]] = {}

    def add(self, point: MetricPoint) -> None:
        """
        Take one point.

        Parameters
        ----------
        point : MetricPoint
            The next point read, in any step order.
        """
        series = self._series.setdefault(point.name, [])
        series.append(point)
        if len(series) >= 2 * self.limit:
            self._series[point.name] = _thin_series(series, self.limit)

    def held(self) -> int:
        """
        Most points held for one name now (at most ``2 * limit``).

        Returns
        -------
        int
            The length of the longest held series.
        """
        return max((len(s) for s in self._series.values()), default=0)

    def points(self) -> list[MetricPoint]:
        """
        The kept points: at most ``limit`` per name.

        Returns
        -------
        list of MetricPoint
            Ordered by name then step.
        """
        out: list[MetricPoint] = []
        for name in sorted(self._series):
            out.extend(_thin_series(self._series[name], self.limit))
        return out


def thin_history(
    points: Iterable[MetricPoint], limit: int = MAX_POINTS_PER_METRIC
) -> list[MetricPoint]:
    """
    At most ``limit`` points per metric name, as ``HistoryThinner`` keeps them.

    Parameters
    ----------
    points : iterable of MetricPoint
        A run's history, in any order.
    limit : int
        Most points to keep per name, at least 5.

    Returns
    -------
    list of MetricPoint
        The kept points, ordered by name then step.

    Examples
    --------
    >>> pts = [MetricPoint(name="loss", step=s, value=9.0 if s == 5 else 1.0) for s in range(10)]
    >>> [p.step for p in thin_history(pts, 5)]
    [0, 2, 5, 6, 9]
    """
    thinner = HistoryThinner(limit)
    for point in points:
        thinner.add(point)
    return thinner.points()
