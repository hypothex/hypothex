"""The file store: projects and run folders are the source of truth."""

from __future__ import annotations

import fcntl
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, Field, ValidationError

from hypothex.core.config import ProjectConfig
from hypothex.core.errors import RunNotFoundError, StoreError
from hypothex.core.fsutil import (
    append_jsonl,
    append_note_file,
    atomic_write_text,
    read_jsonl,
    read_yaml,
    write_yaml,
)
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.records import Artifact, MetricPoint, RunRecord, ScoreRecord

log = logging.getLogger(__name__)
_M = TypeVar("_M", bound=BaseModel)

RUN_SUBDIRS = ("logs", "predictions", "env")


class ProjectEntry(BaseModel):
    """
    A registered project: its repo path and a snapshot of its config.

    ``previous_repos`` lists earlier repo paths (most recent first), so runs
    recorded before the repo moved can be mapped onto the new location.
    """

    project: str
    repo: str
    config: ProjectConfig
    registered_at: datetime
    previous_repos: list[str] = Field(default_factory=list)


@contextmanager
def dir_lock(directory: Path) -> Iterator[None]:
    """
    Hold an exclusive, cross-process lock on one folder.

    Parameters
    ----------
    directory : Path
        The folder to lock; ``.lock`` is created inside it.
    """
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextmanager
def run_lock(run_dir: Path) -> Iterator[None]:
    """
    Hold an exclusive, cross-process lock on one run folder.

    Parameters
    ----------
    run_dir : Path
        The run folder; ``.lock`` is created inside it.
    """
    with dir_lock(run_dir):
        yield


