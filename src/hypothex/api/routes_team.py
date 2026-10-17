"""Notebook, export, and digest routes (phase 3)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request
from pydantic import BaseModel
from starlette.requests import HTTPConnection
from starlette.responses import Response

from hypothex.api.auth import ADMIN, LAUNCH, READ, auth_on, command_key, principal_of
from hypothex.core.context import Context
from hypothex.core.digest import build_digest, send_digest
from hypothex.core.errors import RunError
from hypothex.core.export import (
    EXTENSIONS,
    ExportFormat,
    ExportOptions,
    NoiseMode,
    export_compare,
    export_task,
)
from hypothex.core.ids import utcnow
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.notebook import (
    append_entry,
    hub_today,
    list_days,
    parse_day,
    read_day,
    today,
    write_day,
)
from hypothex.core.settings import Channel, load_settings
from hypothex.notify.notifier import Notifier, notify_status


class NotebookAppendBody(BaseModel):
    """Body of ``POST .../notebook/{day}``; the author is the caller."""

    text: str
    command_id: str | None = None


class NotebookWriteBody(BaseModel):
    """Body of ``PUT .../notebook/{day}``."""

    text: str
    base_hash: str
    command_id: str | None = None


class DigestSendBody(BaseModel):
    """Body of ``POST .../digest/send``."""

    since: datetime | None = None
    channels: list[Channel] | None = None
    command_id: str | None = None


class NotifyTestBody(BaseModel):
    """Body of ``POST /api/v1/notify/test``."""

    channel: Channel
    command_id: str | None = None


def notebook_author(conn: HTTPConnection) -> str:
    """
    Return who writes a notebook entry.

    Parameters
    ----------
    conn : HTTPConnection

    Returns
    -------
    str
        The caller's identity with auth on; ``human`` with auth off.
    """
    return principal_of(conn).identity() if auth_on(conn) else "human"


def _aware(moment: datetime | None) -> datetime | None:
    """Treat naive query timestamps as UTC."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def _split(value: str | None) -> list[str] | None:
    """Split a comma-separated query into nonempty values."""
    items = [v.strip() for v in (value or "").split(",") if v.strip()]
    return items or None


def _download(text: str, fmt: str, stem: str) -> Response:
    """Return an export with its media type and attachment filename."""
    media = "text/csv; charset=utf-8" if fmt == "csv" else "text/plain; charset=utf-8"
    disposition = f'attachment; filename="{stem}.{EXTENSIONS[fmt]}"'
    return Response(text, media_type=media, headers={"Content-Disposition": disposition})


