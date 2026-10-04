import json
from pathlib import Path
from typing import Any

import pytest

import hypothex as hx
from hypothex import sdk
from hypothex.core.errors import StoreError
from hypothex.core.records import Artifact


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
    assert run.log_checkpoint("/x.pt", step=1, metrics={"val": 0.5}) is None
    assert run.log_trace("ex-1", [{"tool": "t"}]) is None
    assert run.log_usage(tokens_in=1, usd=0.5, example_id="ex-1") is None
    assert run.log_samples("latency_ms", [1.0]) is None
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


def test_log_predictions_after_partial_line_keeps_rows(run_env: Path) -> None:
    path = run_env / "predictions" / "predictions.jsonl"
    path.write_text('{"id": "a", "prediction": 1}\n{"id": "b", "pred')  # crash mid-write
    assert hx.current().log_predictions([{"id": "c", "prediction": 3}]) == 1
    lines = path.read_text().splitlines()
    assert json.loads(lines[-1]) == {"id": "c", "prediction": 3}
    assert json.loads(lines[0])["id"] == "a"


def test_seed_rejects_non_integer_env_with_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPOTHEX_SEED", "abc")
    with pytest.raises(ValueError, match="HYPOTHEX_SEED must be an integer, got 'abc'"):
        hx.seed()
    monkeypatch.setenv("HYPOTHEX_SEED", " 42 ")
    assert hx.seed() == 42


def test_log_trace_writes_sanitised_file_and_overwrites(run_env: Path) -> None:
    run = hx.current()
    run.log_trace(
        "route 7/b",
        [
            {
                "tool": "retro_expand",
                "args": {"top_k": 8},
                "result": "8 precursors",
                "tokens_in": 4410,
                "tokens_out": 512,
                "seconds": 4.82,
                "ms": 4820,  # unknown keys are dropped
            },
            {"tool": "check_stock", "args": "CCO", "error": "timeout 8 s"},
        ],
    )
    path = run_env / "traces" / "route_7_b-5db86396.jsonl"  # sha1("route 7/b")[:8]
    assert _lines(path) == [
        {
            "example_id": "route 7/b",
            "turn": 1,
            "tool": "retro_expand",
            "args": {"top_k": 8},
            "result": "8 precursors",
            "tokens_in": 4410,
            "tokens_out": 512,
            "seconds": 4.82,
            "error": None,
        },
        {
            "example_id": "route 7/b",
            "turn": 2,
            "tool": "check_stock",
            "args": "CCO",
            "result": None,
            "tokens_in": 0,
            "tokens_out": 0,
            "seconds": 0.0,
            "error": "timeout 8 s",
        },
    ]
    run.log_trace("route 7/b", [{"turn": 5, "tool": "score_routes"}])
    assert [(r["turn"], r["tool"]) for r in _lines(path)] == [(5, "score_routes")]


def test_log_trace_keeps_similar_ids_apart_and_empty_traces(run_env: Path) -> None:
    run = hx.current()
    run.log_trace("a/b", [{"tool": "x"}])
    run.log_trace("a_b", [{"tool": "y"}])
    run.log_trace("e/0", [])
    traces = run_env / "traces"
    assert sorted(p.name for p in traces.iterdir()) == [
        "a_b-3ec69c85.jsonl",  # sha1("a/b")[:8]
        "a_b.jsonl",
        "e_0-7569d147.jsonl",  # sha1("e/0")[:8]
    ]
    assert [r["tool"] for r in _lines(traces / "a_b-3ec69c85.jsonl")] == ["x"]
    assert [r["tool"] for r in _lines(traces / "a_b.jsonl")] == ["y"]
    # an empty trace still creates its file, with a marker line that keeps the id
    assert _lines(traces / "e_0-7569d147.jsonl") == [{"example_id": "e/0"}]


