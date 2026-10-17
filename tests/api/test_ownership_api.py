import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hypothex.api.app import LaunchBody, create_app, launch_here
from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.records import ExecutorInfo, RunRecord, RunStatus
from hypothex.core.sweeps import SweepParam, SweepSpec, save_sweep
from tests.api.authkit import BASE, auth_app, bearer, token_for
from tests.factories import make_record

PY = sys.executable


@pytest.fixture
def hub(home: Path, toy_repo: Path) -> Iterator[tuple[FastAPI, TestClient, Context]]:
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    app = auth_app(home)
    with TestClient(app, base_url=BASE) as client:
        yield app, client, ctx


def queued(ctx: Context, run_id: str, owner: str | None) -> None:
    ctx.create_run(make_record(run_id, owner=owner, environment_id=ctx.descriptor.environment_id))


def launch_body(repo: Path, **over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "repo": str(repo),
        "command": [PY, "-c", "pass"],
        "hypothesis": "ownership",
        "created_by": "human:sv",
        "owner": "sv",
    }
    body.update(over)
    return body


def test_body_identity_is_ignored_with_auth_on(
    hub: tuple[FastAPI, TestClient, Context], toy_repo: Path
) -> None:
    app, client, ctx = hub
    carol = token_for(app.state.auth, "carol", "admin")  # a second admin, not the owner sv
    record = client.post("/api/v1/runs", json=launch_body(toy_repo), headers=bearer(carol)).json()
    assert (record["created_by"], record["owner"]) == ("human:carol", "carol")
    headers = {**bearer(carol), "X-Hypothex-Agent": "claude"}
    agent = client.post("/api/v1/runs", json=launch_body(toy_repo), headers=headers).json()
    assert (agent["created_by"], agent["owner"]) == ("agent:claude@carol", "carol")
    for run in (record, agent):
        control.wait_for_run(ctx, str(run["run_id"]), timeout=30)


def test_launch_scope_never_runs_code_on_the_hub(
    hub: tuple[FastAPI, TestClient, Context], toy_repo: Path
) -> None:
    # a run here executes as the hub's user and could read the owner's token in server.json
    app, client, ctx = hub
    alice = bearer(token_for(app.state.auth, "alice", "launch"))
    queued(ctx, "hers", "alice")
    refused = [
        client.post("/api/v1/runs", json=launch_body(toy_repo), headers=alice),
        client.post("/api/v1/hosts/local/runs", json={"project": "toy"}, headers=alice),
        client.post("/api/v1/runs/hers/rerun", json={}, headers=alice),
        client.post("/api/v1/runs/hers/reinfer", json={}, headers=alice),
        client.post(
            "/api/v1/sweeps",
            json={
                "project": "toy",
                "grid": [],
                "seeds": [1],
                "command": [PY, "-c", "pass"],
                "hypothesis": "x",
            },  # fmt: skip
            headers=alice,
        ),
    ]
    assert [r.status_code for r in refused] == [403] * 5
    assert {r.json()["error"] for r in refused} == {
        "runs on this machine need admin; launch on a host"
    }
    assert [r.run_id for r in ctx.index.list_runs(limit=None)] == ["hers"]


def test_auth_off_keeps_phase_2_identity(home: Path, toy_repo: Path) -> None:
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE) as client:
        record = client.post("/api/v1/runs", json=launch_body(toy_repo)).json()
    assert (record["created_by"], record["owner"]) == ("human:sv", None)
    control.wait_for_run(ctx, str(record["run_id"]), timeout=30)


