import fcntl
import json
import math
import tracemalloc
from pathlib import Path

import pytest
from pydantic import ValidationError

from hypothex.core.config import ProjectConfig
from hypothex.core.errors import RunNotFoundError, StoreError
from hypothex.core.fsutil import append_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.records import ScoreRecord, UsageTotals
from hypothex.core.store import (
    RunStore,
    TraceStep,
    UsageRow,
    check_stem_owner,
    safe_stem,
    sum_usage,
)
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
    assert store.read_metric_points_bounded("toy", "r1") == store.read_metric_points("toy", "r1")
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


def test_safe_stem_replaces_unsafe_characters_and_adds_a_hash() -> None:
    # sha1("route 7/b:ü")[:8] = b85600fe, sha1("../x")[:8] = 72e4d01d
    assert safe_stem("route 7/b:ü") == "route_7_b__-b85600fe"
    assert safe_stem("a-b_c.d") == "a-b_c.d"  # already safe: unchanged, no hash
    assert safe_stem("../x") == ".._x-72e4d01d"
    with pytest.raises(ValueError, match="must not be empty"):
        safe_stem("")


def test_safe_stem_never_merges_distinct_names() -> None:
    names = ["a/b", "a_b", "a b", "a:b", "a_b-3ec69c85"]
    stems = [safe_stem(n) for n in names]
    assert stems[:2] == ["a_b-3ec69c85", "a_b"]
    assert len(set(stems)) == len(names)


def test_safe_stem_hashes_names_that_already_look_hashed() -> None:
    # regression: "a_b-3ec69c85" is already safe, but kept as is it would take the
    # file of "a/b"; a name ending in "-" + 8 lowercase hex digits is hashed too
    assert safe_stem("a/b") == "a_b-3ec69c85"
    assert safe_stem("a_b-3ec69c85") == "a_b-3ec69c85-d64fa8bc"  # sha1(...)[:8]
    assert safe_stem("a/b") != safe_stem("a_b-3ec69c85")
    assert safe_stem("run-12345678") == "run-12345678-736848d3"
    assert safe_stem("run-1234567") == "run-1234567"  # 7 digits: not a hash tail
    assert safe_stem("run-ABCDEF12") == "run-ABCDEF12"  # upper case: not a hash tail


def test_check_stem_owner_rejects_a_different_original(tmp_path: Path) -> None:
    path = tmp_path / "a_b-3ec69c85.jsonl"
    check_stem_owner(path, "example_id", "a/b")  # no file yet
    path.write_text("")
    check_stem_owner(path, "example_id", "a/b")  # empty file
    path.write_text('{"example_id": "a/b", "turn": 1}\n')
    check_stem_owner(path, "example_id", "a/b")  # the same original: overwrite is fine
    path.write_text('{"example_id": "x/y", "turn": 1}\n')
    with pytest.raises(
        StoreError,
        match=r"id collision: a_b-3ec69c85\.jsonl already holds example_id 'x/y', not 'a/b'",
    ):
        check_stem_owner(path, "example_id", "a/b")
    samples = tmp_path / "lat.jsonl"
    samples.write_text('{"name": "lat", "value": 1.0}\n')
    check_stem_owner(samples, "name", "lat")
    with pytest.raises(StoreError, match="id collision"):
        check_stem_owner(samples, "name", "lat2")
    samples.write_text('{"value": 1.0}\n')  # written by hand, no stored name: not checked
    check_stem_owner(samples, "name", "lat2")


def test_read_usage_skips_bad_rows_and_sums(store: RunStore) -> None:
    store.create_run(make_record())
    path = store.layout.run_dir("toy", "r1") / "usage.jsonl"
    append_jsonl(
        path, {"example_id": "a", "tokens_in": 100, "tokens_out": 20, "usd": 0.25, "seconds": 1.5}
    )
    append_jsonl(path, {"tokens_in": -1})  # negative: skipped
    append_jsonl(path, {"tokens_in": "many"})  # not a number: skipped
    append_jsonl(path, {"usd": math.inf})  # json writes Infinity and reads it back: skipped
    append_jsonl(path, {"seconds": math.nan})  # NaN: skipped
    append_jsonl(
        path, {"example_id": None, "tokens_in": 50, "tokens_out": 5, "usd": 0.125, "seconds": 0.5}
    )
    assert "Infinity" in path.read_text()
    rows = store.read_usage("toy", "r1")
    assert rows == [
        UsageRow(example_id="a", tokens_in=100, tokens_out=20, usd=0.25, seconds=1.5),
        UsageRow(tokens_in=50, tokens_out=5, usd=0.125, seconds=0.5),
    ]
    # 0.25 + 0.125 and 1.5 + 0.5 are exact in binary floating point.
    assert sum_usage(rows) == UsageTotals(
        tokens_in=150, tokens_out=25, usd=0.375, seconds=2.0, calls=2
    )
    assert sum_usage([]) is None
    assert store.read_usage("toy", "missing") == []


