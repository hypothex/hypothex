"""Read models and curation actions shared by the CLI, API, and MCP server."""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import json
import math
import shlex
import weakref
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

from pydantic import BaseModel, Field

from hypothex.core import stats
from hypothex.core.config import (
    ProjectConfig,
    load_project_config,
    parse_metric_key,
    parse_metric_version,
)
from hypothex.core.context import Context
from hypothex.core.datasets import (
    DatasetDrift,
    FingerprintCache,
    OverlapReport,
    check_runs,
    overlap,
    resolve_dataset_path,
)
from hypothex.core.errors import ConfigError, EvalError, RunError, StoreError
from hypothex.core.fsutil import read_jsonl, read_yaml
from hypothex.core.index import Index
from hypothex.core.leaderboard import Leaderboard, build_leaderboard, cached_leaderboard
from hypothex.core.records import (
    INDEXED_POINT_STATUSES,
    MetricPoint,
    RunRecord,
    RunStatus,
    ScoreRecord,
)
from hypothex.core.store import ProjectEntry

LOG_TAIL_BYTES = 8 * 1024 * 1024
LOG_TAIL_LINES = 5000
LOG_STREAMS = ("stdout", "stderr", "supervisor")


class TaskSummary(BaseModel):
    """A task with its current metric versions and best primary value."""

    project: str
    name: str
    description: str
    dataset: str
    dataset_version: str
    split: str | None
    metrics: dict[str, str]
    primary: str
    higher_is_better: bool
    n_runs: int
    best: float | None


class RunDetail(BaseModel):
    """Everything about one run, including where every file lives."""

    record: RunRecord
    scores: list[ScoreRecord]
    paths: dict[str, str]
    notes: str
    has_diff: bool
    metric_names: list[str]
    children: list[str]


class Comparison(BaseModel):
    """Differences between two or more runs."""

    run_ids: list[str]
    fields: dict[str, list[Any]]
    scores: dict[str, list[float | None]]


class PredictionRow(BaseModel):
    """One example with its per-example scores."""

    id: str
    prediction: Any = None
    reference: Any = None
    scores: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PredictionPage(BaseModel):
    """A page of predictions."""

    run_id: str
    total: int
    offset: int
    limit: int
    rows: list[PredictionRow]


class ExampleDiff(BaseModel):
    """Which examples one run fixed or broke relative to another."""

    a: str
    b: str
    metric: str
    field: str
    fixed: list[str]
    broken: list[str]
    both_pass: int
    both_fail: int


class LogChunk(BaseModel):
    """A slice of a run log; pass ``offset`` back to continue."""

    stream: str
    text: str
    offset: int
    size: int


# projects and tasks ----------------------------------------------------------
def refresh_project(ctx: Context, project: str) -> ProjectEntry:
    """
    Re-read a project's ``hypothex.yaml`` so views use the current config.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.

    Returns
    -------
    ProjectEntry
        The refreshed entry, or the stored snapshot if the repo is gone, the
        file is invalid, or the entry is a copy from a host
        (``remote_host``): its repo path is on that host, so it is never read
        here.

    Notes
    -----
    The project is registered again only when the parsed config or the repo
    path changed. A read never rewrites an unchanged ``project.json``: that
    write would change ``registered_at``, bump the index generation, and
    change the project folder's mtime, which makes the next ``Context.open``
    scan every run folder.
    """
    entry = ctx.store.load_project(project)
    try:
        repo = ctx.local_repo(project)
        config = load_project_config(repo)
    except ConfigError:  # includes RemoteProjectError
        return entry
    if config == entry.config and str(repo.resolve()) == entry.repo:
        return entry
    return ctx.register_project(repo)


def list_projects(ctx: Context) -> list[ProjectEntry]:
    """
    Return all projects with a refreshed config snapshot.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.

    Returns
    -------
    list of ProjectEntry
    """
    return [refresh_project(ctx, e.project) for e in ctx.store.list_projects()]


def resolve_task(ctx: Context, ref: str, project: str | None = None) -> tuple[ProjectEntry, str]:
    """
    Find a task by ``task`` or ``project/task``.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    ref : str
        Task name, or ``project/task``.
    project : str, optional
        Project to restrict the search to.

    Returns
    -------
    tuple of (ProjectEntry, str)
        The owning project and the task name.

    Raises
    ------
    ConfigError
        Unknown or ambiguous task.
    """
    if project is None and "/" in ref:
        project, ref = ref.split("/", 1)
    entries = [refresh_project(ctx, project)] if project else list_projects(ctx)
    matches = [e for e in entries if ref in e.config.tasks]
    if not matches:
        where = f" in project {project!r}" if project else ""
        raise ConfigError(f"unknown task {ref!r}{where}")
    if len(matches) > 1:
        names = ", ".join(sorted(e.project for e in matches))
        raise ConfigError(f"task {ref!r} exists in several projects ({names}); use project/task")
    return matches[0], ref


