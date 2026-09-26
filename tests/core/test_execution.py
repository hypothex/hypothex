import sys
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.execution import RunRequest, execute_run, prepare_run
from hypothex.core.records import RunStatus
from tests.factories import write_toy_project

PY = sys.executable
WRITE_PREDS = (
    "import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
    "open(d + '/predictions/predictions.jsonl', 'w').write(''.join("
    "json.dumps(dict(id='ex-' + str(i), prediction=i % 2)) + chr(10) for i in range(4)))"
)


def cmd(code: str, *args: str) -> list[str]:
    return [PY, "-c", code, *args]


def run_fg(ctx: Context, req: RunRequest):
    return execute_run(ctx, prepare_run(ctx, req).run_id)


def test_foreground_run_finishes_with_logs(ctx: Context, toy_repo: Path) -> None:
    code = "import sys; print('hello'); print('warn', file=sys.stderr)"
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd(code), hypothesis="smoke"))
    assert rec.status == RunStatus.QUEUED and rec.git.commit and rec.hypothesis == "smoke"
    done = execute_run(ctx, rec.run_id)
    assert done.status == RunStatus.FINISHED and done.exit_code == 0
    run_dir = ctx.run_dir(done)
    assert (run_dir / "logs" / "stdout.log").read_text().strip() == "hello"
    assert "warn" in (run_dir / "logs" / "stderr.log").read_text()
    assert (run_dir / "env" / "system.json").is_file()
    types = [e.type for e in ctx.events.since(0) if e.run_id == rec.run_id]
    assert types == ["run.created", "run.started", "run.finished"]


def test_failing_command_is_failed(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd("raise SystemExit(3)")))
    assert done.status == RunStatus.FAILED and done.exit_code == 3


def test_missing_command_fails_before_run_dir(ctx: Context, toy_repo: Path) -> None:
    with pytest.raises(RunError, match="command not found"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=["definitely-not-a-command-xyz"]))
    assert ctx.store.list_run_ids() == {}


def test_bad_task_and_missing_template_var(ctx: Context, toy_repo: Path) -> None:
    with pytest.raises(RunError, match="unknown task"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), task="nope"))
    with pytest.raises(RunError, match="checkpoint"):
        prepare_run(ctx, RunRequest(repo=toy_repo, stage="infer"))
    assert ctx.store.list_run_ids() == {}


def test_task_run_auto_evaluates(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(WRITE_PREDS), task="toy-acc"))
    scores = ctx.store.read_scores("toy", done.run_id)
    assert [(s.metric, s.value) for s in scores] == [("accuracy", 0.75)]
    assert done.datasets[0].name == "toyset" and done.datasets[0].hash_mode == "full"


def test_task_run_without_predictions_finishes_unscored(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd("print(1)"), task="toy-acc"))
    assert done.status == RunStatus.FINISHED
    assert ctx.store.read_scores("toy", done.run_id) == []
    skipped = [e for e in ctx.events.since(0) if e.type == "run.eval_skipped"]
    assert skipped and "predictions" in skipped[0].payload["reason"]


def test_seed_template_and_seed_group_hash(ctx: Context, toy_repo: Path) -> None:
    code = "import os, sys; print(sys.argv[1], os.environ['HYPOTHEX_SEED'])"
    a = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(code, "{seed}"), seed=1))
    b = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(code, "{seed}"), seed=2))
    assert a.command[-1] == "1" and b.command[-1] == "2"
    assert a.config_hash == b.config_hash
    assert (ctx.run_dir(b) / "logs" / "stdout.log").read_text().strip() == "2 2"


def test_non_git_repo_runs(ctx: Context, tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "plain", use_git=False)
    done = run_fg(ctx, RunRequest(repo=repo, command=cmd("print(1)")))
    assert done.status == RunStatus.FINISHED and done.git.commit is None


def test_config_file_is_copied(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text("lr: 0.1\nseed: 1\n")
    done = run_fg(
        ctx,
        RunRequest(
            repo=toy_repo,
            command=cmd("import sys; print(open(sys.argv[1]).read())", "{config}"),
            config_path=cfg,
        ),
    )
    assert "lr: 0.1" in (ctx.run_dir(done) / "config.yaml").read_text()
    assert "lr: 0.1" in (ctx.run_dir(done) / "logs" / "stdout.log").read_text()


def test_agent_requires_hypothesis(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYPOTHEX_AGENT", "claude")
    with pytest.raises(RunError, match="hypothesis"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass")))


def test_logged_artifacts_and_metrics_are_ingested(ctx: Context, toy_repo: Path) -> None:
    code = (
        "import json, os; d = os.environ['HYPOTHEX_RUN_DIR']; "
        "open(d + '/artifacts.jsonl', 'a').write(json.dumps("
        "{'kind': 'checkpoint', 'path': '/tmp/m.pt'}) + '\\n'); "
        "open(d + '/metrics.jsonl', 'a').write(json.dumps("
        "{'name': 'loss', 'step': 0, 'value': 1.0}) + '\\n')"
    )
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(code)))
    assert [(a.kind, a.path) for a in done.artifacts] == [("checkpoint", "/tmp/m.pt")]
    assert [p.name for p in ctx.index.metric_points(done.run_id)] == ["loss"]
    assert "checkpoint" in (ctx.run_dir(done) / "run.yaml").read_text()
