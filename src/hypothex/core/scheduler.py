"""Host-level GPU queue for SSH hosts (spec 8A.5): FIFO, first fit.

A run waits in the queue while it is ``queued`` and its folder holds
``queue.json``. Each ``tick`` starts, in queue order, every run whose GPU
count fits the GPUs that are free right now (no hx run holds them and
``nvidia-smi`` shows no process on them).

A run's ``executor.queue_position`` is its queue ticket: written once, when it
joins, one above every ticket still waiting. So ticket order is queue order,
and a start or a stop never rewrites the runs behind it. The live 1-based
place is the rank of the ticket among the waiting runs: ``positions()`` here,
and the same rank by ticket on a hub that mirrors the runs.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from hypothex.core.context import Context
from hypothex.core.errors import HypothexError, RunError
from hypothex.core.execution import (
    QUEUE_FILE,
    SUPERVISOR_PID_FILE,
    _update_terminal_run,
    spawn_supervisor,
    write_queue_marker,
)
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.gpus import free_gpus, gpu_status, query_gpus
from hypothex.core.records import ACTIVE_STATUSES, RunRecord, RunStatus, end_unstarted
from hypothex.core.store import dir_lock

SCHEDULER_INTERVAL_SECONDS = 5.0
log = logging.getLogger(__name__)


@contextmanager
def scheduler_lock(ctx: Context) -> Iterator[None]:
    """
    Hold the host-wide lock for GPU assignment and queue changes.

    Not re-entrant: never nest it.

    Parameters
    ----------
    ctx : Context
    """
    with dir_lock(ctx.layout.home / "scheduler"):
        yield


def assign_gpus(indices: list[int]) -> Callable[[RunRecord], RunRecord]:
    """
    Build an ``update_run`` mutator that records a run's GPUs.

    Parameters
    ----------
    indices : list of int
        GPU indices the run may use (its ``CUDA_VISIBLE_DEVICES``).

    Returns
    -------
    callable
        Sets ``executor.gpus`` and clears ``executor.queue_position``.
    """

    def mutate(r: RunRecord) -> RunRecord:
        executor = r.executor.model_copy(update={"gpus": list(indices), "queue_position": None})
        return r.model_copy(update={"executor": executor})

    return mutate


def _release_gpus(r: RunRecord) -> RunRecord:
    """Drop a reservation that a crashed start left behind (the run keeps its queue place)."""
    return r.model_copy(update={"executor": r.executor.model_copy(update={"gpus": []})})


def _set_ticket(ticket: int) -> Callable[[RunRecord], RunRecord]:
    """Build an ``update_run`` mutator that sets ``executor.queue_position`` (the ticket)."""

    def mutate(r: RunRecord) -> RunRecord:
        executor = r.executor.model_copy(update={"queue_position": ticket})
        return r.model_copy(update={"executor": executor})

    return mutate


@dataclass(frozen=True)
class _Entry:
    run_id: str
    enqueued_at: datetime
    gpus: int
    ticket: int | None


def _enqueued_at(marker: Path, record: RunRecord) -> datetime:
    """Read when a run joined the queue; fall back to its creation time."""
    try:
        return datetime.fromisoformat(json.loads(marker.read_text("utf-8"))["enqueued_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return record.created_at


class Scheduler:
    """
    The GPU queue of this environment (SSH hosts).

    Parameters
    ----------
    ctx : Context
    """

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._swept = False

    def _entries(self) -> list[_Entry]:
        """Waiting runs of this environment, in queue order."""
        mine = self.ctx.descriptor.environment_id
        entries: list[_Entry] = []
        for record in self.ctx.index.list_runs(
            status=RunStatus.QUEUED, include_archived=True, limit=None
        ):
            marker = self.ctx.run_dir(record) / QUEUE_FILE
            if record.environment_id != mine or not marker.is_file():
                continue
            entries.append(
                _Entry(
                    record.run_id,
                    _enqueued_at(marker, record),
                    record.gpus_requested,
                    record.executor.queue_position,
                )
            )
        return sorted(entries, key=lambda e: (e.enqueued_at, e.run_id))

    def positions(self) -> dict[str, int]:
        """
        Return each waiting run's 1-based queue position.

        Returns
        -------
        dict of str to int
            Run id to position, first in line = 1.
        """
        return {e.run_id: i for i, e in enumerate(self._entries(), start=1)}

    def _renumber(self) -> None:
        """
        Give the waiting runs tickets 1..n in queue order (call with the lock held).

        Only crash recovery needs it: a start that never committed cleared its
        run's ticket, and the run keeps its old place in the queue. Runs whose
        ticket is already right are not written.
        """
        for ticket, entry in enumerate(self._entries(), start=1):
            if entry.ticket != ticket:
                self.ctx.update_run(
                    entry.run_id, "run.queue_moved", _set_ticket(ticket), {"position": ticket}
                )

    def _recover_starts(self) -> None:
        """
        Finish or undo starts that a crash cut short (call with the lock held).

        A start is: record the GPUs, spawn the supervisor (``supervisor.pid``
        commits it), delete ``queue.json``, all under the lock. So at the
        start of a tick, an active run with ``queue.json`` and ``supervisor.pid``
        was started (its marker is deleted; it is never spawned again), and a
        waiting run with GPUs but no ``supervisor.pid`` was never started (its
        GPUs are released and it keeps its place in the queue).

        Every tick checks only the runs the index lists as active (one stat
        each). The first tick of a scheduler also sweeps the whole store, so a
        run that ended while it waited (killed, failed, or a crash between its
        end and the marker's removal) never keeps a stale ``queue.json``.
        """
        mine = self.ctx.descriptor.environment_id
        if self._swept:
            markers = [
                self.ctx.run_dir(r) / QUEUE_FILE
                for status in ACTIVE_STATUSES
                for r in self.ctx.index.list_runs(status=status, include_archived=True, limit=None)
                if r.environment_id == mine
            ]
        else:
            markers = list(self.ctx.layout.store.glob(f"*/runs/*/{QUEUE_FILE}"))
            self._swept = True
        released = False
        for marker in sorted(markers):
            if not marker.is_file():
                continue
            run_dir = marker.parent
            try:
                record = self.ctx.store.read_record(run_dir.parent.parent.name, run_dir.name)
            except HypothexError:
                continue
            if record.environment_id != mine:
                continue
            started = (run_dir / SUPERVISOR_PID_FILE).is_file()
            if started or record.status != RunStatus.QUEUED:
                # started (never spawned again), or ended while it waited
                marker.unlink(missing_ok=True)
            elif record.executor.gpus:
                self.ctx.update_run(record.run_id, "run.gpus_released", _release_gpus, {"gpus": []})
                released = True
        if released:
            self._renumber()  # the start that was cut short cleared the run's ticket

    def _keep_fifo(self, record: RunRecord, run_dir: Path) -> None:
        """
        Put a run that joins the queue behind every run already waiting.

        ``enqueued_at`` comes from this host's clock. When the clock stepped back
        (NTP, a VM resume), a new run would sort ahead of older ones; it is moved
        to just after the latest waiting run instead. Call with the lock held.
        """
        marker = run_dir / QUEUE_FILE
        mine = _enqueued_at(marker, record)
        others = [e.enqueued_at for e in self._entries() if e.run_id != record.run_id]
        latest = max(others, default=None)
        if latest is not None and mine <= latest:
            later = latest + timedelta(microseconds=1)
            atomic_write_text(marker, json.dumps({"enqueued_at": later.isoformat()}))

    def enqueue(self, run_id: str) -> int:
        """
        Put a queued run of this environment in the GPU queue.

        Parameters
        ----------
        run_id : str

        Returns
        -------
        int
            The run's 1-based queue position.

        Notes
        -----
        A run that joins gets its ticket (``executor.queue_position``, event
        ``run.enqueued {position}``) here, once; a run already waiting is left
        as it is.

        Raises
        ------
        RunError
            If the run is not queued, belongs to another environment, already
            has a supervisor, or asks for more GPUs than this host has.
        """
        with scheduler_lock(self.ctx):
            record = self.ctx.find_record(run_id)
            if record.status != RunStatus.QUEUED:
                raise RunError(
                    f"run {run_id} is {record.status.value}; only queued runs can wait for GPUs"
                )
            if record.environment_id != self.ctx.descriptor.environment_id:
                raise RunError(f"run {run_id} belongs to another environment")
            run_dir = self.ctx.run_dir(record)
            if (run_dir / SUPERVISOR_PID_FILE).is_file():
                raise RunError(f"run {run_id} was already started")
            total = len(query_gpus())
            if record.gpus_requested > total:
                raise RunError(
                    f"run {run_id} asks for {record.gpus_requested} GPUs; this host has {total}"
                )
            if not (run_dir / QUEUE_FILE).is_file():
                write_queue_marker(run_dir)
            if record.executor.queue_position is not None:  # already waiting
                return self.positions()[run_id]
            self._keep_fifo(record, run_dir)
            entries = self._entries()
            ticket = max((e.ticket or 0 for e in entries if e.run_id != run_id), default=0) + 1
            position = next(i for i, e in enumerate(entries, start=1) if e.run_id == run_id)
            self.ctx.update_run(run_id, "run.enqueued", _set_ticket(ticket), {"position": position})
            return position

    def tick(self) -> list[str]:
        """
        Start every waiting run whose GPUs fit, in queue order (first fit).

        A run that does not fit stays in line; later, smaller runs may start
        before it.

        Returns
        -------
        list of str
            Ids of the runs started, in queue order.
        """
        started: list[str] = []
        with scheduler_lock(self.ctx):
            self._recover_starts()
            entries = self._entries()
            if not entries:
                return started
            free = free_gpus(gpu_status(self.ctx))
            for entry in entries:
                if entry.gpus > len(free):
                    continue
                record = self.ctx.find_record(entry.run_id)
                marker = self.ctx.run_dir(record) / QUEUE_FILE
                if record.status != RunStatus.QUEUED:
                    marker.unlink(missing_ok=True)
                    continue
                chosen, free = free[: entry.gpus], free[entry.gpus :]
                record = self.ctx.update_run(
                    entry.run_id, "run.gpus_assigned", assign_gpus(chosen), {"gpus": chosen}
                )
                try:
                    spawn_supervisor(self.ctx, record)
                except OSError as exc:
                    if (self.ctx.run_dir(record) / SUPERVISOR_PID_FILE).is_file():
                        # committed: the supervisor owns the run, only the event failed
                        log.error(
                            "run %s started, but its launch was not recorded: %s", entry.run_id, exc
                        )
                        marker.unlink(missing_ok=True)
                        started.append(entry.run_id)
                        continue
                    # never committed: nothing runs, so the GPUs go back
                    marker.unlink(missing_ok=True)
                    _update_terminal_run(
                        self.ctx,
                        entry.run_id,
                        "run.failed",
                        end_unstarted(
                            RunStatus.FAILED, reason=f"could not start the supervisor: {exc}"
                        ),
                        {"reason": f"could not start the supervisor: {exc}"},
                    )
                    continue
                marker.unlink(missing_ok=True)
                started.append(entry.run_id)
        return started


def run_scheduler_loop(
    ctx: Context, stop: threading.Event, interval: float = SCHEDULER_INTERVAL_SECONDS
) -> None:
    """
    Tick the scheduler every ``interval`` seconds until ``stop`` is set.

    Used by ``hx serve --kind ssh`` in a background thread. A failing tick is
    logged and the loop goes on.

    Parameters
    ----------
    ctx : Context
    stop : threading.Event
        Set it to end the loop.
    interval : float
        Seconds between ticks.
    """
    scheduler = Scheduler(ctx)
    while not stop.is_set():
        try:
            scheduler.tick()
        except Exception:  # noqa: BLE001 - one bad tick must not stop the queue
            log.exception("scheduler tick failed")
        stop.wait(interval)
