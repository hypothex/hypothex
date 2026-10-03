import os
import resource
import sys
import threading
import time
from pathlib import Path

import pytest

from hypothex.core import execution
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.execution import RunRequest, execute_run, prepare_run, seed_warning
from hypothex.core.records import RunStatus, UsageTotals
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


def _warning_events(ctx: Context, run_id: str) -> list:
    return [e for e in ctx.events.since(0) if e.run_id == run_id and e.type == "run.warning"]


def test_seed_warning_none_when_field_present() -> None:
    assert seed_warning(["python", "train.py", "--seed", "{seed}"], 3) is None
    assert seed_warning(["python", "train.py", "--seed={seed}"], 3) is None


def test_seed_warning_none_when_seed_is_none() -> None:
    assert seed_warning(["python", "train.py", "--seed"], None) is None


def test_seed_warning_message_when_seed_dropped() -> None:
    msg = seed_warning(["python", "train.py", "--seed"], 3)
    assert msg is not None
    assert "{seed}" in msg
    assert "HYPOTHEX_SEED" in msg
    assert "hx.seed()" in msg


def test_prepare_run_emits_seed_warning_when_not_templated(ctx: Context, toy_repo: Path) -> None:
    rec = prepare_run(
        ctx, RunRequest(repo=toy_repo, command=cmd("pass", "--seed"), seed=7, hypothesis="x")
    )
    warnings = _warning_events(ctx, rec.run_id)
    assert len(warnings) == 1
    assert "{seed}" in warnings[0].payload["message"]


def test_prepare_run_no_warning_when_seed_templated(ctx: Context, toy_repo: Path) -> None:
    rec = prepare_run(
        ctx, RunRequest(repo=toy_repo, command=cmd("pass", "{seed}"), seed=7, hypothesis="x")
    )
    assert _warning_events(ctx, rec.run_id) == []


def test_prepare_run_no_warning_when_seed_is_none(ctx: Context, toy_repo: Path) -> None:
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), hypothesis="x"))
    assert _warning_events(ctx, rec.run_id) == []


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


USAGE = (
    "import sys, hypothex as hx; r = hx.current(); "
    "r.log_usage(tokens_in=100, tokens_out=20, usd=0.25, seconds=1.5, example_id='a'); "
    "r.log_usage(tokens_in=50, tokens_out=5, usd=0.125, seconds=0.5); "
    "sys.exit(int(sys.argv[1]))"
)


def test_usage_is_summed_into_the_record(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(USAGE, "0")))
    # 0.25 + 0.125 and 1.5 + 0.5 are exact in binary floating point.
    expected = UsageTotals(tokens_in=150, tokens_out=25, usd=0.375, seconds=2.0, calls=2)
    assert done.status == RunStatus.FINISHED and done.usage == expected
    assert ctx.store.read_record("toy", done.run_id).usage == expected


def test_failed_run_still_records_usage(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(USAGE, "2")))
    assert done.status == RunStatus.FAILED and done.usage is not None
    assert (done.usage.calls, done.usage.usd) == (2, 0.375)


def test_run_without_usage_has_none(ctx: Context, toy_repo: Path) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd("print(1)")))
    assert done.usage is None


def test_checkpoints_keep_step_and_metrics(ctx: Context, toy_repo: Path, tmp_path: Path) -> None:
    code = (
        "import sys, hypothex as hx; r = hx.current(); "
        "r.log_checkpoint(sys.argv[1], step=100, metrics={'val_top1': 0.5}); "
        "r.log_checkpoint(sys.argv[2], step=100, metrics={'val_top1': 0.5}); "
        "r.log_checkpoint(sys.argv[2], step=200, metrics={'val_top1': 0.75})"
    )
    step_100, last = tmp_path / "step_100.pt", tmp_path / "last.pt"
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(code, str(step_100), str(last))))
    assert [(a.kind, a.path, a.step, a.metrics) for a in done.artifacts] == [
        ("checkpoint", str(step_100.resolve()), 100, {"val_top1": 0.5}),
        ("checkpoint", str(last.resolve()), 200, {"val_top1": 0.75}),  # latest entry wins
    ]


