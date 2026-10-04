"""Atomic index rebuild (PERF-F4, INT-F4) and the index generation."""

from __future__ import annotations

import errno
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from hypothex.core.config import ProjectConfig
from hypothex.core.context import Context
from hypothex.core.fsutil import append_jsonl
from hypothex.core.gpus import held_gpus
from hypothex.core.ids import utcnow
from hypothex.core.index import (
    SCHEMA_VERSION,
    Index,
    index_generation,
    rebuild_index,
    rebuild_index_if_stale,
)
from hypothex.core.layout import Layout
from hypothex.core.records import RunRecord, RunStatus, ScoreRecord
from hypothex.core.scheduler import assign_gpus
from hypothex.core.store import RunStore
from tests.factories import make_record


class HookedStore(RunStore):
    """A store that calls ``hook`` once, in the middle of ``iter_records``."""

    def __init__(self, layout: Layout, hook: Callable[[], None], after: int = 1) -> None:
        super().__init__(layout)
        self.hook = hook
        self.after = after
        self.points_read = 0

    def iter_records(self, project: str | None = None) -> Iterator[RunRecord]:
        for i, record in enumerate(super().iter_records(project)):
            if i == self.after:
                self.hook()
            yield record

    def read_metric_points(self, project: str, run_id: str) -> list:
        self.points_read += 1
        return super().read_metric_points(project, run_id)


def _score(value: float = 0.5) -> ScoreRecord:
    return ScoreRecord(metric="acc", version="v1", key="value", value=value, created_at=utcnow())


def _store(tmp_path: Path, runs: int = 5) -> RunStore:
    layout = Layout(tmp_path / "home")
    layout.ensure()
    store = RunStore(layout)
    store.register_project(ProjectConfig(project="toy"), tmp_path)
    for i in range(runs):
        rid = f"r{i}"
        store.create_run(make_record(rid, status=RunStatus.FINISHED))
        store.append_score("toy", rid, _score())
        append_jsonl(
            layout.run_dir("toy", rid) / "metrics.jsonl", {"name": "loss", "step": 0, "value": 1.0}
        )
    return store


def _count(path: Path) -> int:
    with sqlite3.connect(path) as conn:  # another connection, as another process would
        return conn.execute("SELECT count(*) FROM runs").fetchone()[0]


def test_readers_see_the_whole_old_index_during_a_rebuild(tmp_path: Path) -> None:
    store = _store(tmp_path, runs=5)
    index = Index(tmp_path / "index.db", store=store)
    rebuild_index(index, store)
    seen: list[int] = []
    hooked = HookedStore(store.layout, lambda: seen.append(_count(index.path)), after=3)
    assert rebuild_index(index, hooked) == 5
    assert seen == [5]  # not a partly refilled index
    assert _count(index.path) == 5
    assert not index.path.with_name("index.db.tmp").exists()


def test_a_failed_rebuild_leaves_the_live_index_alone(tmp_path: Path) -> None:
    store = _store(tmp_path, runs=3)
    index = Index(tmp_path / "index.db", store=store)
    rebuild_index(index, store)
    before = index.generation()

    def boom() -> None:
        raise RuntimeError("disk on fire")

    with pytest.raises(RuntimeError):
        rebuild_index(index, HookedStore(store.layout, boom))
    assert _count(index.path) == 3 and index.generation() == before
    assert not index.path.with_name("index.db.tmp").exists()


def test_rebuild_does_not_read_metric_files_but_points_stay_available(tmp_path: Path) -> None:
    store = _store(tmp_path, runs=3)
    hooked = HookedStore(store.layout, lambda: None)
    index = Index(tmp_path / "index.db", store=hooked)
    rebuild_index(index, hooked)
    assert hooked.points_read == 0
    assert [(p.name, p.step) for p in index.metric_points("r1")] == [("loss", 0)]
    assert hooked.points_read == 1
    index.metric_points("r1")
    assert hooked.points_read == 1  # indexed now: the file is read once


def test_metric_points_for_reads_skipped_points_of_many_runs(tmp_path: Path) -> None:
    store = _store(tmp_path, runs=3)
    index = Index(tmp_path / "index.db", store=store)
    rebuild_index(index, store)
    got = index.metric_points_for(["r0", "r2"], names=["loss"])
    assert {rid: [(p.name, p.step) for p in pts] for rid, pts in got.items()} == {
        "r0": [("loss", 0)],
        "r2": [("loss", 0)],
    }
    assert index.metric_points_for(["r1"], names=["acc"]) == {}


def test_writes_during_a_rebuild_are_kept(tmp_path: Path) -> None:
    store = _store(tmp_path, runs=4)
    index = Index(tmp_path / "index.db", store=store)
    rebuild_index(index, store)
    other = Index(index.path, store=store)  # another process writing meanwhile

    def write_meanwhile() -> None:
        new = make_record("r9", status=RunStatus.RUNNING)
        store.create_run(new)
        other.upsert_run(new)
        late = store.read_record("toy", "r3").model_copy(update={"tags": ["late"]})
        store.write_record(late)  # r3 is read later by the scan, r0 earlier
        other.upsert_run(late)
        early = store.read_record("toy", "r0").model_copy(update={"starred": True})
        store.write_record(early)
        other.upsert_run(early)
        store.append_score("toy", "r0", _score(0.9))
        other.replace_scores("r0", store.read_scores("toy", "r0"))
        shutil.rmtree(store.layout.run_dir("toy", "r1"))
        other.delete_run("r1")

    assert rebuild_index(index, HookedStore(store.layout, write_meanwhile, after=2)) >= 3
    runs = {r.run_id: r for r in index.list_runs()}
    assert set(runs) == {"r0", "r2", "r3", "r9"}
    assert runs["r0"].starred and runs["r3"].tags == ["late"]
    assert [s.value for s in index.scores_for(["r0"])["r0"]] == [0.5, 0.9]


