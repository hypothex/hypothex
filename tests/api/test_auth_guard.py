from pathlib import Path

import pytest
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from hypothex.api.app import create_app
from hypothex.api.auth import (
    PRINCIPAL_KEY,
    READ,
    SCOPE_KEY,
    SESSION_COOKIE,
    AuthGuard,
    annotate_scopes,
    command_key,
    identity,
    principal_of,
    requires,
    route_scopes,
)
from hypothex.auth.store import HOST_PRINCIPAL, LOCAL_OWNER, AuthStore, Principal, ScopeError
from hypothex.core.layout import Layout
from tests.api.authkit import BASE, WS_URL, auth_app, bearer, token_for

ALICE = Principal(user="alice", scope="launch", session_id="s_00000000000a", client="cli")


async def echo(scope: Scope, receive: Receive, send: Send) -> None:
    principal = scope.get(PRINCIPAL_KEY)
    body = None if principal is None else principal.model_dump()
    await JSONResponse({"principal": body})(scope, receive, send)


def request_as(principal: Principal | None, *, on: bool) -> Request:
    app = FastAPI()
    app.state.auth_on = on
    scope: dict = {"type": "http", "app": app, "headers": []}
    if principal is not None:
        scope[PRINCIPAL_KEY] = principal
    return Request(scope)


def test_auth_on_needs_a_session(home: Path) -> None:
    app = auth_app(home)
    with TestClient(app, base_url=BASE) as client:
        refused = client.get("/api/v1/projects")
        assert refused.status_code == 401 and refused.json()["type"] == "AuthError"
        assert refused.headers["WWW-Authenticate"] == 'Bearer realm="hypothex"'
        assert client.get("/.well-known/hypothex/environment").status_code == 200
        token = token_for(app.state.auth, "alice", "read")
        assert client.get("/api/v1/projects", headers=bearer(token)).status_code == 200
        cookie = {"Cookie": f"{SESSION_COOKIE}={token}"}
        assert client.get("/api/v1/projects", headers=cookie).status_code == 200
        assert client.get("/api/v1/projects", headers=bearer("hxs_nope")).status_code == 401


@pytest.mark.parametrize("scoped", [False, True])
def test_guest_spa_deep_links_use_the_installed_shell(
    home: Path, tmp_path: Path, scoped: bool
) -> None:
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html>installed-shell</html>")
    (ui / "asset.js").write_text("export {}")
    outside = tmp_path / "private.js"
    outside.write_text("private")
    (ui / "escape.js").symlink_to(outside)
    app = create_app(
        home,
        auth=scoped,
        auth_token="t" * 43,
        background_repair=False,
        hub=False,
        ui_dir=ui,
    )
    paths = [
        "/",
        "/r/r1",
        "/s/toy/s-1",
        "/x/toy/r1,r2",
        "/t/toy/t",
        "/t/toy/t/edit/view",
        "/settings",
        "/storage",
        "/n/toy",
        "/n/toy/2026-10-04",
        "/pair",
    ]
    with TestClient(app, base_url=BASE) as client:
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200 and "installed-shell" in response.text, path
            assert client.head(path).status_code == 200, path
            assert client.post(path, json={}).status_code == 401, path
        assert client.get("/asset.js").status_code == 200
        for path in [
            "/api/v1/projects",
            "/mcp",
            "/files/private",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/.well-known/private",
            "/unknown",
            "/n",
            "/n/toy/day/extra",
            "/escape.js",
        ]:
            assert client.get(path).status_code == 401, path
    without_ui = create_app(
        home,
        auth=scoped,
        auth_token="t" * 43,
        background_repair=False,
        hub=False,
        ui_dir=tmp_path / "missing-ui",
    )
    with TestClient(without_ui, base_url=BASE) as client:
        for path in paths:
            assert client.get(path).status_code == 401, path


def test_revoked_session_is_401(home: Path) -> None:
    app = auth_app(home)
    store: AuthStore = app.state.auth
    token = token_for(store, "alice", "read")
    alice = store.authenticate(token)
    assert alice is not None
    store.revoke(str(alice.session_id), by=alice)
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/api/v1/projects", headers=bearer(token)).status_code == 401


