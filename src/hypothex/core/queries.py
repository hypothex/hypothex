"""Read models and curation actions shared by the CLI, API, and MCP server."""

from __future__ import annotations

import contextlib
import itertools
import json
import shlex
import weakref
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
from hypothex.core.records import MetricPoint, RunRecord, RunStatus, ScoreRecord
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
    if entry.remote_host is not None:
        return entry
    repo = Path(entry.repo)
    try:
        config = load_project_config(repo)
    except ConfigError:
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

    Returns
    -------
    dict
        run_id -> example_id -> per-example fields (without ``id``), read from
        ``predictions/scores.<metric>@<version>.jsonl``. Runs without that file
        are left out.
    """
    metric, _ = parse_metric_key(config.tasks[task].primary)
    version = (versions or {}).get(metric, config.metrics[metric].version)
    name = f"scores.{metric}@{version}.jsonl"
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for r in runs:
        if r.task != task or r.status != RunStatus.FINISHED or r.archived:
            continue
        path = ctx.run_dir(r) / "predictions" / name
        if path.is_file():
            out[r.run_id] = {
                str(row["id"]): {k: v for k, v in row.items() if k != "id"}
                for row in read_jsonl(path)
                if "id" in row
            }
    return out


def get_leaderboard(
    ctx: Context,
    ref: str,
    project: str | None = None,
    versions: dict[str, str] | None = None,
    *,
    examples: bool = True,
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

    Returns
    -------
    Leaderboard
    """
    entry, task = resolve_task(ctx, ref, project)
    return _board(ctx, entry, task, versions, examples=examples)


def _board(
    ctx: Context,
    entry: ProjectEntry,
    task: str,
    versions: dict[str, str] | None,
    *,
    examples: bool,
) -> Leaderboard:
    def build() -> Leaderboard:
        runs = ctx.index.list_runs(
            project=entry.project, task=task, include_archived=True, limit=None
        )
        scores = ctx.index.scores_for(r.run_id for r in runs)
        per_example = (
            primary_examples(ctx, entry.config, task, runs, versions) if examples else None
        )
        return build_leaderboard(
            entry.project, task, entry.config, runs, scores, versions, per_example=per_example
        )

    return cached_leaderboard(
        ctx,
        entry.project,
        task,
        entry.config,
        build,
        versions=versions,
        variant=("examples", examples),
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
    """
    entry, name = resolve_task(ctx, ref, project)
    spec = entry.config.tasks[name]
    return {
        "summary": _summary(ctx, entry, name).model_dump(mode="json"),
        "repo": entry.repo,
        "dataset": {
            "name": spec.dataset,
            **entry.config.datasets[spec.dataset].model_dump(mode="json"),
        },
        "metrics": {m: entry.config.metrics[m].model_dump(mode="json") for m in spec.metrics},
        "stages": entry.config.stages,
    }


# runs ----------------------------------------------------------------------------
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
    """
    record = ctx.find_record(run_id)
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
    if (run_dir / "config.yaml").is_file():
        paths["config"] = str(run_dir / "config.yaml")
    for ref in record.datasets:
        paths[f"dataset:{ref.name}"] = f"{ref.host}:{ref.path}"
    for i, art in enumerate(record.artifacts):
        paths[f"artifact:{art.kind}:{i}"] = f"{art.host}:{art.path}"
    return RunDetail(
        record=record,
        scores=ctx.store.read_scores(record.project, run_id),
        paths=paths,
        notes=ctx.store.read_notes(record.project, run_id),
        has_diff=(run_dir / "git.diff").is_file(),
        metric_names=sorted({p.name for p in ctx.index.metric_points(run_id)}),
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
        entry = ctx.store.load_project(record.project)
        if entry.remote_host is not None:
            return {}  # the repo path is on that host: never read a dataset from it here
        repo = Path(entry.repo)
        config = load_project_config(repo)
        spec = config.tasks[record.task]
    except (StoreError, ConfigError, KeyError):
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
        ``name`` or ``name@version`` to limit which per-example scores are shown.
    failures_only : bool
        Keep rows where ``field`` is False or 0 in a shown metric.
    field : str
        Per-example field that marks success.

    Returns
    -------
    PredictionPage

    Raises
    ------
    EvalError
        ``failures_only`` without any per-example scores.
    """
    record = ctx.find_record(run_id)
    run_dir = ctx.run_dir(record)
    per = _per_example(run_dir)
    if metric is not None:
        per = {k: v for k, v in per.items() if k == metric or k.split("@")[0] == metric}
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


def compare_examples(
    ctx: Context, a: str, b: str, metric: str, field: str = "correct"
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

    Returns
    -------
    ExampleDiff
    """
    rec_a = ctx.find_record(a)
    name, version = parse_metric_version(metric)
    if version is None:
        version = refresh_project(ctx, rec_a.project).config.metrics[name].version
    ref = f"{name}@{version}"
    passed: list[dict[str, bool]] = []
    for rid in (a, b):
        per = _per_example(ctx.run_dir(ctx.find_record(rid))).get(ref)
        if per is None:
            raise EvalError(f"run {rid} has no per-example scores for {ref}")
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
    """
    add_set, remove_set = set(add), set(remove)
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
        If the project has no such dataset, or is a copy from a host
        (``remote_host``), whose dataset files are on that host.
    """
    entry = refresh_project(ctx, project)
    if entry.remote_host is not None:
        raise ConfigError(
            f"project {project!r} was copied from host {entry.remote_host} and its data is "
            f"on that host; check overlap there, or `hx register` a checkout here"
        )
    if dataset not in entry.config.datasets:
        raise ConfigError(f"project {project!r} has no dataset {dataset!r}")
    return overlap(dataset, entry.config.datasets[dataset], Path(entry.repo), key_field)
