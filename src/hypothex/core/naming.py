"""Run names: derived from the params that differ inside a task, or set by a rename."""

from __future__ import annotations

from hypothex.core.errors import RunNameError

NAME_MAX = 80
"""Longest run name a rename accepts (after trimming)."""


def clean_run_name(name: str | None) -> str | None:
    """
    Normalize a requested run name; empty means "no name" (reset).

    Parameters
    ----------
    name : str or None
        The requested name.

    Returns
    -------
    str or None
        The trimmed name, or None for None or a blank name.

    Raises
    ------
    RunNameError
        If the trimmed name is longer than ``NAME_MAX`` (80) characters or
        contains a line break. It is a ``ValueError`` too, so a request body
        that validates with it answers 422.

    Examples
    --------
    >>> clean_run_name("  lr 3e-4, wide beam ")
    'lr 3e-4, wide beam'
    >>> clean_run_name("   ") is None
    True
    """
    if name is None:
        return None
    text = name.strip()
    if not text:
        return None
    if "\n" in text or "\r" in text:
        raise RunNameError("a run name is one line")
    if len(text) > NAME_MAX:
        raise RunNameError(f"a run name has at most {NAME_MAX} characters, not {len(text)}")
    return text
