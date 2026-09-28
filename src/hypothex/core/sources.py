"""Flat row iterators over the files in run folders, one per view data source."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hypothex.core.config import load_project_config
from hypothex.core.context import Context
from hypothex.core.datasets import resolve_dataset_path
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.fsutil import read_jsonl
from hypothex.core.leaderboard import group_id_for, group_label
from hypothex.core.records import RunRecord

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

    The rule of ``LeaderboardRow.label``: the group's ``version_param`` value when
    ``version_param`` is given and a run has it (``agent_iteration`` tasks); else
    ``group_label`` of the newest non-empty hypothesis and the group's tags.

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
    out: dict[str, str] = {}
    for key, group in members.items():
        version = _version_of(group, version_param) if version_param is not None else None
        if version:
            out[key] = version
            continue
        hypothesis = next((r.hypothesis for r in reversed(group) if r.hypothesis.strip()), "")
        out[key] = group_label(hypothesis, (t for r in group for t in r.tags), key)
    return out


def _version_of(members: list[RunRecord], param: str) -> str | None:
    """The first non-empty ``params``/``vars`` value of ``param`` among ``members``."""
    return next((v for m in members if (v := m.params.get(param) or m.vars.get(param))), None)


def iter_rows(
    ctx: Context,
    runs: list[RunRecord],
    source: Source,
    fields: list[str] | None = None,
    labels: Mapping[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Yield flat rows of one data source across runs.

    Every row carries ``run_id``, ``group_id``, ``label`` (the seed group's short
    name, as on the leaderboard), and ``seed``. Other keys per source:

    - ``runs``: ``status``, ``created_at`` (ISO string), ``created_by``,
      ``hypothesis``, ``tags``, ``host``, ``exit_code``, ``params.*``,
      ``vars.*``, ``usage.*`` (only when the run has usage totals).
    - ``scores``: ``metric``, ``version``, ``key``, ``value`` (errored scores skipped).
    - ``metrics``: ``name``, ``step``, ``value``, ``t`` (full history from
      ``metrics.jsonl``).
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

    Yields
    ------
    dict
        One flat row.

    Raises
    ------
    ConfigError
        If ``source`` is not a known source.

    Examples
    --------
    >>> rows = list(iter_rows(ctx, runs, "scores", fields=["value"]))  # doctest: +SKIP
    >>> rows[0]  # doctest: +SKIP
    {'run_id': 'r1', 'group_id': 'aaaa@c1', 'label': 'svm', 'seed': 1, 'value': 0.75}
    """
    if source not in SOURCES:
        raise ConfigError(f"unknown source {source!r}; use one of {', '.join(SOURCES)}")
    reader = _READERS[source]
    refs: _Refs = {}
    names = {**group_labels(runs), **(labels or {})}
    for run in runs:
        gid = group_id_for(run)
        base = {"run_id": run.run_id, "group_id": gid, "label": names[gid], "seed": run.seed}
        for row in reader(ctx, run, refs):
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


def _metrics(ctx: Context, run: RunRecord, _refs: _Refs) -> Iterator[dict[str, Any]]:
    for p in ctx.store.read_metric_points(run.project, run.run_id):
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


_READERS: dict[str, Callable[[Context, RunRecord, _Refs], Iterator[dict[str, Any]]]] = {
    "runs": _runs,
    "scores": _scores,
    "metrics": _metrics,
    "predictions": _predictions,
    "samples": _samples,
    "usage": _usage,
    "traces": _traces,
}