def primary_examples(
    ctx: Context,
    config: ProjectConfig,
    task: str,
    runs: list[RunRecord],
    versions: dict[str, str] | None,
    *,
    primary: str | None = None,
    hashes: dict[str, str] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """
    Load the per-example scores of a task's primary metric for its leaderboard runs.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    config : ProjectConfig
        The project's config.
    task : str
        Task name.
    runs : list of RunRecord
        Candidate runs; only finished, unarchived runs of ``task`` are read.
    versions : dict of str to str or None
        Metric version overrides; default is each metric's current version.
    primary : str, optional
        Selected task metric/key; default the configured task primary.
    hashes : dict of str to str, optional
        Populated with SHA256 of the exact bytes parsed for each run.

    Returns
    -------
    dict
        run_id -> example_id -> per-example fields (without ``id``), read from
        ``predictions/scores.<metric>@<version>.jsonl``. Runs without that file
        are left out.
    """
    metric, _ = parse_metric_key(primary or config.tasks[task].primary)
    if metric not in config.tasks[task].metrics:
        raise ConfigError(f"unknown leaderboard primary {primary!r} for task {task!r}")
    version = (versions or {}).get(metric, config.metrics[metric].version)
    name = f"scores.{metric}@{version}.jsonl"
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for r in runs:
        if r.task != task or r.status != RunStatus.FINISHED or r.archived:
            continue
        path = ctx.run_dir(r) / "predictions" / name
        if path.is_file():
            raw = path.read_bytes()
            rows: list[dict[str, Any]] = []
            for line in raw.decode("utf-8").splitlines():
                try:
                    value = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and "id" in value:
                    rows.append(value)
            out[r.run_id] = {
                str(row["id"]): {k: v for k, v in row.items() if k != "id"} for row in rows
            }
            if hashes is not None:
                hashes[r.run_id] = "sha256:" + hashlib.sha256(raw).hexdigest()
    return out


def get_leaderboard(
    ctx: Context,
    ref: str,
    project: str | None = None,
    versions: dict[str, str] | None = None,
    *,
    examples: bool = True,
    primary: str | None = None,
) -> Leaderboard:
    """
    Build the leaderboard of a task from indexed runs, scores, and per-example scores.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    ref : str
        Task name, or ``project/task``.
    project : str, optional
        Project to restrict the search to.
    versions : dict of str to str, optional
        Metric version overrides; default is each metric's current version.
    examples : bool
        Read each run's per-example scores of the primary metric
        (``predictions/scores.<metric>@<version>.jsonl``) for test-set
        intervals and paired tests. ``False`` skips the file reads.
    primary : str, optional
        Selected task metric/key, independently of version pins. Recomputes
        ranking and evidence without changing the project configuration.

    Returns
    -------
    Leaderboard
    """
    entry, task = resolve_task(ctx, ref, project)
    return _board(ctx, entry, task, versions, examples=examples, primary=primary)


def _board(
    ctx: Context,
    entry: ProjectEntry,
    task: str,
    versions: dict[str, str] | None,
    *,
    examples: bool,
    primary: str | None = None,
) -> Leaderboard:
    def build() -> Leaderboard:
        runs = ctx.index.list_runs(
            project=entry.project, task=task, include_archived=True, limit=None
        )
        scores = ctx.index.scores_for(r.run_id for r in runs)
        hashes: dict[str, str] = {}
        per_example = (
            primary_examples(
                ctx, entry.config, task, runs, versions, primary=primary, hashes=hashes
            )
            if examples
            else None
        )
        return build_leaderboard(
            entry.project,
            task,
            entry.config,
            runs,
            scores,
            versions,
            per_example=per_example,
            per_example_hashes=hashes,
            primary=primary,
        )

    return cached_leaderboard(
        ctx,
        entry.project,
        task,
        entry.config,
        build,
        versions=versions,
        variant=("examples", examples, "primary", primary),
    )


class _Ranked(NamedTuple):
    """What a task summary takes from the index, and the state it was read at."""

    generation: int
    config: ProjectConfig
    primary: str
    higher_is_better: bool
    best: float | None
    n_runs: int


_RANKED: weakref.WeakKeyDictionary[Index, dict[tuple[str, str], _Ranked]] = (
    weakref.WeakKeyDictionary()
)
"""Per index, the last ``_Ranked`` of each ``(project, task)``."""


def _ranked(ctx: Context, entry: ProjectEntry, name: str) -> _Ranked:
    """
    Rank a task's runs, or reuse the last ranking while nothing it reads changed.

    The ranking reads only the index and the project config, so it is reused
    while the index generation and the config are the same (a task list
    request then builds no leaderboard).
    """
    memo = _RANKED.setdefault(ctx.index, {})
    generation = ctx.index.generation()  # read first: a write during the build reruns it
    cached = memo.get((entry.project, name))
    if cached is not None and cached.generation == generation and cached.config == entry.config:
        return cached
    board = _board(ctx, entry, name, None, examples=False)
    top = board.rows[0].primary if board.rows else None
    ranked = _Ranked(
        generation=generation,
        config=entry.config,
        primary=board.primary,
        higher_is_better=board.higher_is_better,
        best=top.mean if top else None,
        n_runs=ctx.index.count_runs(project=entry.project, task=name, status=RunStatus.FINISHED),
    )
    memo[(entry.project, name)] = ranked
    return ranked


def _summary(ctx: Context, entry: ProjectEntry, name: str) -> TaskSummary:
    spec = entry.config.tasks[name]
    ranked = _ranked(ctx, entry, name)
    return TaskSummary(
        project=entry.project,
        name=name,
        description=spec.description,
        dataset=spec.dataset,
        dataset_version=entry.config.datasets[spec.dataset].version,
        split=spec.split,
        metrics={m: entry.config.metrics[m].version for m in spec.metrics},
        primary=ranked.primary,
        higher_is_better=ranked.higher_is_better,
        n_runs=ranked.n_runs,
        best=ranked.best,
    )


def list_tasks(ctx: Context, project: str | None = None) -> list[TaskSummary]:
    """
    Summarize every task, optionally for one project.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str, optional
        Restrict to one project.

    Returns
    -------
    list of TaskSummary
    """
    entries = [refresh_project(ctx, project)] if project else list_projects(ctx)
    return [_summary(ctx, e, name) for e in entries for name in sorted(e.config.tasks)]


def get_task(ctx: Context, ref: str, project: str | None = None) -> dict[str, Any]:
    """
    Return a task's summary plus its dataset, metric, and stage definitions.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    ref : str
        Task name, or ``project/task``.
    project : str, optional
        Project to restrict the search to.

    Returns
    -------
    dict
        ``dataset`` holds the config as written; a dataset of a local project
        on this host also has ``resolved_path`` and ``resolved_splits`` (absolute
        paths). A remote project's paths are never resolved on this machine.
    """
    entry, name = resolve_task(ctx, ref, project)
    spec = entry.config.tasks[name]
    ds = entry.config.datasets[spec.dataset]
    dataset: dict[str, Any] = {"name": spec.dataset, **ds.model_dump(mode="json")}
    if entry.remote_host is None and ds.host in ("local", ctx.descriptor.label):
        repo = ctx.local_repo(entry.project)
        dataset["resolved_path"] = str(resolve_dataset_path(repo, ds.path))
        dataset["resolved_splits"] = {
            k: str(resolve_dataset_path(repo, v)) for k, v in ds.splits.items()
        }
    return {
        "summary": _summary(ctx, entry, name).model_dump(mode="json"),
        "repo": entry.repo,
        "dataset": dataset,
        "metrics": {m: entry.config.metrics[m].model_dump(mode="json") for m in spec.metrics},
        "stages": entry.config.stages,
    }


# runs ----------------------------------------------------------------------------
def with_queue_positions(ctx: Context, records: list[RunRecord]) -> list[RunRecord]:
    """
    Copy queued records with live positions instead of their stored queue tickets.

    Parameters
    ----------
    ctx : Context
        Open context; ranking always includes the complete queue on each host.
    records : list of RunRecord
        Records selected for a response, possibly filtered or paginated.

    Returns
    -------
    list of RunRecord
        Response copies. Stored records and their stable tickets are unchanged.

    Examples
    --------
    >>> with_queue_positions(ctx, [])  # doctest: +SKIP
    []
    """
    queued = [r for r in records if r.status == RunStatus.QUEUED]
    if not queued:
        return records
    from hypothex.core.execution import QUEUE_FILE
    from hypothex.core.scheduler import Scheduler

    # QUEUED also describes a prepared run that has never joined a GPU queue.
    # Only real queue members need the global rank lookup. A local marker can
    # precede its ticket if enqueue is still running or stopped between writes.
    if not any(
        r.executor.queue_position is not None
        or (
            r.environment_id == ctx.descriptor.environment_id
            and (ctx.run_dir(r) / QUEUE_FILE).is_file()
        )
        for r in queued
    ):
        return records
    positions = Scheduler(ctx).positions()
    remote: dict[str, list[RunRecord]] = defaultdict(list)
    for record in ctx.index.list_runs(status=RunStatus.QUEUED, include_archived=True, limit=None):
        if (
            record.environment_id != ctx.descriptor.environment_id
            and record.executor.queue_position is not None
        ):
            remote[record.environment_id].append(record)
    for waiting in remote.values():
        waiting.sort(key=lambda r: (r.executor.queue_position or 0, r.created_at, r.run_id))
        positions.update({r.run_id: i for i, r in enumerate(waiting, start=1)})
    return [
        r.model_copy(
            update={
                "executor": r.executor.model_copy(update={"queue_position": positions[r.run_id]})
            }
        )
        if r.run_id in positions
        else r
        for r in records
    ]


def show_run(ctx: Context, run_id: str) -> RunDetail:
    """
    Return a run with its scores, notes, children, and all file paths.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_id : str
        Run id to look up.

    Returns
    -------
    RunDetail
        ``paths`` also names ``run_yaml``, ``scores``, ``metrics``, ``notes``,
        ``config`` and ``diff`` when the run has those files. ``metric_names``
        reads live names from the bounded file policy for queued, running and
        lost runs; finished, failed and killed runs use exact indexed names.
    """
    record = with_queue_positions(ctx, [ctx.find_record(run_id)])[0]
    run_dir = ctx.run_dir(record)
    paths = {
        "run_dir": str(run_dir),
        "cwd": record.cwd,
        "stdout": str(run_dir / "logs" / "stdout.log"),
        "stderr": str(run_dir / "logs" / "stderr.log"),
        "predictions": str(run_dir / "predictions"),
        "env": str(run_dir / "env"),
    }
    with contextlib.suppress(StoreError):
        paths["repo"] = ctx.store.load_project(record.project).repo
    files = {
        "run_yaml": "run.yaml",
        "config": "config.yaml",
        "scores": "scores.jsonl",
        "metrics": "metrics.jsonl",
        "notes": "notes.md",
        "diff": "git.diff",
    }
    for key, name in files.items():
        if (run_dir / name).is_file():
            paths[key] = str(run_dir / name)
    from hypothex.remote.hub import host_paths

    hosted = host_paths(ctx, record)
    if "run_dir" in hosted:
        for key, path in list(paths.items()):
            local = Path(path)
            if local.is_relative_to(run_dir):
                relative = local.relative_to(run_dir)
                paths[key] = hosted["run_dir"] + (f"/{relative}" if relative.parts else "")
    paths.update(hosted)
    for ref in record.datasets:
        paths[f"dataset:{ref.name}"] = f"{ref.host}:{ref.path}"
    for i, art in enumerate(record.artifacts):
        paths[f"artifact:{art.kind}:{i}"] = f"{art.host}:{art.path}"
    return RunDetail(
        record=record,
        scores=ctx.store.read_scores(record.project, run_id),
        paths=paths,
        notes=ctx.store.read_notes(record.project, run_id),
        has_diff="diff" in paths,
        metric_names=(
            ctx.index.metric_names(run_id)
            if record.status in INDEXED_POINT_STATUSES
            else ctx.store.read_metric_names_bounded(record.project, run_id)
        ),
        children=sorted(ctx.index.child_run_ids(run_id)),
    )


def lttb(series: list[MetricPoint], limit: int) -> list[MetricPoint]:
    """
    Downsample one series with Largest-Triangle-Three-Buckets (``stats.lttb``).

    The first and last points are always kept, and peaks and dips survive,
    unlike every-n-th sampling. Kept points are returned as they are (no
    averaging).

    Parameters
    ----------
    series : list of MetricPoint
        One metric's points, ordered by step.
    limit : int
        Maximum points to return; at least 2.

    Returns
    -------
    list of MetricPoint
        ``series`` itself when it has at most ``limit`` points.

    Raises
    ------
    RunError
        If ``limit`` is less than 2.

    Examples
    --------
    >>> pts = [MetricPoint(name="loss", step=i, value=v) for i, v in enumerate([0, 1, 9, 1, 0])]
    >>> [p.value for p in lttb(pts, 3)]
    [0.0, 9.0, 0.0]
    """
    if limit < 2:
        raise RunError(f"max_points must be at least 2, not {limit}")
    keep = stats.lttb([p.step for p in series], [p.value for p in series], limit)
    return series if len(keep) == len(series) else [series[i] for i in keep]


def metric_history(
    ctx: Context,
    run_id: str,
    names: Iterable[str] | None = None,
    max_points: int | None = None,
) -> list[MetricPoint]:
    """
    Return a run's indexed (downsampled) metric history.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_id : str
        Run id to look up.
    names : iterable of str, optional
        Metric names to return; ``None`` returns every name. The filter runs
        in SQL, so a chart of two names reads only their rows.
    max_points : int, optional
        Keep at most this many points per name (at least 2), picked with
        ``lttb``. ``None`` returns the indexed points (up to
        ``MAX_POINTS_PER_METRIC`` per name).

    Returns
    -------
    list of MetricPoint
        Ordered by name, then step.

    Raises
    ------
    RunError
        If ``max_points`` is less than 2.

    Examples
    --------
    >>> metric_history(ctx, run_id, names=["train/loss"], max_points=500)  # doctest: +SKIP
    [MetricPoint(name='train/loss', step=0, value=2.3, t=None), ...]
    """
    if max_points is not None and max_points < 2:
        raise RunError(f"max_points must be at least 2, not {max_points}")
    ctx.find_record(run_id)
    points = ctx.index.metric_points_for([run_id], names).get(run_id, [])
    if max_points is None:
        return points
    out: list[MetricPoint] = []
    for _, series in itertools.groupby(points, key=lambda p: p.name):
        out.extend(lttb(list(series), max_points))
    return out


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}", v, out)
    else:
        out[prefix] = value


