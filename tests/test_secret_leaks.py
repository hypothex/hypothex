"""Secret-leak scan (contract 9): no secret reaches a file, event, log line, answer, or output."""

import json
import logging
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hypothex.auth.pairing import parse_pairing_url
from hypothex.auth.store import parse_token
from hypothex.cli.main import app as cli
from hypothex.core.context import Context
from hypothex.core.execution import RunRequest, execute_run, prepare_run
from hypothex.core.records import RunStatus
from hypothex.core.settings import (
    EmailSettings,
    NotifySettings,
    ProjectRule,
    Settings,
    SlackSettings,
    save_settings,
)
from hypothex.notify.notifier import Notifier
from hypothex.remote.config import HostSpec
from tests.api.authkit import BASE, auth_app, bearer, token_for
from tests.api.envserver import write_hosts
from tests.factories import make_record
from tests.fakes.network import pg_child_environment
from tests.fakes.smtp import FakeSmtp
from tests.fakes.webhook import FakeWebhook, Reply

ALLOWED = {"secrets.env", "serve/server.json", "auth/hub-tokens.json", "auth/host-tokens.json"}
T0 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


def leaks(text: str, needles: list[str]) -> list[str]:
    return [n for n in needles if n and n in text]


def file_hits(home: Path, needles: list[str]) -> list[str]:
    hits: list[str] = []
    for path in home.rglob("*"):
        if not path.is_file() or path.relative_to(home).as_posix() in ALLOWED:
            continue
        data = path.read_bytes()
        hits += [f"{path.relative_to(home)}: {n[:12]}" for n in needles if n and n.encode() in data]
    return hits


def end(ctx: Context, run_id: str, status: RunStatus) -> None:
    ctx.create_run(
        make_record(run_id, status=RunStatus.RUNNING, started_at=T0 - timedelta(minutes=10),
                    environment_id=ctx.descriptor.environment_id)
    )  # fmt: skip
    ctx.update_run(
        run_id,
        f"run.{status.value}",
        lambda r: r.model_copy(update={"status": status, "ended_at": T0, "exit_code": 1}),
    )


