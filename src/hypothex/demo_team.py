"""``hx demo --with-team``: a team hub for the phase 3 UI and its Playwright tests.

Seeds auth (owner ``sv``, collaborator ``alice``), notebook days with a weekly
summary, paper baselines, storage fixtures, outbox entries in every state, and a
shared fake host. ``demo_team_running`` (entered by ``hx serve``) starts a
loopback webhook and SMTP sink and writes fresh pairing links. All network
services bind to loopback; no external services are used.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socketserver
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal

import yaml

from hypothex.auth.pairing import pairing_url
from hypothex.auth.store import AuthStore, Principal
from hypothex.core.context import Context
from hypothex.core.digest import build_digest, render_digest_markdown
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout
from hypothex.core.notebook import append_entry
from hypothex.core.records import Artifact, RunKind, RunRecord, RunStatus
from hypothex.core.settings import (
    Channel,
    DigestSettings,
    EmailSettings,
    NotifySettings,
    ProjectRule,
    ServerSettings,
    Settings,
    SlackSettings,
    load_settings,
    save_settings,
    secrets_path,
    write_private,
)
from hypothex.core.storage import CleanItem, record_cleaned
from hypothex.demo import (
    _PLACEHOLDER_URL,
    DEMO_HOSTS_DIR,
    DEMO_HOSTS_FILE,
    DEMO_TASKS,
    _demo_host_home,
    _DemoHost,
    _prepare_demo_repository,
)
from hypothex.notify.messages import STATUS_GLYPH, Notice, notice_id
from hypothex.notify.notifier import NOTIFY_DIR, OutboxEntry
from hypothex.remote.config import HostSpec, load_hosts, save_hosts

TEAM_DIR = "demo-team"
TEAM_FILE = "team.json"
PAIRING_FILE = "pairing.json"
SLACK_ENV = "HX_DEMO_SLACK_WEBHOOK"
SHARED_TOKEN_ENV = "HX_DEMO_SHARED_TOKEN"
OWNER = "sv"
COLLABORATOR = "alice"
SHARED_HOST = "shared"
OWNER_PRINCIPAL = Principal(user=OWNER, scope="admin", session_id=None, client="local")


def _settings(ctx: Context, generic: str, training: str) -> None:
    email = EmailSettings(
        host="127.0.0.1",
        port=9,  # demo_team_running points it at the loopback sink
        security="none",
        password_env=None,
        sender="hx-demo@lab.org",
        to=["sv@lab.org", "alice@lab.org"],
    )
    rules = {
        generic: ProjectRule(channels=["slack", "email"], min_seconds=60),
        training: ProjectRule(channels=["slack"]),
    }
    save_settings(
        ctx.layout,
        Settings(
            server=ServerSettings(auth="on"),
            notify=NotifySettings(
                slack=SlackSettings(webhook_env=SLACK_ENV), email=email, projects=rules
            ),
            digest=DigestSettings(enabled=True, weekday="mon", hour=9, channels=["slack"]),
        ),
    )


def _users(ctx: Context) -> None:
    store = AuthStore(ctx.layout)
    store.ensure_owner(OWNER)
    if store.get_user(COLLABORATOR) is None:
        offer, secret = store.create_offer(
            issuer=OWNER_PRINCIPAL, user=COLLABORATOR, scope="launch"
        )
        session, _ = store.redeem(offer.id, secret, client="browser", device="demo")
        store.revoke(session.id, by=OWNER_PRINCIPAL)


def _baselines(ctx: Context, project: str, task: str) -> None:
    entry = ctx.store.load_project(project)
    path = Path(entry.repo) / "hypothex.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["tasks"][task]["baselines"] = [
        {
            "name": "SVC (Hsu 2003)",
            "values": {"accuracy": 0.9},
            "std": {"accuracy": 0.012},
            "source": "https://www.csie.ntu.edu.tw/~cjlin/papers/guide/guide.pdf",
            "metric_version_equivalent": {"accuracy": "v1"},
        },
        {
            "name": "Smith 2024",
            "values": {"accuracy": 0.93},
            "source": "arXiv:2401.01234",
            "metric_version_equivalent": {"accuracy": "v0"},
            "note": "reported on the v0 split",
        },
    ]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    ctx.register_project(Path(entry.repo))


def _blob(path: Path, megabytes: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(b"\x00" * (megabytes * 1_000_000))
    return path


def _storage_runs(ctx: Context, project: str, task: str) -> list[str]:
    now = utcnow()
    eid = ctx.descriptor.environment_id
    repo = ctx.store.load_project(project).repo

    def own(run_id: str) -> str:
        # the run's artifacts/: the only part of the Hypothex home cleanup may delete
        # (protected_reason), so <home>/demo-team/... would never be cleanable
        return str(ctx.layout.run_dir(project, run_id) / "artifacts" / "model.pt")

    def ended(
        run_id: str, days: int, owner: str, by: str, artifact: str | None, **extra: Any
    ) -> None:
        at = now - timedelta(days=days)
        digest = hashlib.sha256(run_id.encode()).hexdigest()[:16]
        ctx.create_run(
            RunRecord(
                run_id=run_id,
                project=project,
                task=task,
                command=["python", "train.py"],
                command_template=["python", "train.py"],
                cwd=repo,
                environment_id=eid,
                host=ctx.descriptor.label,
                config_hash=f"sha256:{digest}",
                status=RunStatus.FINISHED,
                created_at=at - timedelta(hours=2),
                started_at=at - timedelta(hours=2),
                ended_at=at,
                artifacts=[Artifact(kind="checkpoint", path=artifact)] if artifact else [],
                archived=extra.pop("archived", True),
                created_by=by,
                owner=owner,
                **extra,
            )
        )

    ended("st-a", 45, "sv", "human:sv", own("st-a"), hypothesis="wider MLP")
    ended("st-b", 60, "alice", "human:alice", own("st-b"), hypothesis="dropout 0.3")
    ended("st-prot", 50, "sv", "agent:claude@sv", repo, hypothesis="checkpoint saved into the repo")
    shared = own("st-parent")
    ended("st-parent", 70, "sv", "human:sv", shared, hypothesis="rbf kernel, C=10")
    ended(  # as control.reinfer writes it: the parent's checkpoint in vars, no artifact
        "st-child", 3, "alice", "human:alice", None, archived=False, parent="st-parent",
        kind=RunKind.INFER, vars={"checkpoint": shared}, hypothesis="Re-infer of st-parent",
    )  # fmt: skip
    ended("st-star", 80, "alice", "human:alice", own("st-star"), starred=True)
    for run_id, megabytes in (("st-a", 6), ("st-b", 4), ("st-parent", 5), ("st-star", 2)):
        _blob(Path(own(run_id)), megabytes)  # after create_run, which makes the run folder
    gone = own("st-done")  # cleaned: the file is not there
    ended("st-done", 90, "sv", "human:sv", gone, hypothesis="first baseline")
    item = CleanItem(
        project=project, run_id="st-done", host="local", environment_id=eid, kind="artifact",
        artifact_kind="checkpoint", path=gone, bytes=4_200_000_000, mtime=None,
        reason="archived 90d",
    )  # fmt: skip
    record_cleaned(ctx, "st-done", [item], actor="human:sv", plan_id="cp-0000d3e0")
    return ["st-a", "st-b", "st-prot", "st-parent", "st-star", "st-done"]


def _at(day: datetime, hour: int, minute: int) -> datetime:
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _notebook(ctx: Context, generic: str, training: str) -> list[str]:
    now = utcnow()
    yesterday = now - timedelta(days=1)
    runs = [
        r.run_id for r in ctx.index.list_runs(project=generic, status=RunStatus.FINISHED, limit=2)
    ]
    first, second = (runs + runs)[:2]
    append_entry(
        ctx, generic, f"svm still leads: [[run:{first}]] beats [[run:{second}]] on 9 items",
        "human:alice", now=_at(yesterday, 9, 14),
    )  # fmt: skip
    append_entry(ctx, generic, "next: sweep C for the rbf kernel, 3 seeds", "human:sv",
                 now=_at(yesterday, 16, 2))  # fmt: skip
    append_entry(
        ctx, generic, "[[run:st-parent]] checkpoint is still used by [[run:st-child]]; keep it",
        "agent:claude@sv", now=now,
    )  # fmt: skip
    digest = build_digest(ctx, generic, since=now - timedelta(days=7), until=now)
    append_entry(ctx, generic, render_digest_markdown(digest), "digest", now=now)
    trained = [r.run_id for r in ctx.index.list_runs(project=training, limit=1)]
    link = f" ([[run:{trained[0]}]])" if trained else ""
    append_entry(ctx, training, f"lr 3e-4 diverged at step 9000{link}; try warmup", "human:sv",
                 now=_at(yesterday, 11, 40))  # fmt: skip
    return sorted({now.astimezone().date().isoformat(), yesterday.astimezone().date().isoformat()})


def _outbox(ctx: Context, project: str, task: str) -> list[str]:
    root = ctx.layout.home / NOTIFY_DIR
    now = utcnow()
    later = now + timedelta(days=1)
    runs = ctx.index.list_runs(project=project, status=RunStatus.FINISHED, limit=5)
    plan: list[
        tuple[Channel, Literal["pending", "sending", "sent", "failed", "skipped"], int, str | None]
    ] = [
        ("slack", "sent", 1, None),
        ("email", "failed", 4, "smtp_451"),
        ("slack", "skipped", 1, f"unset:{SLACK_ENV}"),
        ("slack", "pending", 1, "http_429"),
        ("email", "sending", 0, None),
    ]
    finals: list[str] = []
    made: list[str] = []
    for i, (channel, status, attempts, error) in enumerate(plan):
        record = runs[i % len(runs)]
        state = "failed" if status == "failed" else "finished"
        when = now - timedelta(minutes=10 * (len(plan) - i))
        notice = Notice(
            id=notice_id("run", project, record.run_id, f"{state}:{i}"),
            kind="run",
            project=project,
            run_id=record.run_id,
            status=state,
            title=f"{STATUS_GLYPH[state]} {project}/{task} {record.run_id}",
            lines=[f"{record.created_by} · 0.4 GPU-h · $0.84 · 12m"],
            url=None,
            created_at=when,
        )
        entry = OutboxEntry(
            id=notice.id,
            channel=channel,
            notice=notice,
            status=status,
            attempts=attempts,
            next_at=later if status in ("pending", "sending") else when,
            last_error=error,
            created_at=when,
            sent_at=when if status == "sent" else None,
        )
        if status in ("pending", "sending"):
            write_private(
                root / "outbox" / f"{entry.id}.{channel}.json", entry.model_dump_json(indent=2)
            )
        else:
            finals.append(entry.model_dump_json())
        made.append(status)
    write_private(root / "sent.jsonl", "\n".join(finals) + "\n")
    write_private(root / "cursor.json", json.dumps({"last_sequence": ctx.events.last_sequence()}))
    return made


def _set_secret(layout: Layout, name: str, value: str) -> None:
    """Add or replace ``NAME=value`` in the hub's ``secrets.env`` (0600)."""
    path = secrets_path(layout)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    kept = [ln for ln in lines if ln.strip().removeprefix("export ").split("=", 1)[0] != name]
    write_private(path, "\n".join([*kept, f"{name}={value}"]) + "\n")


