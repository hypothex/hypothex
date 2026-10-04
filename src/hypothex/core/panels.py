"""Panel query engine: turn a view panel into rows the UI can draw."""

from __future__ import annotations

import copy
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from pydantic import BaseModel, Field

from hypothex.core.config import parse_metric_key, parse_metric_version
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError
from hypothex.core.fsutil import read_jsonl
from hypothex.core.headlines import MINUS, fmt_metric, metric_unit
from hypothex.core.leaderboard import (
    Leaderboard,
    _natural_key,
    build_leaderboard,
    cached_leaderboard,
    group_id_for,
    pick_field,
    seed_group_label,
    seed_group_labels,
)
from hypothex.core.queries import primary_examples, refresh_project
from hypothex.core.records import Artifact, MetricPoint, RunRecord, RunStatus, ScoreRecord
from hypothex.core.seeds import summarize
from hypothex.core.sources import group_labels, iter_rows, metric_points, select_fields
from hypothex.core.stats import ecdf_points, lttb, quantile
from hypothex.core.store import ProjectEntry
from hypothex.core.views import (
    VERSION_REF,
    PanelSpec,
    PanelType,
    RunFilter,
    ViewSpec,
    vega_spec_problems,
)

MAX_TABLE_ROWS = 5000
SPIKE_WINDOW = 20
SPIKE_FACTOR = 5.0
AGGREGATES = ("mean", "median", "min", "max", "p50", "p90", "p95", "p99")
PERCENTILES = (("p50", 0.50), ("p95", 0.95), ("p99", 0.99))
BOOTSTRAP_RESAMPLES = 1000
CURVE_POINTS = 500
"""Most points per run and metric in a ``curves`` panel; longer series are thinned by LTTB."""

_BoardKey = tuple[str, str, tuple[str, ...]]


class PanelResult(BaseModel):
    """
    Computed data of one panel.

    Attributes
    ----------
    type : str
        Panel type, copied from the panel spec.
    title : str
        Panel title, copied from the panel spec.
    rows : list of dict
        Rows whose shape depends on ``type``.
    meta : dict
        Axis names, headline, groups, events, warnings, and other extras.
    """

    type: PanelType
    title: str
    rows: list[dict[str, Any]]
    meta: dict[str, Any] = Field(default_factory=dict)


@dataclass
class _RunFiles:
    """
    One run's files that per-run values (``_run_value``) read, each parsed once.

    ``scores.jsonl``, the ``samples/`` series, and the per-example score files
    (keyed by metric name and version, ``id`` dropped).
    """

    run: RunRecord
    _scores: list[ScoreRecord] | None = None
    _samples: dict[str, list[float]] | None = None
    _examples: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)

    def scores(self, ctx: Context) -> list[ScoreRecord]:
        """``RunStore.read_scores`` of the run."""
        if self._scores is None:
            self._scores = ctx.store.read_scores(self.run.project, self.run.run_id)
        return self._scores

    def samples(self, ctx: Context) -> dict[str, list[float]]:
        """``RunStore.read_samples`` of the run."""
        if self._samples is None:
            self._samples = ctx.store.read_samples(self.run.project, self.run.run_id)
        return self._samples

    def examples(self, ctx: Context, name: str, version: str) -> list[dict[str, Any]]:
        """Rows of ``predictions/scores.<name>@<version>.jsonl`` without ``id``."""
        key = (name, version)
        if key not in self._examples:
            path = ctx.run_dir(self.run) / "predictions" / f"scores.{name}@{version}.jsonl"
            rows = read_jsonl(path)
            self._examples[key] = [{k: v for k, v in r.items() if k != "id"} for r in rows]
        return self._examples[key]


@dataclass
class _ViewCache:
    """
    Data the panels of one view share, so each piece is built once per view.

    Boards and labels are keyed by project, task and the panel's run ids (in
    order), so panels with the same runs share them and a panel whose
    ``data.filter`` or ``data.pick`` narrows its runs gets its own.
    """

    entries: dict[str, ProjectEntry] = field(default_factory=dict)
    task_runs: dict[tuple[str, str], list[RunRecord]] = field(default_factory=dict)
    boards: dict[_BoardKey, Leaderboard] = field(default_factory=dict)
    labels: dict[_BoardKey, dict[str, str]] = field(default_factory=dict)
    points: dict[tuple[str, frozenset[str] | None], list[MetricPoint]] = field(default_factory=dict)
    files: dict[str, list[MetricPoint]] = field(default_factory=dict)
    last_run: _RunFiles | None = None

    def run_files(self, run: RunRecord) -> _RunFiles:
        """
        The parsed files of ``run`` (``_RunFiles``), kept for the last run asked for only.

        A panel asks for every value of one run before the next run
        (``_stat_strip`` loops runs, then references), so each run's files are
        read once per panel, not once per reference, while memory holds the
        files of one run, never of all runs.
        """
        if self.last_run is None or self.last_run.run.run_id != run.run_id:
            self.last_run = _RunFiles(run)
        return self.last_run

    def runs_of(self, ctx: Context, entry: ProjectEntry, task: str) -> list[RunRecord]:
        """A new list of the task's unarchived runs, oldest first (read once)."""
        key = (entry.project, task)
        if key not in self.task_runs:
            runs = ctx.index.list_runs(project=entry.project, task=task, limit=None)
            runs.sort(key=lambda r: (r.created_at, r.run_id))
            self.task_runs[key] = runs
        return list(self.task_runs[key])

    def board(
        self, ctx: Context, entry: ProjectEntry, task: str, runs: list[RunRecord]
    ) -> Leaderboard:
        """Leaderboard over ``runs`` (built once per run set)."""
        key = (entry.project, task, tuple(r.run_id for r in runs))
        if key not in self.boards:
            self.boards[key] = _build_board(ctx, entry, task, runs)
        return self.boards[key]

    def group_labels(
        self, ctx: Context, entry: ProjectEntry, task: str, runs: list[RunRecord]
    ) -> dict[str, str]:
        """
        Label per seed-group id of ``runs`` (built once per run set).

        The leaderboard's label for groups on the board; ``sources.group_labels``
        (the same rule) for groups that are not, such as running or unscored ones.
        """
        key = (entry.project, task, tuple(r.run_id for r in runs))
        if key not in self.labels:
            own = _task_labels(entry, task, runs)
            board = self.board(ctx, entry, task, runs)
            self.labels[key] = {**own, **{row.group_id: row.label for row in board.rows}}
        return self.labels[key]

    def metric_points(
        self, ctx: Context, runs: list[RunRecord], names: Iterable[str] | None
    ) -> dict[str, list[MetricPoint]]:
        """
        ``sources.metric_points`` of ``runs``; each run and name set is read once.

        A live run's ``metrics.jsonl`` is parsed once per view, whatever names
        the panels ask for, one line at a time into a bounded copy
        (``RunStore.read_metric_points_bounded``): like an ended run's indexed
        history, at most ``MAX_POINTS_PER_METRIC`` points per name, so neither
        the read nor the cache ever holds a whole file.
        """

        def read_file(run: RunRecord) -> list[MetricPoint]:
            if run.run_id not in self.files:
                self.files[run.run_id] = ctx.store.read_metric_points_bounded(
                    run.project, run.run_id
                )
            return self.files[run.run_id]

        wanted = None if names is None else frozenset(names)
        missing = [r for r in runs if (r.run_id, wanted) not in self.points]
        if missing:
            read = metric_points(ctx, missing, wanted, read_file)
            for r in missing:
                self.points[(r.run_id, wanted)] = read.get(r.run_id, [])
        return {r.run_id: self.points[(r.run_id, wanted)] for r in runs}


