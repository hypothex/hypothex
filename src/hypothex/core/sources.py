"""Flat row iterators over the files in run folders, one per view data source."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hypothex.core.config import load_project_config
from hypothex.core.context import Context
from hypothex.core.datasets import resolve_dataset_path
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.fsutil import read_jsonl
from hypothex.core.leaderboard import group_id_for, seed_group_label
from hypothex.core.records import INDEXED_POINT_STATUSES, MetricPoint, RunRecord

if TYPE_CHECKING:
    from hypothex.core.views import Source

SOURCES: tuple[str, ...] = (
    "runs",
    "scores",
    "metrics",
    "predictions",
    "samples",
    "usage",
    "traces",
)

ROW_KEYS: tuple[str, ...] = ("run_id", "group_id", "label", "seed")
"""Keys every per-run source row carries, whatever ``fields`` lists."""

_Refs = dict[tuple[str, str | None], dict[str, Any]]


def group_labels(runs: list[RunRecord], version_param: str | None = None) -> dict[str, str]:
    """
    Short name per seed group of the given runs.

    ``leaderboard.seed_group_label`` per group, the rule of ``LeaderboardRow.label``:
    the group's ``version_param`` value when ``version_param`` is given and a run has
    it (``agent_iteration`` tasks); else ``group_label`` of the newest non-empty
    hypothesis and the group's tags.

    Parameters
    ----------
    runs : list of RunRecord
        Runs in any order; they are grouped by ``group_id_for``.
    version_param : str, optional
        The task's ``version_param`` for ``agent_iteration`` tasks, else ``None``.

    Returns
    -------
    dict of str to str
        Label per ``group_id``.

    Examples
    --------
    >>> group_labels([make_record(hypothesis="svm, rbf kernel")])  # doctest: +SKIP
    {'aaaa@c1': 'svm'}
    """
    members: dict[str, list[RunRecord]] = {}
    for r in sorted(runs, key=lambda r: (r.created_at, r.run_id)):
        members.setdefault(group_id_for(r), []).append(r)
    return {key: seed_group_label(group, key, version_param) for key, group in members.items()}


def metric_points(
    ctx: Context,
    runs: Iterable[RunRecord],
    names: Collection[str] | None = None,
    read: Callable[[RunRecord], list[MetricPoint]] | None = None,
) -> dict[str, list[MetricPoint]]:
    """
    Metric history of many runs, of some names only, ordered by name then step.

    Runs that ended (``INDEXED_POINT_STATUSES``) read the index in one query
    that filters the names in SQL: the indexed history keeps at most
    ``thin.MAX_POINTS_PER_METRIC`` points per name (always the last one).
    Queued, running and lost runs read their ``metrics.jsonl``, since the index
    may not have their latest points, but only a bounded copy of it
    (``RunStore.read_metric_points_bounded``: at most as many points per name,
    with the first, last, lowest and highest), so a file that grows without
    limit never fills memory.

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    runs : iterable of RunRecord
        Runs to read.
    names : collection of str, optional
        Metric names to keep; ``None`` keeps every name.
    read : callable, optional
        Reads one live run's history; default ``RunStore.read_metric_points_bounded``.
        The panel engine passes a reader that parses each file once per view.

    Returns
    -------
    dict of str to list of MetricPoint
        Points per run id; a run with no matching point may be missing.

    Examples
    --------
    >>> metric_points(ctx, runs, names=["train/loss"])  # doctest: +SKIP
    {'r1': [MetricPoint(name='train/loss', step=0, value=2.3, t=None)]}
    """
    runs = list(runs)
    wanted = None if names is None else set(names)
    ended = [r.run_id for r in runs if r.status in INDEXED_POINT_STATUSES]
    out = ctx.index.metric_points_for(ended, wanted) if ended else {}
    for run in runs:
        if run.status in INDEXED_POINT_STATUSES:
            continue
        if read is not None:
            history = read(run)
        else:
            history = ctx.store.read_metric_points_bounded(run.project, run.run_id)
        points = [p for p in history if wanted is None or p.name in wanted]
        if points:
            out[run.run_id] = sorted(points, key=lambda p: (p.name, p.step))
    return out


def iter_rows(
    ctx: Context,
    runs: list[RunRecord],
    source: Source,
    fields: list[str] | None = None,
    labels: Mapping[str, str] | None = None,
    names: Collection[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Yield flat rows of one data source across runs.

    Every row carries ``run_id``, ``group_id``, ``label`` (the seed group's short
    name, as on the leaderboard), and ``seed``. Other keys per source:

    - ``runs``: ``status``, ``created_at`` (ISO string), ``created_by``,
      ``hypothesis``, ``tags``, ``host``, ``exit_code``, ``params.*``,
      ``vars.*``, ``usage.*`` (only when the run has usage totals).
    - ``scores``: ``metric``, ``version``, ``key``, ``value`` (errored scores skipped).
    - ``metrics``: ``name``, ``step``, ``value``, ``t`` (``metric_points``: the
      indexed history of runs that ended, a bounded read of ``metrics.jsonl``
      of the others; at most ``thin.MAX_POINTS_PER_METRIC`` points per name),
      ordered by name then step and read one run at a time.
    - ``predictions``: ``id``, ``prediction``, ``reference`` (joined from the
      task dataset when the row has none), ``meta.*``, and every per-example
      score field as ``<metric>@<version>.<field>``.
    - ``samples``: ``name``, ``value`` (``RunStore.read_samples``).
    - ``usage``: ``example_id``, ``tokens_in``, ``tokens_out``, ``usd``, ``seconds``
      (``RunStore.read_usage``).
    - ``traces``: ``example_id`` plus the eight ``TraceStep`` fields
      (``RunStore.list_traces`` and ``RunStore.read_trace``).

    Parameters
    ----------
    ctx : Context
        Open Hypothex context.
    runs : list of RunRecord
        Runs to read, in the order rows should appear.
    source : {"runs", "scores", "metrics", "predictions", "samples", "usage", "traces"}
        Which data source to read.
    fields : list of str, optional
        Keep only these keys (plus ``run_id``, ``group_id``, ``label``, ``seed``);
        missing keys become ``None``.
    labels : mapping of str to str, optional
        Label per ``group_id`` (the panel engine passes the leaderboard's);
        groups it lacks get ``group_labels(runs)``.
    names : collection of str, optional
        ``metrics`` source only: keep these metric names. They are filtered in
        the index query, so a chart of one name over many runs reads only that
        name's points.

    Yields
    ------
    dict
        One flat row.

    Raises
    ------
    ConfigError
        If ``source`` is not a per-run source (``groups`` is built per task by
        the panel engine, ``panels.group_rows``).

    Examples
    --------
    >>> rows = list(iter_rows(ctx, runs, "scores", fields=["value"]))  # doctest: +SKIP
    >>> rows[0]  # doctest: +SKIP
    {'run_id': 'r1', 'group_id': 'aaaa@c1', 'label': 'svm', 'seed': 1, 'value': 0.75}
    """
    if source == "groups":
        raise ConfigError("groups is a task-level source; read it through a table panel")
    if source not in SOURCES:
        raise ConfigError(f"unknown source {source!r}; use one of {', '.join(SOURCES)}")
    refs: _Refs = {}
    label_of = {**group_labels(runs), **(labels or {})}
    for run in runs:
        gid = group_id_for(run)
        base = {"run_id": run.run_id, "group_id": gid, "label": label_of[gid], "seed": run.seed}
        if source == "metrics":
            # one run at a time, like the other sources: a table over thousands
            # of runs holds one run's history, not all of them
            points = metric_points(ctx, [run], names).get(run.run_id, [])
            rows: Iterable[dict[str, Any]] = _metric_rows(points)
        else:
            rows = _READERS[source](ctx, run, refs)
        for row in rows:
            yield select_fields({**base, **row}, fields)


