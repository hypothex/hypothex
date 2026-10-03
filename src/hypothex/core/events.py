"""Per-environment event log and idempotent command receipts (SQLite)."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from pydantic import BaseModel

from hypothex.core.ids import utcnow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  project TEXT,
  run_id TEXT,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
  command_id TEXT PRIMARY KEY,
  result TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""
_PENDING = "__pending__"
"""
Result of a claimed receipt whose command is running:
``__pending__:<pid>:<start time>``, with start time ``none`` when it could not
be read.
"""


def _claim_marker() -> str:
    """
    The pending marker naming this process as the claimant.

    When psutil cannot read this process's start time the marker records
    ``none`` (not ``0.0``, which ``_claimant_gone`` would read as a reused pid).
    """
    pid = os.getpid()
    try:
        started = str(psutil.Process(pid).create_time())
    except psutil.Error:
        started = "none"
    return f"{_PENDING}:{pid}:{started}"


def _claimant_gone(marker: str) -> bool:
    """
    True when the process that claimed a receipt no longer runs.

    A bare ``__pending__`` (written before claimants were recorded) has no
    owner that could still finish it, so it counts as gone. A marker with no
    start time (``none``) counts as alive unless its pid is gone or a zombie.
    """
    parts = marker.split(":")
    if len(parts) != 3:
        return True
    try:
        pid = int(parts[1])
        started = None if parts[2] == "none" else float(parts[2])
    except ValueError:
        return True
    try:
        proc = psutil.Process(pid)
        if started is not None and abs(proc.create_time() - started) > 1.0:
            return True  # the pid was reused
        return proc.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True
    except psutil.Error:
        return started is not None


class Event(BaseModel):
    """One entry of the event log."""

    sequence: int
    type: str
    project: str | None = None
    run_id: str | None = None
    payload: dict[str, Any]
    created_at: datetime


class CommandTimeoutError(RuntimeError):
    """A duplicate command waited too long for the first one to finish."""


class EventLog:
    """
    Append-only event log with monotonically increasing sequence numbers.

    Safe to use from several processes at once (SQLite WAL + busy timeout).

    Parameters
    ----------
    path : Path
        SQLite file, e.g. ``~/.hypothex/events.db``.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    def append(
        self,
        type_: str,
        *,
        project: str | None = None,
        run_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        """
        Append one event.

        Parameters
        ----------
        type_ : str
            Event type, e.g. ``run.created``.
        project : str, optional
            Project the event belongs to.
        run_id : str, optional
            Run the event belongs to.
        payload : dict, optional
            Arbitrary JSON-serialisable event body.

        Returns
        -------
        Event
            The stored event with its sequence number.
        """
        now = utcnow()
        body = payload or {}
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO events(type, project, run_id, payload, created_at) VALUES (?,?,?,?,?)",
                (type_, project, run_id, json.dumps(body, default=str), now.isoformat()),
            )
            sequence = int(cur.lastrowid or 0)
        return Event(
            sequence=sequence,
            type=type_,
            project=project,
            run_id=run_id,
            payload=json.loads(json.dumps(body, default=str)),
            created_at=now,
        )

    def since(self, after_sequence: int, limit: int = 1000) -> list[Event]:
        """
        Return events with ``sequence > after_sequence`` in order.

        Parameters
        ----------
        after_sequence : int
            Last sequence number already seen by the caller.
        limit : int, optional
            Maximum number of events to return.

        Returns
        -------
        list of Event
            Events in ascending sequence order.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE sequence > ? ORDER BY sequence LIMIT ?",
                (after_sequence, limit),
            ).fetchall()
        return [
            Event(
                sequence=r["sequence"],
                type=r["type"],
                project=r["project"],
                run_id=r["run_id"],
                payload=json.loads(r["payload"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def last_sequence(self) -> int:
        """Return the highest sequence number, or 0 when empty."""
        with self._conn() as conn:
            return int(conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM events").fetchone()[0])

    def run_once(self, command_id: str | None, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """
        Run ``fn`` at most once per ``command_id`` and return its stored result.

        A second caller with the same id waits for the first result. If ``fn``
        raises, the claim is released so the command can be retried. The claim
        names the claiming process: if that process died before it stored a
        result (killed, crashed, server restart), the next caller drops the
        claim and runs ``fn`` itself.

        Parameters
        ----------
        command_id : str or None
            Client-generated id; ``None`` disables idempotency.
        fn : callable
            Work to do; must return a JSON-serialisable dict.

        Returns
        -------
        dict
            Result of the first successful call.
        """
        if command_id is None:
            return fn()
        while True:
            with self._conn() as conn:
                claimed = (
                    conn.execute(
                        "INSERT OR IGNORE INTO receipts(command_id, result, created_at) "
                        "VALUES (?,?,?)",
                        (command_id, _claim_marker(), utcnow().isoformat()),
                    ).rowcount
                    == 1
                )
            if claimed:
                break
            result = self._wait_for_result(command_id)
            if result is not None:
                return result
            # the claimant died without a result: its claim was dropped, so claim it now
        try:
            result = fn()
        except BaseException:
            with self._conn() as conn:
                conn.execute("DELETE FROM receipts WHERE command_id = ?", (command_id,))
            raise
        with self._conn() as conn:
            conn.execute(
                "UPDATE receipts SET result = ? WHERE command_id = ?",
                (json.dumps(result, default=str), command_id),
            )
        return json.loads(json.dumps(result, default=str))

    def _wait_for_result(self, command_id: str, timeout: float = 60.0) -> dict[str, Any] | None:
        """
        Wait for another caller's result.

        Returns
        -------
        dict or None
            The stored result, or None when the claimant died without one
            (its claim is deleted, so the caller may claim the command).
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT result FROM receipts WHERE command_id = ?", (command_id,)
                ).fetchone()
                if row is None:
                    raise CommandTimeoutError(
                        f"command {command_id} failed in another caller; retry"
                    )
                result = row["result"]
                if not result.startswith(_PENDING):
                    return json.loads(result)
                if _claimant_gone(result):
                    conn.execute(
                        "DELETE FROM receipts WHERE command_id = ? AND result = ?",
                        (command_id, result),
                    )
                    return None
            time.sleep(0.05)
        raise CommandTimeoutError(f"command {command_id} is still running after {timeout}s")
