from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hypothex.api.app import create_app
from hypothex.api.tickets import TicketStore

TOKEN = "synthetic-token"
BASE = "http://127.0.0.1:7777"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_openapi_operations_have_unique_ids(home: Path) -> None:
    schema = create_app(home, hub=False, auth_token=TOKEN).openapi()
    ids = [
        operation["operationId"]
        for methods in schema["paths"].values()
        for operation in methods.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(ids) == len(set(ids)), "OpenAPI clients require unique operation IDs"


def test_ticket_store_expiry_capacity_and_atomic_consumption() -> None:
    now = [10.0]
    store = TicketStore(clock=lambda: now[0], capacity=2)
    first = store.issue()
    second = store.issue()
    assert store.issue() is None
    assert first and second
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(store.consume, [first] * 8)) == 1
    assert store.issue()
    now[0] = 40.0
    assert not store.consume(second)
    assert store.issue()


def test_authenticated_ticket_protocol_and_single_use(home: Path) -> None:
    with TestClient(create_app(home, hub=False, auth_token=TOKEN), base_url=BASE) as c:
        assert c.post("/api/v1/auth/ws-ticket", json={}).status_code == 401
        response = c.post("/api/v1/auth/ws-ticket", json={}, headers=AUTH)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["expires_in"] == 30
        protocols = ["hypothex.v1", "hx-ticket." + body["ticket"]]
        with c.websocket_connect("ws://127.0.0.1:7777/api/v1/ws", subprotocols=protocols) as ws:
            assert ws.accepted_subprotocol == "hypothex.v1"
            ws.send_json({"type": "subscribe", "after_sequence": 0})
            assert ws.receive_json()["type"] == "ready"
        with (
            pytest.raises(WebSocketDisconnect),
            c.websocket_connect("ws://127.0.0.1:7777/api/v1/ws", subprotocols=protocols),
        ):
            pass


@pytest.mark.parametrize(
    "bad_headers",
    [
        {"Origin": "http://localhost:8888"},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "Basic bad"},
    ],
)
def test_rejected_handshake_does_not_consume_ticket(
    home: Path, bad_headers: dict[str, str]
) -> None:
    with TestClient(create_app(home, hub=False, auth_token=TOKEN), base_url=BASE) as c:
        ticket = c.post("/api/v1/auth/ws-ticket", json={}, headers=AUTH).json()["ticket"]
        protocols = ["hypothex.v1", "hx-ticket." + ticket]
        with (
            pytest.raises(WebSocketDisconnect),
            c.websocket_connect(
                "ws://127.0.0.1:7777/api/v1/ws", headers=bad_headers, subprotocols=protocols
            ),
        ):
            pass
        with c.websocket_connect("ws://127.0.0.1:7777/api/v1/ws", subprotocols=protocols) as ws:
            assert ws.accepted_subprotocol == "hypothex.v1"


def test_noauth_ticket_and_protocol(home: Path) -> None:
    with TestClient(create_app(home, hub=False), base_url=BASE) as c:
        response = c.post("/api/v1/auth/ws-ticket", json={})
        assert response.json() == {"ticket": None, "expires_in": 0}
        assert response.headers["cache-control"] == "no-store"
        with c.websocket_connect(
            "ws://127.0.0.1:7777/api/v1/ws", subprotocols=["hypothex.v1"]
        ) as ws:
            assert ws.accepted_subprotocol == "hypothex.v1"


def test_public_shell_is_exact_and_read_only(home: Path, tmp_path: Path) -> None:
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<html>gate</html>")
    (ui / "assets" / "app.js").write_text("app")
    with TestClient(create_app(home, hub=False, auth_token=TOKEN, ui_dir=ui), base_url=BASE) as c:
        for path in ["/", "/index.html", "/assets/app.js", "/t/p/t", "/r/r1", "/s/p/s1", "/x/a/b"]:
            assert c.get(path).status_code == 200, path
            assert c.head(path).status_code == 200, path
            assert c.post(path, json={}).status_code == 401, path
        for path in [
            "/api/nope",
            "/mcp/",
            "/redoc",
            "/api/openapi.json",
            "/.well-known/hypothex/nope",
            "/files/nope",
            "/unknown",
        ]:
            assert c.get(path).status_code == 401, path
        assert c.head("/.well-known/hypothex/environment").status_code == 200
        assert c.post("/.well-known/hypothex/environment", json={}).status_code == 401


def test_ticket_endpoint_capacity_expiry_and_wrong_instance(home: Path, tmp_path: Path) -> None:
    app = create_app(home, hub=False, auth_token=TOKEN)
    now = [0.0]
    app.state.ws_tickets._clock = lambda: now[0]
    with TestClient(app, base_url=BASE) as c:
        tickets = [
            c.post("/api/v1/auth/ws-ticket", json={}, headers=AUTH).json()["ticket"]
            for _ in range(256)
        ]
        assert len(set(tickets)) == 256
        full = c.post("/api/v1/auth/ws-ticket", json={}, headers=AUTH)
        assert full.status_code == 429 and full.headers["cache-control"] == "no-store"
        protocol = ["hypothex.v1", "hx-ticket." + tickets[0]]
        with (
            TestClient(
                create_app(tmp_path / "other", hub=False, auth_token=TOKEN), base_url=BASE
            ) as other,
            pytest.raises(WebSocketDisconnect),
            other.websocket_connect("ws://127.0.0.1:7777/api/v1/ws", subprotocols=protocol),
        ):
            pass
        now[0] = 30.0
        with (
            pytest.raises(WebSocketDisconnect),
            c.websocket_connect("ws://127.0.0.1:7777/api/v1/ws", subprotocols=protocol),
        ):
            pass
        assert c.post("/api/v1/auth/ws-ticket", json={}, headers=AUTH).status_code == 200


@pytest.mark.parametrize(
    "variant", ["duplicate", "missing-fixed", "malformed", "other-route", "host", "duplicate-auth"]
)
def test_bad_handshakes_preserve_ticket(home: Path, variant: str) -> None:
    with TestClient(create_app(home, hub=False, auth_token=TOKEN), base_url=BASE) as c:
        ticket = c.post("/api/v1/auth/ws-ticket", json={}, headers=AUTH).json()["ticket"]
        protocols = ["hypothex.v1", "hx-ticket." + ticket]
        bad = protocols.copy()
        path = "ws://127.0.0.1:7777/api/v1/ws"
        headers: dict[str, str] | list[tuple[str, str]] = {}
        if variant == "duplicate":
            bad.append(bad[1])
        elif variant == "missing-fixed":
            bad.pop(0)
        elif variant == "malformed":
            bad[1] += "!"
        elif variant == "other-route":
            path += "/other"
        elif variant == "host":
            headers = {"Host": "attacker.invalid"}
        elif variant == "duplicate-auth":
            headers = httpx.Headers(
                [("Authorization", "Bearer " + TOKEN), ("Authorization", "Bearer wrong")]
            )
        with (
            pytest.raises(WebSocketDisconnect),
            c.websocket_connect(path, headers=headers, subprotocols=bad),
        ):
            pass
        with c.websocket_connect("ws://127.0.0.1:7777/api/v1/ws", subprotocols=protocols) as ws:
            assert ws.accepted_subprotocol == "hypothex.v1"
