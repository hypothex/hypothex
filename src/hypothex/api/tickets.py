"""Bounded, process-local credentials for one WebSocket handshake."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable

TICKET_SECONDS = 30
TICKET_CAPACITY = 256


class TicketStore:
    """
    Mint short-lived tickets and atomically consume each at most once.

    Parameters
    ----------
    clock : callable
        Monotonic clock, injectable for deterministic expiry tests.
    capacity : int
        Maximum outstanding unexpired tickets.
    """

    def __init__(
        self, clock: Callable[[], float] = time.monotonic, capacity: int = TICKET_CAPACITY
    ) -> None:
        self._clock = clock
        self._capacity = capacity
        self._tickets: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue(self) -> str | None:
        """
        Return a random ticket, or None when the outstanding limit is reached.

        Returns
        -------
        str or None
            A secret valid for 30 seconds and one successful consumption.
        """
        with self._lock:
            now = self._clock()
            self._tickets = {key: end for key, end in self._tickets.items() if end > now}
            if len(self._tickets) >= self._capacity:
                return None
            ticket = secrets.token_urlsafe(24)
            self._tickets[ticket] = now + TICKET_SECONDS
            return ticket

    def consume(self, ticket: str) -> bool:
        """
        Atomically remove a ticket and report whether it was still valid.

        Parameters
        ----------
        ticket : str
            Offered handshake secret.

        Returns
        -------
        bool
            True only for the first consumption before expiry.
        """
        with self._lock:
            end = self._tickets.pop(ticket, None)
            return end is not None and end > self._clock()
