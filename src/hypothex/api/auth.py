"""FastAPI glue for phase 3 auth: the ASGI guard, scope dependencies, and identities.

Every route declares a scope with ``dependencies=READ`` (or ``LAUNCH``,
``ADMIN``, ``PUBLIC``); ``route_scopes`` lists them, and a unit test fails on
any route without one. Scoped auth replaces the baseline root guard. The
transport adapter below extends the inspected token prerequisite.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from http.cookies import CookieError, SimpleCookie
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Send
from starlette.types import Scope as AsgiScope

from hypothex.api.security import (
    PUBLIC_DESCRIPTOR,
    TICKET_PREFIX,
    WS_PATH,
    WS_PROTOCOL,
    bearer_matches,
)
from hypothex.auth.scopes import ScopeOrPublic, covers
from hypothex.auth.store import (
    HOST_PRINCIPAL,
    LOCAL_OWNER,
    AuthError,
    AuthStore,
    Principal,
    ScopeError,
)
from hypothex.core.tokens import validate_bearer_token

SESSION_COOKIE = "hx_session"
AGENT_HEADER = "X-Hypothex-Agent"
SCOPE_KEY = "x-hx-scope"
PRINCIPAL_KEY = "hx.principal"
CREDENTIAL_KEY = "hypothex.auth_token"  # private ASGI scope state, never a response field
AGENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
UNAUTHORIZED = {"WWW-Authenticate": 'Bearer realm="hypothex"'}
SIGN_IN = "401 · pair this device: hx pair"


def auth_on(conn: HTTPConnection) -> bool:
    """
    Tell whether the app serving a request has auth on.

    Parameters
    ----------
    conn : HTTPConnection
        A request or WebSocket.

    Returns
    -------
    bool
    """
    return bool(getattr(conn.app.state, "auth_on", False))


def principal_of(conn: HTTPConnection) -> Principal:
    """
    Return who is calling.

    Parameters
    ----------
    conn : HTTPConnection
        A request or WebSocket.

    Returns
    -------
    Principal
        The principal ``AuthGuard`` or ``TokenGuard`` resolved; ``LOCAL_OWNER``
        when auth is off and no guard named one.

    Raises
    ------
    AuthError
        Auth is on and the request has no principal (a public route).
    """
    principal = conn.scope.get(PRINCIPAL_KEY)
    if isinstance(principal, Principal):
        return principal
    if auth_on(conn):
        raise AuthError(SIGN_IN)
    return LOCAL_OWNER


class _ScopeCheck:
    """The dependency behind ``requires``; ``route_scopes`` reads ``scope`` back."""

    def __init__(self, scope: ScopeOrPublic) -> None:
        """Initialize the scope dependency or transport guard."""
        self.scope: ScopeOrPublic = scope

    def __call__(self, conn: HTTPConnection) -> Principal | None:
        """Validate the declared scope against the selected caller."""
        if self.scope == "public":
            return None
        principal = principal_of(conn)
        if not covers(principal.scope, self.scope):
            raise ScopeError(f"{self.scope} scope needed; you hold {principal.scope}")
        return principal


def requires(scope: ScopeOrPublic) -> Any:
    """
    Declare the scope a route or WebSocket needs.

    Parameters
    ----------
    scope : {"read", "launch", "admin", "public"}

    Returns
    -------
    Any
        A FastAPI ``Depends``; put it in the route's ``dependencies``.
        ``annotate_scopes`` copies it into ``openapi_extra[SCOPE_KEY]``.
    """
    return Depends(_ScopeCheck(scope))


PUBLIC = [requires("public")]
READ = [requires("read")]
LAUNCH = [requires("launch")]
ADMIN = [requires("admin")]


def _declared(dependant: Any) -> ScopeOrPublic | None:
    """Find the scope declaration in a dependency tree."""
    for dep in getattr(dependant, "dependencies", []):
        if isinstance(dep.call, _ScopeCheck):
            return dep.call.scope
        found = _declared(dep)
        if found is not None:
            return found
    return None


def route_scopes(app: FastAPI) -> dict[str, ScopeOrPublic]:
    """
    List the declared scope of every route and WebSocket.

    Parameters
    ----------
    app : FastAPI

    Returns
    -------
    dict of str to str
        ``"METHOD path"`` (``"WS path"`` for WebSockets; paths without
        converters, as in OpenAPI: ``{path}``, not ``{path:path}``) to its scope;
        routes without a declaration are absent.
    """
    out: dict[str, ScopeOrPublic] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            scope = _declared(route.dependant)
            if scope is not None:
                for method in sorted(route.methods or ()):
                    out[f"{method} {route.path_format}"] = scope
        elif isinstance(route, APIWebSocketRoute):
            scope = _declared(route.dependant)
            if scope is not None:
                out[f"WS {route.path_format}"] = scope
    return out


def annotate_scopes(app: FastAPI) -> None:
    """
    Show each route's scope in the OpenAPI document (``x-hx-scope``).

    Parameters
    ----------
    app : FastAPI
        Call after every route is registered.
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            scope = _declared(route.dependant)
            if scope is not None:
                route.openapi_extra = {**(route.openapi_extra or {}), SCOPE_KEY: scope}


