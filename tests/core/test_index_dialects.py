import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import hypothex.core.index as index_module
from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.index import (
    HostCursorRow,
    Index,
    IndexUnavailableError,
    MetaRow,
    RunRow,
    open_index,
    repair_pending,
    upsert,
    upsert_statement,
)
from hypothex.core.layout import Layout
from hypothex.core.queries import archive_run
from hypothex.core.settings import ServerSettings, Settings, save_settings
from hypothex.core.store import run_lock
from tests.factories import make_record

DEAD_PG = "postgresql+psycopg://hx@127.0.0.1:1/hypothex"


def test_sqlite_index_is_unchanged(tmp_path: Path) -> None:
    index = Index(tmp_path / "index.db")
    assert index.dialect == "sqlite" and index.rebuilt_schema is True
    assert Index(tmp_path / "index.db").rebuilt_schema is True  # no rebuild finished yet
    index.set_meta("schema_version", str(index_module.SCHEMA_VERSION))
    assert Index(tmp_path / "index.db").rebuilt_schema is False


def test_upsert_inserts_then_updates(tmp_path: Path) -> None:
    index = Index(tmp_path / "index.db")
    with Session(index.engine) as session, session.begin():
        upsert(session, MetaRow, {"key": "k", "value": "1"}, ["key"])
        upsert(session, MetaRow, {"key": "k", "value": "2"}, ["key"])
    assert index.get_meta("k") == "2"
    index.set_cursor("gpu1", "env-a", 9)
    index.set_cursor("gpu1", "env-a", 4)  # never moves back
    assert index.get_cursor("gpu1", "env-a") == 9


