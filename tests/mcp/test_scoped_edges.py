"""Guard-selected identity remains authoritative across SDK messages and forwarding."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hypothex.api.auth import AuthGuard, command_key, principal_of
from hypothex.auth.client import HubLogin, save_hub_login
from hypothex.core.context import Context
from hypothex.mcp import server as module
from hypothex.mcp.server import (
    NO_AUTH_TOKEN,
    acting_as,
    build_server,
    caller,
    hub_call,
    resolve_hub_token,
    scoped,
)
from tests.api.authkit import BASE, auth_app, token_for
from tests.mcp.test_scoped_tools import ALICE, CAROL, fake_http


def _rpc_result(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    messages = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert len(messages) == 1, response.text
    return messages[0]


def test_one_http_mcp_session_uses_each_messages_principal_and_credential(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = auth_app(home)
    alice = token_for(app.state.auth, "alice", "launch")
    bob = token_for(app.state.auth, "bob", "read")
    sent: list[dict[str, str]] = []

    def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        sent.append(kwargs["headers"])
        return httpx.Response(200, json=[])

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("HTTP must not discover server credentials")

    monkeypatch.setattr(module, "_hub_request", request)
    monkeypatch.setattr(module, "resolve_hub_token", forbidden)
    headers = {"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {alice}"}
    with TestClient(app, base_url=BASE) as client:
        response = client.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "scope-regression", "version": "1"},
                },
            },
        )
        assert response.status_code == 200
        headers["mcp-session-id"] = response.headers["mcp-session-id"]
        client.post(
            "/mcp/",
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        for identifier, (token, user) in enumerate(
            [(alice, "alice"), (bob, "bob"), (alice, "alice")], 2
        ):
            # A rejected bearer must resolve through the cookie on each SDK message.
            call_headers = {
                **headers,
                "Authorization": "Bearer rejected",
                "Cookie": f"hx_session={token}",
            }
            result = _rpc_result(
                client.post(
                    "/mcp/",
                    headers=call_headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": identifier,
                        "method": "tools/call",
                        "params": {"name": "whoami", "arguments": {}},
                    },
                )
            )["result"]
            assert result.get("isError", False) is False
            assert result["structuredContent"]["user"] == user
            result = _rpc_result(
                client.post(
                    "/mcp/",
                    headers=call_headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": identifier + 10,
                        "method": "tools/call",
                        "params": {"name": "list_hosts", "arguments": {}},
                    },
                )
            )["result"]
            assert result.get("isError", False) is False
            assert sent[-1]["Authorization"] == f"Bearer {token}"
        result = _rpc_result(
            client.post(
                "/mcp/",
                headers={**headers, "Authorization": f"Bearer {bob}"},
                json={
                    "jsonrpc": "2.0",
                    "id": 90,
                    "method": "tools/call",
                    "params": {
                        "name": "connect_host",
                        "arguments": {
                            "name": "gpu",
                            "hx_mcp_ctx": None,
                        },
                    },
                },
            )
        )["result"]
        assert result["isError"] is True
        assert "launch scope needed" in result["content"][0]["text"]
    assert len(sent) == 3


def test_http_context_without_principal_never_inherits_local_admin() -> None:
    def who() -> str:
        return caller().user

    wrapped = scoped("read")(who)
    missing = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(scope={})))
    with acting_as(CAROL), pytest.raises(Exception, match="authenticated principal needed"):
        wrapped(hx_mcp_ctx=missing)


def test_scope_and_token_context_are_restored_after_tool_error() -> None:
    def fails() -> None:
        assert caller() == ALICE
        raise ValueError("controlled failure")

    with pytest.raises(ValueError, match="controlled"):
        scoped("read")(fails)(hx_mcp_ctx=fake_http("selected"))
    assert caller().user == "local"
    assert module.caller_token() is None
    assert module.tool_hub_token(lambda: "local-default") == "local-default"


def test_mcp_context_is_hidden_from_every_tool_schema(home: Path) -> None:
    tools = asyncio.run(build_server(home).list_tools())
    assert tools
    assert all("hx_mcp_ctx" not in tool.input_schema.get("properties", {}) for tool in tools)


def test_forwarded_command_receipts_bind_actual_user_and_operation(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = auth_app(home)
    alice = token_for(app.state.auth, "alice", "launch")
    bob = token_for(app.state.auth, "bob", "launch")
    context = Context.open(home)
    calls: list[str] = []

    async def mutate(request: Request) -> JSONResponse:
        body = await request.json()
        principal = principal_of(request)
        key = command_key(request, body["command_id"])

        def effect() -> dict[str, str]:
            label = principal.user + request.url.path
            calls.append(label)
            return {"receipt": label}

        return JSONResponse(context.events.run_once(key, effect))

    target = Starlette(routes=[Route("/api/v1/runs/{run_id}/{action}", mutate, methods=["POST"])])
    with TestClient(AuthGuard(target, app.state.auth), base_url=BASE) as client:

        def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
            return client.request(method, url, json=kwargs["json"], headers=kwargs["headers"])

        monkeypatch.setattr(module, "_hub_request", request)
        monkeypatch.setattr(module, "acts_through_hub", lambda *args: True)
        monkeypatch.setattr(module, "new_command_id", lambda: "same-command")
        tools = {tool.name: tool for tool in build_server(home)._tool_manager.list_tools()}
        for token in (alice, alice, bob):
            principal = app.state.auth.authenticate(token)
            assert principal is not None
            ctx = SimpleNamespace(
                request_context=SimpleNamespace(
                    request=SimpleNamespace(
                        scope={
                            "hx.principal": principal,
                            "hypothex.auth_token": token,
                        }
                    )
                )
            )
            tools["stop_run"].fn(run_id="r", hx_mcp_ctx=ctx)
        tools["rerun"].fn(run_id="r", hx_mcp_ctx=ctx)
    assert calls == [
        "alice/api/v1/runs/r/stop",
        "bob/api/v1/runs/r/stop",
        "bob/api/v1/runs/r/rerun",
    ]


def test_hub_login_resolution_precedence_and_exact_url(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = home / "serve" / "server.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"port": 7777, "token": "local-server"}))
    login = HubLogin(token=SecretStr("saved-token"), user="alice", scope="launch", session_id="s_1")
    save_hub_login(module.Layout(home), BASE, login)
    assert resolve_hub_token(BASE + "/", home) == "saved-token"
    assert resolve_hub_token("https://another-hub.invalid", home) is None
    assert resolve_hub_token("http://localhost:7777", home) == "local-server"
    monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", "environment-token")
    assert resolve_hub_token(BASE, home) == "environment-token"


def test_hub_call_text_and_explicit_agent_override(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, str]] = []

    def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        seen.append(kwargs["headers"])
        return httpx.Response(200, text="| run | score |\n")

    monkeypatch.setattr(module, "_hub_request", request)
    monkeypatch.setenv("HYPOTHEX_AGENT", "environment-agent")
    result = hub_call("GET", "/api/v1/export", token=NO_AUTH_TOKEN, text=True, agent="chosen")
    assert result == "| run | score |\n"
    assert seen == [{"X-Hypothex-Agent": "chosen"}]


def test_stdio_tool_discovers_saved_login_only_in_selected_home(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core.layout import Layout

    login = HubLogin(
        token=SecretStr("saved-selected-home"), user="alice", scope="launch", session_id="s_1"
    )
    save_hub_login(Layout(home), BASE, login)
    seen: list[dict[str, str]] = []

    def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        seen.append(kwargs["headers"])
        return httpx.Response(200, json=[])

    monkeypatch.setattr(module, "_hub_request", request)
    tools = {
        tool.name: tool for tool in build_server(home, hub_url=BASE)._tool_manager.list_tools()
    }
    tools["list_hosts"].fn()
    assert seen == [{"Authorization": "Bearer saved-selected-home", "X-Hypothex-Agent": "mcp"}]


@pytest.mark.parametrize("operation", ["sweep", "tool"])
def test_empty_selected_home_never_falls_back_to_default_home_login(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    selected = tmp_path / "empty-selected"
    Context.open(selected)
    login = HubLogin(token=SecretStr("default-admin"), user="sv", scope="admin", session_id="s_1")
    save_hub_login(module.Layout(home), BASE, login)
    seen: list[dict[str, str]] = []

    def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        seen.append(kwargs["headers"])
        return httpx.Response(200, json=[])

    monkeypatch.setattr(module, "_hub_request", request)
    if operation == "sweep":
        module.sweep_summary(Context.open(selected), "missing", "toy", url=BASE)
    else:
        tools = {
            tool.name: tool
            for tool in build_server(selected, hub_url=BASE)._tool_manager.list_tools()
        }
        tools["list_hosts"].fn()
    assert len(seen) == 1
    assert "Authorization" not in seen[0]
