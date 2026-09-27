"""One-line findings and stat strips generated from leaderboard data."""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from hypothex.core.seeds import Stats, t_critical
from hypothex.core.stats import Z95

if TYPE_CHECKING:
    from hypothex.core.leaderboard import Leaderboard, LeaderboardRow

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


def paired_gain_interval(
    gain: float, fixed: int, broken: int, n_shared: int
) -> tuple[float, float] | None:
    """
    95% interval of a gain from paired binary outcomes on shared examples.

    With ``d = (fixed - broken) / n`` and ``var = (fixed + broken) / n - d**2``
    (the variance of the per-example difference in ``{-1, 0, 1}``), the interval
    is ``gain ± Z95 * sqrt(var / n)``, where ``n`` is the number of examples both
    groups were scored on. Using either group's own example count instead
    understates the width whenever the test sets only partly overlap.

    Parameters
    ----------
    gain : float
        Best mean minus reference mean (the headline's number).
    fixed, broken : int
        Discordant shared examples in favour of and against the best group.
    n_shared : int
        Examples scored for both groups.

    Returns
    -------
    tuple of (float, float) or None
        Lower and upper bound; None when ``n_shared <= 0``.

    Examples
    --------
    >>> lo, hi = paired_gain_interval(0.3, 3, 0, 10)
    >>> round(lo, 3), round(hi, 3)
    (0.016, 0.584)
    """
    if n_shared <= 0:
        return None
    mean_d = (fixed - broken) / n_shared
    var = max((fixed + broken) / n_shared - mean_d**2, 0.0)
    half = Z95 * math.sqrt(var / n_shared)
    return gain - half, gain + half


def _gain_interval(
    best: LeaderboardRow,
    first: LeaderboardRow,
    primary: str,
    paired: tuple[float, float] | None,
) -> tuple[float, float] | None:
    """The paired interval when given, else a Welch interval over seed values."""
    if paired is not None:
        return paired
    w = welch_interval(best.seed_values.get(primary, []), first.seed_values.get(primary, []))
    if w is None or w[1] is None or w[2] is None:
        return None
    return w[1], w[2]


# task headline ---------------------------------------------------------------------
def _scored(board: Leaderboard) -> list[LeaderboardRow]:
    return [r for r in board.rows if r.primary is not None]


def _find(rows: list[LeaderboardRow], group_id: str | None) -> LeaderboardRow | None:
    return next((r for r in rows if r.group_id == group_id), None)


def _mean(row: LeaderboardRow) -> float:
    assert row.primary is not None
    return row.primary.mean


def task_headline(
    board: Leaderboard,
    *,
    reference: str | None = None,
    gain_interval: tuple[float, float] | None = None,
) -> str:
    """
    Return a task's one-line finding.

    Parameters
    ----------
    board : Leaderboard
        The task's leaderboard (rows ranked best first).
    reference : str, optional
        Group id to compare against: the baseline for ``system_bench``, the
        first version for ``agent_iteration``. ``build_leaderboard`` passes it.
    gain_interval : tuple of (float, float), optional
        ``agent_iteration`` only: the paired interval of the gain over the
        first version (``paired_gain_interval`` on the shared examples, which
        ``build_leaderboard`` computes). Without it the bracket is a Welch
        interval over seed values, or absent.

    Returns
    -------
    str
        ``generic``/``training``/``agent_eval``: ``"SVM +0.037 over rf, p = 0.15"``;
        ``system_bench``: ``"<best> p95 −30% vs baseline [−34, −24]"``;
        ``agent_iteration``: ``"v9 0.663, +0.263 over v1 [0.206, 0.321]"``;
        ``"No scored runs yet"`` without scored rows.
    """
    rows = _scored(board)
    if not rows:
        return NO_RUNS
    best = rows[0]
    ref = _find(rows, reference)
    if board.kind == "system_bench":
        return _bench_headline(board, best, ref)
    if board.kind == "agent_iteration":
        head = f"{best.label} {fmt_value(_mean(best))}"
        if ref is None or ref.group_id == best.group_id:
            return head
        text = f"{head}, {fmt_delta(_mean(best) - _mean(ref))} over {ref.label}"
        ci = _gain_interval(best, ref, board.primary, gain_interval)
        if ci is not None:
            text += f" [{fmt_value(ci[0])}, {fmt_value(ci[1])}]"
        return text
    if len(rows) == 1:
        return f"{best.label} {fmt_value(_mean(best))}"
    runner = rows[1]
    text = f"{best.label} {fmt_delta(_mean(best) - _mean(runner))} over {runner.label}"
    if runner.vs_best is not None and runner.vs_best.p is not None:
        text += f", {fmt_p(runner.vs_best.p)}"
    return text


