"""Cross-project overview: timeline, recent ideas, running runs, failures, projects."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from hypothex.core import queries as q
from hypothex.core.config import TaskKind, parse_metric_key
from hypothex.core.context import Context
from hypothex.core.cost import cost_since, today_start
from hypothex.core.headlines import overview_headline
from hypothex.core.ids import utcnow
from hypothex.core.index import _IN_CHUNK, RunRow
from hypothex.core.leaderboard import (
    Leaderboard,
    LeaderboardRow,
    NoiseInterval,
    group_id_for,
    group_label,
)
from hypothex.core.naming import run_view_name
from hypothex.core.records import ACTIVE_STATUSES, MetricPoint, RunRecord, RunStatus
from hypothex.core.seeds import Stats
from hypothex.core.taskruns import derived_names, latest_scores

DEFAULT_WINDOW = timedelta(hours=24)
FAILED_STATUSES = frozenset({RunStatus.FAILED, RunStatus.LOST})
_SQL_SLACK = timedelta(days=1)
"""How far ``_recent_runs`` widens its SQL time bounds; exact filters run in Python."""
RECENT_RUNS = 12
"""Runs in ``OverviewSummary.recent``: the newest unarchived, non-queued runs of any age."""
BEST_HISTORY = 24
"""Most points in ``ProjectRow.best_history``."""
TREND_WINDOW = timedelta(days=7)
"""``ProjectRow.best_7d_ago`` is the best as it stood this long ago."""
PROGRESS_RUNS = 50
"""Most running runs whose latest primary metric value is read (``OverviewSummary.progress``)."""
METRIC_TAIL_BYTES = 64 * 1024
"""How much of the end of a live ``metrics.jsonl`` ``latest_point`` reads."""


class TimelineItem(BaseModel):
    """One run on the overview timeline."""

    run_id: str
    project: str
    task: str | None
    created_at: datetime
    created_by: str
    status: RunStatus
    archived: bool
    group_id: str | None
    is_best: bool
    label: str


class IdeaRow(BaseModel):
    """One seed group with at least one unarchived run in the window."""

    project: str
    task: str | None
    group_id: str
    label: str
    created_by: str
    created_at: datetime
    statuses: list[RunStatus]
    primary: Stats | None
    test_interval: NoiseInterval | None
    identical_seeds: bool
    best_band: NoiseInterval | None
    unit: str = ""
    """Display unit of the task's primary metric (``Leaderboard.unit``): ``ms``, ``$``."""


class FailureRow(BaseModel):
    """A failed or lost run, with where to read its error."""

    run_id: str
    label: str
    exit_code: int | None
    created_at: datetime
    stderr_path: str
    retried_ok: bool


class ProjectRow(BaseModel):
    """One task (or a project without tasks) with its run count and best value."""

    project: str
    task: str | None
    runs: int
    """Unarchived runs in any state, as ``TaskSummary.n_runs`` (the nav and task header)."""
    best: float | None
    kind: TaskKind
    unit: str = ""
    """Display unit of the task's primary metric (``Leaderboard.unit``); ``""`` without one."""
    primary: str = ""
    """The task's primary ``metric/key`` (``Leaderboard.primary``)."""
    higher_is_better: bool = True
    best_7d_ago: float | None = None
    """The best config mean among configs whose time is more than 7 days ago."""
    best_history: list[float] = Field(default_factory=list)
    """The best so far after each scored config, in config time order; the last 24."""
    running: int = 0
    """Unarchived runs of the task that are running now."""
    queued: int = 0
    """Unarchived runs of the task that are queued now."""


class RecentRun(BaseModel):
    """One of the newest runs, for Home's Recent runs table."""

    run_id: str
    project: str
    task: str | None
    name: str
    """The run view name (``naming.run_view_name``), as in ``OverviewSummary.names``."""
    status: RunStatus
    end_reason: str | None
    exit_code: int | None
    created_at: datetime
    ended_at: datetime | None = None
    created_by: str
    hypothesis: str
    primary: float | None
    """The run's primary score at the task's current metric version."""
    delta_best: float | None
    """``primary`` minus the best config mean of the task."""


class RunProgress(BaseModel):
    """
    How far a running run is, for Home's Running now table.

    ``progress`` and ``eta_seconds`` are always None: runs report no total yet.
    ``metric``, ``step`` and ``value`` are the newest logged point of the task's
    primary metric (``latest_point``), or None when the end of the file has none.
    """

    progress: float | None = None
    metric: str | None = None
    step: int | None = None
    value: float | None = None
    eta_seconds: float | None = None


