import hashlib
import os
import resource
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hypothex.core import execution
from hypothex.core.context import Context
from hypothex.core.errors import RemoteProjectError, RunError
from hypothex.core.execution import RunRequest, execute_run, prepare_run, seed_warning
from hypothex.core.index import rebuild_index
from hypothex.core.records import RunRecord, RunStatus, UsageTotals
from tests.factories import git, write_toy_project

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


def _ids(monkeypatch: pytest.MonkeyPatch, *ids: str) -> None:
    supply = iter(ids)
    monkeypatch.setattr(execution, "new_run_id", lambda task: next(supply))


def test_prepare_run_skips_an_id_whose_folder_exists(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass")))
    _ids(monkeypatch, first.run_id, "20260101-000000-explore-0000000b")
    again = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass")))
    assert again.run_id == "20260101-000000-explore-0000000b"
    assert ctx.find_record(first.run_id).command == first.command  # untouched


def test_prepare_run_retries_when_another_launcher_takes_the_id(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clash, fresh = "20260101-000000-explore-0000000a", "20260101-000000-explore-0000000b"
    _ids(monkeypatch, clash, fresh)
    real_git_info = execution.git_info
    taken: list[str] = []

    def git_info_racing(cwd: Path):  # runs after the id check, before create_run
        if not taken:
            other = ctx.layout.run_dir("toy", clash)
            other.mkdir(parents=True)
            taken.append(str(other))
        return real_git_info(cwd)

    monkeypatch.setattr(execution, "git_info", git_info_racing)
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass")))
    assert rec.run_id == fresh and taken
    assert ctx.index.get_run(clash) is None
    assert not any(e.run_id == clash for e in ctx.events.since(0))
    assert list(ctx.layout.run_dir("toy", clash).iterdir()) == []  # the other run's folder


def test_colliding_preparations_never_release_another_launchers_staging_checkout(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clash, fresh = "20260101-000000-explore-0000000a", "20260101-000000-explore-0000000b"
    first_joined, second_attempted = threading.Event(), threading.Event()
    first_created, loser_retried, checked = threading.Event(), threading.Event(), threading.Event()
    attempts: dict[str, int] = {}
    records: dict[str, RunRecord] = {}
    errors: dict[str, BaseException] = {}
    prepare = execution._prepare_in

    def draw(task: str | None) -> str:
        name = threading.current_thread().name
        attempts[name] = attempts.get(name, 0) + 1
        if attempts[name] == 1:
            return clash
        second_attempted.set()  # the exclusive marker can reject before _prepare_in
        loser_retried.set()
        assert checked.wait(10)
        return fresh

    def prepare_in(*args: Any, **kwargs: Any) -> RunRecord:
        name = threading.current_thread().name
        if name == "winner":
            first_joined.set()
            assert second_attempted.wait(10)
        elif args[-1] == clash:
            second_attempted.set()
            assert first_created.wait(10)
        return prepare(*args, **kwargs)

    def capture(repo: Path, env_dir: Path, python_cmd: list[str]) -> None:
        if threading.current_thread().name == "winner":
            first_created.set()  # its run folder now owns the colliding run id
            assert loser_retried.wait(10)
            try:
                assert (repo / "hypothex.yaml").is_file(), "loser removed winner's staging tree"
                assert (repo.parent / f"{repo.name}.users" / clash).is_file()
            finally:
                checked.set()

    monkeypatch.setattr(execution, "new_run_id", draw)
    monkeypatch.setattr(execution, "_prepare_in", prepare_in)
    monkeypatch.setattr(execution, "capture_env", capture)
    req = RunRequest(
        repo=toy_repo, command=cmd("pass"), commit=git(toy_repo, "rev-parse", "HEAD"), queue=True
    )

    def launch() -> None:
        name = threading.current_thread().name
        try:
            records[name] = prepare_run(ctx, req)
        except BaseException as exc:
            errors[name] = exc

    winner = threading.Thread(target=launch, name="winner")
    contender = threading.Thread(target=launch, name="contender")
    winner.start()
    assert first_joined.wait(10)
    contender.start()
    for thread in (winner, contender):
        thread.join(15)
        assert not thread.is_alive()
    assert errors == {}
    assert records["winner"].run_id == clash
    assert records["contender"].run_id == fresh
    assert ctx.find_record(clash) == records["winner"]
    users = next((ctx.layout.project_dir("toy") / execution.STAGING_DIR).glob("*.users"))
    assert {path.name for path in users.iterdir()} == {clash, fresh}


def test_prepare_run_retries_without_removing_a_racing_launchers_worktree(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The destination check must not grant cleanup rights to another launcher's tree."""
    clash, fresh = "20260101-000000-explore-0000000a", "20260101-000000-explore-0000000b"
    _ids(monkeypatch, clash, fresh)
    commit = git(toy_repo, "rev-parse", "HEAD")
    # A clean pinned commit needs a worktree when the working checkout is dirty.
    with (toy_repo / "toymetrics.py").open("a") as fh:
        fh.write("# local change\n")
    competitor = ctx.layout.worktrees_dir("toy") / clash
    real_resolve = execution._resolve_commit
    raced = False

    def resolve_racing(repo: Path, wanted: str) -> str | None:
        nonlocal raced
        if not raced:
            raced = True
            execution.create_worktree(repo, commit, competitor, None)
            (competitor / "owned.txt").write_text("other launcher")
        return real_resolve(repo, wanted)

    monkeypatch.setattr(execution, "_resolve_commit", resolve_racing)
    try:
        rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass"), commit=commit))
    finally:
        assert (competitor / "owned.txt").is_file(), "another launcher's worktree was removed"
    assert rec.run_id == fresh
    assert (competitor / "owned.txt").read_text() == "other launcher"
    assert str(competitor) in git(toy_repo, "worktree", "list", "--porcelain")


def test_prepare_run_gives_up_after_run_id_attempts(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass")))
    monkeypatch.setattr(execution, "new_run_id", lambda task: first.run_id)
    with pytest.raises(RunError, match="free run id"):
        prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass")))


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


@pytest.mark.parametrize("exit_code", [0, 1])
def test_local_end_indexes_exact_history_after_an_intervening_rebuild(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    code = (
        "import json,os; p=os.environ['HYPOTHEX_RUN_DIR']+'/metrics.jsonl'; "
        "open(p,'w').write(''.join(json.dumps(dict(name=f'm{i:03d}',step=0,value=float(i)))"
        "+chr(10) for i in range(257))); "
        f"raise SystemExit({exit_code})"
    )
    original_update = ctx.update_run
    seen: list[int] = []

    def rebuild_before_end(
        run_id: str,
        event_type: str,
        mutate: Callable[[RunRecord], RunRecord],
        payload: dict[str, Any] | None = None,
    ) -> RunRecord:
        if event_type in {"run.finished", "run.failed"}:
            # A concurrent rebuild sees RUNNING and its reader fills bounded points.
            rebuild_index(ctx.index, ctx.store)
            seen.append(len(ctx.index.metric_points(run_id)))
        return original_update(run_id, event_type, mutate, payload)

    monkeypatch.setattr(ctx, "update_run", rebuild_before_end)
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(code)))
    assert done.status == (RunStatus.FINISHED if exit_code == 0 else RunStatus.FAILED)
    assert seen == [256]
    assert len(ctx.index.metric_points(done.run_id)) == 257


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
        thread = execution._pump(src, log, None, threading.Event(), [])
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


def test_stop_marker_written_while_the_child_runs_kills_it(ctx: Context, toy_repo: Path) -> None:
    # INT-F1: the supervisor watches the stop marker while it waits on the child,
    # so a stop that could not signal the child still ends the run.
    sleeper = cmd("import time; time.sleep(30)")
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=sleeper))
    result: list = []
    worker = threading.Thread(target=lambda: result.append(execute_run(ctx, rec.run_id)))
    worker.start()
    deadline = time.monotonic() + 20
    while ctx.find_record(rec.run_id).status != RunStatus.RUNNING:
        assert time.monotonic() < deadline, "the run never started"
        time.sleep(0.05)
    start = time.monotonic()
    (ctx.run_dir(rec) / execution.STOP_MARKER).write_text("now")
    worker.join(timeout=15)
    assert not worker.is_alive(), "the supervisor never noticed the stop marker"
    assert time.monotonic() - start < 15
    done = result[0]
    assert done.status == RunStatus.KILLED
    assert not execution.process_alive(done.executor.child_pid, None)


class _FullDisk:
    """A log file on a full disk: every write fails with ENOSPC."""

    def write(self, data: bytes) -> int:
        raise OSError(28, "No space left on device")

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_a_full_disk_does_not_block_a_chatty_command(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DF-69: the log thread died on ENOSPC; nobody read the pipe, so the child
    # blocked on write and the run never ended
    real_open = Path.open

    def open_full(self: Path, mode: str = "r", *args: object, **kwargs: object) -> object:
        if self.name == "stdout.log" and mode == "ab":
            return _FullDisk()
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_full)
    chatty = cmd("import sys; sys.stdout.write('x' * 4_000_000)")
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=chatty))
    result: list = []
    worker = threading.Thread(target=lambda: result.append(execute_run(ctx, rec.run_id)))
    worker.start()
    worker.join(timeout=60)
    if worker.is_alive():  # the old bug: unblock the child so the test run can end
        execution.terminate_group(ctx.find_record(rec.run_id).executor.child_pid or 0, grace=1)
        worker.join(timeout=30)
        pytest.fail("the run hung on a full disk")
    assert result[0].status == RunStatus.FINISHED
    warnings = [e.payload["message"] for e in _warning_events(ctx, rec.run_id)]
    assert len(warnings) == 1 and "log write failed" in warnings[0]
    assert "stdout.log" in warnings[0] and "No space left" in warnings[0]


