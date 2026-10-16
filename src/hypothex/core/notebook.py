"""Lab notebook: one Markdown file per project and day, with ``[[run:<id>]]`` chips.

Files live in ``<store>/<project>/notebook/YYYY-MM-DD.md`` on the hub. They are
files of record (``hx reindex`` never touches them) and are never mirrored to
hosts. Entries are ``## <iso time> — <author>`` sections, the format of run
``notes.md``.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from hypothex.core.config import parse_metric_key
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, HypothexError, StoreError
from hypothex.core.fsutil import atomic_write_bytes
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.leaderboard import group_label
from hypothex.core.records import RunRecord, RunStatus
from hypothex.core.settings import load_settings

NOTEBOOK_DIR = "notebook"
DAY_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
RUN_LINK = re.compile(r"\[\[run:([A-Za-z0-9][A-Za-z0-9_.-]{0,79})\]\]")
NOTEBOOK_MAX_BYTES = 1024 * 1024
ENTRY_STAMP = re.compile(r"^## (\S+) — (.+)$", re.MULTILINE)


class RunChip(BaseModel):
    """A ``[[run:<id>]]`` link resolved for display; ``status`` None = unknown run."""

    run_id: str
    status: RunStatus | None
    task: str | None
    label: str
    primary: float | None


class NotebookDay(BaseModel):
    """One day's notebook file; ``hash`` is ``sha256:<hex>`` of its bytes ("" when missing)."""

    project: str
    day: date
    text: str
    hash: str
    runs: list[RunChip]
    updated_at: datetime | None


class NotebookConflictError(HypothexError):
    """A whole-day save whose base hash is not the file's (someone else saved first)."""

    def __init__(self, message: str, current: NotebookDay) -> None:
        super().__init__(message)
        self.current = current


class NotebookTooLargeError(HypothexError):
    """A day file would grow past ``NOTEBOOK_MAX_BYTES``."""


def notebook_dir(layout: Layout, project: str) -> Path:
    """
    Return a project's notebook folder.

    Parameters
    ----------
    layout : Layout
    project : str

    Returns
    -------
    Path
        ``<store>/<project>/notebook``.
    """
    return layout.project_dir(project) / NOTEBOOK_DIR


def day_path(layout: Layout, project: str, day: date) -> Path:
    """
    Return the file of one notebook day.

    Parameters
    ----------
    layout : Layout
    project : str
    day : date

    Returns
    -------
    Path
        ``<store>/<project>/notebook/YYYY-MM-DD.md``.
    """
    return notebook_dir(layout, project) / f"{day.isoformat()}.md"


def parse_day(text: str) -> date:
    """
    Parse a ``YYYY-MM-DD`` day.

    Parameters
    ----------
    text : str

    Returns
    -------
    date

    Raises
    ------
    ConfigError
        Anything else (so a day can never name a path outside the folder).

    Examples
    --------
    >>> parse_day("2026-10-04")
    datetime.date(2026, 10, 4)
    """
    if not re.fullmatch(DAY_PATTERN, text):
        raise ConfigError(f"day must be YYYY-MM-DD, got {text!r}")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ConfigError(f"day must be YYYY-MM-DD, got {text!r}") from None


def today(now: datetime | None = None, tz: str | None = None) -> date:
    """
    Return the hub-local date.

    Parameters
    ----------
    now : datetime, optional
        The moment (default now).
    tz : str, optional
        IANA zone (``DigestSettings.timezone``); None uses this machine's zone.

    Returns
    -------
    date
    """
    moment = now or utcnow()
    return (moment.astimezone(ZoneInfo(tz)) if tz else moment.astimezone()).date()


def hub_today(ctx: Context, now: datetime | None = None) -> date:
    """
    Return the hub's "today" for the notebook (contract 1.4).

    The UI, ``hx note``, MCP, and the digest all use this one date, so an entry
    written near midnight lands on the same day file whoever writes it.

    Parameters
    ----------
    ctx : Context
    now : datetime, optional
        The moment (default now).

    Returns
    -------
    date
        ``today(now, DigestSettings.timezone)``; this machine's zone when the
        timezone is unset or ``config.yaml`` cannot be read.
    """
    try:
        tz = load_settings(ctx.layout).digest.timezone
    except ConfigError:
        tz = None
    return today(now, tz)


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest() if data else ""


