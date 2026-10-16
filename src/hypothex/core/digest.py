"""Weekly digest per project: counts, cost, leaderboard changes, notes, and sweeps.

``build_digest`` reads the index, run notes, the notebook, and sweep files;
``send_digest`` (Task 19) enqueues it on the notifier's outbox and saves it to
the notebook. The notifier calls ``digest_due`` every tick.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from hypothex.core.context import Context
from hypothex.core.cost import add_costs, compute_cost
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import build_leaderboard
from hypothex.core.notebook import (
    ENTRY_STAMP,
    NotebookTooLargeError,
    append_entry,
    day_path,
    parse_entries,
    today,
)
from hypothex.core.records import CostTotals, RunRecord, RunStatus, ScoreRecord
from hypothex.core.settings import Channel, DigestSettings, Settings
from hypothex.core.sweeps import list_sweeps
from hypothex.notify.channels import redact
from hypothex.notify.messages import Notice, cost_text, notice_id

log = logging.getLogger(__name__)
NOTE_CHARS = 200
DIGEST_AUTHOR = "digest"


class TaskChange(BaseModel):
    """How one task's best result moved during the window."""

    task: str
    primary: str
    before: float | None
    after: float | None
    best_label: str
    best_group_id: str | None
    new_best: bool
    n_new_runs: int


class NoteItem(BaseModel):
    """A run note or notebook entry written during the window."""

    source: Literal["run", "notebook"]
    run_id: str | None
    day: date | None
    author: str
    at: datetime
    text: str


class SweepLine(BaseModel):
    """A sweep created during the window."""

    id: str
    n_runs: int
    best: dict[str, Any] | None


class Digest(BaseModel):
    """One project's week."""

    project: str
    since: datetime
    until: datetime
    week: str
    counts: dict[str, int]
    by_owner: dict[str, int]
    cost: CostTotals
    tasks: list[TaskChange]
    notes: list[NoteItem]
    sweeps: list[SweepLine]
    headline: str


def week_key(moment: datetime) -> str:
    """
    Return the ISO week of a moment.

    Parameters
    ----------
    moment : datetime

    Returns
    -------
    str
        ``YYYY-Www``.

    Examples
    --------
    >>> from datetime import UTC
    >>> week_key(datetime(2026, 10, 5, tzinfo=UTC))
    '2026-W41'
    """
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def _in(moment: datetime | None, since: datetime, until: datetime) -> bool:
    return moment is not None and since <= moment <= until


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def _task_changes(
    ctx: Context,
    project: str,
    runs: list[RunRecord],
    scores: dict[str, list[ScoreRecord]],
    since: datetime,
    until: datetime,
) -> list[TaskChange]:
    config = ctx.store.load_project(project).config
    changes: list[TaskChange] = []
    for name in sorted(config.tasks):
        task_runs = [r for r in runs if r.task == name]
        if not task_runs:
            continue
        before_runs = [
            r
            for r in task_runs
            if r.created_at < since and r.ended_at is not None and r.ended_at < since
        ]
        before_scores = {k: [s for s in v if s.created_at < since] for k, v in scores.items()}
        after_runs = [
            r
            for r in task_runs
            if r.created_at <= until and (r.ended_at is None or r.ended_at <= until)
        ]
        after_scores = {k: [s for s in v if s.created_at <= until] for k, v in scores.items()}
        before = build_leaderboard(project, name, config, before_runs, before_scores)
        after = build_leaderboard(project, name, config, after_runs, after_scores)
        top_before = before.rows[0] if before.rows and before.rows[0].primary else None
        top_after = after.rows[0] if after.rows and after.rows[0].primary else None
        new_best = top_after is not None and (
            top_before is None or top_after.group_id != top_before.group_id
        )
        n_new = sum(
            1 for r in task_runs if r.status == RunStatus.FINISHED and _in(r.ended_at, since, until)
        )
        if not n_new and not new_best:
            continue
        changes.append(
            TaskChange(
                task=name,
                primary=after.primary,
                before=top_before.primary.mean if top_before and top_before.primary else None,
                after=top_after.primary.mean if top_after and top_after.primary else None,
                best_label=top_after.label if top_after else "",
                best_group_id=top_after.group_id if top_after else None,
                new_best=new_best,
                n_new_runs=n_new,
            )
        )
    return changes


