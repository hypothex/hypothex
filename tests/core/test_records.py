from pathlib import Path

from hypothex.core.fsutil import append_jsonl
from hypothex.core.layout import Layout
from hypothex.core.records import Artifact, GitInfo, RunRecord, UsageTotals
from hypothex.core.store import RunStore
from tests.factories import make_record

PHASE_1A_RUN = {
    "run_id": "r-old",
    "project": "toy",
    "command": ["echo", "hi"],
    "command_template": ["echo", "hi"],
    "cwd": "/tmp",
    "environment_id": "env1",
    "host": "mac",
    "config_hash": "sha256:abc",
    "status": "finished",
    "created_at": "2026-09-26T10:00:00Z",
    "git": {"repo": None, "commit": "a" * 40, "branch": "main", "dirty": True},
    "artifacts": [{"kind": "checkpoint", "path": "/ck/1.pt", "host": "local", "size": 3}],
}


def test_phase_1a_run_yaml_still_loads_with_new_defaults() -> None:
    record = RunRecord.model_validate(PHASE_1A_RUN)
    assert record.git.dirty is True
    assert record.git.untracked_count == 0 and record.git.untracked == []
    assert record.artifacts[0].step is None and record.artifacts[0].metrics == {}
    assert record.usage is None


def test_usage_totals_defaults() -> None:
    assert UsageTotals().model_dump() == {
        "tokens_in": 0,
        "tokens_out": 0,
        "usd": 0.0,
        "seconds": 0.0,
        "calls": 0,
    }


def test_new_fields_round_trip_through_run_yaml(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    layout.ensure()
    store = RunStore(layout)
    record = make_record(
        git=GitInfo(commit="b" * 40, dirty=False, untracked_count=2, untracked=["a.txt", "b.txt"]),
        artifacts=[
            Artifact(kind="checkpoint", path="/ck/5.pt", step=500, metrics={"val_loss": 1.92})
        ],
        usage=UsageTotals(tokens_in=1200, tokens_out=300, usd=0.042, seconds=12.5, calls=4),
    )
    store.create_run(record)
    loaded = store.read_record("toy", "r1")
    assert loaded.git.untracked_count == 2 and loaded.git.untracked == ["a.txt", "b.txt"]
    assert loaded.artifacts[0].step == 500
    assert loaded.artifacts[0].metrics == {"val_loss": 1.92}
    assert loaded.usage == UsageTotals(
        tokens_in=1200, tokens_out=300, usd=0.042, seconds=12.5, calls=4
    )


def test_sdk_style_artifact_rows_without_step_still_parse(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    layout.ensure()
    store = RunStore(layout)
    store.create_run(make_record())
    run_dir = layout.run_dir("toy", "r1")
    append_jsonl(run_dir / "artifacts.jsonl", {"kind": "model", "path": "/m.pt", "size": 1})
    append_jsonl(
        run_dir / "artifacts.jsonl",
        {"kind": "checkpoint", "path": "/c.pt", "step": 10, "metrics": {"loss": 0.5}},
    )
    arts = store.read_artifacts("toy", "r1")
    assert [(a.kind, a.step, a.metrics) for a in arts] == [
        ("model", None, {}),
        ("checkpoint", 10, {"loss": 0.5}),
    ]