def test_usage_and_trace_floats_must_be_finite() -> None:
    with pytest.raises(ValidationError, match="finite number"):
        UsageRow(usd=math.inf)
    with pytest.raises(ValidationError, match="finite number"):
        TraceStep(turn=1, seconds=math.inf)


def test_list_and_read_traces(store: RunStore) -> None:
    store.create_run(make_record())
    traces = store.layout.run_dir("toy", "r1") / "traces"
    assert store.list_traces("toy", "r1") == []
    ab = traces / f"{safe_stem('a/b')}.jsonl"  # a_b-3ec69c85.jsonl
    append_jsonl(
        ab,
        {
            "example_id": "a/b",
            "turn": 1,
            "tool": "retro_expand",
            "tokens_in": 4410,
            "tokens_out": 512,
            "seconds": 4.82,
        },
    )
    append_jsonl(
        ab, {"example_id": "a/b", "turn": 2, "tool": "check_stock", "error": "timeout 8 s"}
    )
    append_jsonl(ab, {"example_id": "a/b", "turn": 3, "seconds": math.inf})  # not finite: skipped
    append_jsonl(traces / "c.jsonl", {"tool": "score_routes"})  # no turn, no example_id
    append_jsonl(traces / "c.jsonl", {"turn": "x"})  # invalid: skipped
    # an empty trace is one marker line holding the original id
    append_jsonl(traces / f"{safe_stem('e/0')}.jsonl", {"example_id": "e/0"})
    assert store.list_traces("toy", "r1") == [
        {"example_id": "a/b", "turns": 2, "failed": True},
        {"example_id": "c", "turns": 1, "failed": False},
        {"example_id": "e/0", "turns": 0, "failed": False},
    ]
    steps = store.read_trace("toy", "r1", "a/b")
    assert steps == [
        TraceStep(turn=1, tool="retro_expand", tokens_in=4410, tokens_out=512, seconds=4.82),
        TraceStep(turn=2, tool="check_stock", error="timeout 8 s"),
    ]
    assert store.read_trace("toy", "r1", "a_b") == []  # a different id, a different file
    assert store.read_trace("toy", "r1", "c") == [TraceStep(turn=1, tool="score_routes")]
    assert store.read_trace("toy", "r1", "e/0") == []
    assert store.read_trace("toy", "r1", "nope") == []


def test_read_samples(store: RunStore) -> None:
    store.create_run(make_record())
    samples = store.layout.run_dir("toy", "r1") / "samples"
    assert store.read_samples("toy", "r1") == {}
    samples.mkdir()
    (samples / "latency_ms.jsonl").write_text(
        '{"value": 12.5}\n{"value": 15}\n{"value": "slow"}\n{"value": true}\n{"value": NaN}\n'
        '{"value": Infinity}\n'
    )
    (samples / "ttft.jsonl").write_text('{"value": 3.0}\n')
    # the SDK stores the original name in every row; the key is that name, not the stem
    (samples / f"{safe_stem('latency ms')}.jsonl").write_text(
        '{"name": "latency ms", "value": 1.0}\n{"name": "latency ms", "value": 2.0}\n'
    )
    assert store.read_samples("toy", "r1") == {
        "latency ms": [1.0, 2.0],
        "latency_ms": [12.5, 15.0],
        "ttft": [3.0],
    }


def test_read_metric_points_bounded_streams_a_huge_live_file(store: RunStore) -> None:
    from hypothex.core.thin import MAX_POINTS_PER_METRIC

    store.create_run(make_record())
    n = 20_000
    with (store.layout.run_dir("toy", "r1") / "metrics.jsonl").open("w") as fh:
        for s in range(n):
            value = 9.0 if s == 13_337 else 1.0 / (s + 1)
            fh.write(json.dumps({"name": "loss", "step": s, "value": value}) + "\n")
            fh.write(json.dumps({"name": "lr", "step": s, "value": 0.1}) + "\n")
        fh.write('{"name": "loss", "step": 1, "value": "' + "x" * (2 << 20) + '"}\n')
    tracemalloc.start()
    try:
        kept = store.read_metric_points_bounded("toy", "r1")
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    # the full read holds all 40k parsed points (~35 MiB); the bounded one a few thousand
    assert peak < 6 * 2**20, f"peak {peak / 2**20:.1f} MiB"
    loss = [p for p in kept if p.name == "loss"]
    assert len(loss) == MAX_POINTS_PER_METRIC
    assert len(kept) == 2 * MAX_POINTS_PER_METRIC
    assert {0, 13_337, n - 1} <= {p.step for p in loss}
