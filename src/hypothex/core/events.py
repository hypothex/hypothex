"""Per-environment event log and idempotent command receipts (SQLite)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from pydantic import BaseModel

from hypothex.core.errors import HypothexError, StoreError
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
CREATE TABLE IF NOT EXISTS sweep_issuance (
  operation_key TEXT PRIMARY KEY,
  project TEXT NOT NULL,
  sweep_id TEXT,
  episode INTEGER NOT NULL,
  revision INTEGER NOT NULL,
  state TEXT NOT NULL,
  data TEXT NOT NULL,
  UNIQUE(project, sweep_id, episode)
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
    Each thread keeps one open connection (a new one after a fork), so an
    append costs one insert, not a connect.

    Parameters
    ----------
    path : Path
        SQLite file, e.g. ``~/.hypothex/events.db``.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")  # stored in the file: once is enough
            conn.executescript(_SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(sweep_issuance)")}
            required = {
                "operation_key",
                "project",
                "sweep_id",
                "episode",
                "revision",
                "state",
                "data",
            }
            if not required <= columns:
                raise StoreError("unrecognized sweep issuance schema; existing data was preserved")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Yield this thread's connection (autocommit); roll back a transaction left open."""
        local = self._local
        conn: sqlite3.Connection | None = getattr(local, "conn", None)
        if conn is None or local.pid != os.getpid():
            conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            conn.execute("PRAGMA busy_timeout=10000")
            conn.row_factory = sqlite3.Row
            local.conn, local.pid = conn, os.getpid()
        try:
            yield conn
        finally:
            if conn.in_transaction:
                conn.rollback()

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

    def command_result(self, command_id: str) -> dict[str, Any] | None:
        """
        Read an existing command receipt without claiming or replaying its action.

        Parameters
        ----------
        command_id : str
            The same effective key used by ``run_once``.

        Returns
        -------
        dict or None
            Immutable result, or None if there is no receipt. Existing pending
            and interrupted claims keep ``run_once``'s waiting/error semantics.
        """
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM receipts WHERE command_id = ?", (command_id,)
            ).fetchone()
        return self._wait_for_result(command_id) if exists else None

    @staticmethod
    def _sweep_data(row: sqlite3.Row | None) -> dict[str, Any] | None:
        """Decode only the supported operational row version; never repair unknown data."""
        if row is None:
            return None
        try:
            data = json.loads(row["data"])
        except (ValueError, TypeError) as exc:
            raise StoreError("invalid sweep issuance data; existing data was preserved") from exc
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise StoreError(
                "unsupported sweep issuance schema version; existing data was preserved"
            )
        return data

    def sweep_operation_by_key(self, operation_key: str) -> dict[str, Any] | None:
        """
        Read one durable sweep operation, including an unfinished preparation.

        Parameters
        ----------
        operation_key : str
            Accepted command key, or a generated key for a no-ID request.

        Returns
        -------
        dict or None
            A detached copy of the operational document.
        """
        with self._conn() as conn:
            return self._sweep_data(
                conn.execute(
                    "SELECT data FROM sweep_issuance WHERE operation_key = ?", (operation_key,)
                ).fetchone()
            )

    def sweep_operation(self, project: str, sweep_id: str) -> dict[str, Any] | None:
        """
        Read the latest issuance episode for a sweep.

        Parameters
        ----------
        project, sweep_id : str
            Local definition identity.

        Returns
        -------
        dict or None
            Current operation, or None for a legacy/direct-core sweep.
        """
        with self._conn() as conn:
            return self._sweep_data(
                conn.execute(
                    "SELECT data FROM sweep_issuance WHERE project = ? AND sweep_id = ? "
                    "ORDER BY episode DESC LIMIT 1",
                    (project, sweep_id),
                ).fetchone()
            )

    def sweep_operations(self, states: set[str]) -> list[dict[str, Any]]:
        """
        Discover persisted operations in the requested states after a lost wakeup.

        Parameters
        ----------
        states : set of str
            States the dispatcher can recover or process.

        Returns
        -------
        list of dict
            Operational documents in insertion order.
        """
        if not states:
            return []
        placeholders = ",".join("?" for _ in states)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT data FROM sweep_issuance WHERE state IN ({placeholders}) ORDER BY rowid",
                sorted(states),
            ).fetchall()
        return [data for row in rows if (data := self._sweep_data(row)) is not None]

    def prepare_sweep(
        self,
        operation_key: str,
        data: dict[str, Any],
        *,
        previous: tuple[str, int] | None = None,
    ) -> bool:
        """
        Atomically reserve a command receipt and persist launch-free preparation.

        Parameters
        ----------
        operation_key : str
            Effective command key in the ordinary shared receipt namespace.
        data : dict
            Version-1 operational document in preparing state, with a nonnegative revision.
        previous : tuple of str and int, optional
            Previous episode key and revision. An extension claims its receipt only
            if this is still the latest terminal episode in the same transaction.

        Returns
        -------
        bool
            True for the new claim; False when that command is already owned.
            No member side effect is permitted before its acceptance transaction.
        """
        state = data["issuance"]
        if (
            data.get("schema_version") != 1
            or state["state"] != "preparing"
            or state["revision"] < 0
        ):
            raise ValueError(
                "a sweep preparation must have version 1 and nonnegative preparing revision"
            )
        if data["operation_key"] != operation_key:
            raise ValueError("sweep preparation key differs from its command receipt")
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM sweep_issuance WHERE operation_key = ?", (operation_key,)
            ).fetchone():
                conn.rollback()
                return False
            if previous is not None:
                latest = conn.execute(
                    "SELECT operation_key,revision,state FROM sweep_issuance "
                    "WHERE project=? AND sweep_id=? ORDER BY episode DESC LIMIT 1",
                    (data["project"], data["sweep_id"]),
                ).fetchone()
                if (
                    latest is None
                    or (latest[0], latest[1]) != previous
                    or latest[2] not in {"issued", "incomplete", "interrupted"}
                ):
                    conn.rollback()
                    return False
            claimed = conn.execute(
                "INSERT OR IGNORE INTO receipts(command_id, result, created_at) VALUES (?,?,?)",
                (operation_key, _claim_marker(), utcnow().isoformat()),
            ).rowcount
            if not claimed:
                conn.rollback()
                return False
            conn.execute(
                "INSERT INTO sweep_issuance"
                "(operation_key,project,sweep_id,episode,revision,state,data) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    operation_key,
                    data["project"],
                    data["sweep_id"],
                    data["episode"],
                    state["revision"],
                    "preparing",
                    json.dumps(data, default=str),
                ),
            )
            conn.commit()
        return True

    @staticmethod
    def _append_sweep_event(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
        """Append only the public invalidation payload inside the caller's transaction."""
        state = data["issuance"]
        payload = {
            "project": data["project"],
            "sweep_id": data["sweep_id"],
            "episode": state["episode"],
            "revision": state["revision"],
            "state": state["state"],
            "cancel_requested": state["cancel_requested"],
            "error_type": state["error"]["type"] if state["error"] else None,
        }
        conn.execute(
            "INSERT INTO events(type,project,run_id,payload,created_at) VALUES (?,?,NULL,?,?)",
            ("sweep.issuance", data["project"], json.dumps(payload), state["updated_at"]),
        )

    def update_sweep(
        self,
        operation_key: str,
        expected_revision: int,
        changes: dict[str, Any],
        *,
        receipt: dict[str, Any] | None = None,
        emit: bool = True,
        require_current: bool = False,
    ) -> dict[str, Any] | None:
        """
        Compare-and-set sweep state, optionally committing its immutable receipt.

        Parameters
        ----------
        operation_key : str
            Existing operation key.
        expected_revision : int
            Revision read by the caller; a concurrent transition invalidates it.
        changes : dict
            Top-level document updates; issuance is a complete public-state object.
        receipt : dict, optional
            First acceptance snapshot, allowed only from preparing to queued.
        emit : bool
            Append ``sweep.issuance`` atomically; False for private preparation/progress.
        require_current : bool
            Refuse a transition if a newer episode has already been accepted/prepared.

        Returns
        -------
        dict or None
            Updated detached document, or None if the expected revision is stale.
        """
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._sweep_data(
                conn.execute(
                    "SELECT data FROM sweep_issuance WHERE operation_key = ? AND revision = ?",
                    (operation_key, expected_revision),
                ).fetchone()
            )
            if current is None:
                conn.rollback()
                return None
            if require_current:
                latest = conn.execute(
                    "SELECT operation_key FROM sweep_issuance WHERE project=? AND sweep_id=? "
                    "ORDER BY episode DESC LIMIT 1",
                    (current["project"], current["sweep_id"]),
                ).fetchone()
                if latest is None or latest[0] != operation_key:
                    conn.rollback()
                    return None
            data = {**current, **changes}
            data["issuance"] = {**data["issuance"], "revision": expected_revision + 1}
            state = data["issuance"]
            if data["operation_key"] != operation_key or data["episode"] != current["episode"]:
                raise StoreError("a sweep transition cannot change operation identity")
            if receipt is not None:
                if current["issuance"]["state"] != "preparing" or state["state"] != "queued":
                    raise StoreError("sweep acceptance receipt can only be committed once")
                previous = conn.execute(
                    "SELECT result FROM receipts WHERE command_id = ?", (operation_key,)
                ).fetchone()
                if previous is None or not previous[0].startswith((_PENDING, _INTERRUPTED)):
                    raise StoreError("sweep preparation no longer owns its pending receipt")
                conn.execute(
                    "UPDATE receipts SET result = ? WHERE command_id = ?",
                    (json.dumps(receipt, default=str), operation_key),
                )
            conn.execute(
                "UPDATE sweep_issuance SET sweep_id=?, revision=?, state=?, data=? "
                "WHERE operation_key=?",
                (
                    data["sweep_id"],
                    state["revision"],
                    state["state"],
                    json.dumps(data, default=str),
                    operation_key,
                ),
            )
            if emit and data["sweep_id"] is not None:
                self._append_sweep_event(conn, data)
            conn.commit()
        return json.loads(json.dumps(data, default=str))

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