@dataclass
class _Scope:
    """The runs a panel sees plus task-level data from the view's cache."""

    ctx: Context
    entry: ProjectEntry
    task: str
    runs: list[RunRecord]
    cache: _ViewCache
    _points: dict[frozenset[str] | None, dict[str, list[MetricPoint]]] = field(default_factory=dict)

    def board(self) -> Leaderboard:
        """Leaderboard over this scope's runs (built once per view)."""
        return self.cache.board(self.ctx, self.entry, self.task, self.runs)

    def labels(self) -> dict[str, str]:
        """Label per seed-group id of this scope's runs (``_ViewCache.group_labels``)."""
        return self.cache.group_labels(self.ctx, self.entry, self.task, self.runs)

    def points(self, names: Iterable[str] | None) -> dict[str, list[MetricPoint]]:
        """
        Metric history per run of this scope's runs, of ``names`` only (``None``: all).

        Kept per name set, so a panel that asks once per run (``_resolve_value``)
        reads every run once, not once per run.
        """
        key = None if names is None else frozenset(names)
        if key not in self._points:
            self._points[key] = self.cache.metric_points(self.ctx, self.runs, key)
        return self._points[key]


def _task_labels(entry: ProjectEntry, task: str, runs: list[RunRecord]) -> dict[str, str]:
    """``sources.group_labels`` with the task's version param for ``agent_iteration``."""
    spec = entry.config.tasks[task]
    return group_labels(runs, spec.version_param if spec.kind == "agent_iteration" else None)


def query_panel(
    ctx: Context,
    project: str,
    task: str,
    panel: PanelSpec,
    runs_filter: RunFilter | None = None,
) -> PanelResult:
    """
    Compute one panel's rows.

    ``markdown`` panels and ``trace`` panels with ``data.run_id`` need no task
    config; every other panel reads the task's runs (unarchived, oldest first),
    narrowed by ``runs_filter``, ``data.filter`` (matched against the flattened
    ``runs`` row; for ``table``/``vega_lite`` matched against each source row
    instead), and ``data.pick``.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    task : str
        Task name.
    panel : PanelSpec
        The panel to compute.
    runs_filter : RunFilter, optional
        The view's run filter.

    Returns
    -------
    PanelResult
        Rows shaped per panel type (see the phase 1b contract, section 1.6).

    Raises
    ------
    ConfigError
        If the task does not exist or the panel lacks a required field.

    Examples
    --------
    >>> panel = PanelSpec(type="markdown", text="hello")
    >>> query_panel(ctx, "toy", "toy-acc", panel).meta  # doctest: +SKIP
    {'text': 'hello'}
    """
    return _panel(ctx, project, task, panel, runs_filter, _ViewCache())


def query_view(ctx: Context, project: str, task: str, view: ViewSpec) -> list[PanelResult]:
    """
    Compute every panel of a view, in order.

    The view must already be resolved (``views.get_view`` returns resolved
    views). A panel that fails with a Hypothex error yields an empty result
    whose ``meta.error`` holds the message, so one bad panel never hides the
    others. The panels share one cache: the task's runs, each leaderboard, and
    each run's metric points are read once per view, not once per panel.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    task : str
        Task name.
    view : ViewSpec
        Resolved view; its ``runs`` filter applies to every panel.

    Returns
    -------
    list of PanelResult
        One result per panel.

    Examples
    --------
    >>> [r.type for r in query_view(ctx, "toy", "toy-acc", view)]  # doctest: +SKIP
    ['stat_strip', 'leaderboard']
    """
    cache = _ViewCache()
    out: list[PanelResult] = []
    for panel in view.panels:
        try:
            out.append(_panel(ctx, project, task, panel, view.runs, cache))
        except HypothexError as exc:
            out.append(
                PanelResult(type=panel.type, title=panel.title, rows=[], meta={"error": str(exc)})
            )
    return out


def _panel(
    ctx: Context,
    project: str,
    task: str,
    panel: PanelSpec,
    runs_filter: RunFilter | None,
    cache: _ViewCache,
) -> PanelResult:
    """Dispatch one panel; ``cache`` holds what the panels of a view share."""
    if panel.type == "markdown":
        return _markdown(panel)
    if panel.type == "trace" and panel.data.run_id:
        return _trace_for(ctx, panel, panel.data.run_id, panel.data.example_id)
    if project not in cache.entries:
        cache.entries[project] = refresh_project(ctx, project)
    return _query(ctx, cache.entries[project], task, panel, runs_filter, cache)


def _query(
    ctx: Context,
    entry: ProjectEntry,
    task: str,
    panel: PanelSpec,
    runs_filter: RunFilter | None,
    cache: _ViewCache,
) -> PanelResult:
    if task not in entry.config.tasks:
        raise ConfigError(f"unknown task {task!r} in project {entry.project!r}")
    runs = cache.runs_of(ctx, entry, task)
    if runs_filter is not None:
        runs = [r for r in runs if _run_matches(r, runs_filter)]
    if panel.data.filter and panel.type not in ("table", "vega_lite"):
        if "label" in panel.data.filter:
            labels = cache.group_labels(ctx, entry, task, runs)
        else:
            labels = _task_labels(entry, task, runs)
        keep = {
            row["run_id"]
            for row in iter_rows(ctx, runs, "runs", labels=labels)
            if _row_matches(row, panel.data.filter)
        }
        runs = [r for r in runs if r.run_id in keep]
    if panel.data.pick == "latest":
        latest = {group_id_for(r): r.run_id for r in runs}
        runs = [r for r in runs if r.run_id in set(latest.values())]
    elif panel.data.pick == "best":
        board_rows = cache.board(ctx, entry, task, runs).rows
        best = set(board_rows[0].run_ids) if board_rows else set()
        runs = [r for r in runs if r.run_id in best]
    scope = _Scope(ctx=ctx, entry=entry, task=task, runs=runs, cache=cache)
    return _HANDLERS[panel.type](scope, panel)


def _run_matches(run: RunRecord, f: RunFilter) -> bool:
    if f.status is not None and run.status.value not in f.status:
        return False
    if f.tags is not None and not set(f.tags) <= set(run.tags):
        return False
    if f.created_by is not None and run.created_by != f.created_by:
        return False
    if f.since is not None:
        since = f.since if f.since.tzinfo else f.since.replace(tzinfo=UTC)
        if run.created_at < since:
            return False
    return True


def _row_matches(row: dict[str, Any], flt: dict[str, Any]) -> bool:
    for key, want in flt.items():
        have = row.get(key)
        if isinstance(want, list):
            if have not in want:
                return False
        elif have != want:
            return False
    return True


def _build_board(
    ctx: Context, entry: ProjectEntry, task: str, runs: list[RunRecord]
) -> Leaderboard:
    def build() -> Leaderboard:
        per_example = primary_examples(ctx, entry.config, task, runs, None)
        scores = ctx.index.scores_for(r.run_id for r in runs)
        return build_leaderboard(
            entry.project, task, entry.config, runs, scores, per_example=per_example or None
        )

    # a view's runs are a filtered list of the task's runs: they are part of the key
    ids = ("view", tuple(r.run_id for r in runs))
    return cached_leaderboard(ctx, entry.project, task, entry.config, build, variant=ids)


def _markdown(panel: PanelSpec) -> PanelResult:
    return PanelResult(type="markdown", title=panel.title, rows=[], meta={"text": panel.text or ""})