def test_pump_drains_a_pipe_whose_log_cannot_be_opened(tmp_path: Path) -> None:
    r, w = os.pipe()
    src = os.fdopen(r, "rb", buffering=0)
    failures: list[str] = []
    thread = execution._pump(src, tmp_path / "no" / "dir.log", None, threading.Event(), failures)
    writer = threading.Thread(target=lambda: (os.write(w, b"x" * 1_000_000), os.close(w)))
    writer.start()
    writer.join(timeout=10)
    thread.join(timeout=10)
    src.close()
    assert not writer.is_alive() and not thread.is_alive()
    assert len(failures) == 1 and failures[0].startswith("dir.log: ")


def _ignore_data_and_pin_old_commit(repo: Path) -> str:
    """Make ``data/`` git-ignored, commit twice, and return the older commit."""
    git(repo, "rm", "-rq", "--cached", "data")
    (repo / ".gitignore").write_text("data/\n")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-qm", "ignore data")
    old = git(repo, "rev-parse", "HEAD")
    (repo / "infer.py").write_text("print('new')\n")
    git(repo, "commit", "-qam", "move on")
    return old


def test_a_pinned_run_reads_git_ignored_data_from_the_repo(ctx: Context, toy_repo: Path) -> None:
    # DF-18: the dataset path was resolved in the worktree, where ignored data is missing
    old = _ignore_data_and_pin_old_commit(toy_repo)
    read = cmd("import sys; print(len(open(sys.argv[1]).readlines()))", "{dataset.path}")
    req = RunRequest(repo=toy_repo, command=read, task="toy-acc", commit=old)
    done = run_fg(ctx, req)
    data = str(toy_repo.resolve() / "data" / "test.jsonl")
    assert done.status == RunStatus.FINISHED
    assert done.command[-1] == data
    assert done.datasets[0].path == data and done.datasets[0].hash_mode != "missing"
    assert (ctx.run_dir(done) / "logs" / "stdout.log").read_text().strip() == "4"


