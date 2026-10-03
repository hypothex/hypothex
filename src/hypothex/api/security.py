"""Local-only request guards: DNS-rebinding and cross-origin protection.

Phase 1a has no auth, so the API must only answer requests that really come
from this machine. A web page in the user's browser can reach
``127.0.0.1:7777`` in two ways, and both are blocked here:

* **DNS rebinding** - the page's own host name resolves to ``127.0.0.1``. The
  browser then sends ``Host: attacker.example``; the ``Host`` allow-list
  (Starlette's ``TrustedHostMiddleware``) rejects it with ``400``.
* **Cross-origin writes** - the page posts to ``http://127.0.0.1:7777``
  directly. The browser sends ``Origin: https://attacker.example``;
  :class:`OriginGuard` rejects state-changing requests and WebSocket
  handshakes whose ``Origin`` host is not local with ``403``.

Non-browser clients (CLI, MCP clients, ``curl``) send no ``Origin`` header
and are unaffected.

Neither check is authentication: any client that is not a browser can send
``Host: localhost``. So ``hx serve`` binds a non-loopback address only with a
bearer token (``HYPOTHEX_SERVE_TOKEN``), which :class:`TokenGuard` enforces on
every request except the public descriptor.
"""

from __future__ import annotations

import hmac
import ipaddress
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
WILDCARD_BINDS = frozenset({"", "0.0.0.0", "::", "[::]", "*"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PUBLIC_PREFIX = "/.well-known/hypothex/"
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


class OriginGuard:
    """
    ASGI middleware that rejects cross-origin writes and WebSocket handshakes.

    Requests without an ``Origin`` header pass. Safe HTTP methods (``GET``,
    ``HEAD``, ``OPTIONS``) pass, because the browser's same-origin policy
    already keeps their responses from a foreign page.

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
            origin = Headers(scope=scope).get("origin")
            if origin is not None and not origin_allowed(origin, self.hosts):
                if kind == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                response = PlainTextResponse("Cross-origin request rejected", status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class TokenGuard:
    """
    Require ``Authorization: Bearer <token>`` on every HTTP and WebSocket request.

    Only paths under ``PUBLIC_PREFIX`` (the environment descriptor) stay open.
    A missing or wrong token gets ``401`` with ``{error, type: "AuthError"}``;
    a WebSocket handshake is closed with code ``1008``.

    Parameters
    ----------
    app : ASGIApp
        The wrapped application.
    token : str
        The server's token (``HYPOTHEX_SERVE_TOKEN``).
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Pass requests that carry the token (or ask for the descriptor).

        Parameters
        ----------
        scope : Scope
        receive : Receive
        send : Send
        """
        if scope["type"] not in ("http", "websocket") or scope["path"].startswith(PUBLIC_PREFIX):
            await self.app(scope, receive, send)
            return
        given = Headers(scope=scope).get("authorization", "").encode()
        if hmac.compare_digest(given, self._expected):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse(
            {"error": "missing or wrong bearer token", "type": "AuthError"}, status_code=401
        )
        await response(scope, receive, send)
