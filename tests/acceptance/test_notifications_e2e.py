"""Real daemon outbox delivery to loopback SMTP/webhook receivers, including restart."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from hypothex.core.context import Context
from hypothex.core.notebook import append_entry
from hypothex.core.records import CostTotals, RunRecord, RunStatus
from hypothex.core.settings import (
    DigestSettings,
    EmailSettings,
    NotifySettings,
    ProjectRule,
    ServerSettings,
    Settings,
    SlackSettings,
    save_settings,
)
from hypothex.core.sweeps import SweepParam, SweepSpec, save_sweep, sweep_tag
from tests.acceptance.conftest import LiveServer, run_cli
from tests.api.envserver import wait_until
from tests.factories import make_record, write_toy_project
from tests.fakes.smtp import FakeSmtp
from tests.fakes.webhook import FakeWebhook


def end_run(ctx: Context, run_id: str, status: RunStatus, ended: datetime) -> None:
    """Publish a real terminal event and indexed record through Context."""

    def change(record: RunRecord) -> RunRecord:
        return record.model_copy(
            update={
                "status": status,
                "ended_at": ended,
                "exit_code": 1 if status == RunStatus.FAILED else 0,
            }
        )

    ctx.update_run(run_id, f"run.{status.value}", change)


def mail_body(message: Any) -> str:
    """Decode the actual delivered MIME text body."""
    return "\n".join(message.get_content().splitlines()).strip()


def test_actual_notifier_delivers_once_folds_200_and_digests_survive_restart(
    tmp_path: Path,
) -> None:
    home = tmp_path / "notify-home"
    ctx = Context.open(home)
    ctx.register_project(write_toy_project(tmp_path / "repo"))
    now = datetime.now(UTC)
    # Before this week's scheduled digest boundary, within the notification age window.
    stamp = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=30)
    eid = ctx.descriptor.environment_id
    password = "synthetic-smtp-acceptance-password"
    with FakeWebhook() as hook, FakeSmtp(user="receiver", password=password) as smtp:
        settings = Settings(
            server=ServerSettings(auth="on"),
            notify=NotifySettings(
                slack=SlackSettings(webhook_env="HX_ACCEPTANCE_WEBHOOK"),
                email=EmailSettings(
                    host="127.0.0.1",
                    port=smtp.port,
                    security="none",
                    username="receiver",
                    password_env="HX_ACCEPTANCE_SMTP_PASSWORD",
                    sender="hx@lab.invalid",
                    to=["owner@lab.invalid"],
                ),
                projects={"toy": ProjectRule(channels=["slack", "email"])},
                max_age_hours=48,
            ),
        )
        save_settings(ctx.layout, settings)
        with LiveServer(
            home,
            ("--auth",),
            {
                "HX_ACCEPTANCE_WEBHOOK": hook.url,
                "HX_ACCEPTANCE_SMTP_PASSWORD": password,
            },
        ) as daemon:
            wait_until(lambda: (home / "notify" / "cursor.json").exists(), timeout=15)
            # Adding public_url while running exercises actual per-tick settings reload.
            settings.server.public_url = daemon.url
            save_settings(ctx.layout, settings)
            for run_id, status, project in [
                ("finished-one", RunStatus.FINISHED, "toy"),
                ("failed-one", RunStatus.FAILED, "toy"),
                ("lost-one", RunStatus.LOST, "toy"),
                ("unsubscribed", RunStatus.FAILED, "other"),
            ]:
                ctx.create_run(
                    make_record(
                        run_id,
                        project=project,
                        task="toy-acc",
                        environment_id=eid,
                        created_at=stamp,
                        started_at=stamp,
                        created_by="human:alice",
                        cost=CostTotals(gpu_hours=2, total_usd=0, gpu_pricing_complete=False),
                    )
                )
                if status == RunStatus.FAILED:
                    path = ctx.run_dir(ctx.find_record(run_id)) / "logs" / "stderr.log"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"delivery context {hook.url} {password}\n")
                end_run(ctx, run_id, status, stamp + timedelta(seconds=30))
            spec = SweepSpec(
                id="s-acceptance200",
                project="toy",
                task="toy-acc",
                host=None,
                grid=[SweepParam(name="x", values=[str(i) for i in range(200)])],
                seeds=[1],
                command_template=["echo", "{x}"],
                created_by="human:alice",
                created_at=stamp,
            )
            save_sweep(ctx.layout, spec)
            tag = sweep_tag(eid, spec.id)
            for index in range(200):
                ctx.create_run(
                    make_record(
                        f"sweep-{index:03d}",
                        task="toy-acc",
                        environment_id=eid,
                        created_at=stamp,
                        started_at=stamp,
                        tags=[tag],
                        sweep_id=spec.id,
                    )
                )
            for index in range(200):
                end_run(
                    ctx, f"sweep-{index:03d}", RunStatus.FINISHED, stamp + timedelta(seconds=45)
                )
            wait_until(lambda: len(hook.requests) >= 4 and len(smtp.received) >= 4, timeout=30)
            assert len(hook.requests) == len(smtp.received) == 4
            slack = {
                entry["body"]["text"].splitlines()[0]: entry["body"]["text"]
                for entry in hook.requests
            }
            email = {
                str(entry.message["Subject"]): mail_body(entry.message) for entry in smtp.received
            }
            assert set(slack) == set(email)
            assert sorted(title.split()[0] for title in slack) == ["?", "✓", "✓", "✗"]
            assert sum("sweep s-acceptance200 200/200" in title for title in slack) == 1
            assert not any("unsubscribed" in body or "other/" in body for body in slack.values())
            for title, body in slack.items():
                if "sweep" not in title:
                    assert "Cost unknown · $0.00 recorded" in body
                    assert "Cost unknown · $0.00 recorded" in email[title]
                    assert "human:alice" in body
                    assert daemon.url + "/r/" in body
                assert hook.secret not in body and password not in body
                assert hook.secret not in email[title] and password not in email[title]
                assert body.split("\n", 1)[1].strip() == email[title]
            assert all(
                entry.mail_from == "hx@lab.invalid" and entry.rcpt_tos == ["owner@lab.invalid"]
                for entry in smtp.received
            )
            # Historical findings belong in the scheduled week; current client notes
            # separately prove API/CLI round trips and run-chip resolution.
            append_entry(
                ctx,
                "toy",
                "historical finding [[run:finished-one]]",
                "human:alice",
                day=stamp.date(),
                now=stamp,
            )
            environment = {"HYPOTHEX_HUB_URL": daemon.url, "HYPOTHEX_HUB_TOKEN": daemon.token}
            run_cli(
                home,
                "note",
                "--project",
                "toy",
                "current finding [[run:finished-one]]",
                environment=environment,
            )
            with httpx.Client(
                base_url=daemon.url, headers={"Authorization": f"Bearer {daemon.token}"}, timeout=10
            ) as client:
                today = client.get("/api/v1/projects/toy/notebook/today")
                assert today.status_code == 200, today.text
                assert "current finding" in today.json()["text"]
                assert today.json()["runs"][0]["run_id"] == "finished-one"
            settings.digest = DigestSettings(
                enabled=True,
                weekday=now.strftime("%a").lower(),
                hour=0,
                timezone="UTC",
                channels=["slack", "email"],
                projects=["toy"],
                save_to_notebook=True,
            )
            save_settings(ctx.layout, settings)
            wait_until(lambda: len(hook.requests) >= 5 and len(smtp.received) >= 5, timeout=20)
            assert len(hook.requests) == len(smtp.received) == 5
            digest_slack = hook.requests[-1]["body"]["text"]
            digest_mail = smtp.received[-1].message
            assert str(digest_mail["Subject"]) == digest_slack.splitlines()[0]
            assert "historical finding" in digest_slack and "historical finding" in mail_body(
                digest_mail
            )
            assert "Cost unknown" in digest_slack
            assert "Cost unknown" in str(digest_mail["Subject"])
            # Resolve through API instead of depending on configured store location.
            notebook = httpx.get(
                daemon.url + "/api/v1/projects/toy/notebook/today",
                headers={"Authorization": f"Bearer {daemon.token}"},
            ).json()
            assert "historical finding" in notebook["text"]
            before_text = notebook["text"]
            before_cursor = json.loads((home / "notify" / "cursor.json").read_text())[
                "last_sequence"
            ]
            daemon.stop()
            daemon.start()
            # Force observable progress on a non-notifying event after restart.
            ctx.events.append("notebook.updated", project="toy", payload={"day": str(now.date())})
            wait_until(
                lambda: (
                    json.loads((home / "notify" / "cursor.json").read_text())["last_sequence"]
                    > before_cursor
                ),
                timeout=15,
            )
            assert len(hook.requests) == len(smtp.received) == 5
            after = httpx.get(
                daemon.url + "/api/v1/projects/toy/notebook/today",
                headers={"Authorization": f"Bearer {daemon.token}"},
            ).json()
            assert after["text"] == before_text
            # Scan notification persistence, not the intentional private source secret stores.
            for path in (home / "notify").rglob("*"):
                if path.is_file():
                    content = path.read_bytes()
                    assert hook.secret.encode() not in content and password.encode() not in content
