"""Score runs with versioned metrics, re-evaluate, and validate projects."""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from pydantic import BaseModel, Field

from hypothex.core.config import (
    BUILTIN_TEMPLATE_VARS,
    CONFIG_FILENAME,
    ProjectConfig,
    TaskSpec,
    load_project_config,
    parse_metric_version,
    template_fields,
)
from hypothex.core.context import Context
from hypothex.core.datasets import resolve_dataset_path
from hypothex.core.errors import ConfigError, EvalError, NoPredictionsError
from hypothex.core.evalrunner import default_python_cmd, run_worker
from hypothex.core.ids import utcnow
from hypothex.core.records import RunRecord, RunStatus, ScoreRecord


class EvalReport(BaseModel):
    """Outcome of a re-evaluation over one or more runs."""

    evaluated: list[str] = Field(default_factory=list)
    skipped: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    """Outcome of ``hx validate``."""

    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def run_checkout(ctx: Context, record: RunRecord) -> Path | None:
    """
    Return the git worktree a run executed in, while it still exists.

    Runs pinned to another commit (spec 8A.4) and reruns at an older commit
    execute in ``<store>/<project>/worktrees/<name>/``.

    Parameters
    ----------
    ctx : Context
    record : RunRecord

    Returns
    -------
    Path or None
        The worktree root (it holds ``hypothex.yaml``), or None when the run
        ran in the project repo or its worktree was removed.

    Examples
    --------
    >>> run_checkout(ctx, record)  # doctest: +SKIP
    PosixPath('/home/me/.hypothex/store/toy/worktrees/20261003-101500-toy-acc-1a2b')
    """
    root = ctx.layout.worktrees_dir(record.project)
    # resolve first: ``cwd`` is text (a mirrored run's was written on a host), so ``..``
    # or a symlink in it must not pass the containment check and name a tree elsewhere
    real_root = root.resolve()
    cwd = Path(record.cwd).resolve()
    if not cwd.is_relative_to(real_root) or cwd == real_root:
        return None
    tree = root / cwd.relative_to(real_root).parts[0]
    return tree if (tree / CONFIG_FILENAME).is_file() else None


def _task_setup(
    ctx: Context, record: RunRecord, *, from_checkout: bool = False
) -> tuple[Path, ProjectConfig, TaskSpec]:
    """
    Load the project config and task spec a run's task belongs to.

    Parameters
    ----------
    ctx : Context
    record : RunRecord
    from_checkout : bool
        Read ``hypothex.yaml`` (and so the metric code) from the worktree the
        run executed in while it exists (``run_checkout``), not the project repo.

    Returns
    -------
    tuple of (Path, ProjectConfig, TaskSpec)

    Raises
    ------
    EvalError
        If the run has no task, or the task no longer exists.
    RemoteProjectError
        If the project is a copy from a host (``Context.local_repo``): its
        repo path is on that host, so it is never read here.
    """
    if record.task is None:
        raise EvalError(f"run {record.run_id} has no task; nothing to evaluate against")
    project_repo = ctx.local_repo(record.project)  # never a host's copy, even with a checkout
    checkout = run_checkout(ctx, record) if from_checkout else None
    repo = checkout or project_repo
    config = load_project_config(repo)
    if record.task not in config.tasks:
        raise EvalError(f"task {record.task!r} no longer exists in {repo / CONFIG_FILENAME}")
    return repo, config, config.tasks[record.task]


def _numeric_values(raw: object) -> dict[str, float] | None:
    """
    Return the worker's values as floats, or None if any is not a number.

    Parameters
    ----------
    raw : object
        The ``values`` field of one worker result.

    Returns
    -------
    dict of str to float, or None
        None when ``raw`` is not a dict of real numbers (bools excluded).
    """
    if not isinstance(raw, dict):
        return None
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in raw.values()):
        return None
    return {str(k): float(v) for k, v in raw.items()}


