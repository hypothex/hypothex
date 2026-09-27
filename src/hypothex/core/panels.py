"""Panel query engine: turn a view panel into rows the UI can draw."""

from __future__ import annotations

import copy
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from pydantic import BaseModel, Field

from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError
from hypothex.core.leaderboard import Leaderboard, build_leaderboard, group_id_for, group_label
from hypothex.core.queries import primary_examples, refresh_project
from hypothex.core.records import Artifact, MetricPoint, RunRecord, RunStatus
from hypothex.core.sources import iter_rows, select_fields
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
class _Scope:
    """The runs a panel sees plus lazily built task-level data."""

    ctx: Context
    entry: ProjectEntry
    task: str
    runs: list[RunRecord]
    _board: Leaderboard | None = None

    def board(self) -> Leaderboard:
        """Leaderboard over this scope's runs (built once)."""
        if self._board is None:
            self._board = _build_board(self.ctx, self.entry, self.task, self.runs)
        return self._board

    def board_labels(self) -> dict[str, str]:
        """Leaderboard label per seed-group id."""
        return {row.group_id: row.label for row in self.board().rows}


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
    return _panel(ctx, project, task, panel, runs_filter, {})


def query_view(ctx: Context, project: str, task: str, view: ViewSpec) -> list[PanelResult]:
    """
    Compute every panel of a view, in order.

    The view must already be resolved (``views.get_view`` returns resolved
    views). A panel that fails with a Hypothex error yields an empty result
    whose ``meta.error`` holds the message, so one bad panel never hides the
    others.

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
    entries: dict[str, ProjectEntry] = {}
    out: list[PanelResult] = []
    for panel in view.panels:
        try:
            out.append(_panel(ctx, project, task, panel, view.runs, entries))
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
    entries: dict[str, ProjectEntry],
) -> PanelResult:
    """Dispatch one panel; ``entries`` caches refreshed projects across a view."""
    if panel.type == "markdown":
        return _markdown(panel)
    if panel.type == "trace" and panel.data.run_id:
        return _trace_for(ctx, panel, panel.data.run_id, panel.data.example_id)
    if project not in entries:
        entries[project] = refresh_project(ctx, project)
    return _query(ctx, entries[project], task, panel, runs_filter)


def _query(
    ctx: Context,
    entry: ProjectEntry,
    task: str,
    panel: PanelSpec,
    runs_filter: RunFilter | None,
) -> PanelResult:
    if task not in entry.config.tasks:
        raise ConfigError(f"unknown task {task!r} in project {entry.project!r}")
    runs = ctx.index.list_runs(project=entry.project, task=task, limit=None)
    runs.sort(key=lambda r: (r.created_at, r.run_id))
    if runs_filter is not None:
        runs = [r for r in runs if _run_matches(r, runs_filter)]
    if panel.data.filter and panel.type not in ("table", "vega_lite"):
        keep = {
            row["run_id"]
            for row in iter_rows(ctx, runs, "runs")
            if _row_matches(row, panel.data.filter)
        }
        runs = [r for r in runs if r.run_id in keep]
    if panel.data.pick == "latest":
        latest = {group_id_for(r): r.run_id for r in runs}
        runs = [r for r in runs if r.run_id in set(latest.values())]
    elif panel.data.pick == "best":
        board_rows = _build_board(ctx, entry, task, runs).rows
        best = set(board_rows[0].run_ids) if board_rows else set()
        runs = [r for r in runs if r.run_id in best]
    scope = _Scope(ctx=ctx, entry=entry, task=task, runs=runs)
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
    per_example = primary_examples(ctx, entry.config, task, runs, None)
    scores = ctx.index.scores_for(r.run_id for r in runs)
    return build_leaderboard(
        entry.project, task, entry.config, runs, scores, per_example=per_example or None
    )


def _markdown(panel: PanelSpec) -> PanelResult:
    return PanelResult(type="markdown", title=panel.title, rows=[], meta={"text": panel.text or ""})


def _stat_strip(scope: _Scope, panel: PanelSpec) -> PanelResult:
    board = scope.board()
    return PanelResult(
        type="stat_strip",
        title=panel.title,
        rows=[dict(item) for item in board.stat_strip],
        meta={"headline": board.headline},
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
    works on a table that shows only ``status``.
    """
    source = panel.data.source or "runs"
    fields = panel.data.fields
    versions = _run_versions(scope) if source == "runs" else {}
    rows: list[dict[str, Any]] = []
    total = 0
    for row in iter_rows(scope.ctx, scope.runs, source):
        if versions:
            row[VERSION_REF] = versions[row["run_id"]][1]
        if panel.data.filter and not _row_matches(row, panel.data.filter):
            continue
        total += 1
        if len(rows) < MAX_TABLE_ROWS:
            rows.append(select_fields(row, fields))
    meta: dict[str, Any] = {"source": source, "total": total}
    if total > MAX_TABLE_ROWS:
        meta["warnings"] = [f"showing the first {MAX_TABLE_ROWS} of {total} rows"]
    return rows, meta


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


