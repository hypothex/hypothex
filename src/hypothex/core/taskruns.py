"""Every run and seed group of one task, named and scored, for the task workspace."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import datetime

from pydantic import BaseModel

from hypothex.core.config import TaskKind
from hypothex.core.context import Context
from hypothex.core.cost import compute_cost
from hypothex.core.headlines import ValueFormat
from hypothex.core.leaderboard import (
    LeaderboardRow,
    NoiseInterval,
    VersusBest,
    cached_names,
    group_id_for,
    key_higher_is_better,
    seed_buckets,
)
from hypothex.core.naming import (
    derive_names,
    display_name,
    group_names,
    run_settings,
    varying_keys,
)
from hypothex.core.queries import get_leaderboard, resolve_task
from hypothex.core.records import INDEXED_POINT_STATUSES, RunRecord, RunStatus, ScoreRecord
from hypothex.core.seeds import Stats


class TaskRun(BaseModel):
    """
    One run of a task as the workspace lists it.

    ``name`` is the display name (``naming.display_name``); ``derived_name`` the
    name from the params that differ in the task. ``params`` holds the run's
    params and template vars (``naming.run_settings``). ``scores`` maps
    ``metric/key`` (the leaderboard's score keys) to the newest successful
    value at the task's current metric versions; ``primary`` is the value of
    the task's primary key. ``commit`` is the full ``git.commit`` (the UI
    shows its first 7 characters). ``progress`` is always None: runs report
    no progress yet.
    """

    run_id: str
    name: str
    derived_name: str
    renamed: bool
    group_id: str
    seed: int | None
    status: RunStatus
    end_reason: str | None
    exit_code: int | None
    created_by: str
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    host: str
    params: dict[str, str]
    tags: list[str]
    archived: bool
    starred: bool
    sweep_id: str | None
    commit: str | None
    scores: dict[str, float]
    primary: float | None
    progress: float | None = None
    gpu_hours: float | None
    cost_usd: float | None

    owner: str | None = None
    """The run's owner (``RunRecord.owner``); None with auth off or before phase 3."""


class TaskGroup(BaseModel):
    """
    One seed group of a task: its leaderboard statistics, or none when unranked.

    A group with no finished, scored run has ``primary``, ``test_interval`` and
    ``vs_best`` None and empty ``scores`` and ``seed_values``. ``scores`` maps
    each score key to the mean over seeds; ``seed_values`` are the per-seed
    primary values.
    """

    group_id: str
    name: str
    run_ids: list[str]
    n: int
    primary: Stats | None
    test_interval: NoiseInterval | None
    scores: dict[str, float | None]
    seed_values: list[float]
    within_noise_of_best: bool
    vs_best: VersusBest | None
    is_best: bool


class TaskRuns(BaseModel):
    """
    A task's runs and seed groups with what the workspace needs to draw them.

    ``groups`` lists ranked groups in leaderboard order, then the unranked ones,
    newest first; group names are unique unless renamed (``naming.disambiguate``).
    ``metric_versions`` holds the task's current version per metric
    (``Leaderboard.metric_versions``), the versions ``scores`` are read at.
    ``key_parts`` are the task's ``score_keys`` part names.
    ``key_higher_is_better`` holds the direction of each of ``score_keys``
    (``leaderboard.key_higher_is_better``); ``higher_is_better`` is the primary's.
    """

    project: str
    task: str
    kind: TaskKind
    primary: str
    higher_is_better: bool
    unit: str
    value_format: ValueFormat
    metric_versions: dict[str, str]
    varying_keys: list[str]
    metric_names: list[str]
    score_keys: list[str]
    key_higher_is_better: dict[str, bool]
    key_parts: list[str] | None
    runs: list[TaskRun]
    groups: list[TaskGroup]