def evaluate_run(
    ctx: Context,
    run_id: str,
    *,
    metrics: list[str] | None = None,
    from_checkout: bool = True,
) -> tuple[list[ScoreRecord], list[str]]:
    """
    Score one run with the current version of its task's metrics.

    Scores are appended; older scores are never changed. A run that executed
    in a worktree (a pinned commit, spec 8A.4) is scored with that checkout's
    ``hypothex.yaml``, metric code, and dataset while the worktree exists, so a
    task that only exists at the pinned commit is still scored.

    Parameters
    ----------
    ctx : Context
    run_id : str
    metrics : list of str, optional
        Subset of the task's metrics; default all.
    from_checkout : bool
        Use the run's worktree when it has one (default). ``reeval`` passes
        False: re-evaluation scores with the project repo's current metrics.

    Returns
    -------
    scores : list of ScoreRecord
        New scores (an ``error`` row with key ``*`` for a metric that raised).
    warnings : list of str
        E.g. metric code changed without a version bump.

    Raises
    ------
    NoPredictionsError
        If the run has no predictions file.
    RemoteProjectError
        If the project is a copy from a host (its repo path is on that host).
    EvalError
        For any other evaluation failure.
    """
    record = ctx.find_record(run_id)
    repo, config, task = _task_setup(ctx, record, from_checkout=from_checkout)
    names = metrics or task.metrics
    unknown = [m for m in names if m not in task.metrics]
    if unknown:
        raise EvalError(f"metrics {unknown} are not part of task {record.task!r}")
    run_dir = ctx.run_dir(record)
    if not (run_dir / "predictions" / "predictions.jsonl").is_file():
        raise NoPredictionsError(f"run {run_id} has no predictions/predictions.jsonl")
    ds = config.datasets[task.dataset]
    dataset = None
    if ds.host in ("local", ctx.descriptor.label):
        path = resolve_dataset_path(repo, ds.path_for(task.split))
        if path.is_file():
            dataset = {
                "path": str(path),
                "id_field": ds.id_field,
                "reference_field": ds.reference_field,
            }
    request = {
        "repo": str(repo),
        "run_dir": str(run_dir),
        "dataset": dataset,
        "metrics": [
            {
                "name": n,
                "version": config.metrics[n].version,
                "fn": config.metrics[n].fn,
                "params": config.metrics[n].params,
            }
            for n in names
        ],
    }
    result = run_worker("evaluate", request, default_python_cmd(repo, config), cwd=repo)
    now = utcnow()
    warnings: list[str] = []
    with ctx.store.project_lock(record.project):  # concurrent evaluations share this file
        known = ctx.store.metric_hashes(record.project)
        for r in result["results"]:
            ref = f"{r['name']}@{r['version']}"
            digest = r["source_hash"]
            if digest and ref in known and known[ref] != digest:
                warnings.append(
                    f"metric {r['name']} code changed without a version bump (still {r['version']})"
                )
            elif digest and ref not in known:
                known[ref] = digest
        ctx.store.save_metric_hashes(record.project, known)
    scores: list[ScoreRecord] = []
    for r in result["results"]:
        digest = r["source_hash"]
        values, error = _numeric_values(r["values"]), r["error"]
        if values is None:
            values = {}
            error = error or f"metric returned non-numeric values: {r['values']!r:.200}"
        if error:
            scores.append(
                ScoreRecord(
                    metric=r["name"],
                    version=r["version"],
                    key="*",
                    error=error,
                    source_hash=digest,
                    created_at=now,
                )
            )
        scores.extend(
            ScoreRecord(
                metric=r["name"],
                version=r["version"],
                key=k,
                value=v,
                source_hash=digest,
                created_at=now,
            )
            for k, v in values.items()
        )
    for score in scores:
        ctx.add_score(record, score)
    return scores, warnings