def compare_runs(ctx: Context, run_ids: list[str]) -> Comparison:
    """
    Compare runs: only fields that differ, plus the latest score per metric version.

    Fields cover the task, commit, ``dirty`` (uncommitted changes), ``diff`` hash, seed,
    stage, command, hypothesis, ``params.*``, ``vars.*`` and ``config.*``.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_ids : list of str
        Run ids to compare; at least two.

    Returns
    -------
    Comparison

    Raises
    ------
    RunError
        With fewer than two runs.
    """
    if len(run_ids) < 2:
        raise RunError("compare needs at least two runs")
    records = [ctx.find_record(r) for r in run_ids]
    flat: list[dict[str, Any]] = []
    for rec in records:
        f: dict[str, Any] = {
            "task": rec.task,
            "commit": rec.git.commit,
            "dirty": rec.git.dirty,
            "diff": rec.git.diff_hash,
            "seed": rec.seed,
            "stage": rec.stage,
            "command": shlex.join(rec.command_template),
            "hypothesis": rec.hypothesis,
        }
        _flatten("params", rec.params, f)
        _flatten("vars", rec.vars, f)
        cfg = ctx.run_dir(rec) / "config.yaml"
        if cfg.is_file():
            _flatten("config", read_yaml(cfg), f)
        flat.append(f)
    keys = sorted(set().union(*flat))
    fields = {
        k: [f.get(k) for f in flat]
        for k in keys
        if len({json.dumps(f.get(k), sort_keys=True, default=str) for f in flat}) > 1
    }
    all_scores = ctx.index.scores_for(run_ids)
    latest: list[dict[str, float | None]] = []
    for rid in run_ids:
        row: dict[str, float | None] = {}
        for s in sorted(all_scores.get(rid, []), key=lambda s: s.created_at):
            if s.error is None:
                row[f"{s.metric}@{s.version}/{s.key}"] = s.value
        latest.append(row)
    score_keys = sorted(set().union(*latest))
    return Comparison(
        run_ids=run_ids,
        fields=fields,
        scores={k: [row.get(k) for row in latest] for k in score_keys},
    )


