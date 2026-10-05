from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.mcp import server


@pytest.mark.parametrize("token", [None, "synthetic-caller"])
def test_http_mcp_forwards_only_guard_selected_credential(
    home: Path, monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    seen: list[dict[str, str]] = []

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        seen.append(kwargs["headers"])
        return httpx.Response(200, json=[], request=httpx.Request(method, url))

    monkeypatch.setattr(server, "_hub_request", request)
    monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", "synthetic-owner-fallback")
    app = create_app(home, hub=False, auth_token=token)
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    with TestClient(app, base_url="http://127.0.0.1:7777") as c:
        response = c.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        headers["mcp-session-id"] = response.headers["mcp-session-id"]
        c.post(
            "/mcp/", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        response = c.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "list_hosts", "arguments": {}},
            },
        )
        assert response.status_code == 200
    assert seen == ([{"Authorization": "Bearer " + token}] if token else [{}])


def test_explicit_no_credential_never_discovers_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", "synthetic-owner-fallback")
    captured: list[dict[str, str]] = []

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        captured.append(kwargs["headers"])
        return httpx.Response(200, json=[], request=httpx.Request(method, url))

    monkeypatch.setattr(server, "_hub_request", request)
    server.hub_call("GET", "/api/v1/hosts", token=server.NO_AUTH_TOKEN)
    assert captured == [{}]


def test_http_missing_or_wrong_token_never_calls_mcp(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("forwarded unauthenticated request")

    monkeypatch.setattr(server, "_hub_request", forbidden)
    monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", "synthetic-owner-fallback")
    with TestClient(
        create_app(home, hub=False, auth_token="synthetic-caller"), base_url="http://127.0.0.1:7777"
    ) as c:
        for auth in [None, "Bearer wrong"]:
            headers = {} if auth is None else {"Authorization": auth}
            assert c.post("/mcp/", json={}, headers=headers).status_code == 401


def test_hub_call_transport_error_never_exposes_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    import traceback

    token = "synthetic-client-credential"

    def broken(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.TransportError("library reflected " + token)

    monkeypatch.setattr(server, "_hub_request", broken)
    with pytest.raises(server.HubUnavailableError) as failure:
        server.hub_call("GET", "/api/v1/hosts", token=token)
    assert token not in "".join(traceback.format_exception(failure.value))


def test_hub_call_reflected_error_redacts_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "synthetic-client-credential"

    def broken(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(403, json={"error": "bad credential " + token})

    monkeypatch.setattr(server, "_hub_request", broken)
    with pytest.raises(server.HypothexError) as failure:
        server.hub_call("GET", "/api/v1/hosts", token=token)
    assert token not in str(failure.value)


@pytest.mark.parametrize("credential", ["selected", "owner", "none"])
@pytest.mark.parametrize("redirect", [False, True])
def test_hub_wire_diagnostics_and_route_are_credential_safe(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    credential: str,
    redirect: bool,
) -> None:
    from typing import Any

    selected = "synthetic-selected-bearer"
    owner = "synthetic-owner-bearer"
    token = (
        selected
        if credential == "selected"
        else None
        if credential == "owner"
        else server.NO_AUTH_TOKEN
    )
    expected = selected if credential == "selected" else owner if credential == "owner" else None
    diagnostic = expected or "no-credential"
    writes: list[bytes] = []
    connects: list[str] = []

    class Stream:
        def __init__(self) -> None:
            status = 302 if redirect else 200
            self.body = (
                f"HTTP/1.1 {status} {diagnostic}\r\nContent-Length: 2\r\n"
                f"X-Diagnostic: {diagnostic}\r\nLocation: http://trap.invalid/\r\n\r\n[]"
            ).encode()

        def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
            body, self.body = self.body, b""
            return body

        def write(self, buffer: bytes, timeout: float | None = None) -> None:
            writes.append(buffer)

        def close(self) -> None:
            pass

        def get_extra_info(self, info: str) -> None:
            return None

    class Backend:
        def connect_tcp(self, host: str, *args: object, **kwargs: object) -> Stream:
            connects.append(host)
            return Stream()

    original = httpx.HTTPTransport.__init__

    def inject(transport: httpx.HTTPTransport, *args: Any, **kwargs: Any) -> None:
        original(transport, *args, **kwargs)
        transport._pool._network_backend = Backend()

    monkeypatch.setattr(httpx.HTTPTransport, "__init__", inject)
    monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", owner)
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.setenv(name, "http://proxy.invalid:9999")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    caplog.set_level("DEBUG")
    assert server.hub_call("GET", "/api/v1/hosts", url="http://hub.invalid", token=token) == []
    request = b"".join(writes)
    if expected:
        assert f"Authorization: Bearer {expected}".encode() in request
        assert expected not in caplog.text
    else:
        assert b"Authorization" not in request and owner.encode() not in request
    assert connects == ["hub.invalid"]  # no ambient proxy and no redirect replay