def reeval(
    ctx: Context,
    *,
    run_id: str | None = None,
    project: str | None = None,
    task: str | None = None,
    metric: str | None = None,
    force: bool = False,
    run_ids: Collection[str] | None = None,
) -> EvalReport:
    """
    Re-score saved predictions without rerunning inference.

    Parameters
    ----------
    ctx : Context
    run_id : str, optional
        One run. Otherwise ``project`` and ``task`` select all finished runs.
    project : str, optional
    task : str, optional
    metric : str, optional
        ``name`` or ``name@version``; the version must be the current one.
    force : bool
        Re-score even runs already scored at the current version.
    run_ids : collection of str, optional
        With ``project`` and ``task``: score only these of the task's finished
        runs (the hub scores its own runs here and sends mirrored ones to their
        hosts). ``None`` scores them all.

    Returns
    -------
    EvalReport
        A run that fails to evaluate (for any reason) is listed in
        ``skipped`` with the reason; the other runs are still scored.

    Raises
    ------
    EvalError
        If neither a run id nor a project and task are given, or a
        non-current metric version is requested.
    RemoteProjectError
        If the project is a copy from a host (its repo path is on that host).
    """
    if run_id is not None:
        targets = [ctx.find_record(run_id)]
    elif project is not None and task is not None:
        targets = list(
            reversed(
                ctx.index.list_runs(
                    project=project,
                    task=task,
                    status=RunStatus.FINISHED,
                    include_archived=True,
                    limit=None,
                )
            )
        )
        if run_ids is not None:
            keep = set(run_ids)
            targets = [t for t in targets if t.run_id in keep]
    else:
        raise EvalError("give a run id, or a project and a task")
    report = EvalReport()
    if not targets:
        return report
    repo, config, task_spec = _task_setup(ctx, targets[0])
    names = task_spec.metrics
    if metric is not None:
        name, version = parse_metric_version(metric)
        if name not in task_spec.metrics:
            raise EvalError(f"metric {name!r} is not part of task {targets[0].task!r}")
        current = config.metrics[name].version
        if version is not None and version != current:
            raise EvalError(
                f"metric {name} is at {current} in {repo / CONFIG_FILENAME}; "
                "only the current version can be computed"
            )
        names = [name]
    wanted = {n: config.metrics[n].version for n in names}
    existing = ctx.index.scores_for([t.run_id for t in targets])
    for record in targets:
        have = existing.get(record.run_id, [])
        done = all(
            any(s.metric == n and s.version == v and s.error is None for s in have)
            for n, v in wanted.items()
        )
        if done and not force:
            report.skipped[record.run_id] = "already scored at the current version"
            continue
        try:
            _, warnings = evaluate_run(ctx, record.run_id, metrics=names, from_checkout=False)
        except NoPredictionsError:
            report.skipped[record.run_id] = "no predictions"
            continue
        except EvalError as exc:
            report.skipped[record.run_id] = str(exc)[:500]
            continue
        except Exception as exc:  # noqa: BLE001 - one bad run must not abort the batch
            report.skipped[record.run_id] = f"{type(exc).__name__}: {exc}"[:500]
            continue
        report.evaluated.append(record.run_id)
        report.warnings.extend(w for w in warnings if w not in report.warnings)
    return report


def validate_project(ctx: Context, repo: Path) -> ValidationReport:
    """
    Check a project's ``hypothex.yaml``, metric imports, and dataset paths.

    Parameters
    ----------
    ctx : Context
    repo : Path
        Repository root directory.

    Returns
    -------
    ValidationReport
    """
    try:
        config = load_project_config(repo)
    except ConfigError as exc:
        return ValidationReport(ok=False, errors=[str(exc)])
    errors: list[str] = []
    warnings: list[str] = []
    for stage, template in config.stages.items():
        custom = template_fields(template) - BUILTIN_TEMPLATE_VARS
        if custom:
            warnings.append(
                f"stage {stage!r} uses custom variables {sorted(custom)}; "
                "pass them with --var name=value"
            )
    for name, spec in config.datasets.items():
        if spec.host not in ("local", ctx.descriptor.label):
            continue
        for raw in dict.fromkeys([spec.path, *spec.splits.values()]):
            path = resolve_dataset_path(repo, raw)
            if not path.exists():
                warnings.append(f"dataset {name!r}: path not found: {path}")
    if config.metrics:
        request = {
            "repo": str(repo),
            "metrics": [{"name": n, "fn": m.fn} for n, m in config.metrics.items()],
        }
        try:
            described = run_worker("describe", request, default_python_cmd(repo, config), cwd=repo)[
                "metrics"
            ]
        except EvalError as exc:
            errors.append(f"could not run the metric worker: {exc}")
            described = {}
        known = ctx.store.metric_hashes(config.project)
        for name, info in described.items():
            spec = config.metrics[name]
            if not info["importable"]:
                errors.append(f"metric {name!r}: cannot import {spec.fn}: {info['error']}")
                continue
            ref = f"{name}@{spec.version}"
            if info["source_hash"] and known.get(ref) not in (None, info["source_hash"]):
                warnings.append(
                    f"metric {name!r} code changed without a version bump (still {spec.version})"
                )
    return ValidationReport(ok=not errors, errors=errors, warnings=warnings)
