import os
import time
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, RemoteProjectError, RunNotFoundError
from hypothex.core.ids import utcnow
from hypothex.core.records import RunStatus, ScoreRecord
from tests.factories import make_record


def test_open_creates_layout_and_is_idempotent(home: Path) -> None:
    ctx = Context.open(home)
    assert ctx.layout.store.is_dir() and ctx.layout.index_db.is_file()
    assert Context.open(home).descriptor.environment_id == ctx.descriptor.environment_id


def test_create_and_update_run_write_file_event_and_index(ctx: Context) -> None:
    record = ctx.create_run(make_record("r1"))
    updated = ctx.update_run(
        "r1", "run.started", lambda r: r.model_copy(update={"status": RunStatus.RUNNING})
    )
    assert updated.status == RunStatus.RUNNING
    assert ctx.store.read_record("toy", "r1").status == RunStatus.RUNNING
    got = ctx.index.get_run("r1")
    assert got is not None and got.status == RunStatus.RUNNING
    assert [e.type for e in ctx.events.since(0)] == ["run.created", "run.started"]
    assert ctx.find_record("r1").run_id == record.run_id


def test_update_run_keeps_concurrent_curation(ctx: Context) -> None:
    ctx.create_run(make_record("r1"))
    ctx.update_run("r1", "run.tagged", lambda r: r.model_copy(update={"tags": ["keep"]}))
    ctx.update_run(
        "r1", "run.finished", lambda r: r.model_copy(update={"status": RunStatus.FINISHED})
    )
    assert ctx.find_record("r1").tags == ["keep"]


def test_open_repairs_index_gaps(home: Path) -> None:
    ctx = Context.open(home)
    ctx.store.create_run(make_record("orphan"))  # file written, index not
    assert Context.open(home).index.get_run("orphan") is not None


def test_open_rebuilds_deleted_index(home: Path) -> None:
    ctx = Context.open(home)
    ctx.create_run(make_record("r1"))
    ctx.layout.index_db.unlink()
    assert Context.open(home).index.get_run("r1") is not None


def test_find_record_unknown(ctx: Context) -> None:
    with pytest.raises(RunNotFoundError):
        ctx.find_record("nope")


def test_open_skips_the_store_scan_when_nothing_changed(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core.store import RunStore

    ctx = Context.open(home)
    ctx.create_run(make_record("r1"))
    past = time.time() - 60  # settled: nothing changed in the last seconds
    project = ctx.layout.project_dir("toy")
    for folder in (ctx.layout.store, project, project / "runs"):
        os.utime(folder, (past, past))
    Context.open(home)  # the store changed since the last scan: this open scans it
    scans: list[int] = []
    real = RunStore.list_run_ids

    def counting(self: RunStore) -> dict[str, str]:
        scans.append(1)
        return real(self)

    monkeypatch.setattr(RunStore, "list_run_ids", counting)
    for _ in range(3):
        Context.open(home)
    assert scans == []
    ctx.store.create_run(make_record("orphan"))  # file written, index not
    assert Context.open(home).index.get_run("orphan") is not None
    assert scans == [1]


def _score(value: float) -> ScoreRecord:
    return ScoreRecord(metric="acc", version="1", key="value", value=value, created_at=utcnow())


def test_add_score_writes_file_event_and_index(ctx: Context) -> None:
    rec = ctx.create_run(make_record("r1", status=RunStatus.FINISHED))
    ctx.add_score(rec, _score(0.5))
    ctx.add_score(rec, _score(0.7))
    assert [s.value for s in ctx.index.scores_for(["r1"])["r1"]] == [0.5, 0.7]
    assert [s.value for s in ctx.store.read_scores("toy", "r1")] == [0.5, 0.7]
    assert ctx.index.stale_score_runs() == []


def test_open_indexes_a_score_whose_add_was_cut_short(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = Context.open(home)
    rec = ctx.create_run(make_record("r1", status=RunStatus.FINISHED))
    ctx.add_score(rec, _score(0.5))

    def killed(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt  # the process dies after the file append

    monkeypatch.setattr(ctx.events, "append", killed)
    with pytest.raises(KeyboardInterrupt):
        ctx.add_score(rec, _score(0.9))
    assert [s.value for s in ctx.index.scores_for(["r1"])["r1"]] == [0.5]
    again = Context.open(home)  # the next start (INT-F8)
    assert [s.value for s in again.index.scores_for(["r1"])["r1"]] == [0.5, 0.9]
    assert again.index.stale_score_runs() == []


def test_a_stale_mark_of_a_deleted_run_is_dropped(home: Path) -> None:
    ctx = Context.open(home)
    ctx.index.mark_scores_stale("gone")
    Context.open(home)
    assert ctx.index.stale_score_runs() == []
    assert not ctx.layout.run_dir("toy", "gone").exists()


def test_local_repo_is_the_registered_checkout(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    assert ctx.local_repo("toy") == toy_repo.resolve()


def test_local_repo_refuses_a_project_copied_from_a_host(ctx: Context, toy_repo: Path) -> None:
    # the host reported this path; it also exists here, but it is never used here
    entry = ctx.register_project(toy_repo)
    ctx.store.save_project(entry.model_copy(update={"remote_host": "gpu1"}))
    with pytest.raises(RemoteProjectError, match="copied from host gpu1"):
        ctx.local_repo("toy")
    assert issubclass(RemoteProjectError, ConfigError)
