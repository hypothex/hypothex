"""The file store: projects and run folders are the source of truth."""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import math
import re
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, Field, ValidationError

from hypothex.core.config import ProjectConfig
from hypothex.core.errors import RunNotFoundError, StoreError
from hypothex.core.fsutil import (
    append_jsonl,
    append_note_file,
    atomic_write_text,
    iter_jsonl,
    read_jsonl,
    read_yaml,
    write_yaml,
)
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.records import (
    Artifact,
    MetricPoint,
    NonFiniteMetric,
    RunRecord,
    ScoreRecord,
    UsageTotals,
)
from hypothex.core.thin import MAX_POINTS_PER_METRIC, HistoryThinner

log = logging.getLogger(__name__)
_M = TypeVar("_M", bound=BaseModel)

RUN_SUBDIRS = ("logs", "predictions", "env")
MAX_METRIC_LINE_BYTES = 64 * 1024
"""Longest ``metrics.jsonl`` line a bounded read parses; a longer line is skipped unread."""
MAX_NAME_WARNINGS = 1024
"""Most recent runs whose metric-name warning each store remembers."""
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]")
_HASH_TAIL = re.compile(r"-[0-9a-f]{8}\Z")
MAX_STEM = 255 - len(".jsonl")
"""Longest stem: ``<stem>.jsonl`` fits the 255-byte name limit of common file systems."""


def safe_stem(name: str) -> str:
    """
    Turn an example id or sample name into a file name stem.

    Every character outside ``[A-Za-z0-9_.-]`` becomes ``_``, so the name can never
    contain a path separator and leave its folder. ``-`` and the first 8 hex digits
    of ``sha1(name)`` are appended when that changes the name, when the name is
    longer than ``MAX_STEM`` (the sanitised part is then cut so the whole stem is
    ``MAX_STEM`` long), and also when the name already ends in ``-`` plus 8
    lowercase hex digits (so ``a_b-3ec69c85`` cannot take the stem of ``a/b``).
    Any other name is returned unchanged. So an unchanged stem never ends in a hash
    and a hashed one always does: two distinct names share a stem only if they
    sanitise alike and their sha1 digests share the first 8 hex digits, which
    ``check_stem_owner`` catches before a write. Every stem that fit the name limit
    before the cut was added is unchanged, so existing files keep their names.

    Parameters
    ----------
    name : str
        Example id or sample name.

    Returns
    -------
    str
        The file name stem.

    Raises
    ------
    ValueError
        If ``name`` is empty.

    Examples
    --------
    >>> safe_stem("route 7/b")
    'route_7_b-5db86396'
    >>> safe_stem("a_b")
    'a_b'
    >>> safe_stem("a_b-3ec69c85")
    'a_b-3ec69c85-d64fa8bc'
    """
    if not name:
        raise ValueError("name must not be empty")
    stem = _UNSAFE_CHARS.sub("_", name)
    if stem == name and len(stem) <= MAX_STEM and not _HASH_TAIL.search(name):
        return stem
    # surrogatepass: a str from undecodable bytes or JSON may hold lone surrogates
    digest = hashlib.sha1(name.encode("utf-8", "surrogatepass")).hexdigest()
    return f"{stem[: MAX_STEM - 9]}-{digest[:8]}"


def check_stem_owner(path: Path, key: str, original: str) -> None:
    """
    Refuse to write a trace or sample file that belongs to a different id or name.

    ``safe_stem`` gives two distinct names one stem only on an 8-hex-digit sha1
    prefix collision. Every row of a trace or sample file stores the original id
    (``example_id``) or name (``name``), so writers call this before they write:
    an existing file whose first line stores a different original is a collision.

    Parameters
    ----------
    path : Path
        The trace or sample file about to be written.
    key : str
        Row key of the original: ``example_id`` for traces, ``name`` for samples.
    original : str
        The id or name about to be written.

    Raises
    ------
    StoreError
        If the file exists and its first line stores a different string under
        ``key``. A missing or empty file, or a first line without that key (a file
        written by hand), passes.

    Examples
    --------
    >>> check_stem_owner(Path("/nonexistent/a_b.jsonl"), "example_id", "a_b")
    """
    if not path.is_file():
        return
    with path.open("rb") as fh:
        first = fh.readline()
    try:
        row = json.loads(first)
    except ValueError:
        return
    stored = row.get(key) if isinstance(row, dict) else None
    if isinstance(stored, str) and stored != original:
        raise StoreError(
            f"id collision: {path.name} already holds {key} {stored!r}, not {original!r}"
        )


class UsageRow(BaseModel):
    """
    One ``log_usage`` call; a line of ``usage.jsonl``.

    Examples
    --------
    >>> UsageRow(tokens_in=100, usd=0.25).tokens_out
    0
    """

    example_id: str | None = None
    tokens_in: int = Field(0, ge=0)
    tokens_out: int = Field(0, ge=0)
    # allow_inf_nan=False: ge=0 alone lets +inf through, and an inf in the run
    # totals would break JSON responses later
    usd: float = Field(0.0, ge=0, allow_inf_nan=False)
    seconds: float = Field(0.0, ge=0, allow_inf_nan=False)