class OverviewSummary(BaseModel):
    """Everything the Overview screen shows."""

    headline: str
    counts: dict[str, int]
    timeline: list[TimelineItem]
    ideas: list[IdeaRow]
    running: list[RunRecord]
    failures: list[FailureRow]
    projects: list[ProjectRow]
    cost_usd: float = 0.0
    """Sum of ``cost.total_usd`` of the runs created in the window (spec 8A.7)."""
    cost_today_usd: float = 0.0
    """Sum of ``cost.total_usd`` of the runs that ended since local midnight."""
    recent: list[RecentRun] = Field(default_factory=list)
    """The ``RECENT_RUNS`` newest unarchived, non-queued runs of any age, newest first."""
    names: dict[str, str] = Field(default_factory=dict)
    """Run view name of every run in ``running``, ``failures`` and ``recent``."""
    progress: dict[str, RunProgress] = Field(default_factory=dict)
    """Per running run id (at most ``PROGRESS_RUNS``): its latest primary metric point."""


def _short_label(record: RunRecord) -> str:
    """
    Return a short name for a run whose group is not on any leaderboard.

    Parameters
    ----------
    record : RunRecord
        Any run.

    Returns
    -------
    str
        ``leaderboard.group_label`` of the run: the first clause of the
        hypothesis, else the first tag, else ``group <group id>``. For example
        ``"SVM, tuned C"`` gives ``"SVM"``; ``"Opus 5.5 with tools"`` stays whole.
    """
    return group_label(record.hypothesis, record.tags, group_id_for(record))


