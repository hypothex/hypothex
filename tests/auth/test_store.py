import re
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hypothex.auth.store import (
    PAIRING_INVALID,
    AuthStore,
    PairingError,
    Principal,
    ScopeError,
    parse_token,
)
from hypothex.core.layout import Layout

T0 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
TOKEN = re.compile(r"^hxs_s_[0-9a-f]{12}_[A-Za-z0-9_-]{43}$")


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> datetime:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path, clock: Clock) -> AuthStore:
    return AuthStore(Layout(tmp_path), now=clock, session_days=90)


def owner(store: AuthStore) -> Principal:
    store.ensure_owner("sv")
    session, token = store.mint_local("sv")
    principal = store.authenticate(token)
    assert principal is not None
    return principal


def pair(store: AuthStore, issuer: Principal, user: str, scope: str, client: str = "cli") -> str:
    offer, secret = store.create_offer(issuer=issuer, user=user, scope=scope)  # type: ignore[arg-type]
    _, token = store.redeem(offer.id, secret, client=client, device="laptop")  # type: ignore[arg-type]
    return token


def test_files_are_private(store: AuthStore, tmp_path: Path) -> None:
    store.ensure_owner("sv")
    assert stat.S_IMODE((tmp_path / "auth").stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_ensure_owner_is_idempotent(store: AuthStore) -> None:
    first = store.ensure_owner("sv")
    again = store.ensure_owner("sv")
    assert first == again and first.role == "admin"
    assert [u.name for u in store.users()] == ["sv"]


def test_pair_a_new_collaborator(store: AuthStore) -> None:
    admin = owner(store)
    offer, secret = store.create_offer(issuer=admin, user="alice", scope="launch")
    assert offer.new_user and offer.id.startswith("p_") and len(secret) == 43
    assert offer.expires_at == T0 + timedelta(seconds=300)
    session, token = store.redeem(offer.id, secret, client="cli", device="MacBook")
    assert TOKEN.match(token) and session.user == "alice" and session.scope == "launch"
    alice = store.authenticate(token)
    assert alice == Principal(user="alice", scope="launch", session_id=session.id, client="cli")
    assert store.get_user("alice") is not None and store.get_user("alice").role == "launch"


def test_pairing_never_widens_scope(store: AuthStore) -> None:
    admin = owner(store)
    alice = store.authenticate(pair(store, admin, "alice", "launch"))
    assert alice is not None
    with pytest.raises(ScopeError):
        store.create_offer(issuer=alice, user="alice", scope="admin")
    with pytest.raises(ScopeError, match="needs admin"):
        store.create_offer(issuer=alice, user="bob", scope="read")  # a new user
    with pytest.raises(ScopeError, match="needs admin"):
        store.create_offer(issuer=alice, user="sv", scope="read")  # another user
    offer, _ = store.create_offer(issuer=alice, user="alice", scope="read")  # own device, narrower
    assert offer.scope == "read" and not offer.new_user
    with pytest.raises(ScopeError, match="role"):
        store.create_offer(issuer=admin, user="alice", scope="admin")  # wider than her role


def test_host_sessions_need_an_admin_offer(store: AuthStore) -> None:
    admin = owner(store)
    alice = store.authenticate(pair(store, admin, "alice", "launch"))
    assert alice is not None
    offer, secret = store.create_offer(issuer=alice, user="alice", scope="launch")
    with pytest.raises(PairingError) as info:
        store.redeem(offer.id, secret, client="host", device="forged-hub")
    assert str(info.value) == PAIRING_INVALID
    session, _ = store.redeem(offer.id, secret, client="cli", device="laptop")  # not used up
    assert session.client == "cli"
    offer, secret = store.create_offer(issuer=admin, user="sv", scope="admin")
    session, _ = store.redeem(offer.id, secret, client="host", device="hub:lab")
    assert session.client == "host" and session.scope == "admin"


def test_ttl_is_at_most_five_minutes(store: AuthStore) -> None:
    with pytest.raises(PairingError):
        store.create_offer(issuer=owner(store), user="alice", scope="read", ttl_seconds=301)


def test_offer_is_one_use(store: AuthStore) -> None:
    offer, secret = store.create_offer(issuer=owner(store), user="alice", scope="read")
    store.redeem(offer.id, secret, client="browser", device="phone")
    with pytest.raises(PairingError) as info:
        store.redeem(offer.id, secret, client="browser", device="phone")
    assert str(info.value) == PAIRING_INVALID


def test_expired_offer_is_refused(store: AuthStore, clock: Clock) -> None:
    offer, secret = store.create_offer(issuer=owner(store), user="alice", scope="read")
    clock.tick(301)
    with pytest.raises(PairingError, match="invalid or expired"):
        store.redeem(offer.id, secret, client="cli", device="x")


def test_five_wrong_secrets_burn_the_offer(store: AuthStore) -> None:
    offer, secret = store.create_offer(issuer=owner(store), user="alice", scope="read")
    for _ in range(5):
        with pytest.raises(PairingError):
            store.redeem(offer.id, "x" * 43, client="cli", device="x")
    with pytest.raises(PairingError):
        store.redeem(offer.id, secret, client="cli", device="x")


def test_unknown_offer_has_the_same_message(store: AuthStore) -> None:
    with pytest.raises(PairingError) as info:
        store.redeem("p_000000000000", "y" * 43, client="cli", device="x")
    assert str(info.value) == PAIRING_INVALID


def test_sessions_slide_and_expire(store: AuthStore, clock: Clock) -> None:
    token = pair(store, owner(store), "alice", "read")
    clock.tick(89 * 86400)
    assert store.authenticate(token) is not None  # slides: expires 90 days from now
    clock.tick(89 * 86400)
    assert store.authenticate(token) is not None
    clock.tick(91 * 86400)
    assert store.authenticate(token) is None


def test_tampered_token_is_refused(store: AuthStore) -> None:
    token = pair(store, owner(store), "alice", "read")
    assert store.authenticate(token[:-1] + ("A" if token[-1] != "A" else "B")) is None
    assert store.authenticate("hxs_garbage") is None
    assert parse_token(token) is not None and parse_token("Bearer x") is None


def test_revoke_own_other_and_admin(store: AuthStore) -> None:
    admin = owner(store)
    alice_token = pair(store, admin, "alice", "launch")
    pair(store, admin, "bob", "read")
    alice = store.authenticate(alice_token)
    assert alice is not None
    bob_session = next(s for s in store.sessions("bob"))
    with pytest.raises(ScopeError):
        store.revoke(bob_session.id, by=alice)
    store.revoke(bob_session.id, by=admin)
    assert store.sessions("bob") == []
    store.revoke(str(alice.session_id), by=alice)
    assert store.authenticate(alice_token) is None


def test_disable_user_revokes_sessions(store: AuthStore) -> None:
    admin = owner(store)
    token = pair(store, admin, "alice", "launch")
    user = store.disable_user("alice", by=admin)
    assert user.disabled_at == T0
    assert store.authenticate(token) is None
    with pytest.raises(ScopeError):
        store.disable_user("sv", by=admin)  # never yourself


def test_secrets_are_stored_hashed(store: AuthStore) -> None:
    offer, secret = store.create_offer(issuer=owner(store), user="alice", scope="read")
    _, token = store.redeem(offer.id, secret, client="cli", device="x")
    data = store.path.read_bytes()
    parts = parse_token(token)
    assert parts is not None
    assert secret.encode() not in data and parts[1].encode() not in data


def test_mint_local_is_an_admin_local_session(store: AuthStore) -> None:
    store.ensure_owner("sv")
    session, token = store.mint_local("sv")
    assert session.client == "local" and session.scope == "admin"
    principal = store.authenticate(token)
    assert principal is not None and principal.user == "sv" and principal.scope == "admin"