def _shared_host(ctx: Context, project: str) -> str:
    # a bearer token, as on a real lab server: the hub forwards as the host principal, so
    # the host keeps each run's owner (alice may stop the runs she launched there)
    _set_secret(ctx.layout, SHARED_TOKEN_ENV, secrets.token_urlsafe(32))
    root = ctx.layout.home / DEMO_HOSTS_DIR
    root.mkdir(parents=True, exist_ok=True)
    hub_repo = Path(ctx.store.load_project(project).repo)
    _prepare_demo_repository(hub_repo)
    host_ctx, repo = _demo_host_home(root, SHARED_HOST, hub_repo)
    marker = root / DEMO_HOSTS_FILE
    hosts = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else []
    hosts.append(
        _DemoHost(
            name=SHARED_HOST,
            kind="ssh",
            home=str(host_ctx.layout.home),
            repo=str(repo),
            token_env=SHARED_TOKEN_ENV,
        ).model_dump()
    )
    atomic_write_text(marker, json.dumps(hosts, indent=2))
    current = load_hosts(ctx.layout)
    spec = HostSpec(
        route="url",
        url=_PLACEHOLDER_URL,
        kind="ssh",
        usd_per_gpu_hour=0.9,
        projects={project: str(repo)},
        token_env=SHARED_TOKEN_ENV,
    )
    save_hosts(
        ctx.layout,
        current.model_copy(update={"environments": {**current.environments, SHARED_HOST: spec}}),
    )
    return SHARED_HOST