def test_no_secret_reaches_any_file_event_log_or_output(
    home: Path, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    caplog.set_level(logging.DEBUG)
    password = "SECRETSMTP-" + secrets.token_hex(6)
    index_password = "SECRETPG-" + secrets.token_hex(6)
    hub_token = "SECRETHUB-" + secrets.token_hex(6)
    host_token = "SECRETHOST-" + secrets.token_hex(6)
    monkeypatch.setenv("HX_LEAK_SMTP", password)
    monkeypatch.setenv("HYPOTHEX_INDEX_PASSWORD", index_password)
    monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", hub_token)
    monkeypatch.setenv("HX_LEAK_HOST", host_token)
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    outputs: list[str] = []
    replies = [Reply(200), Reply(404), Reply(429, retry_after=1), Reply(500)]
    with FakeWebhook(replies) as hook, FakeSmtp(user="sv", password=password) as smtp:
        monkeypatch.setenv("HX_LEAK_HOOK", hook.url)
        email = EmailSettings(
            host="127.0.0.1", port=smtp.port, security="none", username="sv",
            password_env="HX_LEAK_SMTP", sender="hx@lab.org", to=["sv@lab.org"], timeout=1,
        )  # fmt: skip
        settings = Settings(
            notify=NotifySettings(
                slack=SlackSettings(webhook_env="HX_LEAK_HOOK"),
                email=email,
                projects={"toy": ProjectRule(channels=["slack", "email"])},
            )
        )
        save_settings(ctx.layout, settings)
        now = [T0 + timedelta(minutes=5)]
        notifier = Notifier(ctx, settings, now=lambda: now[0])
        notifier.scan()
        for run_id, status in (("a", RunStatus.FINISHED), ("b", RunStatus.FAILED),
                               ("c", RunStatus.LOST), ("d", RunStatus.KILLED)):  # fmt: skip
            end(ctx, run_id, status)
        notifier.scan()
        for _ in range(6):
            notifier.deliver()
            now[0] += timedelta(minutes=11)
        with FakeSmtp(user="sv", password="another-password") as wrong:  # SMTP 535
            settings.notify.email = email.model_copy(update={"port": wrong.port})
            end(ctx, "e", RunStatus.FAILED)
            notifier.scan()
            notifier.deliver()
        settings.notify.email = email
        lab = HostSpec(route="url", url="http://127.0.0.1:9", token_env="HX_LEAK_HOST")
        write_hosts(home, {"lab": lab})
        record = prepare_run(
            ctx,
            RunRequest(
                repo=toy_repo,
                command=[sys.executable, "-c", "import os; print(dict(os.environ))"],
            ),
        )
        # The environment-dump probe receives only synthetic credentials and the
        # test runtime's explicit settings, never unrelated shell credentials.
        probe_names = {
            "PATH",
            "TMPDIR",
            "LANG",
            "LC_ALL",
            "PYTHONPATH",
            "VIRTUAL_ENV",
            "HYPOTHEX_HOME",
            "HYPOTHEX_HUB_URL",
            "HYPOTHEX_HUB_TOKEN",
            "HYPOTHEX_INDEX_PASSWORD",
            "HYPOTHEX_SSH",
            "HYPOTHEX_SCP",
            "HYPOTHEX_TAILSCALE",
            "HX_LEAK_SMTP",
            "HX_LEAK_HOST",
            "HX_LEAK_HOOK",
        }
        with monkeypatch.context() as probe_env:
            for name in list(os.environ):
                if name not in probe_names:
                    probe_env.delenv(name)
            probe_env.setenv("HOME", str(tmp_path / "synthetic-user-home"))
            probe_env.setenv("USER", "synthetic-user")
            execute_run(ctx, record.run_id)
        write_hosts(home, {})  # the hub below has no host to dial
        app = auth_app(home)
        with TestClient(app, base_url=BASE) as client:
            admin = token_for(app.state.auth, "sv", "admin")
            offer = client.post(
                "/api/v1/auth/pairings", json={"user": "sv", "scope": "read"}, headers=bearer(admin)
            ).json()
            _, offer_id, pairing_secret = parse_pairing_url(offer["url"])
            paired = client.post(
                "/api/v1/auth/pair",
                json={"offer_id": offer_id, "secret": pairing_secret, "client": "cli"},
            ).json()
            parts = parse_token(paired["token"])
            assert parts is not None
            session_secret = parts[1]
            for resp in (
                client.get("/api/v1/notify", headers=bearer(admin)),
                client.post(
                    "/api/v1/notify/test", json={"channel": "slack"}, headers=bearer(admin)
                ),
                client.post(
                    "/api/v1/notify/test", json={"channel": "email"}, headers=bearer(admin)
                ),
                client.get("/api/v1/auth/me", headers=bearer(paired["token"])),
                client.get("/api/v1/auth/sessions", headers=bearer(admin)),
            ):
                assert resp.status_code == 200
                outputs.append(resp.text)
        runner = CliRunner()
        with monkeypatch.context() as local_cli:
            local_cli.delenv("HYPOTHEX_HUB_URL", raising=False)
            for args in (
                ["notify", "status", "--json"],
                ["notify", "test", "slack", "--json"],
                ["notify", "test", "email", "--json"],
            ):
                result = runner.invoke(cli, ["--home", str(home), *args])
                assert result.exit_code == 0, type(result.exception).__name__
                if args[1] == "test":
                    assert json.loads(result.stdout) == {"ok": True, "error_class": None}
                outputs.append(result.output)
    file_secret = "SECRETFILE-" + secrets.token_hex(6)
    bad_home = tmp_path / "bad-home"
    bad_home.mkdir()
    (bad_home / "secrets.env").write_text(f"HYPOTHEX_SLACK_WEBHOOK={file_secret}\n")
    (bad_home / "secrets.env").chmod(0o640)
    start = subprocess.run(
        [
            sys.executable,
            "-m",
            "hypothex.cli.main",
            "--home",
            str(bad_home),
            "serve",
            "--port",
            "0",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=pg_child_environment(dict(os.environ)),
    )
    assert start.returncode == 1
    outputs += [start.stdout, start.stderr]
    needles = [
        hook.secret, hook.url, password, index_password, file_secret, pairing_secret,
        session_secret, hub_token, host_token,
    ]  # fmt: skip
    events = "\n".join(e.model_dump_json() for e in ctx.events.since(0, limit=100_000))
    assert file_hits(home, needles) == []
    assert leaks(events, needles) == []
    assert leaks(caplog.text, needles) == []
    assert leaks("\n".join(outputs), needles) == []
    statuses = {e.status for e in notifier.recent(limit=100)}
    assert {"sent", "failed"} <= statuses  # the scenario really went through both paths