def _bench_headline(board: Leaderboard, best: LeaderboardRow, base: LeaderboardRow | None) -> str:
    pct = percentile_of(board.primary) or board.primary.split("/")[0]
    plain = f"{best.label} {pct} {fmt_value(_mean(best))}"
    if base is None or base.group_id == best.group_id:
        return plain
    change = welch_interval(
        best.seed_values.get(board.primary, []), base.seed_values.get(board.primary, []), log=True
    )
    if change is None:
        return plain
    r, lo, hi = change
    text = f"{best.label} {pct} {fmt_pct(r)} vs baseline"
    if lo is not None and hi is not None:
        text += f" [{_signed_int(lo * 100)}, {_signed_int(hi * 100)}]"
    return text


# stat strip ------------------------------------------------------------------------
def _stat(label: str, value: str, tooltip: str, unit: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit, "tooltip": tooltip}


def _seed_sigma(row: LeaderboardRow, word: str = "seed") -> dict[str, Any]:
    assert row.primary is not None
    if row.n < 2:
        return _stat(f"{word} σ", "—", f"{row.label}: single {word}")
    if row.identical_seeds:
        return _stat(f"{word} σ", f"◇×{row.n}", f"{row.label}: all {row.n} {word}s gave one score")
    std = row.primary.std
    text = f"{std:.4f}" if std < 1 else fmt_value(std)
    return _stat(f"{word} σ", text, f"Std of {row.label} over {row.n} {word}s")


def _p_stat(best: LeaderboardRow, other: LeaderboardRow) -> dict[str, Any] | None:
    vs = other.vs_best
    if vs is None or vs.p is None or vs.test is None:
        return None
    if vs.test == "welch":
        tip = f"Welch t-test over seed values, {best.n} vs {other.n} seeds"
        return _stat("p, seeds", _p_value(vs.p), tip)
    if vs.test == "sign":
        tip = f"Exact two-sided sign test on {(vs.fixed or 0) + (vs.broken or 0)} changed examples"
    else:
        tip = "Paired bootstrap of the mean difference over examples, 1,000 resamples"
    return _stat("paired p", _p_value(vs.p), tip)


def task_stat_strip(board: Leaderboard, *, reference: str | None = None) -> list[dict[str, Any]]:
    """
    Return the stat strip for a task: ``{label, value, unit, tooltip}`` entries.

    Parameters
    ----------
    board : Leaderboard
        The task's leaderboard (rows ranked best first).
    reference : str, optional
        Group id of the baseline (``system_bench``) or first version
        (``agent_iteration``).

    Returns
    -------
    list of dict
        Entries in display order; empty without scored rows. ``value`` is the
        full display string; ``unit`` is a small suffix such as ``ms``.
    """
    rows = _scored(board)
    if not rows:
        return []
    best, ref = rows[0], _find(rows, reference)
    if board.kind == "system_bench":
        return _bench_strip(board, best, ref)
    if board.kind == "agent_iteration":
        return _iteration_strip(board, best, ref)
    return _compare_strip(board, best, rows[1] if len(rows) > 1 else None)


