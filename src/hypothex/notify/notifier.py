"""The hub's notifier: event log -> outbox -> Slack and email, at least once.

Only the hub's ``hx serve`` runs it (a thread in the lifespan, Task 30). Each
notice and channel is one file in ``<home>/notify/outbox``; a final state moves
it to ``sent.jsonl``. A crash after a send but before its record leaves the
entry ``sending``; it is sent again after ``SENDING_RETRY_SECONDS``.
"""

from __future__ import annotations

import fcntl
import heapq
import json
import logging
import os
import ssl
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from hypothex.core.context import Context
from hypothex.core.digest import digest_due, digest_due_at, send_digest
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.events import Event
from hypothex.core.fsutil import fsync_dir, iter_jsonl
from hypothex.core.ids import utcnow
from hypothex.core.records import RunRecord
from hypothex.core.settings import (
    Channel,
    ProjectRule,
    Settings,
    _read_secrets,
    load_settings,
    resolve_secret,
    secret_env_names,
    write_private,
)
from hypothex.core.sweeps import (
    SweepSummary,
    summarize_sweep,
    sweep_combos,
    sweep_issuing,
    sweep_tag,
)
from hypothex.notify.channels import ChannelError, redact, send_email, send_slack
from hypothex.notify.messages import (
    Notice,
    render_email,
    render_slack,
    run_notice,
    sweep_notice,
    test_notice,
)
from hypothex.remote.config import load_hosts

log = logging.getLogger(__name__)

NOTIFY_DIR = "notify"
RETRY_DELAYS = (30.0, 120.0, 600.0)
"""Seconds to wait after failed attempts 1, 2, and 3; a fourth failure is final."""
TERMINAL_EVENTS = ("run.finished", "run.failed", "run.killed", "run.lost")
SENDING_RETRY_SECONDS = 60.0
SCAN_BATCH = 500
MAX_ENTRY_BYTES = 1024 * 1024


class OutboxEntry(BaseModel):
    """One notice on one channel, from enqueue to its final state."""

    id: str
    channel: Channel
    notice: Notice
    status: Literal["pending", "sending", "sent", "failed", "skipped"]
    attempts: int = 0
    next_at: datetime
    last_error: str | None = None
    created_at: datetime
    sent_at: datetime | None = None


class _Skip(Exception):
    """The entry cannot be sent with the current settings (``unset:<VAR>``, ...)."""

    def __init__(self, error_class: str) -> None:
        super().__init__(error_class)
        self.error_class = error_class


def _status_of(event: Event) -> str | None:
    """The terminal status an event reports, or None."""
    if event.type in TERMINAL_EVENTS:
        return event.type.removeprefix("run.")
    if event.type == "mirror.run_updated":
        original = event.payload.get("original_type")
        if original in TERMINAL_EVENTS:
            return str(original).removeprefix("run.")
    return None


