import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hypothex.auth.store import Principal
from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.sweeps import SweepParam, SweepSpec, save_sweep
from hypothex.mcp.server import (
    NO_AUTH_TOKEN,
    acting_as,
    build_server,
    caller,
    caller_token,
    scoped,
    tool_hub_token,
    tool_scopes,
)
from tests.api.authkit import BASE, auth_app
from tests.factories import make_record
from tests.mcp.test_server import call

PY = sys.executable
READER = Principal(user="bob", scope="read", session_id="s_00000000000b", client="cli")
ALICE = Principal(user="alice", scope="launch", session_id="s_00000000000a", client="cli")
CAROL = Principal(user="carol", scope="admin", session_id="s_00000000000c", client="cli")
LAUNCH_TOOLS = {
    "launch_run",
    "rerun",
    "reinfer",
    "reevaluate",
    "stop_run",
    "add_note",
    "tag_run",
    "rename_run",
    "add_notebook_entry",
    "add_view",
    "launch_sweep",
    "cancel_sweep",
    "extend_sweep",
    "pull_artifact",
    "connect_host",
}


def test_every_tool_declares_a_scope(home: Path) -> None:
    server = build_server(home)
    names = {t.name for t in asyncio.run(server.list_tools())}
    scopes = tool_scopes(server)
    assert set(scopes) == names
    assert {n for n, s in scopes.items() if s == "launch"} == LAUNCH_TOOLS
    assert all(s == "read" for n, s in scopes.items() if n.startswith(("list_", "get_")))


def test_read_principal_cannot_launch(home: Path, toy_repo: Path) -> None:
    with acting_as(READER):
        err, message = call(
            home,
            "launch_run",
            {"repo": str(toy_repo), "hypothesis": "x", "command": [PY, "-c", "pass"]},
        )
        # the SDK prefixes "Error executing tool launch_run: "; the message is ours
        assert err and message.endswith("403 · launch scope needed; you hold read")
        err, _ = call(home, "list_projects")
        assert not err


def test_session_principal_launches_as_agent_at_user(home: Path, toy_repo: Path) -> None:
    args = {"repo": str(toy_repo), "hypothesis": "x", "command": [PY, "-c", "pass"]}
    with acting_as(CAROL):
        err, out = call(home, "launch_run", {**args, "agent": "claude"})
    assert not err, out
    assert (out["run"]["created_by"], out["run"]["owner"]) == ("agent:claude@carol", "carol")
    control.wait_for_run(Context.open(home), out["run"]["run_id"], timeout=30)
    with acting_as(ALICE):  # launch scope: hosts only, never this machine
        err, message = call(home, "launch_run", {**args, "agent": "claude"})
    assert err and message.endswith("runs on this machine need admin; launch on a host")


def test_local_owner_keeps_phase_2_identity(home: Path, toy_repo: Path) -> None:
    err, out = call(
        home,
        "launch_run",
        {"repo": str(toy_repo), "hypothesis": "x", "command": [PY, "-c", "pass"]},
    )
    assert not err and (out["run"]["created_by"], out["run"]["owner"]) == ("agent:mcp", None)
    control.wait_for_run(Context.open(home), out["run"]["run_id"], timeout=30)


def fake_http(credential: str | None) -> SimpleNamespace:
    request = SimpleNamespace(scope={"hx.principal": ALICE, "hypothex.auth_token": credential})
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


def test_http_principal_and_token_reach_the_tool() -> None:
    def who() -> dict[str, str | None]:
        return {
            "user": caller().user,
            "token": caller_token(),
            "hub": tool_hub_token(lambda: "SERVER-ADMIN"),
        }

    wrapped = scoped("read")(who)
    bearer_call = fake_http("hxs_abc")
    expected = {"user": "alice", "token": "hxs_abc", "hub": "hxs_abc"}
    assert wrapped(hx_mcp_ctx=bearer_call) == expected
    cookie_call = fake_http("hxs_cookie")
    assert wrapped(hx_mcp_ctx=cookie_call)["hub"] == "hxs_cookie"  # never the server's token
    bare_call = fake_http(None)
    assert wrapped(hx_mcp_ctx=bare_call)["hub"] is NO_AUTH_TOKEN
    local = wrapped(hx_mcp_ctx=None)
    assert local == {"user": "local", "token": None, "hub": "SERVER-ADMIN"}  # stdio
    with pytest.raises(Exception, match="admin scope needed"):
        scoped("admin")(who)(hx_mcp_ctx=bearer_call)


