"""Rebuildable SQLite index over the file store."""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import math
import sqlite3
import time
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    event,
    func,
    insert,
    select,
    text,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from hypothex.core.errors import RunNotFoundError
from hypothex.core.records import MetricPoint, RunRecord, RunStatus, ScoreRecord
from hypothex.core.store import ProjectEntry, RunStore

if TYPE_CHECKING:
    from hypothex.core.context import Context

SCHEMA_VERSION = 3
MAX_POINTS_PER_METRIC = 1000
GENERATION_KEY = "generation"
"""``meta`` row holding the index generation (see ``index_generation``)."""


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
    parent: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
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


class HostCursorRow(Base):
    """Last remote event sequence the hub mirrored, per host and environment."""

    __tablename__ = "host_cursors"
    host: Mapped[str] = mapped_column(String, primary_key=True)
    environment_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)


class RunChangeRow(Base):
    """The index generation of the last write that touched each run."""

    __tablename__ = "run_changes"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    generation: Mapped[int] = mapped_column(Integer)


class PointsPendingRow(Base):
    """Runs whose metric points a rebuild skipped; ``metric_points`` reads them on first use."""

    __tablename__ = "metric_points_pending"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)


# HostCursorRow is not listed: ``clear()`` (``hx reindex``) keeps the mirror cursors,
# because the mirrored run folders stay on disk and need no replay.
_DATA_TABLES = (
    ProjectRow,
    DatasetRow,
    MetricRow,
    TaskRow,
    RunRow,
    RunTagRow,
    ScoreRow,
    MetricPointRow,
    PointsPendingRow,
)
_CARRIED_TABLES = (HostCursorRow,)
"""Rows a rebuild copies from the old index: they are not derived from run folders."""

_BUMP_GENERATION = text(
    "INSERT INTO meta(key, value) VALUES (:key, '1') ON CONFLICT(key) "
    "DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
).bindparams(key=GENERATION_KEY)
_MARK_RUN = text(
    "INSERT INTO run_changes(run_id, generation) "
    "SELECT :run_id, CAST(value AS INTEGER) FROM meta WHERE key = :key "
    "ON CONFLICT(run_id) DO UPDATE SET generation = excluded.generation"
).bindparams(key=GENERATION_KEY)


def _touch(session: Session, *run_ids: str) -> None:
    """Bump the index generation and record which runs changed, in the caller's transaction."""
    session.execute(_BUMP_GENERATION)
    for run_id in run_ids:
        session.execute(_MARK_RUN, {"run_id": run_id})


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


def _run_values(record: RunRecord) -> dict[str, Any]:
    """Column values of one ``runs`` row."""
    return {
        "run_id": record.run_id,
        "project": record.project,
        "task": record.task,
        "status": record.status.value,
        "created_at": record.created_at.isoformat(),
        "config_hash": record.config_hash,
        "commit": record.git.commit,
        "environment_id": record.environment_id,
        "parent": record.parent,
        "archived": record.archived,
        "starred": record.starred,
        "record_json": record.model_dump_json(),
    }


