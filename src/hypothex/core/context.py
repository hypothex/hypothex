"""Everything a Hypothex operation needs, plus the single write path for runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hypothex.core.config import load_project_config
from hypothex.core.environment import EnvironmentDescriptor, load_descriptor
from hypothex.core.events import EventLog
from hypothex.core.index import (
    Index,
    rebuild_index_if_stale,
    repair_index_if_changed,
    repair_stale_scores,
)
from hypothex.core.layout import Layout, default_home
from hypothex.core.records import RunRecord, ScoreRecord
from hypothex.core.store import ProjectEntry, RunStore, run_lock


@dataclass
class Context:
    """
    Open handles to the store, index, event log, and environment identity.

    Use ``Context.open()``; all run state changes go through ``create_run``,
    ``update_run``, and ``add_score`` so files, events, and index stay in step.
    """

    layout: Layout
    store: RunStore
    index: Index
    events: EventLog
    descriptor: EnvironmentDescriptor

    @classmethod
    def open(cls, home: Path | None = None) -> Context:
        """
        Open (and if needed create) a Hypothex home.

        A run folder with no index row (a crash between the file write and the
        index write) is indexed here. The store is listed only when a run or
        project folder changed since the last listing
        (``index.repair_index_if_changed``); a new index, or one with an old
        schema, is rebuilt from files (``index.rebuild_index_if_stale``): other
        processes read the old index until the rebuilt one replaces it. A
        score whose add was cut short after its file append is indexed here
        too (``index.repair_stale_scores``).

        Parameters
        ----------
        home : Path, optional
            Home directory; defaults to ``default_home()``.

        Returns
        -------
        Context
        """
        layout = Layout((home or default_home()).expanduser().resolve())
        layout.ensure()
        store = RunStore(layout)
        index = Index(layout.index_db, store=store)
        ctx = cls(
            layout=layout,
            store=store,
            index=index,
            events=EventLog(layout.events_db),
            descriptor=load_descriptor(layout),
        )
        if index.rebuilt_schema:
            rebuild_index_if_stale(index, store)  # atomic; a concurrent open waits for it
        else:
            repair_index_if_changed(index, store)
        repair_stale_scores(index, store)
        return ctx

    def find_record(self, run_id: str) -> RunRecord:
        """
        Read a run's current record from its file.

        Parameters
        ----------
        run_id : str
            Run id to look up.

        Returns
        -------
        RunRecord
            The run's current record.

        Raises
        ------
        RunNotFoundError
            If the run does not exist.
        """
        indexed = self.index.get_run(run_id)
        project = indexed.project if indexed else self.store.find_project_of(run_id)
        return self.store.read_record(project, run_id)

    def run_dir(self, record: RunRecord) -> Path:
        """
        Return the run's folder.

        Parameters
        ----------
        record : RunRecord
            Run to locate.

        Returns
        -------
        Path
        """
        return self.layout.run_dir(record.project, record.run_id)

    def register_project(self, repo: Path) -> ProjectEntry:
        """
        Load ``hypothex.yaml`` from ``repo`` and (re)register the project.

        Parameters
        ----------
        repo : Path
            Repository root directory.

        Returns
        -------
        ProjectEntry
            The stored entry.
        """
        entry = self.store.register_project(load_project_config(repo), repo)
        self.index.upsert_project(entry)
        return entry

    def create_run(self, record: RunRecord) -> RunRecord:
        """
        Create the run folder, then emit ``run.created``, then index it.

        Parameters
        ----------
        record : RunRecord
            The run to create.

        Returns
        -------
        RunRecord
            The created record.
        """
        self.store.create_run(record)
        self.events.append(
            "run.created",
            project=record.project,
            run_id=record.run_id,
            payload={"status": record.status.value},
        )
        self.index.upsert_run(record)
        return record

    def update_run(
        self,
        run_id: str,
        event_type: str,
        mutate: Callable[[RunRecord], RunRecord],
        payload: dict[str, Any] | None = None,
    ) -> RunRecord:
        """
        Apply ``mutate`` to the on-disk record under the run lock.

        The fresh record is re-read inside the lock, so concurrent writers (for
        example tagging while the run finishes) never lose each other's changes.

        Parameters
        ----------
        run_id : str
            Run id to update.
        event_type : str
            Event type to emit, e.g. ``run.started``.
        mutate : callable
            Takes the current record and returns the updated one.
        payload : dict, optional
            Extra fields merged into the emitted event's payload.

        Returns
        -------
        RunRecord
            The written record.
        """
        project = self.find_record(run_id).project
        with run_lock(self.layout.run_dir(project, run_id)):
            updated = mutate(self.store.read_record(project, run_id))
            self.store.write_record(updated)
            self.events.append(
                event_type,
                project=project,
                run_id=run_id,
                payload={"status": updated.status.value, **(payload or {})},
            )
            self.index.upsert_run(updated)
        return updated

    def add_score(self, record: RunRecord, score: ScoreRecord) -> None:
        """
        Append a score to the file, emit ``run.score_added``, and index it.

        The run is marked first (``Index.mark_scores_stale``) and its scores
        are then re-indexed from the file, which clears the mark: a crash
        after the append is repaired by the next ``Context.open``, and an add
        that races an index rebuild is never indexed twice.

        Parameters
        ----------
        record : RunRecord
            Run the score belongs to.
        score : ScoreRecord
            Score to append.
        """
        with run_lock(self.run_dir(record)):
            self.index.mark_scores_stale(record.run_id)
            self.store.append_score(record.project, record.run_id, score)
            self.events.append(
                "run.score_added",
                project=record.project,
                run_id=record.run_id,
                payload=score.model_dump(mode="json"),
            )
            scores = self.store.read_scores(record.project, record.run_id)
            self.index.replace_scores(record.run_id, scores)

    def emit(
        self, event_type: str, record: RunRecord, payload: dict[str, Any] | None = None
    ) -> None:
        """
        Emit an informational event about a run (no state change).

        Parameters
        ----------
        event_type : str
            Event type.
        record : RunRecord
            Run the event belongs to.
        payload : dict, optional
            Event body.
        """
        self.events.append(
            event_type, project=record.project, run_id=record.run_id, payload=payload or {}
        )
