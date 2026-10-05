"""Durable metadata acceptance and bounded sweep issuance regressions."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from hypothex.core import sweeps
from hypothex.core.context import Context
from hypothex.core.errors import RunError, StoreError
from hypothex.core.execution import RunRequest
from hypothex.core.records import RunRecord, RunStatus
from hypothex.core.sweep_issuance import (
    SweepIssuanceActiveError,
    SweepIssuer,
    SweepLegacyResumeRequiredError,
)
from hypothex.remote.client import EnvUnreachableError
from tests.factories import make_record


def inputs(ctx: Context, toy_repo: Path, **changes: Any) -> dict[str, Any]:
    ctx.register_project(toy_repo)
    draft = sweeps._draft(
        "toy",
        None,
        None,
        [sweeps.SweepParam(name="x", values=["a", "b"])],
        None,
        [1],
        ["true", "{x}"],
        "human",
        None,
        None,
    )
    return {
        "spec": draft.model_dump(mode="json"),
        "repo": str(toy_repo),
        "gpus": 2,
        "queue": True,
        "hypothesis": "original",
        **changes,
    }


def test_acceptance_is_metadata_only_and_immutable(ctx: Context, toy_repo: Path) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    assert accepted["issuance"]["state"] == "queued"
    assert accepted["counts"]["total"] == 0
    assert accepted["issuance"]["accepted_at"] is not None
    assert issuer.accept("create", lambda: pytest.fail("retry evaluated edited inputs")) == accepted
    stored = ctx.events.sweep_operation_by_key("create")
    assert stored["request"]["gpus"] == 2
    assert stored["request"]["hypothesis"] == "original"
    assert len(sweeps.list_sweeps(ctx, "toy")) == 1


@pytest.mark.parametrize("point", ["prepared", "bound", "published", "committed"])
def test_acceptance_crash_boundaries_recover_original_definition(
    ctx: Context, toy_repo: Path, point: str
) -> None:
    class Crash(BaseException):
        pass

    def fault(stage: str) -> None:
        if stage == point:
            raise Crash()

    issuer = SweepIssuer(ctx, checkpoint=fault)
    with pytest.raises(Crash):
        issuer.accept("create", lambda: inputs(ctx, toy_repo))
    before = ctx.events.sweep_operation_by_key("create")
    recovered = SweepIssuer(ctx).accept("create", lambda: pytest.fail("replaced original request"))
    assert recovered["issuance"]["state"] == "queued"
    if before["sweep_id"]:
        assert recovered["spec"]["id"] == before["sweep_id"]
    assert len(sweeps.list_sweeps(ctx, "toy")) == 1
    assert ctx.events.sweep_operation_by_key("create")["request"]["queue"] is True


def test_owned_empty_reservation_recovers_but_nonempty_malformed_file_is_preserved(
    ctx: Context, toy_repo: Path
) -> None:
    def fault(stage: str) -> None:
        if stage == "bound":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        SweepIssuer(ctx, checkpoint=fault).accept("create", lambda: inputs(ctx, toy_repo))
    op = ctx.events.sweep_operation_by_key("create")
    path = sweeps.sweep_path(ctx.layout, "toy", op["sweep_id"])
    path.write_text("not: [valid", encoding="utf-8")
    with pytest.raises(StoreError):
        SweepIssuer(ctx).accept("create", lambda: pytest.fail("changed"))
    assert path.read_text() == "not: [valid"
    assert ctx.events.sweep_operation_by_key("create")["issuance"]["state"] == "preparing"


def test_two_coordinators_share_one_receipt(ctx: Context, toy_repo: Path) -> None:
    data = inputs(ctx, toy_repo)
    barrier = threading.Barrier(2)

    def accept() -> dict[str, Any]:
        barrier.wait()
        return SweepIssuer(Context.open(ctx.layout.home)).accept("create", lambda: data)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda _: accept(), range(2)))
    assert a == b
    assert len(sweeps.list_sweeps(ctx, "toy")) == 1


def test_legacy_claim_returns_explicit_conflict(ctx: Context, toy_repo: Path) -> None:
    data = inputs(ctx, toy_repo)
    spec = sweeps.create_sweep(
        ctx,
        project="toy",
        grid=[sweeps.SweepParam(name="x", values=["a"])],
        seeds=[1],
        command=["true", "{x}"],
        command_id="old",
    )
    with pytest.raises(SweepLegacyResumeRequiredError, match=spec.id):
        SweepIssuer(ctx).accept("old", lambda: data)
    assert ctx.events.sweep_operation_by_key("old") is None


def test_active_extend_conflicts_without_claiming_receipt(ctx: Context, toy_repo: Path) -> None:
    issuer = SweepIssuer(ctx)
    first = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    with pytest.raises(SweepIssuanceActiveError):
        issuer.extend("extend", "toy", first["spec"]["id"], [2])
    assert ctx.events.command_result("extend") is None


class Launcher:
    def __init__(self, ctx: Context, *, mirror: bool = True) -> None:
        self.ctx = ctx
        self.mirror = mirror
        self.calls: list[RunRequest] = []
        self.records: list[RunRecord] = []

    def __call__(self, req: RunRequest, key: str) -> RunRecord:
        self.calls.append(req)
        record = make_record(
            f"run-{len(self.calls)}",
            environment_id=self.ctx.descriptor.environment_id,
            seed=req.seed,
            params=req.params,
            tags=req.tags,
            hypothesis=req.hypothesis,
            gpus_requested=req.gpus,
        )
        self.records.append(record)
        if self.mirror:
            self.ctx.create_run(record)
        return record


def test_dispatch_and_explicit_resume_keep_original_options(ctx: Context, toy_repo: Path) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    fake = Launcher(ctx)
    issuer.tick(lambda _: fake)
    sid = accepted["spec"]["id"]
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "issued"
    assert issuer.accept("create", lambda: {}) == accepted
    resumed = issuer.extend("extend", "toy", sid, [1, 2])
    assert resumed["issuance"]["episode"] == 2
    assert resumed["issuance"]["planned"] == 4
    assert resumed["issuance"]["revision"] > accepted["issuance"]["revision"]
    issuer.tick(lambda _: fake)
    assert len(fake.calls) == 4
    assert all(r.gpus == 2 and r.queue and r.hypothesis == "original" for r in fake.calls)
    assert issuer.extend("extend", "toy", sid, [99]) == resumed


def test_eventless_zero_member_failure_is_observable_and_explicitly_resumable(
    ctx: Context, toy_repo: Path
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))

    def fail(req: RunRequest, key: str) -> RunRecord:
        raise RunError("rejected")

    issuer.tick(lambda _: fail)
    summary = sweeps.summarize_sweep(ctx, "toy", accepted["spec"]["id"])
    assert summary.issuance.state == "incomplete"
    assert summary.issuance.error.type == "SweepIncompleteError"
    assert "0 of 2" in summary.issuance.error.message
    assert summary.issuance.resume.seeds == [1]
    assert summary.counts["total"] == 0
    assert [e.payload["state"] for e in ctx.events.since(0) if e.type == "sweep.issuance"][
        -1
    ] == "incomplete"
    issuer.tick(lambda _: pytest.fail("automatically retried failure"))


def test_mirror_lag_settles_without_reissuing(ctx: Context, toy_repo: Path) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    fake = Launcher(ctx, mirror=False)
    issuer.tick(lambda _: fake)
    sid = accepted["spec"]["id"]
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "settling"
    assert sweeps.summarize_sweep(ctx, "toy", sid).counts["total"] == 0
    ctx.create_run(fake.records[0])
    issuer.tick(lambda _: pytest.fail("reissued during mirror lag"))
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "settling"
    ctx.create_run(fake.records[1])
    issuer.tick(lambda _: pytest.fail("reissued at settlement"))
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "issued"


def test_cancel_before_dispatch_prevents_every_member_and_survives_restart(
    ctx: Context, toy_repo: Path
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    sid = accepted["spec"]["id"]
    issuer.request_cancel("toy", sid)
    SweepIssuer(Context.open(ctx.layout.home)).tick(
        lambda _: pytest.fail("launched after cancellation")
    )
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.state == "interrupted" and state.reason == "cancelled"
    assert state.cancel_requested is True
    assert state.resume.seeds == [1]


@pytest.mark.parametrize("running", [False, True])
def test_cancel_drains_blocked_current_member_and_preserves_running_race(
    ctx: Context, toy_repo: Path, running: bool
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    sid = accepted["spec"]["id"]
    entered, release = threading.Event(), threading.Event()
    fake = Launcher(ctx, mirror=False)

    def blocked(req: RunRequest, key: str) -> RunRecord:
        entered.set()
        assert release.wait(5)
        record = fake(req, key)
        if running:
            record.status = RunStatus.RUNNING
        ctx.create_run(record)
        return record

    worker = threading.Thread(target=lambda: issuer.tick(lambda _: blocked))
    worker.start()
    assert entered.wait(5)
    issuer.request_cancel("toy", sid)
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.cancel_requested
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert len(fake.calls) == 1
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.state == "interrupted" and state.reason == "cancelled"
    assert ctx.find_record("run-1").status == (RunStatus.RUNNING if running else RunStatus.KILLED)


def test_ambiguous_remote_cancellation_waits_for_member_identity(
    ctx: Context, toy_repo: Path
) -> None:
    issuer = SweepIssuer(ctx)
    data = inputs(ctx, toy_repo)
    data["spec"]["host"] = "fake"
    accepted = issuer.accept("create", lambda: data)
    sid = accepted["spec"]["id"]
    fake = Launcher(ctx, mirror=False)

    def lost(req: RunRequest, key: str) -> RunRecord:
        fake(req, key)
        issuer.request_cancel("toy", sid)
        raise EnvUnreachableError("answer lost")

    issuer.tick(lambda _: lost)
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "settling"
    SweepIssuer(ctx).tick(lambda _: pytest.fail("ambiguous call repeated"))
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "settling"
    ctx.create_run(fake.records[0])
    SweepIssuer(ctx).tick(lambda _: pytest.fail("resolved call repeated"))
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.state == "interrupted" and state.reason == "cancelled"
    assert ctx.find_record("run-1").status == RunStatus.KILLED


def test_dead_issuing_owner_is_interrupted_without_automatic_launch(
    ctx: Context, toy_repo: Path
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    op = ctx.events.sweep_operation_by_key("create")
    ctx.events.update_sweep(
        "create", op["issuance"]["revision"], {"issuance": {**op["issuance"], "state": "issuing"}}
    )
    SweepIssuer(ctx).tick(lambda _: pytest.fail("dead issuer resumed"))
    state = sweeps.summarize_sweep(ctx, "toy", accepted["spec"]["id"]).issuance
    assert state.state == "interrupted" and state.reason == "worker_lost"


def test_concurrent_dispatchers_have_one_owner(ctx: Context, toy_repo: Path) -> None:
    issuer = SweepIssuer(ctx)
    issuer.accept("create", lambda: inputs(ctx, toy_repo))
    entered, release = threading.Event(), threading.Event()
    fake = Launcher(ctx)

    def blocked(req: RunRequest, key: str) -> RunRecord:
        entered.set()
        assert release.wait(5)
        return fake(req, key)

    thread = threading.Thread(target=lambda: issuer.tick(lambda _: blocked))
    thread.start()
    assert entered.wait(5)
    SweepIssuer(Context.open(ctx.layout.home)).tick(lambda _: pytest.fail("duplicate owner"))
    release.set()
    thread.join(5)
    assert not thread.is_alive() and len(fake.calls) == 2


def test_shutdown_drains_current_call_without_issuing_next(ctx: Context, toy_repo: Path) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    fake = Launcher(ctx)

    def blocked(req: RunRequest, key: str) -> RunRecord:
        entered.set()
        assert release.wait(5)
        return fake(req, key)

    issuer.start(lambda _: blocked)
    assert entered.wait(5)
    stop_thread = threading.Thread(target=lambda: (issuer.stop(), stopped.set()))
    stop_thread.start()
    assert not stopped.wait(0.05)
    release.set()
    stop_thread.join(5)
    assert stopped.is_set() and len(fake.calls) == 1
    state = sweeps.summarize_sweep(ctx, "toy", accepted["spec"]["id"]).issuance
    assert state.state == "interrupted" and state.reason == "shutdown"


def test_cancel_racing_final_transition_is_not_reported_issued(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    sid = accepted["spec"]["id"]
    real = ctx.events.update_sweep
    raced = False

    def update(
        key: str, revision: int, changes: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        nonlocal raced
        if changes.get("issuance", {}).get("state") == "issued" and not raced:
            raced = True
            issuer.request_cancel("toy", sid)
        return real(key, revision, changes, **kwargs)

    monkeypatch.setattr(ctx.events, "update_sweep", update)
    issuer.tick(lambda _: Launcher(ctx))
    issuer.tick(lambda _: pytest.fail("cancel caused relaunch"))
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.state == "interrupted" and state.reason == "cancelled"
    assert all(
        r.status == RunStatus.KILLED
        for r in sweeps.sweep_runs(ctx, sweeps.load_sweep(ctx.layout, "toy", sid))
    )


def test_cancel_cas_retry_cannot_target_a_later_episode(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    sid = accepted["spec"]["id"]
    real = ctx.events.update_sweep
    raced = False

    def update(
        key: str, revision: int, changes: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        nonlocal raced
        if changes.get("issuance", {}).get("cancel_requested") and not raced:
            raced = True
            op = ctx.events.sweep_operation_by_key("create")
            real(
                "create",
                op["issuance"]["revision"],
                {"issuance": {**op["issuance"], "state": "interrupted", "reason": "worker_lost"}},
            )
            issuer.extend("resume", "toy", sid, [1])
        return real(key, revision, changes, **kwargs)

    monkeypatch.setattr(ctx.events, "update_sweep", update)
    issuer.request_cancel("toy", sid)
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.episode == 2 and state.cancel_requested is False


def test_cancel_between_member_check_and_claim_prevents_new_call(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    sid = accepted["spec"]["id"]
    real = ctx.events.update_sweep
    raced = False

    def update(
        key: str, revision: int, changes: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        nonlocal raced
        if changes.get("inflight") and not raced:
            raced = True
            issuer.request_cancel("toy", sid)
        return real(key, revision, changes, **kwargs)

    monkeypatch.setattr(ctx.events, "update_sweep", update)
    issuer.tick(lambda _: lambda req, key: pytest.fail("launch began after durable cancellation"))
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.state == "interrupted" and state.reason == "cancelled"


def test_cancel_accounts_for_member_written_before_launcher_error(
    ctx: Context, toy_repo: Path
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    sid = accepted["spec"]["id"]
    fake = Launcher(ctx)

    def partial(req: RunRequest, key: str) -> RunRecord:
        fake(req, key)
        issuer.request_cancel("toy", sid)
        raise RunError("post-launch failure")

    issuer.tick(lambda _: partial)
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.state == "interrupted" and state.reason == "cancelled"
    assert ctx.find_record("run-1").status == RunStatus.KILLED


def test_cancel_settlement_recognizes_later_confirmed_stop_after_failed_receipt(
    ctx: Context, toy_repo: Path
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    sid = accepted["spec"]["id"]
    fake = Launcher(ctx)

    def launch(req: RunRequest, key: str) -> RunRecord:
        record = fake(req, key)
        issuer.request_cancel("toy", sid)
        return record

    def failed(ids: list[str]) -> sweeps.CancelResult:
        return sweeps.CancelResult(asked=len(ids), failed=len(ids), errors=["temporary host error"])

    issuer.tick(lambda _: launch, lambda spec, key: failed)
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "settling"
    record = ctx.find_record("run-1")
    record.status = RunStatus.KILLED
    ctx.store.write_record(record)
    ctx.index.upsert_run(record)
    issuer.tick(lambda _: pytest.fail("relaunch"), lambda spec, key: failed)
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.state == "interrupted" and state.reason == "cancelled"


def test_failed_preparation_records_safe_diagnostic_without_accepting(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer = SweepIssuer(ctx)

    def fail(layout: object, spec: object) -> None:
        raise OSError("storage full")

    monkeypatch.setattr(sweeps, "save_sweep", fail)
    with pytest.raises(OSError, match="storage full"):
        issuer.accept("create", lambda: inputs(ctx, toy_repo))
    op = ctx.events.sweep_operation_by_key("create")
    assert op["issuance"]["state"] == "preparing" and op["issuance"]["accepted_at"] is None
    assert op["issuance"]["error"] == {"type": "OSError", "message": "storage full"}
    assert ctx.events.sweep_operations({"queued"}) == []


def test_worker_error_redacts_credentials_and_bounds_diagnostic(
    ctx: Context, toy_repo: Path
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))

    def fail(req: RunRequest, key: str) -> RunRecord:
        raise RunError('Authorization: Bearer dangerous123 token="secret456" ' + "x" * 600)

    issuer.tick(lambda _: fail)
    error = sweeps.summarize_sweep(ctx, "toy", accepted["spec"]["id"]).issuance.error
    assert error.type == "SweepIncompleteError" and len(error.message) <= 500
    assert "dangerous123" not in error.message and "secret456" not in error.message


def test_non_cancelled_transport_failure_is_explicitly_resumable(
    ctx: Context, toy_repo: Path
) -> None:
    issuer = SweepIssuer(ctx)
    data = inputs(ctx, toy_repo)
    data["spec"]["host"] = "fake-only"
    accepted = issuer.accept("create", lambda: data)
    keys: list[str] = []

    def offline(req: RunRequest, key: str) -> RunRecord:
        keys.append(key)
        raise EnvUnreachableError("host unavailable")

    issuer.tick(lambda _: offline)
    sid = accepted["spec"]["id"]
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.state == "incomplete" and state.resume.seeds == [1]
    issuer.tick(lambda _: pytest.fail("failed transport auto-retried"))
    issuer.extend("resume", "toy", sid, [1])
    fake = Launcher(ctx)

    def online(req: RunRequest, key: str) -> RunRecord:
        keys.append(key)
        return fake(req, key)

    issuer.tick(lambda _: online)
    assert keys[0] == keys[1]
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "issued"


def test_cancelled_preconnect_failure_has_no_ambiguous_remote_member(
    ctx: Context, toy_repo: Path
) -> None:
    issuer = SweepIssuer(ctx)
    data = inputs(ctx, toy_repo)
    data["spec"]["host"] = "fake-only"
    accepted = issuer.accept("create", lambda: data)
    sid = accepted["spec"]["id"]

    def refused(req: RunRequest, key: str) -> RunRecord:
        issuer.request_cancel("toy", sid)
        raise EnvUnreachableError("connection refused", may_have_been_sent=False)

    issuer.tick(lambda _: refused)
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.state == "interrupted" and state.reason == "cancelled"


def test_cancelling_failed_ambiguous_attempt_does_not_forget_accepted_member(
    ctx: Context, toy_repo: Path
) -> None:
    issuer = SweepIssuer(ctx)
    data = inputs(ctx, toy_repo)
    data["spec"]["host"] = "fake-only"
    accepted = issuer.accept("create", lambda: data)
    sid = accepted["spec"]["id"]
    fake = Launcher(ctx, mirror=False)

    def lost(req: RunRequest, key: str) -> RunRecord:
        fake(req, key)
        raise EnvUnreachableError("response lost")

    issuer.tick(lambda _: lost)
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "incomplete"
    issuer.request_cancel("toy", sid)
    issuer.tick(lambda _: pytest.fail("cancel reissued ambiguous request"))
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "settling"
    ctx.create_run(fake.records[0])
    issuer.tick(lambda _: pytest.fail("cancel reissued mirrored request"))
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.reason == "cancelled"
    assert ctx.find_record("run-1").status == RunStatus.KILLED


@pytest.mark.parametrize("returned", [False, True])
def test_resume_cancel_retains_previous_episode_remote_outcomes(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch, returned: bool
) -> None:
    class Crash(BaseException):
        pass

    issuer = SweepIssuer(ctx)
    data = inputs(ctx, toy_repo)
    data["spec"]["host"] = "fake-only"
    data["spec"]["grid"] = [{"name": "x", "values": ["a"]}]
    accepted = issuer.accept("create", lambda: data)
    sid = accepted["spec"]["id"]
    fake = Launcher(ctx, mirror=False)

    def lost(req: RunRequest, key: str) -> RunRecord:
        record = fake(req, key)
        if not returned:
            raise Crash()
        return record

    real = issuer._update

    def crash_before_settling(key: str, **changes: Any) -> dict[str, Any]:
        if returned and changes.get("state", {}).get("state") == "settling":
            raise Crash()
        return real(key, **changes)

    monkeypatch.setattr(issuer, "_update", crash_before_settling)
    with pytest.raises(Crash):
        issuer.tick(lambda _: lost)
    recovered = SweepIssuer(ctx)
    recovered.tick(lambda _: pytest.fail("dead episode resumed"))
    recovered.extend("resume", "toy", sid, [1])
    recovered.request_cancel("toy", sid)
    recovered.tick(lambda _: pytest.fail("cancelled resumed episode launched"))
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "settling"
    ctx.create_run(fake.records[0])
    recovered.tick(lambda _: pytest.fail("late mirror caused relaunch"))
    assert ctx.find_record("run-1").status == RunStatus.KILLED
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.episode == 2 and state.state == "interrupted" and state.reason == "cancelled"


def test_cancel_of_failed_episode_cannot_race_into_a_new_preparation(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer = SweepIssuer(ctx)
    data = inputs(ctx, toy_repo)
    data["spec"]["host"] = "fake-only"
    accepted = issuer.accept("create", lambda: data)
    sid = accepted["spec"]["id"]

    def lost(req: RunRequest, key: str) -> RunRecord:
        raise EnvUnreachableError("unknown outcome")

    issuer.tick(lambda _: lost)
    real = ctx.events.update_sweep
    raced = False

    def update(
        key: str, revision: int, changes: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        nonlocal raced
        if changes.get("issuance", {}).get("cancel_requested") and not raced:
            raced = True
            issuer.extend("resume", "toy", sid, [1])
        return real(key, revision, changes, **kwargs)

    monkeypatch.setattr(ctx.events, "update_sweep", update)
    issuer.request_cancel("toy", sid)
    state = sweeps.summarize_sweep(ctx, "toy", sid).issuance
    assert state.episode == 2 and state.state == "queued" and not state.cancel_requested
    assert ctx.events.sweep_operation_by_key("create")["issuance"]["state"] == "incomplete"


@pytest.mark.parametrize("state", ["incomplete", "interrupted"])
@pytest.mark.parametrize("returned", [False, True])
def test_direct_cancel_reconciles_terminal_episode_unmirrored_outcomes(
    ctx: Context, toy_repo: Path, state: str, returned: bool
) -> None:
    issuer = SweepIssuer(ctx)
    data = inputs(ctx, toy_repo)
    data["spec"]["host"] = "fake-only"
    accepted = issuer.accept("create", lambda: data)
    sid = accepted["spec"]["id"]
    op = ctx.events.sweep_operation_by_key("create")
    ctx.events.update_sweep(
        "create",
        op["issuance"]["revision"],
        {
            "issuance": {
                **op["issuance"],
                "state": state,
                "reason": "worker_lost" if state == "interrupted" else "launch_failed",
            },
            "run_ids": ["late"] if returned else [],
            "inflight": None
            if returned
            else {"command_id": "member", "seed": 1, "params": {"x": "a"}},
        },
    )
    issuer.request_cancel("toy", sid)
    issuer.tick(lambda _: pytest.fail("terminal cancellation reissued"))
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.state == "settling"
    ctx.create_run(
        make_record(
            "late",
            environment_id=ctx.descriptor.environment_id,
            seed=1,
            params={"x": "a"},
            tags=[sweeps.sweep_tag(ctx.descriptor.environment_id, sid)],
        )
    )
    issuer.tick(lambda _: pytest.fail("late member reissued"))
    assert ctx.find_record("late").status == RunStatus.KILLED
    assert sweeps.summarize_sweep(ctx, "toy", sid).issuance.reason == "cancelled"


def test_cancel_winning_before_extension_prepare_prevents_second_active_episode(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer = SweepIssuer(ctx)
    accepted = issuer.accept("create", lambda: inputs(ctx, toy_repo))
    sid = accepted["spec"]["id"]
    op = ctx.events.sweep_operation_by_key("create")
    ctx.events.update_sweep(
        "create",
        op["issuance"]["revision"],
        {
            "issuance": {**op["issuance"], "state": "incomplete", "reason": "launch_failed"},
            "run_ids": ["unmirrored-accepted"],
        },
    )
    entered, release = threading.Event(), threading.Event()
    real = ctx.events.prepare_sweep

    def prepare(key: str, data: dict[str, Any], **kwargs: Any) -> bool:
        if key == "resume":
            entered.set()
            assert release.wait(5)
        return real(key, data, **kwargs)

    monkeypatch.setattr(ctx.events, "prepare_sweep", prepare)
    with ThreadPoolExecutor(max_workers=1) as pool:
        extending = pool.submit(issuer.extend, "resume", "toy", sid, [1])
        try:
            assert entered.wait(5)
            issuer.request_cancel("toy", sid)
        finally:
            release.set()
        with pytest.raises(SweepIssuanceActiveError):
            extending.result(timeout=5)
    active = ctx.events.sweep_operations({"preparing", "queued", "issuing", "settling"})
    assert [item["operation_key"] for item in active] == ["create"]
    assert active[0]["issuance"]["cancel_requested"]
    assert ctx.events.command_result("resume") is None
    assert ctx.events.sweep_operation_by_key("resume") is None
