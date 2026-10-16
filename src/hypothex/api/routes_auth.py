"""``/api/v1/auth/*``: pairing, the caller, logout, WebSocket tickets, sessions, users."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from hypothex.api.auth import ADMIN, PUBLIC, READ, SESSION_COOKIE, command_key, principal_of
from hypothex.auth.pairing import pairing_url, qr_text
from hypothex.auth.scopes import Scope, scopes_of
from hypothex.auth.store import (
    AuthStore,
    PairingError,
    ScopeError,
    Session,
)
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.settings import is_loopback_host

PAIR_ATTEMPTS_PER_MINUTE = 10


class PairBody(BaseModel):
    """Body of ``POST /api/v1/auth/pair`` (the link's fragment, sent by the client)."""

    offer_id: str = Field(max_length=32)
    secret: str = Field(max_length=128)
    device: str = Field("device", min_length=1, max_length=64)
    client: Literal["browser", "cli", "agent", "host"] = "browser"


class PairingBody(BaseModel):
    """Body of ``POST /api/v1/auth/pairings``."""

    user: str | None = None
    new_user: bool = False
    scope: Scope = "read"
    ttl_seconds: int = Field(300, ge=1, le=300)
    client_hint: str | None = Field(None, max_length=16)
    command_id: str | None = None


class CommandBody(BaseModel):
    """An optional body with a ``command_id``."""

    command_id: str | None = None


def pair_client_key(peer: str, headers: Mapping[str, str], *, behind_proxy: bool) -> str:
    """
    Choose the address the pairing rate limit counts.

    Behind ``tailscale serve`` (``public_url`` set) every request reaches the hub
    from ``127.0.0.1``; counting the peer would let one person's typos lock
    pairing for the whole lab. Headers count only when the peer is loopback (the
    proxy), so a remote caller cannot pick its own key.

    Parameters
    ----------
    peer : str
        The TCP peer address.
    headers : mapping of str to str
        Request headers (lower-case keys, as Starlette gives them).
    behind_proxy : bool
        The hub has a ``public_url``.

    Returns
    -------
    str
        ``ts:<login>`` from ``Tailscale-User-Login``, else the last
        ``X-Forwarded-For`` hop (the one the proxy appended), else ``peer``.

    Examples
    --------
    >>> pair_client_key("127.0.0.1", {"x-forwarded-for": "a, 100.64.0.7"}, behind_proxy=True)
    '100.64.0.7'
    """
    if behind_proxy and is_loopback_host(peer):
        login = headers.get("tailscale-user-login", "").strip()
        if login:
            return f"ts:{login}"
        hops = [h.strip() for h in headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if hops:
            return hops[-1]
    return peer


class PairLimiter:
    """
    At most ``PAIR_ATTEMPTS_PER_MINUTE`` failed pairing attempts per client address and minute.

    Only failures count: a success used up a fresh one-use secret that only the
    offer's issuer could hand out, so it is no guessing. A lab pairing several
    devices in a minute (or a test suite) is never locked out; a guesser is.

    Parameters
    ----------
    now : callable
        The auth store's clock.
    """

    def __init__(self, now: Callable[[], datetime]) -> None:
        """Initialize the scope dependency or transport guard."""
        self.now = now
        self._fails: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, address: str) -> deque[datetime]:
        """Discard expired pairing failures for one client."""
        now = self.now()
        fails = self._fails[address]
        while fails and now - fails[0] >= timedelta(minutes=1):
            fails.popleft()
        return fails

    def blocked(self, address: str) -> bool:
        """
        Tell whether ``address`` has used up its failed attempts for this minute.

        Parameters
        ----------
        address : str

        Returns
        -------
        bool
        """
        with self._lock:
            return len(self._recent(address)) >= PAIR_ATTEMPTS_PER_MINUTE

    def fail(self, address: str) -> None:
        """
        Count one failed attempt of ``address``.

        Parameters
        ----------
        address : str
        """
        with self._lock:
            self._recent(address).append(self.now())


def register_auth_routes(app: FastAPI, ctx: Context, store: AuthStore) -> None:
    """
    Add the ``/api/v1/auth/*`` routes.

    Parameters
    ----------
    app : FastAPI
    ctx : Context
        For ``auth.*`` events and command receipts.
    store : AuthStore
    """
    limiter = PairLimiter(store.now)

    def session_event(kind: str, session: Session) -> None:
        """Record a session change without any credential values."""
        payload = {"session_id": session.id, "user": session.user, "client": session.client}
        ctx.events.append(kind, payload=payload)

    @app.post("/api/v1/auth/pair", dependencies=PUBLIC)
    def pair(body: PairBody, request: Request) -> JSONResponse:
        """Redeem a single-use offer and issue a browser cookie or client token."""
        if not request.app.state.auth_on:
            raise ConfigError("auth is off on this hub; there is nothing to pair")
        peer = request.client.host if request.client else "unknown"
        behind_proxy = request.app.state.public_url is not None
        address = pair_client_key(peer, request.headers, behind_proxy=behind_proxy)
        if limiter.blocked(address):
            return JSONResponse(
                {"error": "too many pairing attempts; wait a minute", "type": "RateLimitError"},
                status_code=429,
            )
        try:
            session, token = store.redeem(
                body.offer_id, body.secret, client=body.client, device=body.device
            )
        except PairingError:
            limiter.fail(address)
            raise
        session_event("auth.session_created", session)
        out = {
            "user": session.user,
            "scope": session.scope,
            "scopes": scopes_of(session.scope),
            "session_id": session.id,
        }
        if body.client != "browser":
            return JSONResponse({"token": token, **out})
        response = JSONResponse(out)
        public = request.app.state.public_url
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=store.session_days * 86400,
            path="/",
            httponly=True,
            samesite="strict",
            secure=bool(public and public.startswith("https://")),
        )
        return response

    @app.get("/api/v1/auth/me", dependencies=READ)
    def me(request: Request) -> dict[str, Any]:
        """Describe the authenticated caller and server authentication mode."""
        principal = principal_of(request)
        return {
            "user": principal.user,
            "scope": principal.scope,
            "scopes": scopes_of(principal.scope),
            "session_id": principal.session_id,
            "client": principal.client,
            "auth": "on" if request.app.state.auth_on else "off",
            "public_url": request.app.state.public_url,
        }

    @app.post("/api/v1/auth/logout", dependencies=READ)
    def logout(request: Request) -> JSONResponse:
        """Revoke the current session and clear the browser cookie."""
        principal = principal_of(request)
        if principal.session_id is not None:
            session_event("auth.session_revoked", store.revoke(principal.session_id, by=principal))
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.post("/api/v1/auth/pairings", dependencies=READ)
    def pairings(body: PairingBody, request: Request) -> dict[str, Any]:
        """Create a scope-limited pairing offer without storing its secret receipt."""
        if not request.app.state.auth_on:
            raise ConfigError("auth is off; set server.auth: on (or hx serve --auth) to pair")
        principal = principal_of(request)
        user = body.user or principal.user
        exists = store.get_user(user) is not None
        if body.new_user and exists:
            raise ConfigError(f"user {user} exists; drop --new-user")
        if not body.new_user and not exists:
            raise ConfigError(f"no user {user}; add --new-user")
        offer, secret = store.create_offer(
            issuer=principal, user=user, scope=body.scope, ttl_seconds=body.ttl_seconds
        )
        base = request.app.state.public_url or str(request.base_url).rstrip("/")
        url = pairing_url(base, offer.id, secret)
        # never stored as a command receipt: the link holds the secret
        return {
            "offer_id": offer.id,
            "url": url,
            "expires_at": offer.expires_at.isoformat(),
            "qr": qr_text(url),
        }

    @app.get("/api/v1/auth/sessions", dependencies=READ)
    def sessions(request: Request, user: str | None = None) -> list[dict[str, Any]]:
        """List the caller sessions, or all sessions for an administrator."""
        principal = principal_of(request)
        if principal.scope != "admin":
            if user not in (None, principal.user):
                raise ScopeError("listing another user's sessions needs admin")
            user = principal.user
        return to_jsonable(store.sessions(user))

    @app.post("/api/v1/auth/sessions/{session_id}/revoke", dependencies=READ)
    def revoke(
        session_id: str, request: Request, body: CommandBody | None = None
    ) -> dict[str, Any]:
        """Revoke an authorized session under a caller-bound receipt."""
        principal = principal_of(request)

        def act() -> dict[str, Any]:
            """Apply the authorized action once and return its result."""
            session = store.revoke(session_id, by=principal)
            session_event("auth.session_revoked", session)
            return to_jsonable(session)

        key = command_key(request, (body or CommandBody()).command_id)
        return ctx.events.run_once(key, act)

    @app.get("/api/v1/auth/users", dependencies=ADMIN)
    def users() -> list[dict[str, Any]]:
        """List users for an administrator."""
        return to_jsonable(store.users())

    @app.post("/api/v1/auth/users/{name}/disable", dependencies=ADMIN)
    def disable(name: str, request: Request, body: CommandBody | None = None) -> dict[str, Any]:
        """Disable a user and publish revocation events for their sessions."""
        principal = principal_of(request)

        def act() -> dict[str, Any]:
            """Apply the authorized action once and return its result."""
            active = store.sessions(name)
            user = store.disable_user(name, by=principal)
            for session in active:
                session_event("auth.session_revoked", session)
            return to_jsonable(user)

        key = command_key(request, (body or CommandBody()).command_id)
        return ctx.events.run_once(key, act)