def _compare_strip(
    board: Leaderboard, best: LeaderboardRow, runner: LeaderboardRow | None
) -> list[dict[str, Any]]:
    name = board.primary.removesuffix("/value")
    out: list[dict[str, Any]] = []
    vs = runner.vs_best if runner is not None else None
    if runner is not None:
        tip = f"{best.label} minus {runner.label}, mean {name}"
        out.append(_stat(f"Δ {name}", fmt_delta(_mean(best) - _mean(runner)), tip))
        p = _p_stat(best, runner)
        if p is not None:
            out.append(p)
        if vs is not None and vs.fixed is not None and vs.broken is not None:
            tip = f"Examples {best.label} gets right and {runner.label} gets wrong, and the reverse"
            out.append(_stat("fixed / broken", f"{vs.fixed} / {vs.broken}", tip))
    if best.test_interval is not None:
        ti = best.test_interval
        method = "Wilson" if ti.method == "wilson" else "bootstrap"
        out.append(
            _stat(
                f"{best.label} 95% CI",
                f"{fmt_value(ti.lo)}–{fmt_value(ti.hi)}",
                f"Test-set 95% CI ({method}, n = {ti.n})",
            )
        )
    out.append(_seed_sigma(best))
    if board.kind == "agent_eval" and best.usage is not None:
        attempts = best.n * (best.test_interval.n if best.test_interval else 1)
        tip = f"{best.label}: ${best.usage.usd:.2f} over {attempts} attempts"
        out.append(_stat("$ / attempt", f"${best.usage.usd / attempts:.2f}", tip))
    if vs is not None and vs.examples_needed is not None:
        tip = "Test examples needed at the same flip rate to reach p < 0.05"
        out.append(_stat("n for p < 0.05", f"≈{vs.examples_needed}", tip))
    if board.kind == "training":
        out.append(_stat("runs", str(sum(r.n for r in board.rows)), "Finished, scored runs"))
    return out


