"""Bounded ASGI tests for session-bound event streams and ticket transport."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.types import Message

from hypothex.api import app as app_module
from hypothex.auth.store import Principal
from tests.api.authkit import auth_app, token_for


async def exchange(
    app: FastAPI,
    *,
    token: str | None = None,
    protocols: list[str] | None = None,
    subscribe: bool = True,
    on_accept: Callable[[], None] | None = None,
    on_ready: Callable[[], None] | None = None,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
    disconnect_ready: bool = False,
) -> tuple[list[Message], int]:
    """Drive the real ASGI app with a deadline and guaranteed task cleanup.

    Parameters
    ----------
    app : FastAPI
        Application under test.
    token : str, optional
        Bearer credential.
    protocols : list of str, optional
        Offered WebSocket protocols.
    subscribe : bool
        Queue one subscribe frame before the handler enters.
    on_accept, on_ready : callable, optional
        Mutations at precise stream milestones.
    extra_headers : list of tuple, optional
        Additional handshake headers.
    disconnect_ready : bool
        End normally once ready is received.

    Returns
    -------
    tuple
        Outbound ASGI events and consumed subscribe count.
    """
    incoming: asyncio.Queue[Message] = asyncio.Queue()
    incoming.put_nowait({"type": "websocket.connect"})
    if subscribe:
        incoming.put_nowait(
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "subscribe", "after_sequence": 0}),
            }
        )
    outgoing: list[Message] = []
    consumed = 0

    async def receive() -> Message:
        nonlocal consumed
        message = await incoming.get()
        if message["type"] == "websocket.receive":
            consumed += 1
        return message

    async def send(message: Message) -> None:
        outgoing.append(message)
        if message["type"] == "websocket.accept" and on_accept is not None:
            on_accept()
        if message["type"] == "websocket.send" and json.loads(message["text"])["type"] == "ready":
            if on_ready is not None:
                on_ready()
            if disconnect_ready:
                incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})

    headers = [(b"host", b"127.0.0.1:7777")]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    scope: dict[str, Any] = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": "/api/v1/ws",
        "raw_path": b"/api/v1/ws",
        "root_path": "",
        "query_string": b"",
        "headers": headers + (extra_headers or []),
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 7777),
        "subprotocols": protocols or [],
    }
    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(task, timeout=2.0)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    return outgoing, consumed


def test_queued_subscribe_is_consumed_and_revocation_closes(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A positive timeout consumes queued input and closes the revoked stream."""
    monkeypatch.setattr(app_module, "WS_RECHECK_SECONDS", 0.01)
    monkeypatch.setattr(app_module, "WS_POLL_SECONDS", 0.01)
    app = auth_app(home)
    token = token_for(app.state.auth, "alice", "read")
    principal = app.state.auth.authenticate(token)
    messages, consumed = asyncio.run(
        exchange(
            app,
            token=token,
            on_ready=lambda: app.state.auth.revoke(principal.session_id, by=principal),
        )
    )
    assert consumed == 1
    assert any(m["type"] == "websocket.send" and '"ready"' in m["text"] for m in messages)
    assert messages[-1] == {"type": "websocket.close", "code": 4401, "reason": ""}


@pytest.mark.parametrize("trigger", ["revoke", "expire", "disable"])
@pytest.mark.parametrize("moment", ["before_subscribe", "after_ready", "ordinary", "filtered"])
def test_session_invalidation_is_bounded(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    trigger: str,
    moment: str,
) -> None:
    """Idle, ordinary and filtered event streams all recheck the session."""
    monkeypatch.setattr(app_module, "WS_RECHECK_SECONDS", 0.01)
    monkeypatch.setattr(app_module, "WS_POLL_SECONDS", 0.01)
    app = auth_app(home)
    token = token_for(app.state.auth, "alice", "launch")
    principal: Principal = app.state.auth.authenticate(token)
    owner = app.state.auth.authenticate(token_for(app.state.auth, "sv", "admin"))
    if moment in {"ordinary", "filtered"}:
        app.state.ctx.events.append("notebook.updated" if moment == "ordinary" else "notify.sent")

    def invalidate() -> None:
        if trigger == "revoke":
            app.state.auth.revoke(principal.session_id, by=principal)
        elif trigger == "disable":
            app.state.auth.disable_user("alice", by=owner)
        else:
            future = app.state.auth.now() + timedelta(days=366)
            app.state.auth.now = lambda: future

    messages, consumed = asyncio.run(
        exchange(
            app,
            token=token,
            subscribe=moment != "before_subscribe",
            on_accept=invalidate if moment == "before_subscribe" else None,
            on_ready=invalidate if moment != "before_subscribe" else None,
        )
    )
    assert consumed == (0 if moment == "before_subscribe" else 1)
    assert messages[-1]["type"] == "websocket.close" and messages[-1]["code"] == 4401
    events = [json.loads(m["text"]) for m in messages if m["type"] == "websocket.send"]
    if moment == "ordinary":
        assert any(
            e["type"] == "event" and e["event"]["type"] == "notebook.updated" for e in events
        )
    if moment == "filtered":
        assert not any(e["type"] == "event" for e in events)
        assert any(e["type"] == "ready" and e["last_sequence"] > 0 for e in events)


