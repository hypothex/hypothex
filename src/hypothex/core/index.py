"""Rebuildable SQLite or PostgreSQL index over the authoritative file store."""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import logging
import os
import secrets
import sqlite3
import time
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import SecretStr, ValidationError
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    Integer,
    MetaData,
    Select,
    String,
    Table,
    Text,
    cast,
    create_engine,
    delete,
    event,
    func,
    insert,
    or_,
    select,
    text,
    tuple_,
)
from sqlalchemy import Index as SqlIndex
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DatabaseError, InterfaceError, OperationalError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from hypothex.core.errors import ConfigError, HypothexError, RunNotFoundError
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.records import (
    INDEXED_POINT_STATUSES,
    MetricPoint,
    RunRecord,
    RunStatus,
    ScoreRecord,
)
from hypothex.core.settings import ServerSettings, redact_url, resolve_secret
from hypothex.core.stats import lttb
from hypothex.core.store import ProjectEntry, RunStore, run_lock
from hypothex.core.thin import MAX_POINTS_PER_METRIC

if TYPE_CHECKING:
    from hypothex.core.context import Context

log = logging.getLogger(__name__)
SCHEMA_VERSION = 5
HEAD_REVISION = "0001_phase3"
"""The Alembic revision a Postgres index must be at (``hypothex.core.migrations``)."""

INDEX_PENDING_FILE = "index-pending.txt"
"""Run ids whose index write failed after their files were written (``repair_pending``)."""


class IndexUnavailableError(HypothexError):
    """The Postgres index does not answer (HTTP 503)."""


class IndexSchemaError(ConfigError):
    """The Postgres index is not at ``HEAD_REVISION``: run ``hx db upgrade``."""


_IN_CHUNK = 450
"""Most values bound in one ``IN (...)`` list of an index query."""
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
    owner: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    record_json: Mapped[str] = mapped_column(Text)


class RunTagRow(Base):
    __tablename__ = "run_tags"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    tag: Mapped[str] = mapped_column(String, primary_key=True, index=True)


class ScoreRow(Base):
    __tablename__ = "scores"
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    run_id: Mapped[str] = mapped_column(String, index=True)
    record_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String)


class MetricPointRow(Base):
    __tablename__ = "metric_points"
    __table_args__ = (SqlIndex("ix_metric_points_run_name_step", "run_id", "name", "step"),)
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    run_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    step: Mapped[int] = mapped_column(BigInteger)
    value: Mapped[float] = mapped_column(Float)
    t: Mapped[float | None] = mapped_column(Float, nullable=True)


class HostCursorRow(Base):
    """Known host identity and last mirrored event sequence; zero reserves an unused identity."""

    __tablename__ = "host_cursors"
    host: Mapped[str] = mapped_column(String, primary_key=True)
    environment_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, default=0)


class RunChangeRow(Base):
    """The index generation of the last write that touched each run."""

    __tablename__ = "run_changes"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    generation: Mapped[int] = mapped_column(BigInteger)


class PointsPendingRow(Base):
    """Runs whose metric points a rebuild skipped; ``metric_points`` reads them on first use."""

    __tablename__ = "metric_points_pending"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)


class ScoresStaleRow(Base):
    """Runs whose ``scores.jsonl`` may hold scores the index lacks (an add cut short)."""

    __tablename__ = "scores_stale"
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
_CARRIED_TABLES = (HostCursorRow, ScoresStaleRow, RunChangeRow)
"""Rows a rebuild copies from the old index: they are not derived from run folders."""

_BUMP_GENERATION = text(
    "INSERT INTO meta(key, value) VALUES (:key, '1') ON CONFLICT(key) "
    "DO UPDATE SET value = CAST(CAST(meta.value AS BIGINT) + 1 AS TEXT)"
).bindparams(key=GENERATION_KEY)
_MARK_RUN = text(
    "INSERT INTO run_changes(run_id, generation) "
    "SELECT :run_id, CAST(meta.value AS BIGINT) FROM meta WHERE key = :key "
    "ON CONFLICT(run_id) DO UPDATE SET generation = excluded.generation"
).bindparams(key=GENERATION_KEY)


def _touch(session: Session, *run_ids: str) -> None:
    """Bump the index generation and record which runs changed, in the caller's transaction."""
    _index_write_guard(session)
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
        "owner": record.owner,
        "name": record.name,
        "record_json": record.model_dump_json(),
    }


def _score_values(run_id: str, score: ScoreRecord) -> dict[str, Any]:
    """Column values of one ``scores`` row (the id is assigned by the database)."""
    return {
        "run_id": run_id,
        "record_json": score.model_dump_json(),
        "created_at": score.created_at.isoformat(),
    }


def downsample(points: list[MetricPoint], limit: int = MAX_POINTS_PER_METRIC) -> list[MetricPoint]:
    """
    Keep at most ``limit`` points per metric name, chosen by LTTB (``stats.lttb``).

    The first and last points of each series are always kept, and so are its
    peaks: a one-step loss spike survives, unlike every-n-th sampling.

    Parameters
    ----------
    points : list of MetricPoint
        Full history.
    limit : int
        Maximum points per name, at least 2.

    Returns
    -------
    list of MetricPoint
        Downsampled points grouped by name, ordered by step.

    Examples
    --------
    >>> pts = [MetricPoint(name="loss", step=i, value=9.0 if i == 3 else 0.0) for i in range(9)]
    >>> [p.step for p in downsample(pts, limit=3)]
    [0, 3, 8]
    """
    by_name: dict[str, list[MetricPoint]] = defaultdict(list)
    for point in points:
        by_name[point.name].append(point)
    out: list[MetricPoint] = []
    for name in sorted(by_name):
        series = sorted(by_name[name], key=lambda p: p.step)
        keep = lttb([p.step for p in series], [p.value for p in series], limit)
        out.extend(series[i] for i in keep)
    return out