def register_team_routes(app: FastAPI, ctx: Context) -> None:
    """
    Add the notebook, export, and digest routes.

    Parameters
    ----------
    app : FastAPI
    ctx : Context
    """

    def the_day(day: str) -> date:
        # `today` is the hub's date (contract 1.4), so a browser or a client in another
        # zone never picks the day file; anything else must be YYYY-MM-DD
        """Resolve today on the hub or validate a calendar day."""
        return hub_today(ctx) if day == "today" else parse_day(day)

    @app.get("/api/v1/projects/{project}/notebook", dependencies=READ)
    def notebook_days(project: str) -> list[dict[str, Any]]:
        """List the available notebook days for a project."""
        return list_days(ctx, project)

    @app.get("/api/v1/projects/{project}/notebook/{day}", dependencies=READ)
    def notebook_day(project: str, day: str) -> dict[str, Any]:
        """Read a notebook day and its linked run summaries."""
        return to_jsonable(read_day(ctx, project, the_day(day)))

    @app.post("/api/v1/projects/{project}/notebook/{day}", dependencies=LAUNCH)
    def notebook_append(
        project: str, day: str, body: NotebookAppendBody, request: Request
    ) -> dict[str, Any]:
        """Append an entry attributed to the authenticated caller."""
        when = the_day(day)
        author = notebook_author(request)
        return ctx.events.run_once(
            command_key(request, body.command_id),
            lambda: to_jsonable(append_entry(ctx, project, body.text, author, day=when)),
        )

    @app.put("/api/v1/projects/{project}/notebook/{day}", dependencies=LAUNCH)
    def notebook_write(
        project: str, day: str, body: NotebookWriteBody, request: Request
    ) -> dict[str, Any]:
        """Replace a notebook day using its optimistic concurrency hash."""
        when = the_day(day)
        author = notebook_author(request)
        return ctx.events.run_once(
            command_key(request, body.command_id),
            lambda: to_jsonable(
                write_day(ctx, project, when, body.text, base_hash=body.base_hash, author=author)
            ),
        )

    def options(
        fmt: ExportFormat,
        metrics: str | None,
        noise: NoiseMode,
        digits: int,
        percent: bool,
        top: int | None,
        groups: str | None,
        baselines: bool,
        caption: str | None,
        label: str | None,
        standalone: bool,
        *,
        primary: str | None = None,
    ) -> ExportOptions:
        """Validate the shared export query options."""
        return ExportOptions(
            format=fmt,
            primary=primary,
            metrics=_split(metrics),
            noise=noise,
            digits=digits,
            percent=percent,
            top=top,
            groups=_split(groups),
            baselines=baselines,
            caption=caption,
            label=label,
            standalone=standalone,
        )

    @app.get("/api/v1/tasks/{project}/{task}/export", dependencies=READ)
    def task_export(
        project: str,
        task: str,
        format: ExportFormat = "markdown",
        metrics: str | None = None,
        primary: str | None = None,
        noise: NoiseMode = "both",
        digits: Annotated[int, Query(ge=0, le=6)] = 3,
        percent: bool = False,
        top: Annotated[int | None, Query(ge=1)] = None,
        groups: str | None = None,
        baselines: bool = True,
        caption: str | None = None,
        label: str | None = None,
        standalone: bool = False,
    ) -> Response:
        """Download a task leaderboard with the selected ranking and format."""
        opts = options(
            format, metrics, noise, digits, percent, top, groups, baselines, caption, label,
            standalone, primary=primary,
        )  # fmt: skip
        return _download(export_task(ctx, task, project, opts), opts.format, task)

    @app.get("/api/v1/compare/export", dependencies=READ)
    def compare_export(
        run_ids: str,
        format: ExportFormat = "markdown",
        metrics: str | None = None,
        primary: str | None = None,
        noise: NoiseMode = "both",
        digits: Annotated[int, Query(ge=0, le=6)] = 3,
        percent: bool = False,
        top: Annotated[int | None, Query(ge=1)] = None,
        groups: str | None = None,
        baselines: bool = True,
        caption: str | None = None,
        label: str | None = None,
        standalone: bool = False,
    ) -> Response:
        """Download a comparison of two to twenty runs."""
        ids = _split(run_ids) or []
        if not 2 <= len(ids) <= 20:
            raise RunError("run_ids takes 2 to 20 comma-separated run ids")
        opts = options(
            format, metrics, noise, digits, percent, top, groups, baselines, caption, label,
            standalone, primary=primary,
        )  # fmt: skip
        return _download(export_compare(ctx, ids, opts), opts.format, "compare")

    @app.get("/api/v1/projects/{project}/digest", dependencies=READ)
    def digest(
        project: str, since: datetime | None = None, until: datetime | None = None
    ) -> dict[str, Any]:
        """Build a project digest for the requested time window."""
        end = _aware(until) or utcnow()
        start = _aware(since) or end - timedelta(days=7)
        top_notes = load_settings(ctx.layout).digest.top_notes
        return to_jsonable(build_digest(ctx, project, since=start, until=end, top_notes=top_notes))

    @app.post("/api/v1/projects/{project}/digest/send", dependencies=ADMIN)
    def digest_send(project: str, body: DigestSendBody, request: Request) -> dict[str, Any]:
        """Queue an administrator-requested digest and save its notebook copy."""
        settings = load_settings(ctx.layout)

        def act() -> dict[str, Any]:
            """Apply the authorized action once and return its result."""
            now = utcnow()
            channels = send_digest(
                ctx, settings, project, now=now, channels=body.channels, since=_aware(body.since)
            )
            day = today(now, settings.digest.timezone) if settings.digest.save_to_notebook else None
            return {"channels": channels, "notebook_day": None if day is None else day.isoformat()}

        return ctx.events.run_once(command_key(request, body.command_id), act)

    @app.get("/api/v1/notify", dependencies=ADMIN)
    def notify_route() -> dict[str, Any]:
        """Describe notification configuration without returning secrets."""
        return notify_status(ctx, load_settings(ctx.layout))

    @app.post("/api/v1/notify/test", dependencies=ADMIN)
    def notify_test(body: NotifyTestBody, request: Request) -> dict[str, Any]:
        """Send one administrator-requested channel test idempotently."""
        notifier = Notifier(ctx, load_settings(ctx.layout))
        key = command_key(request, body.command_id)
        return ctx.events.run_once(key, lambda: notifier.send_test(body.channel))