def latest_scores(records: Iterable[ScoreRecord], versions: Mapping[str, str]) -> dict[str, float]:
    """
    Return the newest successful, finite value per ``metric/key`` at ``versions``.

    The rule of the leaderboard's per-run values: scores of another version, with
    an error, or without a finite value are skipped.

    Parameters
    ----------
    records : iterable of ScoreRecord
        One run's scores.
    versions : mapping of str to str
        Selected version per metric (``Leaderboard.metric_versions``).

    Returns
    -------
    dict of str to float

    Examples
    --------
    >>> from hypothex.core.ids import utcnow
    >>> s = ScoreRecord(metric="acc", version="v1", key="value", value=0.5, created_at=utcnow())
    >>> latest_scores([s], {"acc": "v1"})
    {'acc/value': 0.5}
    >>> latest_scores([s], {"acc": "v2"})
    {}
    """
    out: dict[str, float] = {}
    for s in sorted(records, key=lambda s: s.created_at):
        if (
            versions.get(s.metric) == s.version
            and s.error is None
            and s.value is not None
            and math.isfinite(s.value)
        ):
            out[f"{s.metric}/{s.key}"] = s.value
    return out


def _metric_names(ctx: Context, runs: list[RunRecord]) -> list[str]:
    """Step-metric names of ``runs``: indexed for ended runs, a bounded read for live ones."""
    ended = [r.run_id for r in runs if r.status in INDEXED_POINT_STATUSES]
    names = set(ctx.index.metric_names_for(ended))
    for r in runs:
        if r.status not in INDEXED_POINT_STATUSES:
            names.update(ctx.store.read_metric_names_bounded(r.project, r.run_id))
    return sorted(names)


def _cost(run: RunRecord) -> tuple[float | None, float | None]:
    """GPU hours and total dollars: the recorded cost, else GPU hours of an ended run."""
    if run.cost is not None:
        return run.cost.gpu_hours, run.cost.total_usd
    if run.ended_at is None:
        return None, None
    return compute_cost(run, None).gpu_hours, None


def _group(
    group_id: str,
    members: list[RunRecord],
    row: LeaderboardRow | None,
    name: str,
    primary: str,
    best: str | None,
) -> TaskGroup:
    """One ``TaskGroup`` named ``name``: the board row's statistics when ranked."""
    ordered = sorted(members, key=lambda r: (r.created_at, r.run_id))
    return TaskGroup(
        group_id=group_id,
        name=name,
        run_ids=[r.run_id for r in ordered],
        n=row.n if row is not None else len(seed_buckets(ordered)),
        primary=row.primary if row is not None else None,
        test_interval=row.test_interval if row is not None else None,
        scores={k: s.mean for k, s in row.scores.items()} if row is not None else {},
        seed_values=row.seed_values.get(primary, []) if row is not None else [],
        within_noise_of_best=row is not None and row.within_noise_of_best is True,
        vs_best=row.vs_best if row is not None else None,
        is_best=group_id == best,
    )


def derived_names(ctx: Context, project: str, task: str) -> dict[str, str]:
    """
    Return the derived name of every run of a task, archived runs too.

    ``naming.derive_names`` over all the task's runs, oldest first, memoized
    until the index changes (``leaderboard.cached_names``), so a poll that names
    runs reads and parses the task's records only after a write.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    task : str
        Task name.

    Returns
    -------
    dict of str to str
        Derived name per run id (a copy; callers may change it).

    Examples
    --------
    >>> derived_names(ctx, "toy", "toy-acc")  # doctest: +SKIP
    {'r1': 'lr 1e-3', 'r2': 'lr 3e-4'}
    """

    def build() -> dict[str, str]:
        every = ctx.index.list_runs(project=project, task=task, include_archived=True, limit=None)
        return derive_names(sorted(every, key=lambda r: (r.created_at, r.run_id)))

    return cached_names(ctx, project, task, build)


def run_names(ctx: Context, project: str, task: str) -> dict[str, str]:
    """
    Return the display name of every run of a task, archived runs too.

    The names ``task_runs`` gives (``naming.display_name`` over names derived
    from all the task's runs), for panels that label runs.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    task : str
        Task name.

    Returns
    -------
    dict of str to str
        Display name per run id.

    Examples
    --------
    >>> run_names(ctx, "toy", "toy-acc")  # doctest: +SKIP
    {'r1': 'lr 1e-3', 'r2': 'wide beam'}
    """
    every = ctx.index.list_runs(project=project, task=task, include_archived=True, limit=None)
    derived = derived_names(ctx, project, task)
    return {r.run_id: display_name(r, derived) for r in every}


