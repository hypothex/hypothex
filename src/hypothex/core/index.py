"""Rebuildable SQLite index over the file store."""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Float, Integer, String, Text, create_engine, delete, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from hypothex.core.records import MetricPoint, RunRecord, RunStatus, ScoreRecord
from hypothex.core.store import ProjectEntry, RunStore

SCHEMA_VERSION = 1
MAX_POINTS_PER_METRIC = 1000


class Base(DeclarativeBase):
    """Declarative base for index tables."""


class MetaRow(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)


class ProjectRow(Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String, primary_key=True)
    repo: Mapped[str] = mapped_column(String)
    entry_json: Mapped[str] = mapped_column(Text)


class DatasetRow(Base):
    __tablename__ = "datasets"
    project: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String)
    host: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)


class MetricRow(Base):
    __tablename__ = "metrics"
    project: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String)
    fn: Mapped[str] = mapped_column(String)
    higher_is_better: Mapped[bool] = mapped_column(Boolean)


class TaskRow(Base):
    __tablename__ = "tasks"
    project: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, primary_key=True)
    dataset: Mapped[str] = mapped_column(String)
    split: Mapped[str | None] = mapped_column(String, nullable=True)
    primary: Mapped[str] = mapped_column(String)
    metrics_json: Mapped[str] = mapped_column(Text)


class RunRow(Base):
    __tablename__ = "runs"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    project: Mapped[str] = mapped_column(String, index=True)
    task: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[str] = mapped_column(String, index=True)  # ISO-8601 UTC sorts correctly
    config_hash: Mapped[str] = mapped_column(String)
    commit: Mapped[str | None] = mapped_column(String, nullable=True)
    environment_id: Mapped[str] = mapped_column(String)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    record_json: Mapped[str] = mapped_column(Text)


class RunTagRow(Base):
    __tablename__ = "run_tags"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    tag: Mapped[str] = mapped_column(String, primary_key=True, index=True)


class ScoreRow(Base):
    __tablename__ = "scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    record_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String)


class MetricPointRow(Base):
    __tablename__ = "metric_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    step: Mapped[int] = mapped_column(Integer)
    value: Mapped[float] = mapped_column(Float)
    t: Mapped[float | None] = mapped_column(Float, nullable=True)


_DATA_TABLES = (
    ProjectRow,
    DatasetRow,
    MetricRow,
    TaskRow,
    RunRow,
    RunTagRow,
    ScoreRow,
    MetricPointRow,
)


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


def downsample(points: list[MetricPoint], limit: int = MAX_POINTS_PER_METRIC) -> list[MetricPoint]:
    """
    Keep at most ``limit`` evenly spaced points per metric name, always keeping the last.

    Parameters
    ----------
    points : list of MetricPoint
        Full history.
    limit : int
        Maximum points per name.

    Returns
    -------
    list of MetricPoint
        Downsampled points grouped by name, ordered by step.
    """
    by_name: dict[str, list[MetricPoint]] = defaultdict(list)
    for point in points:
        by_name[point.name].append(point)
    out: list[MetricPoint] = []
    for name in sorted(by_name):
        series = sorted(by_name[name], key=lambda p: p.step)
        if len(series) > limit:
            kept = series[:: math.ceil(len(series) / limit)]
            if kept[-1] is not series[-1]:
                kept = kept[: limit - 1] + [series[-1]]
            series = kept
        out.extend(series)
    return out


