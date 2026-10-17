import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from hypothex.cli.main import app, parse_duration
from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from hypothex.core.ids import utcnow
from hypothex.core.records import Artifact, RunStatus
from hypothex.core.settings import NotifySettings, Settings, SlackSettings, save_settings
from hypothex.core.storage import fmt_bytes
from tests.factories import PREDS_075, make_record, seed_finished_run
from tests.fakes.webhook import FakeWebhook

runner = CliRunner()
PREDS_025 = [{"id": f"ex-{i}", "prediction": 1} for i in range(4)]


def hx(*args: str, input: str | None = None) -> Any:
    result = runner.invoke(app, [*args, "--json"], input=input, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def text(*args: str) -> str:
    result = runner.invoke(app, list(args), catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result.stdout


@pytest.fixture
def scored(ctx: Context, toy_repo: Path) -> Context:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "r2", predictions=PREDS_025, config_hash="sha256:bbbb")
    evaluate_run(ctx, "r1")
    evaluate_run(ctx, "r2")
    return ctx


def test_parse_duration() -> None:
    assert parse_duration("30d") == timedelta(days=30)
    assert parse_duration("12h") == timedelta(hours=12)
    assert parse_duration("2w") == timedelta(days=14)
    with pytest.raises(Exception, match="30d"):
        parse_duration("soon")


def test_export_a_task(scored: Context, tmp_path: Path) -> None:
    md = text("export", "toy-acc")
    assert md.startswith("| group | n | accuracy/value ↑ |")
    out = hx("export", "toy-acc", "--format", "latex", "--digits", "2")
    assert out["format"] == "latex" and out["text"].startswith("% requires")
    assert [r["kind"] for r in out["table"]["rows"]] == ["group", "group"]
    target = tmp_path / "table.csv"
    assert (
        text("export", "toy/toy-acc", "--format", "csv", "-o", str(target)).strip()
        == f"wrote {target}"
    )
    assert target.read_text().startswith("kind,label,key,n,metric")


def test_export_runs(scored: Context) -> None:
    out = hx("export", "--runs", "r1,r2")
    assert out["text"].splitlines()[2] == "| r1 | 1 | **0.750** |"
    result = runner.invoke(app, ["export"])
    assert result.exit_code == 1 and "give a task, or --runs" in str(result.exception)


def test_note_to_the_project_notebook(scored: Context) -> None:
    day = hx("note", "--project", "toy", "r1 beats r2 [[run:r1]]", "--day", "2026-10-04")
    assert day["day"] == "2026-10-04" and "— human" in day["text"]
    hx("note", "r1", "a run note")  # phase 1 form still works
    assert "a run note" in scored.store.read_notes("toy", "r1")


def test_notebook_list_and_show(scored: Context) -> None:
    hx("note", "--project", "toy", "see [[run:r1]]", "--day", "2026-10-04")
    assert hx("notebook", "list", "-p", "toy")[0]["day"] == "2026-10-04"
    shown = hx("notebook", "show", "-p", "toy", "--day", "2026-10-04")
    assert shown["runs"][0]["run_id"] == "r1"
    rendered = text("notebook", "show", "-p", "toy", "--day", "2026-10-04")
    assert "see [[run:r1]]" in rendered and "r1" in rendered.splitlines()[-1]


def test_digest_prints_and_sends_locally(scored: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HX_TEST_HOOK", "http://127.0.0.1:9/services/T/B/x")
    save_settings(
        scored.layout,
        Settings(notify=NotifySettings(slack=SlackSettings(webhook_env="HX_TEST_HOOK"))),
    )
    (digest,) = hx("digest", "-p", "toy", "--since", "7d")
    assert digest["digest"]["counts"]["started"] == 2 and digest["sent"] is None
    assert text("digest", "-p", "toy").startswith("**")
    (sent,) = hx("digest", "-p", "toy", "--send")
    assert sent["sent"]["channels"] == ["slack"]
    assert list((scored.layout.home / "notify" / "outbox").glob("*.slack.json"))


def archived(ctx: Context, run_id: str, artifact: Path) -> None:
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"x" * 30_000)
    ended = utcnow() - timedelta(days=40)
    ctx.create_run(
        make_record(
            run_id,
            status=RunStatus.FINISHED,
            archived=True,
            started_at=ended,
            ended_at=ended,
            artifacts=[Artifact(kind="checkpoint", path=str(artifact))],
            environment_id=ctx.descriptor.environment_id,
        )
    )


def test_fmt_bytes() -> None:
    assert [fmt_bytes(n) for n in (512, 4096, 412_300_000_000, 1_840_000_000_000)] == [
        "512 B",
        "4.1 KB",
        "412.3 GB",
        "1.8 TB",
    ]


def test_notify_status_and_test(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    with FakeWebhook() as hook:
        monkeypatch.setenv("HX_TEST_HOOK", hook.url)
        save_settings(
            ctx.layout,
            Settings(notify=NotifySettings(slack=SlackSettings(webhook_env="HX_TEST_HOOK"))),
        )
        status = hx("notify", "status")
        assert status["channels"]["slack"] == {
            "configured": True,
            "env": "HX_TEST_HOOK",
            "set": True,
        }
        shown = text("notify", "status")
        assert "slack ● set HX_TEST_HOOK" in shown and hook.secret not in shown
        assert hx("notify", "test", "slack") == {"ok": True, "error_class": None}
        assert hook.requests[0]["body"]["text"] == "✓ hypothex test · slack"
        monkeypatch.delenv("HX_TEST_HOOK")
        result = runner.invoke(app, ["notify", "test", "slack"])
        assert result.exit_code == 1 and "✗ slack unset:HX_TEST_HOOK" in result.stdout


def test_storage_report(ctx: Context, tmp_path: Path) -> None:
    archived(ctx, "old", tmp_path / "scratch" / "old.pt")
    report = hx("storage", "report", "--local-only")
    assert report["total_bytes"] > 0 and report["errors"] == []
    shown = text("storage", "report")
    assert shown.splitlines()[0].endswith("items") and "old.pt" in shown


def test_storage_clean_plans_then_applies(ctx: Context, tmp_path: Path) -> None:
    artifact = tmp_path / "scratch" / "old.pt"
    archived(ctx, "old", artifact)
    refused = runner.invoke(app, ["storage", "clean"])
    assert refused.exit_code == 1 and "--archived" in str(refused.exception)
    plan = hx("storage", "clean", "--archived", "--older-than", "30d", "--dry-run")
    assert [i["run_id"] for i in plan["items"]] == ["old"] and artifact.exists()
    shown = text("storage", "clean", "--archived")
    assert "hx storage clean --apply cp-" in shown
    wrong = runner.invoke(app, ["storage", "clean", "--apply", plan["plan_id"]], input="1\n")
    assert wrong.exit_code == 1 and "not confirmed" in str(wrong.exception) and artifact.exists()
    typed = f"{plan['total_bytes']}\n"
    done = runner.invoke(
        app, ["storage", "clean", "--apply", plan["plan_id"], "--json"], input=typed
    )
    assert done.exit_code == 0, done.output
    payload = done.stdout[done.stdout.index("{") :]  # the prompt line comes first
    assert json.loads(payload)["freed_bytes"] == plan["total_bytes"]
    assert not artifact.exists()


def test_apply_needs_a_known_total(ctx: Context) -> None:
    result = runner.invoke(app, ["storage", "clean", "--apply", "cp-0000000a", "--yes"])
    assert result.exit_code == 1 and "--confirm-bytes" in str(result.exception)


def test_export_selected_primary_local_and_http(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The selected primary ranks actual rows and reaches the client HTTP request."""
    from urllib.parse import parse_qs, urlsplit

    import httpx

    from hypothex.auth.client import HubLogin, save_hub_login
    from tests.core.test_backlog_backend import indexed

    indexed(ctx, toy_repo)
    default = hx("export", "toy/t")
    selected = hx("export", "toy/t", "--primary", "latency/p95", "--metrics", "acc/value")
    assert default["table"]["rows"][0]["key"] != selected["table"]["rows"][0]["key"]
    assert selected["table"]["columns"] == ["acc/value"]
    result = runner.invoke(app, ["export", "--runs", "a,b", "--primary", "latency/p95"])
    assert result.exit_code == 1 and "--primary" in str(result.exception)
    base = "http://127.0.0.1:19990"
    monkeypatch.setenv("HYPOTHEX_HUB_URL", base)
    save_hub_login(
        ctx.layout,
        base,
        HubLogin(token="client-token", user="alice", scope="read", session_id="s_client"),
    )
    calls: list[str] = []

    def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        assert method == "GET"
        assert kwargs["headers"]["Authorization"] == "Bearer client-token"
        parts = urlsplit(url)
        assert parts.path == "/api/v1/tasks/toy/t/export"
        assert parse_qs(parts.query)["primary"] == ["latency/p95"]
        assert parse_qs(parts.query)["metrics"] == ["acc/value"]
        calls.append(url)
        return httpx.Response(200, text="selected table\n")

    monkeypatch.setattr("hypothex.mcp.server._hub_request", request)
    out = hx("export", "toy/t", "--primary", "latency/p95", "--metrics", "acc/value")
    assert out == {"format": "markdown", "text": "selected table\n", "table": None}
    assert len(calls) == 1
    result = runner.invoke(app, ["export", "--runs", "a,b", "--primary", "latency/p95"])
    assert result.exit_code == 1 and len(calls) == 1