def _as_utc(moment: datetime) -> datetime:
    """
    Treat a naive datetime as UTC.

    Parameters
    ----------
    moment : datetime
        Aware or naive datetime.

    Returns
    -------
    datetime
        An aware datetime.
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _recent_runs(ctx: Context, start: datetime, today: datetime) -> list[RunRecord]:
    """
    Read the runs the overview can show, in one query, newest first.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    start : datetime
        Aware start of the window.
    today : datetime
        Aware start of today (``cost.today_start``).

    Returns
    -------
    list of RunRecord
        Every run created at or after ``start`` (archived too), every queued
        or running run, and every run that ended at or after ``today``, plus
        some runs just outside these bounds: the SQL bounds are widened by
        ``_SQL_SLACK``, so a time zone offset in the stored text never drops a
        run. Callers filter exactly.
    """
    floor = (start - _SQL_SLACK).astimezone(UTC).isoformat()
    ended_floor = (today - _SQL_SLACK).astimezone(UTC).isoformat()
    active = [s.value for s in ACTIVE_STATUSES]
    ended = func.json_extract(RunRow.record_json, "$.ended_at")
    stmt = (
        select(RunRow.record_json)
        .where(or_(RunRow.created_at >= floor, RunRow.status.in_(active), ended >= ended_floor))
        .order_by(RunRow.created_at.desc(), RunRow.run_id.desc())
    )
    with Session(ctx.index.engine) as session:
        return [RunRecord.model_validate_json(j) for j in session.scalars(stmt)]


def _run_counts(ctx: Context) -> dict[tuple[str, str | None], int]:
    """
    Count the unarchived runs of every task, in any state, with one ``GROUP BY``.

    The same count as ``TaskSummary.n_runs`` (the nav and the task header).

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.

    Returns
    -------
    dict
        Count per ``(project, task)``; ``task`` is ``None`` for runs without
        one. Pairs without such runs are left out.
    """
    stmt = (
        select(RunRow.project, RunRow.task, func.count())
        .where(RunRow.archived.is_(False))
        .group_by(RunRow.project, RunRow.task)
    )
    with Session(ctx.index.engine) as session:
        return {(project, task): int(n) for project, task, n in session.execute(stmt)}


def _newest_runs(ctx: Context, limit: int = RECENT_RUNS) -> list[RunRecord]:
    """
    Read the newest unarchived, non-queued runs of any age, in one query.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    limit : int
        Most runs.

    Returns
    -------
    list of RunRecord
        Newest first (``created_at``, then ``run_id``).
    """
    stmt = (
        select(RunRow.record_json)
        .where(RunRow.archived.is_(False), RunRow.status != RunStatus.QUEUED.value)
        .order_by(RunRow.created_at.desc(), RunRow.run_id.desc())
        .limit(limit)
    )
    with Session(ctx.index.engine) as session:
        return [RunRecord.model_validate_json(j) for j in session.scalars(stmt)]


def _created_times(ctx: Context, run_ids: Iterable[str]) -> dict[str, datetime]:
    """
    Read the creation time of many runs without parsing their records.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_ids : iterable of str
        Run ids; ``_IN_CHUNK`` per statement.

    Returns
    -------
    dict of str to datetime
        Aware creation time per indexed run id.
    """
    ids = list(dict.fromkeys(run_ids))
    out: dict[str, datetime] = {}
    with Session(ctx.index.engine) as session:
        for start in range(0, len(ids), _IN_CHUNK):
            chunk = ids[start : start + _IN_CHUNK]
            stmt = select(RunRow.run_id, RunRow.created_at).where(RunRow.run_id.in_(chunk))
            for run_id, created in session.execute(stmt):
                out[run_id] = _as_utc(datetime.fromisoformat(created))
    return out


def best_trend(
    configs: Iterable[tuple[datetime, float]], higher_is_better: bool, cutoff: datetime
) -> tuple[list[float], float | None]:
    """
    Return how a task's best config mean grew over time.

    Parameters
    ----------
    configs : iterable of tuple of (datetime, float)
        ``(config time, config mean)`` per scored config; the config time is
        the newest ``created_at`` among its runs.
    higher_is_better : bool
        Direction of the primary metric.
    cutoff : datetime
        ``best_7d_ago`` counts only configs older than this.

    Returns
    -------
    history : list of float
        The best so far after each config, in time order; the last ``BEST_HISTORY``.
    best_before : float or None
        The best so far among configs older than ``cutoff``; None when there is none.

    Examples
    --------
    >>> t = [datetime(2026, 10, d, tzinfo=UTC) for d in (1, 2, 3)]
    >>> best_trend(zip(t, [0.5, 0.4, 0.7]), True, datetime(2026, 10, 2, 12, tzinfo=UTC))
    ([0.5, 0.5, 0.7], 0.5)
    >>> best_trend(zip(t, [9.0, 7.0, 8.0]), False, t[0])
    ([9.0, 7.0, 7.0], None)
    """
    history: list[float] = []
    best: float | None = None
    best_before: float | None = None
    for moment, mean in sorted(configs):
        if best is None or (mean > best if higher_is_better else mean < best):
            best = mean
        history.append(best)
        if moment < cutoff:
            best_before = best
    return history[-BEST_HISTORY:], best_before


def latest_point(
    path: Path, metric: str, tail_bytes: int = METRIC_TAIL_BYTES
) -> MetricPoint | None:
    """
    Return the newest point of a metric from the end of a ``metrics.jsonl``.

    Only the last ``tail_bytes`` of the file are read, so a live run's file of
    any size costs one bounded read. A row named ``metric`` wins; else the
    newest row whose name ends in ``/<metric>`` (``val/accuracy`` for
    ``accuracy``). Rows that are not valid metric points are skipped.

    Parameters
    ----------
    path : Path
        The run's ``metrics.jsonl``.
    metric : str
        Metric name, e.g. the task's primary metric ``accuracy``.
    tail_bytes : int
        How much of the end of the file to read.

    Returns
    -------
    MetricPoint or None
        None when the file is missing or its end has no such row.

    Examples
    --------
    >>> latest_point(Path("/nonexistent/metrics.jsonl"), "accuracy") is None
    True
    """
    try:
        with path.open("rb") as fh:
            size = fh.seek(0, 2)
            start = max(size - tail_bytes - 1, 0)  # one byte more: is the first line whole?
            fh.seek(start)
            data = fh.read(size - start)  # a live file may grow meanwhile
    except OSError:
        return None
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]  # the line that the tail cut (empty when the cut is at a line end)
    suffix: MetricPoint | None = None
    for line in reversed(lines):
        try:
            point = MetricPoint.model_validate(json.loads(line))
        except (ValueError, ValidationError):
            continue
        if point.name == metric:
            return point
        if suffix is None and point.name.endswith(f"/{metric}"):
            suffix = point
    return suffix


def _boards(
    ctx: Context, examples_for: set[tuple[str, str]]
) -> tuple[dict[tuple[str, str], Leaderboard], list[ProjectRow]]:
    """
    Get every task's leaderboard (cached) and build the projects table.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    examples_for : set of tuple of (str, str)
        ``(project, task)`` pairs whose boards need the per-example scores
        (test-set intervals and paired p-values): the tasks of the ideas.
        Other boards skip those file reads; their ranking, labels, best and
        unit are the same either way.

    Returns
    -------
    boards : dict
        Leaderboard keyed by ``(project, task)``.
    projects : list of ProjectRow
        Sorted by project, then task; projects without tasks get one row
        with ``task=None``. ``runs`` counts unarchived runs in any state.
    """
    counts = _run_counts(ctx)
    boards: dict[tuple[str, str], Leaderboard] = {}
    rows: list[ProjectRow] = []
    for entry in q.list_projects(ctx):
        if not entry.config.tasks:
            runs = sum(n for (project, _), n in counts.items() if project == entry.project)
            rows.append(
                ProjectRow(project=entry.project, task=None, runs=runs, best=None, kind="generic")
            )
            continue
        for task in sorted(entry.config.tasks):
            key = (entry.project, task)
            board = q._board(ctx, entry, task, None, examples=key in examples_for)
            boards[key] = board
            best = board.rows[0].primary if board.rows else None
            rows.append(
                ProjectRow(
                    project=entry.project,
                    task=task,
                    runs=counts.get(key, 0),
                    best=best.mean if best is not None else None,
                    kind=entry.config.tasks[task].kind,
                    unit=board.unit,
                    primary=board.primary,
                    higher_is_better=board.higher_is_better,
                )
            )
    times = _created_times(
        ctx, (rid for board in boards.values() for row in board.rows for rid in row.run_ids)
    )
    cutoff = utcnow() - TREND_WINDOW
    for row in rows:
        board = boards.get((row.project, row.task)) if row.task is not None else None
        if board is None:
            continue
        configs = [
            (max(times[rid] for rid in r.run_ids if rid in times), r.primary.mean)
            for r in board.rows
            if r.primary is not None and any(rid in times for rid in r.run_ids)
        ]
        row.best_history, row.best_7d_ago = best_trend(configs, board.higher_is_better, cutoff)
    return boards, rows


def _view_names(ctx: Context, runs: Iterable[RunRecord]) -> dict[str, str]:
    """
    Return the run view name of each run (``naming.run_view_name``).

    Names derive over every run of the run's task (archived ones too),
    memoized per task until the index changes (``taskruns.derived_names``); a
    run without a task gets ``_short_label``.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    runs : iterable of RunRecord
        The runs to name.

    Returns
    -------
    dict of str to str
        Name per run id.
    """
    wanted = {r.run_id: r for r in runs}
    derived: dict[str, str] = {}
    for project, task in sorted({(r.project, r.task) for r in wanted.values() if r.task}):
        derived.update(derived_names(ctx, project, task))
    return {
        rid: run_view_name(r, derived) if r.task else (r.name or _short_label(r))
        for rid, r in wanted.items()
    }


def _progress(
    ctx: Context, running: list[RunRecord], boards: dict[tuple[str, str], Leaderboard]
) -> dict[str, RunProgress]:
    """
    Return the latest primary metric point of each running run.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    running : list of RunRecord
        Queued and running runs, newest first; queued ones are skipped.
    boards : dict
        Leaderboards keyed by ``(project, task)``, for the primary metric.

    Returns
    -------
    dict of str to RunProgress
        Per running run id, at most ``PROGRESS_RUNS``; a run without a task
        or a logged point gets nulls.
    """
    out: dict[str, RunProgress] = {}
    live = [r for r in running if r.status == RunStatus.RUNNING][:PROGRESS_RUNS]
    for run in live:
        board = boards.get((run.project, run.task)) if run.task is not None else None
        point = None
        if board is not None:
            metric = parse_metric_key(board.primary)[0]
            point = latest_point(ctx.run_dir(run) / "metrics.jsonl", metric)
        out[run.run_id] = RunProgress(
            metric=point.name if point is not None else None,
            step=point.step if point is not None else None,
            value=point.value if point is not None else None,
        )
    return out


def _recent_rows(
    newest: list[RunRecord],
    ctx: Context,
    boards: dict[tuple[str, str], Leaderboard],
    names: dict[str, str],
) -> list[RecentRun]:
    """
    Build the Recent runs rows: primary score at the current version, gap to the best.

    Parameters
    ----------
    newest : list of RunRecord
        The newest runs (``_newest_runs``).
    ctx : Context
        Open Hypothex context.
    boards : dict
        Leaderboards keyed by ``(project, task)``.
    names : dict of str to str
        Run view name per run id; has every run of ``newest``.

    Returns
    -------
    list of RecentRun
        In the order of ``newest``.
    """
    scores = ctx.index.scores_for(r.run_id for r in newest)
    out: list[RecentRun] = []
    for run in newest:
        board = boards.get((run.project, run.task)) if run.task is not None else None
        primary = None
        delta = None
        if board is not None:
            primary = latest_scores(scores.get(run.run_id, []), board.metric_versions).get(
                board.primary
            )
            top = board.rows[0].primary if board.rows else None
            if primary is not None and top is not None:
                delta = primary - top.mean
        out.append(
            RecentRun(
                run_id=run.run_id,
                project=run.project,
                task=run.task,
                name=names[run.run_id],
                status=run.status,
                end_reason=run.end_reason,
                exit_code=run.exit_code,
                created_at=run.created_at,
                ended_at=run.ended_at,
                created_by=run.created_by,
                hypothesis=run.hypothesis,
                primary=primary,
                delta_best=delta,
            )
        )
    return out


def _retried_ok(failed: RunRecord, later: list[RunRecord]) -> bool:
    """
    Return whether a later finished run retried a failed one.

    A retry is a run created after the failure, in the same project and task,
    that finished and either has the failed run as ``parent``, is in the same
    seed group, or has the same non-empty hypothesis.

    Parameters
    ----------
    failed : RunRecord
        The failed or lost run.
    later : list of RunRecord
        Candidate runs (any order).

    Returns
    -------
    bool
    """
    gid = group_id_for(failed)
    for run in later:
        if run.status != RunStatus.FINISHED or run.created_at <= failed.created_at:
            continue
        if run.project != failed.project or run.task != failed.task:
            continue
        if (
            run.parent == failed.run_id
            or group_id_for(run) == gid
            or (failed.hypothesis and run.hypothesis == failed.hypothesis)
        ):
            return True
    return False


def build_overview(ctx: Context, since: datetime | None = None) -> OverviewSummary:
    """
    Summarise recent activity across all projects.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    since : datetime, optional
        Start of the window; default 24 hours ago. A naive datetime is read
        as UTC.

    Returns
    -------
    OverviewSummary
        ``timeline`` holds every run created in the window (archived ones too),
        oldest first. ``ideas`` holds one row per seed group with an unarchived
        run in the window, newest group first. ``running`` holds every queued or
        running run regardless of the window, newest first. ``failures`` holds
        failed and lost runs created in the window (archived too), newest first.
        ``counts`` has ``total``, one key per status, ``archived``, ``agent``,
        and ``human`` for runs in the window, except ``running`` and ``queued``,
        which count the current active runs. ``cost_usd`` sums the cost of runs in the
        window, ``cost_today_usd`` of runs that ended today. ``recent`` holds the
        ``RECENT_RUNS`` newest unarchived, non-queued runs of any age; ``names``
        the run view name of every run in ``running``, ``failures`` and
        ``recent``; ``progress`` the latest primary metric point of each running
        run. Project rows carry the task's primary, direction, best history,
        best 7 days ago, and running and queued counts.

    Examples
    --------
    >>> import pathlib, tempfile
    >>> summary = build_overview(Context.open(pathlib.Path(tempfile.mkdtemp())))
    >>> summary.counts["total"], summary.ideas
    (0, [])
    """
    start = _as_utc(since) if since is not None else utcnow() - DEFAULT_WINDOW
    today = today_start()
    recent = _recent_runs(ctx, start, today)
    window = sorted(
        (r for r in recent if r.created_at >= start), key=lambda r: (r.created_at, r.run_id)
    )
    ideas_in = {(r.project, r.task) for r in window if r.task is not None and not r.archived}
    boards, projects = _boards(ctx, ideas_in)
    row_of: dict[tuple[str, str, str], LeaderboardRow] = {}
    best_of: dict[tuple[str, str], LeaderboardRow] = {}
    for (project, task), board in boards.items():
        for row in board.rows:
            row_of[(project, task, row.group_id)] = row
        if board.rows and board.rows[0].primary is not None:
            best_of[(project, task)] = board.rows[0]

    def board_row(run: RunRecord) -> LeaderboardRow | None:
        if run.task is None:
            return None
        return row_of.get((run.project, run.task, group_id_for(run)))

    def label(run: RunRecord) -> str:
        row = board_row(run)
        return row.label if row is not None else _short_label(run)

    timeline: list[TimelineItem] = []
    for run in window:
        best = best_of.get((run.project, run.task)) if run.task is not None else None
        timeline.append(
            TimelineItem(
                run_id=run.run_id,
                project=run.project,
                task=run.task,
                created_at=run.created_at,
                created_by=run.created_by,
                status=run.status,
                archived=run.archived,
                group_id=group_id_for(run),
                is_best=best is not None and run.run_id in best.run_ids,
                label=label(run),
            )
        )

    groups: dict[tuple[str, str | None, str], list[RunRecord]] = {}
    for run in window:
        if not run.archived:
            groups.setdefault((run.project, run.task, group_id_for(run)), []).append(run)
    ideas: list[IdeaRow] = []
    for (project, task, gid), members in groups.items():
        row = board_row(members[0])
        best = best_of.get((project, task)) if task is not None else None
        task_board = boards.get((project, task)) if task is not None else None
        ideas.append(
            IdeaRow(
                project=project,
                task=task,
                group_id=gid,
                label=row.label if row is not None else _short_label(members[-1]),
                created_by=members[0].created_by,
                created_at=members[0].created_at,
                statuses=[m.status for m in members],
                primary=row.primary if row is not None else None,
                test_interval=row.test_interval if row is not None else None,
                identical_seeds=row.identical_seeds if row is not None else False,
                best_band=best.test_interval if best is not None else None,
                unit=task_board.unit if task_board is not None else "",
            )
        )
    ideas.sort(key=lambda i: (i.created_at, i.group_id), reverse=True)

    running = [r for r in recent if r.status in ACTIVE_STATUSES and not r.archived]
    failures = [
        FailureRow(
            run_id=run.run_id,
            label=label(run),
            exit_code=run.exit_code,
            created_at=run.created_at,
            stderr_path=str(ctx.run_dir(run) / "logs" / "stderr.log"),
            retried_ok=_retried_ok(run, window),
        )
        for run in reversed(window)
        if run.status in FAILED_STATUSES
    ]

    counts = {"total": len(window)}
    for status in RunStatus:
        counts[status.value] = sum(1 for r in window if r.status == status)
    counts["running"] = sum(1 for r in running if r.status == RunStatus.RUNNING)
    counts["queued"] = sum(1 for r in running if r.status == RunStatus.QUEUED)
    counts["archived"] = sum(1 for r in window if r.archived)
    counts["agent"] = sum(1 for r in window if r.created_by.startswith("agent"))
    counts["human"] = counts["total"] - counts["agent"]

    for row in projects:
        row.running = sum(
            1
            for r in running
            if (r.project, r.task) == (row.project, row.task) and r.status == RunStatus.RUNNING
        )
        row.queued = sum(
            1
            for r in running
            if (r.project, r.task) == (row.project, row.task) and r.status == RunStatus.QUEUED
        )
    newest = _newest_runs(ctx)
    failed = [r for r in window if r.status in FAILED_STATUSES]
    names = _view_names(ctx, [*running, *failed, *newest])

    cost_usd = sum(r.cost.total_usd for r in window if r.cost is not None)
    summary = OverviewSummary(
        headline="",
        counts=counts,
        timeline=timeline,
        ideas=ideas,
        running=running,
        failures=failures,
        projects=projects,
        cost_usd=round(cost_usd, 4),
        cost_today_usd=cost_since(recent, today),
        recent=_recent_rows(newest, ctx, boards, names),
        names=names,
        progress=_progress(ctx, running, boards),
    )
    summary.headline = overview_headline(summary, board=_focus_board(ideas, boards))
    return summary


def _focus_board(
    ideas: list[IdeaRow], boards: dict[tuple[str, str], Leaderboard]
) -> Leaderboard | None:
    """
    Return the leaderboard of the newest scored idea's task, for the headline.

    The focus rule matches ``headlines._summary_lead``; with the board the
    headline also carries the runner-up's p-value.

    Parameters
    ----------
    ideas : list of IdeaRow
        The overview's ideas.
    boards : dict
        Leaderboards keyed by ``(project, task)``.

    Returns
    -------
    Leaderboard or None
        ``None`` when no idea with a task has a primary score.
    """
    scored = [i for i in ideas if i.primary is not None and i.task is not None]
    if not scored:
        return None
    focus = max(scored, key=lambda i: i.created_at)
    return boards.get((focus.project, str(focus.task)))
