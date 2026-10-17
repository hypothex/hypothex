import os
import secrets
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

import hypothex.core.index as index_module
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.core.fsutil import append_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.index import Index, IndexSchemaError, rebuild_index
from hypothex.core.layout import Layout
from hypothex.core.records import MetricPoint, RunRecord, RunStatus, ScoreRecord
from hypothex.core.settings import ServerSettings, Settings, save_settings
from hypothex.core.store import RunStore
from tests.docker.conftest import free_port, run_cmd, wait_until
from tests.factories import make_record, write_toy_project
from tests.fakes.network import pg_child_environment

pytestmark = pytest.mark.docker
IMAGE = "postgres:16-alpine"


def connect(port: int, password: str, dbname: str = "hypothex") -> object:
    import psycopg

    return psycopg.connect(
        host="127.0.0.1", port=port, user="hx", password=password, dbname=dbname, autocommit=True
    )


@pytest.fixture(scope="module")
def postgres() -> Iterator[tuple[int, str]]:
    """A throwaway Postgres on a random loopback port with a random password."""
    port = free_port()
    password = secrets.token_hex(12)
    name = f"hx-test-pg-{secrets.token_hex(4)}"
    run_cmd(
        [
            "docker", "run", "-d", "--rm", "--name", name, "-e", f"POSTGRES_PASSWORD={password}",
            "-e", "POSTGRES_USER=hx", "-e", "POSTGRES_DB=hypothex", "-p", f"127.0.0.1:{port}:5432",
            IMAGE,
        ],
        env=pg_child_environment(dict(os.environ)),
    )  # fmt: skip
    try:
        wait_until(
            lambda: connect(port, password).close() or True,  # type: ignore[attr-defined]
            timeout=120,
            what="postgres to accept connections",
        )
        yield port, password
    finally:
        run_cmd(
            ["docker", "rm", "-f", name],
            check=False,
            env=pg_child_environment(dict(os.environ)),
        )