def _note_entries(path: Path) -> Iterator[tuple[datetime, str, str]]:
    """Stream stamped entries while retaining only their first 200 body characters."""
    try:
        fh = path.open("rb")
    except OSError:
        return
    header = ""
    body = ""
    with fh:
        while raw := fh.readline(65536):
            complete = raw.endswith(b"\n")
            line = raw.decode("utf-8", errors="replace")
            if (complete or len(raw) < 65536) and ENTRY_STAMP.fullmatch(line.rstrip("\r\n")):
                if header:
                    yield from parse_entries(header + "\n" + body)
                header, body = line.rstrip("\r\n"), ""
            elif len(body) < NOTE_CHARS:
                body = (body + line).lstrip()[:NOTE_CHARS]
            # A very long single line is drained without accumulating it. Its
            # continuation cannot masquerade as a new stamped entry.
            if not complete:
                while rest := fh.readline(65536):
                    if rest.endswith(b"\n"):
                        break
        if header:
            yield from parse_entries(header + "\n" + body)


def _notes(
    ctx: Context,
    project: str,
    runs: list[RunRecord],
    since: datetime,
    until: datetime,
    top_notes: int,
) -> list[NoteItem]:
    items: list[NoteItem] = []
    if top_notes <= 0:
        return items

    def keep(item: NoteItem) -> None:
        items.append(item)
        items.sort(key=lambda n: n.at, reverse=True)
        del items[top_notes:]

    for record in runs:
        for stamp, author, body in _note_entries(ctx.run_dir(record) / "notes.md"):
            if _in(stamp, since, until):
                keep(
                    NoteItem(
                        source="run",
                        run_id=record.run_id,
                        day=None,
                        author=author,
                        at=stamp,
                        text=body[:NOTE_CHARS],
                    )
                )
    day = since.date() - timedelta(days=1)
    while day <= until.date() + timedelta(days=1):
        path = day_path(ctx.layout, project, day)
        if path.is_file():
            for stamp, author, body in _note_entries(path):
                if author != DIGEST_AUTHOR and _in(stamp, since, until):
                    keep(
                        NoteItem(
                            source="notebook",
                            run_id=None,
                            day=day,
                            author=author,
                            at=stamp,
                            text=body[:NOTE_CHARS],
                        )
                    )
        day += timedelta(days=1)
    items.sort(key=lambda n: n.at, reverse=True)
    return items


def build_digest(
    ctx: Context,
    project: str,
    *,
    since: datetime,
    until: datetime | None = None,
    top_notes: int = 5,
) -> Digest:
    """
    Build one project's digest for a window.

    Parameters
    ----------
    ctx : Context
    project : str
    since : datetime
        Window start (aware).
    until : datetime, optional
        Window end; default now.
    top_notes : int
        Notes to keep, newest first.

    Returns
    -------
    Digest

    Raises
    ------
    StoreError
        Unknown project.
    """
    end = until or utcnow()
    ctx.store.load_project(project)
    runs = ctx.index.list_runs(project=project, include_archived=True, limit=None)
    created = [r for r in runs if _in(r.created_at, since, end)]
    ended = [r for r in runs if _in(r.ended_at, since, end)]
    counts = {"started": len(created)}
    for status in (RunStatus.FINISHED, RunStatus.FAILED, RunStatus.LOST, RunStatus.KILLED):
        counts[status.value] = sum(1 for r in ended if r.status == status)
    counts["queued"] = sum(1 for r in created if r.status == RunStatus.QUEUED)
    by_owner = dict(sorted(Counter(r.created_by for r in created).items()))
    cost = (
        add_costs(r.cost or compute_cost(r, None) for r in ended)
        if ended
        else CostTotals(gpu_pricing_complete=True)
    )
    assert cost is not None
    scores = ctx.index.scores_for(r.run_id for r in runs)
    tasks = _task_changes(ctx, project, runs, scores, since, end)
    notes = _notes(ctx, project, runs, since, end, top_notes)
    sweeps = [
        SweepLine(id=s["id"], n_runs=s["n_runs"], best=s["best"])
        for s in list_sweeps(ctx, project)
        if _in(s["created_at"], since, end)
    ]
    head = f"▲{counts['started']} ✓{counts['finished']} ✗{counts['failed']} ?{counts['lost']}" + (
        f" ⊘{counts['killed']}" if counts["killed"] else ""
    )
    parts = [
        head,
        f"{cost.gpu_hours:.1f} GPU-h {cost_text(cost.total_usd, cost.gpu_pricing_complete)}",
    ]
    best = next((t for t in tasks if t.new_best and t.after is not None), None)
    if best is not None:
        parts.append(f"{best.task} {_fmt(best.before)}→{_fmt(best.after)} ▲")
    return Digest(
        project=project,
        since=since,
        until=end,
        week=week_key(end),
        counts=counts,
        by_owner=by_owner,
        cost=cost,
        tasks=tasks,
        notes=notes,
        sweeps=sweeps,
        headline=" · ".join(parts),
    )