def _gpu_home(home: Path) -> Context:
    ctx = Context.open(home)
    env = ctx.descriptor.environment_id
    ctx.store.register_project(ProjectConfig(project="toy"), home)
    for rid in ("a1", "a2", "a3"):
        ctx.create_run(make_record(rid, environment_id=env))
    ctx.update_run(
        "a1",
        "run.started",
        lambda r: assign_gpus([0])(r).model_copy(update={"status": RunStatus.RUNNING}),
    )
    return ctx


@pytest.mark.parametrize("after", [0, 1, 2])
def test_a_held_gpu_never_shows_free_during_a_rebuild(home: Path, after: int) -> None:
    ctx = _gpu_home(home)
    reader = Context.open(home)  # e.g. the scheduler of a running hx serve
    seen: list[dict[int, str]] = []
    hooked = HookedStore(ctx.store.layout, lambda: seen.append(held_gpus(reader)), after=after)
    rebuild_index(ctx.index, hooked)
    assert seen == [{0: "a1"}]  # INT-F4


def test_a_gpu_assigned_during_a_rebuild_stays_assigned(home: Path) -> None:
    ctx = _gpu_home(home)
    reader = Context.open(home)

    def scheduler_tick() -> None:  # a2 was scanned already
        reader.update_run("a2", "run.started", assign_gpus([1]))

    rebuild_index(ctx.index, HookedStore(ctx.store.layout, scheduler_tick, after=2))
    assert held_gpus(reader) == {0: "a1", 1: "a2"}


def test_rebuild_keeps_mirror_cursors(tmp_path: Path) -> None:
    store = _store(tmp_path, runs=1)
    index = Index(tmp_path / "index.db", store=store)
    index.set_cursor("gpu1", "env-a", 42)
    rebuild_index(index, store)
    assert index.get_cursor("gpu1", "env-a") == 42


def test_rebuild_keeps_stale_score_marks(tmp_path: Path) -> None:
    store = _store(tmp_path, runs=1)
    index = Index(tmp_path / "index.db", store=store)
    index.mark_scores_stale("r0")  # an add in flight, or cut short
    rebuild_index(index, store)
    assert index.stale_score_runs() == ["r0"]


def test_one_rebuild_when_many_processes_open_a_stale_index(tmp_path: Path) -> None:
    store = _store(tmp_path, runs=3)
    path = tmp_path / "index.db"
    Index(path)  # a new file: stale until rebuilt
    results: list[int | None] = []
    threads = [
        threading.Thread(target=lambda: results.append(rebuild_index_if_stale(Index(path), store)))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results, key=str) == [3, None, None, None]
    assert Index(path).schema_version() == str(SCHEMA_VERSION)


def test_rebuild_runs_where_flock_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_flock(fd: int, operation: int) -> None:
        raise OSError(errno.ENOSYS, "Function not implemented")

    store = _store(tmp_path, runs=2)
    index = Index(tmp_path / "index.db", store=store)
    monkeypatch.setattr("hypothex.core.index.fcntl.flock", no_flock)
    assert rebuild_index(index, store) == 2


def test_rebuild_replaces_a_leftover_temp_file(tmp_path: Path) -> None:
    store = _store(tmp_path, runs=2)
    index = Index(tmp_path / "index.db", store=store)
    index.path.with_name("index.db.tmp").write_bytes(b"half a database from a crash")
    assert rebuild_index(index, store) == 2
    assert len(index.list_runs()) == 2


def test_rebuild_fills_the_parent_column(tmp_path: Path) -> None:
    store = _store(tmp_path, runs=1)
    store.create_run(make_record("kid", parent="r0", status=RunStatus.FINISHED))
    index = Index(tmp_path / "index.db", store=store)
    rebuild_index(index, store)
    assert index.child_run_ids("r0") == ["kid"]


# generation --------------------------------------------------------------------------


def test_generation_grows_on_every_index_write(tmp_path: Path) -> None:
    store = _store(tmp_path, runs=1)
    index = Index(tmp_path / "index.db", store=store)
    other = Index(index.path)  # another process reads the same number
    readings = [index.generation()]

    def step() -> None:
        now = other.generation()
        assert now > readings[-1]
        readings.append(now)

    index.upsert_run(make_record("x1"))
    step()
    index.add_score("x1", _score())
    step()
    index.replace_scores("x1", [_score()])
    step()
    index.replace_metric_points("x1", [])
    step()
    index.upsert_project(store.list_projects()[0])
    step()
    index.delete_run("x1")
    step()
    rebuild_index(index, store)
    step()
    index.clear()
    step()
    index.set_meta("note", "x")
    index.set_cursor("h", "e", 1)
    assert other.generation() == readings[-1]  # bookkeeping is not indexed data


def test_index_generation_of_a_context(home: Path) -> None:
    ctx = Context.open(home)
    before = index_generation(ctx)
    ctx.create_run(make_record("g1", environment_id=ctx.descriptor.environment_id))
    assert index_generation(ctx) > before
