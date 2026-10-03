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

from hypothex.core.errors import HypothexError
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
CREATE TABLE IF NOT EXISTS event_keys (
  key TEXT PRIMARY KEY,
  sequence INTEGER NOT NULL
);
"""
_PENDING = "__pending__"
"""
Result of a claimed receipt whose command is running:
``__pending__:<pid>:<start time>``, with start time ``none`` when it could not
be read.
"""
_INTERRUPTED = "__interrupted__"
"""
Result of a receipt whose claimant died before it stored a result:
``__interrupted__:<time it was found>``. The outcome is unknown, so the
command is never replayed.
"""


def _interrupted(command_id: str) -> CommandInterruptedError:
    return CommandInterruptedError(
        f"command {command_id} was interrupted (the server stopped while it ran); its outcome "
        "is unknown: check the runs, then send it again with a new command_id"
    )


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


class CommandInterruptedError(HypothexError):
    """
    The process running a command died before it stored a result.

    The command may have taken effect (a run launched, a job submitted) or
    not; it is never run again under the same ``command_id``.
    """


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

    def append_once(
        self,
        key: str,
        type_: str,
        *,
        project: str | None = None,
        run_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event | None:
        """
        Append one event unless an event with ``key`` was appended before.

        The key and the event are written in one transaction, so a crash
        never leaves one without the other.

        Parameters
        ----------
        key : str
            Identity of the event, e.g. ``mirror:<host>:<environment_id>:<remote_sequence>``.
        type_ : str
            Event type.
        project, run_id : str, optional
            What the event is about.
        payload : dict, optional
            Event body.

        Returns
        -------
        Event or None
            The stored event, or None when ``key`` was already used.
        """
        now = utcnow()
        body = json.dumps(payload or {}, default=str)
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if conn.execute("SELECT 1 FROM event_keys WHERE key = ?", (key,)).fetchone():
                    conn.execute("COMMIT")
                    return None
                cur = conn.execute(
                    "INSERT INTO events(type, project, run_id, payload, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (type_, project, run_id, body, now.isoformat()),
                )
                sequence = int(cur.lastrowid or 0)
                conn.execute("INSERT INTO event_keys(key, sequence) VALUES (?, ?)", (key, sequence))
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return Event(
            sequence=sequence,
            type=type_,
            project=project,
            run_id=run_id,
            payload=json.loads(body),
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
        result (killed, crashed, server restart), ``fn`` may have taken effect
        (a launched run outlives the server), so it is never run again: the
        receipt is marked interrupted and this and every later caller with
        that id get ``CommandInterruptedError``.

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

        Raises
        ------
        CommandInterruptedError
            The first caller died before it stored a result.
        CommandTimeoutError
            The first caller failed, or is still running after 60 s.
        """
        if command_id is None:
            return fn()
        with self._conn() as conn:
            claimed = (
                conn.execute(
                    "INSERT OR IGNORE INTO receipts(command_id, result, created_at) VALUES (?,?,?)",
                    (command_id, _claim_marker(), utcnow().isoformat()),
                ).rowcount
                == 1
            )
        if not claimed:
            return self._wait_for_result(command_id)
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

    def _wait_for_result(self, command_id: str, timeout: float = 60.0) -> dict[str, Any]:
        """
        Wait for another caller's result.

        Returns
        -------
        dict
            The stored result.

        Raises
        ------
        CommandInterruptedError
            The claimant died without a result (now, or before).
        CommandTimeoutError
            The claimant failed (its claim is gone), or ``timeout`` passed.
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
                if result.startswith(_INTERRUPTED):
                    raise _interrupted(command_id)
                if not result.startswith(_PENDING):
                    return json.loads(result)
                if _claimant_gone(result):
                    conn.execute(
                        "UPDATE receipts SET result = ? WHERE command_id = ? AND result = ?",
                        (f"{_INTERRUPTED}:{utcnow().isoformat()}", command_id, result),
                    )
                    raise _interrupted(command_id)
            time.sleep(0.05)
        raise CommandTimeoutError(f"command {command_id} is still running after {timeout}s")
