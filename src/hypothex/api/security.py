"""Bearer authentication, DNS-rebinding and cross-origin request protection.

Host and exact-Origin guards run before authentication, including before consuming
one-use WebSocket tickets. Non-browser clients need no Origin header. Every data
route requires a bearer by default; only the exact public identity descriptor and
installed static UI shell are public GET/HEAD resources. Explicit no-auth remains
available to in-process callers and loopback-only ``hx serve --no-auth``.
"""

from __future__ import annotations

import hmac
import ipaddress
import re
from collections.abc import Callable
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from hypothex.api.tickets import TicketStore
from hypothex.core.tokens import validate_bearer_token

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
WILDCARD_BINDS = frozenset({"", "0.0.0.0", "::", "[::]", "*"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CLIENT_HEADER = "x-hypothex-client"
"""A ``POST`` with this header (any value) may send a body that is not JSON."""
DEFAULT_PORTS = {"http": 80, "https": 443}
PUBLIC_DESCRIPTOR = "/.well-known/hypothex/environment"
WS_PATH = "/api/v1/ws"
WS_PROTOCOL = "hypothex.v1"
TICKET_PREFIX = "hx-ticket."
"""The descriptor stays open: ``start.sh`` and the hub read it to find the server."""


def is_loopback_bind(bind_host: str) -> bool:
    """
    Tell whether a bind address only accepts connections from this machine.

    Parameters
    ----------
    bind_host : str
        The ``--host`` given to ``hx serve``.

    Returns
    -------
    bool
        ``True`` for ``localhost`` and loopback IPs (``127.0.0.0/8``, ``::1``);
        ``False`` for wildcards (``0.0.0.0``, ``::``), other IPs, and other
        host names, which may resolve to a public interface.

    Examples
    --------
    >>> is_loopback_bind("127.0.0.1"), is_loopback_bind("[::1]")
    (True, True)
    >>> is_loopback_bind("0.0.0.0"), is_loopback_bind("192.168.1.5")
    (False, False)
    """
    host = bind_host.strip()
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.removeprefix("[").removesuffix("]")).is_loopback
    except ValueError:
        return False


def allowed_hosts(bind_host: str | None = None) -> list[str]:
    """
    Return the ``Host`` header values the server accepts (port excluded).

    Parameters
    ----------
    bind_host : str, optional
        The ``--host`` the server binds to. Added to the loopback names unless
        it is a wildcard address such as ``0.0.0.0``.

    Returns
    -------
    list of str
        Host names; IPv6 addresses are bracketed, as they appear in ``Host``.

    Examples
    --------
    >>> allowed_hosts()
    ['127.0.0.1', 'localhost', '[::1]']
    >>> allowed_hosts("192.168.1.5")
    ['127.0.0.1', 'localhost', '[::1]', '192.168.1.5']
    >>> allowed_hosts("0.0.0.0")
    ['127.0.0.1', 'localhost', '[::1]']
    """
    hosts = list(LOOPBACK_HOSTS)
    if bind_host is None or bind_host.strip() in WILDCARD_BINDS:
        return hosts
    host = bind_host.strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if host not in hosts:
        hosts.append(host)
    return hosts


def origin_allowed(origin: str, hosts: list[str]) -> bool:
    """
    Tell whether an ``Origin`` header names one of ``hosts`` (any port).

    Parameters
    ----------
    origin : str
        Value of the ``Origin`` header, e.g. ``http://127.0.0.1:7777``.
    hosts : list of str
        Allowed host names, as returned by :func:`allowed_hosts`.

    Returns
    -------
    bool
        ``True`` for an ``http``/``https`` origin on an allowed host.

    Examples
    --------
    >>> origin_allowed("http://localhost:5173", allowed_hosts())
    True
    >>> origin_allowed("http://attacker.example:7777", allowed_hosts())
    False
    >>> origin_allowed("null", allowed_hosts())
    False
    """
    try:
        parts = urlsplit(origin)
        hostname = parts.hostname
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not hostname:
        return False
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return hostname in hosts


def same_origin(origin: str, host_header: str | None) -> bool:
    """
    Tell whether an ``Origin`` names the host and port a request was sent to.

    A page the server itself served (or the Vite dev server, which forwards the
    browser's ``Host``) has the request's own origin. Any other local server
    (``localhost:8888``) does not.

    Parameters
    ----------
    origin : str
        Value of the ``Origin`` header, e.g. ``http://127.0.0.1:7777``.
    host_header : str or None
        Value of the request's ``Host`` header, e.g. ``127.0.0.1:7777``.

    Returns
    -------
    bool
        ``True`` when host names and ports match (a missing port is the
        scheme's default).

    Examples
    --------
    >>> same_origin("http://127.0.0.1:7777", "127.0.0.1:7777")
    True
    >>> same_origin("http://localhost:8888", "127.0.0.1:7777")
    False
    >>> same_origin("http://localhost", "localhost:80")
    True
    """
    if not host_header:
        return False
    try:
        page = urlsplit(origin)
        server = urlsplit(f"//{host_header}")
        default = DEFAULT_PORTS.get(page.scheme)
        return (
            page.hostname is not None
            and page.hostname == server.hostname
            and (page.port or default) == (server.port or default)
        )
    except ValueError:
        return False


def is_json(content_type: str | None) -> bool:
    """
    Tell whether a ``Content-Type`` is JSON (``application/json`` or ``application/*+json``).

    Parameters
    ----------
    content_type : str or None
        The header value; parameters such as ``charset`` are ignored.

    Returns
    -------
    bool

    Examples
    --------
    >>> is_json("application/json; charset=utf-8"), is_json("text/plain"), is_json(None)
    (True, False, False)
    """
    media = (content_type or "").partition(";")[0].strip().lower()
    return media == "application/json" or (
        media.startswith("application/") and media.endswith("+json")
    )


class OriginGuard:
    """
    ASGI middleware that rejects cross-origin writes and WebSocket handshakes.

    Requests without an ``Origin`` header pass the origin check; one with an
    ``Origin`` must name an allowed host and be the request's own origin
    (:func:`same_origin`), else ``403`` (a WebSocket is closed with ``1008``).
    Safe HTTP methods (``GET``, ``HEAD``, ``OPTIONS``) pass, because the
    browser's same-origin policy already keeps their responses from a foreign
    page. A ``POST`` must carry a JSON body or the ``X-Hypothex-Client``
    header, else ``415`` (``{error, type: "UnsupportedMediaTypeError"}``).

    Parameters
    ----------
    app : ASGIApp
        The wrapped application.
    hosts : list of str
        Allowed host names, as returned by :func:`allowed_hosts`.
    """

    def __init__(self, app: ASGIApp, hosts: list[str]) -> None:
        self.app = app
        self.hosts = list(hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Reject a foreign ``Origin`` on writes and WebSocket handshakes.

        Parameters
        ----------
        scope : Scope
        receive : Receive
        send : Send
        """
        kind = scope["type"]
        if kind == "websocket" or (kind == "http" and scope["method"] not in SAFE_METHODS):
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if origin is not None and not (
                origin_allowed(origin, self.hosts) and same_origin(origin, headers.get("host"))
            ):
                if kind == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                response = PlainTextResponse("Cross-origin request rejected", status_code=403)
                await response(scope, receive, send)
                return
            if (
                kind == "http"
                and scope["method"] == "POST"
                and not is_json(headers.get("content-type"))
                and CLIENT_HEADER not in headers
            ):
                # a browser sends a POST without JSON or a custom header without a preflight
                response = JSONResponse(
                    {
                        "error": "a POST needs a JSON body (Content-Type: application/json) "
                        "or an X-Hypothex-Client header",
                        "type": "UnsupportedMediaTypeError",
                    },
                    status_code=415,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def bearer_matches(authorization: str | None, token: str) -> bool:
    """
    Tell whether an ``Authorization`` header carries ``Bearer <token>`` (constant time).

    Parameters
    ----------
    authorization : str or None
        The request's ``Authorization`` header.
    token : str
        The server's token.

    Returns
    -------
    bool

    Examples
    --------
    >>> bearer_matches("Bearer s3cret", "s3cret"), bearer_matches(None, "s3cret")
    (True, False)
    """
    return hmac.compare_digest((authorization or "").encode(), f"Bearer {token}".encode())


class TokenGuard:
    """
    Require a bearer for data routes and bearer or one-use ticket for events.

    Parameters
    ----------
    app : ASGIApp
        Wrapped application.
    token : str or None
        Root credential; None explicitly disables authentication.
    tickets : TicketStore
        Process-local ticket issuer shared with the HTTP route.
    public_static : callable
        Whether a GET/HEAD path is an actual installed static resource or SPA route.
    """

    def __init__(
        self,
        app: ASGIApp,
        token: str | None,
        tickets: TicketStore,
        public_static: Callable[[str], bool],
    ) -> None:
        self.app = app
        self._token = None if token is None else validate_bearer_token(token)
        self._tickets = tickets
        self._public_static = public_static

    def _websocket(self, scope: Scope, headers: Headers) -> bool:
        protocols = scope.get("subprotocols", [])
        offered = [p for p in protocols if p.startswith(TICKET_PREFIX)]
        # Only the existing event endpoint accepts ticket credentials.
        if offered and (scope["path"] != WS_PATH or len(offered) != 1):
            return False
        if offered and (
            protocols.count(WS_PROTOCOL) != 1
            or not re.fullmatch(r"hx-ticket\.[A-Za-z0-9_-]{32}", offered[0])
        ):
            return False
        auth = headers.getlist("authorization")
        if len(auth) > 1:
            return False
        if self._token is None:
            valid = not offered
        elif auth:
            # An explicitly offered invalid bearer never falls back to a ticket.
            valid = bearer_matches(auth[0], self._token)
        else:
            valid = bool(offered) and self._tickets.consume(offered[0][len(TICKET_PREFIX) :])
        if valid and scope["path"] == WS_PATH and protocols.count(WS_PROTOCOL) == 1:
            scope["hypothex.ws_protocol"] = WS_PROTOCOL
        return valid

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Validate credentials, without exposing offered secrets in an error.

        Parameters
        ----------
        scope : Scope
        receive : Receive
        send : Send
        """
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if kind == "websocket":
            valid = self._websocket(scope, headers)
        else:
            public = scope["method"] in ("GET", "HEAD") and (
                scope["path"] == PUBLIC_DESCRIPTOR or self._public_static(scope["path"])
            )
            auth = headers.getlist("authorization")
            valid = (
                self._token is None
                or public
                or (len(auth) == 1 and bearer_matches(auth[0], self._token))
            )
        if valid:
            # MCP reads this per-message request scope, never an inherited root fallback.
            if kind == "http":
                scope["hypothex.auth_token"] = (
                    self._token
                    if self._token is not None
                    and len(auth) == 1
                    and bearer_matches(auth[0], self._token)
                    else None
                )
            await self.app(scope, receive, send)
            return
        if kind == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse(
            {"error": "missing or wrong bearer token", "type": "AuthError"}, status_code=401
        )
        await response(scope, receive, send)