def test_postgres_statements_compile(tmp_path: Path) -> None:
    stmt = upsert_statement(
        "postgresql",
        HostCursorRow,
        {"host": "gpu1", "environment_id": "e", "last_sequence": 3},
        ["host", "environment_id"],
        keep_max="last_sequence",
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (host, environment_id) DO UPDATE SET last_sequence = greatest(" in sql
    lite = str(
        upsert_statement("sqlite", MetaRow, {"key": "k", "value": "v"}, ["key"]).compile(
            dialect=sqlite.dialect()
        )
    )
    assert 'ON CONFLICT ("key") DO UPDATE SET value = excluded.value' in lite


def test_json_text_reads_record_fields(ctx: Context) -> None:
    ctx.create_run(make_record("r1", environment_id=ctx.descriptor.environment_id))
    ended = ctx.index.json_text(RunRow.record_json, "run_id")
    with Session(ctx.index.engine) as session:
        assert session.scalars(select(ended)).all() == ["r1"]


def test_open_index_defaults_to_sqlite(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    assert open_index(layout, ServerSettings()).dialect == "sqlite"


def test_unreachable_postgres_names_the_url_without_the_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYPOTHEX_INDEX_PASSWORD", "pw-SECRETXYZ")
    with pytest.raises(IndexUnavailableError) as info:
        open_index(Layout(tmp_path), ServerSettings(index_url=DEAD_PG))
    message = str(info.value)
    assert "127.0.0.1:1" in message and "hx@" in message and "SECRETXYZ" not in message


def test_postgres_without_psycopg_says_what_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "psycopg", None)  # as on an install without the extra
    with pytest.raises(ConfigError, match=r"needs psycopg: uv tool install 'hypothex\[server\]'"):
        Index(DEAD_PG)


def test_context_open_uses_config_yaml(home: Path) -> None:
    save_settings(Layout(home), Settings(server=ServerSettings(index_url=DEAD_PG)))
    with pytest.raises(IndexUnavailableError):
        Context.open(home)


def test_index_failure_mid_request_is_503(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")

    def down(*args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))

    with TestClient(app, base_url="http://127.0.0.1:7777") as client:
        monkeypatch.setattr(app.state.ctx.index, "list_runs", down)
        resp = client.get("/api/v1/runs")
    assert resp.status_code == 503 and resp.json()["type"] == "IndexUnavailableError"


def test_a_write_that_fails_at_the_index_is_repaired_from_files(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = Context.open(home)
    ctx.create_run(make_record("r1", environment_id=ctx.descriptor.environment_id))
    real = index_module.upsert

    def down(*args: object, **kwargs: object) -> None:
        raise OperationalError("INSERT", {}, Exception("server closed the connection"))

    monkeypatch.setattr(index_module, "upsert", down)
    with pytest.raises(OperationalError):
        archive_run(ctx, "r1")  # run.yaml is archived; the indexed row is not
    monkeypatch.setattr(index_module, "upsert", real)
    stale = ctx.index.get_run("r1")
    assert ctx.find_record("r1").archived and stale is not None and not stale.archived
    reopened = Context.open(home)  # the next open, or the server's repair loop
    fresh = reopened.index.get_run("r1")
    assert fresh is not None and fresh.archived
    assert repair_pending(reopened.index, reopened.store) == []


def test_a_claim_left_by_a_crashed_repair_is_picked_up(home: Path) -> None:
    ctx = Context.open(home)
    ctx.create_run(make_record("r1", environment_id=ctx.descriptor.environment_id))
    ctx.store.write_record(ctx.find_record("r1").model_copy(update={"archived": True}))
    assert ctx.index.pending is not None
    left = ctx.index.pending.with_name(f"{ctx.index.pending.name}.deadbeef.claim")
    left.write_text("r1\n")  # moved out of the journal, then that process died
    assert repair_pending(ctx.index, ctx.store) == ["r1"]
    fresh = ctx.index.get_run("r1")
    assert fresh is not None and fresh.archived and not left.exists()


def test_repair_reads_and_indexes_under_the_run_lock(home: Path) -> None:
    ctx = Context.open(home)
    ctx.create_run(make_record("r1", environment_id=ctx.descriptor.environment_id))
    assert ctx.index.pending is not None
    ctx.index.pending.write_text("r1\n")  # an earlier write that failed at the index
    done: list[list[str]] = []
    worker = threading.Thread(target=lambda: done.append(repair_pending(ctx.index, ctx.store)))
    record = ctx.find_record("r1")
    with run_lock(ctx.run_dir(record)):  # Context.update_run archiving it, mid-write
        worker.start()
        worker.join(1)
        assert worker.is_alive() and done == []
        archived = record.model_copy(update={"archived": True})
        ctx.store.write_record(archived)
        ctx.index.upsert_run(archived)
    worker.join(30)
    fresh = ctx.index.get_run("r1")
    assert done == [["r1"]] and fresh is not None and fresh.archived  # never the old value


def test_postgres_cache_identity_never_uses_a_path(ctx: Context) -> None:
    from hypothex.core.config import ProjectConfig
    from hypothex.core.leaderboard import (
        Leaderboard,
        build_leaderboard,
        cached_leaderboard,
        cached_names,
        clear_caches,
    )

    class PgIndex:
        dialect = "postgresql"

        def __init__(self) -> None:
            self.cache_identity = object()
            self.version = 0

        @property
        def path(self) -> Path:
            raise AssertionError("PostgreSQL caches must not inspect a SQLite path")

        def generation(self) -> int:
            return self.version

    clear_caches()
    original = ctx.index
    fake = PgIndex()
    ctx.index = fake  # type: ignore[assignment]
    config = ProjectConfig.model_validate(
        {
            "project": "toy",
            "datasets": {"d": {"version": "v1", "path": "x"}},
            "metrics": {"acc": {"version": "v1", "fn": "m:acc"}},
            "tasks": {"t": {"dataset": "d", "metrics": ["acc"], "primary": "acc"}},
        }
    )
    builds = []
    names = []

    def board() -> Leaderboard:
        builds.append(1)
        return build_leaderboard("toy", "t", config, [], {})

    def run_names() -> dict[str, str]:
        names.append(1)
        return {"r1": str(len(names))}

    try:
        for expected in (1, 2, 3):
            for _ in range(2):
                cached_leaderboard(ctx, "toy", "t", config, board)
                cached_names(ctx, "toy", "t", run_names)
            assert len(builds) == len(names) == expected
            if expected == 1:
                fake.version += 1
            else:
                fake.cache_identity = object()  # reopen at the same generation
    finally:
        ctx.index = original
        clear_caches()


def test_sqlite_cache_identity_changes_with_database_replacement(ctx: Context) -> None:
    from hypothex.core.leaderboard import _index_key

    before = _index_key(ctx)
    replacement = ctx.index.path.with_name("replacement.db")
    other = Index(replacement)
    other.set_meta("generation", str(ctx.index.generation()))
    other.engine.dispose()
    ctx.index.engine.dispose()
    replacement.replace(ctx.index.path)
    assert _index_key(ctx) != before


@pytest.mark.parametrize(
    "method", ["upsert_run", "add_score", "replace_scores", "replace_metric_points", "delete_run"]
)
def test_every_run_write_journals_connection_failure(
    ctx: Context, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    from sqlalchemy.exc import InterfaceError

    from hypothex.core.ids import utcnow
    from hypothex.core.records import ScoreRecord

    record = make_record("r1")
    ctx.create_run(record)
    score = ScoreRecord(metric="acc", version="v1", key="value", value=0.5, created_at=utcnow())

    def fail(session: Session) -> None:
        raise InterfaceError("synthetic", {}, RuntimeError("synthetic unavailable"))

    monkeypatch.setattr(index_module, "_index_write_guard", fail)
    args = {
        "upsert_run": (record,),
        "add_score": ("r1", score),
        "replace_scores": ("r1", [score]),
        "replace_metric_points": ("r1", []),
        "delete_run": ("r1",),
    }
    with pytest.raises(InterfaceError):
        getattr(ctx.index, method)(*args[method])
    assert ctx.index.pending is not None
    assert ctx.index.pending.read_text() == "r1\n"


def test_failed_repair_keeps_claim_until_retry(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.create_run(make_record("r1"))
    assert ctx.index.pending is not None
    ctx.index.pending.write_text("r1\n")
    original = index_module.index_run

    def fail(*args: object) -> None:
        raise OperationalError("synthetic", {}, RuntimeError("offline"))

    monkeypatch.setattr(index_module, "index_run", fail)
    with pytest.raises(OperationalError):
        repair_pending(ctx.index, ctx.store)
    claims = list(ctx.layout.home.glob("index-pending.txt.*.claim"))
    assert len(claims) == 1 and claims[0].read_text() == "r1\n"
    monkeypatch.setattr(index_module, "index_run", original)
    assert repair_pending(ctx.index, ctx.store) == ["r1"]
    assert not claims[0].exists()


def test_journal_writer_follows_a_claimed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "index-pending.txt"
    claim = tmp_path / "index-pending.txt.deadbeef.claim"
    original = index_module.fcntl.flock
    moved = False

    def move_on_lock(fd: int, operation: int) -> None:
        nonlocal moved
        if not moved:
            path.replace(claim)
            moved = True
        original(fd, operation)

    monkeypatch.setattr(index_module.fcntl, "flock", move_on_lock)
    index_module._append_pending(path, "r1")
    assert claim.read_text() == "" and path.read_text() == "r1\n"


@pytest.mark.parametrize(
    "target",
    [
        "postgresql://hx:SECRET@127.0.0.1/db",
        "postgresql://hx@127.0.0.1/db?password=SECRET",
        "mysql://hx:SECRET@127.0.0.1/db",
    ],
)
def test_direct_index_rejects_password_or_wrong_backend_without_leaking(target: str) -> None:
    with pytest.raises(ConfigError) as info:
        Index(target)
    assert "SECRET" not in str(info.value)
