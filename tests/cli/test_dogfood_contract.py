"""CLI regressions for the user-visible dogfood contracts."""

import json
import os
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import typer
import yaml
from sqlalchemy.exc import DBAPIError
from typer.testing import CliRunner

import hypothex.cli.main as main
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.records import RunStatus, ScoreRecord
from tests.factories import make_record, seed_finished_run

runner = CliRunner()


@pytest.mark.parametrize("command", ["run", "launch"])
@pytest.mark.parametrize("stage", [True, False])
def test_stage_cwd_uses_repo_but_raw_command_keeps_subdirectory(
    command: str, stage: bool, ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = toy_repo / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    seen: list[main.RunRequest] = []
    rec = make_record("r1", status=RunStatus.FINISHED, exit_code=0)

    def capture(c: Context, request: main.RunRequest) -> Any:
        seen.append(request)
        return rec

    monkeypatch.setattr(main, "prepare_run", capture)
    monkeypatch.setattr(main, "launch_run", capture)
    monkeypatch.setattr(main, "execute_run", lambda *a, **kw: rec)
    args = [command, "--json"] + (["--stage", "infer"] if stage else ["--", "echo", "hi"])
    result = runner.invoke(main.app, args, catch_exceptions=False)
    assert result.exit_code == 0
    assert seen[0].repo == toy_repo.resolve()
    assert seen[0].cwd == (None if stage else nested)


@pytest.mark.parametrize("force", [False, True])
def test_init_rejects_invalid_names_without_writing(
    force: bool, tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    args = ["init", "--project", "Not Valid"] + (["--force"] if force else [])
    with pytest.raises(RunError, match="project name"):
        runner.invoke(main.app, args, catch_exceptions=False)
    assert not (tmp_path / "hypothex.yaml").exists()


def test_nested_init_requires_force(
    toy_repo: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = toy_repo / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    with pytest.raises(RunError, match="parent project"):
        runner.invoke(main.app, ["init"], catch_exceptions=False)
    assert not (nested / "hypothex.yaml").exists()
    result = runner.invoke(
        main.app, ["init", "--force", "--project", "child"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert yaml.safe_load((nested / "hypothex.yaml").read_text())["project"] == "child"


@pytest.mark.parametrize(("code", "expected"), [(-15, 143), (-2, 130), (7, 7), (None, 1)])
def test_finish_maps_signal_exit_codes(
    code: int | None, expected: int, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main._state, "home", home)
    rec = make_record(status=RunStatus.KILLED, exit_code=code)
    with pytest.raises(typer.Exit) as caught:
        main._finish(rec, False)
    assert caught.value.exit_code == expected


def test_show_prints_metadata_and_last_error_line(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1", seed=13)
    ctx.update_run(
        "r1",
        "test.metadata",
        lambda r: r.model_copy(
            update={
                "tags": ["ablation"],
                "params": {"lr": "0.01"},
                "vars": {"temperature": "2"},
                "parent": "parent-run",
                "starred": True,
                "exit_code": 0,
                "started_at": r.created_at,
                "ended_at": r.created_at,
            }
        ),
    )
    child = make_record("child-run", parent="r1", environment_id=ctx.descriptor.environment_id)
    ctx.create_run(child)
    ctx.store.append_note(rec.project, rec.run_id, "Remember this result", author="researcher")
    ctx.store.append_score(
        rec.project,
        rec.run_id,
        ScoreRecord(
            metric="accuracy",
            version="v1",
            key="value",
            error="Traceback:\n  call()\nValueError: bad data\n\n",
            created_at=rec.created_at,
        ),
    )
    monkeypatch.setattr(main, "_hub_read", lambda *a: None)
    result = runner.invoke(main.app, ["show", "r1"], catch_exceptions=False)
    for text in [
        "Remember this result",
        "ablation",
        "seed:",
        "13",
        "lr",
        "0.01",
        "temperature",
        "parent-run",
        "child-run",
        "starred:",
        "exit code:",
        "created:",
        "started:",
        "ended:",
        "ValueError: bad data",
    ]:
        assert text in result.stdout
    assert "Traceback:" not in result.stdout


@pytest.mark.parametrize("as_json", [False, True])
def test_successful_process_reports_evaluation_errors_on_stderr(
    as_json: bool, home: Path, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(toy_repo)
    code = (
        "import os; open(os.environ['HYPOTHEX_RUN_DIR'] + "
        "'/predictions/predictions.jsonl', 'w').write('')"
    )
    args = ["run", "-t", "toy-broken"] + (["--json"] if as_json else [])
    result = runner.invoke(
        main.app, [*args, "--", sys.executable, "-c", code], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert "eval: 1 errors" in result.stderr
    if as_json:
        assert json.loads(result.stdout)["status"] == "finished"


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.KILLED, RunStatus.LOST])
def test_default_failed_logs_include_stderr_but_explicit_stdout_and_json_do_not(
    status: RunStatus, ctx: Context, toy_repo: Path
) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    ctx.update_run("r1", "test.failed", lambda r: r.model_copy(update={"status": status}))
    (ctx.run_dir(rec) / "logs" / "stdout.log").write_text("out\n")
    (ctx.run_dir(rec) / "logs" / "stderr.log").write_text("ValueError: failure\n")
    out = runner.invoke(main.app, ["logs", "r1"], catch_exceptions=False)
    assert out.stdout == "out\n-- stderr --\nValueError: failure\n"
    explicit = runner.invoke(main.app, ["logs", "r1", "--stream", "stdout"], catch_exceptions=False)
    assert explicit.stdout == "out\n"
    as_json = runner.invoke(main.app, ["logs", "r1", "--json"], catch_exceptions=False)
    assert json.loads(as_json.stdout)["text"] == "out\n"


def test_finished_default_logs_do_not_append_stderr(ctx: Context, toy_repo: Path) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    (ctx.run_dir(rec) / "logs" / "stderr.log").write_text("debug\n")
    assert runner.invoke(main.app, ["logs", "r1"], catch_exceptions=False).stdout == ""


def test_text_dates_are_local_but_json_stays_utc(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    created = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    ctx.update_run("r1", "test.time", lambda r: r.model_copy(update={"created_at": created}))
    monkeypatch.setattr(main, "_hub_read", lambda *a: None)
    monkeypatch.setattr(
        main.q,
        "list_sweeps",
        lambda *a: [
            {
                "id": "s1",
                "project": "toy",
                "task": "t",
                "host": None,
                "created_at": created,
                "n_runs": 0,
                "best": None,
            }
        ],
    )
    prior = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Asia/Kolkata"
        time.tzset()
        for command in ["runs", "sweeps"]:
            text = runner.invoke(main.app, [command], catch_exceptions=False)
            assert "2026-01-02 17:30" in text.stdout
            payload = runner.invoke(main.app, [command, "--json"], catch_exceptions=False)
            assert json.loads(payload.stdout)[0]["created_at"] == "2026-01-02T12:00:00Z"
    finally:
        if prior is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = prior
        time.tzset()
    assert rec.run_id == "r1"


@pytest.mark.parametrize(
    "error",
    [
        OSError("read-only home"),
        sqlite3.DatabaseError("database broken"),
        DBAPIError(None, None, Exception("db refused")),
        json.JSONDecodeError("bad json", "x", 0),
    ],
)
@pytest.mark.parametrize("as_json", [False, True])
def test_console_entry_reports_startup_storage_errors(
    error: Exception,
    as_json: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> None:
        raise error

    monkeypatch.setattr(main, "app", fail)
    monkeypatch.setattr(sys, "argv", ["hx", "runs"] + (["--json"] if as_json else []))
    with pytest.raises(SystemExit) as caught:
        main.cli()
    assert caught.value.code == 1
    captured = capsys.readouterr()
    if as_json:
        payload = json.loads(captured.out)
        assert payload["type"] == type(error).__name__ and payload["error"]
    else:
        assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.out + captured.err


@pytest.mark.parametrize("p", [0.000001, 0.26, None])
def test_leaderboard_shows_test_uncertainty_and_identical_seed_marker(
    p: float | None, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core.leaderboard import NoiseInterval
    from tests.core.test_headlines import board, row, welch

    candidate = row(
        "candidate",
        [0.5, 0.5, 0.5],
        vs=welch(-0.1, p),
        ti=NoiseInterval(lo=0.2, hi=0.8, method="wilson", n=10),
    )
    candidate.within_noise_of_best = None if p is None else p >= 0.05
    ranked = board("generic", [row("best", [0.6, 0.6, 0.6]), candidate])
    monkeypatch.setattr(main, "_board", lambda *a: ranked)
    result = runner.invoke(main.app, ["leaderboard", "toy-test"], catch_exceptions=False)
    assert "test 95%" in result.stdout and "◇×3" in result.stdout
    assert "[0.2000, 0.8000]" in result.stdout and "± 0.0000" not in result.stdout
    if p is not None:
        assert ("p < 0.001" if p < 0.001 else "p = 0.26") in result.stdout
        assert ("within noise" in result.stdout) is (p >= 0.05)
    else:
        assert "within noise" not in result.stdout


def test_cli_exposes_stored_metric_source_drift(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.core.test_headlines import board

    ranked = board("generic", [])
    ranked.metric_drift = ["accuracy@v1"]
    monkeypatch.setattr(main, "_board", lambda *a: ranked)
    result = runner.invoke(main.app, ["leaderboard", "toy-test"], catch_exceptions=False)
    assert "accuracy@v1" in result.stdout and "different recorded source hashes" in result.stdout


def test_show_exposes_persisted_end_reason_after_reopen(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1")
    ctx.update_run(
        "r1",
        "run.lost",
        lambda r: r.model_copy(
            update={"status": RunStatus.LOST, "end_reason": "supervisor vanished"}
        ),
    )
    result = runner.invoke(main.app, ["show", "r1"], catch_exceptions=False)
    assert "end reason: supervisor vanished" in result.stdout
    result = runner.invoke(main.app, ["show", "r1", "--json"], catch_exceptions=False)
    assert json.loads(result.stdout)["record"]["end_reason"] == "supervisor vanished"


def test_followed_failure_appends_stderr_on_its_own_line(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    ctx.update_run(
        "r1", "test.running", lambda r: r.model_copy(update={"status": RunStatus.RUNNING})
    )
    (ctx.run_dir(rec) / "logs" / "stdout.log").write_text("partial stdout")
    (ctx.run_dir(rec) / "logs" / "stderr.log").write_text("traceback\n")
    monkeypatch.setattr(
        main.time,
        "sleep",
        lambda _: ctx.update_run(
            "r1", "test.failed", lambda r: r.model_copy(update={"status": RunStatus.FAILED})
        ),
    )
    result = runner.invoke(main.app, ["logs", "r1", "--follow"], catch_exceptions=False)
    assert result.stdout == "partial stdout\n-- stderr --\ntraceback\n"


def test_finish_reports_score_errors_without_opening_shared_databases(
    ctx: Context,
    toy_repo: Path,
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    ctx.store.append_score(
        "toy",
        "r1",
        ScoreRecord(metric="m", version="v1", key="*", error="failed", created_at=rec.created_at),
    )
    monkeypatch.setattr(main._state, "home", home)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("finishing a SLURM child must not open the shared databases")

    monkeypatch.setattr(Context, "open", forbidden)
    main._finish(rec, False)
    assert "eval: 1 errors" in capsys.readouterr().err
