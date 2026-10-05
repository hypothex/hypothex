import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from hypothex.core.config import ProjectConfig
from hypothex.core.fsutil import append_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.index import (
    SCHEMA_VERSION,
    Index,
    downsample,
    index_run,
    rebuild_index,
    rebuild_index_if_stale,
    repair_index_gaps,
)
from hypothex.core.layout import Layout
from hypothex.core.records import MetricPoint, RunRecord, RunStatus, ScoreRecord
from hypothex.core.store import RunStore
from hypothex.core.thin import MAX_METRIC_NAMES
from tests.factories import make_record


def test_upsert_and_filters(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    idx.upsert_run(make_record("r1", task="a", tags=["x"]))
    idx.upsert_run(make_record("r2", task="b", archived=True))
    idx.upsert_run(make_record("r3", status=RunStatus.FINISHED))
    assert {r.run_id for r in idx.list_runs()} == {"r1", "r3"}
    assert len(idx.list_runs(include_archived=True)) == 3
    assert [r.run_id for r in idx.list_runs(task="a")] == ["r1"]
    assert [r.run_id for r in idx.list_runs(tag="x")] == ["r1"]
    assert [r.run_id for r in idx.list_runs(status=RunStatus.FINISHED)] == ["r3"]
    got = idx.get_run("r2")
    assert got is not None and got.archived
    assert idx.get_run("zz") is None


def test_child_run_ids_use_the_parent_index(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    idx.upsert_run(make_record("p1"))
    idx.upsert_run(make_record("c1", parent="p1"))
    idx.upsert_run(make_record("c2", parent="p1", archived=True, project="other"))
    idx.upsert_run(make_record("c3", parent="p2"))
    assert sorted(idx.child_run_ids("p1")) == ["c1", "c2"]
    assert idx.child_run_ids("c1") == []
    with idx.engine.connect() as conn:
        plan = conn.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT run_id FROM runs WHERE parent = 'p1'"
        ).all()
    assert any("ix_runs_parent" in str(row) for row in plan)


def test_keyset_pages_match_the_full_list(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    same = utcnow()
    for i in range(7):  # four share a created_at: the run id breaks the tie
        when = same if i < 4 else same - timedelta(seconds=i)
        idx.upsert_run(make_record(f"r{i}", created_at=when, tags=["t"] if i % 2 else []))
    full = idx.list_runs(limit=None)
    pages: list[str] = []
    before = None
    while True:
        page = idx.list_runs(limit=3, before=before)
        if not page:
            break
        pages += [r.run_id for r in page]
        before = (page[-1].created_at, page[-1].run_id)
    assert pages == [r.run_id for r in full]
    iso = (full[2].created_at.isoformat(), full[2].run_id)
    assert idx.list_runs(before=iso) == full[3:]
    assert [r.run_id for r in idx.list_runs(tag="t", before=iso)] == [
        r.run_id for r in full[3:] if r.tags == ["t"]
    ]


def test_count_runs_matches_list_runs_without_parsing_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    idx = Index(tmp_path / "i.db")
    idx.upsert_run(make_record("r1", task="a", tags=["x"]))
    idx.upsert_run(make_record("r2", task="b", archived=True, tags=["x"]))
    idx.upsert_run(make_record("r3", status=RunStatus.FINISHED, environment_id="e2"))
    cases: list[dict] = [
        {},
        {"include_archived": True},
        {"task": "a"},
        {"tag": "x"},
        {"tag": "x", "include_archived": True},
        {"status": RunStatus.FINISHED},
        {"environment_id": "e2"},
        {"project": "nope"},
    ]
    want = [len(idx.list_runs(limit=None, **c)) for c in cases]

    def no_parse(*args: object, **kwargs: object) -> None:
        raise AssertionError("count_runs parsed a record")

    monkeypatch.setattr(RunRecord, "model_validate_json", no_parse)
    assert [idx.count_runs(**c) for c in cases] == want == [2, 3, 1, 1, 2, 1, 1, 0]


def test_upsert_run_replaces_tags(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    idx.upsert_run(make_record("r1", tags=["old"]))
    idx.upsert_run(make_record("r1", tags=["new"]))
    assert idx.list_runs(tag="old") == []
    assert [r.run_id for r in idx.list_runs(tag="new")] == ["r1"]


def test_scores_roundtrip(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    s1 = ScoreRecord(metric="acc", version="v1", key="value", value=0.5, created_at=utcnow())
    s2 = ScoreRecord(metric="acc", version="v2", key="value", value=0.6, created_at=utcnow())
    idx.add_score("r1", s1)
    idx.add_score("r1", s2)
    assert idx.scores_for(["r1", "r2"]) == {"r1": [s1, s2]}
    idx.replace_scores("r1", [s2])
    assert idx.scores_for(["r1"]) == {"r1": [s2]}


def test_metric_points_for_filters_names_with_the_composite_index(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    names = ("loss", "acc", "lr")
    for rid in ("r1", "r2", "r3"):
        points = [MetricPoint(name=n, step=s, value=float(s)) for n in names for s in (2, 1)]
        idx.replace_metric_points(rid, points)
    got = idx.metric_points_for(["r1", "r3", "zz"], names=["loss", "acc"])
    assert set(got) == {"r1", "r3"}
    want = [("acc", 1), ("acc", 2), ("loss", 1), ("loss", 2)]
    assert [(p.name, p.step) for p in got["r1"]] == want
    assert idx.metric_points("r2") == idx.metric_points_for(["r2"])["r2"]
    with idx.engine.connect() as conn:
        plan = conn.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT step, value FROM metric_points "
            "WHERE run_id IN ('r1', 'r3') AND name IN ('loss') ORDER BY run_id, name, step"
        ).all()
    text = " ".join(str(row) for row in plan)
    assert "ix_metric_points_run_name_step" in text and "TEMP B-TREE" not in text


def test_metric_names_reads_distinct_names_only(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    points = [MetricPoint(name=n, step=s, value=1.0) for n in ("lr", "acc") for s in range(3)]
    idx.replace_metric_points("r1", points)
    assert idx.metric_names("r1") == ["acc", "lr"]
    assert idx.metric_names("zz") == []


def test_downsample_keeps_last_point_and_limit() -> None:
    points = [MetricPoint(name="loss", step=i, value=float(i)) for i in range(2500)]
    points.append(MetricPoint(name="acc", step=0, value=1.0))
    out = downsample(points, limit=1000)
    loss = [p for p in out if p.name == "loss"]
    assert len(loss) <= 1000
    assert loss[-1].step == 2499
    assert [p.name for p in out].count("acc") == 1


def _store_with_long_runs(tmp_path: Path) -> RunStore:
    """A store with a running and a finished run, each 3,000 loss points peaking at step 1234."""
    layout = Layout(tmp_path / "home")
    layout.ensure()
    store = RunStore(layout)
    store.register_project(ProjectConfig(project="toy"), tmp_path)
    for rid, status in (("live", RunStatus.RUNNING), ("done", RunStatus.FINISHED)):
        store.create_run(make_record(rid, status=status))
        path = layout.run_dir("toy", rid) / "metrics.jsonl"
        for s in range(3000):
            append_jsonl(path, {"name": "loss", "step": s, "value": 50.0 if s == 1234 else 1.0})
    return store


@pytest.mark.parametrize("via", ["index_run", "rebuild"])
def test_a_live_runs_points_are_indexed_from_a_bounded_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, via: str
) -> None:
    store = _store_with_long_runs(tmp_path)
    idx = Index(tmp_path / "i.db", store=store)
    exact = downsample(store.read_metric_points("toy", "done"))
    full_reads: list[str] = []
    real = store.read_metric_points

    def spy(project: str, run_id: str) -> list[MetricPoint]:
        full_reads.append(run_id)
        return real(project, run_id)

    monkeypatch.setattr(store, "read_metric_points", spy)
    if via == "index_run":
        for record in store.iter_records():
            index_run(idx, store, record)
    else:  # a rebuild skips the files; the first read indexes them
        rebuild_index(idx, store)
        assert full_reads == []
    live, done = idx.metric_points("live"), idx.metric_points("done")
    assert full_reads == ["done"]  # an ended run's history stays exact (downsample of all)
    assert done == exact
    assert len(live) == 1000
    assert {0, 1234, 2999} <= {p.step for p in live}  # the live run's peak survives


def test_downsample_keeps_a_one_step_spike() -> None:
    # every-n-th sampling dropped it, so the indexed curve of an ended run lost its spike
    points = [MetricPoint(name="loss", step=i, value=1.0) for i in range(5000)]
    points[2501] = MetricPoint(name="loss", step=2501, value=50.0)
    out = downsample(points, limit=1000)
    assert len(out) == 1000 and out[0].step == 0 and out[-1].step == 4999
    assert any(p.step == 2501 and p.value == 50.0 for p in out)


def test_schema_version_mismatch_triggers_rebuild(tmp_path: Path) -> None:
    path = tmp_path / "i.db"
    store = RunStore(Layout(tmp_path / "home"))
    store.layout.ensure()
    fresh = Index(path)
    assert fresh.rebuilt_schema  # new file: empty tables, rebuild from files
    fresh.upsert_run(make_record("r1"))  # usable at once
    assert Index(path).rebuilt_schema  # still not rebuilt
    rebuild_index(fresh, store)
    assert not Index(path).rebuilt_schema
    fresh.upsert_run(make_record("r1"))
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    old = Index(path)
    assert old.rebuilt_schema
    assert [r.run_id for r in old.list_runs()] == ["r1"]  # untouched until the rebuild
    assert rebuild_index_if_stale(old, store) == 0
    assert old.list_runs() == [] and old.schema_version() == str(SCHEMA_VERSION)
    assert rebuild_index_if_stale(old, store) is None


def _seeded_store(tmp_path: Path) -> RunStore:
    layout = Layout(tmp_path / "home")
    layout.ensure()
    store = RunStore(layout)
    store.register_project(ProjectConfig(project="toy"), tmp_path)
    for rid in ("r1", "r2"):
        store.create_run(make_record(rid, status=RunStatus.FINISHED, tags=["t"]))
        store.append_score(
            "toy",
            rid,
            ScoreRecord(metric="acc", version="v1", key="value", value=0.5, created_at=utcnow()),
        )
        append_jsonl(
            layout.run_dir("toy", rid) / "metrics.jsonl", {"name": "loss", "step": 0, "value": 1.0}
        )
    return store


def test_rebuild_matches_live_index(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    live = Index(tmp_path / "live.db")
    for entry in store.list_projects():
        live.upsert_project(entry)
    for record in store.iter_records():
        live.upsert_run(record)
        live.replace_scores(record.run_id, store.read_scores(record.project, record.run_id))
        live.replace_metric_points(
            record.run_id, store.read_metric_points(record.project, record.run_id)
        )
    rebuilt = Index(tmp_path / "rebuilt.db", store=store)
    assert rebuild_index(rebuilt, store) == 2
    assert live.list_runs() == rebuilt.list_runs()
    assert live.scores_for(["r1", "r2"]) == rebuilt.scores_for(["r1", "r2"])
    assert live.metric_points("r1") == rebuilt.metric_points("r1")
    assert [p.project for p in rebuilt.list_projects()] == ["toy"]


def test_repair_index_gaps(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    idx = Index(tmp_path / "i.db")
    assert repair_index_gaps(idx, store) == ["r1", "r2"]
    assert repair_index_gaps(idx, store) == []
    assert idx.get_project("toy") is not None


def test_a_corrupt_index_file_is_moved_aside_and_rebuilt(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    path = tmp_path / "i.db"
    path.write_bytes(b"garbage, not a database" * 100)
    idx = Index(path, store=store)
    assert idx.rebuilt_schema
    assert [p.read_bytes()[:7] for p in tmp_path.glob("i.db.corrupt-*")] == [b"garbage"]
    assert rebuild_index_if_stale(idx, store) == 2
    assert idx.run_ids() == {"r1", "r2"}
    assert not Index(path, store=store).rebuilt_schema  # the new file is used as it is


def test_an_unopenable_index_is_not_moved_aside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "i.db"
    Index(path)

    def locked(_conn: object, _record: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("hypothex.core.index._sqlite_pragmas", locked)
    with pytest.raises(OperationalError):
        Index(path)
    assert not list(tmp_path.glob("i.db.corrupt-*"))


def test_repair_index_gaps_drops_runs_whose_folder_is_gone(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    idx = Index(tmp_path / "i.db")
    repair_index_gaps(idx, store)
    shutil.rmtree(store.layout.run_dir("toy", "r1"))
    assert repair_index_gaps(idx, store) == []
    assert idx.run_ids() == {"r2"}
    assert idx.get_run("r1") is None
    assert idx.scores_for(["r1"]) == {}
    assert [r.run_id for r in idx.list_runs()] == ["r2"]


def test_schema_version_is_none_only_for_a_missing_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    idx = Index(tmp_path / "i.db")
    assert idx.schema_version() is None  # new file: tables, but no rebuild yet
    with sqlite3.connect(idx.path) as conn:
        conn.execute("DROP TABLE meta")
    assert idx.schema_version() is None

    def locked(key: str) -> None:
        raise OperationalError("SELECT", {}, sqlite3.OperationalError("database is locked"))

    monkeypatch.setattr(idx, "get_meta", locked)
    with pytest.raises(OperationalError):
        idx.schema_version()  # a busy index is not mistaken for a new one


def test_metric_points_for_takes_more_names_than_sqlite_has_variables(tmp_path: Path) -> None:
    idx = Index(tmp_path / "i.db")
    for rid in ("r1", "r2"):
        idx.replace_metric_points(
            rid,
            [MetricPoint(name=n, step=s, value=1.0) for n in ("loss", "acc", "lr") for s in (0, 1)],
        )
    names = [f"m{i:05d}" for i in range(40_000)] + ["lr", "acc"]
    got = idx.metric_points_for(["r1", "r2"], names=names)
    want = [("acc", 0), ("acc", 1), ("lr", 0), ("lr", 1)]
    assert {rid: [(p.name, p.step) for p in pts] for rid, pts in got.items()} == {
        "r1": want,
        "r2": want,
    }


@pytest.mark.parametrize("rebuild_after_publish", [False, True])
def test_pending_live_metric_read_keeps_a_newer_terminal_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rebuild_after_publish: bool
) -> None:
    layout = Layout(tmp_path / "home")
    layout.ensure()
    store = RunStore(layout)
    store.register_project(ProjectConfig(project="toy"), tmp_path)
    record = make_record("r1", status=RunStatus.RUNNING)
    store.create_run(record)
    expected = [
        MetricPoint(name=f"m{i:03d}", step=0, value=float(i)) for i in range(MAX_METRIC_NAMES + 1)
    ]
    for point in expected:
        append_jsonl(layout.run_dir("toy", "r1") / "metrics.jsonl", point.model_dump())
    idx = Index(layout.index_db, store=store)
    rebuild_index(idx, store)
    original_read = store.read_metric_points_bounded
    published_generations: list[int] = []

    def read_then_finish(project: str, run_id: str, limit: int = 1000) -> list[MetricPoint]:
        bounded = original_read(project, run_id, limit)
        assert len(bounded) == MAX_METRIC_NAMES
        # The pending reader is paused while the terminal path publishes the exact history.
        ended = record.model_copy(update={"status": RunStatus.FINISHED})
        store.write_record(ended)
        index_run(idx, store, ended)
        assert idx.metric_points(run_id) == expected
        if rebuild_after_publish:
            # A fresh marker must not authorize a snapshot of the old RUNNING state.
            rebuild_index(idx, store)
        published_generations.append(idx.generation())
        return bounded

    monkeypatch.setattr(store, "read_metric_points_bounded", read_then_finish)
    assert idx.metric_points("r1") == expected
    assert idx.metric_points("r1") == expected
    assert idx.generation() == published_generations[0] + int(rebuild_after_publish)
    assert idx.get_run("r1") == store.read_record("toy", "r1")