def _references(ctx: Context, record: RunRecord) -> dict[str, Any]:
    if record.task is None:
        return {}
    try:
        repo = ctx.local_repo(record.project)
        config = load_project_config(repo)
        spec = config.tasks[record.task]
    except (StoreError, ConfigError, KeyError):  # ConfigError includes a host's copy
        return {}
    ds = config.datasets[spec.dataset]
    path = resolve_dataset_path(repo, ds.path_for(spec.split))
    return {
        str(r[ds.id_field]): r.get(ds.reference_field) for r in read_jsonl(path) if ds.id_field in r
    }


def _per_example(run_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for path in sorted((run_dir / "predictions").glob("scores.*.jsonl")):
        ref = path.name[len("scores.") : -len(".jsonl")]
        out[ref] = {
            str(r["id"]): {k: v for k, v in r.items() if k != "id"}
            for r in read_jsonl(path)
            if "id" in r
        }
    return out


def _resolve_metric(
    ctx: Context, record: RunRecord, per: dict[str, Any], metric: str
) -> tuple[str, str | None]:
    """
    Check a metric name for a run and give a bare name its current version.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    record : RunRecord
        The run whose per-example scores are read.
    per : dict
        The run's per-example scores, keyed by ``name@version``.
    metric : str
        ``name`` or ``name@version`` asked for.

    Returns
    -------
    tuple of (str, str or None)
        Metric name and version. A bare name gets the version in
        ``hypothex.yaml``; ``None`` only when the metric is no longer there.

    Raises
    ------
    ConfigError
        If the name is neither a metric of the run's task nor scored on
        disk; the message lists the known names.
    """
    name, version = parse_metric_version(metric)
    known = {parse_metric_version(k)[0] for k in per}
    current: dict[str, str] = {}
    with contextlib.suppress(StoreError):
        config = refresh_project(ctx, record.project).config
        spec = config.tasks.get(record.task or "")
        known.update(spec.metrics if spec else ())
        current = {m: c.version for m, c in config.metrics.items()}
    if name not in known:
        names = ", ".join(sorted(known)) or "none"
        raise ConfigError(f"unknown metric {name!r} for run {record.run_id}; known: {names}")
    return name, version or current.get(name)


def _require_field(per: dict[str, dict[str, dict[str, Any]]], field: str) -> None:
    """
    Raise unless some per-example row of ``per`` has ``field``.

    Parameters
    ----------
    per : dict
        ``name@version`` -> example id -> per-example fields.
    field : str
        Per-example field that marks success.

    Raises
    ------
    EvalError
        If no row has ``field``; the message lists the fields there are.
    """
    fields = {k for rows in per.values() for row in rows.values() for k in row}
    if field not in fields:
        raise EvalError(
            f"no per-example field {field!r} in {', '.join(sorted(per))}; "
            f"fields: {', '.join(sorted(fields)) or 'none'}"
        )


def _is_failure(value: Any) -> bool:
    return value is False or (isinstance(value, int | float) and value == 0)


def get_predictions(
    ctx: Context,
    run_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
    metric: str | None = None,
    failures_only: bool = False,
    field: str = "correct",
) -> PredictionPage:
    """
    Page through a run's predictions with references and per-example scores.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_id : str
        Run id to look up.
    offset : int
        First row to return.
    limit : int
        Maximum rows to return.
    metric : str, optional
        ``name`` (current version) or ``name@version`` to limit which
        per-example scores are shown.
    failures_only : bool
        Keep rows where ``field`` is False or 0 in a shown metric.
    field : str
        Per-example field that marks success.

    Returns
    -------
    PredictionPage

    Raises
    ------
    ConfigError
        ``metric`` is neither a metric of the run's task nor scored on disk.
    EvalError
        ``failures_only`` without any per-example scores, or with a
        ``field`` that no shown metric has.
    """
    record = ctx.find_record(run_id)
    run_dir = ctx.run_dir(record)
    per = _per_example(run_dir)
    if metric is not None:
        name, version = _resolve_metric(ctx, record, per, metric)
        per = {
            k: v
            for k, v in per.items()
            if k == f"{name}@{version}" or (version is None and k.split("@")[0] == name)
        }
    refs = _references(ctx, record)
    rows = [
        PredictionRow(
            id=str(r["id"]),
            prediction=r.get("prediction"),
            reference=r["reference"] if "reference" in r else refs.get(str(r["id"])),
            scores={m: d.get(str(r["id"]), {}) for m, d in per.items()},
        )
        for r in read_jsonl(run_dir / "predictions" / "predictions.jsonl")
        if "id" in r
    ]
    if failures_only:
        if not per:
            raise EvalError("no per-example scores for this run; run `hx reeval` first")
        _require_field(per, field)
        rows = [
            row
            for row in rows
            if any(field in s and _is_failure(s[field]) for s in row.scores.values())
        ]
    return PredictionPage(
        run_id=run_id,
        total=len(rows),
        offset=offset,
        limit=limit,
        rows=rows[offset : offset + limit],
    )


def _bound_example_pair(
    ctx: Context,
    a: str,
    b: str,
    name: str,
    version: str,
    field: str,
) -> list[dict[str, bool]]:
    """Read a coherent pair of current evaluator-bound binary outcome snapshots."""
    ref = f"{name}@{version}"
    records = [ctx.find_record(rid) for rid in (a, b)]
    initial_scores = ctx.index.scores_for((a, b))
    files: list[tuple[Path, bytes]] = []
    populations: list[tuple[object, ...]] = []
    passed: list[dict[str, bool]] = []
    for record in records:
        rid = record.run_id
        if record.status != RunStatus.FINISHED or record.archived or record.task is None:
            raise EvalError(f"run {rid} is not a finished current comparison member")
        candidates = [
            s for s in initial_scores.get(rid, []) if s.metric == name and s.version == version
        ]
        if not candidates:
            raise EvalError(f"run {rid} has no bound evaluation for {ref}")
        latest_at = max(s.created_at for s in candidates)
        batch = [s for s in candidates if s.created_at == latest_at]
        if any(
            s.error is not None
            or s.key == "*"
            or s.value is None
            or not math.isfinite(s.value)
            or not s.source_hash
            or not s.per_example_hash
            or s.evaluation_examples is None
            or not s.evaluation_ids_hash
            for s in batch
        ):
            raise EvalError(f"run {rid} has no healthy bound current evaluation for {ref}")
        evidence = {
            (s.source_hash, s.per_example_hash, s.evaluation_examples, s.evaluation_ids_hash)
            for s in batch
        }
        if len(evidence) != 1:
            raise EvalError(f"run {rid} has inconsistent evaluation bindings for {ref}")
        source, digest, count, ids_digest = next(iter(evidence))
        path = ctx.run_dir(record) / "predictions" / f"scores.{ref}.jsonl"
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise EvalError(f"run {rid} has no bound per-example artifact for {ref}") from exc
        if "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
            raise EvalError(f"run {rid} per-example artifact does not match its bound evaluation")
        try:
            rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvalError(f"run {rid} has malformed bound per-example data") from exc
        if any(not isinstance(row, dict) or "id" not in row for row in rows):
            raise EvalError(f"run {rid} has malformed bound per-example rows")
        ids = [str(row["id"]) for row in rows]
        if (
            not ids
            or len(ids) != len(set(ids))
            or len(ids) != count
            or "sha256:" + hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()
            != ids_digest
        ):
            raise EvalError(f"run {rid} per-example population does not match its bound evaluation")
        if any(
            type(row.get(field)) not in (bool, int, float) or row[field] not in (0, 1)
            for row in rows
        ):
            raise EvalError(
                f"run {rid} has no complete binary {field!r} field in its bound evaluation"
            )
        config = refresh_project(ctx, record.project).config
        spec = config.tasks.get(record.task)
        refs = [
            r
            for r in record.datasets
            if spec is not None and r.name == spec.dataset and r.split == spec.split
        ]
        if len(refs) != 1 or not refs[0].hash:
            raise EvalError(f"run {rid} has no known comparison dataset identity")
        dataset = refs[0]
        populations.append(
            (
                record.project,
                record.task,
                source,
                dataset.name,
                dataset.version,
                dataset.split,
                dataset.hash,
                dataset.hash_mode,
            )
        )
        passed.append({str(row["id"]): bool(row[field]) for row in rows})
        files.append((path, raw))
    if populations[0] != populations[1]:
        raise EvalError(
            "comparison runs do not share project/task, evaluator source and dataset identity"
        )
    # Atomic evaluator file replacement and appended score records can race a
    # query. Use only the bytes validated above, then reject observed changes.
    for path, raw in files:
        try:
            current = path.read_bytes()
        except OSError as exc:
            raise EvalError("bound comparison artifact changed during the query; retry") from exc
        if current != raw:
            raise EvalError("bound comparison artifact changed during the query; retry")
    if ctx.index.scores_for((a, b)) != initial_scores:
        raise EvalError("bound comparison evaluation changed during the query; retry")
    if any(ctx.find_record(record.run_id) != record for record in records):
        raise EvalError("bound comparison run identity changed during the query; retry")
    return passed


def compare_examples(
    ctx: Context,
    a: str,
    b: str,
    metric: str,
    field: str = "correct",
    *,
    require_bound: bool = False,
) -> ExampleDiff:
    """
    List examples fixed (fail in ``a``, pass in ``b``) and broken (the reverse).

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    a : str
        First run id.
    b : str
        Second run id.
    metric : str
        ``name`` (current version) or ``name@version``.
    field : str
        Per-example field that marks success.
    require_bound : bool
        Require current successful evaluator-issued artifact/population bindings,
        complete binary outcomes and matching dataset/source identity. False
        preserves the existing Examples behavior for legacy score files.

    Returns
    -------
    ExampleDiff

    Raises
    ------
    ConfigError
        Unknown metric name, or a bare name no longer in ``hypothex.yaml``.
    EvalError
        A run without per-example scores for the metric, or without ``field``.
        Strict comparisons also reject absent, stale, partial, incompatible or
        concurrently changed evaluation evidence.
    """
    rec_a = ctx.find_record(a)
    if require_bound:
        # Only metric names are needed for resolution. Strict comparison reads
        # the selected artifact itself once for hash and outcome verification.
        known = {
            path.name[len("scores.") : -len(".jsonl")]: {}
            for path in (ctx.run_dir(rec_a) / "predictions").glob("scores.*.jsonl")
        }
    else:
        known = _per_example(ctx.run_dir(rec_a))
    name, version = _resolve_metric(ctx, rec_a, known, metric)
    if version is None:
        raise ConfigError(f"metric {name!r} is not in hypothex.yaml; pass {name}@<version>")
    ref = f"{name}@{version}"
    if require_bound:
        passed = _bound_example_pair(ctx, a, b, name, version, field)
    else:
        passed: list[dict[str, bool]] = []
        for rid in (a, b):
            per = _per_example(ctx.run_dir(ctx.find_record(rid))).get(ref)
            if per is None:
                raise EvalError(f"run {rid} has no per-example scores for {ref}")
            _require_field({ref: per}, field)
            passed.append({i: not _is_failure(v.get(field)) for i, v in per.items() if field in v})
    pa, pb = passed
    ids = sorted(pa.keys() & pb.keys())
    return ExampleDiff(
        a=a,
        b=b,
        metric=ref,
        field=field,
        fixed=[i for i in ids if not pa[i] and pb[i]],
        broken=[i for i in ids if pa[i] and not pb[i]],
        both_pass=sum(1 for i in ids if pa[i] and pb[i]),
        both_fail=sum(1 for i in ids if not pa[i] and not pb[i]),
    )


def read_log(
    ctx: Context, run_id: str, stream: str = "stdout", offset: int | None = None
) -> LogChunk:
    """
    Read a run log.

    Without ``offset``: the tail (last 5,000 lines / 8 MiB). With ``offset``:
    new bytes since that offset (up to 8 MiB).

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_id : str
        Run id to look up.
    stream : {"stdout", "stderr", "supervisor"}
        Which log to read.
    offset : int, optional
        Byte offset to resume from.

    Returns
    -------
    LogChunk

    Raises
    ------
    RunError
        If ``stream`` is not a known log stream.
    """
    if stream not in LOG_STREAMS:
        raise RunError(f"unknown log stream {stream!r}; use one of {LOG_STREAMS}")
    path = ctx.run_dir(ctx.find_record(run_id)) / "logs" / f"{stream}.log"
    size = path.stat().st_size if path.is_file() else 0
    start = max(0, size - LOG_TAIL_BYTES) if offset is None else min(offset, size)
    data = b""
    if size:
        with path.open("rb") as fh:
            fh.seek(start)
            data = fh.read(LOG_TAIL_BYTES)
    text = data.decode("utf-8", errors="replace")
    if offset is None:
        text = "".join(text.splitlines(keepends=True)[-LOG_TAIL_LINES:])
    return LogChunk(stream=stream, text=text, offset=start + len(data), size=size)


# curation -------------------------------------------------------------------------
def tag_run(
    ctx: Context, run_id: str, add: Iterable[str] = (), remove: Iterable[str] = ()
) -> RunRecord:
    """
    Add and remove tags.

    Sweep tags (``sweep:<owner>:<id>``) hold sweep membership, so only the
    sweep code sets them.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_id : str
        Run id to update.
    add : iterable of str
        Tags to add.
    remove : iterable of str
        Tags to remove.

    Returns
    -------
    RunRecord

    Raises
    ------
    RunError
        If a tag to add or remove is a sweep tag.
    """
    from hypothex.core.sweeps import SWEEP_TAG_PREFIX  # sweeps imports this module

    add_set, remove_set = set(add), set(remove)
    sweep_tags = sorted(t for t in add_set | remove_set if t.startswith(SWEEP_TAG_PREFIX))
    if sweep_tags:
        raise RunError(
            f"cannot add or remove sweep tag {', '.join(sweep_tags)}: "
            "sweep membership is set by `hx sweep`"
        )
    return ctx.update_run(
        run_id,
        "run.tagged",
        lambda r: r.model_copy(update={"tags": sorted((set(r.tags) | add_set) - remove_set)}),
    )


def star_run(ctx: Context, run_id: str, on: bool = True) -> RunRecord:
    """
    Star or unstar a run.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_id : str
        Run id to update.
    on : bool
        Whether the run should be starred.

    Returns
    -------
    RunRecord
    """
    return ctx.update_run(
        run_id, "run.starred", lambda r: r.model_copy(update={"starred": on}), {"on": on}
    )


def archive_run(ctx: Context, run_id: str, on: bool = True) -> RunRecord:
    """
    Archive (hide) or unarchive a run.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_id : str
        Run id to update.
    on : bool
        Whether the run should be archived.

    Returns
    -------
    RunRecord
    """
    return ctx.update_run(
        run_id, "run.archived", lambda r: r.model_copy(update={"archived": on}), {"on": on}
    )


def add_note(ctx: Context, run_id: str, text: str, author: str = "human") -> None:
    """
    Append a note to a run.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    run_id : str
        Run id to annotate.
    text : str
        Note body (Markdown).
    author : str
        Who wrote it, e.g. ``human`` or ``agent:claude``.
    """
    record = ctx.find_record(run_id)
    ctx.store.append_note(record.project, run_id, text, author)
    ctx.emit("run.note_added", record, {"author": author})


# sweeps ----------------------------------------------------------------------------
def list_sweeps(ctx: Context, project: str | None = None) -> list[dict[str, Any]]:
    """
    List sweeps of one project or of all projects, newest first.

    The rows are those of ``hx sweeps --json``: ``GET
    /api/v1/projects/{project}/sweeps`` rows plus the project.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str, optional
        Restrict to one project; ``None`` lists every registered project.

    Returns
    -------
    list of dict
        ``{project, id, created_at, n_runs, best}`` per sweep; ``best`` is the
        best cell (``None`` before any run is scored). Unreadable sweep files
        are skipped.

    Examples
    --------
    >>> list_sweeps(ctx, "toy")  # doctest: +SKIP
    [{'project': 'toy', 'id': 's-0002', 'created_at': datetime(...), 'n_runs': 6, 'best': {...}}]
    """
    from hypothex.core.sweeps import list_sweeps as project_sweeps  # sweeps imports this module

    projects = [project] if project else [e.project for e in ctx.store.list_projects()]
    rows = [{"project": p, **s} for p in projects for s in project_sweeps(ctx, p)]
    rows.sort(key=lambda s: (s["created_at"], s["id"]), reverse=True)
    return rows


# datasets --------------------------------------------------------------------------
def check_datasets(ctx: Context, project: str | None = None) -> list[DatasetDrift]:
    """
    Re-fingerprint datasets used by runs and report drift.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str, optional
        Restrict to one project.

    Returns
    -------
    list of DatasetDrift
    """
    records = ctx.index.list_runs(project=project, include_archived=True, limit=None)
    return check_runs(records, FingerprintCache(ctx.layout.dataset_cache))


def dataset_overlap(
    ctx: Context, project: str, dataset: str, key_field: str | None = None
) -> OverlapReport:
    """
    Count examples shared between a dataset's splits.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    project : str
        Project name.
    dataset : str
        Dataset name.
    key_field : str, optional
        JSON field identifying an example; default compares whole lines.

    Returns
    -------
    OverlapReport

    Raises
    ------
    ConfigError
        If the project has no such dataset.
    RemoteProjectError
        If the project is a copy from a host (its datasets are on that host).
    """
    entry = refresh_project(ctx, project)
    repo = ctx.local_repo(project)
    if dataset not in entry.config.datasets:
        raise ConfigError(f"project {project!r} has no dataset {dataset!r}")
    return overlap(dataset, entry.config.datasets[dataset], repo, key_field)
