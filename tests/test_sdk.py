import json
from pathlib import Path

import pytest

import hypothex as hx
from hypothex import sdk


@pytest.fixture
def run_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "predictions").mkdir(parents=True)
    monkeypatch.setenv("HYPOTHEX_RUN_DIR", str(run_dir))
    monkeypatch.setenv("HYPOTHEX_RUN_ID", "r1")
    monkeypatch.setenv("HYPOTHEX_PROJECT", "toy")
    monkeypatch.setenv("HYPOTHEX_SEED", "7")
    monkeypatch.setattr(sdk, "_current", None)
    return run_dir


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_noop_outside_a_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYPOTHEX_RUN_DIR", raising=False)
    monkeypatch.delenv("HYPOTHEX_SEED", raising=False)
    run = hx.current()
    assert isinstance(run, hx.NoopRun) and not run.active and run.run_id is None
    run.log({"loss": 1.0})
    assert run.log_predictions([{"id": "a", "prediction": 1}]) == 0
    run.log_artifact("/x")
    run.note("n")
    assert hx.seed() is None and hx.seed(3) == 3


def test_log_auto_and_explicit_steps(run_env: Path) -> None:
    run = hx.current()
    assert isinstance(run, hx.Run) and run.run_id == "r1" and run.project == "toy"
    run.log({"loss": 1.0, "acc": 0.5})
    hx.current().log({"loss": 0.5})  # same object: step continues
    run.log({"loss": 0.1}, step=100)
    rows = _lines(run_env / "metrics.jsonl")
    assert [(r["name"], r["step"]) for r in rows] == [
        ("loss", 0),
        ("acc", 0),
        ("loss", 1),
        ("loss", 100),
    ]
    assert hx.seed() == 7


def test_log_predictions_validates_rows(run_env: Path) -> None:
    run = hx.current()
    assert run.log_predictions([{"id": "a", "prediction": 1}, {"id": 2, "prediction": [0]}]) == 2
    assert _lines(run_env / "predictions" / "predictions.jsonl")[1] == {"id": 2, "prediction": [0]}
    with pytest.raises(ValueError, match="'id' and 'prediction'"):
        run.log_predictions([{"prediction": 1}])


def test_log_artifact_and_note(run_env: Path, tmp_path: Path) -> None:
    ckpt = tmp_path / "m.pt"
    ckpt.write_bytes(b"12345")
    run = hx.current()
    run.log_artifact(ckpt, kind="checkpoint")
    row = _lines(run_env / "artifacts.jsonl")[0]
    assert row == {"kind": "checkpoint", "path": str(ckpt.resolve()), "host": "local", "size": 5}
    run.note("loss spikes at 9k")
    assert "loss spikes at 9k" in (run_env / "notes.md").read_text()