def _require_project(ctx: Context, project: str) -> None:
    ctx.store.load_project(project)  # StoreError (404) for an unknown project


def run_links(text: str) -> list[str]:
    """
    Return the run ids linked as ``[[run:<id>]]``, unique, in order of first use.

    Parameters
    ----------
    text : str

    Returns
    -------
    list of str

    Examples
    --------
    >>> run_links("[[run:a]] [[run:b]] [[run:a]]")
    ['a', 'b']
    """
    return list(dict.fromkeys(RUN_LINK.findall(text)))


def parse_entries(text: str) -> list[tuple[datetime, str, str]]:
    """
    Split a notebook or ``notes.md`` text into its stamped entries.

    Parameters
    ----------
    text : str

    Returns
    -------
    list of (datetime, str, str)
        ``(stamp, author, body)`` in file order; sections whose stamp is not
        an ISO time with a zone are skipped.
    """
    matches = list(ENTRY_STAMP.finditer(text))
    out: list[tuple[datetime, str, str]] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        try:
            stamp = datetime.fromisoformat(match.group(1))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            continue
        out.append((stamp, match.group(2).strip(), text[match.end() : end].strip()))
    return out


def run_primary(ctx: Context, record: RunRecord) -> float | None:
    """
    Return a run's newest valid score of its task's primary metric at the current version.

    Parameters
    ----------
    ctx : Context
    record : RunRecord

    Returns
    -------
    float or None
        None for a run without a task, an unknown project or task, or no such score.
    """
    if record.task is None:
        return None
    try:
        config = ctx.store.load_project(record.project).config
    except StoreError:
        return None
    spec = config.tasks.get(record.task)
    if spec is None:
        return None
    metric, key = parse_metric_key(spec.primary)
    current = config.metrics.get(metric)
    if current is None:
        return None
    value: float | None = None
    scores = ctx.index.scores_for([record.run_id]).get(record.run_id, [])
    for score in sorted(scores, key=lambda s: s.created_at):
        if (
            score.metric == metric
            and score.key == key
            and score.version == current.version
            and score.error is None
            and score.value is not None
        ):
            value = score.value
    return value


def _chips(ctx: Context, run_ids: list[str]) -> list[RunChip]:
    chips: list[RunChip] = []
    for run_id in run_ids:
        record = ctx.index.get_run(run_id)
        if record is None:
            chips.append(RunChip(run_id=run_id, status=None, task=None, label=run_id, primary=None))
            continue
        label = group_label(record.hypothesis, record.tags, run_id).removeprefix("group ")
        chips.append(
            RunChip(
                run_id=run_id,
                status=record.status,
                task=record.task,
                label=label,
                primary=run_primary(ctx, record),
            )
        )
    return chips


def list_days(ctx: Context, project: str) -> list[dict[str, Any]]:
    """
    List a project's notebook days, newest first.

    Parameters
    ----------
    ctx : Context
    project : str

    Returns
    -------
    list of dict
        ``{day, bytes, entries}`` per day file.

    Raises
    ------
    StoreError
        Unknown project.
    """
    _require_project(ctx, project)
    folder = notebook_dir(ctx.layout, project)
    if not folder.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.md"), reverse=True):
        if not re.fullmatch(DAY_PATTERN, path.stem):
            continue
        try:
            with path.open("rb") as fh:
                data = fh.read()  # one read: bytes and entries of the same text
        except FileNotFoundError:
            continue  # an empty save removed the day after the listing
        text = data.decode("utf-8", errors="replace")
        out.append(
            {"day": path.stem, "bytes": len(data), "entries": len(ENTRY_STAMP.findall(text))}
        )
    return out


