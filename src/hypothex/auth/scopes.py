"""Scopes: ``read`` ⊂ ``launch`` ⊂ ``admin``."""

from __future__ import annotations

from typing import Literal

Scope = Literal["read", "launch", "admin"]
ScopeOrPublic = Literal["read", "launch", "admin", "public"]
SCOPE_ORDER: tuple[Scope, ...] = ("read", "launch", "admin")
SCOPE_GLYPH: dict[Scope, str] = {"read": "r", "launch": "l", "admin": "a"}


def covers(held: Scope, wanted: Scope) -> bool:
    """
    Tell whether a held scope allows an action that needs ``wanted``.

    Parameters
    ----------
    held : Scope
        The principal's scope.
    wanted : Scope
        The scope the route, socket, or tool declares.

    Returns
    -------
    bool
        True when ``held`` is ``wanted`` or wider.

    Examples
    --------
    >>> covers("admin", "launch"), covers("read", "launch")
    (True, False)
    """
    return SCOPE_ORDER.index(held) >= SCOPE_ORDER.index(wanted)


def scopes_of(held: Scope) -> list[Scope]:
    """
    List every scope a held scope includes.

    Parameters
    ----------
    held : Scope
        The principal's scope.

    Returns
    -------
    list of Scope
        From ``read`` up to ``held``.

    Examples
    --------
    >>> scopes_of("launch")
    ['read', 'launch']
    """
    return list(SCOPE_ORDER[: SCOPE_ORDER.index(held) + 1])