def _filter_runs(
    stmt: Select[Any],
    *,
    project: str | None,
    task: str | None,
    status: RunStatus | str | None,
    tag: str | None,
    environment_id: str | None,
    include_archived: bool,
    search: str | None = None,
    owner: str | None = None,
) -> Select[Any]:
    """Add the ``list_runs`` filters to a select over ``runs``."""
    if project is not None:
        stmt = stmt.where(RunRow.project == project)
    if task is not None:
        stmt = stmt.where(RunRow.task == task)
    if status is not None:
        stmt = stmt.where(RunRow.status == str(status))
    if tag is not None:
        stmt = stmt.join(RunTagRow, RunTagRow.run_id == RunRow.run_id).where(RunTagRow.tag == tag)
    if environment_id is not None:
        stmt = stmt.where(RunRow.environment_id == environment_id)
    if not include_archived:
        stmt = stmt.where(RunRow.archived.is_(False))
    if search:
        stmt = stmt.where(
            or_(
                RunRow.name.icontains(search, autoescape=True),
                RunRow.run_id.icontains(search, autoescape=True),
            )
        )
    if owner is not None:
        stmt = stmt.where(RunRow.owner == owner)
    return stmt


def upsert_statement(
    dialect: str,
    model: type[Base],
    values: dict[str, Any],
    keys: list[str],
    *,
    keep_max: str | None = None,
) -> Any:
    """
    Build ``INSERT ... ON CONFLICT DO UPDATE`` for SQLite or Postgres.

    Parameters
    ----------
    dialect : str
        ``sqlite`` or ``postgresql``.
    model : type
        An index table.
    values : dict
        Column values, keys included.
    keys : list of str
        The conflict target (primary key columns).
    keep_max : str, optional
        A column that keeps the larger of the stored and the new value.

    Returns
    -------
    sqlalchemy.sql.dml.Insert
        The statement.
    """
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    stmt = insert(model).values(**values)
    update: dict[str, Any] = {k: stmt.excluded[k] for k in values if k not in keys}
    if keep_max is not None:
        larger = func.greatest if dialect == "postgresql" else func.max
        update[keep_max] = larger(getattr(model, keep_max), stmt.excluded[keep_max])
    if not update:
        return stmt.on_conflict_do_nothing(index_elements=keys)
    return stmt.on_conflict_do_update(index_elements=keys, set_=update)


def upsert(
    session: Session,
    model: type[Base],
    values: dict[str, Any],
    keys: list[str],
    *,
    keep_max: str | None = None,
) -> None:
    """
    Insert a row or update it in place, atomically, on either dialect.

    Parameters
    ----------
    session : Session
        An open session (inside a transaction).
    model : type
        An index table.
    values : dict
        Column values, keys included.
    keys : list of str
        The conflict target.
    keep_max : str, optional
        A column that keeps the larger value.
    """
    _index_write_guard(session)
    dialect = session.get_bind().dialect.name
    session.execute(upsert_statement(dialect, model, values, keys, keep_max=keep_max))


PG_REBUILD_LOCK = 0x48595801
PG_WRITE_LOCK = 0x48595802


def _index_write_guard(session: Session) -> None:
    """Serialize PostgreSQL index mutations and the final swap; SQLite is unchanged."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PG_WRITE_LOCK})


@contextlib.contextmanager
def _index_write_session(engine: Engine) -> Iterator[Session]:
    """Acquire the PostgreSQL write guard before any live-table DML or row lock."""
    with Session(engine) as session, session.begin():
        _index_write_guard(session)
        yield session


class _Rows(Protocol):
    """The two staging backends share the existing row-building functions."""

    def add(self, table: str, row: dict[str, Any]) -> None: ...
    def flush(self) -> None: ...


class _PgBatch:
    """Batch writes into this transaction's temporary PostgreSQL tables."""

    def __init__(self, session: Session, tables: dict[str, Table]) -> None:
        self.session = session
        self.tables = tables
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
                self.session.execute(insert(self.tables[name]), rows)
        self.rows.clear()
        self.size = 0


