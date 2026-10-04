import json
import sys
from pathlib import Path

import pytest

from hypothex.core.config import load_project_config
from hypothex.core.errors import EvalError
from hypothex.core.evalrunner import default_python_cmd, run_worker
from hypothex.core.fsutil import read_jsonl
from hypothex.metrics import MetricResult, normalize_result
from tests.factories import write_toy_project


def _run_dir(tmp_path: Path, rows: list[dict]) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "predictions").mkdir(parents=True)
    (run_dir / "predictions" / "predictions.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows)
    )
    return run_dir


def _request(repo: Path, run_dir: Path, metrics: list[str]) -> dict:
    fns = {"accuracy": "toymetrics:accuracy", "broken": "toymetrics:broken"}
    return {
        "repo": str(repo),
        "run_dir": str(run_dir),
        "dataset": {
            "path": str(repo / "data" / "test.jsonl"),
            "id_field": "id",
            "reference_field": "reference",
        },
        "metrics": [{"name": m, "version": "v1", "fn": fns[m], "params": {}} for m in metrics],
    }


def test_normalize_result_variants() -> None:
    res = MetricResult(values={"a": 1.0}, per_example={"ex-0": {"ok": True}})
    assert normalize_result(res) == res
    assert normalize_result(0.5).values == {"value": 0.5}
    assert normalize_result({"k=1": 1}).values == {"k=1": 1.0}
    for bad in ("x", True, {"a": "b"}):
        with pytest.raises(TypeError):
            normalize_result(bad)


def test_normalize_result_validates_metric_result_values() -> None:
    assert normalize_result(MetricResult(values={"a": 1})).values == {"a": 1.0}
    for bad in ({"a": "0.5x"}, {"a": None}, {"a": True}, {}):
        with pytest.raises(TypeError, match="MetricResult.values"):
            normalize_result(MetricResult(values=bad))  # type: ignore[arg-type]


def test_evaluate_records_per_metric_error_for_non_numeric_result(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    (repo / "badmetrics.py").write_text(
        "from hypothex.metrics import MetricResult\n\n\n"
        "def stringy(examples):\n"
        "    return MetricResult(values={'value': 'high'})\n"
    )
    run_dir = _run_dir(tmp_path, [{"id": "ex-0", "prediction": 0}])
    request = _request(repo, run_dir, ["accuracy"])
    request["metrics"].append(
        {"name": "stringy", "version": "v1", "fn": "badmetrics:stringy", "params": {}}
    )
    acc, stringy = run_worker("evaluate", request, [sys.executable], cwd=repo)["results"]
    assert acc["values"] == {"value": 1.0} and acc["error"] is None
    assert stringy["values"] == {} and "MetricResult.values" in stringy["error"]


def test_evaluate_scores_and_writes_per_example(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    run_dir = _run_dir(tmp_path, [{"id": "ex-0", "prediction": 0}, {"id": "ex-1", "prediction": 0}])
    out = run_worker(
        "evaluate", _request(repo, run_dir, ["accuracy", "broken"]), [sys.executable], cwd=repo
    )
    acc, broken = out["results"]
    assert out["n_examples"] == 2
    assert acc["values"] == {"value": 0.5} and acc["error"] is None
    assert acc["source_hash"].startswith("sha256:")
    assert "boom" in broken["error"] and broken["values"] == {}
    per = read_jsonl(run_dir / "predictions" / "scores.accuracy@v1.jsonl")
    assert {r["id"]: r["correct"] for r in per} == {"ex-0": True, "ex-1": False}


def test_inline_reference_wins_over_dataset(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    run_dir = _run_dir(tmp_path, [{"id": "ex-1", "prediction": 5, "reference": 5}])
    out = run_worker("evaluate", _request(repo, run_dir, ["accuracy"]), [sys.executable], cwd=repo)
    assert out["results"][0]["values"] == {"value": 1.0}


def test_missing_predictions_is_eval_error(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    run_dir = tmp_path / "empty"
    run_dir.mkdir()
    with pytest.raises(EvalError, match="no predictions"):
        run_worker("evaluate", _request(repo, run_dir, ["accuracy"]), [sys.executable], cwd=repo)


def test_describe_reports_import_errors(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    request = {
        "repo": str(repo),
        "metrics": [
            {"name": "accuracy", "fn": "toymetrics:accuracy"},
            {"name": "gone", "fn": "nomodule:fn"},
        ],
    }
    out = run_worker("describe", request, [sys.executable], cwd=repo)["metrics"]
    assert out["accuracy"]["importable"] and out["accuracy"]["source_hash"]
    assert not out["gone"]["importable"] and "nomodule" in out["gone"]["error"]


def test_default_python_cmd_uses_env_python_or_falls_back_to_uv(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    config = load_project_config(repo)
    assert default_python_cmd(repo, config) == [sys.executable]

    config = config.model_copy(update={"env": config.env.model_copy(update={"python": None})})
    assert default_python_cmd(repo, config) == ["uv", "run", "--project", str(repo), "python"]


def test_missing_python_is_eval_error(tmp_path: Path) -> None:
    with pytest.raises(EvalError, match="could not start"):
        run_worker(
            "describe",
            {"repo": str(tmp_path), "metrics": []},
            ["/nonexistent/python"],
            cwd=tmp_path,
        )


def test_evaluate_counts_prediction_ids_missing_from_the_dataset(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    rows = [
        {"id": "ex-0", "prediction": 0},
        {"id": "x-1", "prediction": 1},
        {"id": "x-2", "prediction": 1, "reference": 1},  # inline: not joined
    ]
    run_dir = _run_dir(tmp_path, rows)
    out = run_worker("evaluate", _request(repo, run_dir, ["accuracy"]), [sys.executable], cwd=repo)
    assert (out["n_examples"], out["n_unmatched"]) == (3, 1)
    assert out["results"][0]["values"] == {"value": 2 / 3}


def test_evaluate_runs_no_metric_when_no_id_is_in_the_dataset(tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "repo", use_git=False)
    run_dir = _run_dir(tmp_path, [{"id": f"x-{i}", "prediction": 0} for i in range(3)])
    out = run_worker("evaluate", _request(repo, run_dir, ["accuracy"]), [sys.executable], cwd=repo)
    assert out == {"n_examples": 3, "n_unmatched": 3, "results": []}
    assert not (run_dir / "predictions" / "scores.accuracy@v1.jsonl").exists()