def _stat_strip(scope: _Scope, panel: PanelSpec) -> PanelResult:
    """
    The task's stat strip, or one item per ``data.metrics`` reference.

    With ``data.metrics`` each item is the mean of ``_run_value`` over the
    selected runs (after ``data.filter`` and ``data.pick``) that have a value.
    Values are read run by run, each reference once, so a run's files are
    parsed once (``_ViewCache.run_files``), however many references there are.
    """
    board = scope.board()
    rows: list[dict[str, Any]] = []
    if not panel.data.metrics:
        rows = [dict(item) for item in board.stat_strip]
    else:
        groups = _groups(scope, panel)
        only = f" of {groups[0][1]}" if len(groups) == 1 else ""
        found: dict[str, list[float]] = {ref: [] for ref in panel.data.metrics}
        for r in scope.runs:
            for ref, got in found.items():
                if (v := _run_value(scope, r, ref)) is not None:
                    got.append(v)
        for ref in panel.data.metrics:
            values = found[ref]
            if not values:
                tooltip = f"No value in the {len(scope.runs)} selected runs"
                rows.append({"label": ref, "value": "—", "unit": "", "tooltip": tooltip})
                continue
            n = len(values)
            unit = _unit(scope, ref)
            rows.append(
                {
                    "label": ref,
                    "value": fmt_metric(math.fsum(values) / n, unit, suffix=False),
                    "unit": "" if unit == "$" else unit,
                    "tooltip": f"Mean of {n} run{'s' if n != 1 else ''}{only}",
                }
            )
    return PanelResult(
        type="stat_strip",
        title=panel.title,
        rows=rows,
        meta={"headline": board.headline, "unit": board.unit, "value_format": board.value_format},
    )


def _leaderboard(scope: _Scope, panel: PanelSpec) -> PanelResult:
    board = scope.board()
    return PanelResult(
        type="leaderboard",
        title=panel.title,
        rows=[row.model_dump(mode="json") for row in board.rows],
        meta={
            "headline": board.headline,
            "primary": board.primary,
            "higher_is_better": board.higher_is_better,
            "unit": board.unit,
            "value_format": board.value_format,
            "metric_versions": board.metric_versions,
            "noise": list(panel.noise),
            "needs_reeval": board.needs_reeval,
            "unscored": board.unscored,
        },
    )