def test_a_pinned_run_reads_tracked_data_from_its_checkout(ctx: Context, toy_repo: Path) -> None:
    old = git(toy_repo, "rev-parse", "HEAD")
    (toy_repo / "data" / "test.jsonl").write_text('{"id": "ex-0", "reference": 1}\n')
    git(toy_repo, "commit", "-qam", "new data")
    read = cmd("import sys; print(len(open(sys.argv[1]).readlines()))", "{dataset.path}")
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=read, task="toy-acc", commit=old))
    assert done.command[-1].startswith(str(ctx.layout.worktrees_dir("toy")))
    assert done.datasets[0].path == done.command[-1]
    assert (ctx.run_dir(done) / "logs" / "stdout.log").read_text().strip() == "4"


def _old_commit(repo: Path) -> str:
    """Commit once more so the current HEAD is an older commit; return it."""
    old = git(repo, "rev-parse", "HEAD")
    (repo / "infer.py").write_text("print('new')\n")
    git(repo, "commit", "-qam", "move on")
    return old


def test_delayed_checkout_refuses_an_existing_unowned_worktree(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = prepare_run(
        ctx, RunRequest(repo=toy_repo, command=cmd("pass"), commit=_old_commit(toy_repo))
    )
    tree = ctx.layout.worktrees_dir("toy") / record.run_id
    assert not tree.exists()
    tree.parent.mkdir(parents=True, exist_ok=True)
    execution.create_worktree(toy_repo, record.git.commit, tree, None)
    original = (tree / "hypothex.yaml").read_bytes()
    discarded: list[Path] = []
    real_discard = execution._discard_worktree

    def discard(repo: Path, path: Path) -> None:
        discarded.append(path)
        real_discard(repo, path)

    monkeypatch.setattr(execution, "_discard_worktree", discard)
    done = execute_run(ctx, record.run_id)
    assert done.status == RunStatus.FAILED
    assert done.started_at is None
    assert "already exists" in (ctx.run_dir(record) / "logs" / "stderr.log").read_text()
    assert tree not in discarded
    assert (tree / "hypothex.yaml").read_bytes() == original


def test_delayed_checkout_reserves_the_directory_before_git(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = prepare_run(
        ctx, RunRequest(repo=toy_repo, command=cmd("pass"), commit=_old_commit(toy_repo))
    )
    tree = ctx.layout.worktrees_dir("toy") / record.run_id
    assert not tree.exists()
    real_create = execution.create_worktree
    calls: list[Path] = []

    def create(repo: Path, commit: str, dest: Path, diff: bytes | None) -> Path:
        calls.append(dest)
        assert dest.is_dir(), "git must only receive an exclusively reserved directory"
        assert list(dest.iterdir()) == []
        return real_create(repo, commit, dest, diff)

    monkeypatch.setattr(execution, "create_worktree", create)
    assert execution.checkout_run_tree(ctx, record) == tree
    # SLURM prepares on the login node and reuses the same checkout on its compute node.
    assert execution.checkout_run_tree(ctx, record) == tree
    assert calls == [tree]


def test_delayed_checkout_collision_at_reservation_preserves_the_winner(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = prepare_run(
        ctx, RunRequest(repo=toy_repo, command=cmd("pass"), commit=_old_commit(toy_repo))
    )
    tree = ctx.layout.worktrees_dir("toy") / record.run_id
    sentinel = tree / "winner.txt"
    real_mkdir = Path.mkdir
    real_create = execution.create_worktree
    creates: list[Path] = []

    def mkdir(path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        if path == tree and not path.exists():
            real_mkdir(path, mode=mode, parents=True)
            sentinel.write_text("another owner\n")
        real_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    def create(repo: Path, commit: str, dest: Path, diff: bytes | None) -> Path:
        creates.append(dest)
        return real_create(repo, commit, dest, diff)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(execution, "create_worktree", create)
    with pytest.raises(RunError, match="already exists"):
        execution.checkout_run_tree(ctx, record)
    assert creates == []
    assert sentinel.read_text() == "another owner\n"


@pytest.mark.parametrize("ready", [False, True], ids=["staging", "checked-out"])
@pytest.mark.parametrize("operation", ["checkout", "release"])
def test_remote_project_gate_precedes_pinned_checkout_and_staging_cleanup(
    ctx: Context,
    toy_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    ready: bool,
    operation: str,
) -> None:
    record = prepare_run(
        ctx, RunRequest(repo=toy_repo, command=cmd("pass"), commit=_old_commit(toy_repo))
    )
    if ready:
        execution.checkout_run_tree(ctx, record)
    staging = ctx.layout.project_dir("toy") / execution.STAGING_DIR
    before = {
        str(p.relative_to(staging)): p.read_bytes() for p in staging.rglob("*") if p.is_file()
    }
    entry = ctx.store.load_project("toy")
    # The reported remote path deliberately also exists on this machine.
    ctx.store.save_project(entry.model_copy(update={"remote_host": "gpu1"}))
    calls: list[str] = []
    local_repo = ctx.local_repo

    def checked_repo(project: str) -> Path:
        calls.append("gate")
        return local_repo(project)

    def no_git(*args: object, **kwargs: object) -> Any:
        calls.append("git")
        pytest.fail("remote-only project reached checkout or staging git operations")

    monkeypatch.setattr(ctx, "local_repo", checked_repo)
    monkeypatch.setattr(execution, "create_worktree", no_git)
    monkeypatch.setattr(execution, "_discard_worktree", no_git)
    monkeypatch.setattr(execution, "capture_diff", no_git)
    monkeypatch.setattr(execution.subprocess, "run", no_git)
    if operation == "checkout":
        with pytest.raises(RemoteProjectError, match="copied from host gpu1"):
            execution.checkout_run_tree(ctx, record)
    else:
        assert execution.release_worktree(ctx, record) is False
    assert calls == ["gate"]
    after = {str(p.relative_to(staging)): p.read_bytes() for p in staging.rglob("*") if p.is_file()}
    assert after == before
    tree = ctx.layout.worktrees_dir("toy") / record.run_id
    assert tree.is_dir() is ready


@pytest.mark.parametrize("log_writable", [True, False])
def test_execute_terminalizes_a_pinned_run_refused_by_the_project_gate(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch, log_writable: bool
) -> None:
    record = prepare_run(
        ctx, RunRequest(repo=toy_repo, command=cmd("pass"), commit=_old_commit(toy_repo))
    )
    record = ctx.update_run(
        record.run_id,
        "run.test_assignment",
        lambda r: r.model_copy(
            update={"executor": r.executor.model_copy(update={"gpus": [0], "queue_position": 1})}
        ),
    )
    staging = ctx.layout.project_dir("toy") / execution.STAGING_DIR
    before = {
        str(p.relative_to(staging)): p.read_bytes() for p in staging.rglob("*") if p.is_file()
    }
    entry = ctx.store.load_project("toy")
    ctx.store.save_project(entry.model_copy(update={"remote_host": "gpu1"}))

    def forbidden(*args: object, **kwargs: object) -> Any:
        pytest.fail("a refused project reached checkout, cleanup, or command execution")

    monkeypatch.setattr(execution, "create_worktree", forbidden)
    monkeypatch.setattr(execution, "_discard_worktree", forbidden)
    monkeypatch.setattr(execution.subprocess, "Popen", forbidden)
    write_text = Path.write_text

    def write(path: Path, *args: Any, **kwargs: Any) -> int:
        if not log_writable and path == ctx.run_dir(record) / "logs" / "stderr.log":
            raise OSError("log volume full")
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write)
    failed = execute_run(ctx, record.run_id)
    assert failed.status == RunStatus.FAILED and failed.ended_at is not None
    assert failed.started_at is None
    assert failed.executor.gpus == [] and failed.executor.queue_position is None
    assert (ctx.run_dir(failed) / execution.EXECUTION_CLAIM).is_file()
    events = [
        e for e in ctx.events.since(0) if e.run_id == record.run_id and e.type == "run.failed"
    ]
    assert len(events) == 1 and "copied from host gpu1" in events[0].payload["reason"]
    after = {str(p.relative_to(staging)): p.read_bytes() for p in staging.rglob("*") if p.is_file()}
    assert after == before
    with pytest.raises(RunError, match="not queued"):
        execute_run(ctx, record.run_id)


def test_failed_checkout_is_not_masked_by_a_staging_cleanup_error(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = prepare_run(
        ctx, RunRequest(repo=toy_repo, command=cmd("pass"), commit=_old_commit(toy_repo))
    )

    def reject(*args: object) -> None:
        raise RunError("checkout refused")

    def cleanup(*args: object) -> None:
        raise OSError("staging cleanup unavailable")

    monkeypatch.setattr(execution, "checkout_run_tree", reject)
    monkeypatch.setattr(execution, "_leave_staging_of", cleanup)
    failed = execute_run(ctx, record.run_id)
    assert failed.status == RunStatus.FAILED
    assert "checkout refused" in (ctx.run_dir(failed) / "logs" / "stderr.log").read_text()


@pytest.mark.parametrize(
    ("venv", "removed"), [(".venv", True), ("sub/.venv", False)], ids=["top", "nested"]
)
def test_release_worktree_ignores_the_top_level_venv(
    ctx: Context, toy_repo: Path, venv: str, removed: bool
) -> None:
    # DF-19: `uv run --project <worktree>` (env capture, scoring) makes .venv/,
    # and the worktree was then kept forever
    make = (
        "import os, sys; d = sys.argv[1]; os.makedirs(d + '/bin'); "
        "open(d + '/bin/python', 'w').write('x'); open(d + '/.gitignore', 'w').write('*')"
    )
    req = RunRequest(repo=toy_repo, command=cmd(make, venv), commit=_old_commit(toy_repo))
    done = run_fg(ctx, req)
    assert done.status == RunStatus.FINISHED
    tree = ctx.layout.worktrees_dir("toy") / done.run_id
    assert tree.exists() is not removed


def test_auto_eval_warnings_become_run_warnings_once(ctx: Context, toy_repo: Path) -> None:
    # DF-6, DF-17: auto-eval dropped the warnings of scoring; each must show up once
    preds = WRITE_PREDS.replace("'ex-' + str(i)", "('ex-' if i < 3 else 'x') + str(i)")
    done = run_fg(ctx, RunRequest(repo=toy_repo, command=cmd(preds), task="toy-acc"))
    assert done.status == RunStatus.FINISHED
    assert [e.payload["message"] for e in _warning_events(ctx, done.run_id)] == [
        "1 of 4 prediction ids are not in dataset 'toyset' split 'test'; "
        "they are scored with no reference"
    ]


def test_an_unknown_stage_is_refused_also_with_a_command(ctx: Context, toy_repo: Path) -> None:
    # DF-58: with a command, --stage was not checked and a misspelled stage was saved
    req = RunRequest(repo=toy_repo, stage="infre", command=cmd("print(1)"))
    with pytest.raises(RunError, match="no stage 'infre'"):
        prepare_run(ctx, req)
    assert ctx.store.list_run_ids() == {}
    ok = prepare_run(ctx, RunRequest(repo=toy_repo, stage="infer", command=cmd("print(1)")))
    assert ok.stage == "infer" and ok.command == cmd("print(1)")


def test_refusing_a_provided_var_names_how_to_set_it(ctx: Context, toy_repo: Path) -> None:
    # DF-12: the refusal said "--var seed ...", a CLI flag name, and gave no way out
    req = RunRequest(repo=toy_repo, command=cmd("print(1)"), vars={"seed": "3"})
    with pytest.raises(RunError) as err:
        prepare_run(ctx, req)
    message = str(err.value)
    assert message.startswith("template var seed is set by Hypothex")
    assert message.endswith("; --seed N; API/MCP: seed")


def test_prepared_runs_persist_their_actual_diff_identity(ctx: Context, toy_repo: Path) -> None:
    from hypothex.core.leaderboard import group_id_for

    req = RunRequest(repo=toy_repo, command=cmd("pass"), seed=1)
    clean = prepare_run(ctx, req)
    tracked = toy_repo / "identity.txt"
    tracked.write_text("base\n")
    git(toy_repo, "add", "identity.txt")
    git(toy_repo, "commit", "-qm", "capture identity fixture")
    tracked.write_text("first dirty model\n")
    first = prepare_run(ctx, req)
    same = prepare_run(ctx, req)
    tracked.write_text("second dirty model\n")
    other = prepare_run(ctx, req)
    assert clean.git.model_dump().get("diff_hash") is None
    for record in (first, same, other):
        saved = ctx.run_dir(record) / "git.diff"
        expected = hashlib.sha256(saved.read_bytes()).hexdigest()[:8]
        assert record.git.model_dump().get("diff_hash") == expected
        assert ctx.find_record(record.run_id).git.model_dump().get("diff_hash") == expected
    assert group_id_for(first) == group_id_for(same)
    assert group_id_for(first) != group_id_for(other)


def test_oversized_diff_identity_uses_the_captured_stat(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core.gitinfo import DiffCapture

    stat = "train.py | 2000000 +++++\n"
    monkeypatch.setattr(execution, "capture_diff", lambda _: DiffCapture(None, stat, True))
    record = prepare_run(ctx, RunRequest(repo=toy_repo, command=cmd("pass")))
    assert record.git.model_dump().get("diff_hash") == hashlib.sha256(stat.encode()).hexdigest()[:8]
    assert record.git.dirty
    assert (ctx.run_dir(record) / "git.diff.too_large").is_file()


def test_queued_pin_survives_checkout_changes_after_preparation(
    ctx: Context, toy_repo: Path
) -> None:
    tracked = toy_repo / "queued-model.txt"
    tracked.write_text("original model")
    git(toy_repo, "add", "queued-model.txt")
    git(toy_repo, "commit", "-qm", "pin queued model")
    commit = git(toy_repo, "rev-parse", "HEAD")
    record = prepare_run(
        ctx,
        RunRequest(
            repo=toy_repo,
            command=cmd("print(open('queued-model.txt').read())"),
            commit=commit,
            queue=True,
        ),
    )
    tracked.write_text("different model")
    git(toy_repo, "commit", "-qam", "change model while queued")
    done = execute_run(ctx, record.run_id)
    assert done.status == RunStatus.FINISHED
    assert (ctx.run_dir(done) / "logs/stdout.log").read_text().strip() == "original model"
