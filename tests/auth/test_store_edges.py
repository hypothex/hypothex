"""Auth state remains bounded and atomic across failure and concurrent clients."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from hypothex.auth.store import (
    HOST_PRINCIPAL,
    LOCAL_OWNER,
    PAIRING_INVALID,
    AuthStore,
    PairingError,
    ScopeError,
    Session,
    parse_token,
)
from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout
from tests.auth.test_store import Clock, owner, pair


def test_owner_bootstrap_cannot_promote_collaborator(tmp_path: Path) -> None:
    store = AuthStore(Layout(tmp_path))
    admin = owner(store)
    pair(store, admin, "alice", "launch")
    with pytest.raises(ScopeError, match="active admin"):
        store.ensure_owner("alice")
    with pytest.raises(ScopeError, match="initialized"):
        store.ensure_owner("different_owner")
    assert [(u.name, u.role) for u in store.users()] == [("alice", "launch"), ("sv", "admin")]
    with pytest.raises(ScopeError):
        store.mint_local("alice")
    with pytest.raises(ScopeError):
        store.mint_local("missing")


def test_owner_bootstrap_is_atomic_across_store_instances(tmp_path: Path) -> None:
    stores = [AuthStore(Layout(tmp_path)) for _ in range(8)]

    def attempt(index: int) -> bool:
        try:
            stores[index].ensure_owner(f"owner{index}")
        except ScopeError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(8))) == 1
    assert len(stores[0].users()) == 1


def test_disabled_admin_cannot_be_reminted_or_bootstrapped(tmp_path: Path) -> None:
    store = AuthStore(Layout(tmp_path))
    admin = owner(store)
    pair(store, admin, "second", "admin")
    store.disable_user("second", by=admin)
    for operation in (store.ensure_owner, store.mint_local):
        with pytest.raises(ScopeError):
            operation("second")
    with pytest.raises(ScopeError, match="last active admin"):
        store.disable_user("sv", by=HOST_PRINCIPAL)


def test_concurrent_disable_preserves_one_admin(tmp_path: Path) -> None:
    store = AuthStore(Layout(tmp_path))
    admin = owner(store)
    pair(store, admin, "second", "admin")

    def disable(name: str) -> bool:
        try:
            AuthStore(Layout(tmp_path)).disable_user(name, by=LOCAL_OWNER)
        except ScopeError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(disable, ["sv", "second"])) == 1
    assert sum(u.role == "admin" and u.disabled_at is None for u in store.users()) == 1


def test_offer_redemption_is_atomic_across_instances(tmp_path: Path) -> None:
    store = AuthStore(Layout(tmp_path))
    offer, secret = store.create_offer(issuer=owner(store), user="alice", scope="launch")

    def redeem(_: int) -> bool:
        try:
            AuthStore(Layout(tmp_path)).redeem(offer.id, secret, client="cli", device="parallel")
        except PairingError as error:
            assert str(error) == PAIRING_INVALID
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(redeem, range(8))) == 1
    assert len(store.sessions("alice")) == 1


def test_failure_ceiling_is_atomic(tmp_path: Path) -> None:
    store = AuthStore(Layout(tmp_path))
    offer, secret = store.create_offer(issuer=owner(store), user="alice", scope="read")

    def fail(_: int) -> None:
        with pytest.raises(PairingError, match="invalid or expired"):
            AuthStore(Layout(tmp_path)).redeem(offer.id, "wrong", client="cli", device="x")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fail, range(12)))
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT failures FROM offers WHERE id = ?", (offer.id,)).fetchone() == (
            5,
        )
    with pytest.raises(PairingError):
        store.redeem(offer.id, secret, client="cli", device="x")
    assert store.get_user("alice") is None


def test_unexpected_failure_rolls_back_user_and_offer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AuthStore(Layout(tmp_path))
    offer, secret = store.create_offer(issuer=owner(store), user="alice", scope="launch")
    original = store._new_session

    def fail_after_insert(
        conn: sqlite3.Connection,
        user: str,
        scope: str,
        client: str,
        device: str,
        now: datetime,
    ) -> tuple[Session, str]:
        original(conn, user, scope, client, device, now)
        raise RuntimeError("injected persistence failure")

    monkeypatch.setattr(store, "_new_session", fail_after_insert)
    with pytest.raises(RuntimeError, match="injected"):
        store.redeem(offer.id, secret, client="cli", device="x")
    assert store.get_user("alice") is None
    assert store.sessions("alice") == []
    monkeypatch.setattr(store, "_new_session", original)
    assert store.redeem(offer.id, secret, client="cli", device="x")[0].user == "alice"


def test_offer_and_session_exact_expiry_and_slide_boundary(tmp_path: Path) -> None:
    clock = Clock()
    store = AuthStore(Layout(tmp_path), now=clock, session_days=1)
    admin = owner(store)
    offer, secret = store.create_offer(issuer=admin, user="alice", scope="read")
    clock.tick(300)
    with pytest.raises(PairingError):
        store.redeem(offer.id, secret, client="cli", device="x")
    token = pair(store, admin, "alice", "read")
    initial = store.sessions("alice")[0]
    clock.tick(59.999)
    assert store.authenticate(token) is not None
    assert store.sessions("alice")[0].last_seen_at == initial.last_seen_at
    clock.tick(0.001)
    assert store.authenticate(token) is not None
    assert store.sessions("alice")[0].last_seen_at == clock.t
    clock.tick(86400)
    assert store.authenticate(token) is None
    assert not store.session_active(initial.id)
    assert store.sessions("alice") == []


def test_two_new_user_offers_cannot_change_the_first_role(tmp_path: Path) -> None:
    store = AuthStore(Layout(tmp_path))
    admin = owner(store)
    first, secret1 = store.create_offer(issuer=admin, user="alice", scope="read")
    second, secret2 = store.create_offer(issuer=admin, user="alice", scope="admin")
    store.redeem(first.id, secret1, client="cli", device="first")
    with pytest.raises(PairingError):
        store.redeem(second.id, secret2, client="cli", device="second")
    assert store.users()[0].role == "read"


def test_disabled_target_cannot_redeem_outstanding_offer(tmp_path: Path) -> None:
    store = AuthStore(Layout(tmp_path))
    admin = owner(store)
    pair(store, admin, "alice", "read")
    offer, secret = store.create_offer(issuer=admin, user="alice", scope="read")
    store.disable_user("alice", by=admin)
    with pytest.raises(PairingError):
        store.redeem(offer.id, secret, client="cli", device="x")


@pytest.mark.parametrize("ttl", [0, -1, 301, True, 1.5])
def test_invalid_ttl_cannot_create_offer(tmp_path: Path, ttl: int) -> None:
    store = AuthStore(Layout(tmp_path))
    with pytest.raises(PairingError):
        store.create_offer(issuer=owner(store), user="alice", scope="read", ttl_seconds=ttl)


def test_token_parser_requires_exact_full_string() -> None:
    token = "hxs_s_0123456789ab_" + "a" * 43
    assert parse_token(token) is not None
    for value in (token + "\n", token + "x", " " + token, token[:-1]):
        assert parse_token(value) is None


@pytest.mark.parametrize("target", ["directory", "file"])
def test_auth_storage_refuses_symlinks(tmp_path: Path, target: str) -> None:
    outside = tmp_path / "outside"
    if target == "directory":
        outside.mkdir()
        (tmp_path / "auth").symlink_to(outside, target_is_directory=True)
    else:
        outside.write_text("do not change")
        (tmp_path / "auth").mkdir()
        (tmp_path / "auth" / "auth.db").symlink_to(outside)
    with pytest.raises(ConfigError):
        AuthStore(Layout(tmp_path))
    if target == "file":
        assert outside.read_text() == "do not change"