class TraceStep(BaseModel):
    """
    One step of an agent trajectory; a line of ``traces/<example_id>.jsonl``.

    Unknown keys are dropped. A non-empty ``error`` marks the step as failed.
    ``seconds`` must be finite.

    Examples
    --------
    >>> TraceStep(turn=1, tool="check_stock", error="timeout").error
    'timeout'
    """

    turn: int
    tool: str | None = None
    args: Any = None
    result: Any = None
    tokens_in: int = Field(0, ge=0)
    tokens_out: int = Field(0, ge=0)
    seconds: float = Field(0.0, ge=0, allow_inf_nan=False)
    error: str | None = None


def sum_usage(rows: Iterable[UsageRow]) -> UsageTotals | None:
    """
    Add up usage rows into run totals.

    Parameters
    ----------
    rows : iterable of UsageRow
        Rows from ``RunStore.read_usage``.

    Returns
    -------
    UsageTotals or None
        Sums of every field and ``calls`` = number of rows; None if there are no rows.

    Examples
    --------
    >>> sum_usage([UsageRow(tokens_in=3, usd=0.25), UsageRow(tokens_in=4, usd=0.5)])
    UsageTotals(tokens_in=7, tokens_out=0, usd=0.75, seconds=0.0, calls=2)
    >>> sum_usage([]) is None
    True
    """
    items = list(rows)
    if not items:
        return None
    return UsageTotals(
        tokens_in=sum(r.tokens_in for r in items),
        tokens_out=sum(r.tokens_out for r in items),
        usd=math.fsum(r.usd for r in items),
        seconds=math.fsum(r.seconds for r in items),
        calls=len(items),
    )


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
    remote_host: str | None = None
    """Set when the hub copied this entry from a host (the repo path is on that host)."""


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
        self._name_cap_warned: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._name_warning_lock = Lock()

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

    def save_project(self, entry: ProjectEntry) -> None:
        """
        Atomically write a project entry as it is (the hub's copy of a host's project).

        Parameters
        ----------
        entry : ProjectEntry
            Entry to store.
        """
        atomic_write_text(self._project_file(entry.project), entry.model_dump_json(indent=2))

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
        Read the logged metric history for a run, every point.

        Memory grows with the file: use it where every point matters (an
        ended run's history before the index downsamples it) and
        ``read_metric_points_bounded`` for a live run.

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

    def read_metric_points_bounded(
        self, project: str, run_id: str, limit: int = MAX_POINTS_PER_METRIC
    ) -> list[MetricPoint]:
        """
        Read a bounded copy of a run's metric history, one line at a time.

        For a live run, whose file may still grow without limit: memory stays
        bounded by ``2 * limit`` points per name and ``thin.MAX_METRIC_NAMES``
        names (the first distinct names in the file; rows of others are skipped, with one
        warning per run remembered for ``MAX_NAME_WARNINGS`` recent runs per
        store) whatever the file size (``thin.HistoryThinner``), and
        lines over ``MAX_METRIC_LINE_BYTES`` or not UTF-8 are skipped unread.
        A history of at most ``limit`` points per name is read whole, as
        ``read_metric_points`` reads it.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.
        limit : int
            Most points kept per name, at least 5.

        Returns
        -------
        list of MetricPoint
            At most ``limit`` points per name, ordered by name then step: the
            first and last step and the lowest and highest value of each name,
            the rest picked by LTTB. Malformed rows are skipped.

        Examples
        --------
        >>> store.read_metric_points_bounded("toy", "r1")  # doctest: +SKIP
        [MetricPoint(name='loss', step=0, value=2.3, t=None)]
        """
        path = self.layout.run_dir(project, run_id) / "metrics.jsonl"
        thinner = HistoryThinner(limit)
        for point in _iter_rows(MetricPoint, path, MAX_METRIC_LINE_BYTES):
            thinner.add(point)
        key = (project, run_id)
        warn = False
        if thinner.dropped_rows:
            with self._name_warning_lock:
                warn = key not in self._name_cap_warned
                self._name_cap_warned[key] = None
                self._name_cap_warned.move_to_end(key)
                if len(self._name_cap_warned) > MAX_NAME_WARNINGS:
                    self._name_cap_warned.popitem(last=False)
        if warn:
            log.warning(
                "run %s: metrics.jsonl holds more than %d metric names; %d rows of further "
                "names were skipped by a bounded read",
                run_id,
                thinner.max_names,
                thinner.dropped_rows,
            )
        return thinner.points()

    def read_nonfinite_points(self, project: str, run_id: str) -> list[NonFiniteMetric]:
        """
        Read the ``NaN`` / infinite metric values the SDK recorded for a run.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        list of NonFiniteMetric
            Rows of ``metrics_nonfinite.jsonl`` in the order written; malformed
            rows are skipped.
        """
        path = self.layout.run_dir(project, run_id) / "metrics_nonfinite.jsonl"
        return _parse_rows(NonFiniteMetric, path)

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

    def read_usage(self, project: str, run_id: str) -> list[UsageRow]:
        """
        Read the usage rows logged by the SDK for a run.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        list of UsageRow
            Rows of ``usage.jsonl`` in the order written; malformed rows (for example a
            negative token count) are skipped.
        """
        return _parse_rows(UsageRow, self.layout.run_dir(project, run_id) / "usage.jsonl")

    def list_traces(self, project: str, run_id: str) -> list[dict[str, Any]]:
        """
        Summarise every trace logged for a run.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        list of dict
            One ``{"example_id": str, "turns": int, "failed": bool}`` per trace file,
            sorted by example id. ``example_id`` is the original id written by
            ``log_trace`` (also for an empty trace, whose file holds one marker line);
            the file stem only for files written without it. ``failed`` is True when
            any step has a non-empty ``error``.
        """
        folder = self.layout.run_dir(project, run_id) / "traces"
        if not folder.is_dir():
            return []
        found: list[dict[str, Any]] = []
        for path in sorted(folder.glob("*.jsonl")):
            raw = read_jsonl(path)
            steps = _parse_steps(raw)
            original = next((r["example_id"] for r in raw if "example_id" in r), None)
            found.append(
                {
                    "example_id": original if isinstance(original, str) else path.stem,
                    "turns": len(steps),
                    "failed": any(step.error for step in steps),
                }
            )
        return sorted(found, key=lambda row: row["example_id"])

    def read_trace(self, project: str, run_id: str, example_id: str) -> list[TraceStep]:
        """
        Read one example's trace.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.
        example_id : str
            Example id as given to ``log_trace`` (sanitised here the same way).

        Returns
        -------
        list of TraceStep
            Steps in file order; ``[]`` if the example has no trace. A step without
            ``turn`` gets its 1-based position; malformed steps are skipped.

        Raises
        ------
        ValueError
            If ``example_id`` is empty.
        """
        path = self.layout.run_dir(project, run_id) / "traces" / f"{safe_stem(example_id)}.jsonl"
        return _parse_steps(read_jsonl(path))

    def read_samples(self, project: str, run_id: str) -> dict[str, list[float]]:
        """
        Read every raw sample series logged for a run.

        Parameters
        ----------
        project : str
            Project name.
        run_id : str
            Run id.

        Returns
        -------
        dict of str to list of float
            Series name to values in the order written, sorted by name. The name is
            the original one ``log_samples`` stores in each row (the file stem only
            for files written without it). Rows whose ``value`` is not a finite
            number are skipped.
        """
        folder = self.layout.run_dir(project, run_id) / "samples"
        if not folder.is_dir():
            return {}
        series: dict[str, list[float]] = {}
        for path in sorted(folder.glob("*.jsonl")):
            rows = read_jsonl(path)
            name = next((r["name"] for r in rows if isinstance(r.get("name"), str)), path.stem)
            values: list[float] = []
            for raw in rows:
                value = raw.get("value")
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                if math.isfinite(value):
                    values.append(float(value))
            series.setdefault(name, []).extend(values)
        return dict(sorted(series.items()))

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


def _iter_rows(model: type[_M], path: Path, max_line_bytes: int | None = None) -> Iterator[_M]:
    """
    Parse each JSONL row of ``path`` into ``model`` one at a time, skipping invalid rows.

    Parameters
    ----------
    model : type
        Pydantic model to validate each row against.
    path : Path
        JSONL file to read.
    max_line_bytes : int, optional
        Longest line to parse (``fsutil.iter_jsonl``); ``None`` parses every line.

    Yields
    ------
    model
        Successfully parsed rows, in file order.
    """
    for raw in iter_jsonl(path, max_line_bytes):
        try:
            yield model.model_validate(raw)
        except ValidationError:
            continue


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
    return list(_iter_rows(model, path))


def _parse_steps(raws: list[dict[str, Any]]) -> list[TraceStep]:
    """
    Parse trace rows, giving a row without ``turn`` its 1-based position.

    Parameters
    ----------
    raws : list of dict
        Rows read from a trace file.

    Returns
    -------
    list of TraceStep
        Valid steps in file order; invalid rows and the empty-trace marker line
        (``{"example_id": ...}`` alone) are skipped.
    """
    steps: list[TraceStep] = []
    for position, raw in enumerate(raws, start=1):
        if raw.keys() == {"example_id"}:
            continue
        try:
            steps.append(TraceStep.model_validate({"turn": position, **raw}))
        except ValidationError:
            continue
    return steps