def test_trace_and_sample_writers_refuse_a_file_of_another_id(run_env: Path) -> None:
    run = hx.current()
    # regression: "a_b-3ec69c85" looks like the stem of "a/b", so it is hashed too
    run.log_trace("a/b", [{"tool": "x"}])
    run.log_trace("a_b-3ec69c85", [{"tool": "y"}])
    traces = run_env / "traces"
    assert [r["tool"] for r in _lines(traces / "a_b-3ec69c85.jsonl")] == ["x"]
    assert [r["tool"] for r in _lines(traces / "a_b-3ec69c85-d64fa8bc.jsonl")] == ["y"]
    # a sha1 prefix collision cannot be produced on demand: plant a file that stores
    # another id under the stem of "k/1", as a colliding id would have written it
    planted = traces / "k_1-3437d2e8.jsonl"  # sha1("k/1")[:8]
    planted.write_text('{"example_id": "other", "turn": 1}\n')
    with pytest.raises(StoreError, match="id collision: k_1-3437d2e8.jsonl already holds"):
        run.log_trace("k/1", [{"tool": "z"}])
    assert planted.read_text() == '{"example_id": "other", "turn": 1}\n'  # untouched
    samples = run_env / "samples"
    samples.mkdir()
    (samples / "lat_ms-94293541.jsonl").write_text('{"name": "other", "value": 1.0}\n')
    with pytest.raises(StoreError, match="id collision: lat_ms-94293541.jsonl already holds"):
        run.log_samples("lat ms", [2.0])  # sha1("lat ms")[:8] = 94293541
    assert _lines(samples / "lat_ms-94293541.jsonl") == [{"name": "other", "value": 1.0}]


def test_log_trace_rejects_bad_steps_without_writing(run_env: Path) -> None:
    run = hx.current()
    with pytest.raises(ValueError, match="trace step 2 of 'e1' is invalid: tokens_in"):
        run.log_trace("e1", [{"tool": "a"}, {"tool": "b", "tokens_in": -1}])
    with pytest.raises(
        ValueError, match="trace step 1 of 'e1' is invalid: seconds: Input should be a finite"
    ):
        run.log_trace("e1", [{"tool": "a", "seconds": float("inf")}])
    assert not (run_env / "traces" / "e1.jsonl").exists()
    with pytest.raises(ValueError, match="must not be empty"):
        run.log_trace("", [{"tool": "a"}])


def test_log_usage_appends_rows_and_validates(run_env: Path) -> None:
    run = hx.current()
    run.log_usage(tokens_in=100, tokens_out=20, usd=0.25, seconds=1.5, example_id="a")
    run.log_usage(tokens_in=50)
    path = run_env / "usage.jsonl"
    assert _lines(path) == [
        {"example_id": "a", "tokens_in": 100, "tokens_out": 20, "usd": 0.25, "seconds": 1.5},
        {"example_id": None, "tokens_in": 50, "tokens_out": 0, "usd": 0.0, "seconds": 0.0},
    ]
    with pytest.raises(ValueError, match="invalid usage: usd"):
        run.log_usage(usd=-0.5)
    with pytest.raises(ValueError, match="invalid usage: usd: Input should be a finite number"):
        run.log_usage(usd=float("inf"))
    with pytest.raises(ValueError, match="invalid usage: seconds: Input should be a finite"):
        run.log_usage(seconds=float("inf"))
    assert len(_lines(path)) == 2


def test_log_samples_appends_values(run_env: Path) -> None:
    run = hx.current()
    run.log_samples("latency ms", [12.5, 15])
    run.log_samples("latency ms", iter([20.0]))
    run.log_samples("latency_ms", [1.0])  # a different series, a different file
    path = run_env / "samples" / "latency_ms-136bd8be.jsonl"  # sha1("latency ms")[:8]
    assert _lines(path) == [
        {"name": "latency ms", "value": 12.5},
        {"name": "latency ms", "value": 15.0},
        {"name": "latency ms", "value": 20.0},
    ]
    assert _lines(run_env / "samples" / "latency_ms.jsonl") == [
        {"name": "latency_ms", "value": 1.0}
    ]
    with pytest.raises(ValueError, match="sample of 'latency ms' must be a finite number"):
        run.log_samples("latency ms", [1.0, float("nan")])
    with pytest.raises(ValueError, match="must be a finite number, got 'slow'"):
        run.log_samples("latency ms", ["slow"])
    assert len(_lines(path)) == 3  # a bad batch writes nothing
    run.log_samples("empty", [])
    assert not (run_env / "samples" / "empty.jsonl").exists()


