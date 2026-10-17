"""Who may act on a run: everyone with ``launch``; stop/archive/cancel only the owner or admin."""

from __future__ import annotations

from typing import Literal

from hypothex.auth.scopes import covers
from hypothex.auth.store import Principal, ScopeError

RunAction = Literal[
    "stop", "archive", "tag", "star", "note", "rerun", "reinfer", "reeval", "cancel_queued",
    "extend", "pull", "name",
]  # fmt: skip
OWNER_ACTIONS = frozenset({"stop", "archive", "cancel_queued"})


def may_act(principal: Principal, owner: str | None, action: RunAction) -> bool:
    """
    Tell whether a principal may take an action on a run.

    Parameters
    ----------
    principal : Principal
        The caller.
    owner : str or None
        ``RunRecord.owner`` (or ``SweepSpec.owner``); None means the hub owner's.
    action : RunAction
        The action.

    Returns
    -------
    bool
        Every action needs ``launch``; ``OWNER_ACTIONS`` also need the caller
        to be the owner, or ``admin``. A run without an owner is the hub
        owner's, so only ``admin`` may stop or archive it.

    Examples
    --------
    >>> p = Principal(user="al", scope="launch", session_id=None, client="cli")
    >>> may_act(p, "al", "stop"), may_act(p, "sv", "stop"), may_act(p, "sv", "tag")
    (True, False, True)
    """
    if not covers(principal.scope, "launch"):
        return False
    if action not in OWNER_ACTIONS or principal.scope == "admin":
        return True
    return owner is not None and principal.user == owner


def require_act(principal: Principal, owner: str | None, action: RunAction) -> None:
    """
    Raise unless ``may_act`` allows the action.

    Parameters
    ----------
    principal : Principal
        The caller.
    owner : str or None
        The run's owner.
    action : RunAction
        The action.

    Raises
    ------
    ScopeError
        ``run owned by <owner>; <action> needs owner or admin``, or a missing
        ``launch`` scope.
    """
    if may_act(principal, owner, action):
        return
    if not covers(principal.scope, "launch"):
        raise ScopeError(f"{action} needs the launch scope; you hold {principal.scope}")
    who = owner if owner is not None else "the hub owner"
    raise ScopeError(f"run owned by {who}; {action} needs owner or admin")


LOCAL_EXEC_REFUSED = "runs on this machine need admin; launch on a host"


def require_local_exec(principal: Principal) -> None:
    """
    Raise unless a principal may start a run on this machine.

    A run executes as this server's Unix user, so its command can read every
    file that user can (``serve/server.json`` with the owner's admin token,
    ``secrets.env``, ``auth.db``, SSH keys). Starting one is trusting the
    caller with all of that, which is ``admin``: the hub owner, every caller
    with auth off (``LOCAL_OWNER``), and a hub forwarding to its host
    (``HOST_PRINCIPAL``). A ``launch`` principal launches on hosts, which run
    jobs under their own account.

    Parameters
    ----------
    principal : Principal
        The caller.

    Raises
    ------
    ScopeError
        ``runs on this machine need admin; launch on a host``.

    Examples
    --------
    >>> from hypothex.auth.store import LOCAL_OWNER
    >>> require_local_exec(LOCAL_OWNER)
    """
    if principal.scope != "admin":
        raise ScopeError(LOCAL_EXEC_REFUSED)
