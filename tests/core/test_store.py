import fcntl
from pathlib import Path

import pytest

from hypothex.core.config import ProjectConfig
from hypothex.core.errors import RunNotFoundError, StoreError
from hypothex.core.fsutil import append_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.records import ScoreRecord
from hypothex.core.store import RunStore
from tests.factories import make_record


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    layout = Layout(tmp_path)
    layout.ensure()
    return RunStore(layout)


def test_register_and_load_project(store: RunStore, tmp_path: Path) -> None:
    cfg = ProjectConfig(project="toy")
    entry = store.register_project(cfg, tmp_path)
    assert entry.repo == str(tmp_path.resolve())
    assert store.load_project("toy").config.project == "toy"
    assert [e.project for e in store.list_projects()] == ["toy"]
    with pytest.raises(StoreError, match="unknown project"):
        store.load_project("nope")


def test_register_at_new_path_remembers_previous_repos(store: RunStore, tmp_path: Path) -> None:
    cfg = ProjectConfig(project="toy")
    a, b = tmp_path / "a", tmp_path / "b"
    assert store.register_project(cfg, a).previous_repos == []
    assert store.register_project(cfg, a).previous_repos == []
    assert store.register_project(cfg, b).previous_repos == [str(a.resolve())]
    entry = store.register_project(cfg, a)
    assert entry.repo == str(a.resolve()) and entry.previous_repos == [str(b.resolve())]
    assert store.load_project("toy").previous_repos == [str(b.resolve())]


def test_create_read_and_duplicate(store: RunStore) -> None:
    record = make_record()
    run_dir = store.create_run(record)
    for sub in ("logs", "predictions", "env"):
        assert (run_dir / sub).is_dir()
    assert store.read_record("toy", "r1") == record
    with pytest.raises(StoreError, match="exists"):
        store.create_run(record)


def test_iter_records_skips_broken_dirs(store: RunStore) -> None:
    store.create_run(make_record("r1"))
    store.create_run(make_record("r2"))
    (store.layout.runs_dir("toy") / "empty").mkdir()
    (store.layout.run_dir("toy", "r2") / "run.yaml").write_text("{not: [valid")
    assert [r.run_id for r in store.iter_records()] == ["r1"]
    assert store.list_run_ids() == {"r1": "toy", "r2": "toy"}


def test_find_project_of(store: RunStore) -> None:
    store.create_run(make_record("r9", project="other"))
    assert store.find_project_of("r9") == "other"
    with pytest.raises(RunNotFoundError):
        store.find_project_of("missing")


def test_scores_points_artifacts_notes(store: RunStore) -> None:
    store.create_run(make_record())
    run_dir = store.layout.run_dir("toy", "r1")
    score = ScoreRecord(metric="acc", version="v1", key="value", value=0.5, created_at=utcnow())
    store.append_score("toy", "r1", score)
    assert store.read_scores("toy", "r1") == [score]
    append_jsonl(run_dir / "metrics.jsonl", {"name": "loss", "step": 0, "value": 1.5, "t": 1.0})
    append_jsonl(run_dir / "metrics.jsonl", {"name": "loss", "value": "bad"})
    assert [p.value for p in store.read_metric_points("toy", "r1")] == [1.5]
    append_jsonl(run_dir / "artifacts.jsonl", {"kind": "checkpoint", "path": "/m.pt"})
    assert store.read_artifacts("toy", "r1")[0].kind == "checkpoint"
    store.append_note("toy", "r1", "looks good", "alice")
    assert "looks good" in store.read_notes("toy", "r1")


def test_metric_hashes_roundtrip(store: RunStore) -> None:
    assert store.metric_hashes("toy") == {}
    store.save_metric_hashes("toy", {"acc@v1": "sha256:1"})
    assert store.metric_hashes("toy") == {"acc@v1": "sha256:1"}


def test_corrupt_files_raise_store_error_with_path(store: RunStore, tmp_path: Path) -> None:
    store.register_project(ProjectConfig(project="toy"), tmp_path)
    project_file = store.layout.project_dir("toy") / "project.json"
    project_file.write_text('{"project": "toy"}')
    with pytest.raises(StoreError, match="project.json"):
        store.load_project("toy")
    store.register_project(ProjectConfig(project="toy"), tmp_path)  # repairs the file
    assert store.load_project("toy").project == "toy"
    store.create_run(make_record("r1"))
    run_yaml = store.layout.run_dir("toy", "r1") / "run.yaml"
    run_yaml.write_bytes(b"\xff\xfe: [")
    with pytest.raises(StoreError, match="run.yaml"):
        store.read_record("toy", "r1")


def test_project_lock_excludes_other_holders(store: RunStore) -> None:
    with store.project_lock("toy"):
        lock_file = store.layout.project_dir("toy") / ".lock"
        with lock_file.open("a") as fh, pytest.raises(BlockingIOError):
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    with lock_file.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # released on exit