def _append_private(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a+b") as fh:
        if fh.seek(0, os.SEEK_END):
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                fh.write(b"\n")
        fh.write((line + "\n").encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())
    fsync_dir(path.parent)


class Notifier:
    """
    Turns run endings into outbox entries and delivers them.

    Parameters
    ----------
    ctx : Context
        The hub's context.
    settings : Settings
        Current settings (``run_notifier_loop`` refreshes them every tick).
    now : callable
        Clock (tests pass a fake one; no test sleeps).
    transport : httpx.BaseTransport, optional
        For Slack calls in tests.
    ssl_context : ssl.SSLContext, optional
        For SMTP in tests (trust a fake CA).
    """

    def __init__(
        self,
        ctx: Context,
        settings: Settings,
        *,
        now: Callable[[], datetime] = utcnow,
        transport: httpx.BaseTransport | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.ctx = ctx
        self.settings = settings
        self.now = now
        self.transport = transport
        self.ssl_context = ssl_context
        self.root = ctx.layout.home / NOTIFY_DIR
        self.outbox = self.root / "outbox"
        self._sent: set[str] | None = None
        self._sent_version: tuple[int, int, int] | None = None
        self._sweeps: dict[tuple[str, str], SweepSummary | None] = {}
        self._pending = self._read_pending()

    # files ---------------------------------------------------------------------------
    @contextmanager
    def _outbox_lock(self) -> Iterator[None]:
        """Serialize outbox writers and delivery across notifier instances."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        fd = os.open(self.root / "outbox.lock", os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _path(self, entry_id: str, channel: str) -> Path:
        return self.outbox / f"{entry_id}.{channel}.json"

    def _write(self, entry: OutboxEntry) -> None:
        text = entry.model_dump_json(indent=2)
        if len(text.encode("utf-8")) >= MAX_ENTRY_BYTES:
            raise ValueError("notification entry exceeds the size limit")
        write_private(self._path(entry.id, entry.channel), text)

    def _read_cursor(self) -> int | None:
        try:
            return int(json.loads((self.root / "cursor.json").read_text())["last_sequence"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save_cursor(self, sequence: int) -> None:
        write_private(self.root / "cursor.json", json.dumps({"last_sequence": sequence}))

    def _read_pending(self) -> dict[str, Event]:
        try:
            raw = json.loads((self.root / "pending-sweeps.json").read_text())
            return {key: Event.model_validate(value) for key, value in raw.items()}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def _save_pending(self) -> None:
        write_private(
            self.root / "pending-sweeps.json",
            json.dumps(
                {key: event.model_dump(mode="json") for key, event in self._pending.items()}
            ),
        )

    def _sent_keys(self) -> set[str]:
        path = self.root / "sent.jsonl"
        try:
            stat = path.stat()
            version = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            version = None
        if self._sent is None or version != self._sent_version:
            rows = iter_jsonl(path, max_line_bytes=MAX_ENTRY_BYTES)
            self._sent = {f"{r.get('id')}.{r.get('channel')}" for r in rows}
            self._sent_version = version
        return self._sent

    def _finish(self, entry: OutboxEntry) -> OutboxEntry:
        known = self._sent_keys()
        _append_private(self.root / "sent.jsonl", entry.model_dump_json())
        stat = (self.root / "sent.jsonl").stat()
        self._sent_version = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        known.add(f"{entry.id}.{entry.channel}")
        self._path(entry.id, entry.channel).unlink(missing_ok=True)
        fsync_dir(self.outbox)
        kind = "notify.sent" if entry.status == "sent" else "notify.failed"
        self.ctx.events.append(
            kind,
            project=entry.notice.project,
            run_id=entry.notice.run_id,
            payload={
                "entry_id": entry.id,
                "channel": entry.channel,
                "kind": entry.notice.kind,
                "run_id": entry.notice.run_id,
                "attempts": entry.attempts,
                "error_class": entry.last_error,
            },
        )
        return entry

    # rules ---------------------------------------------------------------------------
    def _configured(self, channel: Channel) -> bool:
        if channel == "slack":
            return self.settings.notify.slack is not None
        return self.settings.notify.email is not None

    def _rule(self, project: str) -> ProjectRule | None:
        return self.settings.notify.projects.get(project) or self.settings.notify.default

    def secret_values(self) -> list[SecretStr]:
        """
        Return every configured secret value (to redact from notices and errors).

        Returns
        -------
        list of SecretStr
            Configured and default secret variables, host token variables, and
            every value in a safe ``secrets.env``. An unsafe file contributes
            nothing; environment values can still be redacted.
        """
        names = secret_env_names(self.settings)
        try:
            for host in load_hosts(self.ctx.layout).environments.values():
                name = getattr(host, "token_env", None)
                if name:
                    names.add(name)
        except ConfigError:
            pass
        values: list[SecretStr] = []
        with suppress(ConfigError):
            values.extend(SecretStr(value) for value in _read_secrets(self.ctx.layout).values())
        for name in names:
            try:
                value = resolve_secret(self.ctx.layout, name)
            except ConfigError:
                value = None
            if value is not None:
                values.append(value)
        return values

    def _redact(self, notice: Notice) -> Notice:
        secrets = self.secret_values()
        fields = ("project", "run_id", "sweep_id", "status", "title", "url")
        update = {
            name: redact(value, secrets)
            for name in fields
            if isinstance(value := getattr(notice, name), str)
        }
        return notice.model_copy(
            update={**update, "lines": [redact(line, secrets) for line in notice.lines]}
        )

    # enqueue -------------------------------------------------------------------------
    def enqueue(self, notice: Notice, channels: Iterable[Channel]) -> list[OutboxEntry]:
        """
        Write one pending entry per configured channel, unless one exists already.

        Every configured secret value is redacted here, before anything is
        written: run, sweep, and digest notices (a note quoting a webhook URL)
        all pass through this one place.

        Parameters
        ----------
        notice : Notice
            The notice as built.
        channels : iterable of Channel
            Wanted channels; unconfigured ones are dropped.

        Returns
        -------
        list of OutboxEntry
            The new entries (empty when every one was queued or sent before).
        """
        with self._outbox_lock():
            return self._enqueue(notice, channels)

    def _enqueue(self, notice: Notice, channels: Iterable[Channel]) -> list[OutboxEntry]:
        notice = self._redact(notice)
        made: list[OutboxEntry] = []
        now = self.now()
        for channel in dict.fromkeys(channels):
            if not self._configured(channel):
                continue
            if f"{notice.id}.{channel}" in self._sent_keys():
                continue
            if self._path(notice.id, channel).exists():
                continue
            entry = OutboxEntry(
                id=notice.id,
                channel=channel,
                notice=notice,
                status="pending",
                next_at=now,
                created_at=now,
            )
            self._write(entry)
            made.append(entry)
        return made

    def scan(self) -> list[OutboxEntry]:
        """
        Read the event log after the cursor and enqueue the notices it calls for.

        Returns
        -------
        list of OutboxEntry
            New entries. The first scan of a home only sets the cursor.
        """
        last = self._read_cursor()
        if last is None:
            self._save_cursor(self.ctx.events.last_sequence())
            return []
        self._sweeps = {}
        made: list[OutboxEntry] = []
        # Retry before fetching events, even with an empty log or after restart. If a
        # later launch failed there may never be another member-ending event.
        for event in list(self._pending.values()):
            made += self._consider(event)
        while True:
            batch = self.ctx.events.since(last, SCAN_BATCH)
            # one summary per sweep per batch, read after the batch was fetched, so it holds
            # every ending in it; a summary kept across batches would miss a sweep whose last
            # run ends while an earlier batch is read (its notice would never be sent)
            self._sweeps = {}
            for event in batch:
                made += self._consider(event)
                last = event.sequence
            self._save_cursor(last)
            if len(batch) < SCAN_BATCH:
                return made

    def _sweep(self, record: RunRecord) -> SweepSummary | None:
        # a member carries this hub's tag (sweep_runs matches it exactly): a mirrored run of
        # another hub's sweep with the same id is not one, and is notified as a run
        if sweep_tag(self.ctx.descriptor.environment_id, str(record.sweep_id)) not in record.tags:
            return None
        key = (record.project, str(record.sweep_id))
        if key not in self._sweeps:
            try:
                self._sweeps[key] = summarize_sweep(self.ctx, *key)
            except (StoreError, ConfigError):
                self._sweeps[key] = None  # the sweep file is not on this hub: notify the run
        return self._sweeps[key]

    def _consider(self, event: Event) -> list[OutboxEntry]:
        if _status_of(event) is None or event.run_id is None:
            return []
        made, deferred = self._consider_now(event)
        # One trigger per sweep is sufficient; it is only used to find the live summary.
        try:
            record = self.ctx.find_record(event.run_id) if event.run_id else None
        except StoreError:
            record = None
        owns_sweep = (
            record is not None
            and record.sweep_id is not None
            and (sweep_tag(self.ctx.descriptor.environment_id, str(record.sweep_id)) in record.tags)
        )
        key = (
            f"{record.project}/{record.sweep_id}"
            if owns_sweep
            else next((k for k, saved in self._pending.items() if saved.run_id == event.run_id), "")
        )
        if deferred:
            self._pending[key] = event
            self._save_pending()  # durable before scan can advance its event cursor
        elif key in self._pending:
            del self._pending[key]
            self._save_pending()  # after enqueue: deterministic IDs make replay safe
        return made

    def _consider_now(self, event: Event) -> tuple[list[OutboxEntry], bool]:
        status = _status_of(event)
        if status is None or event.run_id is None:
            return [], False
        try:
            record = self.ctx.find_record(event.run_id)
        except StoreError:
            return [], False
        rule = self._rule(record.project)
        if rule is None:
            return [], False
        max_age = timedelta(hours=self.settings.notify.max_age_hours)
        if record.ended_at is not None and self.now() - record.ended_at > max_age:
            return [], False
        base = self.settings.server.public_url
        summary = self._sweep(record) if rule.fold_sweeps and record.sweep_id else None
        if summary is not None:
            counts = summary.counts
            if counts.get("queued", 0) + counts.get("running", 0) > 0:
                return [], True
            spec = summary.spec
            if summary.issuance is not None:
                if summary.issuance.state in {"preparing", "queued", "issuing", "settling"}:
                    return [], True  # durable worker may add or settle members with no run event
            else:
                # Legacy/direct-core sweeps still use the synchronous launch lock.
                planned = len(sweep_combos(spec)) * len(spec.seeds)
                if counts.get("total", 0) < planned and sweep_issuing(
                    self.ctx.layout, spec.project, spec.id
                ):
                    return [], True
            if not any(counts.get(wanted, 0) for wanted in rule.events):
                return [], False  # the sweep's outcome holds no status this rule asks for
            notice = sweep_notice(self.ctx, summary, base_url=base)
        else:
            if status not in rule.events:
                return [], False
            if status == "finished" and rule.min_seconds > 0:
                wall = 0.0
                if record.started_at is not None and record.ended_at is not None:
                    wall = (record.ended_at - record.started_at).total_seconds()
                if wall < rule.min_seconds:
                    return [], False
            notice = run_notice(self.ctx, record, base_url=base)
        return self.enqueue(notice, rule.channels), False

    # delivery ------------------------------------------------------------------------
    def _send(self, entry: OutboxEntry) -> None:
        notice = entry.notice
        layout = self.ctx.layout
        if entry.channel == "slack":
            slack = self.settings.notify.slack
            if slack is None:
                raise _Skip("unconfigured")
            hook = resolve_secret(layout, slack.webhook_env)
            if hook is None:
                raise _Skip(f"unset:{slack.webhook_env}")
            send_slack(hook, render_slack(notice), transport=self.transport)
            return
        email = self.settings.notify.email
        if email is None:
            raise _Skip("unconfigured")
        password = resolve_secret(layout, email.password_env) if email.password_env else None
        if email.username and password is None:
            raise _Skip(f"unset:{email.password_env}")
        message = render_email(notice, email)
        send_email(email, password, message, ssl_context=self.ssl_context)

    def _attempt(self, entry: OutboxEntry, now: datetime) -> OutboxEntry:
        attempts = entry.attempts + 1
        sending = entry.model_copy(
            update={
                "status": "sending",
                "attempts": attempts,
                "next_at": now + timedelta(seconds=SENDING_RETRY_SECONDS),
            }
        )
        self._write(sending)  # recorded before the send: a crash leaves it "sending"
        try:
            self._send(sending)
        except _Skip as exc:
            final = {
                "status": "skipped",
                "attempts": attempts,
                "last_error": redact(exc.error_class, self.secret_values()),
            }
            return self._finish(sending.model_copy(update=final))
        except ConfigError:
            final = {"status": "skipped", "attempts": attempts, "last_error": "secrets_file"}
            return self._finish(sending.model_copy(update=final))
        except ChannelError as exc:
            error = redact(exc.error_class, self.secret_values())
            if exc.permanent or attempts > len(RETRY_DELAYS):
                final = {"status": "failed", "attempts": attempts, "last_error": error}
                return self._finish(sending.model_copy(update=final))
            delay = max(RETRY_DELAYS[attempts - 1], exc.retry_after or 0.0)
            retry = sending.model_copy(
                update={
                    "status": "pending",
                    "attempts": attempts,
                    "last_error": error,
                    "next_at": now + timedelta(seconds=delay),
                }
            )
            self._write(retry)
            return retry
        sent = {"status": "sent", "attempts": attempts, "sent_at": now, "last_error": None}
        return self._finish(sending.model_copy(update=sent))

    def deliver(self) -> list[OutboxEntry]:
        """
        Send every due entry once.

        Returns
        -------
        list of OutboxEntry
            The entries after this attempt (final or rescheduled).
        """
        now = self.now()
        out: list[OutboxEntry] = []
        for path in sorted(self.outbox.glob("*.json")) if self.outbox.is_dir() else []:
            # Release between entries so an API enqueue never waits for the
            # entire backlog of channel timeouts to finish.
            with self._outbox_lock():
                try:
                    entry = self._read_entry(path)
                except (OSError, ValidationError):
                    continue
                if f"{entry.id}.{entry.channel}" in self._sent_keys():
                    # The journal wins over an outbox file left by a crash.
                    path.unlink(missing_ok=True)
                    continue
                if entry.status not in ("pending", "sending") or entry.next_at > now:
                    continue
                out.append(self._attempt(entry, now))
        return out

    def recent(self, limit: int = 50) -> list[OutboxEntry]:
        """
        Return the newest entries, final and pending, newest first.

        Parameters
        ----------
        limit : int

        Returns
        -------
        list of OutboxEntry
        """
        if limit <= 0:
            return []
        return heapq.nlargest(
            limit, self._recent_entries(), key=lambda e: (e.created_at, e.id, e.channel)
        )

    def _read_entry(self, path: Path) -> OutboxEntry:
        with path.open("rb") as fh:
            data = fh.read(MAX_ENTRY_BYTES + 1)
        if len(data) > MAX_ENTRY_BYTES:
            raise OSError("notification entry exceeds the size limit")
        return OutboxEntry.model_validate_json(data)

    def _recent_entries(self) -> Iterator[OutboxEntry]:
        for row in iter_jsonl(self.root / "sent.jsonl", max_line_bytes=MAX_ENTRY_BYTES):
            try:
                yield OutboxEntry.model_validate(row)
            except ValidationError:
                continue
        for path in self.outbox.glob("*.json") if self.outbox.is_dir() else []:
            try:
                entry = self._read_entry(path)
            except (OSError, ValidationError):
                continue
            if f"{entry.id}.{entry.channel}" not in self._sent_keys():
                yield entry

    def tick(self) -> None:
        """
        Scan the event log, send due digests, then deliver what is due.

        A digest that fails (an unreadable project file, a full disk) is logged
        by its type name and tried again next tick; it never stops delivery of
        the notices already queued.
        """
        self.scan()
        try:
            self.digests()
        except Exception as exc:  # noqa: BLE001 - delivery must not wait on a digest
            log.warning("digest failed: %s", type(exc).__name__)
        self.deliver()

    def digests(self) -> list[str]:
        """
        Send this week's digest for every project whose time has come.

        Returns
        -------
        list of str
            Projects sent on this call; ``<home>/notify/digest.json`` records them.
        """
        cfg = self.settings.digest
        if not cfg.enabled:
            return []
        path = self.root / "digest.json"
        try:
            state: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if cfg.projects == "all":
            projects = [e.project for e in self.ctx.store.list_projects()]
        else:
            projects = list(cfg.projects)
        now = self.now()
        # the week's send time, not this tick's: a resend after a crash (before digest.json
        # below) has the same window, notice id, and notebook stamp, so it is queued once
        at = digest_due_at(cfg, now)
        sent: list[str] = []
        for project in projects:
            key = digest_due(cfg, state.get(project), now)
            if key is None:
                continue
            try:
                send_digest(self.ctx, self.settings, project, now=at)
            except StoreError:
                continue
            state[project] = key
            sent.append(project)
        if sent:
            write_private(path, json.dumps(state, indent=2, sort_keys=True))
        return sent

    def send_test(self, channel: Channel) -> dict[str, Any]:
        """
        Send a test notice on one channel now (not through the outbox).

        Parameters
        ----------
        channel : Channel

        Returns
        -------
        dict
            ``{"ok": bool, "error_class": str | None}``; the error class is
            redacted (``unset:<VAR>``, ``unconfigured``, ``http_404``, ...).
        """
        now = self.now()
        notice = test_notice(channel)
        entry = OutboxEntry(
            id=notice.id,
            channel=channel,
            notice=notice,
            status="sending",
            next_at=now,
            created_at=now,
        )
        try:
            self._send(entry)
        except _Skip as exc:
            return {"ok": False, "error_class": redact(exc.error_class, self.secret_values())}
        except ConfigError:
            return {"ok": False, "error_class": "secrets_file"}
        except ChannelError as exc:
            return {"ok": False, "error_class": redact(exc.error_class, self.secret_values())}
        return {"ok": True, "error_class": None}


def run_notifier_loop(ctx: Context, stop: threading.Event, *, interval: float = 5.0) -> None:
    """
    Run the notifier until ``stop`` is set (a thread in the hub's ``hx serve``).

    ``config.yaml`` is read again every tick, so edits apply without a restart.
    An error in one tick is logged by its type name only (it may quote a URL)
    and the loop goes on.

    Parameters
    ----------
    ctx : Context
        The hub's context.
    stop : threading.Event
    interval : float
        Seconds between ticks.
    """
    notifier: Notifier | None = None
    while not stop.is_set():
        try:
            settings = load_settings(ctx.layout)
            if notifier is None:
                notifier = Notifier(ctx, settings)
            else:
                notifier.settings = settings
            notifier.tick()
        except Exception as exc:  # noqa: BLE001 - the loop must outlive any one tick
            log.warning("notifier tick failed: %s", type(exc).__name__)
        stop.wait(interval)


def notify_status(ctx: Context, settings: Settings) -> dict[str, Any]:
    """
    Describe the notification setup without any secret value.

    Parameters
    ----------
    ctx : Context
    settings : Settings

    Returns
    -------
    dict
        ``{channels: {slack: {configured, env, set}, email: {configured, env, set,
        host, to}}, projects, default, digest, recent}``; ``set`` says whether the
        variable has a value.
    """

    def has_value(name: str | None) -> bool:
        if name is None:
            return False
        try:
            return resolve_secret(ctx.layout, name) is not None
        except ConfigError:
            return False

    slack, email = settings.notify.slack, settings.notify.email
    email_set = email is not None and (not email.username or has_value(email.password_env))
    channels: dict[str, Any] = {
        "slack": {
            "configured": slack is not None,
            "env": slack.webhook_env if slack else None,
            "set": has_value(slack.webhook_env) if slack else False,
        },
        "email": {
            "configured": email is not None,
            "env": email.password_env if email else None,
            "set": email_set,
            "host": email.host if email else None,
            "to": email.to if email else [],
        },
    }
    return {
        "channels": channels,
        "projects": {k: v.model_dump(mode="json") for k, v in settings.notify.projects.items()},
        "default": settings.notify.default.model_dump(mode="json")
        if settings.notify.default
        else None,
        "digest": settings.digest.model_dump(mode="json"),
        "recent": [e.model_dump(mode="json") for e in Notifier(ctx, settings).recent()],
    }
