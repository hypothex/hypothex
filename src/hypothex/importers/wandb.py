"""Import local W&B logs and exported history as historical Hypothex runs."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, TextIO

from hypothex.core.config import load_project_config
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.fsutil import write_yaml
from hypothex.core.ids import utcnow
from hypothex.core.naming import NAME_MAX, clean_run_name
from hypothex.core.records import ExecutorInfo, MetricPoint, RunRecord, RunStatus
from hypothex.core.store import RUN_SUBDIRS, dir_lock, run_lock
from hypothex.core.thin import HistoryThinner
from hypothex.importers.history_reader import iter_history_rows
from hypothex.importers.wandb_reader import WandbReadError, iter_wandb_records


@dataclass
class WandbImportResult:
    """Imported run and whether this invocation created it."""

    record: RunRecord
    imported: bool
    metric_points: int


@dataclass
class _Data:
    run_id: str = ""
    name: str = ""
    project: str = ""
    entity: str = ""
    tags: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    start: datetime | None = None
    end: datetime | None = None
    exit_code: int | None = None
    count: int = 0
    history_rows: int = 0
    thinner: HistoryThinner = field(default_factory=HistoryThinner)


def _source(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_dir():
        matches = list(path.glob("*.wandb"))
        if len(matches) != 1:
            raise RunError("choose one W&B run folder containing exactly one .wandb file")
        path = matches[0]
    if not path.is_file() or path.suffix.lower() not in {".wandb", ".csv", ".jsonl", ".json"}:
        raise RunError("expected a .wandb, .csv, .jsonl or .json file, or a W&B run folder")
    return path


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _json(value: str) -> Any:
    try:
        return json.loads(value)
    except (ValueError, RecursionError) as exc:
        raise RunError("invalid JSON value in W&B record") from exc


def _key(item: Any) -> list[str]:
    return list(item.nested_key) if item.nested_key else [item.key]


def _history_value(item: Any) -> Any:
    # SDK 0.31 adds a typed oneof; older logs still use value_json.
    kind = item.WhichOneof("value")
    if kind == "none":
        return None
    if kind == "json":
        return _json(item.json)
    if kind is not None:
        return getattr(item, kind)
    return _json(item.value_json)


def _updates(target: dict[str, Any], record: Any) -> None:
    for item in record.update:
        keys = _key(item)
        current = target
        for key in keys[:-1]:
            if not isinstance(current.get(key), dict):
                current[key] = {}
            current = current[key]
        current[keys[-1]] = _json(item.value_json)
    for item in record.remove:
        keys = _key(item)
        current = target
        for key in keys[:-1]:
            child = current.get(key)
            if not isinstance(child, dict):
                break
            current = child
        else:
            current.pop(keys[-1], None)


def _history(data: _Data, history: Any, output: TextIO) -> None:
    values = {"/".join(_key(item)): _history_value(item) for item in history.item}
    default_step = history.step.num if history.HasField("step") else data.history_rows
    _points(data, values, output, default_step)


def _points(data: _Data, values: dict[str, Any], output: TextIO, default_step: int) -> None:
    step = values.get("_step", default_step)
    data.history_rows += 1
    if isinstance(step, bool) or not isinstance(step, (int, float, Decimal)):
        raise RunError("W&B history step must be an integer")
    if _number(step) is None or step != int(step) or not -(2**63) <= step < 2**63:
        raise RunError("W&B history step is outside the supported integer range")
    timestamp = _number(values.get("_timestamp"))
    if timestamp is not None:
        try:
            stamp = datetime.fromtimestamp(timestamp, UTC)
        except (ValueError, OverflowError, OSError):
            timestamp = None
        else:
            data.end = max(data.end, stamp) if data.end else stamp
    for name, value in values.items():
        number = _number(value)
        if not name or name.startswith("_") or number is None:
            continue
        point = MetricPoint(name=name, step=int(step), value=number, t=timestamp)
        output.write(point.model_dump_json() + "\n")
        data.thinner.add(point)
        data.count += 1


def _flatten(row: dict[str, Any], prefix: str = "", depth: int = 0) -> dict[str, Any]:
    if depth > 64:
        raise RunError("W&B history object nesting exceeds 64 levels")
    result: dict[str, Any] = {}
    for key, value in row.items():
        name = f"{prefix}/{key}" if prefix else key
        if isinstance(value, dict):
            if "_type" in value:
                continue
            nested = _flatten(value, name, depth + 1)
        else:
            nested = {name: value}
        if result.keys() & nested.keys():
            raise RunError("W&B history contains conflicting nested metric names")
        result.update(nested)
    return result


def _read_export(snapshot: Path, source: Path, output: TextIO) -> _Data:
    data = _Data(run_id=source.stem, name=source.stem, exit_code=0)
    suffix = source.suffix.lower()
    format_name = "csv" if suffix == ".csv" else "json" if suffix == ".json" else "jsonl"
    for row in iter_history_rows(snapshot, format_name):
        values = _flatten(row)
        if "_step" not in values and "Step" in values:
            values["_step"] = values.pop("Step")
        _points(data, values, output, data.history_rows)
        timestamp = _number(values.get("_timestamp"))
        if timestamp is not None:
            try:
                stamp = datetime.fromtimestamp(timestamp, UTC)
            except (ValueError, OverflowError, OSError):
                pass
            else:
                data.start = min(data.start, stamp) if data.start else stamp
    if data.count == 0:
        raise RunError("W&B history export contains no finite scalar metric values")
    return data


def _read(snapshot: Path, output: TextIO) -> _Data:
    data = _Data()
    for record in iter_wandb_records(snapshot):
        kind = record.WhichOneof("record_type")
        if kind == "run":
            run = record.run
            if data.run_id and data.run_id != run.run_id:
                raise RunError("W&B file contains multiple run identities")
            data.run_id = run.run_id
            data.name = run.display_name
            data.project, data.entity = run.project, run.entity
            data.tags = list(run.tags)
            if run.HasField("start_time"):
                try:
                    data.start = run.start_time.ToDatetime(tzinfo=UTC)
                except (OverflowError, ValueError) as exc:
                    raise RunError("invalid W&B start timestamp") from exc
            _updates(data.config, run.config)
        elif kind == "config":
            _updates(data.config, record.config)
        elif kind == "summary":
            _updates(data.summary, record.summary)
        elif kind == "history":
            _history(data, record.history, output)
        elif kind == "exit":
            if record.exit.not_complete:
                raise RunError("W&B run is unfinished; finish the run before importing its log")
            data.exit_code = record.exit.exit_code
    if not data.run_id:
        raise RunError("W&B file has no run metadata")
    if data.exit_code is None:
        raise RunError("W&B run is unfinished; finish the run before importing its log")
    return data


def import_wandb(
    ctx: Context, source: Path, repo: Path, *, task: str | None = None
) -> WandbImportResult:
    """
    Import a completed W&B binary log or exported scalar history read-only.

    Parameters
    ----------
    ctx : Context
        Destination Hypothex home.
    source : Path
        A ``.wandb`` file, run folder, or CSV/JSONL/JSON history export.
    repo : Path
        Local project containing ``hypothex.yaml``.
    task : str, optional
        Existing task to associate with the imported run.

    Returns
    -------
    WandbImportResult
        Run, creation flag and full scalar point count. Identical file bytes,
        project and task produce the same run id, including across file copies.

    Raises
    ------
    RunError
        Invalid source, unfinished log, or unknown destination task.

    Examples
    --------
    >>> result = import_wandb(ctx, Path("run-abc.wandb"), Path("."))  # doctest: +SKIP
    >>> result.record.tags  # doctest: +SKIP
    ['wandb']
    """
    source = _source(source)
    repo = repo.expanduser().resolve()
    config = load_project_config(repo)
    if task is not None and task not in config.tasks:
        raise RunError(f"unknown task {task!r} in project {config.project!r}")
    # Stage outside store: concurrent discovery cannot see half-imported runs.
    with TemporaryDirectory(prefix=".wandb-import-", dir=ctx.layout.home) as temp:
        staging = Path(temp)
        snapshot = staging / "source"
        digest = hashlib.sha256()
        with source.open("rb") as src, snapshot.open("wb") as dst:
            before = os.fstat(src.fileno())
            remaining = before.st_size
            while remaining:
                chunk = src.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RunError("W&B source changed while importing; retry after it finishes")
                digest.update(chunk)
                dst.write(chunk)
                remaining -= len(chunk)
            after = os.fstat(src.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise RunError("W&B source changed while importing; retry after it finishes")
        content_hash = digest.hexdigest()
        source_format = "wandb" if source.suffix.lower() == ".wandb" else source.suffix.lower()[1:]
        identity = json.dumps([config.project, task, source_format, content_hash]).encode()
        run_id = "wandb-" + hashlib.sha256(identity).hexdigest()[:32]
        folder = staging / "run"
        folder.mkdir()
        try:
            with (folder / "metrics.jsonl").open("w", encoding="utf-8") as output:
                data = (
                    _read(snapshot, output)
                    if source_format == "wandb"
                    else _read_export(snapshot, source, output)
                )
        except (WandbReadError, ImportError) as exc:
            raise RunError(str(exc)) from exc
        created = data.start or data.end or utcnow()
        record = RunRecord(
            run_id=run_id,
            project=config.project,
            task=task,
            command=[],
            command_template=[],
            cwd=str(repo),
            environment_id=ctx.descriptor.environment_id,
            host=ctx.descriptor.label,
            executor=ExecutorInfo(type="import"),
            config_hash=hashlib.sha256(
                json.dumps(data.config, sort_keys=True).encode()
            ).hexdigest(),
            status=RunStatus.FINISHED if data.exit_code == 0 else RunStatus.FAILED,
            created_at=created,
            started_at=data.start,
            ended_at=max(created, data.end or created),
            exit_code=data.exit_code,
            tags=sorted(set(["wandb", *data.tags])),
            name=clean_run_name(" ".join(data.name.split())[:NAME_MAX]),
            created_by="wandb-import",
            params={k: str(v) for k, v in data.config.items() if not k.startswith("_")},
        )
        for sub in RUN_SUBDIRS:
            (folder / sub).mkdir()
        write_yaml(folder / "run.yaml", record.model_dump(mode="json"))
        write_yaml(folder / "config.yaml", data.config)
        provenance = {
            "format": source_format,
            "snapshot": source_format != "wandb",
            "source": str(source),
            "sha256": content_hash,
            "run_id": data.run_id,
            "name": data.name,
            "project": data.project,
            "entity": data.entity,
            "metric_points": data.count,
            "indexed_dropped_rows": data.thinner.dropped_rows,
            "summary": data.summary,
        }
        (folder / "env" / "wandb.json").write_text(json.dumps(provenance), encoding="utf-8")
        ctx.register_project(repo)
        destination = ctx.layout.run_dir(config.project, run_id)
        # Serialize the publish decision, including concurrent identical imports.
        with dir_lock(ctx.layout.home / ".wandb-import-lock"):
            imported = not destination.exists()
            if imported:
                destination.parent.mkdir(parents=True, exist_ok=True)
                folder.rename(destination)
                ctx.events.append(
                    "run.created",
                    project=config.project,
                    run_id=run_id,
                    payload={"status": record.status.value, "source": "wandb"},
                )
            else:
                return WandbImportResult(
                    record=ctx.store.read_record(config.project, run_id),
                    imported=False,
                    metric_points=data.count,
                )
            with run_lock(destination):
                record = ctx.store.read_record(config.project, run_id)
                # Publish points before the run row. If either write fails, the
                # normal missing-run repair can recover the complete disk state.
                ctx.index.replace_metric_points(run_id, data.thinner.points())
                ctx.index.upsert_run(record)
        return WandbImportResult(record=record, imported=imported, metric_points=data.count)
