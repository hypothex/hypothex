"""Real process exits exercise durable state and operating-system flock release."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from hypothex.core import sweeps
from hypothex.core.context import Context
from hypothex.core.sweep_issuance import SweepIssuer
from tests.core.test_sweep_issuance import Launcher, inputs

SCRIPT = """
import json, os, sys, time
from pathlib import Path
from hypothex.core.context import Context
from hypothex.core.sweep_issuance import SweepIssuer
home, request_file, point, output = sys.argv[1:]
ctx = Context.open(Path(home))
data = json.loads(Path(request_file).read_text())
def fault(stage):
    if stage == point:
        os._exit(23)
issuer = SweepIssuer(ctx, checkpoint=fault)
accepted = issuer.accept("process-create", lambda: data)
Path(output).write_text(json.dumps(accepted, sort_keys=True))
"""


def child(ctx: Context, request: Path, point: str, output: Path) -> subprocess.Popen[str]:
    env = {**os.environ, "HOME": str(ctx.layout.home), "HYPOTHEX_HOME": str(ctx.layout.home)}
    return subprocess.Popen(
        [sys.executable, "-c", SCRIPT, str(ctx.layout.home), str(request), point, str(output)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.mark.parametrize("point", ["prepared", "bound", "published", "committed"])
def test_process_death_during_acceptance_keeps_identity(
    ctx: Context, toy_repo: Path, tmp_path: Path, point: str
) -> None:
    request = tmp_path / "request.json"
    request.write_text(json.dumps(inputs(ctx, toy_repo)))
    process = child(ctx, request, point, tmp_path / "out.json")
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 23, (stdout, stderr)
    before = ctx.events.sweep_operation_by_key("process-create")
    after = SweepIssuer(Context.open(ctx.layout.home)).accept(
        "process-create", lambda: pytest.fail("replaced crashed original")
    )
    if before["sweep_id"]:
        assert before["sweep_id"] == after["spec"]["id"]
    assert len(sweeps.list_sweeps(ctx, "toy")) == 1
    assert after["issuance"]["state"] == "queued"


def test_two_processes_accept_identical_receipts(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    request = tmp_path / "request.json"
    request.write_text(json.dumps(inputs(ctx, toy_repo)))
    outputs = [tmp_path / "a.json", tmp_path / "b.json"]
    processes = [child(ctx, request, "none", output) for output in outputs]
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
    assert outputs[0].read_text() == outputs[1].read_text()
    assert len(sweeps.list_sweeps(ctx, "toy")) == 1


def test_worker_process_death_exposes_interruption_then_only_missing_cells_resume(
    ctx: Context, toy_repo: Path
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    script = """
import os, sys
from pathlib import Path
from hypothex.core.context import Context
from hypothex.core.sweep_issuance import SweepIssuer
from tests.factories import make_record
ctx = Context.open(Path(sys.argv[1]))
def launch(req, key):
    ctx.create_run(make_record("before-death", environment_id=ctx.descriptor.environment_id,
                               params=req.params, seed=req.seed, tags=req.tags))
    os._exit(23)
SweepIssuer(ctx).tick(lambda spec: launch)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(ctx.layout.home)],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "HOME": str(ctx.layout.home), "HYPOTHEX_HOME": str(ctx.layout.home)},
    )
    assert result.returncode == 23, result.stderr
    recovered = SweepIssuer(Context.open(ctx.layout.home))
    recovered.tick(lambda _: pytest.fail("dead worker auto-resumed"))
    sid = accepted["spec"]["id"]
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.reason == "worker_lost"
    recovered.extend("resume", "toy", sid, [1])
    fake = Launcher(ctx)
    recovered.tick(lambda _: fake)
    assert len(fake.calls) == 1
    assert set(sweeps.summarize_sweep(ctx, "toy", sid).run_ids) == {"before-death", "run-1"}


def test_receipt_namespace_and_anonymous_requests(ctx: Context, toy_repo: Path) -> None:
    issuer = SweepIssuer(ctx)
    original = ctx.events.run_once("existing", lambda: {"unrelated": "same namespace"})
    assert issuer.accept("existing", lambda: pytest.fail("claimed another route key")) == original
    a = issuer.accept(None, lambda: inputs(ctx, toy_repo))
    b = issuer.accept(None, lambda: inputs(ctx, toy_repo))
    assert a["spec"]["id"] != b["spec"]["id"]


def test_acceptance_transaction_failure_can_retry_metadata_only(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer = SweepIssuer(ctx)
    real = ctx.events._append_sweep_event

    def fail(*args: Any) -> None:
        raise RuntimeError("rollback")

    monkeypatch.setattr(ctx.events, "_append_sweep_event", fail)
    with pytest.raises(RuntimeError, match="rollback"):
        issuer.accept("create", lambda: inputs(ctx, toy_repo))
    op = ctx.events.sweep_operation_by_key("create")
    assert op["issuance"]["state"] == "preparing"
    assert ctx.events.sweep_operations({"queued"}) == []
    monkeypatch.setattr(ctx.events, "_append_sweep_event", real)
    accepted = issuer.accept("create", lambda: pytest.fail("changed original"))
    assert accepted["spec"]["id"] == op["sweep_id"]


def test_missing_dirty_patch_refuses_new_episode(ctx: Context, toy_repo: Path) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    issuer.tick(lambda _: Launcher(ctx))
    first = ctx.find_record("run-1")
    first.git.commit = "c" * 40
    first.git.dirty = True
    # Re-persisting the first member simulates its missing captured patch.
    ctx.store.write_record(first)
    ctx.index.upsert_run(first)
    with pytest.raises(sweeps.SweepError, match="patch is missing"):
        issuer.extend("resume", "toy", accepted["spec"]["id"], [2])
    assert ctx.events.command_result("resume") is None


def test_process_death_after_cancel_intent_keeps_ambiguous_call_until_mirrored(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    request = inputs(ctx, toy_repo)
    request["spec"]["host"] = "fake-only"
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: request)
    output = tmp_path / "accepted-remote-run.json"
    script = """
import os, sys
from pathlib import Path
from hypothex.core.context import Context
from hypothex.core.sweep_issuance import SweepIssuer
from tests.factories import make_record
ctx = Context.open(Path(sys.argv[1]))
issuer = SweepIssuer(ctx)
sid = sys.argv[2]
def launch(req, key):
    record = make_record("accepted-remote", environment_id=ctx.descriptor.environment_id,
                         params=req.params, seed=req.seed, tags=req.tags)
    Path(sys.argv[3]).write_text(record.model_dump_json())
    issuer.request_cancel("toy", sid)
    os._exit(23)
issuer.tick(lambda spec: launch)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(ctx.layout.home), accepted["spec"]["id"], str(output)],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "HOME": str(ctx.layout.home), "HYPOTHEX_HOME": str(ctx.layout.home)},
    )
    assert result.returncode == 23, result.stderr
    recovered = SweepIssuer(Context.open(ctx.layout.home))
    recovered.tick(lambda _: pytest.fail("cancelled worker reissued"))
    state = sweeps.summarize_sweep(ctx, "toy", accepted["spec"]["id"]).issuance
    assert state.state == "settling" and state.cancel_requested
    from hypothex.core.records import RunRecord, RunStatus

    ctx.create_run(RunRecord.model_validate_json(output.read_text()))
    recovered.tick(lambda _: pytest.fail("resolved member reissued"))
    state = sweeps.summarize_sweep(ctx, "toy", accepted["spec"]["id"]).issuance
    assert state.state == "interrupted" and state.reason == "cancelled"
    assert ctx.find_record("accepted-remote").status == RunStatus.KILLED