def test_websocket_without_a_session_is_closed_4401(home: Path) -> None:
    with TestClient(auth_app(home), base_url=BASE) as client:
        with pytest.raises(WebSocketDisconnect) as info, client.websocket_connect(WS_URL):
            pass
        assert info.value.code == 4401


def test_auth_off_is_the_local_owner(home: Path) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    assert app.state.auth_on is False
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/api/v1/projects").status_code == 200
    assert principal_of(request_as(None, on=False)) == LOCAL_OWNER


def test_guards_set_the_principal(tmp_path: Path) -> None:
    store = AuthStore(Layout(tmp_path))
    token = token_for(store, "alice", "launch")
    guarded = TestClient(AuthGuard(echo, store, host_token="hubtoken"), base_url=BASE)
    me = guarded.get("/api/v1/x", headers={**bearer(token), "X-Hypothex-Agent": "claude"})
    assert me.json()["principal"]["user"] == "alice"
    assert me.json()["principal"]["agent"] == "claude"
    bad_agent = guarded.get("/api/v1/x", headers={**bearer(token), "X-Hypothex-Agent": "-x y"})
    assert bad_agent.json()["principal"]["agent"] is None
    hub = guarded.get("/api/v1/x", headers=bearer("hubtoken")).json()["principal"]
    assert hub == HOST_PRINCIPAL.model_dump()


def test_identity_rules() -> None:
    assert identity(request_as(ALICE, on=True), created_by="human:sv", owner="sv") == (
        "human:alice",
        "alice",
    )
    agent = ALICE.model_copy(update={"agent": "claude"})
    assert identity(request_as(agent, on=True), created_by="x", owner=None) == (
        "agent:claude@alice",
        "alice",
    )
    hub = request_as(HOST_PRINCIPAL, on=True)
    assert identity(hub, created_by="human:alice", owner="alice") == ("human:alice", "alice")
    off = request_as(None, on=False)
    assert identity(off, created_by="agent:claude", owner="sv") == ("agent:claude", None)
    assert identity(request_as(HOST_PRINCIPAL, on=False), created_by="h", owner="o") == ("h", "o")


def test_command_key_binds_the_caller_and_the_route() -> None:
    def key(principal: Principal, path: str, command_id: str | None = "c1") -> str | None:
        app = FastAPI()
        app.state.auth_on = True
        scope: dict = {"type": "http", "app": app, "headers": [], "method": "POST", "path": path}
        scope[PRINCIPAL_KEY] = principal
        return command_key(Request(scope), command_id)

    mine = key(ALICE, "/api/v1/runs/r1/tags")
    assert mine == "alice|launch|POST /api/v1/runs/r1/tags|c1"
    assert key(ALICE, "/api/v1/runs/r1/tags") == mine  # a retry finds its receipt
    admin = ALICE.model_copy(update={"scope": "admin"})
    others = {
        key(ALICE, "/api/v1/runs/r2/tags"),  # another target
        key(ALICE, "/api/v1/auth/logout"),  # another operation
        key(admin, "/api/v1/runs/r1/tags"),  # the same user's admin session
        key(HOST_PRINCIPAL, "/api/v1/runs/r1/tags"),  # a hub forwarding
    }
    assert len(others) == 4 and mine not in others
    assert key(ALICE, "/api/v1/runs/r1/tags", None) is None


def test_route_scopes_and_openapi() -> None:
    app = FastAPI()

    @app.get("/a", dependencies=READ)
    def a() -> dict[str, str]:
        return {}

    @app.post("/b", dependencies=[requires("admin")])
    def b() -> dict[str, str]:
        return {}

    @app.get("/c")
    def c() -> dict[str, str]:
        return {}

    @app.websocket("/ws", dependencies=READ)
    async def ws(socket: WebSocket) -> None:
        await socket.close()

    assert route_scopes(app) == {"GET /a": "read", "POST /b": "admin", "WS /ws": "read"}
    annotate_scopes(app)
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert paths["/a"]["get"][SCOPE_KEY] == "read" and SCOPE_KEY not in paths["/c"]["get"]


def test_scope_check_raises_scope_error() -> None:
    check = requires("admin").dependency
    with pytest.raises(ScopeError, match="admin scope needed; you hold launch"):
        check(request_as(ALICE, on=True))
    assert check(request_as(None, on=False)) == LOCAL_OWNER