def _score_values(run_id: str, score: ScoreRecord) -> dict[str, Any]:
    """Column values of one ``scores`` row (the id is assigned by SQLite)."""
    return {
        "run_id": run_id,
        "record_json": score.model_dump_json(),
        "created_at": score.created_at.isoformat(),
    }


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

    The index is disposable. A new file, or one written with another
    ``SCHEMA_VERSION``, sets ``rebuilt_schema``: the caller then rebuilds it
    from files (``rebuild_index``). An old index is left as it is until that
    rebuild replaces it in one transaction, so readers never see it half
    built. A new file gets empty tables at once.

    Parameters
    ----------
    path : Path
        SQLite file path.
    store : RunStore, optional
        File store that ``metric_points`` reads when a rebuild skipped a run's
        points; without it those runs have no points until they are re-indexed.
    """

    def __init__(self, path: Path, store: RunStore | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.store = store
        self.engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 10}
        )
        event.listen(self.engine, "connect", _sqlite_pragmas)
        self.rebuilt_schema = self._ensure_schema()

    def schema_version(self) -> str | None:
        """
        Return the schema version the last rebuild stored, or None.

        Returns
        -------
        str or None
            None for a new file, or one no rebuild has finished.
        """
        try:
            return self.get_meta("schema_version")
        except OperationalError:  # a new file: no meta table yet
            return None

    def _ensure_schema(self) -> bool:
        """Create the tables of a new file; True when the caller must rebuild."""
        if self.schema_version() == str(SCHEMA_VERSION):
            return False
        with self.engine.connect() as conn:
            tables = conn.execute(
                text("SELECT count(*) FROM sqlite_master WHERE type = 'table'")
            ).scalar_one()
        if not tables:
            Base.metadata.create_all(self.engine)
        return True

    def generation(self) -> int:
        """
        Return the index generation: it grows on every write of indexed data.

        Every write of projects, runs, tags, scores, or metric points (and
        every rebuild) adds at least 1 in the same transaction, so two equal
        readings mean nothing indexed changed in between, also across
        processes. Bookkeeping (``set_meta``, ``set_cursor``) does not count.

        Returns
        -------
        int
            0 for an index that was never written.

        Examples
        --------
        >>> import tempfile
        >>> idx = Index(Path(tempfile.mkdtemp()) / "i.db")
        >>> before = idx.generation()
        >>> idx.delete_run("nope")
        >>> idx.generation() > before
        True
        """
        value = self.get_meta(GENERATION_KEY)
        return int(value) if value is not None else 0

    def clear(self) -> None:
        """Delete all indexed data except the hub's mirror cursors (keeps the schema)."""
        with Session(self.engine) as session, session.begin():
            for model in _DATA_TABLES:
                session.execute(delete(model))
            _touch(session)

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
            _touch(session)
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
            _touch(session, record.run_id)
            session.merge(RunRow(**_run_values(record)))
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
        environment_id: str | None = None,
        include_archived: bool = False,
        limit: int | None = 500,
    ) -> list[RunRecord]:
        """
        List runs, newest first.

        Parameters
        ----------
        project, task, status, tag : optional
            Filters; ``None`` means no filter.
        environment_id : str, optional
            Only runs of this environment (e.g. one host's queue); ``None`` means all.
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
        if environment_id is not None:
            stmt = stmt.where(RunRow.environment_id == environment_id)
        if not include_archived:
            stmt = stmt.where(RunRow.archived.is_(False))
        if limit is not None:
            stmt = stmt.limit(limit)
        with Session(self.engine) as session:
            return [RunRecord.model_validate_json(j) for j in session.scalars(stmt)]

    def child_run_ids(self, run_id: str) -> list[str]:
        """
        Return the ids of runs whose ``parent`` is ``run_id``, archived ones too.

        One lookup on the indexed ``parent`` column, whatever the project size.

        Parameters
        ----------
        run_id : str
            Parent run id.

        Returns
        -------
        list of str
            Child run ids, newest first.

        Examples
        --------
        >>> idx.child_run_ids("20261004-101500-qa-1a2b3c4d")  # doctest: +SKIP
        ['20261004-111500-qa-5e6f7a8b']
        """
        stmt = (
            select(RunRow.run_id)
            .where(RunRow.parent == run_id)
            .order_by(RunRow.created_at.desc(), RunRow.run_id.desc())
        )
        with Session(self.engine) as session:
            return list(session.scalars(stmt))

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
            _touch(session, run_id)
            for model in (RunRow, RunTagRow, ScoreRow, MetricPointRow, PointsPendingRow):
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
            _touch(session, run_id)
            session.add(ScoreRow(**_score_values(run_id, score)))

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
            _touch(session, run_id)
            session.execute(delete(ScoreRow).where(ScoreRow.run_id == run_id))
            if scores:
                session.execute(insert(ScoreRow), [_score_values(run_id, s) for s in scores])

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
        rows = [
            {"run_id": run_id, "name": p.name, "step": p.step, "value": p.value, "t": p.t}
            for p in downsample(points)
        ]
        with Session(self.engine) as session, session.begin():
            _touch(session, run_id)
            session.execute(delete(MetricPointRow).where(MetricPointRow.run_id == run_id))
            session.execute(delete(PointsPendingRow).where(PointsPendingRow.run_id == run_id))
            if rows:
                session.execute(insert(MetricPointRow), rows)

    def metric_points(self, run_id: str) -> list[MetricPoint]:
        """
        Return one run's indexed metric history ordered by name then step.

        A rebuild does not read ``metrics.jsonl`` files (the slow part of a
        rebuild); the first call for such a run reads its file through
        ``store`` and indexes the points, so the result is the same as if the
        rebuild had read them.

        Parameters
        ----------
        run_id : str
            Run id.

        Returns
        -------
        list of MetricPoint
        """
        if self.store is not None:
            with Session(self.engine) as session:
                pending = session.get(PointsPendingRow, run_id) is not None
                project = session.scalar(select(RunRow.project).where(RunRow.run_id == run_id))
            if pending and project is not None:
                self.replace_metric_points(run_id, self.store.read_metric_points(project, run_id))
        stmt = (
            select(MetricPointRow.name, MetricPointRow.step, MetricPointRow.value, MetricPointRow.t)
            .where(MetricPointRow.run_id == run_id)
            .order_by(MetricPointRow.name, MetricPointRow.step)
        )
        with Session(self.engine) as session:
            return [
                MetricPoint(name=name, step=step, value=value, t=t)
                for name, step, value, t in session.execute(stmt)
            ]

    # host cursors -------------------------------------------------------------
    def get_cursor(self, host: str, environment_id: str) -> int:
        """
        Return the last mirrored event sequence of one host environment.

        Parameters
        ----------
        host : str
            Host name from ``environments.yaml``.
        environment_id : str
            The host's stable environment id.

        Returns
        -------
        int
            Last mirrored sequence; 0 when the pair was never mirrored.

        Examples
        --------
        >>> import tempfile
        >>> idx = Index(Path(tempfile.mkdtemp()) / "i.db")
        >>> idx.get_cursor("gpu1", "env-a")
        0
        >>> idx.set_cursor("gpu1", "env-a", 42)
        >>> idx.get_cursor("gpu1", "env-a")
        42
        """
        with Session(self.engine) as session:
            row = session.get(HostCursorRow, (host, environment_id))
            return row.last_sequence if row else 0

    def set_cursor(self, host: str, environment_id: str, last_sequence: int) -> None:
        """
        Store the last mirrored event sequence of one host environment.

        The cursor only moves forward: one atomic upsert keeps the larger of
        the stored and the new value, so a late writer never moves it back.

        Parameters
        ----------
        host : str
            Host name from ``environments.yaml``.
        environment_id : str
            The host's stable environment id.
        last_sequence : int
            Sequence of the last event the hub mirrored.
        """
        stmt = sqlite_insert(HostCursorRow).values(
            host=host, environment_id=environment_id, last_sequence=last_sequence
        )
        newer = func.max(HostCursorRow.last_sequence, stmt.excluded.last_sequence)
        stmt = stmt.on_conflict_do_update(
            index_elements=["host", "environment_id"], set_={"last_sequence": newer}
        )
        with Session(self.engine) as session, session.begin():
            session.execute(stmt)


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


def index_generation(ctx: Context) -> int:
    """
    Return the index generation of a context: it grows on every index write.

    Every write of indexed data (a run upserted or deleted, a score added or
    replaced, metric points replaced, a project registered, a rebuild) adds
    at least 1 in the same SQLite transaction, so the number is consistent
    across processes. Cache anything derived from the index (leaderboards,
    view panels) under this number: an unchanged generation means unchanged
    index data. It is one primary-key read, cheap enough for every request.
    Bookkeeping writes (``Index.set_meta``, ``Index.set_cursor``) do not
    count, and files that change without an index write (a live run's
    ``metrics.jsonl``) are not seen.

    Parameters
    ----------
    ctx : Context
        Open context.

    Returns
    -------
    int
        The generation; 0 for an index that was never written.

    Examples
    --------
    >>> before = index_generation(ctx)  # doctest: +SKIP
    >>> ctx.add_score(record, score)  # doctest: +SKIP
    >>> index_generation(ctx) > before  # doctest: +SKIP
    True
    """
    return ctx.index.generation()


REBUILD_BATCH = 2000
"""Rows per ``executemany`` while a rebuild fills its temporary database."""


@contextlib.contextmanager
def _rebuild_lock(index: Index) -> Iterator[None]:
    """
    Hold the cross-process lock that lets one rebuild of ``index`` run at a time.

    On a file system without ``flock`` the rebuild runs unlocked: it is still
    atomic, two processes may just both rebuild.
    """
    lock_path = index.path.with_name(index.path.name + ".rebuild.lock")
    with lock_path.open("a") as fh:
        locked = True
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            if exc.errno not in (errno.ENOSYS, errno.ENOLCK, errno.EOPNOTSUPP):
                raise
            locked = False
        try:
            yield
        finally:
            if locked:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _insert_sql(table: str, schema: str, columns: Iterable[str]) -> str:
    cols = list(columns)
    names = ", ".join(f'"{c}"' for c in cols)
    marks = ", ".join(f":{c}" for c in cols)
    return f'INSERT INTO {schema}."{table}" ({names}) VALUES ({marks})'


class _Batch:
    """Collects row dicts per table and writes them with ``executemany``."""

    def __init__(self, conn: sqlite3.Connection, schema: str) -> None:
        self.conn = conn
        self.schema = schema
        self.rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.size = 0

    def add(self, table: str, row: dict[str, Any]) -> None:
        self.rows[table].append(row)
        self.size += 1
        if self.size >= REBUILD_BATCH:
            self.flush()

    def flush(self) -> None:
        for name, rows in self.rows.items():
            if rows:
                self.conn.executemany(_insert_sql(name, self.schema, rows[0]), rows)
        self.rows.clear()
        self.size = 0


def _add_run(batch: _Batch, store: RunStore, record: RunRecord) -> None:
    """Queue one run, its tags, its scores, and a pending mark for its metric points."""
    batch.add(RunRow.__tablename__, _run_values(record))
    for tag in sorted(set(record.tags)):
        batch.add(RunTagRow.__tablename__, {"run_id": record.run_id, "tag": tag})
    for score in store.read_scores(record.project, record.run_id):
        batch.add(ScoreRow.__tablename__, _score_values(record.run_id, score))
    batch.add(PointsPendingRow.__tablename__, {"run_id": record.run_id})


def _add_project(batch: _Batch, entry: ProjectEntry) -> None:
    """Queue one project and its datasets, metrics, and tasks."""
    cfg, name = entry.config, entry.project
    batch.add(
        ProjectRow.__tablename__,
        {"name": name, "repo": entry.repo, "entry_json": entry.model_dump_json()},
    )
    for n, d in cfg.datasets.items():
        row = {"project": name, "name": n, "version": d.version, "host": d.host, "path": d.path}
        batch.add(DatasetRow.__tablename__, row)
    for n, m in cfg.metrics.items():
        row = {
            "project": name,
            "name": n,
            "version": m.version,
            "fn": m.fn,
            "higher_is_better": m.higher_is_better,
        }
        batch.add(MetricRow.__tablename__, row)
    for n, t in cfg.tasks.items():
        row = {
            "project": name,
            "name": n,
            "dataset": t.dataset,
            "split": t.split,
            "primary": t.primary,
            "metrics_json": json.dumps(t.metrics),
        }
        batch.add(TaskRow.__tablename__, row)


def _table_names(conn: sqlite3.Connection, schema: str) -> set[str]:
    rows = conn.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    return {r[0] for r in rows}


def _int_meta(conn: sqlite3.Connection, key: str) -> int:
    """An integer ``main.meta`` value; 0 when the table or row is missing."""
    try:
        row = conn.execute("SELECT value FROM main.meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row is not None else 0


def _build_fresh(path: Path, store: RunStore) -> int:
    """Write every run of ``store`` into a new database at ``path``; return the run count."""
    for leftover in (path, path.with_name(path.name + "-journal")):
        leftover.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=OFF")  # a throwaway file: a crash just deletes it
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("BEGIN")
        batch = _Batch(conn, "main")
        count = 0
        for record in store.iter_records():
            _add_run(batch, store, record)
            count += 1
        batch.flush()
        conn.execute("COMMIT")
    finally:
        conn.close()
    return count


def _catch_up(conn: sqlite3.Connection, store: RunStore, since: int) -> None:
    """
    Re-read into ``fresh`` the runs written to the live index after generation ``since``.

    Runs while the live index is locked for writing, so every write that
    committed during the rebuild is seen here, and every later one lands on
    top of the swapped-in data.
    """
    if "run_changes" not in _table_names(conn, "main"):
        return
    changed = [
        (run_id, project)
        for run_id, project in conn.execute(
            "SELECT c.run_id, r.project FROM main.run_changes c "
            "LEFT JOIN main.runs r ON r.run_id = c.run_id WHERE c.generation > ?",
            (since,),
        )
    ]
    batch = _Batch(conn, "fresh")
    for run_id, project in changed:
        for name in ("runs", "run_tags", "scores", "metric_points_pending"):
            conn.execute(f'DELETE FROM fresh."{name}" WHERE run_id = ?', (run_id,))
        try:
            record = store.read_record(project or store.find_project_of(run_id), run_id)
        except RunNotFoundError:
            continue  # the folder is gone: the run stays out
        except Exception:  # noqa: BLE001 - an unreadable run.yaml is skipped, as in a scan
            continue
        _add_run(batch, store, record)
    batch.flush()


def _swap_in(index: Index, store: RunStore, fresh: Path, since: int) -> None:
    """Replace every table of the live index with ``fresh`` in one write transaction."""
    conn = sqlite3.connect(index.path, timeout=60, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("ATTACH DATABASE ? AS fresh", (str(fresh),))
        conn.execute("BEGIN IMMEDIATE")
        try:
            _catch_up(conn, store, since)
            batch = _Batch(conn, "fresh")
            for entry in store.list_projects():  # few and cheap: read under the lock
                _add_project(batch, entry)
            batch.flush()
            live = _table_names(conn, "main")
            for model in _CARRIED_TABLES:
                table = Base.metadata.tables[model.__tablename__]
                if table.name in live:
                    cols = ", ".join(f'"{c.name}"' for c in table.columns)
                    with contextlib.suppress(sqlite3.OperationalError):  # an old shape: drop it
                        conn.execute(
                            f'INSERT OR REPLACE INTO fresh."{table.name}" ({cols}) '
                            f'SELECT {cols} FROM main."{table.name}"'
                        )
            generation = _int_meta(conn, GENERATION_KEY) + 1
            for name in live:
                conn.execute(f'DROP TABLE main."{name}"')
            schema = conn.execute(
                "SELECT type, name, sql FROM fresh.sqlite_master "
                "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type = 'index'"
            ).fetchall()
            for _type, _name, sql in schema:
                conn.execute(sql)  # unqualified: creates it in main
            for _type, name, _sql in schema:
                if _type == "table":
                    conn.execute(f'INSERT INTO main."{name}" SELECT * FROM fresh."{name}"')
            conn.executemany(
                "INSERT OR REPLACE INTO main.meta(key, value) VALUES (?, ?)",
                [("schema_version", str(SCHEMA_VERSION)), (GENERATION_KEY, str(generation))],
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("DETACH DATABASE fresh")
    finally:
        conn.close()


def _rebuild_locked(index: Index, store: RunStore) -> int:
    try:
        since = index.generation()  # read before the scan: later writes are caught up
    except OperationalError:  # a file with no meta table
        since = 0
    fresh = index.path.with_name(index.path.name + ".tmp")
    try:
        count = _build_fresh(fresh, store)
        _swap_in(index, store, fresh, since)
    finally:
        for leftover in (fresh, fresh.with_name(fresh.name + "-journal")):
            leftover.unlink(missing_ok=True)
    index.engine.dispose()  # pooled connections re-read the new schema
    return count


def rebuild_index(index: Index, store: RunStore) -> int:
    """
    Rebuild the whole index from files, atomically.

    The runs are written into ``<index>.tmp`` first, without any lock on the
    live index; then one write transaction re-reads the runs written to the
    live index meanwhile, copies the hub's mirror cursors, and replaces every
    table. Readers (other processes too) see the old index until that
    transaction commits, then the new one, never a part of it; a write that
    lands during the rebuild is kept. Metric points are not read here:
    ``Index.metric_points`` reads a run's file on first use. One rebuild runs
    at a time (a lock file next to the index).

    Parameters
    ----------
    index : Index
        Index to repopulate.
    store : RunStore
        File store, the source of truth.

    Returns
    -------
    int
        Number of runs indexed.
    """
    with _rebuild_lock(index):
        return _rebuild_locked(index, store)


def rebuild_index_if_stale(index: Index, store: RunStore) -> int | None:
    """
    Rebuild the index unless its stored schema version is current.

    For ``Context.open``: when several processes open an old index at once,
    the first rebuilds it and the others wait for that rebuild, then find the
    index current and do not rebuild it again.

    Parameters
    ----------
    index : Index
        Index to check.
    store : RunStore
        File store, the source of truth.

    Returns
    -------
    int or None
        Number of runs indexed, or None when no rebuild was needed.
    """
    with _rebuild_lock(index):
        if index.schema_version() == str(SCHEMA_VERSION):
            return None
        return _rebuild_locked(index, store)


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
