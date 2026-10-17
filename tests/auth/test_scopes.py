import pytest

from hypothex.auth.ownership import OWNER_ACTIONS, may_act, require_act, require_local_exec
from hypothex.auth.scopes import covers, scopes_of
from hypothex.auth.store import HOST_PRINCIPAL, LOCAL_OWNER, PAIRING_INVALID, Principal, ScopeError


def who(user: str, scope: str, agent: str | None = None) -> Principal:
    return Principal(user=user, scope=scope, session_id="s_000000000001", client="cli", agent=agent)


@pytest.mark.parametrize(
    ("held", "wanted", "ok"),
    [
        ("read", "read", True),
        ("read", "launch", False),
        ("read", "admin", False),
        ("launch", "read", True),
        ("launch", "launch", True),
        ("launch", "admin", False),
        ("admin", "read", True),
        ("admin", "admin", True),
    ],
)
def test_covers(held: str, wanted: str, ok: bool) -> None:
    assert covers(held, wanted) is ok  # type: ignore[arg-type]


def test_scopes_of() -> None:
    assert scopes_of("read") == ["read"]
    assert scopes_of("launch") == ["read", "launch"]
    assert scopes_of("admin") == ["read", "launch", "admin"]


def test_identity() -> None:
    assert who("alice", "launch").identity() == "human:alice"
    assert who("alice", "launch", agent="claude").identity() == "agent:claude@alice"
    assert LOCAL_OWNER.scope == "admin" and LOCAL_OWNER.client == "local"


@pytest.mark.parametrize(
    ("user", "scope", "owner", "action", "ok"),
    [
        ("alice", "launch", "alice", "stop", True),
        ("alice", "launch", "sv", "stop", False),
        ("alice", "launch", "sv", "archive", False),
        ("alice", "launch", "sv", "cancel_queued", False),
        ("alice", "launch", "sv", "tag", True),
        ("alice", "launch", "sv", "rerun", True),
        ("alice", "launch", None, "stop", False),
        ("sv", "admin", "alice", "stop", True),
        ("sv", "admin", None, "archive", True),
        ("bob", "read", "bob", "stop", False),
        ("bob", "read", "bob", "note", False),
    ],
)
def test_may_act(user: str, scope: str, owner: str | None, action: str, ok: bool) -> None:
    assert may_act(who(user, scope), owner, action) is ok  # type: ignore[arg-type]


def test_only_admin_starts_runs_on_this_machine() -> None:
    require_local_exec(LOCAL_OWNER)  # auth off
    require_local_exec(HOST_PRINCIPAL)  # a hub forwarding to its host
    require_local_exec(who("sv", "admin"))
    with pytest.raises(ScopeError, match=r"^runs on this machine need admin; launch on a host$"):
        require_local_exec(who("alice", "launch"))


def test_require_act_message_names_the_owner() -> None:
    with pytest.raises(ScopeError, match="run owned by sv; stop needs owner or admin"):
        require_act(who("alice", "launch"), "sv", "stop")
    with pytest.raises(ScopeError, match="run owned by the hub owner"):
        require_act(who("alice", "launch"), None, "archive")
    with pytest.raises(ScopeError, match="launch scope"):
        require_act(who("bob", "read"), "bob", "tag")


def test_owner_actions() -> None:
    assert frozenset({"stop", "archive", "cancel_queued"}) == OWNER_ACTIONS
    assert "expired" in PAIRING_INVALID