def _rebuild_postgres(index: Index, store: RunStore) -> int:
    """
    Stage a rebuild, then catch up changed runs and replace live data in one transaction.

    Parameters
    ----------
    index : Index
        An upgraded PostgreSQL index.
    store : RunStore
        Authoritative file store.

    Returns
    -------
    int
        Number of run rows published.

    Notes
    -----
    Concurrent readers keep seeing committed live data. Writers proceed during
    staging, then wait only for the final swap; their later commits land on the
    rebuilt index. Rebuild never takes run locks while excluding index writes:
    an ordinary writer can already hold one while waiting to index its file.
    """
    with Session(index.engine) as session, session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PG_REBUILD_LOCK})
        since = int(session.scalar(select(MetaRow.value).where(MetaRow.key == GENERATION_KEY)) or 0)
        tables: dict[str, Table] = {}
        metadata = MetaData()
        for model in _DATA_TABLES:
            original = Base.metadata.tables[model.__tablename__]
            name = f"hx_rebuild_{original.name}"
            # Names come only from our metadata. LIKE retains serial defaults,
            # so stage score/point ids use the live sequences (gaps are harmless).
            session.execute(
                text(
                    f'CREATE TEMPORARY TABLE "{name}" (LIKE "{original.name}" INCLUDING DEFAULTS) '
                    "ON COMMIT DROP"
                )
            )
            tables[original.name] = original.to_metadata(metadata, name=name)
        batch = _PgBatch(session, tables)
        for record in store.iter_records():
            _add_run(batch, store, record)
        batch.flush()
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PG_WRITE_LOCK})
        changed = list(
            session.execute(
                select(RunChangeRow.run_id, RunRow.project)
                .outerjoin(RunRow, RunRow.run_id == RunChangeRow.run_id)
                .where(RunChangeRow.generation > since)
            )
        )
        for run_id, project in changed:
            for name in ("runs", "run_tags", "scores", "metric_points_pending"):
                table = tables[name]
                session.execute(delete(table).where(table.c.run_id == run_id))
            try:
                record = store.read_record(project or store.find_project_of(run_id), run_id)
            except RunNotFoundError:
                continue
            except Exception:  # noqa: BLE001 - matches SQLite's unreadable-run policy
                continue
            _add_run(batch, store, record)
        for entry in store.list_projects():
            _add_project(batch, entry)
        batch.flush()
        count = int(session.scalar(select(func.count()).select_from(tables["runs"])) or 0)
        for model in _DATA_TABLES:
            live = Base.metadata.tables[model.__tablename__]
            staged = tables[live.name]
            session.execute(delete(live))
            session.execute(insert(live).from_select(list(live.columns.keys()), select(staged)))
        # Bookkeeping tables are not rebuilt: cursors, stale-score marks and
        # run-change generations survive, including writes made during staging.
        _touch(session)
        upsert(session, MetaRow, {"key": "schema_version", "value": str(SCHEMA_VERSION)}, ["key"])
        session.execute(delete(MetaRow).where(MetaRow.key == STORE_SCAN_KEY))
        return count  # transaction commits before return; any exception rolls it all back


