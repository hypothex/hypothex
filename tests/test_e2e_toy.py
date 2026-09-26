"""End to end: the toy example through the real CLI."""

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from hypothex.cli.main import app
from tests.factories import init_git_repo

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "toy-classifier"
runner = CliRunner()


def hx(*args: str) -> dict:
    argv = list(args)
    argv.insert(argv.index("--") if "--" in argv else len(argv), "--json")
    result = runner.invoke(app, argv, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_toy_classifier_end_to_end(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "toy-classifier"
    shutil.copytree(EXAMPLE, repo, ignore=shutil.ignore_patterns("data"))
    cfg_path = repo / "hypothex.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["env"]["python"] = [sys.executable]
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    monkeypatch.chdir(repo)
    assert runner.invoke(app, ["--help"]).exit_code == 0
    runpy.run_path(str(repo / "make_data.py"), run_name="__main__")
    init_git_repo(repo)

    # 3 models x 3 seeds
    for model in ("logreg", "rf", "knn"):
        for seed in (1, 2, 3):
            out = hx(
                "run",
                "-t",
                "toy-test",
                "-H",
                f"baseline {model}",
                "--seed",
                str(seed),
                "--",
                sys.executable,
                "train_eval.py",
                "--model",
                model,
                "--seed",
                "{seed}",
            )
            assert out["status"] == "finished"

    board = hx("leaderboard", "toy-test")
    assert len(board["rows"]) == 3 and all(r["n"] == 3 for r in board["rows"])
    assert board["rows"][0]["primary"]["mean"] > 0.5

    # bump a metric version: old scores become stale, re-eval rescores from predictions
    cfg["metrics"]["accuracy"]["version"] = "v2"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    stale = hx("leaderboard", "toy-test")
    assert len(stale["needs_reeval"]) == 9
    assert len(hx("reeval", "--task", "toy-test")["evaluated"]) == 9
    board = hx("leaderboard", "toy-test")
    assert board["metric_versions"]["accuracy"] == "v2"
    assert all(r["n"] == 3 and r["primary"] is not None for r in board["rows"])

    best = board["rows"][0]
    detail = hx("show", best["latest_run_id"])
    versions = {s["version"] for s in detail["scores"] if s["metric"] == "accuracy"}
    assert versions == {"v1", "v2"}
    assert detail["paths"]["dataset:toyset"].endswith("data/test.jsonl")
    assert any(k.startswith("artifact:checkpoint") for k in detail["paths"])

    cmp = hx("compare", *best["run_ids"][:2])
    assert cmp["fields"]["seed"] != [None, None]

    # exact rerun and re-infer-free re-score of one run
    child = hx("rerun", best["latest_run_id"], "--foreground")
    assert child["status"] == "finished" and child["parent"] == best["latest_run_id"]

    # the index is disposable: delete it, rebuild, get the same leaderboard
    before = hx("leaderboard", "toy-test")
    for path in home.glob("index.db*"):
        path.unlink()
    hx("reindex")
    assert hx("leaderboard", "toy-test") == before
