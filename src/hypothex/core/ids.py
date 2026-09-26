"""Identifier and clock helpers."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime

_SLUG = re.compile(r"[^a-z0-9]+")


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


def new_run_id(task: str | None, now: datetime | None = None) -> str:
    """
    Create a sortable, human-readable run id.

    Parameters
    ----------
    task : str or None
        Task name used as a slug; ``None`` gives ``explore``.
    now : datetime, optional
        Timestamp to embed (UTC). Defaults to now.

    Returns
    -------
    str
        ``YYYYMMDD-HHMMSS-<slug>-<4 hex>``.

    Examples
    --------
    >>> new_run_id("toy-test").count("-") >= 3
    True
    """
    stamp = (now or utcnow()).strftime("%Y%m%d-%H%M%S")
    slug = _SLUG.sub("-", (task or "explore").lower()).strip("-")[:16].strip("-") or "run"
    return f"{stamp}-{slug}-{secrets.token_hex(2)}"


def new_command_id() -> str:
    """Return a random id used to make commands idempotent."""
    return secrets.token_hex(8)