def _iteration_strip(
    board: Leaderboard, best: LeaderboardRow, first: LeaderboardRow | None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if first is not None and first.group_id != best.group_id:
        vs = first.vs_best
        if vs is not None and vs.fixed is not None and vs.broken is not None:
            tip = f"Examples {first.label} missed and {best.label} solved, and the reverse"
            out.append(_stat(f"fixed / broken vs {first.label}", f"{vs.fixed} / {vs.broken}", tip))
        p = _p_stat(best, first)
        if p is not None:
            out.append(p)
    out.append(_seed_sigma(best))
    if best.usage is not None and best.test_interval is not None:
        solved = _mean(best) * best.test_interval.n * best.n
        if solved > 0:
            tip = f"{best.label}: ${best.usage.usd:.2f} over {solved:g} solved examples"
            out.append(_stat("$ / solved", f"${best.usage.usd / solved:.2f}", tip))
    out.append(_stat("versions", str(len(board.rows)), "Seed groups in this task"))
    return out


def _bench_strip(
    board: Leaderboard, best: LeaderboardRow, base: LeaderboardRow | None
) -> list[dict[str, Any]]:
    metric = board.primary.split("/")[0]
    pct = percentile_of(board.primary) or metric
    unit = "ms" if "ms" in board.primary else ""
    out: list[dict[str, Any]] = []
    if base is not None and base.group_id != best.group_id:
        value = f"{fmt_value(_mean(best))} vs {fmt_value(_mean(base))}"
        tip = f"{best.label} vs baseline {base.label}, mean of repeats"
        out.append(_stat(pct, value, tip, unit))
        keys = [
            k
            for k in best.seed_values
            if k.split("/")[0] == metric and percentile_of(k) and k in base.seed_values
        ]
        for key in sorted(keys, key=lambda k: float(str(percentile_of(k))[1:])):
            change = welch_interval(best.seed_values[key], base.seed_values[key], log=True)
            if change is None:
                continue
            r, lo, hi = change
            tip = f"{percentile_of(key)} change vs baseline"
            if lo is not None and hi is not None:
                tip += f", 95% CI {_signed_int(lo * 100)} to {_signed_int(hi * 100)}%"
            out.append(_stat(f"Δ {percentile_of(key)}", fmt_pct(r), tip))
    else:
        out.append(_stat(pct, fmt_value(_mean(best)), f"{best.label}, mean of repeats", unit))
    out.append(_stat("repeats", str(best.n), f"Repeats of {best.label}"))
    out.append(_seed_sigma(best, word="repeat"))
    return out


# overview headline --------------------------------------------------------------------
class IdeaLike(Protocol):
    """What ``overview_headline`` reads from an idea row (``overview.IdeaRow``)."""

    @property
    def project(self) -> str: ...
    @property
    def task(self) -> str | None: ...
    @property
    def label(self) -> str: ...
    @property
    def primary(self) -> Stats | None: ...
    @property
    def created_at(self) -> datetime: ...


class ProjectLike(Protocol):
    """What ``overview_headline`` reads from a project row (``overview.ProjectRow``)."""

    @property
    def project(self) -> str: ...
    @property
    def task(self) -> str | None: ...
    @property
    def best(self) -> float | None: ...


class SummaryLike(Protocol):
    """What ``overview_headline`` reads from ``overview.OverviewSummary``."""

    @property
    def running(self) -> Sequence[object]: ...
    @property
    def ideas(self) -> Sequence[IdeaLike]: ...
    @property
    def projects(self) -> Sequence[ProjectLike]: ...


def overview_headline(summary: SummaryLike, *, board: Leaderboard | None = None) -> str:
    """
    Return the Overview page's one-line status.

    Parameters
    ----------
    summary : OverviewSummary
        The overview (any object with ``running``, ``ideas``, ``projects``).
    board : Leaderboard, optional
        Leaderboard of the task to lead with. With it, the line carries the
        paired p-value; without it, the task of the newest scored idea is used.

    Returns
    -------
    str
        For example ``"Idle. SVM leads toy-test by 0.037, p = 0.15"`` or
        ``"2 running. SVM leads toy-test by 0.037"``.
    """
    n = len(summary.running)
    prefix = "Idle." if n == 0 else f"{n} running."
    lead = _board_lead(board) if board is not None else _summary_lead(summary)
    return f"{prefix} {lead}"


def _board_lead(board: Leaderboard) -> str:
    rows = _scored(board)
    if not rows:
        return NO_RUNS
    best = rows[0]
    if len(rows) == 1:
        return f"{best.label} leads {board.task} at {fmt_value(_mean(best))}"
    runner = rows[1]
    text = f"{best.label} leads {board.task} by {fmt_value(abs(_mean(best) - _mean(runner)))}"
    if runner.vs_best is not None and runner.vs_best.p is not None:
        text += f", {fmt_p(runner.vs_best.p)}"
    return text


def _summary_lead(summary: SummaryLike) -> str:
    scored = [i for i in summary.ideas if i.primary is not None and i.task is not None]
    if not scored:
        return NO_RUNS
    focus = max(scored, key=lambda i: i.created_at)
    same = [i for i in scored if (i.project, i.task) == (focus.project, focus.task)]
    best = next(
        (p.best for p in summary.projects if (p.project, p.task) == (focus.project, focus.task)),
        None,
    )
    task = str(focus.task)
    if best is None:
        return f"{task} has no best yet"
    leader = next((i for i in same if i.primary and math.isclose(i.primary.mean, best)), None)
    if leader is None:
        return f"{task} best {fmt_value(best)}"
    others = [i for i in same if i is not leader and i.primary is not None]
    if not others:
        return f"{leader.label} leads {task} at {fmt_value(best)}"
    gap = min(abs(best - i.primary.mean) for i in others if i.primary is not None)
    return f"{leader.label} leads {task} by {fmt_value(gap)}"
