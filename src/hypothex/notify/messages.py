"""Notices: what a run, sweep, digest, or test notification says, and how channels show it."""

from __future__ import annotations

import hashlib
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Literal

from pydantic import BaseModel

from hypothex.core.config import parse_metric_key
from hypothex.core.context import Context
from hypothex.core.cost import compute_cost
from hypothex.core.errors import StoreError
from hypothex.core.ids import utcnow
from hypothex.core.notebook import run_primary
from hypothex.core.records import RunRecord, RunStatus
from hypothex.core.settings import Channel, EmailSettings
from hypothex.core.sweeps import SweepSummary

NoticeKind = Literal["run", "sweep", "digest", "test"]
STATUS_GLYPH = {"finished": "✓", "failed": "✗", "lost": "?", "killed": "⊘"}
STDERR_CHARS = 200
STDERR_TAIL_BYTES = 8192


class Notice(BaseModel):
    """One notification, before it is shown on a channel."""

    id: str
    kind: NoticeKind
    project: str | None
    run_id: str | None = None
    sweep_id: str | None = None
    status: str | None = None
    title: str
    lines: list[str]
    url: str | None
    created_at: datetime


def notice_id(
    kind: str, project: str | None, ref: str | None, status: str | None, n: int = 0
) -> str:
    """
    Return the stable id of a notice: one per (kind, project, run/sweep/week, status, n).

    Parameters
    ----------
    kind : str
    project : str or None
    ref : str or None
        Run id, sweep id, or ISO week.
    status : str or None
    n : int
        Run count for a sweep notice.

    Returns
    -------
    str
        16 hex digits.

    Examples
    --------
    >>> notice_id("run", "toy", "r1", "finished") == notice_id("run", "toy", "r1", "finished")
    True
    """
    joined = "\x1f".join([kind, project or "", ref or "", status or "", str(n)])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def fmt_duration(seconds: float) -> str:
    """
    Format a duration tersely.

    Parameters
    ----------
    seconds : float

    Returns
    -------
    str
        ``45s``, ``12m``, ``1h05m``, or ``2d03h``.

    Examples
    --------
    >>> fmt_duration(3900)
    '1h05m'
    """
    total = max(int(seconds), 0)
    if total < 60:
        return f"{total}s"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h"


def _primary_text(ctx: Context, record: RunRecord) -> str | None:
    value = run_primary(ctx, record)
    if value is None or record.task is None:
        return None
    try:
        spec = ctx.store.load_project(record.project).config.tasks[record.task]
    except (StoreError, KeyError):
        return None
    metric, key = parse_metric_key(spec.primary)
    name = metric if key == "value" else f"{metric}/{key}"
    return f"{name} {value:.3f}"


def _stderr_tail(ctx: Context, record: RunRecord) -> str | None:
    path = ctx.run_dir(record) / "logs" / "stderr.log"
    try:
        with path.open("rb") as fh:
            size = fh.seek(0, 2)
            fh.seek(max(size - STDERR_TAIL_BYTES, 0))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:STDERR_CHARS] if lines else None


def _url(base_url: str | None, path: str) -> str | None:
    return f"{base_url.rstrip('/')}{path}" if base_url else None


def cost_text(total_usd: float, complete: bool | None) -> str:
    """
    Format a complete total or an explicitly incomplete recorded subtotal.

    Parameters
    ----------
    total_usd : float
        Known recorded dollars; preserve zero without inferring completeness.
    complete : bool or None
        Only True certifies complete pricing. False and legacy None are unknown.

    Returns
    -------
    str
        ``$0.00`` for a certified free run, otherwise e.g.
        ``Cost unknown · $0.25 recorded`` when pricing is incomplete.
    """
    return f"${total_usd:.2f}" if complete is True else f"Cost unknown · ${total_usd:.2f} recorded"