def test_log_checkpoint_records_step_and_metrics(run_env: Path, tmp_path: Path) -> None:
    ckpt = tmp_path / "step_100.pt"
    ckpt.write_bytes(b"12345")
    run = hx.current()
    run.log_checkpoint(ckpt, step=100, metrics={"val_top1": 0.5})
    row = _lines(run_env / "artifacts.jsonl")[0]
    assert row == {
        "kind": "checkpoint",
        "path": str(ckpt.resolve()),
        "host": "local",
        "size": 5,
        "step": 100,
        "metrics": {"val_top1": 0.5},
    }
    artifact = Artifact.model_validate(row)
    assert (artifact.step, artifact.metrics) == (100, {"val_top1": 0.5})
    with pytest.raises(TypeError):
        run.log_checkpoint(ckpt, step=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="checkpoint metric 'val' must be a finite number"):
        run.log_checkpoint(ckpt, step=200, metrics={"val": float("inf")})
    assert len(_lines(run_env / "artifacts.jsonl")) == 1


def test_log_skips_non_finite_values_with_a_warning(run_env: Path) -> None:
    run = hx.current()
    with pytest.warns(RuntimeWarning, match="loss"):
        run.log({"loss": float("nan"), "acc": 0.5})
    with pytest.warns(RuntimeWarning, match="loss"):
        run.log({"loss": float("inf")})
    run.log({"loss": 0.25})
    rows = _lines(run_env / "metrics.jsonl")
    assert [(r["name"], r["step"], r["value"]) for r in rows] == [
        ("acc", 0, 0.5),
        ("loss", 2, 0.25),
    ]


def test_log_records_non_finite_values_as_divergence_markers(run_env: Path) -> None:
    run = hx.current()
    with pytest.warns(RuntimeWarning):
        run.log({"loss": float("nan"), "acc": 0.5})
    with pytest.warns(RuntimeWarning):
        run.log({"loss": float("inf"), "grad": float("-inf")}, step=7)
    rows = _lines(run_env / "metrics_nonfinite.jsonl")
    assert [(r["name"], r["step"], r["value"]) for r in rows] == [
        ("loss", 0, "nan"),
        ("loss", 7, "inf"),
        ("grad", 7, "-inf"),
    ]
    assert all(isinstance(r["t"], float) for r in rows)
    assert len(_lines(run_env / "metrics.jsonl")) == 1  # only acc


def test_log_opens_each_metrics_file_once_per_call(
    run_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    real = sdk.open_jsonl_append

    def counting(path: Path) -> Any:
        opened.append(path.name)
        return real(path)

    monkeypatch.setattr(sdk, "open_jsonl_append", counting)
    monkeypatch.setattr(sdk, "append_jsonl", lambda *a, **k: pytest.fail("per-row append"))
    run = hx.current()
    values = {f"m/{i:03d}": i / 10 for i in range(50)}
    values["bad"] = float("nan")
    values["worse"] = float("inf")
    with pytest.warns(RuntimeWarning):
        run.log(values)
    assert sorted(opened) == ["metrics.jsonl", "metrics_nonfinite.jsonl"]
    rows = _lines(run_env / "metrics.jsonl")
    assert [(r["name"], r["step"], r["value"]) for r in rows] == [
        (f"m/{i:03d}", 0, i / 10) for i in range(50)
    ]
    assert len({r["t"] for r in rows}) == 1
    bad = _lines(run_env / "metrics_nonfinite.jsonl")
    assert [(r["name"], r["value"]) for r in bad] == [("bad", "nan"), ("worse", "inf")]
    opened.clear()
    run.log({"loss": 0.5})
    assert opened == ["metrics.jsonl"]


def test_log_with_a_non_number_writes_nothing_and_keeps_steps(run_env: Path) -> None:
    run = hx.current()
    with pytest.raises(ValueError):
        run.log({"loss": 0.5, "acc": "high"})  # type: ignore[dict-item]
    assert not (run_env / "metrics.jsonl").exists()
    run.log({"loss": 0.25})
    rows = _lines(run_env / "metrics.jsonl")
    assert [(r["name"], r["step"]) for r in rows] == [("loss", 0)]


@pytest.mark.parametrize("name", ["", "x" * 257, 3])
def test_log_rejects_a_bad_metric_name_and_writes_nothing(run_env: Path, name: object) -> None:
    # An empty or 2M-character name made the run page millions of pixels wide.
    run = hx.current()
    with pytest.raises(ValueError, match="metric name"):
        run.log({"loss": 0.5, name: 1.0})  # type: ignore[dict-item]
    assert not (run_env / "metrics.jsonl").exists()
    run.log({"loss": 0.25, "x" * 256: 1.0})
    rows = _lines(run_env / "metrics.jsonl")
    assert [(r["name"][:4], r["step"]) for r in rows] == [("loss", 0), ("xxxx", 0)]