class Index:
    """
    SQLite or PostgreSQL index used for fast listing and filtering.

    The index is disposable. A new file, or one written with another
    ``SCHEMA_VERSION``, sets ``rebuilt_schema``: the caller then rebuilds it
    from files (``rebuild_index``). An old index is left as it is until that
    rebuild replaces it in one transaction, so readers never see it half
    built. A new file gets empty tables at once. A file SQLite cannot read as
    a database (corrupt, or not SQLite) is moved aside to
    ``<name>.corrupt-<time>`` with a warning and replaced by a new file.

    PostgreSQL uses an Alembic-managed schema and checks its revision at open.
    Explicit rebuilding uses temporary tables and atomic transactional
    publication; normal opening never drops or rebuilds a PostgreSQL schema.

    Parameters
    ----------
    target : Path or str
        SQLite file path or password-free PostgreSQL URL.
    password : SecretStr, optional
        PostgreSQL password resolved from the configured secret environment name.
    store : RunStore, optional
        File store that ``metric_points`` reads when a rebuild skipped a run's
        points; without it those runs have no points until they are re-indexed.
    """

    def __init__(
        self,
        target: Path | str,
        store: RunStore | None = None,
        *,
        password: SecretStr | None = None,
    ) -> None:
        self.store = store
        self.cache_identity: object = object()  # private, secret-free lifetime identity
        self.dialect: Literal["sqlite", "postgresql"]
        if isinstance(target, Path):
            self.path = target  # SQLite staging/rebuild owns a local database path
            target.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                f"sqlite:///{target}", connect_args={"check_same_thread": False, "timeout": 10}
            )
            event.listen(self.engine, "connect", _sqlite_pragmas)
            self.dialect = "sqlite"
            self.rebuilt_schema = self._open_schema()
            return
        # Validate direct construction too; credentials only enter via SecretStr.
        try:
            ServerSettings(index_url=target)
        except ValidationError:
            raise ConfigError("index target must be a password-free PostgreSQL URL") from None
        url = make_url(target).set(drivername="postgresql+psycopg")
        if password is not None:
            url = url.set(password=password.get_secret_value())
        try:
            self.engine = create_engine(url, pool_pre_ping=True, isolation_level="READ COMMITTED")
        except ImportError:
            raise ConfigError(
                "a Postgres index needs psycopg: uv tool install 'hypothex[server]'"
            ) from None
        self.dialect = "postgresql"
        self.rebuilt_schema = False  # Alembic owns the schema; never dropped here
        self._check_revision(redact_url(target))

    def _check_revision(self, shown: str) -> None:
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        except ProgrammingError:
            row = None  # no alembic_version table: never upgraded
        except (OperationalError, InterfaceError) as exc:
            self.engine.dispose()
            reason = type(exc.orig).__name__ if exc.orig is not None else "no answer"
            message = f"the index at {shown} does not answer ({reason})"
            raise IndexUnavailableError(message) from None
        found = row[0] if row is not None else "none"
        if found != HEAD_REVISION:
            self.engine.dispose()
            raise IndexSchemaError(
                f"the index at {shown} is at revision {found}, not {HEAD_REVISION}; "
                "run hx db upgrade"
            )

    def json_text(self, column: Any, key: str) -> Any:
        """
        Read one top-level field of a JSON text column, as text.

        Parameters
        ----------
        column : column expression
            E.g. ``RunRow.record_json``.
        key : str
            Field name, e.g. ``ended_at``.

        Returns
        -------
        SQL expression
        """
        if self.dialect == "postgresql":
            return func.json_extract_path_text(cast(column, JSON), key)
        return func.json_extract(column, f"$.{key}")

    pending: Path | None = None
    """Where failed run writes are noted (``open_index`` sets it; None: not noted)."""

    @contextmanager
    def _journal(self, run_id: str) -> Iterator[None]:
        """Note ``run_id`` in ``pending`` when its write fails; the files hold the truth."""
        try:
            yield
        except (OperationalError, InterfaceError):
            if self.pending is not None:
                with contextlib.suppress(OSError):
                    _append_pending(self.pending, run_id)
            raise

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
        except OperationalError as exc:
            if "no such table" in str(exc.orig):  # a new file: no meta table yet
                return None
            raise

    def _open_schema(self) -> bool:
        """``_ensure_schema``, moving a file that is not a database aside first."""
        try:
            return self._ensure_schema()
        except DatabaseError as exc:
            if isinstance(exc, OperationalError):  # locked, read-only, ...: not corrupt
                raise
        with _rebuild_lock(self):
            self.engine.dispose()
            try:
                return self._ensure_schema()  # another process moved it aside meanwhile
            except DatabaseError as exc:
                if isinstance(exc, OperationalError):
                    raise
                self._move_aside(exc)
            return self._ensure_schema()

    def _move_aside(self, exc: DatabaseError) -> None:
        """Rename the unreadable index file and its WAL files to ``*.corrupt-<time>``."""
        self.engine.dispose()
        stamp = utcnow().strftime("%Y%m%dT%H%M%S%f")
        for suffix in ("", "-wal", "-shm"):
            source = self.path.with_name(self.path.name + suffix)
            if source.exists():
                source.replace(self.path.with_name(f"{self.path.name}.corrupt-{stamp}{suffix}"))
        log.warning(
            "index %s is not a readable database (%s); moved it to %s.corrupt-%s and rebuilding",
            self.path,
            exc.orig,
            self.path.name,
            stamp,
        )

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
        with _index_write_session(self.engine) as session:
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
        with _index_write_session(self.engine) as session:
            _touch(session)
            upsert(
                session,
                ProjectRow,
                {"name": entry.project, "repo": entry.repo, "entry_json": entry.model_dump_json()},
                ["name"],
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
                    higher_is_better=m.higher_is_better is not False,
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
        with self._journal(record.run_id), _index_write_session(self.engine) as session:
            _touch(session, record.run_id)
            upsert(session, RunRow, _run_values(record), ["run_id"])
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
        before: tuple[datetime | str, str] | None = None,
        search: str | None = None,
        owner: str | None = None,
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
        before : tuple of (datetime or str, str), optional
            Keyset cursor ``(created_at, run_id)`` of the last run of the
            previous page: only runs after it in this order are returned.
        owner : str, optional
            Only runs owned by this user; None means all owners, including legacy runs.
        search : str, optional
            Only runs whose ``name`` or ``run_id`` contains this text, ignoring
            ASCII case (``%`` and ``_`` match themselves).

        Returns
        -------
        list of RunRecord

        Examples
        --------
        >>> page = idx.list_runs(limit=200)  # doctest: +SKIP
        >>> last = page[-1]  # doctest: +SKIP
        >>> idx.list_runs(limit=200, before=(last.created_at, last.run_id))  # doctest: +SKIP
        >>> idx.list_runs(search="wide beam")  # doctest: +SKIP
        """
        stmt = select(RunRow.record_json).order_by(RunRow.created_at.desc(), RunRow.run_id.desc())
        stmt = _filter_runs(
            stmt,
            project=project,
            task=task,
            status=status,
            tag=tag,
            environment_id=environment_id,
            include_archived=include_archived,
            search=search,
            owner=owner,
        )
        if before is not None:
            created, run_id = before
            stamp = created.isoformat() if isinstance(created, datetime) else created
            stmt = stmt.where(tuple_(RunRow.created_at, RunRow.run_id) < tuple_(stamp, run_id))
        if limit is not None:
            stmt = stmt.limit(limit)
        with Session(self.engine) as session:
            return [RunRecord.model_validate_json(j) for j in session.scalars(stmt)]

    def count_runs(
        self,
        *,
        project: str | None = None,
        task: str | None = None,
        status: RunStatus | str | None = None,
        tag: str | None = None,
        environment_id: str | None = None,
        include_archived: bool = False,
        search: str | None = None,
        owner: str | None = None,
    ) -> int:
        """
        Count the runs ``list_runs`` would return with no limit, without reading them.

        Parameters
        ----------
        project, task, status, tag, environment_id, include_archived, search, owner : optional
            The same filters as ``list_runs``.

        Returns
        -------
        int

        Examples
        --------
        >>> idx.count_runs(project="toy", status="finished")  # doctest: +SKIP
        12
        """
        stmt = _filter_runs(
            select(func.count()).select_from(RunRow),
            project=project,
            task=task,
            status=status,
            tag=tag,
            environment_id=environment_id,
            include_archived=include_archived,
            search=search,
            owner=owner,
        )
        with Session(self.engine) as session:
            return int(session.scalar(stmt) or 0)

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
        with self._journal(run_id), _index_write_session(self.engine) as session:
            _touch(session, run_id)
            for model in (
                RunRow,
                RunTagRow,
                ScoreRow,
                MetricPointRow,
                PointsPendingRow,
                ScoresStaleRow,
            ):
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
        with _index_write_session(self.engine) as session:
            upsert(session, MetaRow, {"key": key, "value": value}, ["key"])

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
        with self._journal(run_id), _index_write_session(self.engine) as session:
            _touch(session, run_id)
            session.add(ScoreRow(**_score_values(run_id, score)))

    def mark_scores_stale(self, run_id: str) -> None:
        """
        Record that a score is about to be appended to the run's ``scores.jsonl``.

        ``replace_scores`` clears the mark. A mark that is still there (the
        writer died between its file append and its index write) makes
        ``repair_stale_scores`` re-index the run's scores from the file. A
        mark is bookkeeping: it does not change the generation.

        Parameters
        ----------
        run_id : str
            Run id.
        """
        with _index_write_session(self.engine) as session:
            upsert(session, ScoresStaleRow, {"run_id": run_id}, ["run_id"])

    def stale_score_runs(self) -> list[str]:
        """
        Return the runs marked by ``mark_scores_stale`` and not re-indexed since.

        Returns
        -------
        list of str
            Run ids, sorted.
        """
        with Session(self.engine) as session:
            return sorted(session.scalars(select(ScoresStaleRow.run_id)))

    def replace_scores(self, run_id: str, scores: list[ScoreRecord]) -> None:
        """
        Replace all indexed scores of one run (and clear its stale mark).

        Parameters
        ----------
        run_id : str
            Run id.
        scores : list of ScoreRecord
            Full replacement set, oldest first.
        """
        with self._journal(run_id), _index_write_session(self.engine) as session:
            _touch(session, run_id)
            session.execute(delete(ScoreRow).where(ScoreRow.run_id == run_id))
            session.execute(delete(ScoresStaleRow).where(ScoresStaleRow.run_id == run_id))
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
        self._replace_metric_points(run_id, points, pending_status=None)

    def _replace_metric_points(
        self, run_id: str, points: list[MetricPoint], *, pending_status: str | None
    ) -> bool:
        """Install points if the pending marker and captured status still match."""
        rows = [
            {"run_id": run_id, "name": p.name, "step": p.step, "value": p.value, "t": p.t}
            for p in downsample(points)
        ]
        with self._journal(run_id), _index_write_session(self.engine) as session:
            # This DELETE obtains the write lock and checks both conditions
            # atomically. A terminal publisher clears the marker; a subsequent
            # rebuild can recreate it, but must not authorize an old live read.
            claim = delete(PointsPendingRow).where(PointsPendingRow.run_id == run_id)
            if pending_status is not None:
                claim = claim.where(
                    select(RunRow.run_id)
                    .where(RunRow.run_id == run_id, RunRow.status == pending_status)
                    .exists()
                )
            pending = session.connection().execute(claim)
            if pending_status is not None and pending.rowcount == 0:
                return False
            _touch(session, run_id)
            session.execute(delete(MetricPointRow).where(MetricPointRow.run_id == run_id))
            if rows:
                session.execute(insert(MetricPointRow), rows)
        return True

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
        return self.metric_points_for([run_id]).get(run_id, [])

    def metric_points_for(
        self, run_ids: Iterable[str], names: Iterable[str] | None = None
    ) -> dict[str, list[MetricPoint]]:
        """
        Return the indexed metric history of many runs, optionally of some names only.

        Uses the ``(run_id, name, step)`` index, so a chart of a few names over
        many runs reads only those rows. Points a rebuild skipped are read
        first, as in ``metric_points``.

        Parameters
        ----------
        run_ids : iterable of str
            Runs to read.
        names : iterable of str, optional
            Metric names to keep; ``None`` keeps all.

        Returns
        -------
        dict of str to list of MetricPoint
            Per run, points ordered by name then step; runs with none are omitted.

        Examples
        --------
        >>> idx.metric_points_for(["r1", "r2"], names=["loss"])  # doctest: +SKIP
        {'r1': [MetricPoint(name='loss', step=0, value=1.0, t=None)]}
        """
        ids = list(dict.fromkeys(run_ids))
        wanted = None if names is None else sorted(set(names))
        self._fill_pending_points(ids)
        out: dict[str, list[MetricPoint]] = {}
        cols = (
            MetricPointRow.run_id,
            MetricPointRow.name,
            MetricPointRow.step,
            MetricPointRow.value,
            MetricPointRow.t,
        )
        # Both lists are cut into chunks: a statement binds at most 2 x _IN_CHUNK
        # values, under SQLite's oldest limit of 999. Sorted name chunks, read in
        # order, keep each run's points ordered by name then step.
        name_chunks: list[list[str] | None] = (
            [None]
            if wanted is None
            else [wanted[i : i + _IN_CHUNK] for i in range(0, len(wanted), _IN_CHUNK)]
        )
        with Session(self.engine) as session:
            for start in range(0, len(ids), _IN_CHUNK):
                chunk = ids[start : start + _IN_CHUNK]
                for name_chunk in name_chunks:
                    stmt = select(*cols).where(MetricPointRow.run_id.in_(chunk))
                    if name_chunk is not None:
                        stmt = stmt.where(MetricPointRow.name.in_(name_chunk))
                    stmt = stmt.order_by(
                        MetricPointRow.run_id, MetricPointRow.name, MetricPointRow.step
                    )
                    for run_id, name, step, value, t in session.execute(stmt):
                        point = MetricPoint(name=name, step=step, value=value, t=t)
                        out.setdefault(run_id, []).append(point)
        return out

    def metric_names(self, run_id: str) -> list[str]:
        """
        Return the names of one run's indexed metrics, sorted.

        Reads only the names through the ``(run_id, name, step)`` index, not
        every point. Points a rebuild skipped are read first, as in
        ``metric_points``.

        Parameters
        ----------
        run_id : str
            Run id.

        Returns
        -------
        list of str
            Distinct metric names; empty for a run with no points.

        Examples
        --------
        >>> idx.metric_names("r1")  # doctest: +SKIP
        ['loss', 'lr']
        """
        self._fill_pending_points([run_id])
        stmt = (
            select(MetricPointRow.name)
            .where(MetricPointRow.run_id == run_id)
            .distinct()
            .order_by(MetricPointRow.name)
        )
        with Session(self.engine) as session:
            return list(session.scalars(stmt))

    def metric_names_for(self, run_ids: Iterable[str]) -> list[str]:
        """
        Return the distinct names of the indexed metrics of many runs, sorted.

        Reads only names through the ``(run_id, name, step)`` index, ``_IN_CHUNK``
        run ids per statement. Points a rebuild skipped are read first, as in
        ``metric_points``.

        Parameters
        ----------
        run_ids : iterable of str
            Runs to read.

        Returns
        -------
        list of str
            Distinct metric names over all the runs; empty when none has points.

        Examples
        --------
        >>> idx.metric_names_for(["r1", "r2"])  # doctest: +SKIP
        ['loss', 'lr', 'val/acc']
        """
        ids = list(dict.fromkeys(run_ids))
        self._fill_pending_points(ids)
        names: set[str] = set()
        with Session(self.engine) as session:
            for start in range(0, len(ids), _IN_CHUNK):
                chunk = ids[start : start + _IN_CHUNK]
                stmt = select(MetricPointRow.name).where(MetricPointRow.run_id.in_(chunk))
                names.update(session.scalars(stmt.distinct()))
        return sorted(names)

    def _fill_pending_points(self, run_ids: list[str]) -> None:
        """Index the metric files of the runs whose points a rebuild skipped."""
        if self.store is None or not run_ids:
            return
        pending: list[tuple[str, str, str]] = []
        with Session(self.engine) as session:
            for start in range(0, len(run_ids), 500):
                stmt = (
                    select(RunRow.run_id, RunRow.project, RunRow.status)
                    .join(PointsPendingRow, PointsPendingRow.run_id == RunRow.run_id)
                    .where(RunRow.run_id.in_(run_ids[start : start + 500]))
                )
                pending.extend((r, p, st) for r, p, st in session.execute(stmt))
        for run_id, project, status in pending:
            while True:
                points = points_to_index(self.store, project, run_id, status)
                if self._replace_metric_points(run_id, points, pending_status=status):
                    break
                # Read outside the write transaction. A changed status can
                # require exact terminal history instead of bounded live points.
                with Session(self.engine) as session:
                    current = session.execute(
                        select(RunRow.project, RunRow.status)
                        .join(PointsPendingRow, PointsPendingRow.run_id == RunRow.run_id)
                        .where(RunRow.run_id == run_id)
                    ).one_or_none()
                if current is None:
                    break
                project, status = current

    # host cursors -------------------------------------------------------------
    def cursor_hosts(self, environment_id: str) -> list[str]:
        """
        Return the hosts known to have served an environment, including sequence zero.

        Parameters
        ----------
        environment_id : str
            Environment identity reported by a host.

        Returns
        -------
        list of str
            Host names in sorted order. Removed aliases remain in the cursor table;
            the caller checks which names are still configured.

        Examples
        --------
        >>> idx.cursor_hosts("env-a")  # doctest: +SKIP
        ['gpu1']
        """
        stmt = (
            select(HostCursorRow.host)
            .where(HostCursorRow.environment_id == environment_id)
            .order_by(HostCursorRow.host)
        )
        with Session(self.engine) as session:
            return list(session.scalars(stmt))

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
        values = {"host": host, "environment_id": environment_id, "last_sequence": last_sequence}
        keys = ["host", "environment_id"]
        with _index_write_session(self.engine) as session:
            upsert(session, HostCursorRow, values, keys, keep_max="last_sequence")

    def reset_cursor(self, host: str, environment_id: str) -> None:
        """
        Reset the mirror sequence of one host environment, keeping its identity reservation.

        ``set_cursor`` only moves forward, so a host whose event log restarted
        (its last sequence is below the cursor) needs this to be replayed from
        the start. The row remains at zero, so another configured host cannot
        take the identity after a hub restart. Like ``set_cursor`` it does not
        change ``generation``.

        Parameters
        ----------
        host : str
            Host name from ``environments.yaml``.
        environment_id : str
            The host's stable environment id.

        Examples
        --------
        >>> import tempfile
        >>> idx = Index(Path(tempfile.mkdtemp()) / "i.db")
        >>> idx.set_cursor("gpu1", "env-a", 42)
        >>> idx.reset_cursor("gpu1", "env-a")
        >>> idx.get_cursor("gpu1", "env-a")
        0
        """
        values = {"host": host, "environment_id": environment_id, "last_sequence": 0}
        with _index_write_session(self.engine) as session:
            upsert(session, HostCursorRow, values, ["host", "environment_id"])


def points_to_index(
    store: RunStore, project: str, run_id: str, status: RunStatus | str
) -> list[MetricPoint]:
    """
    Read the metric history to index for a run in state ``status``.

    A run that ended (``INDEXED_POINT_STATUSES``) is read in full, so its
    indexed history is exactly ``downsample`` of every point. Any other run may
    still be writing its file, without limit (a remote host can fill it), so it
    is read bounded (``RunStore.read_metric_points_bounded``); its end indexes
    it again in full.

    Parameters
    ----------
    store : RunStore
        File store to read from.
    project : str
        Project name.
    run_id : str
        Run id.
    status : RunStatus or str
        The run's state.

    Returns
    -------
    list of MetricPoint
        The points to pass to ``Index.replace_metric_points``.

    Examples
    --------
    >>> points_to_index(store, "toy", "r1", RunStatus.RUNNING)  # doctest: +SKIP
    [MetricPoint(name='loss', step=0, value=2.3, t=None)]
    """
    if RunStatus(status) in INDEXED_POINT_STATUSES:
        return store.read_metric_points(project, run_id)
    return store.read_metric_points_bounded(project, run_id)


def index_run_points(index: Index, store: RunStore, record: RunRecord) -> None:
    """
    Re-index a run's metric points from its file after a status change, never failing.

    Every end path calls this (or ``index_run``): a run that ends is indexed
    from its whole file (``points_to_index``), replacing the bounded copy held
    while it ran. A read or index error is logged, so nothing the run logged
    keeps it from ending.

    Parameters
    ----------
    index : Index
        Target index.
    store : RunStore
        File store to read from.
    record : RunRecord
        The run as just written.

    Examples
    --------
    >>> index_run_points(ctx.index, ctx.store, killed)  # doctest: +SKIP
    """
    try:
        points = points_to_index(store, record.project, record.run_id, record.status)
        index.replace_metric_points(record.run_id, points)
    except Exception as exc:  # noqa: BLE001 - the run has ended either way
        log.warning("run %s: could not index its metric points: %s", record.run_id, exc)


def index_run(index: Index, store: RunStore, record: RunRecord) -> None:
    """
    Index a run, its scores, and its metric points from files (``points_to_index``).

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
    points = points_to_index(store, record.project, record.run_id, record.status)
    index.replace_metric_points(record.run_id, points)


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


def _add_run(batch: _Rows, store: RunStore, record: RunRecord) -> None:
    """Queue one run, its tags, its scores, and a pending mark for its metric points."""
    batch.add(RunRow.__tablename__, _run_values(record))
    for tag in sorted(set(record.tags)):
        batch.add(RunTagRow.__tablename__, {"run_id": record.run_id, "tag": tag})
    for score in store.read_scores(record.project, record.run_id):
        batch.add(ScoreRow.__tablename__, _score_values(record.run_id, score))
    batch.add(PointsPendingRow.__tablename__, {"run_id": record.run_id})


def _add_project(batch: _Rows, entry: ProjectEntry) -> None:
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
            "higher_is_better": m.higher_is_better is not False,
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


def _generation_or_zero(index: Index) -> int:
    """The index generation; 0 for a file with no meta table."""
    try:
        return index.generation()
    except OperationalError as exc:
        if "no such table" in str(exc.orig):
            return 0
        raise


def _rebuild_locked(index: Index, store: RunStore) -> int:
    # read before the scan: every write after it is caught up in _swap_in
    since = _generation_or_zero(index)
    # Some filesystems cannot flock: concurrent rebuilds must never share staging.
    with TemporaryDirectory(prefix=index.path.name + ".tmp-", dir=index.path.parent) as staging:
        fresh = Path(staging) / index.path.name
        count = _build_fresh(fresh, store)
        _swap_in(index, store, fresh, since)
    index.engine.dispose()  # pooled connections re-read the new schema
    return count


def rebuild_index(index: Index, store: RunStore) -> int:
    """
    Rebuild the whole index from files, atomically.

    The runs are written into a unique ``<index>.tmp-*`` directory first, without a lock on the
    live index; then one write transaction re-reads the runs written to the
    live index meanwhile, copies the hub's mirror cursors, and replaces every
    table. Readers (other processes too) see the old index until that
    transaction commits, then the new one, never a part of it; a write that
    lands during the rebuild is kept. Metric points are not read here:
    ``Index.metric_points`` reads a run's file on first use. One rebuild runs
    at a time (a lock file next to the index) where advisory locks are available;
    otherwise separate staging directories keep concurrent rebuilds isolated,
    and carried change markers retain writes across overlapping swaps.

    PostgreSQL uses transaction-local temporary tables and database advisory
    locks. Writers proceed during staging; final catch-up and publication
    serialize with writes. Failure rolls back publication and temporary
    tables, while disconnect releases transaction locks.

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
    if index.dialect == "postgresql":
        return _rebuild_postgres(index, store)
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
    if index.dialect == "postgresql":
        raise IndexSchemaError("Postgres schemas require hx db upgrade")
    with _rebuild_lock(index):
        if index.schema_version() == str(SCHEMA_VERSION):
            return None
        return _rebuild_locked(index, store)


def repair_index_gaps(index: Index, store: RunStore) -> list[str]:
    """
    Index projects and run folders that have no index row yet, and drop gone runs.

    A run row whose ``run.yaml`` is gone (its folder was deleted or moved) is
    deleted, so it leaves listings, counts, and leaderboards without a
    ``hx reindex``. The index ids are read before the store is listed: a run
    created during the scan is never taken for a gone one.

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
    indexed = index.run_ids()  # before the listing: a run made during it is not "gone"
    on_disk = store.list_run_ids()
    for run_id in sorted(indexed - set(on_disk)):
        index.delete_run(run_id)
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


def repair_stale_scores(index: Index, store: RunStore) -> list[str]:
    """
    Re-index the scores of runs whose score add was cut short.

    ``Context.add_score`` marks the run (``Index.mark_scores_stale``), appends
    to ``scores.jsonl``, then re-indexes the run's scores, which clears the
    mark. A crash in between leaves the mark; this reads the file again under
    the run lock, so it never races an add that is still running.

    Parameters
    ----------
    index : Index
        Index to repair.
    store : RunStore
        File store, the source of truth.

    Returns
    -------
    list of str
        Run ids whose scores were re-indexed, sorted.
    """
    repaired: list[str] = []
    for run_id in index.stale_score_runs():
        indexed = index.get_run(run_id)
        try:
            project = indexed.project if indexed else store.find_project_of(run_id)
        except RunNotFoundError:
            index.replace_scores(run_id, [])  # the folder is gone: nothing to index
            continue
        run_dir = store.layout.run_dir(project, run_id)
        if not run_dir.is_dir():
            index.replace_scores(run_id, [])
            continue
        with run_lock(run_dir):
            index.replace_scores(run_id, store.read_scores(project, run_id))
        repaired.append(run_id)
    return repaired


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


def _append_pending(path: Path, run_id: str) -> None:
    """Add one id to the journal under its lock; follow the journal if a repair moved it."""
    while True:
        with path.open("a") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)  # released when the file closes
            try:
                current = os.stat(path).st_ino == os.fstat(fh.fileno()).st_ino
            except FileNotFoundError:
                current = False
            if current:
                fh.write(f"{run_id}\n")
                return
        # a repair claimed the file between our open and our lock: write to the new one