def identity(conn: HTTPConnection, *, created_by: str, owner: str | None) -> tuple[str, str | None]:
    """
    Decide ``created_by`` and ``owner`` for something a request creates.

    Parameters
    ----------
    conn : HTTPConnection
    created_by : str
        The body's value.
    owner : str or None
        The body's value.

    Returns
    -------
    tuple of (str, str or None)
        The body's values from a hub forwarding (``client == "host"`` with
        ``admin`` scope: ``HOST_PRINCIPAL`` or a host session redeemed from an
        admin offer); with auth off ``(created_by, None)``; else the principal's
        identity and user.
    """
    principal = principal_of(conn)
    if principal.client == "host" and principal.scope == "admin":
        return created_by, owner
    if not auth_on(conn):
        return created_by, None
    return principal.identity(), principal.user


def command_key(conn: HTTPConnection, command_id: str | None) -> str | None:
    """
    Bind a client's command id to the caller and the route it was sent to.

    ``EventLog.run_once`` hands a stored result to anyone who repeats a
    command id, without running the route's scope or ownership checks again.
    A raw id would let a reader send an admin's id to a read route and get the
    admin's result back. Every route therefore stores its receipt under this
    key: the caller's user and scope, the method, and the path (operation and
    target). Only the same caller retrying the same call finds it. The body is
    left out on purpose: a retry with an edited body still gets the first
    result (phase 1 rule, ``test_put_view_is_idempotent_by_command_id``).

    Parameters
    ----------
    conn : HTTPConnection
        The request.
    command_id : str or None
        The body's ``command_id``.

    Returns
    -------
    str or None
        ``<user>|<scope>|<METHOD> <path>|<command_id>``; None when
        ``command_id`` is None (no idempotency).

    Examples
    --------
    >>> command_key(request, "c1")  # doctest: +SKIP
    'alice|launch|POST /api/v1/runs/r1/tags|c1'
    """
    if command_id is None:
        return None
    principal = principal_of(conn)
    method = str(conn.scope.get("method", ""))
    path = str(conn.scope.get("path", ""))
    return f"{principal.user}|{principal.scope}|{method} {path}|{command_id}"


def _cookie(header: str | None, name: str) -> str | None:
    """Read one cookie value without exposing malformed input."""
    if not header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(header)
    except CookieError:
        return None
    morsel = jar.get(name)
    return morsel.value if morsel is not None else None


