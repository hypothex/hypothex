"""Cross-project overview: timeline, recent ideas, running runs, failures, projects."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from hypothex.core import queries as q
from hypothex.core.config import TaskKind
from hypothex.core.context import Context
from hypothex.core.cost import cost_since, today_start
from hypothex.core.headlines import overview_headline
from hypothex.core.ids import utcnow
from hypothex.core.index import RunRow
from hypothex.core.leaderboard import (
    Leaderboard,
    LeaderboardRow,
    NoiseInterval,
    group_id_for,
    group_label,
)
from hypothex.core.records import ACTIVE_STATUSES, RunRecord, RunStatus
from hypothex.core.seeds import Stats

DEFAULT_WINDOW = timedelta(hours=24)
FAILED_STATUSES = frozenset({RunStatus.FAILED, RunStatus.LOST})
_SQL_SLACK = timedelta(days=1)
"""How far ``_recent_runs`` widens its SQL time bounds; exact filters run in Python."""


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
    best: float | None
    kind: TaskKind
    unit: str = ""
    """Display unit of the task's primary metric (``Leaderboard.unit``); ``""`` without one."""


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


def _finished_counts(ctx: Context) -> dict[tuple[str, str | None], int]:
    """
    Count the finished, unarchived runs of every task with one ``GROUP BY``.

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
        .where(RunRow.status == RunStatus.FINISHED.value, RunRow.archived.is_(False))
        .group_by(RunRow.project, RunRow.task)
    )
    with Session(ctx.index.engine) as session:
        return {(project, task): int(n) for project, task, n in session.execute(stmt)}


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
        with ``task=None``. ``runs`` counts finished, unarchived runs.
    """
    finished = _finished_counts(ctx)
    boards: dict[tuple[str, str], Leaderboard] = {}
    rows: list[ProjectRow] = []
    for entry in q.list_projects(ctx):
        if not entry.config.tasks:
            runs = sum(n for (project, _), n in finished.items() if project == entry.project)
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
                    runs=finished.get(key, 0),
                    best=best.mean if best is not None else None,
                    kind=entry.config.tasks[task].kind,
                    unit=board.unit,
                )
            )
    return boards, rows


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
        window, ``cost_today_usd`` of runs that ended today.

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