class Index:
    """
    SQLite index used for fast listing and filtering.

    The index is disposable: when ``SCHEMA_VERSION`` changes it is recreated
    empty and ``rebuilt_schema`` is True so the caller rebuilds it from files.

    Parameters
    ----------
    path : Path
        SQLite file path.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 10}
        )
        event.listen(self.engine, "connect", _sqlite_pragmas)
        self.rebuilt_schema = self._ensure_schema()

    def _ensure_schema(self) -> bool:
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            row = session.get(MetaRow, "schema_version")
            if row is not None and row.value == str(SCHEMA_VERSION):
                return False
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session, session.begin():
            session.add(MetaRow(key="schema_version", value=str(SCHEMA_VERSION)))
        return True

    def clear(self) -> None:
        """Delete all indexed data (keeps the schema)."""
        with Session(self.engine) as session, session.begin():
            for model in _DATA_TABLES:
                session.execute(delete(model))

    # projects -----------------------------------------------------------------
    def upsert_project(self, entry: ProjectEntry) -> None:
        """
        Index a project and its datasets, metrics, and tasks.

        Parameters
        ----------
        entry : ProjectEntry
            Registered project to index.
        """
        cfg = entry.config
        with Session(self.engine) as session, session.begin():
            session.merge(
                ProjectRow(name=entry.project, repo=entry.repo, entry_json=entry.model_dump_json())
            )
            for model in (DatasetRow, MetricRow, TaskRow):
                session.execute(delete(model).where(model.project == entry.project))
            session.add_all(
                DatasetRow(
                    project=entry.project, name=n, version=d.version, host=d.host, path=d.path
                )
                for n, d in cfg.datasets.items()
            )
            session.add_all(
                MetricRow(
                    project=entry.project,
                    name=n,
                    version=m.version,
                    fn=m.fn,
                    higher_is_better=m.higher_is_better,
                )
                for n, m in cfg.metrics.items()
            )
            session.add_all(
                TaskRow(
                    project=entry.project,
                    name=n,
                    dataset=t.dataset,
                    split=t.split,
                    primary=t.primary,
                    metrics_json=json.dumps(t.metrics),
                )
                for n, t in cfg.tasks.items()
            )

    def list_projects(self) -> list[ProjectEntry]:
        """
        Return indexed projects sorted by name.

        Returns
        -------
        list of ProjectEntry
        """
        with Session(self.engine) as session:
            rows = session.scalars(select(ProjectRow.entry_json).order_by(ProjectRow.name))
            return [ProjectEntry.model_validate_json(r) for r in rows]

    def get_project(self, name: str) -> ProjectEntry | None:
        """
        Return one indexed project or None.

        Parameters
        ----------
        name : str
            Project name.

        Returns
        -------
        ProjectEntry or None
        """
        with Session(self.engine) as session:
            row = session.get(ProjectRow, name)
            return ProjectEntry.model_validate_json(row.entry_json) if row else None

    # runs ---------------------------------------------------------------------
    def upsert_run(self, record: RunRecord) -> None:
        """
        Insert or replace one run and its tags.

        Parameters
        ----------
        record : RunRecord
            Run to index.
        """
        with Session(self.engine) as session, session.begin():
            session.merge(
                RunRow(
                    run_id=record.run_id,
                    project=record.project,
                    task=record.task,
                    status=record.status.value,
                    created_at=record.created_at.isoformat(),
                    config_hash=record.config_hash,
                    commit=record.git.commit,
                    environment_id=record.environment_id,
                    archived=record.archived,
                    starred=record.starred,
                    record_json=record.model_dump_json(),
                )
            )
            session.execute(delete(RunTagRow).where(RunTagRow.run_id == record.run_id))
            session.add_all(
                RunTagRow(run_id=record.run_id, tag=t) for t in sorted(set(record.tags))
            )

    def get_run(self, run_id: str) -> RunRecord | None:
        """
        Return one indexed run or None.

        Parameters
        ----------
        run_id : str
            Run id.

        Returns
        -------
        RunRecord or None
        """
        with Session(self.engine) as session:
            row = session.get(RunRow, run_id)
            return RunRecord.model_validate_json(row.record_json) if row else None

    def list_runs(
        self,
        *,
        project: str | None = None,
        task: str | None = None,
        status: RunStatus | str | None = None,
        tag: str | None = None,
        include_archived: bool = False,
        limit: int | None = 500,
    ) -> list[RunRecord]:
        """
        List runs, newest first.

        Parameters
        ----------
        project, task, status, tag : optional
            Filters; ``None`` means no filter.
        include_archived : bool
            Include archived runs.
        limit : int or None
            Maximum rows; ``None`` for all.

        Returns
        -------
        list of RunRecord
        """
        stmt = select(RunRow.record_json).order_by(RunRow.created_at.desc(), RunRow.run_id.desc())
        if project is not None:
            stmt = stmt.where(RunRow.project == project)
        if task is not None:
            stmt = stmt.where(RunRow.task == task)
        if status is not None:
            stmt = stmt.where(RunRow.status == str(status))
        if tag is not None:
            stmt = stmt.join(RunTagRow, RunTagRow.run_id == RunRow.run_id).where(
                RunTagRow.tag == tag
            )
        if not include_archived:
            stmt = stmt.where(RunRow.archived.is_(False))
        if limit is not None:
            stmt = stmt.limit(limit)
        with Session(self.engine) as session:
            return [RunRecord.model_validate_json(j) for j in session.scalars(stmt)]

    def run_ids(self) -> set[str]:
        """
        Return all indexed run ids.

        Returns
        -------
        set of str
        """
        with Session(self.engine) as session:
            return set(session.scalars(select(RunRow.run_id)))

    def delete_run(self, run_id: str) -> None:
        """
        Drop a run and its tags, scores, and metric points from the index.

        Used when the run's folder is gone; the files are the source of truth.

        Parameters
        ----------
        run_id : str
            Run id.
        """
        with Session(self.engine) as session, session.begin():
            for model in (RunRow, RunTagRow, ScoreRow, MetricPointRow):
                session.execute(delete(model).where(model.run_id == run_id))

    def get_meta(self, key: str) -> str | None:
        """
        Return a stored index setting, or None.

        Parameters
        ----------
        key : str
            Setting name, e.g. ``schema_version``.

        Returns
        -------
        str or None
        """
        with Session(self.engine) as session:
            row = session.get(MetaRow, key)
            return None if row is None else row.value

    def set_meta(self, key: str, value: str) -> None:
        """
        Store an index setting.

        Parameters
        ----------
        key : str
            Setting name.
        value : str
            Its value.
        """
        with Session(self.engine) as session, session.begin():
            session.merge(MetaRow(key=key, value=value))

    # scores -------------------------------------------------------------------
    def add_score(self, run_id: str, score: ScoreRecord) -> None:
        """
        Index one score.

        Parameters
        ----------
        run_id : str
            Run id the score belongs to.
        score : ScoreRecord
            Score to index.
        """
        with Session(self.engine) as session, session.begin():
            session.add(
                ScoreRow(
                    run_id=run_id,
                    record_json=score.model_dump_json(),
                    created_at=score.created_at.isoformat(),
                )
            )

    def replace_scores(self, run_id: str, scores: list[ScoreRecord]) -> None:
        """
        Replace all indexed scores of one run.

        Parameters
        ----------
        run_id : str
            Run id.
        scores : list of ScoreRecord
            Full replacement set, oldest first.
        """
        with Session(self.engine) as session, session.begin():
            session.execute(delete(ScoreRow).where(ScoreRow.run_id == run_id))
            session.add_all(
                ScoreRow(
                    run_id=run_id,
                    record_json=s.model_dump_json(),
                    created_at=s.created_at.isoformat(),
                )
                for s in scores
            )

    def scores_for(self, run_ids: Iterable[str]) -> dict[str, list[ScoreRecord]]:
        """
        Return scores per run, oldest first; runs without scores are omitted.

        Parameters
        ----------
        run_ids : iterable of str
            Run ids to look up.

        Returns
        -------
        dict of str to list of ScoreRecord
        """
        ids = list(dict.fromkeys(run_ids))
        out: dict[str, list[ScoreRecord]] = {}
        with Session(self.engine) as session:
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                stmt = (
                    select(ScoreRow.run_id, ScoreRow.record_json)
                    .where(ScoreRow.run_id.in_(chunk))
                    .order_by(ScoreRow.created_at, ScoreRow.id)
                )
                for run_id, blob in session.execute(stmt):
                    out.setdefault(run_id, []).append(ScoreRecord.model_validate_json(blob))
        return out

    # metric points ------------------------------------------------------------
    def replace_metric_points(self, run_id: str, points: list[MetricPoint]) -> None:
        """
        Replace one run's indexed (downsampled) metric history.

        Parameters
        ----------
        run_id : str
            Run id.
        points : list of MetricPoint
            Full history to (down)sample and store.
        """
        with Session(self.engine) as session, session.begin():
            session.execute(delete(MetricPointRow).where(MetricPointRow.run_id == run_id))
            session.add_all(
                MetricPointRow(run_id=run_id, name=p.name, step=p.step, value=p.value, t=p.t)
                for p in downsample(points)
            )

    def metric_points(self, run_id: str) -> list[MetricPoint]:
        """
        Return one run's indexed metric history ordered by name then step.

        Parameters
        ----------
        run_id : str
            Run id.

        Returns
        -------
        list of MetricPoint
        """
        stmt = (
            select(MetricPointRow)
            .where(MetricPointRow.run_id == run_id)
            .order_by(MetricPointRow.name, MetricPointRow.step)
        )
        with Session(self.engine) as session:
            return [
                MetricPoint(name=r.name, step=r.step, value=r.value, t=r.t)
                for r in session.scalars(stmt)
            ]


def index_run(index: Index, store: RunStore, record: RunRecord) -> None:
    """
    Index a run, its scores, and its metric points from files.

    Parameters
    ----------
    index : Index
        Index to update.
    store : RunStore
        File store to read scores and metric points from.
    record : RunRecord
        Run to index.
    """
    index.upsert_run(record)
    index.replace_scores(record.run_id, store.read_scores(record.project, record.run_id))
    index.replace_metric_points(
        record.run_id, store.read_metric_points(record.project, record.run_id)
    )


def rebuild_index(index: Index, store: RunStore) -> int:
    """
    Rebuild the whole index from files.

    Parameters
    ----------
    index : Index
        Index to clear and repopulate.
    store : RunStore
        File store, the source of truth.

    Returns
    -------
    int
        Number of runs indexed.
    """
    index.clear()
    for entry in store.list_projects():
        index.upsert_project(entry)
    count = 0
    for record in store.iter_records():
        index_run(index, store, record)
        count += 1
    return count


def repair_index_gaps(index: Index, store: RunStore) -> list[str]:
    """
    Index projects and run folders that have no index row yet.

    Parameters
    ----------
    index : Index
        Index to fill in.
    store : RunStore
        File store, the source of truth.

    Returns
    -------
    list of str
        Run ids that were added, sorted.
    """
    for entry in store.list_projects():
        if index.get_project(entry.project) is None:
            index.upsert_project(entry)
    on_disk = store.list_run_ids()
    missing = sorted(set(on_disk) - index.run_ids())
    added: list[str] = []
    for run_id in missing:
        try:
            record = store.read_record(on_disk[run_id], run_id)
        except Exception:  # noqa: BLE001 - unreadable folders are skipped, not fatal
            continue
        index_run(index, store, record)
        added.append(run_id)
    return added


STORE_SCAN_KEY = "store_scanned"
SETTLED_NANOSECONDS = 2_000_000_000
"""A folder changed this recently may still be filling in; its scan is not trusted yet."""


def store_fingerprint(store: RunStore) -> tuple[str, bool]:
    """
    Fingerprint the folders a new run or project changes, without listing runs.

    Creating or deleting a run folder changes the modification time of its
    project's ``runs/`` folder; a new or re-registered project changes the
    store folder or its project folder. So this costs one ``stat`` per
    project, not per run.

    Parameters
    ----------
    store : RunStore
        File store.

    Returns
    -------
    fingerprint : str
        Stable text of the folders' modification times.
    settled : bool
        False when any of them changed in the last ``SETTLED_NANOSECONDS`` (a
        run folder may exist before its ``run.yaml``, and coarse clocks give
        two changes in one tick the same time).

    Examples
    --------
    >>> store_fingerprint(RunStore(layout))  # doctest: +SKIP
    ('[["", 1759480000000000000], ["toy", ...]]', True)
    """
    root = store.layout.store
    stamps: list[tuple[str, int]] = [("", root.stat().st_mtime_ns)]
    for project in sorted(p for p in root.iterdir() if p.is_dir()):
        stamps.append((project.name, project.stat().st_mtime_ns))
        runs = project / "runs"
        if runs.is_dir():
            stamps.append((f"{project.name}/runs", runs.stat().st_mtime_ns))
    newest = max(ns for _, ns in stamps)
    return json.dumps(stamps), time.time_ns() - newest >= SETTLED_NANOSECONDS


def repair_index_if_changed(index: Index, store: RunStore) -> list[str]:
    """
    Run ``repair_index_gaps`` only when run or project folders changed since the last scan.

    ``Context.open`` calls this on every open (each CLI command, each
    supervisor), so an unchanged store costs one ``stat`` per project instead
    of a listing of every run folder.

    Parameters
    ----------
    index : Index
        Index to fill in.
    store : RunStore
        File store, the source of truth.

    Returns
    -------
    list of str
        Run ids that were added, sorted.
    """
    fingerprint, settled = store_fingerprint(store)
    if index.get_meta(STORE_SCAN_KEY) == fingerprint:
        return []
    added = repair_index_gaps(index, store)
    if settled:  # taken before the scan: a later change gives a new fingerprint
        index.set_meta(STORE_SCAN_KEY, fingerprint)
    return added