def _own_label(members: list[RunRecord], key: str) -> str:
    """``group_label`` of the newest non-empty hypothesis and the group's tags."""
    hypothesis = next((r.hypothesis for r in reversed(members) if r.hypothesis.strip()), "")
    return group_label(hypothesis, (t for r in members for t in r.tags), key)


def _groups(scope: _Scope, panel: PanelSpec) -> list[tuple[str, str, list[RunRecord]]]:
    """Return ``(key, label, members)`` per group, in order of first run."""
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
    labels = scope.board_labels() if by == "group" else {}
    out: list[tuple[str, str, list[RunRecord]]] = []
    for key, runs in members.items():
        label = f"seed {runs[0].seed}" if by == "seed" else labels.get(key)
        out.append((key, label or _own_label(runs, key), runs))
    return out


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


def _checkpoints(scope: _Scope, run: RunRecord) -> list[Artifact]:
    logged = scope.ctx.store.read_artifacts(run.project, run.run_id)
    merged = {(a.kind, a.path): a for a in [*run.artifacts, *logged]}
    return sorted(
        (a for a in merged.values() if a.kind == "checkpoint" and a.step is not None),
        key=lambda a: a.step or 0,
    )


def _curves(scope: _Scope, panel: PanelSpec) -> PanelResult:
    wanted = panel.data.metrics
    x_name = panel.data.step_metric or "step"
    rows: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    groups: list[dict[str, str]] = []
    group_of: dict[str, str] = {}
    for key, label, members in _groups(scope, panel):
        groups.append({"group_id": key, "label": label})
        for r in members:
            group_of[r.run_id] = key
    names_seen: list[str] = []
    for run in scope.runs:
        points = scope.ctx.store.read_metric_points(run.project, run.run_id)
        by_name: dict[str, list[MetricPoint]] = defaultdict(list)
        for p in points:
            by_name[p.name].append(p)
        x_of: dict[int, float] | None = None
        if x_name != "step":
            x_of = {p.step: p.value for p in by_name.get(x_name, [])}
        names = wanted if wanted is not None else sorted(n for n in by_name if n != x_name)
        run_events: list[dict[str, Any]] = []
        last_x: float | None = None
        for name in names:
            series = sorted(by_name.get(name, []), key=lambda p: p.step)
            if series and name not in names_seen:
                names_seen.append(name)
            for p in series:
                x = p.step if x_of is None else x_of.get(p.step)
                if x is None:
                    continue
                last_x = x if last_x is None else max(last_x, x)
                rows.append(
                    {
                        "run_id": run.run_id,
                        "group_id": group_of[run.run_id],
                        "seed": run.seed,
                        "name": name,
                        "step": x,
                        "value": p.value,
                    }
                )
            if "loss" in name.lower():
                for step in _spikes(series):
                    x = step if x_of is None else x_of.get(step)
                    if x is not None:
                        run_events.append({"run_id": run.run_id, "step": x, "kind": "spike"})
        if run.status in (RunStatus.KILLED, RunStatus.FAILED) and last_x is not None:
            run_events.append({"run_id": run.run_id, "step": last_x, "kind": run.status.value})
        events.extend(sorted(run_events, key=lambda e: e["step"]))
        checkpoints.extend(_checkpoint_rows(scope, run, panel, x_of))
    return PanelResult(
        type="curves",
        title=panel.title,
        rows=rows,
        meta={
            "x": x_name,
            "metrics": names_seen,
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


_HANDLERS = {
    "stat_strip": _stat_strip,
    "leaderboard": _leaderboard,
    "curves": _curves,
    "table": _table,
    "vega_lite": _vega_lite,
    "trace": _trace,
}
