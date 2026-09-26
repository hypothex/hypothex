import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hypothex.cli.main import app, cli
from hypothex.core.errors import RunError
from tests.factories import write_toy_project

runner = CliRunner()
PY = sys.executable
WRITE_PREDS = (
    "import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
    "open(d + '/predictions/predictions.jsonl', 'w').write(''.join("
    "json.dumps(dict(id='ex-' + str(i), prediction=i % 2)) + chr(10) for i in range(4)))"
)


def hx(*args: str) -> dict | list:
    argv = list(args)
    argv.insert(argv.index("--") if "--" in argv else len(argv), "--json")
    result = runner.invoke(app, argv, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


@pytest.fixture
def in_repo(toy_repo: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(toy_repo)
    return toy_repo


def _run(seed: int = 1, code: str = WRITE_PREDS) -> dict:
    out = hx("run", "-t", "toy-acc", "-H", "baseline", "--seed", str(seed), "--", PY, "-c", code)
    assert isinstance(out, dict)
    return out


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and result.stdout.strip()


def test_init_refuses_overwrite(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    out = hx("init", "--project", "demo")
    assert Path(out["path"]).read_text().startswith("# Hypothex project file")
    with pytest.raises(RunError, match="exists"):
        runner.invoke(app, ["init"], catch_exceptions=False)


def test_validate_ok(in_repo: Path) -> None:
    assert hx("validate")["ok"] is True


def test_run_json_status_and_exit_code(in_repo: Path) -> None:
    out = _run()
    assert out["status"] == "finished" and out["task"] == "toy-acc"
    result = runner.invoke(app, ["run", "--json", "--", PY, "-c", "raise SystemExit(3)"])
    assert result.exit_code == 3
    assert json.loads(result.stdout)["status"] == "failed"


def test_read_commands(in_repo: Path) -> None:
    a = _run(1)
    b = _run(2)
    board = hx("leaderboard", "toy-acc")
    assert len(board["rows"]) == 1 and board["rows"][0]["n"] == 2
    assert {r["run_id"] for r in hx("runs")} == {a["run_id"], b["run_id"]}
    detail = hx("show", a["run_id"])
    assert detail["paths"]["repo"] == str(in_repo.resolve())
    assert hx("compare", a["run_id"], b["run_id"])["fields"]["seed"] == [1, 2]
    assert hx("tasks")[0]["project"] == "toy"
    assert hx("projects")[0]["project"] == "toy"
    assert hx("task", "show", "toy-acc")["dataset"]["name"] == "toyset"
    assert hx("predictions", a["run_id"], "--failures")["rows"][0]["id"] == "ex-3"
    assert hx("examples", a["run_id"], b["run_id"], "--metric", "accuracy")["both_pass"] == 3
    assert "text" in hx("logs", a["run_id"])


def test_reeval_after_version_bump(in_repo: Path) -> None:
    _run()
    write_toy_project(in_repo, accuracy_version="v2")
    assert len(hx("leaderboard", "toy-acc")["needs_reeval"]) == 1
    assert len(hx("reeval", "--task", "toy-acc")["evaluated"]) == 1
    assert hx("leaderboard", "toy-acc")["metric_versions"] == {"accuracy": "v2"}


def test_curation_commands(in_repo: Path) -> None:
    rid = _run()["run_id"]
    assert hx("tag", rid, "--add", "ablation")["tags"] == ["ablation"]
    assert hx("star", rid)["starred"] is True
    hx("note", rid, "works")
    assert "works" in hx("show", rid)["notes"]
    assert hx("archive", rid)["archived"] is True
    assert hx("runs") == []


def test_launch_wait_and_rerun(in_repo: Path) -> None:
    out = hx("launch", "--wait", "-H", "bg", "--", PY, "-c", "print('bg')")
    assert out["status"] == "finished"
    child = hx("rerun", out["run_id"], "--foreground")
    assert child["parent"] == out["run_id"] and child["status"] == "finished"


def test_agent_requires_hypothesis(in_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPOTHEX_AGENT", "claude")
    with pytest.raises(RunError, match="hypothesis"):
        runner.invoke(app, ["run", "--", PY, "-c", "pass"], catch_exceptions=False)


def test_reindex_and_repair_and_datasets(in_repo: Path) -> None:
    _run()
    assert hx("reindex")["runs"] == 1
    assert hx("repair")["lost"] == []
    assert [d["status"] for d in hx("datasets", "check")] == ["ok"]
    assert hx("datasets", "overlap", "toy", "toyset")["pairs"] == {}


def test_cli_errors_are_json(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["hx", "show", "nope", "--json"])
    with pytest.raises(SystemExit) as exc:
        cli()
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["type"] == "RunNotFoundError"