def test_scoped_handler_preserves_sweep_status_and_recovery_fields(home: Path) -> None:
    import asyncio
    import json
    from datetime import UTC, datetime

    from hypothex.core.errors import HypothexError
    from hypothex.core.sweep_issuance import (
        SweepIssuanceActiveError,
        SweepLegacyResumeRequiredError,
    )
    from hypothex.core.sweeps import SweepIncompleteError, SweepSpec

    app = auth_app(home)
    spec = SweepSpec(
        id="s-1",
        project="toy",
        task=None,
        host="gpu1",
        grid=[],
        seeds=[1, 2],
        command_template=["true"],
        created_by="human:sv",
        created_at=datetime.now(UTC),
    )
    incomplete = SweepIncompleteError(spec, 1, 2, RuntimeError("offline"))
    cases = [
        (SweepIssuanceActiveError("active"), 409),
        (SweepLegacyResumeRequiredError("legacy"), 409),
        (incomplete, 503),
    ]
    handler = app.exception_handlers[HypothexError]
    for error, status in cases:
        response = asyncio.run(handler(Request({"type": "http"}), error))
        assert response.status_code == status
        payload = json.loads(response.body)
        assert payload["type"] == type(error).__name__ and payload["error"] == str(error)
        if error is incomplete:
            assert {
                key: payload[key]
                for key in (
                    "sweep_id",
                    "project",
                    "host",
                    "launched",
                    "total",
                    "hint",
                )
            } == {
                key: getattr(error, key)
                for key in (
                    "sweep_id",
                    "project",
                    "host",
                    "launched",
                    "total",
                    "hint",
                )
            }


@pytest.mark.parametrize(
    "offered", [b"Bearer wrong", b"Bearer ", b"Bearer bad\xa0token", b"Basic nope"]
)
def test_http_forwards_only_the_credential_that_authenticated(
    tmp_path: Path,
    offered: bytes,
) -> None:
    """Rejected bearers may use a valid cookie, whose exact value is selected."""
    from hypothex.api.auth import CREDENTIAL_KEY

    store = AuthStore(Layout(tmp_path))
    token = token_for(store, "alice", "read")

    async def selected(scope: Scope, receive: Receive, send: Send) -> None:
        await JSONResponse(
            {"credential": scope.get(CREDENTIAL_KEY), "user": scope[PRINCIPAL_KEY].user}
        )(scope, receive, send)

    guarded = TestClient(AuthGuard(selected, store), base_url=BASE)
    response = guarded.get(
        "/api/v1/x",
        headers=[(b"authorization", offered), (b"cookie", f"hx_session={token}".encode())],
    )
    assert response.status_code == 200
    assert response.json() == {"credential": token, "user": "alice"}
    denied = guarded.get("/api/v1/x", headers=[(b"authorization", offered)])
    assert denied.status_code == 401


def test_public_descriptor_exposes_full_details_only_to_selected_identity(home: Path) -> None:
    """Anonymous identity stays minimal while an actual session gets the descriptor."""
    app = auth_app(home, auth_token="root-never-selected")
    token = token_for(app.state.auth, "reader", "read")
    with TestClient(app, base_url=BASE) as client:
        for headers in ({}, bearer("root-never-selected"), bearer("wrong")):
            response = client.get("/.well-known/hypothex/environment", headers=headers)
            assert set(response.json()) == {"environment_id", "protocol_version", "hx_version"}
        full = client.get("/.well-known/hypothex/environment", headers=bearer(token)).json()
        assert full == app.state.ctx.descriptor.model_dump(mode="json")


def test_default_root_is_owner_and_explicit_host_preserves_forwarded_identity(home: Path) -> None:
    """Token provenance selects owner versus host rather than token string equality."""
    for host in (False, True):
        app = create_app(
            home,
            auth_token="explicit",
            token_is_host=host,
            hub=False,
            background_repair=False,
            ui_dir=home / "missing-ui",
        )
        with TestClient(app, base_url=BASE) as client:
            refused = client.get("/api/v1/auth/me")
            assert refused.status_code == 401
            assert refused.headers["www-authenticate"] == 'Bearer realm="hypothex"'
            me = client.get("/api/v1/auth/me", headers=bearer("explicit")).json()
        assert me["client"] == ("host" if host else "local")