@pytest.mark.parametrize("authorization", [None, b"Bearer rejected", b"Bearer ", b"Bearer \xa0"])
@pytest.mark.parametrize("tool_name", ["stop_run", "get_sweep", "cancel_sweep", "extend_sweep"])
def test_registered_http_tool_forwards_only_authenticated_cookie(
    home: Path, monkeypatch: pytest.MonkeyPatch, authorization: bytes | None, tool_name: str
) -> None:
    import httpx
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from hypothex.api.auth import AuthGuard
    from tests.api.authkit import token_for

    app = auth_app(home)
    token = token_for(app.state.auth, "alice", "launch")
    server = build_server(home, hub_url=BASE, hub_token="SERVER-ADMIN")
    tool = next(t for t in server._tool_manager.list_tools() if t.name == tool_name)
    args = (
        {"run_id": "remote-run"}
        if tool_name == "stop_run"
        else {
            "project": "toy",
            "sweep_id": "s-0001",
        }
    )
    if tool_name == "extend_sweep":
        args["seeds"] = [2]
    spec = SweepSpec(
        id="s-0001",
        project="toy",
        task=None,
        host=None,
        grid=[SweepParam(name="x", values=["1"])],
        seeds=[1],
        command_template=["echo", "{x}"],
        created_by="human:alice",
        created_at=make_record().created_at,
        owner="alice",
    )
    sent: list[dict[str, str]] = []

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        assert url.startswith(BASE + "/api/v1/")
        sent.append(dict(kwargs["headers"]))
        return httpx.Response(200, json={"spec": spec.model_dump(mode="json")})

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("HTTP caller must never discover the server credential")

    monkeypatch.setattr("hypothex.mcp.server._hub_request", request)
    monkeypatch.setattr("hypothex.mcp.server.resolve_hub_token", forbidden)

    async def invoke(request: Request) -> JSONResponse:
        mcp_ctx = SimpleNamespace(request_context=SimpleNamespace(request=request))
        return JSONResponse(tool.fn(**args, hx_mcp_ctx=mcp_ctx))

    endpoint = Starlette(routes=[Route("/mcp/", invoke, methods=["POST"])])
    with TestClient(AuthGuard(endpoint, app.state.auth), base_url=BASE) as client:
        headers = [(b"cookie", f"hx_session={token}".encode())]
        if authorization is not None:
            headers.append((b"authorization", authorization))
        assert client.post("/mcp/", headers=headers, json={}).status_code == 200
    assert sent and all(headers["Authorization"] == f"Bearer {token}" for headers in sent)
    # Even a principal-only HTTP context cannot activate either discovery layer.
    sent.clear()
    tool.fn(**args, hx_mcp_ctx=fake_http(None))
    assert sent and all("Authorization" not in headers for headers in sent)


@pytest.mark.parametrize("tool_name", ["list_runs", "get_run"])
@pytest.mark.parametrize("credential", ["hxs_selected", None])
def test_host_state_reads_never_discover_a_server_token_over_http(
    home: Path,
    toy_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    credential: str | None,
) -> None:
    import httpx

    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    ctx.create_run(make_record("remote-read", environment_id="env-remote"))
    sent: list[dict[str, str]] = []

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        assert method == "GET" and "/api/v1/runs?" in url
        sent.append(dict(kwargs["headers"]))
        return httpx.Response(200, json=[{"host_state": "connected"}])

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("HTTP host-state reads cannot discover a server credential")

    monkeypatch.setattr("hypothex.mcp.server._hub_request", request)
    monkeypatch.setattr("hypothex.mcp.server.resolve_hub_token", forbidden)
    server = build_server(home, hub_url=BASE, hub_token="SERVER-ADMIN")
    tool = next(t for t in server._tool_manager.list_tools() if t.name == tool_name)
    args = {"run_id": "remote-read"} if tool_name == "get_run" else {}
    tool.fn(**args, hx_mcp_ctx=fake_http(credential))
    assert len(sent) == 1
    if credential is None:
        assert "Authorization" not in sent[0]
    else:
        assert sent[0]["Authorization"] == f"Bearer {credential}"


def test_read_principal_cannot_reconnect_a_host(home: Path) -> None:
    with acting_as(READER):
        err, message = call(home, "connect_host", {"name": "gpu1"})
    assert err and message.endswith("403 · launch scope needed; you hold read")