def _run_versions(scope: _Scope) -> dict[str, tuple[bool, str]]:
    """
    Run id -> (from the version param, version text) for every selected run.

    The text is the run param ``TaskSpec.version_param`` names; a run without
    it gets the creation time (UTC, ``YYYY-MM-DD HH:MM:SS``) of the first
    selected run of its seed group (spec 8.4). ``scope.runs`` is oldest first.
    """
    param = scope.entry.config.tasks[scope.task].version_param
    first: dict[str, RunRecord] = {}
    for r in scope.runs:
        first.setdefault(group_id_for(r), r)
    out: dict[str, tuple[bool, str]] = {}
    for r in scope.runs:
        value = r.params.get(param)
        if value is not None:
            out[r.run_id] = (True, value)
            continue
        created = first[group_id_for(r)].created_at
        created = created if created.tzinfo else created.replace(tzinfo=UTC)
        out[r.run_id] = (False, created.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"))
    return out


def _table_rows(scope: _Scope, panel: PanelSpec) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Source rows filtered on the full row, then projected to ``data.fields``.

    Filtering first lets ``data.filter`` use a field the table does not show. The
    synthetic ``version`` field (``VERSION_REF``) is set on every full ``runs`` row
    before the filter, whatever ``fields`` lists, so ``filter: {version: p10}``
    works on a table that shows only ``status``. The task-level ``groups`` source
    (``group_rows``) keeps exactly the listed ``fields``, in order. With ``fields``,
    ``meta.columns`` lists them: the columns the table draws (per-run rows still carry
    ``run_id``, ``group_id``, ``label`` and ``seed`` for links and filters).
    """
    source = panel.data.source or "runs"
    fields = panel.data.fields
    versions = _run_versions(scope) if source == "runs" else {}
    rows: list[dict[str, Any]] = []
    total = 0
    if source == "groups":
        full: Iterable[dict[str, Any]] = group_rows(scope)
    else:
        names = _filter_names(panel.data.filter) if source == "metrics" else None
        full = iter_rows(scope.ctx, scope.runs, source, labels=scope.labels(), names=names)
    for row in full:
        if versions:
            row[VERSION_REF] = versions[row["run_id"]][1]
        if panel.data.filter and not _row_matches(row, panel.data.filter):
            continue
        total += 1
        if len(rows) < MAX_TABLE_ROWS:
            if source == "groups":
                rows.append(row if fields is None else {f: row.get(f) for f in fields})
            else:
                rows.append(select_fields(row, fields))
    meta: dict[str, Any] = {"source": source, "total": total}
    if fields is not None:
        meta["columns"] = list(fields)  # the table shows these; rows keep ROW_KEYS too
    if total > MAX_TABLE_ROWS:
        meta["warnings"] = [f"showing the first {MAX_TABLE_ROWS} of {total} rows"]
    return rows, meta


def _filter_names(flt: dict[str, Any] | None) -> list[str] | None:
    """The metric names a ``metrics`` source ``data.filter`` keeps, or ``None`` for all."""
    want = (flt or {}).get("name")
    if isinstance(want, str):
        return [want]
    if isinstance(want, list) and all(isinstance(n, str) for n in want):
        return want
    return None


def _version_text(members: list[RunRecord], versions: dict[str, tuple[bool, str]]) -> str:
    """A group's version: its first version-param value, else its first-run time."""
    return next(
        (versions[r.run_id][1] for r in members if versions[r.run_id][0]),
        versions[members[0].run_id][1],
    )


def _items(value: str) -> list[str] | None:
    """Comma-separated items of a param value, or ``None`` when it has no comma."""
    return [t.strip() for t in value.split(",") if t.strip()] if "," in value else None


def _change(key: str, old: str | None, new: str | None) -> str:
    """One changed key: ``model: a → b``, ``tools: +x −y`` for lists, ``— `` for missing."""
    if old is not None and new is not None:
        before, after = _items(old), _items(new)
        if before is not None or after is not None:
            before, after = before or [old], after or [new]
            diff = [f"+{t}" for t in after if t not in before]
            diff += [f"{MINUS}{t}" for t in before if t not in after]
            if diff:
                return f"{key}: {' '.join(diff)}"
    return f"{key}: {old if old is not None else '—'} → {new if new is not None else '—'}"


def _settings(run: RunRecord, skip: str) -> dict[str, str]:
    """A run's ``vars`` then ``params`` (params win), without the version param."""
    return {k: v for k, v in {**run.vars, **run.params}.items() if k != skip}


def group_changes(prev: RunRecord | None, run: RunRecord, version_param: str) -> str:
    """
    Short text of what changed from the previous group's latest run to this one.

    Parameters
    ----------
    prev : RunRecord or None
        Latest run of the previous group in version order; ``None`` for the first
        group, which gives ``""`` (nothing to compare with; the UI shows ``—``).
    run : RunRecord
        Latest run of this group.
    version_param : str
        The task's version param, never listed as a change.

    Returns
    -------
    str
        ``params``/``vars`` keys whose values differ, ``key: old → new`` joined by
        ``; `` (comma-separated values show added and removed items, ``tools:
        +stock_check``); with no such key, the short commit (``""`` without git);
        ``""`` for the first group.

    Examples
    --------
    >>> group_changes(v1, v2, "version")  # doctest: +SKIP
    'model: sonnet-5 → opus-5.5; tools: +stock_check'
    """
    if prev is None:
        return ""
    commit = (run.git.commit or "")[:7]
    old, new = _settings(prev, version_param), _settings(run, version_param)
    keys = [*new, *(k for k in old if k not in new)]
    parts = [_change(k, old.get(k), new.get(k)) for k in keys if old.get(k) != new.get(k)]
    return "; ".join(parts) if parts else commit


def group_rows(scope: _Scope) -> list[dict[str, Any]]:
    """
    One row per seed group of the scope's runs, in version order (``groups`` source).

    Version order is the ordinal ``version`` axis of the scatter: groups with a
    version-param value first, in natural order (``v9`` before ``v10``), then groups
    without one by first-run creation time.

    Parameters
    ----------
    scope : _Scope
        The panel's runs and task-level data.

    Returns
    -------
    list of dict
        Rows with the ``views.GROUP_FIELDS`` keys: ``group_id``, ``label``,
        ``version``, ``run_id`` (latest run), ``n`` (runs), ``commit`` (7 chars),
        ``created_by`` (comma-joined), ``hypothesis`` (newest non-empty),
        ``primary`` (leaderboard mean, ``None`` off the board), ``primary_lo`` /
        ``primary_hi`` (test-set interval, else the seed interval), ``delta_prev``
        (``primary`` minus the previous row's; ``None`` for the first row or a
        missing side), and ``changes`` (``group_changes``).
    """
    versions = _run_versions(scope)
    param = scope.entry.config.tasks[scope.task].version_param
    board = {row.group_id: row for row in scope.board().rows}
    labels = scope.labels()
    members: dict[str, list[RunRecord]] = defaultdict(list)
    for r in scope.runs:
        members[group_id_for(r)].append(r)

    def order(gid: str) -> tuple[bool, tuple[tuple[int, int | str], ...]]:
        runs = members[gid]
        from_param = any(versions[r.run_id][0] for r in runs)
        return (not from_param, _natural_key(_version_text(runs, versions)))

    rows: list[dict[str, Any]] = []
    prev_run: RunRecord | None = None
    prev_primary: float | None = None
    for gid in sorted(members, key=order):
        runs = members[gid]
        latest = runs[-1]
        row = board.get(gid)
        primary = row.primary.mean if row is not None and row.primary is not None else None
        lo = hi = None
        if row is not None and row.test_interval is not None:
            lo, hi = row.test_interval.lo, row.test_interval.hi
        elif row is not None and row.primary is not None:
            lo, hi = row.primary.ci_low, row.primary.ci_high
        delta = None if primary is None or prev_primary is None else primary - prev_primary
        rows.append(
            {
                "group_id": gid,
                "label": labels[gid],
                "version": _version_text(runs, versions),
                "run_id": latest.run_id,
                "n": len(runs),
                "commit": (latest.git.commit or "")[:7] or None,
                "created_by": ", ".join(sorted({r.created_by for r in runs})),
                "hypothesis": next((r.hypothesis for r in reversed(runs) if r.hypothesis), ""),
                "primary": primary,
                "primary_lo": lo,
                "primary_hi": hi,
                "delta_prev": delta,
                "changes": group_changes(prev_run, latest, param),
            }
        )
        prev_run, prev_primary = latest, primary
    return rows


def _table(scope: _Scope, panel: PanelSpec) -> PanelResult:
    rows, meta = _table_rows(scope, panel)
    return PanelResult(type="table", title=panel.title, rows=rows, meta=meta)


def _vega_lite(scope: _Scope, panel: PanelSpec) -> PanelResult:
    """
    Rows plus the spec with its root ``data`` replaced by ``{"values": []}``.

    Any other external resource (nested ``data.url``, lookup sources, image
    marks, ``href``, ``embedOptions``) raises: views that were never validated
    (inline in ``hypothex.yaml``, editor previews) reach this point too.
    """
    spec = copy.deepcopy(panel.spec or {})
    spec["data"] = {"values": []}
    problems = vega_spec_problems(spec)
    if problems:
        loc, message = problems[0]
        raise ConfigError(f"{message} at spec.{'.'.join(str(p) for p in loc)}")
    rows, meta = _table_rows(scope, panel)
    return PanelResult(type="vega_lite", title=panel.title, rows=rows, meta={**meta, "spec": spec})


def _trace_for(ctx: Context, panel: PanelSpec, run_id: str, example_id: str | None) -> PanelResult:
    record = ctx.find_record(run_id)
    if example_id is None:
        traces = ctx.store.list_traces(record.project, run_id)
        if not traces:
            return _empty_trace(panel, run_id, None, f"run {run_id} has no traces")
        failing = [t for t in traces if t["failed"]]
        example_id = str((failing or traces)[0]["example_id"])
    steps = ctx.store.read_trace(record.project, run_id, example_id)
    rows = [step.model_dump() for step in steps]
    meta: dict[str, Any] = {
        "run_id": run_id,
        "example_id": example_id,
        "failed_turn": next((r["turn"] for r in rows if r["error"]), None),
    }
    if not rows:
        meta["warnings"] = [f"no trace for example {example_id!r} in run {run_id}"]
    return PanelResult(type="trace", title=panel.title, rows=rows, meta=meta)


def _trace(scope: _Scope, panel: PanelSpec) -> PanelResult:
    for run in reversed(scope.runs):
        if any((scope.ctx.run_dir(run) / "traces").glob("*.jsonl")):
            return _trace_for(scope.ctx, panel, run.run_id, panel.data.example_id)
    return _empty_trace(panel, None, panel.data.example_id, "no run in this view has traces")


def _empty_trace(
    panel: PanelSpec, run_id: str | None, example_id: str | None, warning: str
) -> PanelResult:
    return PanelResult(
        type="trace",
        title=panel.title,
        rows=[],
        meta={
            "run_id": run_id,
            "example_id": example_id,
            "failed_turn": None,
            "warnings": [warning],
        },
    )


def _groups(scope: _Scope, panel: PanelSpec) -> list[tuple[str, str, list[RunRecord]]]:
    """
    Return ``(key, label, members)`` per group, in order of first run.

    ``group_by: run`` labels each run ``<group label> r<n>``, ``n`` its position in
    its seed group (oldest first), so small multiples of one config stay apart.
    """
    by = panel.data.group_by or "group"
    members: dict[str, list[RunRecord]] = defaultdict(list)
    for r in scope.runs:
        if by == "config":
            key = r.config_hash.removeprefix("sha256:")[:8]
        elif by == "run":
            key = r.run_id
        elif by == "seed":
            key = f"seed={r.seed}"
        else:
            key = group_id_for(r)
        members[key].append(r)
    if by in ("group", "run"):
        labels = scope.labels()
    elif by == "config":
        labels = seed_group_labels(members)  # the board's rule, over these config groups
    else:
        labels = {}
    repeat = _repeats(scope.runs) if by == "run" else {}
    out: list[tuple[str, str, list[RunRecord]]] = []
    for key, runs in members.items():
        if by == "run":
            label: str | None = f"{labels[group_id_for(runs[0])]} r{repeat[key]}"
        else:
            label = f"seed {runs[0].seed}" if by == "seed" else labels.get(key)
        out.append((key, label or seed_group_label(runs, key), runs))
    return out


def _repeats(runs: list[RunRecord]) -> dict[str, int]:
    """Run id -> 1-based position of the run in its seed group (``runs`` oldest first)."""
    seen: dict[str, int] = defaultdict(int)
    out: dict[str, int] = {}
    for r in runs:
        gid = group_id_for(r)
        seen[gid] += 1
        out[r.run_id] = seen[gid]
    return out


def _unit(scope: _Scope, ref: str) -> str:
    """Display unit of a reference: the metric's configured ``unit``, else from its name."""
    name, _ = parse_metric_version(ref.partition("/")[0])
    spec = scope.entry.config.metrics.get(name)
    return metric_unit(ref, spec.unit if spec is not None else "")


def _lower_is_better(name: str) -> bool:
    lowered = name.lower()
    return "loss" in lowered or "error" in lowered


def _spikes(points: list[MetricPoint]) -> list[int]:
    """
    Steps whose value exceeds 5x the median of the previous 20 values.

    Exactly the contract rule ``value > 5 × median(previous 20 values)``: a zero
    median makes any positive value a spike (a loss leaving a flat zero).
    """
    steps: list[int] = []
    values = [p.value for p in points]
    for i in range(1, len(points)):
        window = values[max(0, i - SPIKE_WINDOW) : i]
        if values[i] > SPIKE_FACTOR * statistics.median(window):
            steps.append(points[i].step)
    return steps


def _spike_ranges(
    series: list[MetricPoint], x_of: dict[int, float] | None
) -> list[tuple[float, float]]:
    """
    ``(first x, last x)`` of each run of consecutive spike points (``_spikes``).

    ``x_of`` maps a step to the curves' x (``None``: x is the step); a point
    without an x is skipped, as on the curve.
    """
    flagged = set(_spikes(series))
    out: list[tuple[float, float]] = []
    inside = False
    for p in series:
        x = p.step if x_of is None else x_of.get(p.step)
        if x is None:
            continue
        if p.step in flagged:
            if inside:
                out[-1] = (out[-1][0], x)
            else:
                out.append((x, x))
            inside = True
        else:
            inside = False
    return out


def _merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping ``(start, end)`` ranges, e.g. one spike in train and val loss."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def short_step(x: float) -> str:
    """
    A step or x value in at most four characters: ``950``, ``9.5k``, ``14k``, ``1.2M``.

    Parameters
    ----------
    x : float
        The step (or ``step_metric`` value).

    Returns
    -------
    str
        Thousands as ``k`` and millions as ``M``, with one decimal below 10.

    Examples
    --------
    >>> short_step(9000), short_step(9500), short_step(14250), short_step(950)
    ('9k', '9.5k', '14k', '950')
    """
    for size, suffix in ((1e6, "M"), (1e3, "k")):
        if abs(x) >= size:
            v = x / size
            if abs(v) < 10:
                text = f"{math.floor(v * 10 + 0.5) / 10:.1f}".removesuffix(".0")
            else:
                text = str(math.floor(v + 0.5))
            return text + suffix
    return str(int(x)) if float(x).is_integer() else f"{x:.3g}"


def _event(run_id: str, x: float, kind: str) -> dict[str, Any]:
    """
    A curves event with its short label, e.g. ``spike 9k``, ``killed 14k``, or
    ``NaN 9k`` (kind ``nonfinite``).
    """
    text = "NaN" if kind == "nonfinite" else kind
    return {"run_id": run_id, "step": x, "kind": kind, "label": f"{text} {short_step(x)}"}


def _nonfinite_xs(
    scope: _Scope,
    run: RunRecord,
    wanted: list[str] | None,
    x_name: str,
    x_of: dict[int, float] | None,
) -> list[float]:
    """
    Distinct x of the run's recorded ``NaN`` / infinite values, sorted.

    Only names the panel shows count (all but the step metric when ``wanted`` is
    ``None``); a step with no ``step_metric`` value is dropped, like a curve point.
    """
    xs: set[float] = set()
    for p in scope.ctx.store.read_nonfinite_points(run.project, run.run_id):
        if (p.name not in wanted) if wanted is not None else p.name == x_name:
            continue
        x = p.step if x_of is None else x_of.get(p.step)
        if x is not None:
            xs.add(x)
    return sorted(xs)


def _checkpoints(scope: _Scope, run: RunRecord) -> list[Artifact]:
    logged = scope.ctx.store.read_artifacts(run.project, run.run_id)
    merged = {(a.kind, a.path): a for a in [*run.artifacts, *logged]}
    return sorted(
        (a for a in merged.values() if a.kind == "checkpoint" and a.step is not None),
        key=lambda a: a.step or 0,
    )


def _curves(scope: _Scope, panel: PanelSpec) -> PanelResult:
    # a name listed twice is drawn once: repeats would multiply the rows
    wanted = None if panel.data.metrics is None else list(dict.fromkeys(panel.data.metrics))
    x_name = panel.data.step_metric or "step"
    rows: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    group_of: dict[str, str] = {}
    by_run = panel.data.group_by == "run"
    repeat = _repeats(scope.runs) if by_run else {}
    for key, label, members in _groups(scope, panel):
        entry: dict[str, Any] = {"group_id": key, "label": label}
        if by_run:
            entry |= {"seed_group": group_id_for(members[0]), "repeat": repeat[key]}
        groups.append(entry)
        for r in members:
            group_of[r.run_id] = key
    names_seen: dict[str, None] = {}  # insertion-ordered set
    needed = None if wanted is None else [*wanted, *([x_name] if x_name != "step" else [])]
    history = scope.points(needed)
    for run in scope.runs:
        by_name: dict[str, list[MetricPoint]] = defaultdict(list)
        for p in history.get(run.run_id, []):
            by_name[p.name].append(p)
        x_of: dict[int, float] | None = None
        if x_name != "step":
            x_of = {p.step: p.value for p in by_name.get(x_name, [])}
        names = wanted if wanted is not None else sorted(n for n in by_name if n != x_name)
        run_events: list[dict[str, Any]] = []
        spike_ranges: list[tuple[float, float]] = []
        last_x: float | None = None
        for name in names:
            series = sorted(by_name.get(name, []), key=lambda p: p.step)
            if series:
                names_seen.setdefault(name)
            xy = [
                (x, p.value)
                for p in series
                if (x := p.step if x_of is None else x_of.get(p.step)) is not None
            ]
            if xy:
                last_x = max([x for x, _ in xy] + ([] if last_x is None else [last_x]))
            for i in lttb([x for x, _ in xy], [v for _, v in xy], CURVE_POINTS):
                rows.append(
                    {
                        "run_id": run.run_id,
                        "group_id": group_of[run.run_id],
                        "seed": run.seed,
                        "name": name,
                        "step": xy[i][0],
                        "value": xy[i][1],
                    }
                )
            if "loss" in name.lower():
                spike_ranges += _spike_ranges(series, x_of)
        for start, _ in _merge_ranges(spike_ranges):
            run_events.append(_event(run.run_id, start, "spike"))
        for x in _nonfinite_xs(scope, run, wanted, x_name, x_of):
            run_events.append(_event(run.run_id, x, "nonfinite"))
        if run.status in (RunStatus.KILLED, RunStatus.FAILED) and last_x is not None:
            run_events.append(_event(run.run_id, last_x, run.status.value))
        events.extend(sorted(run_events, key=lambda e: e["step"]))
        checkpoints.extend(_checkpoint_rows(scope, run, panel, x_of))
    return PanelResult(
        type="curves",
        title=panel.title,
        rows=rows,
        meta={
            "x": x_name,
            "metrics": list(names_seen),
            "checkpoints": checkpoints,
            "events": events,
            "groups": groups,
        },
    )


def _checkpoint_rows(
    scope: _Scope, run: RunRecord, panel: PanelSpec, x_of: dict[int, float] | None
) -> list[dict[str, Any]]:
    """
    Checkpoint marks of one run, at the curves' x.

    ``x_of`` maps a training step to the ``data.step_metric`` value logged at
    that step (``None`` when x is the step itself); a checkpoint whose step has
    no such value is dropped, like a curve point.
    """
    arts = [
        a
        for a in _checkpoints(scope, run)
        if x_of is None or (a.step is not None and a.step in x_of)
    ]
    if not arts:
        return []
    name = panel.data.y
    if name is None:
        present = [m for m in (panel.data.metrics or []) if any(m in a.metrics for a in arts)]
        keys = sorted({k for a in arts for k in a.metrics})
        name = present[0] if present else (keys[0] if keys else None)
    out = [
        {
            "run_id": run.run_id,
            "step": a.step if x_of is None or a.step is None else x_of[a.step],
            "value": a.metrics.get(name) if name else None,
            "best": False,
        }
        for a in arts
    ]
    scored = [c for c in out if c["value"] is not None]
    if scored and name is not None:
        pick = min if _lower_is_better(name) else max
        best = pick(scored, key=lambda c: c["value"])
        best["best"] = True
    return out


def _aggregate(values: list[float], agg: str) -> float | None:
    if not values:
        return None
    if agg == "mean":
        return math.fsum(values) / len(values)
    if agg == "median":
        return statistics.median(values)
    if agg == "min":
        return min(values)
    if agg == "max":
        return max(values)
    return quantile(values, int(agg[1:]) / 100)


def _samples(scope: _Scope, run: RunRecord, name: str) -> list[float]:
    """A run's raw samples of series ``name`` (the name given to ``log_samples``)."""
    if not name:
        return []
    return scope.cache.run_files(run).samples(scope.ctx).get(name, [])


def _example_values(scope: _Scope, run: RunRecord, name: str, version: str) -> list[float]:
    """Per-example values of a metric: the field ``pick_field`` chooses, one per example."""
    rows = scope.cache.run_files(run).examples(scope.ctx, name, version)
    picked = pick_field(rows, name)
    if picked is None:
        return []
    field = picked[0]
    return [float(row[field]) for row in rows if row.get(field) is not None]


def _primary_rows(scope: _Scope, run: RunRecord) -> tuple[str, list[dict[str, Any]]] | None:
    """
    The primary metric's name and a run's per-example rows of it (without ``id``).

    ``None`` when the primary is not a configured metric; no rows when the run
    has no per-example file.
    """
    name = scope.board().primary.partition("/")[0]
    spec = scope.entry.config.metrics.get(name)
    if spec is None:
        return None
    return name, scope.cache.run_files(run).examples(scope.ctx, name, spec.version)


def _attempts(scope: _Scope, run: RunRecord) -> int | None:
    """
    Count the examples a run attempted: its per-example rows of the primary metric.

    The same count as the stat strip's ``$ / attempt``; ``None`` without rows.
    """
    primary = _primary_rows(scope, run)
    if primary is None or not primary[1]:
        return None
    return len(primary[1])


def _solved(scope: _Scope, run: RunRecord) -> int | None:
    """
    Count the examples a run solved on the task's primary metric.

    ``None`` when the run has no per-example file or its field (chosen by
    ``pick_field``, as for test-set noise) is not binary.
    """
    primary = _primary_rows(scope, run)
    if primary is None:
        return None
    name, rows = primary
    picked = pick_field(rows, name)
    if picked is None or not picked[1]:
        return None
    field = picked[0]
    return sum(1 for row in rows if row.get(field) in (True, 1))


def _param_raw(run: RunRecord, ref: str) -> str | None:
    """The raw ``params.<p>`` / ``vars.<p>`` value as text, or ``None``."""
    for prefix, values in (("params.", run.params), ("vars.", run.vars)):
        if ref.startswith(prefix):
            return values.get(ref.removeprefix(prefix))
    return None


def _as_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _run_value(scope: _Scope, run: RunRecord, ref: str) -> float | None:
    """
    Resolve a reference to one finite number for one run.

    Order: ``usage.<field>`` (run totals), ``usage.<field>/solved`` (the total
    per example solved on the primary metric) or ``usage.<field>/attempt`` (the
    total per example attempted: per-example rows of the primary),
    ``params.<p>``/``vars.<p>`` (cast to float), a configured metric
    ``name[@version][/key]`` (newest good score; when no score has that key and
    the key is an aggregate such as ``median``, the aggregate of the metric's
    per-example values), samples ``name[/agg]``, then the last logged value of
    a history metric named exactly ``ref``.
    NaN and ±inf count as no value (``None``): they would become null points
    in JSON and make every Pareto comparison false.
    """
    value = _resolve_value(scope, run, ref)
    return value if value is not None and math.isfinite(value) else None


def _resolve_value(scope: _Scope, run: RunRecord, ref: str) -> float | None:
    """The raw value behind ``_run_value``; may be NaN or ±inf."""
    if ref.startswith("usage."):
        field, _, per = ref.removeprefix("usage.").partition("/")
        if per not in ("", "solved", "attempt"):
            raise ConfigError(
                "usage references are usage.<field>, usage.<field>/solved or usage.<field>/attempt"
            )
        value = getattr(run.usage, field, None) if run.usage is not None else None
        if not isinstance(value, int | float):
            return None
        if not per:
            return float(value)
        count = _solved(scope, run) if per == "solved" else _attempts(scope, run)
        return float(value) / count if count else None
    if ref.startswith(("params.", "vars.")):
        raw = _param_raw(run, ref)
        return None if raw is None else _as_float(raw)
    head, _, key = ref.partition("/")
    name, version = parse_metric_version(head)
    metrics = scope.entry.config.metrics
    if name in metrics:
        version = version or metrics[name].version
        key = key or "value"
        found: float | None = None
        for s in scope.cache.run_files(run).scores(scope.ctx):
            if (s.metric, s.version, s.key) == (name, version, key) and s.error is None:
                found = s.value
        if found is None and key in AGGREGATES:
            return _aggregate(_example_values(scope, run, name, version), key)
        return found
    whole = _samples(scope, run, ref)
    if whole:
        return _aggregate(whole, "mean")
    if key in AGGREGATES:
        return _aggregate(_samples(scope, run, head), key)
    points = scope.points([ref]).get(run.run_id, [])
    return max(points, key=lambda p: p.step).value if points else None


def _interval(values: list[float]) -> tuple[float | None, float | None]:
    stats = summarize(values)
    return stats.ci_low, stats.ci_high


def _is_ordinal(
    groups: list[tuple[str, str, list[RunRecord]]],
    x_ref: str,
    text_of: Callable[[RunRecord], str | None],
) -> bool:
    """Whether ``x_ref`` is a params/vars field or ``version`` with a non-numeric value."""
    if x_ref != VERSION_REF and not x_ref.startswith(("params.", "vars.")):
        return False
    for _, _, members in groups:
        for r in members:
            raw = text_of(r)
            if raw is not None and _as_float(raw) is None:
                return True
    return False


def _scatter(scope: _Scope, panel: PanelSpec) -> PanelResult:
    """
    One point per group: mean x and y over its runs, with seed intervals.

    ``data.y`` defaults to the task's primary metric. A ``params``/``vars`` x
    with a value that is not a number (e.g. ``version: v9``) makes an ordinal
    axis: x is the raw text, rows are in natural order (``v9`` before ``v10``),
    there are no x intervals and no Pareto front, and ``meta.x_type`` is
    ``"ordinal"`` (else ``"quantitative"``). Only an ordinal axis sets
    ``regression`` (``_mark_regressions``); otherwise every row has ``False``.
    ``x: version`` reads the task's version param, else the group's first-run
    creation time (``_run_versions``). ``meta.y_higher_is_better`` and
    ``meta.best_group`` (best mean y in that direction) are always set.
    """
    x_ref = panel.data.x
    if not x_ref:
        raise ConfigError("scatter panel needs data.x")
    if panel.pareto and set(panel.pareto) - {"x", "y"}:
        # the same rule as view validation; unvalidated previews reach this point
        raise ConfigError("pareto keys are x and y")
    board = scope.board()
    primary = board.primary
    y_ref = panel.data.y or primary
    board_rows = {row.group_id: row for row in board.rows}
    y_name, y_version = parse_metric_version(y_ref.partition("/")[0])
    y_key = y_ref.partition("/")[2] or "value"
    # the board's test-set interval belongs to the primary at the board's metric version;
    # an explicit other version (accuracy@v0 while the board uses v1) keeps seed intervals
    board_version = y_version is None or y_version == board.metric_versions.get(y_name)
    y_is_primary = (
        (panel.data.group_by or "group") == "group"
        and f"{y_name}/{y_key}" == primary
        and board_version
    )
    higher = _y_higher_is_better(scope, y_ref)
    groups = _groups(scope, panel)
    versions = _run_versions(scope) if x_ref == VERSION_REF else {}

    def text_of(r: RunRecord) -> str | None:
        return versions[r.run_id][1] if x_ref == VERSION_REF else _param_raw(r, x_ref)

    ordinal = _is_ordinal(groups, x_ref, text_of)
    rows: list[dict[str, Any]] = []
    for key, label, members in groups:
        seeds: list[dict[str, Any]] = []
        for r in members:
            if ordinal:
                x: float | str | None = text_of(r)
            elif x_ref == VERSION_REF:
                x = _as_float(versions[r.run_id][1])
            else:
                x = _run_value(scope, r, x_ref)
            y = _run_value(scope, r, y_ref)
            if x is not None and y is not None:
                seeds.append({"x": x, "y": y})
        if not seeds:
            continue
        ys = [s["y"] for s in seeds]
        x_lo: float | None = None
        x_hi: float | None = None
        if ordinal:
            x_mid: float | str = ", ".join(sorted({s["x"] for s in seeds}, key=_natural_key))
        else:
            xs = [s["x"] for s in seeds]
            x_mid = math.fsum(xs) / len(xs)
            x_lo, x_hi = _interval(xs)
        y_lo, y_hi = _interval(ys)
        board_row = board_rows.get(key)
        test = board_row.test_interval if y_is_primary and board_row is not None else None
        if test is not None:
            y_lo, y_hi = test.lo, test.hi
        rows.append(
            {
                "group_id": key,
                "label": label,
                "x": x_mid,
                "x_lo": x_lo,
                "x_hi": x_hi,
                "y": math.fsum(ys) / len(ys),
                "y_lo": y_lo,
                "y_hi": y_hi,
                "seeds": seeds,
                "pareto": False,
                "regression": False,
            }
        )
    if ordinal:
        # version axis: groups with a version param value first, then fallback times
        from_param = {
            key: any(versions[r.run_id][0] for r in members) if versions else True
            for key, _, members in groups
        }
        rows.sort(key=lambda row: (not from_param[row["group_id"]], _natural_key(row["x"])))
        _mark_regressions(rows, higher)
    elif panel.pareto:
        _mark_pareto(rows, panel.pareto)
    best = (max if higher else min)(rows, key=lambda row: row["y"]) if rows else None
    return PanelResult(
        type="scatter",
        title=panel.title,
        rows=rows,
        meta={
            "x": x_ref,
            "y": y_ref,
            "x_type": "ordinal" if ordinal else "quantitative",
            "scale": panel.scale,
            "pareto": panel.pareto,
            "y_higher_is_better": higher,
            "best_group": best["group_id"] if best is not None else None,
            "x_unit": "" if x_ref == VERSION_REF else _unit(scope, x_ref),
            "y_unit": _unit(scope, y_ref),
        },
    )


def _mark_pareto(rows: list[dict[str, Any]], directions: Mapping[str, str]) -> None:
    """Set ``pareto`` on rows that no other row dominates."""
    axes = [(axis, 1.0 if d == "max" else -1.0) for axis, d in directions.items()]

    def better_or_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
        return all(sign * a[axis] >= sign * b[axis] for axis, sign in axes)

    def strictly_better(a: dict[str, Any], b: dict[str, Any]) -> bool:
        return any(sign * a[axis] > sign * b[axis] for axis, sign in axes)

    for row in rows:
        row["pareto"] = not any(
            other is not row and better_or_equal(other, row) and strictly_better(other, row)
            for other in rows
        )


def _y_higher_is_better(scope: _Scope, y_ref: str) -> bool:
    """
    Direction of a scatter y reference.

    ``usage.*`` (cost, tokens, time) is lower-is-better; the task's primary
    uses the leaderboard's direction; another configured metric uses its
    ``higher_is_better``; any other name is lower-is-better when it names a
    loss or an error.
    """
    if y_ref.startswith("usage."):
        return False
    board = scope.board()
    head, _, key = y_ref.partition("/")
    name, _ = parse_metric_version(head)
    if f"{name}/{key or 'value'}" == board.primary:
        return board.higher_is_better
    metrics = scope.entry.config.metrics
    if name in metrics:
        return metrics[name].higher_is_better
    return not _lower_is_better(y_ref)


def _mark_regressions(rows: list[dict[str, Any]], higher: bool) -> None:
    """
    Flag rows worse than the row just before them by more than the intervals allow.

    ``rows`` are in axis order, so each version is compared with the previous
    version, not with the best so far: a version that improves on a bad one is
    never flagged. Higher-is-better: a row regresses when its ``y_hi`` is below
    the previous row's ``y_lo``; lower-is-better: when its ``y_lo`` is above the
    previous row's ``y_hi``. A ``None`` bound on either side flags nothing.
    """
    for prev, row in zip(rows, rows[1:], strict=False):
        mine = row["y_hi"] if higher else row["y_lo"]
        bound = prev["y_lo"] if higher else prev["y_hi"]
        if mine is not None and bound is not None:
            row["regression"] = mine < bound if higher else mine > bound


def _usage_values(scope: _Scope, run: RunRecord, field_name: str) -> list[float]:
    """A run's per-example ``usage.jsonl`` values of one numeric field, booleans excluded."""
    rows = scope.ctx.store.read_usage(run.project, run.run_id)
    values = [getattr(row, field_name, None) for row in rows]
    return [float(v) for v in values if isinstance(v, int | float) and not isinstance(v, bool)]


def _distribution_values(scope: _Scope, run: RunRecord, name: str) -> list[float]:
    """A distribution panel's raw values: ``usage.<field>`` rows, else a named samples series."""
    if name.startswith("usage."):
        return _usage_values(scope, run, name.removeprefix("usage."))
    return _samples(scope, run, name)


def _baseline_key(
    selector: str | None, groups: list[tuple[str, str, list[RunRecord]]]
) -> str | None:
    """
    The key of the group ``TaskSpec.baseline`` selects, or ``None``.

    Same rules as the leaderboard's ``_select_group``: ``tag:<t>`` is the first
    group with a run tagged ``<t>``; anything else is a full or prefix
    ``group_id`` or a ``config_hash``.

    Parameters
    ----------
    selector : str or None
        The task's ``baseline`` field.
    groups : list of (str, str, list of RunRecord)
        The panel's groups, as returned by ``_groups``.

    Returns
    -------
    str or None
        The matching group's key, or ``None`` when nothing matches.
    """
    if not selector:
        return None
    if selector.startswith("tag:"):
        tag = selector.removeprefix("tag:")
        return next((k for k, _, members in groups if any(tag in m.tags for m in members)), None)
    for key, _, members in groups:
        if key.startswith(selector) or any(m.config_hash == selector for m in members):
            return key
    return None


def _rel_change_interval(
    values: list[float], base: list[float], resamples: int = BOOTSTRAP_RESAMPLES, seed: int = 0
) -> tuple[float | None, float | None]:
    """
    Percentile bootstrap 95% interval of ``mean(values) / mean(base) - 1``.

    Each resample draws ``values`` then ``base`` with replacement from one
    ``random.Random(seed)``; resamples whose base mean is 0 are skipped.

    Parameters
    ----------
    values : list of float
        Per-seed values of the row being compared.
    base : list of float
        Per-seed values of the baseline row.
    resamples : int
        Number of bootstrap resamples.
    seed : int
        Seed for the resample generator.

    Returns
    -------
    tuple of (float or None, float or None)
        ``(lo, hi)`` of the 95% interval, or ``(None, None)`` when either side
        has fewer than 2 values.
    """
    if len(values) < 2 or len(base) < 2:
        return None, None
    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(resamples):
        drawn = rng.choices(values, k=len(values))
        drawn_base = rng.choices(base, k=len(base))
        base_mean = math.fsum(drawn_base) / len(drawn_base)
        if base_mean != 0:
            deltas.append((math.fsum(drawn) / len(drawn) - base_mean) / base_mean)
    if not deltas:
        return None, None
    return quantile(deltas, 0.025), quantile(deltas, 0.975)


def _vs_baseline(row: dict[str, Any], base: dict[str, Any]) -> dict[str, list[float | None]] | None:
    """Relative change of each percentile vs the baseline row, with a repeat-bootstrap CI."""
    if row is base or any(base[p] == 0 for p, _ in PERCENTILES):
        return None
    out: dict[str, list[float | None]] = {}
    for p, _ in PERCENTILES:
        lo, hi = _rel_change_interval([s[p] for s in row["seeds"]], [s[p] for s in base["seeds"]])
        out[p] = [(row[p] - base[p]) / base[p], lo, hi]
    return out


def _distribution(scope: _Scope, panel: PanelSpec) -> PanelResult:
    """
    Pooled percentiles and ECDF per group, per-seed percentiles, and the change
    of each percentile vs the task's baseline group (``vs_baseline``).

    Parameters
    ----------
    scope : _Scope
        The panel's runs and task-level data.
    panel : PanelSpec
        The panel spec; ``data.metrics[0]`` or ``data.x`` names the samples
        series (or ``usage.<field>``).

    Returns
    -------
    PanelResult
        One row per group (see the phase 1b contract, section 1.6).

    Raises
    ------
    ConfigError
        If neither ``data.metrics`` nor ``data.x`` is set.
    """
    name = panel.data.metrics[0] if panel.data.metrics else panel.data.x
    if not name:
        raise ConfigError("distribution panel needs data.metrics or data.x")
    groups = _groups(scope, panel)
    rows: list[dict[str, Any]] = []
    for key, label, members in groups:
        pooled: list[float] = []
        seeds: list[dict[str, Any]] = []
        for r in members:
            values = _distribution_values(scope, r, name)
            if not values:
                continue
            pooled.extend(values)
            seeds.append({"run_id": r.run_id, **{p: quantile(values, q) for p, q in PERCENTILES}})
        if not pooled:
            continue
        rows.append(
            {
                "group_id": key,
                "label": label,
                "n": len(pooled),
                **{p: quantile(pooled, q) for p, q in PERCENTILES},
                "ecdf": [[x, y] for x, y in ecdf_points(pooled, max_points=200)],
                "seeds": seeds,
                "vs_baseline": None,
            }
        )
    base_key = _baseline_key(scope.entry.config.tasks[scope.task].baseline, groups)
    base = next((row for row in rows if row["group_id"] == base_key), None)
    if base is not None:
        for row in rows:
            row["vs_baseline"] = _vs_baseline(row, base)
    return PanelResult(
        type="distribution",
        title=panel.title,
        rows=rows,
        meta={
            "name": name,
            "unit": _unit(scope, name),
            "scale": panel.scale,
            "render": panel.render,
            "baseline": base["group_id"] if base is not None else None,
        },
    )


def _is_solved(value: Any) -> bool:
    """Whether one per-example field value counts as solved (not ``False`` and not ``0``)."""
    return not (value is False or (isinstance(value, int | float) and value == 0))


def _grid(scope: _Scope, panel: PanelSpec) -> PanelResult:
    """
    Fraction of seeds that solved each example, per group.

    Parameters
    ----------
    scope : _Scope
        The panel's runs and task-level data.
    panel : PanelSpec
        The panel spec; ``data.metrics[0]`` names the metric (``name[@version]``,
        default the task's primary), ``data.y`` an explicit per-example field.

    Returns
    -------
    PanelResult
        One row per ``(item_id, group_id)`` with a scored value (see the
        phase 1b contract, section 1.6).

    Raises
    ------
    ConfigError
        If the referenced metric is not configured.
    """
    config = scope.entry.config
    if panel.data.metrics:
        ref = panel.data.metrics[0]
    else:
        ref = parse_metric_key(config.tasks[scope.task].primary)[0]
    name, version = parse_metric_version(ref.partition("/")[0])
    if name not in config.metrics:
        raise ConfigError(f"grid panel: unknown metric {name!r}")
    prefix = f"{name}@{version or config.metrics[name].version}."
    groups = _groups(scope, panel)
    group_of = {r.run_id: key for key, _, members in groups for r in members}
    pred_rows = list(iter_rows(scope.ctx, scope.runs, "predictions"))
    column = f"{prefix}{panel.data.y}" if panel.data.y else _solved_column(pred_rows, prefix)
    solved: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in pred_rows:
        if column is not None and row.get(column) is not None:
            solved[(row["id"], group_of[row["run_id"]])].append(_is_solved(row[column]))
    cells = {k: sum(v) / len(v) for k, v in solved.items()}
    by_item: dict[str, list[float]] = defaultdict(list)
    by_group: dict[str, list[float]] = defaultdict(list)
    for (item, gid), value in cells.items():
        by_item[item].append(value)
        by_group[gid].append(value)
    items = sorted(by_item, key=lambda i: (math.fsum(by_item[i]) / len(by_item[i]), i))
    labels = {key: label for key, label, _ in groups}
    gids = sorted(by_group, key=lambda g: (-math.fsum(by_group[g]) / len(by_group[g]), g))
    rows = [
        {"item_id": item, "group_id": gid, "value": cells[(item, gid)]}
        for item in items
        for gid in gids
        if (item, gid) in cells
    ]
    return PanelResult(
        type="grid",
        title=panel.title,
        rows=rows,
        meta={
            "items": items,
            "groups": [{"group_id": g, "label": labels[g]} for g in gids],
            "field": column,
        },
    )


def _solved_column(rows: list[dict[str, Any]], prefix: str) -> str | None:
    """The per-example field to use: ``correct``, else ``solved``, else the first bool column."""
    columns = {k for row in rows for k in row if k.startswith(prefix)}
    for preferred in ("correct", "solved"):
        if f"{prefix}{preferred}" in columns:
            return f"{prefix}{preferred}"
    for row in rows:
        for k, v in row.items():
            if k.startswith(prefix) and isinstance(v, bool):
                return k
    return None


_HANDLERS = {
    "stat_strip": _stat_strip,
    "leaderboard": _leaderboard,
    "curves": _curves,
    "scatter": _scatter,
    "distribution": _distribution,
    "grid": _grid,
    "table": _table,
    "vega_lite": _vega_lite,
    "trace": _trace,
}