def seed_demo_team(home: Path) -> dict[str, Any]:
    """
    Seed the team fixtures next to the generic and training demos.

    Parameters
    ----------
    home : Path
        A home that already holds ``toy-classifier`` and ``rxn-forward``.

    Returns
    -------
    dict
        ``{users, storage_runs, notebook_days, outbox, host}``.

    Raises
    ------
    ConfigError
        The generic or training demo is missing.
    StoreError
        The team fixtures exist already.
    """
    ctx = Context.open(home.expanduser().resolve())
    generic, generic_task = DEMO_TASKS["generic"]
    training, _ = DEMO_TASKS["training"]
    for project in (generic, training):
        try:
            entry = ctx.store.load_project(project)
        except StoreError as exc:
            raise ConfigError(
                "--with-team needs the generic and training demos; add --kinds generic,training"
            ) from exc
        if Path(entry.repo).resolve() != (ctx.layout.home / "demo-repos" / project).resolve():
            raise ConfigError(f"--with-team requires the generated {project} demo repository")
    root = ctx.layout.home / TEAM_DIR
    if root.exists():
        raise StoreError(f"demo team already exists in {root}; seed into an empty HYPOTHEX_HOME")
    root.mkdir(parents=True)
    _settings(ctx, generic, training)
    _users(ctx)
    _baselines(ctx, generic, generic_task)
    made = {
        "users": {OWNER: "admin", COLLABORATOR: "launch"},
        "storage_runs": _storage_runs(ctx, generic, generic_task),
        "notebook_days": _notebook(ctx, generic, training),
        "outbox": _outbox(ctx, generic, generic_task),
        "host": _shared_host(ctx, generic),
    }
    atomic_write_text(root / TEAM_FILE, json.dumps(made, indent=2))
    return made