class AuthGuard:
    """Resolve scoped callers through the baseline transport boundary.

    Parameters
    ----------
    app : ASGIApp
        Wrapped application.
    store : AuthStore
        Sessions and the shared bounded ticket issuer.
    host_token : str, optional
        Explicit host credential, never a generated local root credential.
    public_static : callable, optional
        Baseline exact classifier for installed resources and known SPA paths.
    """

    def __init__(
        self,
        app: ASGIApp,
        store: AuthStore,
        *,
        host_token: str | None = None,
        public_static: Callable[[str], bool] | None = None,
    ) -> None:
        """Initialize the scope dependency or transport guard."""
        self.app = app
        self.store = store
        self._host = None if host_token is None else validate_bearer_token(host_token)
        self._public_static = public_static or (lambda path: False)

    def _bearer(self, given: str) -> tuple[Principal | None, str | None]:
        """Resolve one bearer to its principal and exact forwarding credential."""
        if self._host is not None and bearer_matches(given, self._host):
            return HOST_PRINCIPAL, self._host
        if not given.startswith("Bearer "):
            return None, None
        token = given.removeprefix("Bearer ")
        principal = self.store.authenticate(token)
        return principal, token if principal is not None else None

    def _resolve(self, scope: AsgiScope) -> Principal | None:
        """Resolve the transport-selected principal and credential."""
        scope.pop(CREDENTIAL_KEY, None)
        headers = Headers(scope=scope)
        auth_headers = headers.getlist("authorization")
        if len(auth_headers) > 1:
            return None
        principal: Principal | None = None
        credential: str | None = None
        is_ws = scope["type"] == "websocket"
        offered: list[str] = []
        protocols = scope.get("subprotocols", []) if is_ws else []
        if is_ws:
            if len(protocols) != len(set(protocols)):
                return None
            offered = [value for value in protocols if value.startswith(TICKET_PREFIX)]
            if offered and (
                scope["path"] != WS_PATH
                or len(offered) != 1
                or protocols.count(WS_PROTOCOL) != 1
                or re.fullmatch(r"hx-ticket\.[A-Za-z0-9_-]{32}", offered[0]) is None
            ):
                return None
        if auth_headers:
            principal, credential = self._bearer(auth_headers[0])
            if is_ws and principal is None:
                return None  # an explicitly invalid WS bearer never falls back
        if principal is None and is_ws and offered:
            principal = self.store.redeem_ticket(offered[0][len(TICKET_PREFIX) :])
            if principal is None:
                return None  # a cookie cannot bypass one-use ticket consumption
        elif principal is None:
            token = _cookie(headers.get("cookie"), SESSION_COOKIE)
            if token:
                principal = self.store.authenticate(token)
                if principal is not None:
                    credential = token
        if principal is not None:
            scope[CREDENTIAL_KEY] = credential
            if is_ws and scope["path"] == WS_PATH and protocols.count(WS_PROTOCOL) == 1:
                scope["hypothex.ws_protocol"] = WS_PROTOCOL
            agent = headers.get(AGENT_HEADER) or ""
            if principal.client != "host" and AGENT_NAME.fullmatch(agent):
                principal = principal.model_copy(update={"agent": agent})
        return principal

    async def __call__(self, scope: AsgiScope, receive: Receive, send: Send) -> None:
        """Resolve the caller or reject a protected request without leaking secrets.

        Parameters
        ----------
        scope : Scope
            ASGI connection scope.
        receive : Receive
            ASGI incoming event callback.
        send : Send
            ASGI outgoing event callback.
        """
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        static = (
            kind == "http"
            and scope["method"] in ("GET", "HEAD")
            and self._public_static(scope["path"])
        )
        if static:
            await self.app(scope, receive, send)
            return
        public = kind == "http" and (
            (scope["method"] in ("GET", "HEAD") and scope["path"] == PUBLIC_DESCRIPTOR)
            or (scope["method"] == "POST" and scope["path"] == "/api/v1/auth/pair")
        )
        principal = await asyncio.to_thread(self._resolve, scope)
        if principal is not None:
            scope[PRINCIPAL_KEY] = principal
        elif not public:
            if kind == "websocket":
                await receive()
                await send({"type": "websocket.close", "code": 4401})
                return
            await JSONResponse(
                {"error": SIGN_IN, "type": "AuthError"}, status_code=401, headers=UNAUTHORIZED
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)
