import sqlite3
from pathlib import Path

from hypothex.core.config import ProjectConfig
from hypothex.core.fsutil import append_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.index import Index, downsample, rebuild_index, repair_index_gaps
from hypothex.core.layout import Layout
from hypothex.core.records import MetricPoint, RunStatus, ScoreRecord
from hypothex.core.store import RunStore
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


def test_downsample_keeps_last_point_and_limit() -> None:
    points = [MetricPoint(name="loss", step=i, value=float(i)) for i in range(2500)]
    points.append(MetricPoint(name="acc", step=0, value=1.0))
    out = downsample(points, limit=1000)
    loss = [p for p in out if p.name == "loss"]
    assert len(loss) <= 1000
    assert loss[-1].step == 2499
    assert [p.name for p in out].count("acc") == 1


def test_schema_version_mismatch_triggers_rebuild(tmp_path: Path) -> None:
    path = tmp_path / "i.db"
    assert Index(path).rebuilt_schema  # fresh file
    assert not Index(path).rebuilt_schema
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    assert Index(path).rebuilt_schema


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
    rebuilt = Index(tmp_path / "rebuilt.db")
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
