"""HTTP acceptance snapshots and current sweep observations stay distinct."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.core import sweeps
from hypothex.core.context import Context
from hypothex.core.execution import RunRequest
from hypothex.core.records import RunRecord
from tests.api.envserver import wait_until
from tests.factories import make_record

BASE = "http://127.0.0.1:7777"
BODY = {
    "project": "toy",
    "grid": [{"name": "x", "values": ["a", "b"]}],
    "seeds": [1],
    "command": ["true", "{x}"],
    "gpus": 3,
    "queue": True,
    "hypothesis": "saved",
    "command_id": "create",
}


def test_post_returns_before_gated_launch_then_get_advances(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.register_project(toy_repo)
    entered, release = threading.Event(), threading.Event()
    calls: list[RunRequest] = []

    def factory(actual_ctx: Context, sid: str) -> sweeps.Launcher:
        def launch(req: RunRequest, key: str) -> RunRecord:
            entered.set()
            assert release.wait(5)
            calls.append(req)
            return actual_ctx.create_run(
                make_record(
                    f"run-{len(calls)}",
                    environment_id=actual_ctx.descriptor.environment_id,
                    params=req.params,
                    seed=req.seed,
                    tags=req.tags,
                )
            )

        return launch

    monkeypatch.setattr(sweeps, "_local_launcher", factory)
    app = create_app(ctx.layout.home, hub=False, background_repair=False)
    with TestClient(app, base_url=BASE) as client:
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(client.post, "/api/v1/sweeps", json=BODY)
                response = future.result(timeout=2)
            assert response.status_code == 200
            first = response.json()
            assert first["issuance"]["state"] == "queued" and first["counts"]["total"] == 0
            sid = first["spec"]["id"]
            assert entered.wait(2)
            assert client.get(f"/api/v1/sweeps/{sid}").json()["issuance"]["state"] == "issuing"
            assert client.get("/api/v1/projects/toy/sweeps").json()[0]["issuance"]["planned"] == 2
            active = client.post(
                f"/api/v1/sweeps/toy/{sid}/extend", json={"seeds": [2], "command_id": "extend"}
            )
            assert active.status_code == 409 and active.json()["type"] == "SweepIssuanceActiveError"
            assert (
                client.post(
                    "/api/v1/sweeps", json={**BODY, "gpus": 0, "hypothesis": "changed"}
                ).json()
                == first
            )
        finally:
            release.set()
        wait_until(
            lambda: client.get(f"/api/v1/sweeps/{sid}").json()["issuance"]["state"] == "issued"
        )
        assert len(calls) == 2 and all(req.gpus == 3 and req.hypothesis == "saved" for req in calls)
        assert client.post("/api/v1/sweeps", json=BODY).json() == first


def test_token_guard_prevents_acceptance_state(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    with TestClient(
        create_app(ctx.layout.home, hub=False, background_repair=False, auth_token="fake-only"),
        base_url=BASE,
    ) as client:
        assert client.post("/api/v1/sweeps", json=BODY).status_code == 401
    assert ctx.events.sweep_operations({"preparing", "queued", "issuing"}) == []
    assert sweeps.list_sweeps(ctx, "toy") == []


def test_retry_replays_before_semantic_validation_of_edited_body(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core.sweep_issuance import SweepIssuer

    monkeypatch.setattr(SweepIssuer, "start", lambda *args: None)
    ctx.register_project(toy_repo)
    with TestClient(
        create_app(ctx.layout.home, hub=False, background_repair=False), base_url=BASE
    ) as client:
        first = client.post("/api/v1/sweeps", json=BODY)
        retry = client.post(
            "/api/v1/sweeps",
            json={
                **BODY,
                "created_by": "agent:changed",
                "hypothesis": "",
                "host": "missing",
                "command": ["{unknown}"],
            },
        )
        assert retry.status_code == 200 and retry.json() == first.json()


def test_legacy_create_retry_is_a_prompt_explicit_409(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    spec = sweeps.create_sweep(
        ctx,
        project="toy",
        grid=[sweeps.SweepParam(name="x", values=["a"])],
        seeds=[1],
        command=["true", "{x}"],
        command_id="create",
    )
    with TestClient(
        create_app(ctx.layout.home, hub=False, background_repair=False), base_url=BASE
    ) as client:
        response = client.post("/api/v1/sweeps", json=BODY)
    assert response.status_code == 409
    assert response.json()["type"] == "SweepLegacyResumeRequiredError"
    assert spec.id in response.json()["error"] and "zero-run" in response.json()["error"]
    assert ctx.events.sweep_operation_by_key("create") is None


def test_cancel_receipt_replay_cannot_cancel_resumed_episode(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core.sweep_issuance import SweepIssuer

    monkeypatch.setattr(SweepIssuer, "start", lambda *args: None)
    ctx.register_project(toy_repo)
    app = create_app(ctx.layout.home, hub=False, background_repair=False)
    with TestClient(app, base_url=BASE) as client:
        first = client.post("/api/v1/sweeps", json=BODY).json()
        sid = first["spec"]["id"]
        route = f"/api/v1/sweeps/toy/{sid}"
        cancelled = client.post(route + "/cancel_queued", json={"command_id": "cancel"}).json()
        assert cancelled["cancel"]["asked"] == 0 and cancelled["issuance"]["cancel_requested"]
        app.state.sweep_issuer.tick(lambda _: pytest.fail("launch after cancel"))
        more = client.post(route + "/extend", json={"seeds": [1], "command_id": "resume"})
        assert more.status_code == 200 and more.json()["issuance"]["episode"] == 2
        assert (
            client.post(route + "/cancel_queued", json={"command_id": "cancel"}).json() == cancelled
        )
        assert client.get(route).json()["issuance"]["cancel_requested"] is False


def test_two_http_apps_share_original_acceptance(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core.sweep_issuance import SweepIssuer

    monkeypatch.setattr(SweepIssuer, "start", lambda *args: None)
    ctx.register_project(toy_repo)
    app1 = create_app(ctx.layout.home, hub=False, background_repair=False)
    app2 = create_app(ctx.layout.home, hub=False, background_repair=False)
    with TestClient(app1, base_url=BASE) as a, TestClient(app2, base_url=BASE) as b:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(client.post, "/api/v1/sweeps", json=BODY) for client in (a, b)]
            replies = [job.result(timeout=5) for job in jobs]
        assert [reply.status_code for reply in replies] == [200, 200]
        assert replies[0].json() == replies[1].json()
        assert len(a.get("/api/v1/projects/toy/sweeps").json()) == 1


def test_lifespan_keeps_manager_and_demo_context_alive_until_issuer_drains(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    from hypothex.api.app import HubManager

    ctx.register_project(toy_repo)
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    active = {"extra": False, "manager_stopped": False}

    @contextmanager
    def extra() -> Iterator[None]:
        active["extra"] = True
        try:
            yield
        finally:
            active["extra"] = False

    async def manager_stop(manager: HubManager) -> None:
        active["manager_stopped"] = True

    def factory(actual_ctx: Context, sid: str) -> sweeps.Launcher:
        def launch(req: RunRequest, key: str) -> RunRecord:
            entered.set()
            assert release.wait(5)
            assert active["extra"] and not active["manager_stopped"]
            return actual_ctx.create_run(
                make_record(
                    "drained",
                    environment_id=actual_ctx.descriptor.environment_id,
                    params=req.params,
                    seed=req.seed,
                    tags=req.tags,
                )
            )

        return launch

    monkeypatch.setattr(HubManager, "stop", manager_stop)
    monkeypatch.setattr(sweeps, "_local_launcher", factory)
    app = create_app(ctx.layout.home, hub=False, background_repair=False, lifespan_context=extra)
    client = TestClient(app, base_url=BASE)
    client.__enter__()
    response = client.post("/api/v1/sweeps", json=BODY)
    assert response.status_code == 200
    assert entered.wait(2)

    def close() -> None:
        client.__exit__(None, None, None)
        closed.set()

    closer = threading.Thread(target=close)
    closer.start()
    try:
        assert not closed.wait(0.05)
        assert active["extra"] and not active["manager_stopped"]
    finally:
        release.set()
        closer.join(5)
    assert closed.is_set() and active == {"extra": False, "manager_stopped": True}
    current = sweeps.summarize_sweep(ctx, "toy", response.json()["spec"]["id"])
    assert current.issuance.state == "interrupted" and current.issuance.reason == "shutdown"


@pytest.mark.parametrize("explicit", [False, True])
def test_zero_run_restart_retains_nondefault_options_and_effective_pin_after_checkout_changes(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch, explicit: bool
) -> None:
    from hypothex.core.sweep_issuance import SweepIssuer
    from tests.core.test_sweep_issuance import Launcher
    from tests.factories import git

    monkeypatch.setattr(SweepIssuer, "start", lambda *args: None)
    ctx.register_project(toy_repo)
    head = git(toy_repo, "rev-parse", "HEAD")
    tracked = toy_repo / "infer.py"
    tracked.write_text(tracked.read_text() + "\n# accepted patch\n")
    patch = git(toy_repo, "diff", "HEAD")
    body = {
        **BODY,
        "gpus": 2,
        "queue": False,
        "created_by": "agent:original",
        "task": "toy-acc",
        "hypothesis": "original nondefault",
    }
    if explicit:
        body.update(commit=head, diff=patch)
        git(toy_repo, "checkout", "--", "infer.py")
    app = create_app(ctx.layout.home, hub=False, background_repair=False)
    with TestClient(app, base_url=BASE) as client:
        accepted = client.post("/api/v1/sweeps", json=body).json()
        assert accepted["counts"]["total"] == 0 and accepted["issuance"]["state"] == "queued"
        assert accepted["spec"]["commit"] == head
        assert accepted["spec"]["diff"].strip() == patch.strip()
        tracked.write_text(tracked.read_text() + "\n# later checkout\n")
        git(toy_repo, "add", "infer.py")
        git(toy_repo, "commit", "-qm", "later checkout")
        assert git(toy_repo, "rev-parse", "HEAD") != head
        # A fresh coordinator has only persisted inputs, no request closure or first run.
        restored_ctx = Context.open(ctx.layout.home)
        restored = SweepIssuer(restored_ctx)
        fake = Launcher(restored_ctx)
        restored.tick(lambda _: fake)
        assert len(fake.calls) == 2
        for request in fake.calls:
            assert (
                request.gpus,
                request.queue,
                request.created_by,
                request.task,
                request.hypothesis,
            ) == (2, False, "agent:original", "toy-acc", "original nondefault")
            assert request.commit == head and str(request.diff).strip() == patch.strip()
        assert client.post("/api/v1/sweeps", json={**BODY, "seeds": [99]}).json() == accepted