def select_fields(row: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    """
    Keep ``run_id``, ``group_id``, ``label``, ``seed`` and the listed fields of a full row.

    The projection is taken from the full row, so listing ``run_id``,
    ``group_id``, ``label``, or ``seed`` keeps their values instead of blanking them.

    Parameters
    ----------
    row : dict
        A full row from a source (with ``run_id``, ``group_id``, ``label``, ``seed``).
    fields : list of str or None
        Fields to keep; ``None`` keeps the whole row.

    Returns
    -------
    dict
        The projected row; a listed field the row lacks is ``None``.

    Examples
    --------
    >>> row = {"run_id": "r1", "group_id": "g", "label": "svm", "seed": 1, "v": 2}
    >>> select_fields(row, ["seed", "x"])
    {'run_id': 'r1', 'group_id': 'g', 'label': 'svm', 'seed': 1, 'x': None}
    """
    if fields is None:
        return row
    out = {key: row.get(key) for key in ROW_KEYS}
    out.update({f: row.get(f) for f in fields})
    return out


def _flat(prefix: str, value: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}.{k}": v for k, v in value.items()}


def _runs(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    row: dict[str, Any] = {
        "status": run.status.value,
        "created_at": run.created_at.isoformat(),
        "created_by": run.created_by,
        "hypothesis": run.hypothesis,
        "tags": list(run.tags),
        "host": run.host,
        "exit_code": run.exit_code,
        **_flat("params", run.params),
        **_flat("vars", run.vars),
    }
    if run.usage is not None:
        row.update(_flat("usage", run.usage.model_dump()))
    yield row


def _scores(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    for s in ctx.store.read_scores(run.project, run.run_id):
        if s.error is None and s.value is not None:
            yield {"metric": s.metric, "version": s.version, "key": s.key, "value": s.value}


def _metric_rows(points: list[MetricPoint]) -> Iterator[dict[str, Any]]:
    for p in points:
        yield {"name": p.name, "step": p.step, "value": p.value, "t": p.t}


def _dataset_references(ctx: Context, project: str, task: str | None) -> dict[str, Any]:
    if task is None:
        return {}
    try:
        repo = Path(ctx.store.load_project(project).repo)
        config = load_project_config(repo)
        spec = config.tasks[task]
        ds = config.datasets[spec.dataset]
        path = resolve_dataset_path(repo, ds.path_for(spec.split))
    except (StoreError, ConfigError, KeyError):
        return {}
    return {
        str(r[ds.id_field]): r.get(ds.reference_field) for r in read_jsonl(path) if ds.id_field in r
    }


def _predictions(ctx: Context, run: RunRecord, refs: _Refs) -> Iterator[dict[str, Any]]:
    pred_dir = ctx.run_dir(run) / "predictions"
    rows = [r for r in read_jsonl(pred_dir / "predictions.jsonl") if "id" in r]
    if not rows:
        return
    per_example: dict[str, dict[str, dict[str, Any]]] = {}
    for path in sorted(pred_dir.glob("scores.*.jsonl")):
        ref = path.name[len("scores.") : -len(".jsonl")]
        per_example[ref] = {
            str(r["id"]): {k: v for k, v in r.items() if k != "id"}
            for r in read_jsonl(path)
            if "id" in r
        }
    key = (run.project, run.task)
    if any("reference" not in r for r in rows) and key not in refs:
        refs[key] = _dataset_references(ctx, run.project, run.task)
    for r in rows:
        ex_id = str(r["id"])
        row: dict[str, Any] = {
            "id": ex_id,
            "prediction": r.get("prediction"),
            "reference": r["reference"] if "reference" in r else refs[key].get(ex_id),
        }
        meta = r.get("meta")
        if isinstance(meta, dict):
            row.update(_flat("meta", meta))
        for ref, per in per_example.items():
            for field, value in per.get(ex_id, {}).items():
                row[f"{ref}.{field}"] = value
        yield row


def _samples(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    for name, values in ctx.store.read_samples(run.project, run.run_id).items():
        for value in values:
            yield {"name": name, "value": value}


def _usage(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    for row in ctx.store.read_usage(run.project, run.run_id):
        yield row.model_dump()


def _traces(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    for summary in ctx.store.list_traces(run.project, run.run_id):
        example_id = summary["example_id"]
        for step in ctx.store.read_trace(run.project, run.run_id, example_id):
            yield {"example_id": example_id, **step.model_dump()}


# Per-run readers; ``metrics`` reads each run through ``metric_points``.
_READERS: dict[str, Callable[[Context, RunRecord, _Refs], Iterator[dict[str, Any]]]] = {
    "runs": _runs,
    "scores": _scores,
    "predictions": _predictions,
    "samples": _samples,
    "usage": _usage,
    "traces": _traces,
}
