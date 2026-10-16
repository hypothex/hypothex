from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hypothex.api.app import create_app
from hypothex.api.routes_auth import PAIR_ATTEMPTS_PER_MINUTE, pair_client_key
from hypothex.auth.pairing import parse_pairing_url
from hypothex.auth.store import PAIRING_INVALID, AuthStore
from tests.api.authkit import BASE, auth_app, bearer, token_for


@pytest.fixture
def app(home: Path) -> FastAPI:
    return auth_app(home)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=BASE) as test_client:
        yield test_client


def owner_token(app: FastAPI) -> str:
    return token_for(app.state.auth, "sv", "admin")


def pair_link(client: TestClient, token: str, **body: object) -> str:
    resp = client.post("/api/v1/auth/pairings", json=body, headers=bearer(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["url"]


def test_owner_pairs_a_new_collaborator(app: FastAPI, client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/pairings",
        json={"user": "alice", "new_user": True, "scope": "launch"},
        headers=bearer(owner_token(app)),
    )
    offer = resp.json()
    assert offer["url"].startswith(f"{BASE}/pair#p_") and "█" in offer["qr"]
    _, offer_id, secret = parse_pairing_url(offer["url"])
    paired = client.post(
        "/api/v1/auth/pair",
        json={"offer_id": offer_id, "secret": secret, "device": "MacBook", "client": "cli"},
    ).json()
    assert paired["user"] == "alice" and paired["scopes"] == ["read", "launch"]
    me = client.get("/api/v1/auth/me", headers=bearer(paired["token"])).json()
    assert (me["user"], me["scope"], me["client"], me["auth"]) == ("alice", "launch", "cli", "on")


@pytest.mark.parametrize(("public", "secure"), [(None, False), ("https://hub.ts.net", True)])
def test_browser_pairing_sets_a_strict_cookie(home: Path, public: str | None, secure: bool) -> None:
    app = auth_app(home, public_url=public)
    with TestClient(app, base_url=BASE) as client:
        link = pair_link(client, owner_token(app), user="sv", scope="read")
        _, offer_id, secret = parse_pairing_url(link)
        resp = client.post(
            "/api/v1/auth/pair", json={"offer_id": offer_id, "secret": secret, "device": "phone"}
        )
    cookie = resp.headers["set-cookie"].lower()
    assert "hx_session=hxs_" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "path=/" in cookie and ("secure" in cookie) is secure
    assert "token" not in resp.json()
    if public:
        assert link.startswith("https://hub.ts.net/pair#")


def test_pairing_never_widens_scope_over_http(app: FastAPI, client: TestClient) -> None:
    alice = token_for(app.state.auth, "alice", "launch")
    resp = client.post("/api/v1/auth/pairings", json={"scope": "admin"}, headers=bearer(alice))
    assert resp.status_code == 403
    resp = client.post(
        "/api/v1/auth/pairings", json={"user": "bob", "new_user": True}, headers=bearer(alice)
    )
    assert resp.status_code == 403
    assert (
        client.post(
            "/api/v1/auth/pairings", json={"user": "zed"}, headers=bearer(alice)
        ).status_code
        == 400
    )


def test_bad_links_get_one_message_and_reuse_fails(app: FastAPI, client: TestClient) -> None:
    link = pair_link(client, owner_token(app), user="sv", scope="read")
    _, offer_id, secret = parse_pairing_url(link)
    body = {"offer_id": offer_id, "secret": secret, "client": "cli"}
    assert client.post("/api/v1/auth/pair", json=body).status_code == 200
    again = client.post("/api/v1/auth/pair", json=body)
    wrong = client.post("/api/v1/auth/pair", json={**body, "secret": "x" * 43})
    for resp in (again, wrong):
        assert resp.status_code == 400 and resp.json() == {
            "error": PAIRING_INVALID,
            "type": "PairingError",
        }


def test_pairing_attempts_are_rate_limited(client: TestClient) -> None:
    body = {"offer_id": "p_000000000000", "secret": "y" * 43}
    codes = [client.post("/api/v1/auth/pair", json=body).status_code for _ in range(11)]
    assert codes == [400] * 10 + [429]


def test_successful_pairings_do_not_count(app: FastAPI, client: TestClient) -> None:
    token = owner_token(app)
    for i in range(PAIR_ATTEMPTS_PER_MINUTE + 2):  # a lab pairing a dozen devices in a minute
        _, offer_id, secret = parse_pairing_url(pair_link(client, token, scope="read"))
        body = {"offer_id": offer_id, "secret": secret, "device": f"d{i}", "client": "cli"}
        assert client.post("/api/v1/auth/pair", json=body).status_code == 200


def test_the_pairing_limit_counts_people_behind_a_proxy() -> None:
    ts = {"tailscale-user-login": "alice@lab.org", "x-forwarded-for": "100.64.0.7"}
    assert pair_client_key("127.0.0.1", ts, behind_proxy=True) == "ts:alice@lab.org"
    xff = {"x-forwarded-for": "203.0.113.9, 100.64.0.7"}
    assert pair_client_key("127.0.0.1", xff, behind_proxy=True) == "100.64.0.7"
    assert pair_client_key("127.0.0.1", {}, behind_proxy=True) == "127.0.0.1"
    assert pair_client_key("10.0.0.5", ts, behind_proxy=True) == "10.0.0.5"  # not from the proxy
    assert pair_client_key("127.0.0.1", ts, behind_proxy=False) == "127.0.0.1"


def test_logout_revokes_and_clears_the_cookie(app: FastAPI, client: TestClient) -> None:
    token = token_for(app.state.auth, "alice", "read")
    before = app.state.ctx.events.last_sequence()
    resp = client.post("/api/v1/auth/logout", headers=bearer(token), json={})
    assert resp.json() == {"ok": True} and 'hx_session=""' in resp.headers["set-cookie"]
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    (event,) = [e for e in app.state.ctx.events.since(before) if e.type == "auth.session_revoked"]
    assert event.payload["user"] == "alice" and "token" not in event.payload


def test_sessions_are_own_unless_admin(app: FastAPI, client: TestClient) -> None:
    store: AuthStore = app.state.auth
    admin, alice = owner_token(app), token_for(store, "alice", "launch")
    token_for(store, "bob", "read")
    mine = client.get("/api/v1/auth/sessions", headers=bearer(alice)).json()
    assert {s["user"] for s in mine} == {"alice"} and all("secret" not in s for s in mine)
    assert client.get("/api/v1/auth/sessions?user=bob", headers=bearer(alice)).status_code == 403
    every = client.get("/api/v1/auth/sessions", headers=bearer(admin)).json()
    assert {s["user"] for s in every} == {"sv", "alice", "bob"}
    bob_session = next(s["id"] for s in every if s["user"] == "bob")
    url = f"/api/v1/auth/sessions/{bob_session}/revoke"
    assert client.post(url, json={}, headers=bearer(alice)).status_code == 403
    assert client.post(url, json={}, headers=bearer(admin)).json()["revoked_at"] is not None


def test_users_are_admin_only_and_disable_locks_out(app: FastAPI, client: TestClient) -> None:
    admin, alice = owner_token(app), token_for(app.state.auth, "alice", "launch")
    assert client.get("/api/v1/auth/users", headers=bearer(alice)).status_code == 403
    users = client.get("/api/v1/auth/users", headers=bearer(admin)).json()
    assert {u["name"]: u["role"] for u in users} == {"sv": "admin", "alice": "launch"}
    resp = client.post("/api/v1/auth/users/alice/disable", json={}, headers=bearer(admin))
    assert resp.json()["disabled_at"] is not None
    assert client.get("/api/v1/auth/me", headers=bearer(alice)).status_code == 401


def test_ws_ticket(app: FastAPI, client: TestClient) -> None:
    resp = client.post("/api/v1/auth/ws-ticket", headers=bearer(owner_token(app)), json={})
    assert resp.json()["expires_in"] == 30 and len(resp.json()["ticket"]) > 20


def test_auth_off_answers_as_local_owner(home: Path) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE) as client:
        me = client.get("/api/v1/auth/me").json()
        assert (me["user"], me["scope"], me["auth"], me["session_id"]) == (
            "local",
            "admin",
            "off",
            None,
        )
        assert client.post("/api/v1/auth/pairings", json={}).status_code == 400


@pytest.mark.parametrize("mode", ["session", "host", "root", "off"])
def test_ticket_route_is_unique_bounded_and_not_cached(home: Path, mode: str) -> None:
    """All transport modes share one bounded, no-store ticket endpoint."""
    from fastapi.routing import APIRoute

    from hypothex.api.tickets import TicketStore

    scoped = mode in {"session", "host"}
    app = create_app(
        home,
        auth=scoped,
        token_is_host=mode == "host",
        auth_token="synthetic-root" if mode in {"host", "root"} else None,
        background_repair=False,
        hub=False,
        ui_dir=home / "no-ui",
    )
    store = app.state.ws_tickets
    assert isinstance(store, TicketStore)
    store._capacity = 2
    routes = [
        r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/v1/auth/ws-ticket"
    ]
    assert len(routes) == 1
    token = token_for(app.state.auth, "alice", "read") if mode == "session" else "synthetic-root"
    headers = {} if mode == "off" else bearer(token)
    with TestClient(app, base_url=BASE) as client:
        responses = [
            client.post("/api/v1/auth/ws-ticket", json={}, headers=headers) for _ in range(3)
        ]
    assert all(r.headers["cache-control"] == "no-store" for r in responses)
    if mode == "off":
        assert all(r.json() == {"ticket": None, "expires_in": 0} for r in responses)
    else:
        assert [r.status_code for r in responses] == [200, 200, 429]
        assert responses[0].json()["ticket"] != responses[1].json()["ticket"]
        assert responses[0].json()["expires_in"] == 30
