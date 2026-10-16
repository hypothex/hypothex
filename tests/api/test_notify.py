import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hypothex.api import app as app_module
from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.records import RunStatus
from hypothex.core.settings import (
    NotifySettings,
    ProjectRule,
    Settings,
    SlackSettings,
    save_settings,
)
from tests.api.authkit import BASE, auth_app, bearer, token_for
from tests.api.envserver import wait_until
from tests.factories import make_record
from tests.fakes.webhook import FakeWebhook


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeWebhook]:
    with FakeWebhook() as fake:
        monkeypatch.setenv("HX_TEST_HOOK", fake.url)
        yield fake


def slack_settings() -> Settings:
    return Settings(
        notify=NotifySettings(
            slack=SlackSettings(webhook_env="HX_TEST_HOOK"),
            projects={"toy": ProjectRule(channels=["slack"])},
        )
    )


def test_notify_status_never_returns_a_secret(home: Path, hook: FakeWebhook) -> None:
    save_settings(Context.open(home).layout, slack_settings())
    app = auth_app(home)
    with TestClient(app, base_url=BASE) as client:
        admin = bearer(token_for(app.state.auth, "sv", "admin"))
        status = client.get("/api/v1/notify", headers=admin)
        launcher = bearer(token_for(app.state.auth, "alice", "launch"))
        assert client.get("/api/v1/notify", headers=launcher).status_code == 403
    body = status.json()
    assert body["channels"]["slack"] == {"configured": True, "env": "HX_TEST_HOOK", "set": True}
    assert body["channels"]["email"]["configured"] is False
    assert body["projects"]["toy"]["channels"] == ["slack"] and body["recent"] == []
    assert hook.secret not in status.text and os.environ["HX_TEST_HOOK"] not in status.text


def test_notify_test_sends_now(
    home: Path, hook: FakeWebhook, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_settings(Context.open(home).layout, slack_settings())
    app = auth_app(home)
    with TestClient(app, base_url=BASE) as client:
        admin = bearer(token_for(app.state.auth, "sv", "admin"))
        ok = client.post("/api/v1/notify/test", json={"channel": "slack"}, headers=admin).json()
        assert ok == {"ok": True, "error_class": None}
        assert hook.requests[0]["body"]["text"] == "✓ hypothex test · slack"
        monkeypatch.delenv("HX_TEST_HOOK")
        unset = client.post("/api/v1/notify/test", json={"channel": "slack"}, headers=admin).json()
        assert unset == {"ok": False, "error_class": "unset:HX_TEST_HOOK"}
        email = client.post("/api/v1/notify/test", json={"channel": "email"}, headers=admin).json()
        assert email == {"ok": False, "error_class": "unconfigured"}


def test_hub_runs_the_notifier_thread(
    home: Path, hook: FakeWebhook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "NOTIFY_INTERVAL_SECONDS", 0.05)
    ctx = Context.open(home)
    save_settings(ctx.layout, slack_settings())
    app = create_app(home, background_repair=False, hub=False, notifier=True, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE):
        wait_until(lambda: (ctx.layout.home / "notify" / "cursor.json").exists(), timeout=10)
        ctx.create_run(make_record("n1", environment_id=ctx.descriptor.environment_id))
        ctx.update_run(
            "n1",
            "run.failed",
            lambda r: r.model_copy(update={"status": RunStatus.FAILED, "ended_at": r.created_at}),
        )
        wait_until(lambda: hook.requests, timeout=10)
    assert hook.requests[0]["body"]["text"].startswith("✗ toy/t n1")


def test_notifier_is_off_without_background_loops(home: Path) -> None:
    app = create_app(home, background_repair=False, hub=False, ui_dir=home / "no-ui")
    with TestClient(app, base_url=BASE):
        pass
    assert not (home / "notify" / "cursor.json").exists()


@pytest.mark.parametrize("kind", ["ssh", "slurm"])
def test_environment_servers_never_run_notifier(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """An env server cannot accidentally become a second delivery loop."""
    monkeypatch.setattr(
        app_module, "run_notifier_loop", lambda *a, **k: pytest.fail("env notifier")
    )
    app = create_app(
        home, background_repair=False, hub=False, notifier=True, kind=kind, ui_dir=home / "no-ui"
    )
    with TestClient(app, base_url=BASE):
        pass
    assert not (home / "notify" / "cursor.json").exists()
