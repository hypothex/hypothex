"""Hub side of remote hosts: one connection supervisor per host, and the run mirror.

The hub keeps one supervisor task per host in ``environments.yaml``. A supervisor
opens the route (a plain URL, or SSH bootstrap plus a tunnel), checks the
descriptor, subscribes to the host's event log after the saved cursor, and mirrors
every ``run.*`` event into the hub store. Mirrored runs keep the host's
``environment_id``; the hub re-emits each one as ``mirror.run_updated`` so UI
streams update. Spec sections 5.3, 5.5, 5.6, and 8A.2-8A.3.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel

from hypothex.core.errors import HypothexError
from hypothex.remote.config import HostKind

log = logging.getLogger(__name__)

ConnState = Literal[
    "connecting", "bootstrapping", "connected", "stale", "upgrade", "error", "disabled"
]

MIRROR_FILES = (
    "run.yaml",
    "scores.jsonl",
    "metrics.jsonl",
    "notes.md",
    "usage.jsonl",
    "config.yaml",
    "git.diff",
    "git.stat",
)
MIRROR_DIRS = ("predictions", "traces", "samples", "env", "logs")
MIRROR_MAX_BYTES = 200 * 1024 * 1024

BACKOFF_SECONDS: tuple[float, ...] = (3.0, 4.0, 8.0, 16.0)
STABLE_AFTER_SECONDS = 30.0
STALE_AFTER_SECONDS = 60.0
PING_INTERVAL_SECONDS = 10.0
PING_TIMEOUT_SECONDS = 5.0
REMOTE_FILE_KIND = "remote_file"
MANIFEST_NAME = ".mirror.json"
_SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,200}")
_MESSAGE_LIMIT = 2000


class HostUnavailableError(HypothexError):
    """The host is unknown or not connected, so nothing can be forwarded to it."""


class HostState(BaseModel):
    """
    Connection state of one host, as the hub sees it.

    ``since`` is when ``state`` last changed; for ``stale`` it is the time of the
    last successful contact.

    Examples
    --------
    >>> from hypothex.core.ids import utcnow
    >>> HostState(name="gpu1", kind="ssh", state="connecting", since=utcnow()).last_sequence
    0
    """

    name: str
    kind: HostKind | Literal["local"]  # "local": the hub's own row in GET /api/v1/hosts
    state: ConnState
    since: datetime
    message: str = ""
    environment_id: str | None = None
    hx_version: str | None = None
    last_sequence: int = 0
    local_port: int | None = None


class Backoff:
    """
    Reconnect delays 3/4/8/16 s; the sequence restarts after a stable connection.

    Parameters
    ----------
    delays : tuple of float
        Delays in order; the last one repeats.
    stable_after : float
        A connection that lasted at least this long resets the sequence.

    Examples
    --------
    >>> b = Backoff()
    >>> [b.next_delay(0.0) for _ in range(5)]
    [3.0, 4.0, 8.0, 16.0, 16.0]
    >>> b.connected(100.0)
    >>> b.next_delay(131.0)
    3.0
    """

    def __init__(
        self,
        delays: tuple[float, ...] = BACKOFF_SECONDS,
        stable_after: float = STABLE_AFTER_SECONDS,
    ) -> None:
        if not delays:
            raise ValueError("delays must not be empty")
        self.delays = tuple(delays)
        self.stable_after = stable_after
        self.attempt = 0
        self._connected_at: float | None = None

    def connected(self, now: float) -> None:
        """
        Record that a connection was established.

        Parameters
        ----------
        now : float
            Monotonic time of the connection.
        """
        self._connected_at = now

    def next_delay(self, now: float) -> float:
        """
        Return the delay before the next attempt and advance the sequence.

        Parameters
        ----------
        now : float
            Monotonic time of the failure or disconnect.

        Returns
        -------
        float
            Seconds to wait.
        """
        if self._connected_at is not None and now - self._connected_at >= self.stable_after:
            self.attempt = 0
        self._connected_at = None
        delay = self.delays[min(self.attempt, len(self.delays) - 1)]
        self.attempt += 1
        return delay


# mirror ------------------------------------------------------------------------------
def wanted_path(rel: str) -> bool:
    """
    Return True when a run-relative path is one the hub mirrors.

    Only ``MIRROR_FILES`` and files inside ``MIRROR_DIRS`` qualify; absolute,
    non-normalised, and ``..`` paths never do.

    Parameters
    ----------
    rel : str
        POSIX path relative to the run folder.

    Returns
    -------
    bool

    Examples
    --------
    >>> wanted_path("scores.jsonl"), wanted_path("predictions/predictions.jsonl")
    (True, True)
    >>> wanted_path("artifacts/model.pt"), wanted_path("logs/../../x"), wanted_path("/etc/passwd")
    (False, False, False)
    """
    path = PurePosixPath(rel)
    if not rel or "\\" in rel or path.is_absolute() or str(path) != rel:
        return False
    if any(part in (".", "..") for part in path.parts):
        return False
    if rel in MIRROR_FILES:
        return True
    return len(path.parts) > 1 and path.parts[0] in MIRROR_DIRS