def run_notice(ctx: Context, record: RunRecord, *, base_url: str | None) -> Notice:
    """
    Build the notice of a run that ended.

    Parameters
    ----------
    ctx : Context
    record : RunRecord
        A run in a terminal status.
    base_url : str or None
        ``server.public_url`` (no link when None).

    Returns
    -------
    Notice
        Not yet redacted: the notifier redacts secrets before it stores it.
    """
    status = record.status.value
    primary = _primary_text(ctx, record) if record.status == RunStatus.FINISHED else None
    head = [STATUS_GLYPH.get(status, "·"), f"{record.project}/{record.task or 'exploratory'}"]
    title = " ".join([*head, record.run_id, *([primary] if primary else [])])
    cost = record.cost or compute_cost(record, None)
    wall = None
    if record.started_at is not None and record.ended_at is not None:
        wall = (record.ended_at - record.started_at).total_seconds()
    facts = [
        record.created_by,
        f"{cost.gpu_hours:.1f} GPU-h",
        cost_text(cost.total_usd, cost.gpu_pricing_complete),
        fmt_duration(wall) if wall is not None else None,
    ]
    lines = [" · ".join(f for f in facts if f)]
    if record.status == RunStatus.FAILED:
        tail = _stderr_tail(ctx, record)
        lines.append(f"exit {record.exit_code}" + (f" · {tail}" if tail else ""))
    elif record.status == RunStatus.LOST:
        lines.append("lost · no exit record")
    elif record.status == RunStatus.KILLED:
        lines.append("killed")
    return Notice(
        id=notice_id("run", record.project, record.run_id, status),
        kind="run",
        project=record.project,
        run_id=record.run_id,
        status=status,
        title=title,
        lines=lines,
        url=_url(base_url, f"/r/{record.run_id}"),
        created_at=utcnow(),
    )


def sweep_notice(ctx: Context, summary: SweepSummary, *, base_url: str | None) -> Notice:
    """
    Build the one notice of a sweep whose runs have all ended.

    Parameters
    ----------
    ctx : Context
    summary : SweepSummary
    base_url : str or None

    Returns
    -------
    Notice
    """
    counts, spec = summary.counts, summary.spec
    done = sum(counts.get(k, 0) for k in ("finished", "failed", "lost", "killed"))
    total = counts.get("total", done)
    bad = counts.get("failed", 0) + counts.get("lost", 0)
    lines = [
        f"✓{counts.get('finished', 0)} ✗{counts.get('failed', 0)} ?{counts.get('lost', 0)} "
        f"⊘{counts.get('killed', 0)} · {cost_text(summary.total_usd, summary.cost_complete)}"
    ]
    best: dict[str, Any] | None = summary.best
    if best:
        params = " ".join(f"{k}={v}" for k, v in best.get("params", {}).items())
        mean = best.get("mean")
        lines.append(f"best {params} {mean:.3f}" if mean is not None else f"best {params}")
    return Notice(
        id=notice_id("sweep", spec.project, spec.id, "done", total),
        kind="sweep",
        project=spec.project,
        sweep_id=spec.id,
        status="done",
        title=f"{'✗' if bad else '✓'} {spec.project} sweep {spec.id} {done}/{total}",
        lines=lines,
        url=_url(base_url, f"/s/{spec.project}/{spec.id}"),
        created_at=utcnow(),
    )


def test_notice(channel: Channel) -> Notice:
    """
    Build a test notice for one channel (``hx notify test``).

    Parameters
    ----------
    channel : Channel

    Returns
    -------
    Notice
    """
    now = utcnow()
    return Notice(
        id=notice_id("test", None, channel, now.isoformat()),
        kind="test",
        project=None,
        title=f"✓ hypothex test · {channel}",
        lines=[],
        url=None,
        created_at=now,
    )


def render_slack(notice: Notice) -> dict[str, Any]:
    """
    Show a notice as a Slack incoming-webhook payload.

    Parameters
    ----------
    notice : Notice

    Returns
    -------
    dict
        ``{"text": "<title>\\n<lines...>\\n<url>"}``.
    """
    parts = [notice.title, *notice.lines, *([notice.url] if notice.url else [])]
    return {"text": "\n".join(parts)}


def render_email(notice: Notice, settings: EmailSettings) -> EmailMessage:
    """
    Show a notice as a plain-text email.

    Parameters
    ----------
    notice : Notice
    settings : EmailSettings
        Sender and recipients.

    Returns
    -------
    EmailMessage
        ``Subject`` = the title; body = the lines and the URL.
    """
    message = EmailMessage()
    message["Subject"] = notice.title
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.to)
    body = "\n".join([*notice.lines, *([notice.url] if notice.url else [])])
    message.set_content((body or notice.title) + "\n")
    return message