class _LoopbackHTTPServer(ThreadingHTTPServer):
    """Bind a demo webhook with a fixed local identity and no reverse DNS."""

    def server_bind(self) -> None:
        """Bind the socket and record its explicit local server identity."""
        socketserver.TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


class _Webhook:
    """A loopback Slack-like webhook that answers 200."""

    def __init__(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server's name
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        self.server = _LoopbackHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/services/DEMO/DEMO/demo"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _SmtpHandler(socketserver.StreamRequestHandler):
    """Just enough SMTP to accept a message (EHLO, MAIL, RCPT, DATA, QUIT)."""

    def handle(self) -> None:
        self.wfile.write(b"220 hx-demo ESMTP\r\n")
        data = False
        while line := self.rfile.readline():
            if data:
                if line in (b".\r\n", b".\n"):
                    data = False
                    self.wfile.write(b"250 OK\r\n")
                continue
            verb = line.strip().split(b" ", 1)[0].upper()
            if verb in (b"EHLO", b"HELO"):
                self.wfile.write(b"250 hx-demo\r\n")
            elif verb in (b"MAIL", b"RCPT", b"RSET", b"NOOP"):
                self.wfile.write(b"250 OK\r\n")
            elif verb == b"DATA":
                data = True
                self.wfile.write(b"354 end with .\r\n")
            elif verb == b"QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"502 not implemented\r\n")


class _Smtp:
    """A loopback SMTP sink for the demo's email channel."""

    def __init__(self) -> None:
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), _SmtpHandler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _links(layout: Layout, base_url: str) -> dict[str, str]:
    store = AuthStore(layout)
    out: dict[str, str] = {}
    for user, scope in ((OWNER, "admin"), (COLLABORATOR, "launch")):
        offer, secret = store.create_offer(issuer=OWNER_PRINCIPAL, user=user, scope=scope)  # type: ignore[arg-type]
        out[user] = pairing_url(base_url, offer.id, secret)
    return out


@contextmanager
def demo_team_running(home: Path, base_url: str) -> Iterator[dict[str, str]]:
    """
    Run the team demo's loopback channels and hand out fresh pairing links.

    Without ``<home>/demo-team/team.json`` this does nothing and yields ``{}``.

    Parameters
    ----------
    home : Path
        The hub's home.
    base_url : str
        Where browsers reach the hub (pairing links point there).

    Yields
    ------
    dict of str to str
        ``{"sv": link, "alice": link}``, also written to ``<home>/demo-team/pairing.json``.
    """
    if not (home / TEAM_DIR / TEAM_FILE).is_file():
        yield {}
        return
    layout = Layout(home.expanduser().resolve())
    with ExitStack() as resources:
        webhook = _Webhook()
        resources.callback(webhook.stop)
        smtp = _Smtp()
        resources.callback(smtp.stop)
        previous = os.environ.get(SLACK_ENV)
        os.environ[SLACK_ENV] = webhook.url
        try:
            settings = load_settings(layout)
            if settings.notify.email is not None:
                settings.notify.email = settings.notify.email.model_copy(update={"port": smtp.port})
                save_settings(layout, settings)
            links = _links(layout, base_url)
            write_private(layout.home / TEAM_DIR / PAIRING_FILE, json.dumps(links, indent=2))
            yield links
        finally:
            if previous is None:
                os.environ.pop(SLACK_ENV, None)
            else:
                os.environ[SLACK_ENV] = previous