def test_tools_keep_the_ownership_rules(home: Path, toy_repo: Path) -> None:
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    ctx.create_run(make_record("svs", owner="sv", environment_id=ctx.descriptor.environment_id))
    save_sweep(
        ctx.layout,
        SweepSpec(
            id="sw-sv",
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
    with acting_as(ALICE):
        err, message = call(home, "stop_run", {"run_id": "svs"})
        assert err and message.endswith("run owned by sv; stop needs owner or admin")
        err, message = call(home, "cancel_sweep", {"project": "toy", "sweep_id": "sw-sv"})
        assert err and message.endswith("run owned by sv; cancel_queued needs owner or admin")
    assert ctx.find_record("svs").status.value == "queued"


def test_mcp_over_http_needs_a_session(home: Path) -> None:
    with TestClient(auth_app(home), base_url=BASE) as client:
        resp = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp.status_code == 401 and resp.json()["type"] == "AuthError"


@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize("session", [False, True])
@pytest.mark.parametrize("override", [None, "chosen"])
def test_note_attribution_keeps_selected_agent_and_unscoped_author(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote: bool,
    session: bool,
    override: str | None,
) -> None:
    from typing import Any

    import httpx

    from hypothex.auth.store import LOCAL_OWNER

    sent: list[tuple[dict[str, str], dict[str, Any]]] = []
    saved: list[str] = []

    def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        assert method == "POST" and url == BASE + "/api/v1/runs/r/notes"
        sent.append((dict(kwargs["headers"]), dict(kwargs["json"])))
        return httpx.Response(200, json={"ok": True})

    def save_note(ctx: Context, run_id: str, text: str, author: str) -> None:
        assert run_id == "r" and text == "note"
        saved.append(author)

    monkeypatch.setattr("hypothex.mcp.server.acts_through_hub", lambda *args: remote)
    monkeypatch.setattr("hypothex.mcp.server._hub_request", request)
    monkeypatch.setattr("hypothex.mcp.server.q.add_note", save_note)
    server = build_server(home, hub_url=BASE, hub_token="test-token", agent="configured")
    tool = next(t for t in server._tool_manager.list_tools() if t.name == "add_note")
    args: dict[str, Any] = {"run_id": "r", "text": "note", "author": "custom-author"}
    if override is not None:
        args["agent"] = override
    with acting_as(ALICE if session else LOCAL_OWNER):
        assert tool.fn(**args) == {"ok": True}
    acting = "configured" if override is None else override
    writer = f"agent:{acting}@alice" if session else "custom-author"
    if remote:
        assert saved == [] and len(sent) == 1
        headers, body = sent[0]
        assert headers["X-Hypothex-Agent"] == acting and body["author"] == writer
    else:
        assert sent == [] and saved == [writer]


@pytest.mark.parametrize("tool_name", ["rerun", "launch_run", "stop_run"])
@pytest.mark.parametrize("override", [None, "chosen"])
def test_registered_tools_forward_the_configured_agent_or_explicit_override(
    home: Path,
    toy_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    override: str | None,
) -> None:
    import httpx

    monkeypatch.delenv("HYPOTHEX_AGENT", raising=False)
    monkeypatch.setattr("hypothex.mcp.server.acts_through_hub", lambda *args: True)
    sent: list[tuple[dict[str, str], dict[str, Any]]] = []

    def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        assert method == "POST" and url.startswith(BASE + "/api/v1/")
        sent.append((dict(kwargs["headers"]), dict(kwargs["json"])))
        return httpx.Response(200, json={"run_id": "child"})

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("an HTTP tool cannot discover the privileged server token")

    monkeypatch.setattr("hypothex.mcp.server._hub_request", request)
    monkeypatch.setattr("hypothex.mcp.server.resolve_hub_token", forbidden)
    server = build_server(home, hub_url=BASE, hub_token="SERVER-ADMIN", agent="configured")
    tool = next(t for t in server._tool_manager.list_tools() if t.name == tool_name)
    args: dict[str, Any] = (
        {"run_id": "remote"}
        if tool_name != "launch_run"
        else {
            "repo": str(toy_repo),
            "host": "gpu1",
            "hypothesis": "agent attribution",
            "command": ["true"],
        }
    )
    if override is not None:
        args["agent"] = override
    result = tool.fn(**args, hx_mcp_ctx=fake_http("hxs_selected"))
    assert result["run"]["run_id"] == "child"
    headers, body = sent[0]
    acting = "configured" if override is None else override
    assert headers["X-Hypothex-Agent"] == acting
    assert headers["Authorization"] == "Bearer hxs_selected"
    assert body["created_by"].startswith(f"agent:{acting}") and "None" not in body["created_by"]