def task_runs(
    ctx: Context, ref: str, project: str | None = None, *, archived: bool = False
) -> TaskRuns:
    """
    List a task's runs and seed groups, named, scored and ranked.

    Group statistics come from the task's leaderboard (``queries.get_leaderboard``,
    cached until the index changes), never recomputed here. Names are derived
    over every run of the task, archived ones too, so hiding archived runs never
    renames the others.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    ref : str
        Task name, or ``project/task``.
    project : str, optional
        Project to restrict the search to.
    archived : bool
        Include archived runs (and their groups).

    Returns
    -------
    TaskRuns
        Runs newest first; groups ranked first, then unranked newest first.

    Examples
    --------
    >>> [r.name for r in task_runs(ctx, "toy-acc").runs]  # doctest: +SKIP
    ['lr 3e-4', 'lr 1e-3']
    """
    entry, task = resolve_task(ctx, ref, project)
    board = get_leaderboard(ctx, task, entry.project)
    every = ctx.index.list_runs(project=entry.project, task=task, include_archived=True, limit=None)
    oldest_first = sorted(every, key=lambda r: (r.created_at, r.run_id))
    derived = derived_names(ctx, entry.project, task)
    shown = [r for r in every if archived or not r.archived]
    stored = ctx.index.scores_for(r.run_id for r in shown)
    runs: list[TaskRun] = []
    for r in shown:
        scores = latest_scores(stored.get(r.run_id, []), board.metric_versions)
        gpu_hours, cost_usd = _cost(r)
        runs.append(
            TaskRun(
                run_id=r.run_id,
                name=display_name(r, derived),
                derived_name=derived[r.run_id],
                renamed=r.name is not None,
                group_id=group_id_for(r),
                seed=r.seed,
                status=r.status,
                end_reason=r.end_reason,
                exit_code=r.exit_code,
                created_by=r.created_by,
                owner=r.owner,
                created_at=r.created_at,
                started_at=r.started_at,
                ended_at=r.ended_at,
                host=r.host,
                params=run_settings(r),
                tags=list(r.tags),
                archived=r.archived,
                starred=r.starred,
                sweep_id=r.sweep_id,
                commit=r.git.commit,
                scores=scores,
                primary=scores.get(board.primary),
                gpu_hours=gpu_hours,
                cost_usd=cost_usd,
            )
        )
    members: dict[str, list[RunRecord]] = {}
    for r in shown:
        members.setdefault(group_id_for(r), []).append(r)
    rows = {row.group_id: row for row in board.rows if row.group_id in members}
    best = board.rows[0].group_id if board.rows and board.rows[0].primary is not None else None
    unranked = sorted(
        (g for g in members if g not in rows),
        key=lambda g: max((r.created_at, r.run_id) for r in members[g]),
        reverse=True,
    )
    names = group_names(members, derived)
    groups = [
        _group(g, members[g], rows.get(g), names[g], board.primary, best)
        for g in [*rows, *unranked]
    ]
    score_keys = sorted({k for run in runs for k in run.scores})
    spec = entry.config.tasks[task]
    return TaskRuns(
        project=entry.project,
        task=task,
        kind=board.kind,
        primary=board.primary,
        higher_is_better=board.higher_is_better,
        unit=board.unit,
        value_format=board.value_format,
        metric_versions=dict(board.metric_versions),
        varying_keys=varying_keys([run_settings(r) for r in oldest_first]),
        metric_names=_metric_names(ctx, shown),
        score_keys=score_keys,
        key_higher_is_better={k: key_higher_is_better(entry.config, spec, k) for k in score_keys},
        key_parts=spec.key_parts,
        runs=runs,
        groups=groups,
    )
