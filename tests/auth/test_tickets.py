from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hypothex.auth.store import LOCAL_OWNER, AuthError, AuthStore
from hypothex.core.layout import Layout


def test_ticket_monotonic_boundary_capacity_and_wall_clock(tmp_path: Path) -> None:
    monotonic = [0.0]
    wall = [datetime(2026, 10, 5, tzinfo=UTC)]
    store = AuthStore(
        Layout(tmp_path),
        now=lambda: wall[0],
        ticket_clock=lambda: monotonic[0],
        ticket_capacity=2,
    )
    first = store.issue_ticket(LOCAL_OWNER)
    second = store.issue_ticket(LOCAL_OWNER)
    assert first is not None and second is not None and store.issue_ticket(LOCAL_OWNER) is None
    wall[0] += timedelta(days=365)
    monotonic[0] = 29.999
    assert store.redeem_ticket(first) == LOCAL_OWNER
    assert store.redeem_ticket(first) is None
    wall[0] -= timedelta(days=730)
    monotonic[0] = 30.0
    assert store.redeem_ticket(second) is None
    assert store.issue_ticket(LOCAL_OWNER) is not None


def test_ticket_is_atomic_instance_local_and_rechecks_revocation(tmp_path: Path) -> None:
    store = AuthStore(Layout(tmp_path / "one"))
    other = AuthStore(Layout(tmp_path / "two"))
    store.ensure_owner("sv")
    session, token = store.mint_local("sv")
    principal = store.authenticate(token)
    assert principal is not None
    ticket = store.issue_ticket(principal)
    assert ticket is not None and other.redeem_ticket(ticket) is None
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(store.redeem_ticket, [ticket] * 8))
    assert sum(value is not None for value in values) == 1
    ticket = store.issue_ticket(principal)
    assert ticket is not None
    store.revoke(session.id, by=principal)
    assert store.redeem_ticket(ticket) is None
    with pytest.raises(AuthError, match="no longer active"):
        store.issue_ticket(principal)


def test_default_ticket_capacity_and_payload_snapshot(tmp_path: Path) -> None:
    store = AuthStore(Layout(tmp_path))
    principal = LOCAL_OWNER.model_copy(deep=True)
    tickets = [store.issue_ticket(principal) for _ in range(256)]
    assert all(ticket is not None for ticket in tickets)
    assert store.issue_ticket(principal) is None
    principal.user = "changed"
    first = tickets[0]
    assert first is not None
    assert store.redeem_ticket(first) == LOCAL_OWNER
    assert store.issue_ticket(LOCAL_OWNER) is not None


def test_ticket_rechecks_disabled_user_and_session_expiry(tmp_path: Path) -> None:
    from tests.auth.test_store import Clock, owner, pair

    clock = Clock()
    store = AuthStore(Layout(tmp_path), now=clock, session_days=1)
    admin = owner(store)
    token = pair(store, admin, "alice", "read")
    principal = store.authenticate(token)
    assert principal is not None
    ticket = store.issue_ticket(principal)
    assert ticket is not None
    store.disable_user("alice", by=admin)
    assert store.redeem_ticket(ticket) is None
    with pytest.raises(AuthError):
        store.issue_ticket(principal)
    ticket = store.issue_ticket(admin)
    assert ticket is not None
    clock.tick(86400)
    assert store.redeem_ticket(ticket) is None
    with pytest.raises(AuthError):
        store.issue_ticket(admin)


def test_ticket_store_payload_keeps_boolean_root_contract() -> None:
    from hypothex.api.tickets import TicketStore

    store = TicketStore()
    ticket = store.issue()
    assert ticket is not None and store.consume(ticket) is True
    assert store.consume(ticket) is False
    value = {"example": "payload"}
    ticket = store.issue(value)
    assert ticket is not None and store.redeem(ticket) is value
    assert store.redeem(ticket) is None