@pytest.mark.parametrize("scope", ["read", "launch", "admin"])
def test_event_scopes_and_ticket_single_use(home: Path, scope: str) -> None:
    """Ticket auth negotiates only the fixed protocol and filters admin events."""
    app = auth_app(home)
    token = token_for(app.state.auth, "sv" if scope == "admin" else "alice", scope)
    app.state.ctx.events.append("auth.session_created")
    app.state.ctx.events.append("notify.sent")
    app.state.ctx.events.append("notebook.updated")
    ticket = app.state.auth.issue_ticket(app.state.auth.authenticate(token))
    protocols = ["hypothex.v1", f"hx-ticket.{ticket}"]
    messages, count = asyncio.run(exchange(app, protocols=protocols, disconnect_ready=True))
    assert count == 1 and messages[0]["subprotocol"] == "hypothex.v1"
    events = [
        json.loads(m["text"])["event"]["type"]
        for m in messages
        if m["type"] == "websocket.send" and json.loads(m["text"])["type"] == "event"
    ]
    assert "notebook.updated" in events
    assert ("auth.session_created" in events) is (scope == "admin")
    assert ("notify.sent" in events) is (scope == "admin")
    again, _ = asyncio.run(exchange(app, protocols=protocols))
    assert again[-1]["code"] == 4401


def test_zero_timeout_cancels_an_unstarted_receive() -> None:
    """Retain the narrow bounded reproduction of the former test setup defect."""

    async def probe(timeout: float) -> int:
        count = 0

        async def receive() -> str:
            nonlocal count
            count += 1
            return "subscribe"

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(receive(), timeout=timeout)
        return count

    assert asyncio.run(probe(0)) == 0
    assert asyncio.run(probe(0.01)) == 1


@pytest.mark.parametrize("bad", ["bearer", "origin", "duplicate", "malformed"])
def test_bad_handshake_leaves_ticket_available(home: Path, bad: str) -> None:
    """Invalid credentials, origins and protocols fail before ticket consumption."""
    app = auth_app(home)
    token = token_for(app.state.auth, "alice", "read")
    ticket = app.state.auth.issue_ticket(app.state.auth.authenticate(token))
    protocols = ["hypothex.v1", f"hx-ticket.{ticket}"]
    offered = protocols + ["hypothex.v1"] if bad == "duplicate" else protocols
    if bad == "malformed":
        offered = ["hypothex.v1", "hx-ticket.invalid"]
    messages, _ = asyncio.run(
        exchange(
            app,
            token="wrong" if bad == "bearer" else None,
            protocols=offered,
            extra_headers=[(b"origin", b"http://evil.example")] if bad == "origin" else None,
        )
    )
    assert messages[-1]["type"] == "websocket.close"
    assert messages[-1]["code"] == (1008 if bad == "origin" else 4401)
    valid, _ = asyncio.run(exchange(app, protocols=protocols, disconnect_ready=True))
    assert valid[0]["type"] == "websocket.accept"


def test_duplicate_fixed_protocol_is_refused_even_with_bearer(home: Path) -> None:
    """A bearer cannot make a malformed duplicate protocol offer valid."""
    app = auth_app(home)
    token = token_for(app.state.auth, "reader", "read")
    messages, _ = asyncio.run(
        exchange(app, token=token, protocols=["hypothex.v1", "hypothex.v1"], disconnect_ready=True)
    )
    assert messages[-1]["type"] == "websocket.close" and messages[-1]["code"] == 4401
