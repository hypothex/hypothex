"""Cross-layer API contracts remaining after the first dogfood integration."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from hypothex.api import app as app_module
from hypothex.api.app import HubManager, create_app
from hypothex.core import control
from hypothex.core import sweeps as sweeps_module
from hypothex.core.context import Context
from hypothex.core.errors import RunError
from hypothex.core.ids import utcnow
from hypothex.core.records import Artifact, RunStatus
from hypothex.core.sweeps import SweepIncompleteError, SweepParam, create_sweep, sweep_tag
from hypothex.remote.config import HostSpec, SlurmDefaults
from hypothex.remote.hub import HostState, HostUnavailableError, Hub
from hypothex.remote.ssh import SshError
from tests.api.envserver import write_hosts
from tests.factories import make_record

BASE = "http://127.0.0.1:7777"


@pytest.mark.parametrize("mode", ["disabled", "not_started", "error", "not_applied"])
def test_offline_host_keeps_its_unique_verified_cursor_identity(ctx: Context, mode: str) -> None:
    write_hosts(ctx.layout.home, {"gpu1": HostSpec(route="url", url="http://127.0.0.1:9")})
    ctx.index.set_cursor("gpu1", "env-known", 0)
    manager = HubManager(ctx)
    if mode == "disabled":
        manager.disabled["gpu1"] = utcnow()
    elif mode == "error":
        manager.error = "invalid host configuration"
    elif mode == "not_applied":
        manager.hub = Mock(spec=Hub)
        manager.hub.state.side_effect = HostUnavailableError("not applied")
    assert manager.state("gpu1").environment_id == "env-known"
    assert manager.host_for_environment("env-known") == "gpu1"


def test_ambiguous_host_history_is_not_an_active_serving_identity(ctx: Context) -> None:
    write_hosts(ctx.layout.home, {"gpu1": HostSpec(route="url", url="http://127.0.0.1:9")})
    ctx.index.set_cursor("gpu1", "env-old", 200)
    ctx.index.set_cursor("gpu1", "env-new", 0)
    manager = HubManager(ctx)
    assert manager.state("gpu1").environment_id is None
    assert manager.host_for_environment("env-old") is None
    assert manager.host_for_environment("env-new") is None
    assert manager.mirrored_from("env-old") == "gpu1"
    assert set(manager.environment_ids(manager.state("gpu1"))) == {"env-old", "env-new"}


def test_current_identity_blocks_historical_execution_but_keeps_provenance(
    ctx: Context, toy_repo: Path
) -> None:
    ctx.register_project(toy_repo)
    write_hosts(ctx.layout.home, {"gpu1": HostSpec(route="url", url="http://127.0.0.1:9")})
    ctx.index.set_cursor("gpu1", "env-old", 100)
    ctx.index.set_cursor("gpu1", "env-new", 0)
    for run_id, env in (("old", "env-old"), ("new", "env-new")):
        ctx.create_run(make_record(run_id, environment_id=env))
    app = create_app(ctx.layout.home, hub=False, background_repair=False)
    with TestClient(app, base_url=BASE) as client:
        manager = app.state.hub
        manager.hub = Mock(spec=Hub)
        manager.hub.state.return_value = HostState(
            name="gpu1", kind="ssh", state="connected", since=utcnow(), environment_id="env-new"
        )
        manager._seen["env-old"] = "gpu1"
        assert client.get("/api/v1/runs/old").json()["served"] is False
        assert client.get("/api/v1/runs/new").json()["served"] is True
        assert manager.host_for_environment("env-old") is None
        for action in ("rerun", "reinfer", "reeval", "stop"):
            response = client.post(f"/api/v1/runs/old/{action}", json={})
            assert response.status_code == 503, response.text
            assert "no configured host serves" in response.json()["error"]
        assert manager.mirrored_from("env-old") == "gpu1"
        manager.disabled["gpu1"] = utcnow()
        manager.hub = None
        assert manager.state("gpu1").environment_id == "env-new"
        assert manager.host_for_environment("env-old") is None
        assert client.get("/api/v1/runs/new").json()["served"] is True


def test_run_detail_serving_distinguishes_local_known_offline_and_unknown(
    ctx: Context, toy_repo: Path
) -> None:
    ctx.register_project(toy_repo)
    write_hosts(ctx.layout.home, {"gpu1": HostSpec(route="url", url="http://127.0.0.1:9")})
    ctx.index.set_cursor("gpu1", "env-known", 0)
    ctx.index.set_cursor("removed", "env-removed", 5)
    for name, env in (
        ("local", ctx.descriptor.environment_id),
        ("known", "env-known"),
        ("unknown", "env-unknown"),
        ("removed", "env-removed"),
    ):
        ctx.create_run(make_record(name, environment_id=env))
    with TestClient(
        create_app(ctx.layout.home, hub=False, background_repair=False), base_url=BASE
    ) as c:
        assert {
            name: c.get(f"/api/v1/runs/{name}").json()["served"]
            for name in ("local", "known", "unknown", "removed")
        } == {"local": True, "known": True, "unknown": False, "removed": False}


def test_slurm_defaults_are_exposed_while_the_host_is_offline(ctx: Context) -> None:
    defaults = SlurmDefaults(partition="gpu", account="lab", time="03:00:00", gpus=2)
    write_hosts(
        ctx.layout.home,
        {"cluster": HostSpec(route="url", url="http://127.0.0.1:9", kind="slurm", slurm=defaults)},
    )
    with TestClient(
        create_app(ctx.layout.home, hub=False, background_repair=False), base_url=BASE
    ) as c:
        rows = c.get("/api/v1/hosts").json()
        assert rows[0]["slurm"] is None
        assert rows[1]["state"]["state"] == "disabled"
        assert rows[1]["slurm"]["defaults"] == defaults.model_dump(mode="json")


@pytest.mark.parametrize("remote", [False, True])
def test_reinfer_variables_cross_the_local_and_remote_api_boundary(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch, remote: bool
) -> None:
    ctx.register_project(toy_repo)
    env = "env-host" if remote else ctx.descriptor.environment_id
    record = ctx.create_run(make_record("parent", environment_id=env))
    seen: list[dict[str, object]] = []

    def reinfer(context: Context, run_id: str, **kwargs: object) -> object:
        seen.append(kwargs)
        return record

    monkeypatch.setattr(control, "reinfer", reinfer)
    write_hosts(ctx.layout.home, {"gpu1": HostSpec(route="url", url="http://127.0.0.1:9")})
    ctx.index.set_cursor("gpu1", "env-host", 0)
    app = create_app(ctx.layout.home, hub=False, background_repair=False)
    with TestClient(app, base_url=BASE) as client:
        transport = Mock()
        transport.post_json.return_value = record.model_dump(mode="json")
        monkeypatch.setattr(app.state.hub, "client", lambda name: transport)
        response = client.post(
            "/api/v1/runs/parent/reinfer",
            json={"checkpoint": "chosen", "vars": {"temperature": "2"}, "created_by": "agent:test"},
        )
        assert response.status_code == 200, response.text
        payload = transport.post_json.call_args.args[1] if remote else seen[0]
        assert payload["vars"] == {"temperature": "2"}
        assert payload["checkpoint"] == "chosen"
        assert payload["created_by"] == "agent:test"


def test_legacy_incomplete_sweep_has_structured_service_error(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.register_project(toy_repo)
    spec = create_sweep(
        ctx,
        project="toy",
        grid=[SweepParam(name="x", values=["1", "2"])],
        seeds=[1, 2],
        command=["true", "{x}"],
        host="gpu1",
    )

    def incomplete(*args: object, **kwargs: object) -> object:
        raise SweepIncompleteError(spec, 2, 4, RunError("launch refused"))

    monkeypatch.setattr(app_module, "extend_sweep", incomplete)
    with TestClient(
        create_app(ctx.layout.home, hub=False, background_repair=False), base_url=BASE
    ) as c:
        response = c.post(f"/api/v1/sweeps/toy/{spec.id}/extend", json={"seeds": [3]})
        assert response.status_code == 503, response.text
        body = response.json()
        assert {
            k: body[k] for k in ("type", "sweep_id", "project", "host", "launched", "total")
        } == {
            "type": "SweepIncompleteError",
            "sweep_id": spec.id,
            "project": "toy",
            "host": "gpu1",
            "launched": 2,
            "total": 4,
        }
        assert body["hint"] == f"hx sweep extend {spec.id} --seeds 1,2"


def test_stop_queued_endpoint_batches_once_and_preserves_running_members(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.register_project(toy_repo)
    for name, status in (
        ("q1", RunStatus.QUEUED),
        ("q2", RunStatus.QUEUED),
        ("run", RunStatus.RUNNING),
    ):
        ctx.create_run(
            make_record(name, status=status, environment_id=ctx.descriptor.environment_id)
        )
    actual = control.cancel_many_if_queued
    batches: list[list[str]] = []

    def cancel(context: Context, run_ids: list[str]) -> control.CancelBatch:
        batches.append(run_ids)
        return actual(context, run_ids)

    monkeypatch.setattr(sweeps_module, "cancel_many_if_queued", cancel)
    # The fixture's running member has no real process; startup repair is unrelated here.
    monkeypatch.setattr(control, "repair_runs", lambda context: [])

    with TestClient(
        create_app(ctx.layout.home, hub=False, background_repair=False), base_url=BASE
    ) as c:
        body = {"run_ids": ["q1", "missing", "run", "q2"], "command_id": "batch-1"}
        first = c.post("/api/v1/runs/stop_queued", json=body)
        assert first.status_code == 200, first.text
        assert first.json()["asked"] == 4 and first.json()["failed"] == 1
        assert c.post("/api/v1/runs/stop_queued", json=body).json() == first.json()
        assert ctx.find_record("run").status == RunStatus.RUNNING
        assert ctx.find_record("q1").status == ctx.find_record("q2").status == RunStatus.KILLED
        assert c.post("/api/v1/runs/stop_queued", json={"run_ids": ["q1"] * 51}).status_code == 422
        assert len(batches) == 1


def test_remote_sweep_cancel_uses_bounded_batches_and_continues_after_error(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.register_project(toy_repo)
    write_hosts(ctx.layout.home, {"gpu1": HostSpec(route="url", url="http://127.0.0.1:9")})
    spec = create_sweep(
        ctx,
        project="toy",
        host="gpu1",
        grid=[SweepParam(name="x", values=["1"])],
        seeds=[1],
        command=["true", "{x}"],
    )
    for i in range(300):
        ctx.create_run(
            make_record(
                f"q{i}",
                environment_id="env-host",
                status=RunStatus.QUEUED,
                tags=[sweep_tag(ctx.descriptor.environment_id, spec.id)],
            )
        )
    calls: list[tuple[str, dict[str, object]]] = []

    def post(path: str, body: dict[str, object], **kwargs: object) -> dict[str, object]:
        calls.append((path, body))
        if len(calls) == 1:
            raise HostUnavailableError("fake first-batch failure")
        return {"asked": len(body["run_ids"]), "failed": 0, "errors": []}

    app = create_app(ctx.layout.home, hub=False, background_repair=False)
    with TestClient(app, base_url=BASE) as c:
        transport = Mock()
        transport.post_json.side_effect = post
        monkeypatch.setattr(app.state.hub, "client", lambda name: transport)
        result = c.post(
            f"/api/v1/sweeps/toy/{spec.id}/cancel_queued", json={"command_id": "cancel"}
        )
        assert result.status_code == 200, result.text
        assert len(calls) == 6
        assert {path for path, _ in calls} == {"/api/v1/runs/stop_queued"}
        assert result.json()["cancel"] == {
            "asked": 300,
            "failed": 50,
            "errors": ["fake first-batch failure"],
        }
        assert len({str(body["command_id"]) for _, body in calls}) == 6


@pytest.mark.parametrize("token", [None, "test-secret"])
@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_mcp_protocol_reaches_both_paths_with_spa_and_token_guard(
    home: Path, tmp_path: Path, token: str | None, path: str
) -> None:
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html>demo SPA</html>")
    headers = {"Accept": "application/json, text/event-stream"}
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    with TestClient(
        create_app(home, hub=False, background_repair=False, ui_dir=ui, auth_token=token),
        base_url=BASE,
    ) as c:
        if token:
            assert c.post(path, json=body, headers=headers).status_code == 401
            headers["Authorization"] = f"Bearer {token}"
        response = c.post(path, json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert '"protocolVersion"' in response.text and "hypothex" in response.text


@pytest.mark.parametrize("kind", ["http-missing", "http-stream", "http-folder", "ssh"])
def test_failed_pulls_leave_no_new_final_destination(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    ctx.register_project(toy_repo)
    write_hosts(ctx.layout.home, {"gpu1": HostSpec(route="ssh", ssh_alias="fake")})
    ctx.index.set_cursor("gpu1", "env-host", 0)
    record = ctx.create_run(
        make_record(
            "artifact",
            environment_id="env-host",
            artifacts=[Artifact(kind="checkpoint", path="/scratch/model.pt", host="gpu1")],
        )
    )

    def failed_fetch(run_id: str, path: str, dest: Path, **kwargs: object) -> bool:
        if kind == "http-missing":
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        if kind == "http-folder":
            dest.mkdir()
            (dest / "partial").write_text("incomplete")
        raise HostUnavailableError("fake stream failure")

    def failed_copy(*args: object, **kwargs: object) -> None:
        raise SshError("fake copy failure")

    monkeypatch.setattr(app_module, "copy_from", failed_copy)
    app = create_app(ctx.layout.home, hub=False, background_repair=False)
    with TestClient(app, base_url=BASE) as c:
        transport = Mock()
        transport.fetch_file.side_effect = failed_fetch
        monkeypatch.setattr(app.state.hub, "client", lambda name: transport)
        artifact = "checkpoint" if kind == "ssh" else "nested/weights"
        response = c.post("/api/v1/runs/artifact/pull", json={"artifact": artifact})
        assert response.status_code in (400, 503), response.text
    assert not (ctx.run_dir(record) / "pulled").exists()


@pytest.mark.parametrize("failure", [404, 413, "oversize", "malformed", "outside"])
@pytest.mark.parametrize("existing", [False, True])
def test_partial_nested_http_folder_pull_preserves_final_destination(
    ctx: Context,
    toy_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: int | str,
    existing: bool,
) -> None:
    import httpx

    from hypothex.remote.client import EnvClient

    ctx.register_project(toy_repo)
    write_hosts(ctx.layout.home, {"gpu1": HostSpec(route="url", url="http://127.0.0.1:9")})
    ctx.index.set_cursor("gpu1", "env-host", 0)
    record = ctx.create_run(make_record("artifact", environment_id="env-host"))
    pulled = ctx.run_dir(record) / "pulled"
    dest = pulled / "nested/weights"
    if existing:
        dest.mkdir(parents=True)
        (dest / "keep").write_text("original complete folder")

    def handler(request: httpx.Request) -> httpx.Response:
        rel = request.url.path.split("/files/", 1)[1]
        headers = {"X-Hypothex-Dir": "1"}
        if rel == "nested/weights":
            return httpx.Response(
                200,
                json=[{"path": rel + "/good", "size": 2}, {"path": rel + "/deeper", "size": 1}],
                headers=headers,
            )
        if rel == "nested/weights/good":
            return httpx.Response(200, content=b"ok")
        if rel == "nested/weights/deeper":
            listing = [
                {
                    "path": rel + "/bad",
                    "size": app_module.PULL_MAX_BYTES + 1 if failure == "oversize" else 1,
                }
            ]
            if failure == "malformed":
                return httpx.Response(200, content=b"broken json", headers=headers)
            if failure == "outside":
                listing = [{"path": "../outside", "size": 1}]
            return httpx.Response(200, json=listing, headers=headers)
        return httpx.Response(failure if isinstance(failure, int) else 404)

    transport = EnvClient("http://fake-only")
    transport._http = httpx.Client(
        base_url="http://fake-only", transport=httpx.MockTransport(handler)
    )
    app = create_app(ctx.layout.home, hub=False, background_repair=False)
    with TestClient(app, base_url=BASE) as client:
        monkeypatch.setattr(app.state.hub, "client", lambda _: transport)
        response = client.post("/api/v1/runs/artifact/pull", json={"artifact": "nested/weights"})
        assert response.status_code >= 400, response.text
    if existing:
        assert [(p.name, p.read_text()) for p in dest.iterdir()] == [
            ("keep", "original complete folder")
        ]
    else:
        assert not pulled.exists()