def _claim_ids(path: Path) -> set[str]:
    """Read a claim file under its lock (a journal write still going in finishes first)."""
    try:
        with path.open("r") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            text = fh.read()
    except FileNotFoundError:
        return set()
    return {s for s in (x.strip() for x in text.splitlines()) if s}


def repair_pending(index: Index, store: RunStore) -> list[str]:
    """
    Re-index the runs whose index write failed after their files were written.

    A write that reaches the run folder and then fails at the index (Postgres
    went away mid-request) leaves the row stale, not missing, so
    ``repair_index_gaps`` never sees it. ``Index`` notes those run ids in
    ``index.pending``; this re-reads each one from its files (drops it when its
    folder is gone).

    The journal is first moved to a claim file of its own,
    ``index-pending.txt.<8 hex>.claim`` (a write failing meanwhile starts a new
    journal). Then every claim file is read, those a crashed process left
    included, and each is removed only after all of its runs are indexed. A
    crash or an error at any step leaves a file the next call reads; two
    repairs at once index some runs twice, which is harmless. Each run is
    re-read and indexed under its run lock, the one ``Context.update_run``
    holds, so a repair never writes back a value older than an update that
    finished meanwhile.

    Parameters
    ----------
    index : Index
    store : RunStore
        File store, the source of truth.

    Returns
    -------
    list of str
        Run ids re-indexed or dropped, sorted.
    """
    if index.pending is None:
        return []
    journal = index.pending
    with contextlib.suppress(FileNotFoundError):
        os.replace(journal, journal.with_name(f"{journal.name}.{secrets.token_hex(4)}.claim"))
    claims = sorted(journal.parent.glob(f"{journal.name}.*.claim"))
    wanted: set[str] = set()
    for claim in claims:
        wanted |= _claim_ids(claim)
    ids = sorted(wanted)
    on_disk = store.list_run_ids() if ids else {}
    for run_id in ids:
        if run_id in on_disk:
            project = on_disk[run_id]
            with run_lock(store.layout.run_dir(project, run_id)):
                index_run(index, store, store.read_record(project, run_id))
        else:
            index.delete_run(run_id)
    for claim in claims:
        claim.unlink(missing_ok=True)
    return ids


def open_index(layout: Layout, settings: ServerSettings, store: RunStore | None = None) -> Index:
    """
    Open the index ``config.yaml`` asks for.

    Parameters
    ----------
    layout : Layout
    settings : ServerSettings
        ``index_url`` (None = SQLite ``<home>/index.db``) and ``index_password_env``.
    store : RunStore, optional
        Existing store; defaults to a store over ``layout``.

    Returns
    -------
    Index

    Raises
    ------
    IndexUnavailableError
        Postgres does not answer.
    IndexSchemaError
        Postgres is not at ``HEAD_REVISION``.
    """
    source = store if store is not None else RunStore(layout)
    if settings.index_url is None:
        index = Index(layout.index_db, store=source)
    else:
        password = resolve_secret(layout, settings.index_password_env)
        index = Index(settings.index_url, store=source, password=password)
    index.pending = layout.home / INDEX_PENDING_FILE
    return index
