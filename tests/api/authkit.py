"""Test helpers: a hub app with auth on, and session tokens for each scope."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI

from hypothex.auth.scopes import Scope
from hypothex.auth.store import AuthStore, Principal

BASE = "http://127.0.0.1:7777"
WS_URL = "ws://127.0.0.1:7777/api/v1/ws"
OWNER = Principal(user="sv", scope="admin", session_id=None, client="local")


def auth_app(home: Path, **kwargs: Any) -> FastAPI:
    """A hub app with auth on, no host connections, no background loops, no UI."""
    from hypothex.api.app import create_app

    options: dict[str, Any] = {"background_repair": False, "hub": False, "auth": True}
    options.update(kwargs)
    return create_app(home, ui_dir=home / "no-ui", **options)


def token_for(store: AuthStore, user: str, scope: Scope, *, client: str = "cli") -> str:
    """A fresh session token for ``user`` (created with role ``scope`` when new)."""
    store.ensure_owner("sv")
    offer, secret = store.create_offer(issuer=OWNER, user=user, scope=scope)
    _, token = store.redeem(offer.id, secret, client=client, device="test")  # type: ignore[arg-type]
    return token


def bearer(token: str) -> dict[str, str]:
    """The ``Authorization`` header of a token."""
    return {"Authorization": f"Bearer {token}"}