# review fixes -----------------------------------------------------------------------------
NON_FINITE = (
    "import os; d = os.environ['HYPOTHEX_RUN_DIR']; f = open(d + '/metrics.jsonl', 'a'); "
    'f.write(\'{"name": "loss", "step": 1, "value": 0.5}\\n\'); '
    'f.write(\'{"name": "loss", "step": 2, "value": NaN}\\n\'); '
    'f.write(\'{"name": "loss", "step": 3, "value": Infinity}\\n\'); print(\'trained\')'
)


def test_non_finite_metric_values_do_not_break_the_run_or_the_index(
    ctx: Context, toy_repo: Path
) -> None:
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(NON_FINITE)))
    assert done.status == RunStatus.FINISHED and done.exit_code == 0 and done.ended_at
    assert [(p.step, p.value) for p in ctx.index.metric_points(done.run_id)] == [(1, 0.5)]
    ctx.layout.index_db.unlink()
    reopened = Context.open(ctx.layout.home)
    assert reopened.index.get_run(done.run_id) is not None
    assert [p.value for p in reopened.index.metric_points(done.run_id)] == [0.5]


def test_index_refresh_failure_still_finishes_the_run(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("index is broken")

    monkeypatch.setattr(ctx.index, "replace_metric_points", boom)
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd("print(1)")))
    assert done.status == RunStatus.FINISHED and done.exit_code == 0
    warnings = [e.payload["message"] for e in _warning_events(ctx, done.run_id)]
    assert any("index is broken" in w for w in warnings)


def test_background_process_left_running_does_not_hold_the_run(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core import execution

    monkeypatch.setattr(execution, "PUMP_DRAIN_SECONDS", 0.5)
    start = time.monotonic()
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=["sh", "-c", "sleep 30 & echo main-done"]))
    try:
        assert time.monotonic() - start < 10
        assert done.status == RunStatus.FINISHED and done.exit_code == 0
        assert (ctx.run_dir(done) / "logs" / "stdout.log").read_text().strip() == "main-done"
        warnings = [e.payload["message"] for e in _warning_events(ctx, done.run_id)]
        assert any("still open" in w for w in warnings)
    finally:
        execution.terminate_group(done.executor.child_pid or 0, grace=1)


@pytest.mark.parametrize("name", ["run_dir", "run_id", "repo", "task", "seed", "dataset.path"])
def test_vars_cannot_override_hypothex_template_values(
    ctx: Context, toy_repo: Path, name: str
) -> None:
    req = RunRequest(repo=toy_repo, command=cmd("print(1)"), vars={name: "/elsewhere"})
    with pytest.raises(RunError, match=f"{name} is set by Hypothex"):
        prepare_run(ctx, req)
    assert ctx.store.list_run_ids() == {}


def test_checkpoint_var_is_still_allowed(ctx: Context, toy_repo: Path) -> None:
    req = RunRequest(
        repo=toy_repo, command=cmd("print(1)", "{checkpoint}"), vars={"checkpoint": "x"}
    )
    assert prepare_run(ctx, req).command[-1] == "x"


def test_unexpected_eval_error_is_recorded_as_eval_skipped(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core import execution

    def malformed(*args: object, **kwargs: object) -> None:
        raise KeyError("results")

    monkeypatch.setattr(execution, "evaluate_run", malformed)
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(WRITE_PREDS), task="toy-acc"))
    assert done.status == RunStatus.FINISHED
    skipped = [e for e in ctx.events.since(0) if e.type == "run.eval_skipped"]
    assert skipped and "results" in skipped[0].payload["reason"]


def test_pump_reads_a_pipe_on_a_file_descriptor_above_1024(tmp_path: Path) -> None:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    high = 1500
    if soft <= high:
        if hard != resource.RLIM_INFINITY and hard <= high:
            pytest.skip("cannot open a file descriptor above 1024")
        resource.setrlimit(resource.RLIMIT_NOFILE, (high + 1, hard))
    r, w = os.pipe()
    try:
        os.dup2(r, high)
        os.close(r)
        src = os.fdopen(high, "rb", buffering=0)
        log = tmp_path / "out.log"
        thread = execution._pump(src, log, None, threading.Event())
        os.write(w, b"hello\n")
        os.close(w)
        w = -1
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert log.read_bytes() == b"hello\n"
        src.close()
    finally:
        if w >= 0:
            os.close(w)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
