import os
import time
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.errors import RunNotFoundError
from hypothex.core.records import RunStatus
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