@pytest.fixture
def pg_home(tmp_path: Path, postgres: tuple[int, str], monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home whose config.yaml points at a fresh database of the container."""
    port, password = postgres
    dbname = f"hx_{secrets.token_hex(4)}"
    with connect(port, password) as conn:  # type: ignore[attr-defined]
        conn.execute(f"CREATE DATABASE {dbname}")
    home = tmp_path / "hxhome"
    home.mkdir()
    monkeypatch.setenv("HYPOTHEX_HOME", str(home))
    monkeypatch.setenv("HYPOTHEX_INDEX_PASSWORD", password)
    url = f"postgresql+psycopg://hx@127.0.0.1:{port}/{dbname}"
    save_settings(Layout(home), Settings(server=ServerSettings(index_url=url)))
    return home


def snapshot(index: Index) -> dict[str, object]:
    runs = index.list_runs(include_archived=True, limit=None)
    ids = sorted(r.run_id for r in runs)
    scores = index.scores_for(ids)
    return {
        "projects": [p.project for p in index.list_projects()],
        "runs": sorted(r.model_dump_json() for r in runs),
        "scores": {k: [s.model_dump_json() for s in v] for k, v in sorted(scores.items())},
        "owners": sorted(r.run_id for r in index.list_runs(owner="alice", limit=None)),
    }


def test_upgrade_then_live_index_equals_rebuilt_and_sqlite(pg_home: Path, tmp_path: Path) -> None:
    with pytest.raises(IndexSchemaError, match="run hx db upgrade"):
        Context.open(pg_home)
    result = CliRunner().invoke(app, ["db", "upgrade", "--json"], catch_exceptions=False)
    assert result.exit_code == 0 and '"revision": "0001_phase3"' in result.stdout
    ctx = Context.open(pg_home)
    assert ctx.index.dialect == "postgresql"
    ctx.register_project(write_toy_project(tmp_path / "toy"))
    for i in range(12):
        record = make_record(
            f"r{i:02d}",
            status=RunStatus.FINISHED,
            owner="alice" if i % 3 == 0 else "sv",
            environment_id=ctx.descriptor.environment_id,
        )
        ctx.create_run(record)
        value = i / 12
        score = ScoreRecord(
            metric="accuracy", version="v1", key="value", value=value, created_at=utcnow()
        )
        ctx.add_score(record, score)
    live = snapshot(ctx.index)
    rebuild_index(ctx.index, ctx.store)
    assert snapshot(ctx.index) == live
    lite = Index(tmp_path / "sqlite.db", store=ctx.store)
    rebuild_index(lite, ctx.store)
    assert snapshot(lite) == live


def test_concurrent_upserts_never_fail(pg_home: Path) -> None:
    CliRunner().invoke(app, ["db", "upgrade"], catch_exceptions=False)
    ctx = Context.open(pg_home)
    record = make_record("same", environment_id=ctx.descriptor.environment_id)
    errors: list[BaseException] = []

    def work(n: int) -> None:
        try:
            for step in range(20):
                ctx.index.upsert_run(record.model_copy(update={"hypothesis": f"{n}-{step}"}))
                ctx.index.set_cursor("gpu1", "env-a", n * 100 + step)
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert ctx.index.get_cursor("gpu1", "env-a") == 7 * 100 + 19
    assert [r.run_id for r in ctx.index.list_runs(include_archived=True)] == ["same"]


class PausedStore(RunStore):
    """Pause once after the first staged row; no lock is held by the hook."""

    def __init__(self, layout: Layout, hook: Callable[[], None]) -> None:
        super().__init__(layout)
        self.hook = hook
        self.points_read = 0

    def iter_records(self, project: str | None = None) -> Iterator[RunRecord]:
        for i, record in enumerate(super().iter_records(project)):
            yield record
            if i == 0:
                self.hook()

    def read_metric_points(self, project: str, run_id: str) -> list[MetricPoint]:
        self.points_read += 1
        return super().read_metric_points(project, run_id)


def ready_context(pg_home: Path) -> Context:
    result = CliRunner().invoke(app, ["db", "upgrade"], catch_exceptions=False)
    assert result.exit_code == 0
    ctx = Context.open(pg_home)
    for rid in ("r0", "r1", "r2"):
        ctx.create_run(make_record(rid, status=RunStatus.FINISHED, owner="alice"))
        append_jsonl(
            ctx.layout.run_dir("toy", rid) / "metrics.jsonl",
            {"name": "loss", "step": 0, "value": 1.0},
        )
    return ctx


def test_int64_steps_cursors_and_generation_round_trip(pg_home: Path) -> None:
    ctx = ready_context(pg_home)
    step = 2**63 - 1
    ctx.index.replace_metric_points("r0", [MetricPoint(name="loss", step=step, value=0.5)])
    assert ctx.index.metric_points("r0")[0].step == step
    append_jsonl(
        ctx.layout.run_dir("toy", "r0") / "metrics.jsonl",
        {"name": "loss", "step": step, "value": 0.5},
    )
    ctx.index.set_cursor("gpu1", "env-a", step)
    assert ctx.index.get_cursor("gpu1", "env-a") == step
    ctx.index.set_meta(index_module.GENERATION_KEY, str(2**31 - 1))
    ctx.index.upsert_run(ctx.find_record("r0"))  # exercises existing-key conflict RHS
    assert ctx.index.generation() == 2**31
    with Session(ctx.index.engine) as session:
        assert (
            session.scalar(
                select(index_module.RunChangeRow.generation).where(
                    index_module.RunChangeRow.run_id == "r0"
                )
            )
            == 2**31
        )
    rebuild_index(ctx.index, ctx.store)
    assert ctx.index.get_cursor("gpu1", "env-a") == step
    assert max(p.step for p in ctx.index.metric_points("r0")) == step  # lazy hydration too

    # The index's generated row ids also retain SQLite's int64 capacity.
    with Session(ctx.index.engine) as session, session.begin():
        for table in ("scores", "metric_points"):
            session.execute(
                index_module.text(
                    "SELECT setval(pg_get_serial_sequence(:table, 'id')::regclass, :value, true)"
                ),
                {"table": table, "value": 2**31},
            )
    score = ScoreRecord(metric="acc", version="v1", key="value", value=0.7, created_at=utcnow())
    ctx.add_score(ctx.find_record("r0"), score)
    ctx.index.replace_metric_points("r0", [MetricPoint(name="loss", step=step, value=0.5)])
    with Session(ctx.index.engine) as session:
        assert (
            session.scalar(
                select(index_module.ScoreRow.id).where(index_module.ScoreRow.run_id == "r0")
            )
            > 2**31
        )
        assert (
            session.scalar(
                select(index_module.MetricPointRow.id).where(
                    index_module.MetricPointRow.run_id == "r0"
                )
            )
            > 2**31
        )


def test_rebuild_keeps_readers_writes_markers_and_deferred_points(pg_home: Path) -> None:
    ctx = ready_context(pg_home)
    before = snapshot(ctx.index)
    generation = ctx.index.generation()
    ctx.index.set_cursor("gpu1", "env-a", 9)
    score = ScoreRecord(metric="acc", version="v1", key="value", value=0.8, created_at=utcnow())
    writer_errors: list[BaseException] = []

    def changed_during_scan() -> None:
        # A separate session sees the complete old index, not staging rows.
        assert snapshot(ctx.index) == before

        def write() -> None:
            try:
                ctx.update_run(
                    "r0",
                    "run.tagged",
                    lambda r: r.model_copy(
                        update={"tags": ["late"], "parent": "r2", "owner": "sv"}
                    ),
                )
                ctx.add_score(ctx.find_record("r0"), score)
                ctx.create_run(make_record("late", owner="alice", parent="r0"))
                ctx.index.set_cursor("gpu1", "env-a", 12)
                ctx.index.mark_scores_stale("r2")
                ctx.store.append_score("toy", "r2", score)  # simulate a cut-short add
            except BaseException as exc:  # noqa: BLE001 - asserted in test thread
                writer_errors.append(exc)

        worker = threading.Thread(target=write, daemon=True)
        worker.start()
        worker.join(10)
        assert not worker.is_alive(), "staging must not exclude ordinary writers"
        assert writer_errors == []

    staged = PausedStore(ctx.layout, changed_during_scan)
    ctx.index.store = staged
    assert rebuild_index(ctx.index, staged) == 4
    assert staged.points_read == 0  # neither dialect reads metric files while rebuilding
    assert ctx.index.get_cursor("gpu1", "env-a") == 12
    assert ctx.index.generation() > generation
    assert ctx.index.stale_score_runs() == ["r2"]
    with Session(ctx.index.engine) as session:
        assert session.execute(
            select(index_module.RunRow.owner, index_module.RunRow.parent).where(
                index_module.RunRow.run_id == "r0"
            )
        ).one() == ("sv", "r2")
        assert (
            session.scalar(
                select(index_module.RunChangeRow.generation).where(
                    index_module.RunChangeRow.run_id == "r0"
                )
            )
            is not None
        )
    current = ctx.index.get_run("r0")
    assert current is not None and current.tags == ["late"]
    assert ctx.index.scores_for(["r0"])["r0"] == [score]
    assert [(p.name, p.step) for p in ctx.index.metric_points("r0")] == [("loss", 0)]
    assert staged.points_read == 1
    ctx.index.metric_points("r0")
    assert staged.points_read == 1
    reopened = Context.open(pg_home)
    assert reopened.index.store is reopened.store
    assert reopened.index.stale_score_runs() == []
    assert reopened.index.scores_for(["r2"])["r2"] == [score]  # repaired exactly once


def test_failure_after_live_replacement_rolls_back_everything(
    pg_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = ready_context(pg_home)
    before = snapshot(ctx.index)
    generation = ctx.index.generation()
    real = index_module._touch

    def fail_publish(session: Session, *run_ids: str) -> None:
        if not run_ids:
            # Rebuild invokes _touch after DELETE/INSERT, before commit. Other
            # sessions still see the old index even at this final boundary.
            assert snapshot(ctx.index) == before
            raise RuntimeError("publication interrupted")
        real(session, *run_ids)

    monkeypatch.setattr(index_module, "_touch", fail_publish)
    with pytest.raises(RuntimeError, match="publication interrupted"):
        rebuild_index(ctx.index, ctx.store)
    assert snapshot(ctx.index) == before and ctx.index.generation() == generation
    monkeypatch.setattr(index_module, "_touch", real)
    assert rebuild_index(ctx.index, ctx.store) == 3  # locks/staging released after failure


def test_a_writer_waits_for_final_swap_then_commits_after_it(pg_home: Path) -> None:
    ctx = ready_context(pg_home)
    entered = threading.Event()
    done = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        entered.set()
        try:
            ctx.update_run("r0", "run.tagged", lambda r: r.model_copy(update={"tags": ["after"]}))
        except BaseException as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)
        finally:
            done.set()

    with Session(ctx.index.engine) as session, session.begin():
        session.execute(
            index_module.text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": index_module.PG_WRITE_LOCK},
        )
        worker = threading.Thread(target=writer, daemon=True)
        worker.start()
        assert entered.wait(5)
        wait_until(
            lambda: ctx.store.read_record("toy", "r0").tags == ["after"],
            timeout=5,
            what="writer to reach its index update",
        )
        assert not done.is_set()
        # Ordinary reads do not acquire the write guard.
        assert ctx.index.count_runs(include_archived=True) == 3
    worker.join(10)
    assert done.is_set() and not worker.is_alive() and errors == []
    current = ctx.index.get_run("r0")
    assert current is not None and current.tags == ["after"]


def test_concurrent_rebuilds_keep_writes_and_use_separate_staging(pg_home: Path) -> None:
    ctx = ready_context(pg_home)
    first_paused, release, second_scanned = threading.Event(), threading.Event(), threading.Event()
    errors: list[BaseException] = []

    def pause() -> None:
        first_paused.set()
        assert release.wait(10)

    def rebuild(store: RunStore) -> None:
        try:
            rebuild_index(ctx.index, store)
        except BaseException as exc:  # noqa: BLE001 - asserted after both joins
            errors.append(exc)

    first = threading.Thread(target=rebuild, args=(PausedStore(ctx.layout, pause),), daemon=True)
    second = threading.Thread(
        target=rebuild, args=(PausedStore(ctx.layout, second_scanned.set),), daemon=True
    )
    first.start()
    try:
        assert first_paused.wait(5)
        second.start()
        assert not second_scanned.wait(0.1)  # waits on rebuild lock, not the write guard
        ctx.update_run("r0", "run.tagged", lambda r: r.model_copy(update={"tags": ["kept"]}))
    finally:
        release.set()
        first.join(10)
        if second.ident is not None:
            second.join(10)
    assert not first.is_alive() and not second.is_alive() and errors == []
    assert second_scanned.is_set()
    current = ctx.index.get_run("r0")
    assert current is not None and current.tags == ["kept"]


def test_cursor_reset_keeps_empty_identity_across_rebuild(pg_home: Path) -> None:
    ctx = ready_context(pg_home)
    generation = ctx.index.generation()
    ctx.index.set_cursor("reserved-only", "env-empty", 0)
    ctx.index.set_cursor("gpu1", "env-a", 9)
    ctx.index.reset_cursor("gpu1", "env-a")
    assert ctx.index.get_cursor("gpu1", "env-a") == 0
    assert ctx.index.cursor_hosts("env-a") == ["gpu1"]
    assert ctx.index.generation() == generation
    rebuild_index(ctx.index, ctx.store)
    reopened = Context.open(pg_home)
    assert reopened.index.cursor_hosts("env-empty") == ["reserved-only"]
    assert reopened.index.cursor_hosts("env-a") == ["gpu1"]
    assert reopened.index.get_cursor("gpu1", "env-a") == 0


def test_pending_hydration_cannot_resurrect_deleted_run(
    pg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = ready_context(pg_home)
    rebuild_index(ctx.index, ctx.store)
    captured, resume = threading.Event(), threading.Event()
    errors: list[BaseException] = []
    result: list[list[MetricPoint]] = []
    real_read = index_module.points_to_index

    def paused_read(
        store: RunStore, project: str, run_id: str, status: RunStatus | str
    ) -> list[MetricPoint]:
        points = real_read(store, project, run_id, status)
        captured.set()
        assert resume.wait(10)
        return points

    def hydrate() -> None:
        try:
            result.append(ctx.index.metric_points("r0"))
        except BaseException as exc:  # noqa: BLE001 - asserted after join
            errors.append(exc)

    monkeypatch.setattr(index_module, "points_to_index", paused_read)
    worker = threading.Thread(target=hydrate, daemon=True)
    worker.start()
    try:
        assert captured.wait(5)
        ctx.index.delete_run("r0")
        published_generation = ctx.index.generation()
    finally:
        resume.set()
        worker.join(10)
    assert not worker.is_alive() and errors == []
    assert result == [[]] and ctx.index.get_run("r0") is None
    assert ctx.index.generation() == published_generation
    with Session(ctx.index.engine) as session:
        assert (
            session.scalar(
                select(index_module.PointsPendingRow.run_id).where(
                    index_module.PointsPendingRow.run_id == "r0"
                )
            )
            is None
        )


def test_pending_hydration_waits_for_swap_and_retries_terminal_status(
    pg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = ready_context(pg_home)
    ctx.update_run(
        "r0", "run.running", lambda r: r.model_copy(update={"status": RunStatus.RUNNING})
    )
    rebuild_index(ctx.index, ctx.store)
    captured, resume_read = threading.Event(), threading.Event()
    swap_holds_guard, release_swap = threading.Event(), threading.Event()
    hydration_at_guard, hydrated = threading.Event(), threading.Event()
    errors: list[BaseException] = []
    claims: list[tuple[bool, int, int]] = []
    claim_before: list[int] = []
    result: list[list[MetricPoint]] = []
    real_read, real_touch = index_module.points_to_index, index_module._touch
    real_guard, real_replace = index_module._index_write_guard, ctx.index._replace_metric_points
    expected = [
        MetricPoint(name="loss", step=0, value=1.0),
        MetricPoint(name="loss", step=1, value=0.25),
    ]

    def paused_read(
        store: RunStore, project: str, run_id: str, status: RunStatus | str
    ) -> list[MetricPoint]:
        points = real_read(store, project, run_id, status)
        if threading.current_thread().name == "hydration" and not captured.is_set():
            captured.set()
            assert resume_read.wait(10)
        return points

    def guarded(session: Session) -> None:
        if threading.current_thread().name == "hydration":
            hydration_at_guard.set()
        real_guard(session)
        if threading.current_thread().name == "hydration" and not claim_before:
            claim_before.append(ctx.index.generation())

    def publish(session: Session, *run_ids: str) -> None:
        if threading.current_thread().name == "publication" and not run_ids:
            swap_holds_guard.set()  # DELETE/INSERT already ran under PG_WRITE_LOCK
            assert release_swap.wait(10)
        real_touch(session, *run_ids)

    def replace(run_id: str, points: list[MetricPoint], *, pending_status: str | None) -> bool:
        if threading.current_thread().name == "hydration":
            claim_before.clear()
            accepted = real_replace(run_id, points, pending_status=pending_status)
            # captured by the actual transaction guard, after publication commits
            assert len(claim_before) == 1
            claims.append((accepted, claim_before[0], ctx.index.generation()))
            return accepted
        return real_replace(run_id, points, pending_status=pending_status)

    def hydrate() -> None:
        try:
            result.append(ctx.index.metric_points("r0"))
        except BaseException as exc:  # noqa: BLE001 - asserted after join
            errors.append(exc)
        finally:
            hydrated.set()

    def rebuild() -> None:
        try:
            rebuild_index(ctx.index, ctx.store)
        except BaseException as exc:  # noqa: BLE001 - asserted after join
            errors.append(exc)

    monkeypatch.setattr(index_module, "points_to_index", paused_read)
    monkeypatch.setattr(index_module, "_index_write_guard", guarded)
    monkeypatch.setattr(index_module, "_touch", publish)
    monkeypatch.setattr(ctx.index, "_replace_metric_points", replace)
    worker = threading.Thread(target=hydrate, name="hydration", daemon=True)
    publisher = threading.Thread(target=rebuild, name="publication", daemon=True)
    worker.start()
    try:
        assert captured.wait(5)
        append_jsonl(ctx.layout.run_dir("toy", "r0") / "metrics.jsonl", expected[-1].model_dump())
        ctx.update_run(
            "r0", "run.finished", lambda r: r.model_copy(update={"status": RunStatus.FINISHED})
        )
        ctx.index.replace_metric_points("r0", expected)
        publisher.start()
        assert swap_holds_guard.wait(5)
        resume_read.set()
        assert hydration_at_guard.wait(5)
        assert not hydrated.is_set()
    finally:
        release_swap.set()
        resume_read.set()
        worker.join(10)
        if publisher.ident is not None:
            publisher.join(10)
    assert not worker.is_alive() and not publisher.is_alive() and errors == []
    assert result == [expected]
    assert len(claims) == 2 and [accepted for accepted, _, _ in claims] == [False, True]
    assert claims[0][1] == claims[0][2]  # failed status CAS did not bump generation
    assert claims[1][2] == claims[1][1] + 1


def test_failed_deferred_hydration_is_journalled_and_repaired(
    pg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = ready_context(pg_home)
    rebuild_index(ctx.index, ctx.store)
    real_guard = index_module._index_write_guard

    def unavailable(session: Session) -> None:
        raise OperationalError("SELECT pg_advisory_xact_lock", {}, RuntimeError("offline"))

    monkeypatch.setattr(index_module, "_index_write_guard", unavailable)
    with pytest.raises(OperationalError):
        ctx.index.metric_points("r0")
    assert ctx.index.pending is not None
    assert ctx.index.pending.read_text().splitlines() == ["r0"]
    monkeypatch.setattr(index_module, "_index_write_guard", real_guard)
    assert index_module.repair_pending(ctx.index, ctx.store) == ["r0"]
    assert ctx.index.metric_points("r0") == [MetricPoint(name="loss", step=0, value=1.0)]
    assert not ctx.index.pending.exists()
    assert list(ctx.layout.home.glob("index-pending.txt.*.claim")) == []


def test_metadata_matches_real_postgres(pg_home: Path) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import BigInteger, inspect

    ctx = ready_context(pg_home)
    with ctx.index.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, index_module.Base.metadata) == []
        inspector = inspect(connection)
        assert {i["name"] for i in inspector.get_indexes("runs")} >= {
            "ix_runs_name",
            "ix_runs_parent",
            "ix_runs_owner",
        }
        for table, column in (
            ("scores", "id"),
            ("metric_points", "id"),
            ("metric_points", "step"),
            ("host_cursors", "last_sequence"),
            ("run_changes", "generation"),
        ):
            reflected = next(c for c in inspector.get_columns(table) if c["name"] == column)
            assert isinstance(reflected["type"], BigInteger)
            assert reflected["nullable"] is False
            if column == "id":
                assert reflected["autoincrement"] is True


def test_ui_v5_queries_cache_filters_and_scoped_http_survive_rebuild(
    pg_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace
    from datetime import timedelta

    import yaml
    from fastapi.testclient import TestClient
    from sqlalchemy import event

    from hypothex.api.app import create_app
    from hypothex.auth.store import LOCAL_OWNER, AuthStore
    from hypothex.core.overview import build_overview
    from hypothex.core.panels import query_panel
    from hypothex.core.queries import get_leaderboard, rename_run
    from hypothex.core.settings import load_settings
    from hypothex.core.taskruns import task_runs
    from hypothex.core.views import PanelData, PanelSpec

    result = CliRunner().invoke(app, ["db", "upgrade"], catch_exceptions=False)
    assert result.exit_code == 0
    current = CliRunner().invoke(app, ["db", "current", "--json"], catch_exceptions=False)
    assert current.exit_code == 0 and index_module.HEAD_REVISION in current.stdout
    ctx = Context.open(pg_home)
    repo = write_toy_project(tmp_path / "ui-toy", use_git=False)
    config_path = repo / "hypothex.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["metrics"] = {
        "accuracy": {"version": "v1", "fn": "toymetrics:accuracy", "higher_is_better": True},
        "loss": {"version": "v1", "fn": "toymetrics:accuracy", "higher_is_better": False},
        "inferred": {"version": "v1", "fn": "toymetrics:accuracy"},
    }
    config["tasks"] = {
        "toy-acc": {
            "dataset": "toyset",
            "metrics": ["accuracy", "loss", "inferred"],
            "primary": "accuracy/value",
            "score_keys": "{dataset}.{model}.{metric}",
            "kind": "system_bench",
        }
    }
    config_path.write_text(yaml.safe_dump(config))
    ctx.register_project(repo)
    base = utcnow() - timedelta(minutes=10)
    records = [
        make_record(
            rid,
            task="toy-acc",
            status=RunStatus.FINISHED if i < 2 else RunStatus.RUNNING,
            created_at=base + timedelta(minutes=i),
            ended_at=base + timedelta(minutes=i + 1) if i < 2 else None,
            name="wide %_ beam" if i == 0 else None,
            owner="alice" if i != 1 else None,
            parent="named" if i else None,
            config_hash=f"sha256:{i:08x}",
            environment_id=ctx.descriptor.environment_id,
        )
        for i, rid in enumerate(("named", "literal%_id", "live"))
    ]
    expected_scores = {}
    for i, record in enumerate(records):
        ctx.create_run(record)
        points = [
            MetricPoint(
                name="train/loss" if i < 2 else "live/loss",
                step=step,
                value=1 / (step + 1),
                t=1760000000.0 + step,
            )
            for step in (0, 1)
        ]
        for point in points:
            append_jsonl(ctx.run_dir(record) / "metrics.jsonl", point.model_dump())
        if i < 2:
            ctx.index.replace_metric_points(record.run_id, points)
        scores = [
            ScoreRecord(
                metric=metric,
                version="v1",
                key=key,
                value=value,
                created_at=base,
                source_hash="sha256:predictions",
                per_example_hash="sha256:bound",
                evaluation_examples=4,
                evaluation_ids_hash="sha256:population",
            )
            for metric, key, value in (
                ("accuracy", "value", 0.7 + i / 10),
                ("accuracy", "set1.m1.top1", 0.6 + i / 10),
                ("accuracy", "set2.m2.top1", 0.5 + i / 10),
                ("loss", "set1.m1.error", 0.3 - i / 10),
                ("inferred", "set1.m1.p95", 30 + i),
            )
        ]
        for score in scores:
            ctx.add_score(record, score)
        expected_scores[record.run_id] = scores

    statements = []

    def capture_sql(*args: object) -> None:
        statements.append(str(args[2]))

    event.listen(ctx.index.engine, "before_cursor_execute", capture_sql)
    compare = PanelSpec(
        type="compare",
        render="table",
        data=PanelData(
            datasets=["set1", "set2"],
            metrics=["top1"],
            model=None,
        ),
    )
    curves = PanelSpec(type="curves", data=PanelData(metrics=["train/loss"], group_by="run"))

    def check_queries(context: Context, name: str) -> dict[str, object]:
        index = context.index
        assert index.get_run("named").name == name
        assert index.get_run("literal%_id").parent == "named"
        assert index.scores_for(expected_scores) == expected_scores
        assert [
            r.run_id for r in index.list_runs(search="%_", owner="alice", status="finished")
        ] == ["named"]
        assert index.count_runs(search="%_", owner="alice", status="finished") == 1
        assert [r.run_id for r in index.list_runs(search="%_id")] == ["literal%_id"]
        page = index.list_runs(limit=1)
        assert [
            r.run_id for r in index.list_runs(limit=1, before=(page[0].created_at, page[0].run_id))
        ] == ["literal%_id"]
        entry = index.get_project("toy")
        assert entry is not None
        assert entry.config.metrics["inferred"].higher_is_better is None
        assert entry.config.metrics["accuracy"].higher_is_better is True
        assert entry.config.metrics["loss"].higher_is_better is False
        assert '"config_format":2' in entry.model_dump_json()
        board = get_leaderboard(
            context, "toy-acc", "toy", examples=False, primary="inferred/set1.m1.p95"
        )
        assert board.higher_is_better is False and board.rows
        runs = task_runs(context, "toy-acc", "toy")
        assert {r.run_id: r.name for r in runs.runs}["named"] == name
        assert runs.metric_names == ["live/loss", "train/loss"]
        overview = build_overview(context)
        assert overview.names["named"] == name
        assert {r.run_id: r.owner for r in overview.recent}["named"] == "alice"
        table = query_panel(context, "toy", "toy-acc", compare)
        assert table.rows and table.meta["render"] == "table"
        assert {row["dataset"] for row in table.rows} == {"set1", "set2"}
        assert {row["model"] for row in table.rows} == {"m1", "m2"}
        bars = query_panel(context, "toy", "toy-acc", compare.model_copy(update={"render": "bars"}))
        assert bars.rows == table.rows and bars.meta["render"] == "bars"
        curve = query_panel(context, "toy", "toy-acc", curves)
        assert curve.rows and {r["t"] for r in curve.rows} == {1760000000.0, 1760000001.0}
        return {
            "snapshot": snapshot(index),
            "board": board.model_dump(),
            "names": overview.names,
            "run_names": {r.run_id: r.name for r in runs.runs},
            "compare": table.model_dump(),
            "curves": curve.model_dump(),
        }

    check_queries(ctx, "wide %_ beam")
    # Prime both caches, rename, then require recomputation from each public query.
    rename_run(ctx, "named", "renamed %_ beam")
    live = check_queries(ctx, "renamed %_ beam")
    rebuild_index(ctx.index, ctx.store)
    assert check_queries(ctx, "renamed %_ beam") == live
    reopened = Context.open(pg_home)
    assert check_queries(reopened, "renamed %_ beam") == live
    lite = Index(tmp_path / "ui-sqlite.db", store=ctx.store)
    rebuild_index(lite, ctx.store)
    assert check_queries(replace(ctx, index=lite), "renamed %_ beam") == live
    assert not any("json_extract(" in sql or "sqlite" in sql.lower() for sql in statements)

    settings = load_settings(ctx.layout)
    settings.server.auth = "on"
    save_settings(ctx.layout, settings)
    auth = AuthStore(ctx.layout)
    auth.ensure_owner("alice")
    offer, secret = auth.create_offer(issuer=LOCAL_OWNER, user="reader", scope="read")
    _, token = auth.redeem(offer.id, secret, client="cli", device="synthetic-pg-test")
    api = create_app(pg_home, hub=False, background_repair=False)
    with TestClient(api, base_url="http://127.0.0.1:7777") as client:
        assert client.get("/api/v1/overview").status_code == 401
        client.headers["Authorization"] = f"Bearer {token}"
        for path in (
            "/api/v1/overview",
            "/api/v1/tasks/toy/toy-acc/runs",
            "/api/v1/tasks/toy/toy-acc/leaderboard?primary=inferred%2Fset1.m1.p95",
        ):
            response = client.get(path)
            assert response.status_code == 200, response.text
        response = client.post(
            "/api/v1/tasks/toy/toy-acc/views/query", json={"panel": compare.model_dump()}
        )
        assert response.status_code == 200, response.text
        assert "set1" in response.text
    for index in (ctx.index, reopened.index, lite, api.state.ctx.index):
        index.engine.dispose()