def read_day(ctx: Context, project: str, day: date) -> NotebookDay:
    """
    Read one notebook day with its run chips.

    Parameters
    ----------
    ctx : Context
    project : str
    day : date

    Returns
    -------
    NotebookDay
        Empty text and hash when the day has no file.

    Raises
    ------
    StoreError
        Unknown project.
    """
    _require_project(ctx, project)
    path = day_path(ctx.layout, project, day)
    # one open: the text, its hash, and its time come from the same file, and a day that
    # an empty save removes meanwhile reads as missing instead of failing
    updated: datetime | None = None
    try:
        with path.open("rb") as fh:
            data = fh.read()
            updated = datetime.fromtimestamp(os.fstat(fh.fileno()).st_mtime, UTC)
    except FileNotFoundError:
        data = b""
    text = data.decode("utf-8", errors="replace")
    return NotebookDay(
        project=project,
        day=day,
        text=text,
        hash=_hash(data),
        runs=_chips(ctx, run_links(text)),
        updated_at=updated,
    )


def _emit(ctx: Context, project: str, day: date, author: str) -> None:
    payload = {"project": project, "day": day.isoformat(), "author": author}
    ctx.events.append("notebook.updated", project=project, payload=payload)


def append_entry(
    ctx: Context,
    project: str,
    text: str,
    author: str,
    *,
    day: date | None = None,
    now: datetime | None = None,
) -> NotebookDay:
    """
    Append a stamped entry to a notebook day (never conflicts).

    Parameters
    ----------
    ctx : Context
    project : str
    text : str
        Markdown body; leading and trailing blank space is dropped.
    author : str
        ``human:<user>``, ``agent:<agent>@<user>``, ``digest``, ...
    day : date, optional
        Default: ``hub_today(ctx, now)``.
    now : datetime, optional
        Entry time (default now).

    Returns
    -------
    NotebookDay
        The day after the append.

    Raises
    ------
    StoreError
        Unknown project.
    ConfigError
        Empty text.
    NotebookTooLargeError
        The day would exceed ``NOTEBOOK_MAX_BYTES``.
    """
    _require_project(ctx, project)
    body = text.strip()
    if not body:
        raise ConfigError("empty notebook entry")
    moment = now or utcnow()
    when = day or hub_today(ctx, moment)
    entry = f"\n## {moment.isoformat()} — {author}\n\n{body}\n".encode()
    path = day_path(ctx.layout, project, when)
    with ctx.store.project_lock(project):
        size = path.stat().st_size if path.is_file() else 0
        if size + len(entry) > NOTEBOOK_MAX_BYTES:
            raise NotebookTooLargeError(
                f"notebook day {when} would exceed {NOTEBOOK_MAX_BYTES} bytes"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as fh:
            fh.write(entry)
    _emit(ctx, project, when, author)
    return read_day(ctx, project, when)


def write_day(
    ctx: Context, project: str, day: date, text: str, *, base_hash: str, author: str
) -> NotebookDay:
    """
    Replace a whole notebook day, if nobody saved it since ``base_hash``.

    Parameters
    ----------
    ctx : Context
    project : str
    day : date
    text : str
        New content; an empty text deletes the day file.
    base_hash : str
        ``NotebookDay.hash`` the editor started from ("" for a new day).
    author : str
        Who saved (for the event).

    Returns
    -------
    NotebookDay
        The saved day.

    Raises
    ------
    StoreError
        Unknown project.
    NotebookConflictError
        The file's hash is not ``base_hash``; ``.current`` holds the day as it is.
    NotebookTooLargeError
        ``text`` is larger than ``NOTEBOOK_MAX_BYTES``.
    """
    _require_project(ctx, project)
    data = text.encode("utf-8")
    if data and not data.endswith(b"\n"):
        data += b"\n"
    if len(data) > NOTEBOOK_MAX_BYTES:
        raise NotebookTooLargeError(f"notebook day {day} is over {NOTEBOOK_MAX_BYTES} bytes")
    path = day_path(ctx.layout, project, day)
    with ctx.store.project_lock(project):
        current = path.read_bytes() if path.is_file() else b""
        if _hash(current) != base_hash:
            raise NotebookConflictError(
                f"notebook day {day} changed since you opened it",
                current=read_day(ctx, project, day),
            )
        if data.strip():
            atomic_write_bytes(path, data)
        else:
            path.unlink(missing_ok=True)
    _emit(ctx, project, day, author)
    return read_day(ctx, project, day)