class RunStore:
    """
    Read and write projects and runs under ``<home>/store``.

    Parameters
    ----------
    layout : Layout
        Home directory layout.
    """

    def __init__(self, layout: Layout) -> None:
        self.layout = layout

    # projects -----------------------------------------------------------
    def _project_file(self, project: str) -> Path:
        return self.layout.project_dir(project) / "project.json"

    def register_project(self, config: ProjectConfig, repo: Path) -> ProjectEntry:
        """
        Record (or refresh) a project's repo path and config snapshot.

        Parameters
        ----------
        config : ProjectConfig
            Parsed ``hypothex.yaml`` to snapshot.
        repo : Path
            Repository root the project lives in.

        Returns
        -------
        ProjectEntry
            The stored entry. The latest registration wins; when the repo
            path changed, the old path is kept in ``previous_repos``.
        """
        repo_path = str(repo.resolve())
        previous: list[str] = []
        try:
            old = self.load_project(config.project)
        except StoreError:  # new project, or an unreadable file being replaced
            old = None
        if old is not None:
            history = (
                [old.repo, *old.previous_repos] if old.repo != repo_path else old.previous_repos
            )
            previous = [p for p in dict.fromkeys(history) if p != repo_path]
        entry = ProjectEntry(
            project=config.project,
            repo=repo_path,
            config=config,
            registered_at=utcnow(),
            previous_repos=previous,
        )
        atomic_write_text(self._project_file(config.project), entry.model_dump_json(indent=2))
        return entry

    def load_project(self, project: str) -> ProjectEntry:
        """
        Load a registered project.

        Parameters
        ----------
        project : str
            Project name.

        Returns
        -------
        ProjectEntry
            The stored entry.

        Raises
        ------
        StoreError
            If no such project is registered, or its file cannot be parsed.
        """
        path = self._project_file(project)
        if not path.is_file():
            raise StoreError(f"unknown project {project!r}")
        try:
            return ProjectEntry.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:  # includes pydantic ValidationError and bad UTF-8
            raise StoreError(f"unreadable project file {path}: {_brief(exc)}") from exc

    def list_projects(self) -> list[ProjectEntry]:
        """
        Return all registered projects, sorted by name.

        Returns
        -------
        list of ProjectEntry
            Every registered project whose ``project.json`` parses.
        """
        if not self.layout.store.is_dir():
            return []
        entries = []
        for path in sorted(self.layout.store.glob("*/project.json")):
            try:
                entries.append(ProjectEntry.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError:  # includes pydantic ValidationError and bad UTF-8
                log.warning("skipping unreadable project file %s", path)
        return entries

    # runs ---------------------------------------------------------------
    def create_run(self, record: RunRecord) -> Path:
        """
        Create a new run folder and its ``run.yaml``.

        Parameters
        ----------
        record : RunRecord
            The run to create.

        Returns
        -------
        Path
            The created run folder.

        Raises
        ------
        StoreError
            If the run folder already exists.
        """
        run_dir = self.layout.run_dir(record.project, record.run_id)
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise StoreError(f"run folder already exists: {run_dir}") from exc
        for sub in RUN_SUBDIRS:
            (run_dir / sub).mkdir()
        self.write_record(record)
        return run_dir

    def write_record(self, record: RunRecord) -> None:
        """
        Atomically write ``run.yaml``.

        Parameters
        ----------
        record : RunRecord
            The run record to persist. Callers must hold ``run_lock``.
        """
        path = self.layout.run_dir(record.project, record.run_id) / "run.yaml"
        write_yaml(path, record.model_dump(mode="json"))

    def read_record(self, project: str, run_id: str) -> RunRecord:
        """
        Read one run's ``run.yaml``.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        RunRecord
            The parsed run record.

        Raises
        ------
        RunNotFoundError
            If no such run exists.
        StoreError
            If ``run.yaml`` cannot be parsed.
        """
        path = self.layout.run_dir(project, run_id) / "run.yaml"
        if not path.is_file():
            raise RunNotFoundError(f"no run {run_id!r} in project {project!r}")
        try:
            return RunRecord.model_validate(read_yaml(path))
        except (ValueError, yaml.YAMLError) as exc:
            raise StoreError(f"unreadable run file {path}: {_brief(exc)}") from exc

    def iter_records(self, project: str | None = None) -> Iterator[RunRecord]:
        """
        Yield every readable run record.

        Parameters
        ----------
        project : str, optional
            Restrict to one project; ``None`` iterates all projects.

        Yields
        ------
        RunRecord
            Each run record whose ``run.yaml`` parses; unreadable folders are
            logged and skipped.
        """
        if project is not None:
            projects = [project]
        elif self.layout.store.is_dir():
            projects = sorted(p.name for p in self.layout.store.iterdir() if p.is_dir())
        else:
            projects = []
        for name in projects:
            runs_dir = self.layout.runs_dir(name)
            if not runs_dir.is_dir():
                continue
            for run_dir in sorted(runs_dir.iterdir()):
                path = run_dir / "run.yaml"
                if not path.is_file():
                    continue
                try:
                    yield RunRecord.model_validate(read_yaml(path))
                except Exception:  # noqa: BLE001 - a corrupt file must not stop listing
                    log.warning("skipping unreadable run file %s", path)

    def list_run_ids(self) -> dict[str, str]:
        """
        Map every run id that has a ``run.yaml`` to its project.

        Returns
        -------
        dict of str to str
            Run id to project name.
        """
        found: dict[str, str] = {}
        for path in self.layout.store.glob("*/runs/*/run.yaml"):
            found[path.parent.name] = path.parent.parent.parent.name
        return found

    def find_project_of(self, run_id: str) -> str:
        """
        Find which project owns a run id.

        Parameters
        ----------
        run_id : str
            Run id to look up.

        Returns
        -------
        str
            The owning project's name.

        Raises
        ------
        RunNotFoundError
            If no run with that id exists.
        """
        for path in self.layout.store.glob(f"*/runs/{run_id}/run.yaml"):
            return path.parent.parent.parent.name
        raise RunNotFoundError(f"no run {run_id!r}")

    # run contents ---------------------------------------------------------
    def append_score(self, project: str, run_id: str, score: ScoreRecord) -> None:
        """
        Append one score to ``scores.jsonl``.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.
        score : ScoreRecord
            Score to append. Old scores are never overwritten or deleted.
        """
        append_jsonl(
            self.layout.run_dir(project, run_id) / "scores.jsonl",
            score.model_dump(mode="json"),
        )

    def read_scores(self, project: str, run_id: str) -> list[ScoreRecord]:
        """
        Read all scores for a run, oldest first.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        list of ScoreRecord
            Scores in the order written; malformed rows are skipped.
        """
        return _parse_rows(ScoreRecord, self.layout.run_dir(project, run_id) / "scores.jsonl")

    def read_metric_points(self, project: str, run_id: str) -> list[MetricPoint]:
        """
        Read the logged metric history for a run.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        list of MetricPoint
            Points in the order written; malformed rows are skipped.
        """
        return _parse_rows(MetricPoint, self.layout.run_dir(project, run_id) / "metrics.jsonl")

    def read_artifacts(self, project: str, run_id: str) -> list[Artifact]:
        """
        Read artifacts logged by the SDK for a run.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        list of Artifact
            Artifacts in the order written; malformed rows are skipped.
        """
        return _parse_rows(Artifact, self.layout.run_dir(project, run_id) / "artifacts.jsonl")

    def append_note(self, project: str, run_id: str, text: str, author: str) -> None:
        """
        Append a note to the run's ``notes.md``.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.
        text : str
            Note body (Markdown).
        author : str
            Who wrote it, e.g. ``human`` or ``agent:claude``.
        """
        append_note_file(self.layout.run_dir(project, run_id) / "notes.md", text, author)

    def read_notes(self, project: str, run_id: str) -> str:
        """
        Return the run's notes.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        str
            The full contents of ``notes.md``, or an empty string.
        """
        path = self.layout.run_dir(project, run_id) / "notes.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    # metric source hashes ----------------------------------------------------
    @contextmanager
    def project_lock(self, project: str) -> Iterator[None]:
        """
        Hold an exclusive, cross-process lock on a project's folder.

        Hold it around read-modify-write updates of project files such as
        ``metric_hashes.json``.

        Parameters
        ----------
        project : str
            Project name.
        """
        with dir_lock(self.layout.project_dir(project)):
            yield

    def metric_hashes(self, project: str) -> dict[str, str]:
        """
        Return first-seen source hashes for a project's metrics.

        Parameters
        ----------
        project : str
            Project name.

        Returns
        -------
        dict of str to str
            Source hash keyed by ``name@version``; ``{}`` if none recorded.
        """
        path = self.layout.project_dir(project) / "metric_hashes.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def save_metric_hashes(self, project: str, hashes: dict[str, str]) -> None:
        """
        Persist metric source hashes for a project.

        Parameters
        ----------
        project : str
            Project name.
        hashes : dict of str to str
            Source hash keyed by ``name@version``.
        """
        atomic_write_text(
            self.layout.project_dir(project) / "metric_hashes.json",
            json.dumps(hashes, indent=2, sort_keys=True),
        )


def _brief(exc: Exception) -> str:
    """
    Summarize a parse error in one short line.

    Parameters
    ----------
    exc : Exception
        The parse or validation error.

    Returns
    -------
    str
        The first line of the message, at most 200 characters.
    """
    lines = str(exc).strip().splitlines()
    return (lines[0] if lines else type(exc).__name__)[:200]


def _parse_rows(model: type[_M], path: Path) -> list[_M]:
    """
    Parse each JSONL row of ``path`` into ``model``, skipping invalid rows.

    Parameters
    ----------
    model : type
        Pydantic model to validate each row against.
    path : Path
        JSONL file to read.

    Returns
    -------
    list
        Successfully parsed rows, in file order.
    """
    rows: list[_M] = []
    for raw in read_jsonl(path):
        try:
            rows.append(model.model_validate(raw))
        except ValidationError:
            continue
    return rows