def test_only_owner_or_admin_may_stop(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    alice = token_for(app.state.auth, "alice", "launch")
    admin = token_for(app.state.auth, "sv", "admin")
    for run_id, owner in (("svs", "sv"), ("hers", "alice"), ("legacy", None)):
        queued(ctx, run_id, owner)
    refused = client.post("/api/v1/runs/svs/stop", json={}, headers=bearer(alice))
    assert refused.status_code == 403
    assert refused.json()["error"] == "run owned by sv; stop needs owner or admin"
    assert (
        client.post("/api/v1/runs/legacy/stop", json={}, headers=bearer(alice)).status_code == 403
    )
    own = client.post("/api/v1/runs/hers/stop", json={}, headers=bearer(alice))
    assert own.json()["status"] == RunStatus.KILLED.value
    assert client.post("/api/v1/runs/svs/stop", json={}, headers=bearer(admin)).status_code == 200


def test_archive_needs_the_owner_but_tags_do_not(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    alice = token_for(app.state.auth, "alice", "launch")
    queued(ctx, "svs", "sv")
    assert (
        client.post("/api/v1/runs/svs/archive", json={}, headers=bearer(alice)).status_code == 403
    )
    tagged = client.post("/api/v1/runs/svs/tags", json={"add": ["seen"]}, headers=bearer(alice))
    assert tagged.json()["tags"] == ["seen"]


def test_sweep_cancel_needs_the_sweep_owner(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    alice = token_for(app.state.auth, "alice", "launch")
    save_sweep(
        ctx.layout,
        SweepSpec(
            id="s-0003",
            project="toy",
            task=None,
            host=None,
            grid=[SweepParam(name="x", values=["1"])],
            seeds=[1],
            command_template=["echo", "{x}"],
            created_by="human:sv",
            created_at=make_record().created_at,
            owner="sv",
        ),
    )
    resp = client.post("/api/v1/sweeps/toy/s-0003/cancel_queued", json={}, headers=bearer(alice))
    assert resp.status_code == 403 and "cancel_queued needs owner or admin" in resp.json()["error"]


def test_owner_me_filters_runs(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    alice = token_for(app.state.auth, "alice", "read")
    queued(ctx, "a1", "alice")
    queued(ctx, "s1", "sv")
    mine = client.get("/api/v1/runs?owner=me", headers=bearer(alice)).json()
    assert [r["run_id"] for r in mine] == ["a1"]
    theirs = client.get("/api/v1/runs?owner=sv", headers=bearer(alice)).json()
    assert [r["run_id"] for r in theirs] == ["s1"]


def test_owner_me_with_auth_off_lists_every_run(home: Path) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    ctx: Context = app.state.ctx
    queued(ctx, "a1", "alice")
    queued(ctx, "n1", None)  # what an auth-off launch records
    with TestClient(app, base_url=BASE) as client:
        mine = client.get("/api/v1/runs?owner=me").json()
    assert {r["run_id"] for r in mine} == {"a1", "n1"}


def test_overview_rows_name_their_owner(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    reader = token_for(app.state.auth, "bo", "read")
    queued(ctx, "al-fail", "alice")
    ctx.update_run(
        "al-fail",
        "run.failed",
        lambda r: r.model_copy(update={"status": RunStatus.FAILED, "ended_at": r.created_at}),
    )
    queued(ctx, "sv-q", "sv")
    body = client.get("/api/v1/overview", headers=bearer(reader)).json()
    assert {t["run_id"]: t["owner"] for t in body["timeline"]} == {"al-fail": "alice", "sv-q": "sv"}
    assert [(f["run_id"], f["owner"]) for f in body["failures"]] == [("al-fail", "alice")]
    assert body["ideas"] and all(i["owner"] in ("alice", "sv") for i in body["ideas"])
    assert [r["owner"] for r in body["running"]] == ["sv"]


def test_note_author_is_the_caller(hub: tuple[FastAPI, TestClient, Context]) -> None:
    app, client, ctx = hub
    alice = token_for(app.state.auth, "alice", "launch")
    queued(ctx, "svs", "sv")
    body = {"text": "looks good", "author": "human:sv"}
    assert client.post("/api/v1/runs/svs/notes", json=body, headers=bearer(alice)).json() == {
        "ok": True
    }
    assert "— human:alice" in ctx.store.read_notes("toy", "svs")


def test_a_command_id_is_bound_to_its_caller_and_route(
    hub: tuple[FastAPI, TestClient, Context],
) -> None:
    app, client, ctx = hub
    admin = bearer(token_for(app.state.auth, "sv", "admin"))
    alice = bearer(token_for(app.state.auth, "alice", "launch"))
    reader = token_for(app.state.auth, "bo", "read")
    queued(ctx, "r1", "sv")
    tags = "/api/v1/runs/r1/tags"
    first = client.post(tags, json={"add": ["a"], "command_id": "c1"}, headers=admin).json()
    assert first["tags"] == ["a"]
    # the same caller retrying gets the stored result, even with an edited body (phase 1)
    again = client.post(tags, json={"add": ["z"], "command_id": "c1"}, headers=admin).json()
    assert again["tags"] == ["a"]
    # another caller with the same id runs their own command
    hers = client.post(tags, json={"add": ["b"], "command_id": "c1"}, headers=alice).json()
    assert hers["tags"] == ["a", "b"]
    # a reader replaying the id on a read route gets that route's answer, not the admin's
    session = app.state.auth.authenticate(reader)
    assert session is not None
    out = client.post(
        f"/api/v1/auth/sessions/{session.session_id}/revoke",
        json={"command_id": "c1"},
        headers=bearer(reader),
    ).json()
    assert "tags" not in out and out["user"] == "bo"


def test_rerun_belongs_to_the_caller(
    hub: tuple[FastAPI, TestClient, Context], toy_repo: Path
) -> None:
    app, client, ctx = hub
    admin = token_for(app.state.auth, "sv", "admin")
    carol = token_for(app.state.auth, "carol", "admin")
    parent = client.post("/api/v1/runs", json=launch_body(toy_repo), headers=bearer(admin)).json()
    control.wait_for_run(ctx, str(parent["run_id"]), timeout=30)
    child = client.post(
        f"/api/v1/runs/{parent['run_id']}/rerun", json={}, headers=bearer(carol)
    ).json()
    assert (child["owner"], child["created_by"], child["parent"]) == (
        "carol",
        "human:carol",
        parent["run_id"],
    )
    control.wait_for_run(ctx, str(child["run_id"]), timeout=30)


def test_batch_cancel_checks_every_owner_before_stopping_and_keeps_receipts(
    hub: tuple[FastAPI, TestClient, Context],
) -> None:
    app, client, ctx = hub
    alice = bearer(token_for(app.state.auth, "alice", "launch"))
    admin = bearer(token_for(app.state.auth, "sv", "admin"))
    reader = bearer(token_for(app.state.auth, "reader", "read"))
    for rid, owner in (("own", "alice"), ("other", "sv"), ("later", "alice")):
        queued(ctx, rid, owner)
    ctx.create_run(
        make_record(
            "started",
            owner="alice",
            status=RunStatus.RUNNING,
            environment_id=ctx.descriptor.environment_id,
        )
    )
    url = "/api/v1/runs/stop_queued"
    assert client.post(url, json={"run_ids": ["own"]}, headers=reader).status_code == 403
    denied = client.post(url, json={"run_ids": ["own", "other"]}, headers=alice)
    assert denied.status_code == 403
    assert ctx.find_record("own").status == RunStatus.QUEUED  # no partial unauthorized batch
    first = client.post(
        url, json={"run_ids": ["own", "started"], "command_id": "batch"}, headers=alice
    )
    assert first.status_code == 200 and first.json()["asked"] == 2
    assert ctx.find_record("own").status == RunStatus.KILLED
    assert ctx.find_record("started").status == RunStatus.RUNNING
    retry = client.post(url, json={"run_ids": ["later"], "command_id": "batch"}, headers=alice)
    assert retry.json() == first.json() and ctx.find_record("later").status == RunStatus.QUEUED
    assert (
        client.post(
            url, json={"run_ids": ["other"], "command_id": "batch"}, headers=admin
        ).status_code
        == 200
    )
    assert ctx.find_record("other").status == RunStatus.KILLED
    missing = client.post(url, json={"run_ids": ["later", "missing"]}, headers=alice)
    assert missing.status_code == 200 and missing.json()["failed"] == 1
    assert ctx.find_record("later").status == RunStatus.KILLED


def test_owner_paging_retains_queue_ranks_host_state_and_cursor_validation(
    hub: tuple[FastAPI, TestClient, Context],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, client, ctx = hub
    reader = bearer(token_for(app.state.auth, "alice", "read"))
    when = make_record().created_at
    for rid, owner, ticket in (("a", "alice", 10), ("b", "sv", 20), ("c", "alice", 30)):
        ctx.create_run(
            make_record(
                rid,
                owner=owner,
                created_at=when,
                environment_id="env-remote",
                executor=ExecutorInfo(queue_position=ticket),
            )
        )
    monkeypatch.setattr(app.state.hub, "host_for_environment", lambda env: "gpu1")
    monkeypatch.setattr(app.state.hub, "state", lambda host: SimpleNamespace(state="connected"))
    first = client.get("/api/v1/runs", params={"owner": "me", "limit": 1}, headers=reader).json()
    assert [r["run_id"] for r in first] == ["c"]
    second = client.get(
        "/api/v1/runs",
        params={
            "owner": "me",
            "limit": 1,
            "before_created_at": first[0]["created_at"],
            "before_run_id": first[0]["run_id"],
        },
        headers=reader,
    ).json()
    assert [r["run_id"] for r in second] == ["a"]
    assert [r["executor"]["queue_position"] for r in first + second] == [3, 1]
    assert {r["host_state"] for r in first + second} == {"connected"}
    half = client.get("/api/v1/runs", params={"before_run_id": "c"}, headers=reader)
    assert half.status_code == 400 and "together" in half.json()["error"]


@pytest.mark.parametrize(
    ("action", "body"),
    [
        ("tags", {"add": ["seen"]}),
        ("star", {"on": True}),
        ("archive", {"on": True}),
        ("notes", {"text": "seen"}),
    ],
)
def test_unserved_mirror_edits_are_refused_but_imported_run_edits_remain_local(
    hub: tuple[FastAPI, TestClient, Context],
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    body: dict[str, object],
) -> None:
    app, client, ctx = hub
    admin = bearer(token_for(app.state.auth, "sv", "admin"))
    ctx.create_run(make_record("foreign", owner="sv", environment_id="env-remote"))
    monkeypatch.setattr(app.state.hub, "host_for_environment", lambda env: None)
    monkeypatch.setattr(app.state.hub, "mirrored_from", lambda env: "removed-host")
    refused = client.post(f"/api/v1/runs/foreign/{action}", json=body, headers=admin)
    assert (
        refused.status_code == 503 and "mirrored from host removed-host" in refused.json()["error"]
    )
    monkeypatch.setattr(app.state.hub, "mirrored_from", lambda env: None)
    assert (
        client.post(f"/api/v1/runs/foreign/{action}", json=body, headers=admin).status_code == 200
    )


def test_task_reeval_keeps_host_partition_timeout_failure_aggregation_and_caller_receipts(
    hub: tuple[FastAPI, TestClient, Context],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hypothex.api import app as api_module
    from hypothex.core.evaluation import EvalReport
    from hypothex.remote.hub import HostUnavailableError

    app, client, ctx = hub
    for rid, env in (
        ("here", ctx.descriptor.environment_id),
        ("remote", "env-gpu"),
        ("down1", "env-down"),
        ("down2", "env-down"),
    ):
        ctx.create_run(
            make_record(
                rid, task="toy-acc", status=RunStatus.FINISHED, owner="alice", environment_id=env
            )
        )
    local_calls: list[list[str] | None] = []
    sent: list[tuple[str, str, dict[str, Any], float | None]] = []

    def local_reeval(context: Context, **kwargs: Any) -> EvalReport:
        local_calls.append(kwargs.get("run_ids"))
        return EvalReport(evaluated=kwargs.get("run_ids") or [])

    class HostClient:
        def __init__(self, name: str) -> None:
            self.name = name

        def post_json(
            self, path: str, body: dict[str, Any], *, timeout: float | None = None
        ) -> dict[str, Any]:
            sent.append((self.name, path, body, timeout))
            if self.name == "down":
                raise HostUnavailableError("offline")
            return EvalReport(evaluated=["remote"]).model_dump(mode="json")

    monkeypatch.setattr(api_module, "reeval", local_reeval)
    monkeypatch.setattr(
        app.state.hub,
        "host_for_environment",
        lambda env: {"env-gpu": "gpu", "env-down": "down"}.get(env),
    )
    monkeypatch.setattr(app.state.hub, "mirrored_from", lambda env: None)
    monkeypatch.setattr(app.state.hub, "names", lambda: ["gpu", "down"])
    monkeypatch.setattr(app.state.hub, "client", HostClient)
    url = "/api/v1/tasks/toy/toy-acc/reeval"
    body = {"force": True, "command_id": "same"}
    alice = bearer(token_for(app.state.auth, "alice", "launch"))
    first = client.post(url, json=body, headers=alice)
    assert first.status_code == 200 and set(first.json()["evaluated"]) == {"here", "remote"}
    assert set(first.json()["skipped"]) == {"down1", "down2"}
    assert local_calls == [["here"]] and len(sent) == 2  # one request to a down host
    assert all(timeout == api_module.REEVAL_FORWARD_SECONDS for _, _, _, timeout in sent)
    remote_body = next(payload for host, _, payload, _ in sent if host == "gpu")
    assert remote_body["command_id"] == f"alice|launch|POST {url}|same:remote"
    assert client.post(url, json=body, headers=alice).json() == first.json() and len(sent) == 2
    admin = bearer(token_for(app.state.auth, "sv", "admin"))
    assert client.post(url, json=body, headers=admin).status_code == 200 and len(sent) == 4
    assert any(
        payload["command_id"] == f"sv|admin|POST {url}|same:remote" for _, _, payload, _ in sent
    )
    single = client.post("/api/v1/runs/remote/reeval", json={"command_id": "one"}, headers=alice)
    assert single.status_code == 200
    assert sent[-1][3] == api_module.REEVAL_FORWARD_SECONDS
    assert sent[-1][2]["command_id"] == "alice|launch|POST /api/v1/runs/remote/reeval|one"


def test_local_reinfer_keeps_template_overrides_with_new_owner(
    hub: tuple[FastAPI, TestClient, Context],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, client, ctx = hub
    queued(ctx, "parent", "sv")
    seen: list[dict[str, Any]] = []

    def reinfer(context: Context, run_id: str, **kwargs: Any) -> RunRecord:
        seen.append(kwargs)
        return context.find_record(run_id)

    monkeypatch.setattr(control, "reinfer", reinfer)
    carol = bearer(token_for(app.state.auth, "carol", "admin"))
    response = client.post(
        "/api/v1/runs/parent/reinfer",
        json={
            "checkpoint": "/tmp/model.pt",
            "vars": {"temperature": "0.2"},
        },
        headers=carol,
    )
    assert response.status_code == 200
    assert seen == [
        {
            "checkpoint": "/tmp/model.pt",
            "vars": {"temperature": "0.2"},
            "created_by": "human:carol",
            "owner": "carol",
        }
    ]


def test_scoped_rename_reset_receipts_forwarding_and_literal_search(
    hub: tuple[FastAPI, TestClient, Context],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Naming retains caller receipts, remote ownership and literal paged search."""
    app, client, ctx = hub
    alice = bearer(token_for(app.state.auth, "alice", "launch"))
    admin = bearer(token_for(app.state.auth, "sv", "admin"))
    reader = bearer(token_for(app.state.auth, "reader", "read"))
    for run_id, owner in [("a", "alice"), ("b", "alice"), ("c", "sv")]:
        queued(ctx, run_id, owner)
    url = "/api/v1/runs/a/name"
    body = {"name": "wide%_ beam", "command_id": "name-1"}
    assert client.post(url, json=body, headers=reader).status_code == 403
    first = client.post(url, json=body, headers=alice)
    assert first.status_code == 200 and first.json()["name"] == "wide%_ beam"
    assert client.post(url, json={**body, "name": "changed"}, headers=alice).json() == first.json()
    assert client.post(url, json={**body, "name": None}, headers=admin).json()["name"] is None
    assert client.post(url, json={"name": "wide%_ beam"}, headers=alice).status_code == 200
    assert (
        client.post("/api/v1/runs/b/name", json={"name": "wide%_ b"}, headers=alice).status_code
        == 200
    )
    assert (
        client.post("/api/v1/runs/c/name", json={"name": "wide%_ c"}, headers=alice).status_code
        == 200
    )
    query = {"q": "wide%_", "owner": "me", "status": "queued", "limit": 1}
    first_page = client.get("/api/v1/runs", params=query, headers=alice).json()
    second_page = client.get(
        "/api/v1/runs",
        params={
            **query,
            "before_created_at": first_page[0]["created_at"],
            "before_run_id": first_page[0]["run_id"],
        },
        headers=alice,
    ).json()
    assert {r["run_id"] for r in first_page + second_page} == {"a", "b"}
    assert (
        client.get("/api/v1/runs", params={"q": "nomatch", "owner": "me"}, headers=alice).json()
        == []
    )
    assert client.get("/api/v1/runs", params={"q": "x" * 201}, headers=alice).status_code == 422
    sent: list[tuple[str, dict[str, Any]]] = []
    ctx.create_run(make_record("remote", owner="sv", environment_id="remote-env"))
    monkeypatch.setattr(
        app.state.hub, "host_for_environment", lambda env: "gpu1" if env == "remote-env" else None
    )

    def post(path: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        sent.append((path, payload))
        return {"name": payload["name"]}

    monkeypatch.setattr(app.state.hub, "client", lambda host: SimpleNamespace(post_json=post))
    response = client.post("/api/v1/runs/remote/name", json=body, headers=alice)
    assert response.status_code == 200 and sent == [
        (
            "/api/v1/runs/remote/name",
            {
                "name": "wide%_ beam",
                "created_by": "api",
                "owner": None,
                "command_id": "alice|launch|POST /api/v1/runs/remote/name|name-1",
            },
        )
    ]


def test_task_workspace_and_overview_preserve_individual_mixed_owners(
    hub: tuple[FastAPI, TestClient, Context],
    toy_repo: Path,
) -> None:
    """Current task and overview DTO fields survive adding per-run ownership."""
    from hypothex.core.overview import build_overview
    from hypothex.core.taskruns import task_runs
    from tests.core.test_taskruns import _run, _scored

    app, client, ctx = hub
    for index, owner in enumerate(["alice", "sv", None]):
        record = _run(ctx, toy_repo, f"owned-{index}", "same", owner=owner, seed=index)
        _scored(ctx, record, 3)
    reader = bearer(token_for(app.state.auth, "reader", "read"))
    payload = client.get("/api/v1/tasks/toy/toy-acc/runs", headers=reader)
    assert payload.status_code == 200
    workspace = payload.json()
    assert {r["run_id"]: r["owner"] for r in workspace["runs"]} == {
        "owned-0": "alice",
        "owned-1": "sv",
        "owned-2": None,
    }
    assert set(workspace["groups"][0]["run_ids"]) == {"owned-0", "owned-1", "owned-2"}
    assert "owner" not in workspace["groups"][0]
    retained = {"name", "derived_name", "renamed", "params", "scores", "created_by", "cost_usd"}
    assert retained <= workspace["runs"][0].keys()
    assert {r.run_id: r.owner for r in task_runs(ctx, "toy-acc").runs} == {
        "owned-0": "alice",
        "owned-1": "sv",
        "owned-2": None,
    }
    overview = build_overview(ctx)
    assert {r.run_id: r.owner for r in overview.recent} == {
        "owned-0": "alice",
        "owned-1": "sv",
        "owned-2": None,
    }
    assert {
        r["run_id"]: r["owner"]
        for r in client.get("/api/v1/overview", headers=reader).json()["recent"]
    } == {"owned-0": "alice", "owned-1": "sv", "owned-2": None}


def test_durable_scoped_sweep_receipts_reopen_ownership_and_cancellation(
    home: Path,
    toy_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepted scopes survive restart and cancellation checks precede durable intent."""
    from hypothex.core import sweeps
    from hypothex.core.execution import RunRequest
    from hypothex.core.sweep_issuance import SweepIssuer

    monkeypatch.setattr(SweepIssuer, "start", lambda *args: None)
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    app = auth_app(home)
    body = {
        "project": "toy",
        "grid": [],
        "seeds": [1],
        "command": ["true"],
        "hypothesis": "preserve",
        "command_id": "shared",
        "owner": "forged",
    }
    with TestClient(app, base_url=BASE) as client:
        admin = bearer(token_for(app.state.auth, "sv", "admin"))
        carol = bearer(token_for(app.state.auth, "carol", "admin"))
        alice = bearer(token_for(app.state.auth, "alice", "launch"))
        accepted = client.post("/api/v1/sweeps", json=body, headers=admin).json()
        retry = client.post("/api/v1/sweeps", json={**body, "hypothesis": "edited"}, headers=admin)
        assert retry.json() == accepted
        other = client.post("/api/v1/sweeps", json=body, headers=carol).json()
        assert other["spec"]["id"] != accepted["spec"]["id"]
        assert (accepted["spec"]["owner"], other["spec"]["owner"]) == ("sv", "carol")
        sid = accepted["spec"]["id"]
        route = f"/api/v1/sweeps/toy/{sid}"
        assert client.post("/api/v1/sweeps", json=body, headers=alice).status_code == 403
        assert client.post(route + "/extend", json={"seeds": [2]}, headers=alice).status_code == 403
        assert client.post(route + "/extend", json={"seeds": [2]}, headers=admin).status_code == 409
        assert client.post(route + "/cancel_queued", json={}, headers=alice).status_code == 403
        assert (
            app.state.ctx.events.sweep_operation("toy", sid)["issuance"]["cancel_requested"]
            is False
        )
    reopened = Context.open(home)
    issuer = SweepIssuer(reopened)
    seen: list[RunRequest] = []

    def factory(spec: SweepSpec) -> sweeps.Launcher:
        def launch(req: RunRequest, key: str) -> RunRecord:
            seen.append(req)
            return reopened.create_run(
                make_record(
                    f"issued-{len(seen)}",
                    owner=req.owner,
                    created_by=req.created_by,
                    tags=req.tags,
                    seed=req.seed,
                    params=req.params,
                    environment_id=reopened.descriptor.environment_id,
                )
            )

        return launch

    issuer.tick(factory)
    assert {(r.created_by, r.owner) for r in seen} == {("human:sv", "sv"), ("human:carol", "carol")}
    assert sweeps.load_sweep(reopened.layout, "toy", sid).owner == "sv"
    with TestClient(auth_app(home), base_url=BASE) as client:
        stop_order: list[bool] = []
        from hypothex.api import app as api_module

        real_cancel = api_module.cancel_queued

        def cancel(context: Context, project: str, sweep_id: str, **kwargs: Any) -> Any:
            stop_order.append(
                context.events.sweep_operation(project, sweep_id)["issuance"]["cancel_requested"]
            )
            return real_cancel(context, project, sweep_id, **kwargs)

        monkeypatch.setattr(api_module, "cancel_queued", cancel)
        pending = client.post(
            "/api/v1/sweeps", json={**body, "command_id": "pending"}, headers=admin
        ).json()
        pending_route = f"/api/v1/sweeps/toy/{pending['spec']['id']}"
        response = client.post(pending_route + "/cancel_queued", json={}, headers=admin)
        assert response.status_code == 200 and stop_order == [True]


def test_scoped_sweep_never_replays_or_inherits_a_raw_legacy_claim(
    home: Path,
    toy_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An old unscoped command ID cannot select a scoped caller's receipt."""
    from hypothex.core import sweeps
    from hypothex.core.sweep_issuance import SweepIssuer

    monkeypatch.setattr(SweepIssuer, "start", lambda *args: None)
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    legacy = sweeps.create_sweep(
        ctx, project="toy", grid=[], seeds=[1], command=["true"], command_id="legacy"
    )
    app = auth_app(home)
    with TestClient(app, base_url=BASE) as client:
        admin = bearer(token_for(app.state.auth, "sv", "admin"))
        response = client.post(
            "/api/v1/sweeps",
            json={
                "project": "toy",
                "grid": [],
                "seeds": [1],
                "command": ["true"],
                "command_id": "legacy",
                "hypothesis": "scoped separation",
            },
            headers=admin,
        )
        assert response.status_code == 200
        assert response.json()["spec"]["id"] != legacy.id
        assert response.json()["spec"]["owner"] == "sv"
        assert ctx.events.sweep_operation_by_key("legacy") is None
        assert ctx.events.sweep_operation_by_key("sv|admin|POST /api/v1/sweeps|legacy") is not None


def _legacy_receipt(ctx: Context, command_id: str, result: str) -> None:
    """Seed a pre-upgrade unbound receipt without executing its uncertain action."""
    with ctx.events._conn() as conn:
        conn.execute(
            "INSERT INTO receipts(command_id, result, created_at) VALUES (?,?,?)",
            (command_id, result, "2026-01-01T00:00:00+00:00"),
        )


@pytest.mark.parametrize("marker", ["__pending__", "__interrupted__:legacy"])
@pytest.mark.parametrize("action", ["stop", "archive", "tags"])
def test_legacy_unknown_outcome_never_mutates_an_existing_run(
    home: Path,
    marker: str,
    action: str,
) -> None:
    """Unbound pre-upgrade interruptions fail closed for the original local owner."""
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    ctx = app.state.ctx
    queued(ctx, "untouched", None)
    _legacy_receipt(ctx, "legacy-action", marker)
    with TestClient(app, base_url=BASE) as client:
        before = ctx.find_record("untouched").model_dump(mode="json")
        response = client.post(
            f"/api/v1/runs/untouched/{action}",
            json={
                "command_id": "legacy-action",
                "add": ["must-not-appear"],
            },
        )
        assert response.status_code == 409
        assert response.json()["type"] == "CommandInterruptedError"
        assert ctx.find_record("untouched").model_dump(mode="json") == before
        assert (
            ctx.events.command_result(
                f"local|admin|POST /api/v1/runs/untouched/{action}|legacy-action"
            )
            is None
        )


@pytest.mark.parametrize(
    "marker",
    [
        "__pending__",
        "__interrupted__:legacy",
        '{"private_legacy_payload":"not-the-caller"}',
    ],
)
def test_scoped_actions_ignore_unbound_receipts_and_still_check_authorization(
    home: Path,
    marker: str,
) -> None:
    """Legacy state cannot disclose results or bypass scoped ownership/revocation."""
    app = auth_app(home)
    ctx = app.state.ctx
    queued(ctx, "mine", "alice")
    queued(ctx, "theirs", "sv")
    _legacy_receipt(ctx, "legacy-action", marker)
    token = token_for(app.state.auth, "alice", "launch")
    reader = token_for(app.state.auth, "reader", "read")
    body = {"command_id": "legacy-action"}
    with TestClient(app, base_url=BASE) as client:
        assert (
            client.post("/api/v1/runs/mine/stop", json=body, headers=bearer(reader)).status_code
            == 403
        )
        assert (
            client.post("/api/v1/runs/theirs/stop", json=body, headers=bearer(token)).status_code
            == 403
        )
        mine = client.post("/api/v1/runs/mine/stop", json=body, headers=bearer(token))
        assert mine.status_code == 200 and mine.json()["status"] == "killed"
        assert "private_legacy_payload" not in mine.json()
        assert ctx.find_record("theirs").status == RunStatus.QUEUED
        principal = app.state.auth.authenticate(token)
        app.state.auth.revoke(principal.session_id, by=principal)
        assert (
            client.post("/api/v1/runs/mine/stop", json=body, headers=bearer(token)).status_code
            == 401
        )
    with ctx.events._conn() as conn:
        assert (
            conn.execute(
                "SELECT result FROM receipts WHERE command_id=?", ("legacy-action",)
            ).fetchone()[0]
            == marker
        )


@pytest.mark.parametrize("marker", ["__pending__", "{}", '{"old":"result"}'])
def test_namespaced_local_receipt_precedes_unbound_legacy_interruption(
    home: Path, marker: str
) -> None:
    """A completed current-route receipt remains immutable on a later retry."""
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    ctx = app.state.ctx
    queued(ctx, "mine", None)
    route = "/api/v1/runs/mine/tags"
    with TestClient(app, base_url=BASE) as client:
        first = client.post(route, json={"command_id": "shared", "add": ["first"]})
        assert first.status_code == 200
        _legacy_receipt(ctx, "shared", marker)
        repeat = client.post(route, json={"command_id": "shared", "add": ["second"]})
        assert repeat.status_code == 200 and repeat.json() == first.json()
        assert ctx.find_record("mine").tags == ["first"]


@pytest.mark.parametrize("scoped", [False, True])
def test_host_principal_does_not_consult_unbound_legacy_receipts(home: Path, scoped: bool) -> None:
    """Forwarded host callers cannot accidentally inherit the local compatibility path."""
    app = create_app(
        home,
        auth=scoped,
        auth_token="host-test",
        token_is_host=True,
        background_repair=False,
        hub=False,
        ui_dir=home / "no-ui",
    )
    ctx = app.state.ctx
    queued(ctx, "mine", "alice")
    _legacy_receipt(ctx, "shared", "__pending__")
    with TestClient(app, base_url=BASE) as client:
        response = client.post(
            "/api/v1/runs/mine/stop", json={"command_id": "shared"}, headers=bearer("host-test")
        )
    assert response.status_code == 200 and response.json()["status"] == "killed"
    with ctx.events._conn() as conn:
        assert (
            conn.execute("SELECT result FROM receipts WHERE command_id=?", ("shared",)).fetchone()[
                0
            ]
            == "__pending__"
        )


@pytest.mark.parametrize("marker", ['{"private_legacy_payload":"another-route"}', "{}"])
def test_completed_raw_local_receipt_is_never_returned_as_a_bound_result(
    home: Path, marker: str
) -> None:
    """Only the current caller/route receipt can supply the API result payload."""
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    ctx = app.state.ctx
    queued(ctx, "mine", None)
    _legacy_receipt(ctx, "shared", marker)
    with TestClient(app, base_url=BASE) as client:
        response = client.post(
            "/api/v1/runs/mine/tags", json={"command_id": "shared", "add": ["new"]}
        )
    assert response.status_code == 409
    assert response.json()["type"] == "CommandInterruptedError"
    assert ctx.find_record("mine").tags == []
    assert "private_legacy_payload" not in response.json()
    assert ctx.events.command_result("local|admin|POST /api/v1/runs/mine/tags|shared") is None


@pytest.mark.parametrize("root_token", [None, "synthetic-root-token"])
def test_completed_preupgrade_launch_receipt_cannot_execute_again(
    home: Path, toy_repo: Path, root_token: str | None
) -> None:
    """A legacy completed launch cannot create a second run or repeat its side effect."""
    app = create_app(
        home,
        auth=False,
        auth_token=root_token,
        hub=False,
        background_repair=False,
        ui_dir=home / "no-ui",
    )
    ctx = app.state.ctx
    counter = home / "execution-count.txt"
    body = LaunchBody(
        repo=str(toy_repo),
        command=[
            PY,
            "-c",
            f"from pathlib import Path; Path({str(counter)!r}).open('a').write('executed\\n')",
        ],
        hypothesis="Migration receipt replay test",
        command_id="preupgrade-successful-launch",
    )
    first = ctx.events.run_once(
        body.command_id, lambda: to_jsonable(launch_here(ctx, body, body.repo))
    )
    control.wait_for_run(ctx, first["run_id"], timeout=30)
    assert counter.read_text().splitlines() == ["executed"]
    headers = {} if root_token is None else bearer(root_token)
    with TestClient(app, base_url=BASE) as client:
        response = client.post("/api/v1/runs", json=body.model_dump(mode="json"), headers=headers)
        if response.status_code == 200:
            control.wait_for_run(ctx, response.json()["run_id"], timeout=30)
    assert response.status_code == 409
    assert response.json()["type"] == "CommandInterruptedError"
    assert "run_id" not in response.json()
    assert counter.read_text().splitlines() == ["executed"]
    assert [r.run_id for r in ctx.index.list_runs(limit=None)] == [first["run_id"]]
    assert ctx.events.command_result("local|admin|POST /api/v1/runs|" + body.command_id) is None
