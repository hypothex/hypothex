from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hypothex.api.app import create_app
from hypothex.api.security import (
    allowed_hosts,
    is_json,
    is_loopback_bind,
    origin_allowed,
    same_origin,
)

TOKEN = "a1" * 24
BASE = "http://127.0.0.1:7777"


@pytest.mark.parametrize(
    ("bind", "expected"),
    [
        (None, ["127.0.0.1", "localhost", "[::1]"]),
        ("127.0.0.1", ["127.0.0.1", "localhost", "[::1]"]),
        ("0.0.0.0", ["127.0.0.1", "localhost", "[::1]"]),
        ("::", ["127.0.0.1", "localhost", "[::1]"]),
        ("10.0.0.5", ["127.0.0.1", "localhost", "[::1]", "10.0.0.5"]),
        ("fe80::1", ["127.0.0.1", "localhost", "[::1]", "[fe80::1]"]),
    ],
)
def test_allowed_hosts(bind: str | None, expected: list[str]) -> None:
    assert allowed_hosts(bind) == expected


@pytest.mark.parametrize(
    ("origin", "ok"),
    [
        ("http://127.0.0.1:7777", True),
        ("http://localhost:5173", True),
        ("https://localhost", True),
        ("http://[::1]:7777", True),
        ("http://attacker.example", False),
        ("http://127.0.0.1.attacker.example", False),
        ("null", False),
        ("file://", False),
        ("http://[bad", False),
    ],
)
def test_origin_allowed(origin: str, ok: bool) -> None:
    assert origin_allowed(origin, allowed_hosts()) is ok


@pytest.mark.parametrize(
    ("origin", "host", "ok"),
    [
        ("http://127.0.0.1:7777", "127.0.0.1:7777", True),
        ("http://LOCALHOST:5173", "localhost:5173", True),
        ("http://localhost", "localhost:80", True),
        ("https://localhost", "localhost", True),
        ("http://[::1]:7777", "[::1]:7777", True),
        ("http://localhost:8888", "127.0.0.1:7777", False),
        ("http://localhost:8888", "localhost:7777", False),
        ("http://127.0.0.1:7777", "localhost:7777", False),
        ("http://127.0.0.1:7777", None, False),
        ("http://[bad", "127.0.0.1:7777", False),
        ("null", "127.0.0.1:7777", False),
    ],
)
def test_same_origin(origin: str, host: str | None, ok: bool) -> None:
    assert same_origin(origin, host) is ok


@pytest.mark.parametrize(
    ("content_type", "ok"),
    [
        ("application/json", True),
        ("Application/JSON; charset=utf-8", True),
        ("application/merge-patch+json", True),
        ("text/plain", False),
        ("application/x-www-form-urlencoded", False),
        ("multipart/form-data; boundary=x", False),
        ("", False),
        (None, False),
    ],
)
def test_is_json(content_type: str | None, ok: bool) -> None:
    assert is_json(content_type) is ok


@pytest.mark.parametrize(
    ("bind", "loopback"),
    [
        ("127.0.0.1", True),
        ("127.0.0.2", True),
        ("localhost", True),
        ("::1", True),
        ("[::1]", True),
        (" 127.0.0.1 ", True),
        ("0.0.0.0", False),
        ("::", False),
        ("", False),
        ("10.0.0.5", False),
        ("fe80::1", False),
        ("myhost.example", False),
    ],
)
def test_is_loopback_bind(bind: str, loopback: bool) -> None:
    assert is_loopback_bind(bind) is loopback


@pytest.fixture
def guarded(home: Path) -> Iterator[TestClient]:
    app = create_app(home, background_repair=False, auth_token=TOKEN)
    with TestClient(app, base_url="http://127.0.0.1:7777") as c:
        yield c


def test_token_guard_refuses_requests_without_the_token(guarded: TestClient) -> None:
    missing = guarded.get("/api/v1/runs")
    assert missing.status_code == 401 and missing.json()["type"] == "AuthError"
    wrong = guarded.post("/api/v1/runs", json={}, headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert guarded.get("/mcp/").status_code == 401
    good = {"Authorization": f"Bearer {TOKEN}"}
    assert guarded.get("/api/v1/runs", headers=good).json() == []


def test_token_guard_leaves_the_descriptor_open(guarded: TestClient) -> None:
    body = guarded.get("/.well-known/hypothex/environment").json()
    assert body["protocol_version"] == 1


def test_the_descriptor_names_host_facts_only_to_the_token_holder(guarded: TestClient) -> None:
    url = "/.well-known/hypothex/environment"
    for headers in ({}, {"Authorization": "Bearer nope"}):
        bare = guarded.get(url, headers=headers).json()
        assert sorted(bare) == ["environment_id", "hx_version", "protocol_version"]
    full = guarded.get(url, headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert {"hostname", "gpus", "os", "kind", "label"} <= set(full)
    assert full["environment_id"] == bare["environment_id"]


def test_without_a_token_the_descriptor_is_whole(home: Path) -> None:
    with TestClient(create_app(home, background_repair=False), base_url=BASE) as c:
        assert "hostname" in c.get("/.well-known/hypothex/environment").json()


def test_token_guard_closes_a_websocket_without_the_token(guarded: TestClient) -> None:
    url = "ws://127.0.0.1:7777/api/v1/ws"
    with pytest.raises(WebSocketDisconnect) as exc, guarded.websocket_connect(url) as ws:
        ws.receive_json()
    assert exc.value.code == 1008
    good = {"Authorization": f"Bearer {TOKEN}"}
    with guarded.websocket_connect(url, headers=good) as ws:
        ws.send_json({"type": "subscribe", "after_sequence": 0})
        assert ws.receive_json()["type"] == "ready"