def _who(author: str) -> str:
    return "@" + author.removeprefix("human:") if author.startswith("human:") else author


def _task_line(change: TaskChange) -> str:
    """One task change as ``toy-acc 0.600→0.700 ▲ · 1 runs`` (notebook and notices alike)."""
    best = " ▲" if change.new_best else ""
    moved = f"{_fmt(change.before)}→{_fmt(change.after)}{best}"
    return f"{change.task} {moved} · {change.n_new_runs} runs"


def _note_line(note: NoteItem) -> str:
    """One note as ``10-04 09:00 @alice [[run:<id>]] <text on one line>``."""
    text = " ".join(note.text.split())
    link = f" [[run:{note.run_id}]]" if note.run_id else ""
    return f"{note.at:%m-%d %H:%M} {_who(note.author)}{link} {text}"


def render_digest_markdown(digest: Digest) -> str:
    """
    Render a digest as the Markdown block saved to the notebook.

    Parameters
    ----------
    digest : Digest

    Returns
    -------
    str
        ``**<week>** · <headline>``, then a list of task changes, notes, and
        sweeps (each only when present).
    """
    blocks = [f"**{digest.week}** · {digest.headline}"]
    if digest.tasks:
        # a list, not a table: the UI's Markdown (and contract 10.1's summary block) has no tables
        blocks.append("\n".join(f"- {_task_line(t)}" for t in digest.tasks))
    if digest.notes:
        blocks.append("\n".join(["notes", *(f"- {_note_line(n)}" for n in digest.notes)]))
    if digest.sweeps:
        lines = ["sweeps"]
        for sweep in digest.sweeps:
            best = ""
            if sweep.best:
                params = " ".join(f"{k}={v}" for k, v in sweep.best.get("params", {}).items())
                mean = sweep.best.get("mean")
                best = f" · best {params}" + (f" {mean:.3f}" if mean is not None else "")
            lines.append(f"- {sweep.id} · {sweep.n_runs} runs{best}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def digest_notice(digest: Digest, *, base_url: str | None) -> Notice:
    """
    Build the notice of a digest (one per send).

    Parameters
    ----------
    digest : Digest
    base_url : str or None

    Returns
    -------
    Notice
        ``lines``: one per task change, then one ``✎`` line per top note
        (``top_notes`` of the build, newest first).
    """
    lines = [_task_line(t) for t in digest.tasks]
    lines += [f"✎ {_note_line(note)}" for note in digest.notes]
    return Notice(
        id=notice_id("digest", digest.project, digest.week, digest.until.isoformat()),
        kind="digest",
        project=digest.project,
        title=f"Σ {digest.project} {digest.week} · {digest.headline}",
        lines=lines,
        url=f"{base_url.rstrip('/')}/n/{digest.project}" if base_url else None,
        created_at=utcnow(),
    )


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def digest_due(settings: DigestSettings, last_sent: str | None, now: datetime) -> str | None:
    """
    Tell whether this week's digest is due.

    Parameters
    ----------
    settings : DigestSettings
        Weekday, hour, and timezone.
    last_sent : str or None
        The week key sent last (``digest.json``).
    now : datetime
        Aware current time.

    Returns
    -------
    str or None
        This week's key when ``now`` (local) is at or after this week's
        ``weekday`` ``hour:00`` and that week was not sent; else None. Earlier
        missed weeks are never sent.
    """
    if not settings.enabled:
        return None
    zone = ZoneInfo(settings.timezone) if settings.timezone else None
    local = now.astimezone(zone) if zone is not None else now.astimezone()
    key = week_key(local)
    if last_sent == key:
        return None
    return key if now.timestamp() >= digest_due_at(settings, now).timestamp() else None


def digest_due_at(settings: DigestSettings, now: datetime) -> datetime:
    """
    Return this week's send time: ``weekday`` at ``hour:00`` in the digest's zone.

    A scheduled digest ends its window here (not at the tick that sends it), so
    a resend after a crash builds the same window, notice id, and notebook stamp.

    Parameters
    ----------
    settings : DigestSettings
        Weekday, hour, and timezone (the machine's zone when unset).
    now : datetime
        Aware time in the week.

    Returns
    -------
    datetime
        Aware, in the digest's zone.

    Examples
    --------
    >>> from datetime import UTC
    >>> s = DigestSettings(enabled=True, weekday="mon", hour=9, timezone="UTC")
    >>> digest_due_at(s, datetime(2026, 10, 7, 12, tzinfo=UTC)).isoformat()
    '2026-10-05T09:00:00+00:00'
    """
    zone = ZoneInfo(settings.timezone) if settings.timezone else None
    local = now.astimezone(zone) if zone is not None else now.astimezone()
    monday = local.date() - timedelta(days=local.weekday())
    day = monday + timedelta(days=WEEKDAYS.index(settings.weekday))
    scheduled = datetime(day.year, day.month, day.day, settings.hour)
    # astimezone() on a naive wall time asks the system for that date's offset,
    # unlike local.tzinfo which is only a fixed offset at the current moment.
    return scheduled.replace(tzinfo=zone) if zone else scheduled.astimezone()


def send_digest(
    ctx: Context,
    settings: Settings,
    project: str,
    *,
    now: datetime,
    channels: list[Channel] | None = None,
    since: datetime | None = None,
) -> list[str]:
    """
    Build a project's digest, enqueue it, and save it to the notebook.

    Parameters
    ----------
    ctx : Context
    settings : Settings
    project : str
    now : datetime
        The window's end and the notebook entry's time.
    channels : list of Channel, optional
        Default ``settings.digest.channels``; unconfigured channels are dropped.
    since : datetime, optional
        Window start; default ``now - 7 days``.

    Returns
    -------
    list of str
        Channels a notice was enqueued on. A notebook day that is full
        (``NotebookTooLargeError``) loses the copy, never the digest: it is
        logged and the digest still counts as sent.

    Raises
    ------
    StoreError
        Unknown project.
    """
    from hypothex.notify.notifier import Notifier  # the notifier imports this module

    digest = build_digest(
        ctx,
        project,
        since=since or now - timedelta(days=7),
        until=now,
        top_notes=settings.digest.top_notes,
    )
    notifier = Notifier(ctx, settings, now=lambda: now)
    wanted = channels if channels is not None else settings.digest.channels
    made = notifier.enqueue(digest_notice(digest, base_url=settings.server.public_url), wanted)
    sent = [e.channel for e in made]
    if settings.digest.save_to_notebook:
        day = today(now, settings.digest.timezone)
        saved = any(
            stamp == now and author == DIGEST_AUTHOR
            for stamp, author, _ in _note_entries(day_path(ctx.layout, project, day))
        )
        if not saved:  # a resend after a crash: saved once
            body = redact(render_digest_markdown(digest), notifier.secret_values())
            try:
                append_entry(ctx, project, body, DIGEST_AUTHOR, day=day, now=now)
            except NotebookTooLargeError:
                # the notice is queued already; a retry would hit the same full day each tick
                log.warning("digest of %s not saved: notebook day %s is full", project, day)
    ctx.events.append(
        "digest.sent",
        project=project,
        payload={"project": project, "week": digest.week, "channels": sent},
    )
    return list(sent)
