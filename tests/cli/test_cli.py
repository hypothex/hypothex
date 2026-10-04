import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from hypothex.cli.main import app, cli
from hypothex.core.config import load_project_config
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, RunError
from hypothex.core.views import load_preset
from hypothex.demo import DEMO_TASKS
from tests.factories import write_toy_project

runner = CliRunner()
PY = sys.executable
WRITE_PREDS = (
    "import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
    "open(d + '/predictions/predictions.jsonl', 'w').write(''.join("
    "json.dumps(dict(id='ex-' + str(i), prediction=i % 2)) + chr(10) for i in range(4)))"
)
GOOD_VIEW = """\
title: acc only
panels:
  - type: leaderboard
    title: board
    data: {metrics: [accuracy]}
"""
# "acuracy" is one letter off; difflib.get_close_matches("acuracy", ["accuracy"]) ->
# ["accuracy"]. The bad name sits on line 5 (1-based) of the text.
BAD_VIEW = GOOD_VIEW.replace("[accuracy]", "[acuracy]")


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


def test_run_warns_on_stderr_when_seed_is_dropped(in_repo: Path) -> None:
    result = runner.invoke(app, ["run", "--json", "--seed", "1", "--", PY, "-c", "pass"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "finished"
    assert "warning:" in result.stderr
    assert "{seed}" in result.stderr


def test_run_no_seed_warning_when_seed_is_templated(in_repo: Path) -> None:
    result = runner.invoke(app, ["run", "--json", "--seed", "1", "--", PY, "-c", "pass", "{seed}"])
    assert result.exit_code == 0
    assert "warning:" not in result.stderr


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


def test_view_commands(in_repo: Path) -> None:
    _run()
    views_dir = in_repo.resolve() / ".hypothex" / "views" / "toy-acc"
    assert [(v["name"], v["origin"]) for v in hx("view", "list", "toy-acc")] == [
        ("overview", "preset")
    ]

    made = hx("view", "init", "toy-acc", "--from", "generic", "--name", "mine")
    assert made["info"]["path"] == str(views_dir / "mine.yaml")
    shown = hx("view", "show", "toy-acc", "mine")
    assert yaml.safe_load(shown["text"]) == {"title": "mine", "from": "generic", "panels": []}
    assert [p["type"] for p in shown["view"]["panels"]] == [
        p.type for p in load_preset("generic").panels
    ]
    with pytest.raises(ConfigError, match="exists"):
        runner.invoke(
            app,
            ["view", "init", "toy-acc", "--from", "generic", "--name", "mine"],
            catch_exceptions=False,
        )

    good = in_repo / "acc.yaml"
    good.write_text(GOOD_VIEW)
    assert hx("view", "validate", "toy-acc", str(good))["ok"] is True
    added = hx("view", "add", "toy-acc", "--file", str(good))
    assert (added["info"]["name"], added["info"]["title"]) == ("acc", "acc only")
    assert (views_dir / "acc.yaml").read_text() == GOOD_VIEW
    assert hx("view", "add", "toy-acc", "--file", str(good), "--name", "other")["info"][
        "path"
    ] == str(views_dir / "other.yaml")
    assert hx("view", "show", "toy-acc", "acc")["text"] == GOOD_VIEW
    assert [v["name"] for v in hx("view", "list", "toy-acc")] == [
        "overview",
        "acc",
        "mine",
        "other",
    ]

    assert hx("view", "rm", "toy-acc", "acc") == {"ok": True}
    assert not (views_dir / "acc.yaml").exists()
    text = runner.invoke(app, ["view", "show", "toy-acc", "other"], catch_exceptions=False)
    assert text.exit_code == 0 and text.stdout == GOOD_VIEW


def test_view_validate_reports_issues_and_exits_1(in_repo: Path) -> None:
    _run()
    bad = in_repo / "bad.yaml"
    bad.write_text(BAD_VIEW)
    result = runner.invoke(app, ["view", "validate", "toy-acc", str(bad), "--json"])
    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert (report["issues"][0]["line"], report["issues"][0]["suggestion"]) == (5, "accuracy")
    human = runner.invoke(app, ["view", "validate", "toy-acc", str(bad)])
    assert (
        human.exit_code == 1
        and "line 5" in human.stdout
        and "did you mean accuracy" in human.stdout
    )


def test_view_show_reports_an_inline_view_with_anchors_cleanly(
    in_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run()
    config_path = in_repo / "hypothex.yaml"
    cfg = yaml.safe_load(config_path.read_text())
    spec: dict = {"mark": "point"}
    spec["layer"] = [spec]  # safe_dump writes the loop as &id001 ... *id001
    cfg["tasks"]["toy-acc"]["views"] = {
        "loop": {"title": "loop", "panels": [{"type": "vega_lite", "spec": spec}]}
    }
    text = yaml.safe_dump(cfg, sort_keys=False)
    config_path.write_text(text)
    line = next(i for i, row in enumerate(text.splitlines(), 1) if "&id001" in row)
    monkeypatch.setattr(sys, "argv", ["hx", "view", "show", "toy-acc", "loop", "--json"])
    with pytest.raises(SystemExit) as exc:
        cli()
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["type"] == "ConfigError"
    assert f"YAML anchors and aliases are not allowed in views (line {line})" in err["error"]


def test_view_add_invalid_is_not_saved_and_reports_issues(
    in_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run()
    bad = in_repo / "bad.yaml"
    bad.write_text(BAD_VIEW)
    monkeypatch.setattr(sys, "argv", ["hx", "view", "add", "toy-acc", "--file", str(bad), "--json"])
    with pytest.raises(SystemExit) as exc:
        cli()
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["type"] == "ViewValidationError"
    assert err["issues"][0]["suggestion"] == "accuracy"
    assert not (in_repo / ".hypothex" / "views" / "toy-acc" / "bad.yaml").exists()
    with pytest.raises(ConfigError, match="invalid view"):
        runner.invoke(
            app,
            ["view", "init", "toy-acc", "--from", "nope", "--name", "x"],
            catch_exceptions=False,
        )
    assert not (in_repo / ".hypothex" / "views" / "toy-acc" / "x.yaml").exists()


def test_demo_is_hidden_and_seeds(home: Path) -> None:
    assert "demo" not in runner.invoke(app, ["--help"]).stdout
    out = hx("demo", "--kinds", "generic")
    assert isinstance(out, dict) and list(out) == ["generic"]
    refs = {f"{t['project']}/{t['name']}" for t in hx("tasks")}
    assert out["generic"] in refs
    with pytest.raises(ConfigError, match="nope"):
        runner.invoke(app, ["demo", "--kinds", "generic,nope"], catch_exceptions=False)


def test_demo_refuses_a_home_with_real_projects(in_repo: Path) -> None:
    _run()
    with pytest.raises(ConfigError, match=r"already has projects \(toy\)"):
        runner.invoke(app, ["demo", "--kinds", "generic"], catch_exceptions=False)
    assert [p["project"] for p in hx("projects")] == ["toy"]


def test_demo_refuses_a_real_project_with_a_demo_name(home: Path) -> None:
    # regression: the guard matched demo projects by name, and the repo's own example
    # is also "toy-classifier", so the demo was seeded next to the user's real project
    example = Path(__file__).resolve().parents[2] / "examples" / "toy-classifier"
    config = load_project_config(example)
    assert config.project == DEMO_TASKS["generic"][0]
    Context.open(home).store.register_project(config, example)
    with pytest.raises(ConfigError, match=r"already has projects \(toy-classifier\)"):
        runner.invoke(app, ["demo", "--kinds", "training"], catch_exceptions=False)
    assert [p["project"] for p in hx("projects")] == ["toy-classifier"]


def test_demo_adds_kinds_to_a_demo_home(home: Path) -> None:
    # projects whose repo is under <home>/demo-repos/ are the demo's own
    hx("demo", "--kinds", "generic")
    assert list(hx("demo", "--kinds", "training")) == ["training"]
    assert {p["project"] for p in hx("projects")} == {
        DEMO_TASKS["generic"][0],
        DEMO_TASKS["training"][0],
    }


def test_view_list_and_show_with_a_non_utf8_file(
    in_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run()
    path = in_repo / ".hypothex" / "views" / "toy-acc" / "latin.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("title: café\npanels: []\n".encode("latin-1"))
    assert [(v["name"], v["title"]) for v in hx("view", "list", "toy-acc")][1:] == [
        ("latin", "latin")
    ]
    monkeypatch.setattr(sys, "argv", ["hx", "view", "show", "toy-acc", "latin", "--json"])
    with pytest.raises(SystemExit) as exc:
        cli()
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["type"] == "ConfigError" and "cannot read view file" in err["error"]


@pytest.mark.parametrize("command", ["add", "validate"])
def test_view_add_and_validate_with_a_non_utf8_file(
    in_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    _run()
    path = in_repo / "latin.yaml"
    path.write_bytes("title: café\npanels: []\n".encode("latin-1"))
    target = ["--file", str(path)] if command == "add" else [str(path)]
    monkeypatch.setattr(sys, "argv", ["hx", "view", command, "toy-acc", *target, "--json"])
    with pytest.raises(SystemExit) as exc:
        cli()
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["type"] == "ConfigError" and "cannot read view file" in err["error"]
    assert not (in_repo / ".hypothex" / "views" / "toy-acc" / "latin.yaml").exists()


class _FakeUvicorn:
    """Records what ``hx serve`` would serve; binds a free port instead of the asked one."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._asked: tuple[str, int] = ("", 0)

    def listen(self, host: str, port: int) -> socket.socket:
        self._asked = (host, port)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        return sock

    def run(self, server: Any, sockets: list[socket.socket] | None = None) -> None:
        for sock in sockets or []:
            sock.close()
        host, port = self._asked
        # server.json exists only while the server runs: keep its token for the test
        info = Path(os.environ["HYPOTHEX_HOME"]) / "serve" / "server.json"
        token = json.loads(info.read_text())["token"] if info.is_file() else None
        self.calls.append({"app": server.config.app, "host": host, "port": port, "token": token})


@pytest.fixture
def fake_uvicorn(monkeypatch: pytest.MonkeyPatch) -> _FakeUvicorn:
    import uvicorn

    import hypothex.cli.main as cli_main

    fake = _FakeUvicorn()
    monkeypatch.setattr(cli_main, "_listen", fake.listen)
    monkeypatch.setattr(
        uvicorn.Server, "run", lambda server, sockets=None: fake.run(server, sockets)
    )
    monkeypatch.delenv("HYPOTHEX_SERVE_TOKEN", raising=False)
    return fake


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "myhost.example"])
def test_serve_refuses_a_non_loopback_host_without_a_token(
    home: Path, fake_uvicorn: _FakeUvicorn, host: str
) -> None:
    with pytest.raises(ConfigError) as exc:
        runner.invoke(app, ["serve", "--host", host], catch_exceptions=False)
    message = str(exc.value)
    assert host in message and "HYPOTHEX_SERVE_TOKEN" in message
    assert "arbitrary commands" in message and "ssh -L" in message
    assert fake_uvicorn.calls == []


def test_serve_on_loopback_needs_no_token(home: Path, fake_uvicorn: _FakeUvicorn) -> None:
    result = runner.invoke(app, ["serve"], catch_exceptions=False)
    assert result.exit_code == 0
    [call] = fake_uvicorn.calls
    assert call["host"] == "127.0.0.1" and call["port"] == 7777


def test_serve_with_a_token_binds_anywhere_and_enforces_it(
    home: Path, fake_uvicorn: _FakeUvicorn, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("HYPOTHEX_SERVE_TOKEN", "s3cret")
    result = runner.invoke(app, ["serve", "--host", "0.0.0.0"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "HYPOTHEX_SERVE_TOKEN" not in os.environ  # runs never inherit it
    [call] = fake_uvicorn.calls
    assert call["host"] == "0.0.0.0"
    with TestClient(call["app"], base_url="http://127.0.0.1:7777") as c:  # type: ignore[arg-type]
        assert c.get("/api/v1/runs").status_code == 401
        good = {"Authorization": "Bearer s3cret"}
        assert c.get("/api/v1/runs", headers=good).json() == []


def test_no_auth_env_server_still_refuses_a_network_bind(
    home: Path, fake_uvicorn: _FakeUvicorn
) -> None:
    with pytest.raises(ConfigError, match="without authentication"):
        runner.invoke(
            app,
            ["serve", "--host", "0.0.0.0", "--kind", "ssh", "--no-auth"],
            catch_exceptions=False,
        )
    assert fake_uvicorn.calls == []


def test_env_server_makes_a_token_when_none_is_given(
    home: Path, fake_uvicorn: _FakeUvicorn
) -> None:
    from fastapi.testclient import TestClient

    result = runner.invoke(app, ["serve", "--kind", "slurm"], catch_exceptions=False)
    assert result.exit_code == 0
    [call] = fake_uvicorn.calls
    with TestClient(call["app"], base_url="http://127.0.0.1:7777") as c:  # type: ignore[arg-type]
        assert c.get("/api/v1/runs").status_code == 401
        descriptor = "/.well-known/hypothex/environment"
        assert "kind" not in c.get(descriptor).json()  # host facts only for the token holder
        good = {"Authorization": f"Bearer {call['token']}"}
        assert c.get(descriptor, headers=good).json()["kind"] == "slurm"


def test_show_says_untracked_files_only(in_repo: Path) -> None:
    (in_repo / "scratch notes.txt").write_text("x\n")
    run_id = _run()["run_id"]
    shown = hx("show", run_id)
    assert shown["record"]["git"]["dirty"] is False
    assert shown["record"]["git"]["untracked_count"] >= 1
    text = runner.invoke(app, ["show", run_id], catch_exceptions=False).stdout
    git_line = next(line for line in text.splitlines() if line.startswith("git:"))
    assert "untracked files only (" in git_line and "dirty" not in git_line
