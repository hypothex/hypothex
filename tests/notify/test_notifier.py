import fcntl
import json
import stat
import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

import hypothex.core.notebook as notebook_module
from hypothex.core.context import Context
from hypothex.core.events import Event
from hypothex.core.fsutil import read_jsonl
from hypothex.core.notebook import append_entry, read_day
from hypothex.core.records import RunRecord, RunStatus
from hypothex.core.settings import (
    DigestSettings,
    EmailSettings,
    NotifySettings,
    ProjectRule,
    Settings,
    SlackSettings,
)
from hypothex.core.sweeps import (
    SweepParam,
    SweepSpec,
    save_sweep,
    sweep_issuing,
    sweep_path,
    sweep_tag,
)
from hypothex.notify.notifier import Notifier, OutboxEntry, run_notifier_loop
from tests.factories import make_record
from tests.fakes.smtp import FakeSmtp
from tests.fakes.webhook import FakeWebhook, Reply

T0 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.t = T0 + timedelta(hours=1)

    def __call__(self) -> datetime:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeWebhook]:
    with FakeWebhook() as fake:
        monkeypatch.setenv("HX_TEST_HOOK", fake.url)
        yield fake


@pytest.fixture
def smtp() -> Iterator[FakeSmtp]:
    with FakeSmtp() as fake:
        yield fake


@pytest.fixture
def toy(ctx: Context, toy_repo: Path) -> Context:
    ctx.register_project(toy_repo)
    return ctx


def settings_for(
    smtp: FakeSmtp | None = None,
    *,
    project: str = "toy",
    default: ProjectRule | None = None,
    **rule: object,
) -> Settings:
    email = None
    if smtp is not None:
        email = EmailSettings(
            host="127.0.0.1",
            port=smtp.port,
            security="none",
            password_env=None,
            sender="hx@lab.org",
            to=["sv@lab.org"],
            timeout=5,
        )
    channels = ["slack", "email"] if smtp is not None else ["slack"]
    return Settings(
        notify=NotifySettings(
            slack=SlackSettings(webhook_env="HX_TEST_HOOK"),
            email=email,
            projects={project: ProjectRule.model_validate({"channels": channels, **rule})},
            default=default,
        )
    )


def end_run(
    ctx: Context,
    run_id: str,
    status: str,
    *,
    minutes: float = 10,
    ended: datetime = T0,
    project: str = "toy",
    tags: list[str] | None = None,
    sweep_id: str | None = None,
) -> RunRecord:
    ctx.create_run(
        make_record(
            run_id,
            project=project,
            task="toy-acc",
            status=RunStatus.RUNNING,
            started_at=ended - timedelta(minutes=minutes),
            environment_id=ctx.descriptor.environment_id,
            tags=tags or [],
            sweep_id=sweep_id,
        )
    )
    return ctx.update_run(
        run_id,
        f"run.{status}",
        lambda r: r.model_copy(
            update={"status": RunStatus(status), "ended_at": ended, "exit_code": 0}
        ),
    )


def primed(ctx: Context, settings: Settings, clock: Clock) -> Notifier:
    notifier = Notifier(ctx, settings, now=clock)
    assert notifier.scan() == []  # first start: cursor at the end of the log
    return notifier


def test_first_start_skips_the_backlog(toy: Context, hook: FakeWebhook, clock: Clock) -> None:
    end_run(toy, "old", "finished")
    notifier = primed(toy, settings_for(), clock)
    assert json.loads((toy.layout.home / "notify" / "cursor.json").read_text()) == {
        "last_sequence": toy.events.last_sequence()
    }
    end_run(toy, "new", "finished")
    (entry,) = notifier.scan()
    assert entry.notice.run_id == "new" and entry.channel == "slack" and entry.status == "pending"


def test_each_ending_enqueues_once_per_channel(
    toy: Context, hook: FakeWebhook, smtp: FakeSmtp, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(smtp), clock)
    for run_id, status in (("a", "finished"), ("b", "failed"), ("c", "lost")):
        end_run(toy, run_id, status)
    made = notifier.scan()
    assert sorted((e.notice.run_id, e.channel) for e in made) == [
        ("a", "email"), ("a", "slack"), ("b", "email"), ("b", "slack"), ("c", "email"),
        ("c", "slack"),
    ]  # fmt: skip
    assert notifier.scan() == []
    toy.events.append("run.lost", project="toy", run_id="c", payload={})  # a repeated event
    assert notifier.scan() == []


def test_unlisted_projects_get_nothing_unless_a_default(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(project="other"), clock)
    end_run(toy, "a", "failed")
    assert notifier.scan() == []
    notifier.settings = settings_for(project="other", default=ProjectRule())
    end_run(toy, "b", "failed")
    assert [e.notice.run_id for e in notifier.scan()] == ["b"]


def test_events_and_min_seconds(toy: Context, hook: FakeWebhook, clock: Clock) -> None:
    notifier = primed(toy, settings_for(events=["finished", "failed"], min_seconds=600), clock)
    end_run(toy, "short", "finished", minutes=5)
    end_run(toy, "long", "finished", minutes=10)
    end_run(toy, "crash", "failed", minutes=1)
    end_run(toy, "gone", "lost")
    assert sorted(e.notice.run_id for e in notifier.scan()) == ["crash", "long"]


def test_mirrored_runs_notify_from_the_mirror_event(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(), clock)
    toy.create_run(
        make_record(
            "remote1",
            task="toy-acc",
            status=RunStatus.FAILED,
            environment_id="env-gpu1",
            started_at=T0 - timedelta(minutes=3),
            ended_at=T0,
        )
    )
    toy.events.append(
        "mirror.run_updated",
        project="toy",
        run_id="remote1",
        payload={"host": "gpu1", "original_type": "run.started", "status": "running"},
    )
    assert notifier.scan() == []
    toy.events.append(
        "mirror.run_updated",
        project="toy",
        run_id="remote1",
        payload={"host": "gpu1", "original_type": "run.failed", "status": "failed"},
    )
    (entry,) = notifier.scan()
    assert entry.notice.run_id == "remote1" and entry.notice.status == "failed"


def test_runs_that_ended_long_ago_are_skipped(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "late", "finished", ended=clock() - timedelta(hours=25))
    assert notifier.scan() == []


def test_sweep_gives_one_notice_when_its_last_run_ends(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    spec = SweepSpec(
        id="s-0001",
        project="toy",
        task="toy-acc",
        host=None,
        grid=[SweepParam(name="x", values=[str(i) for i in range(200)])],
        seeds=[1],
        command_template=["echo", "{x}"],
        created_by="human:sv",
        created_at=T0,
    )
    save_sweep(toy.layout, spec)
    tag = sweep_tag(toy.descriptor.environment_id, spec.id)
    notifier = primed(toy, settings_for(), clock)
    for i in range(200):
        toy.create_run(
            make_record(
                f"sw{i:03d}",
                task="toy-acc",
                status=RunStatus.QUEUED,
                environment_id=toy.descriptor.environment_id,
                tags=[tag],
                sweep_id=spec.id,
            )
        )
    for i in range(199):
        status = RunStatus.FAILED if i % 50 == 0 else RunStatus.FINISHED
        toy.update_run(
            f"sw{i:03d}",
            f"run.{status.value}",
            lambda r, s=status: r.model_copy(update={"status": s, "ended_at": T0}),
        )
    assert notifier.scan() == []  # one run still queued
    toy.update_run(
        "sw199",
        "run.finished",
        lambda r: r.model_copy(update={"status": RunStatus.FINISHED, "ended_at": T0}),
    )
    (entry,) = notifier.scan()
    assert entry.notice.kind == "sweep" and entry.notice.title == "✗ toy sweep s-0001 200/200"
    assert entry.notice.lines[0].startswith("✓196 ✗4 ?0 ⊘0")


def test_a_sweep_that_ends_between_scan_batches_still_notifies(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hypothex.notify.notifier.SCAN_BATCH", 1)
    spec = SweepSpec(
        id="s-0009", project="toy", task="toy-acc", host=None,
        grid=[SweepParam(name="x", values=["1", "2"])], seeds=[1],
        command_template=["echo", "{x}"], created_by="human:sv", created_at=T0,
    )  # fmt: skip
    save_sweep(toy.layout, spec)
    tag = sweep_tag(toy.descriptor.environment_id, spec.id)
    for run_id in ("y0", "y1"):
        toy.create_run(
            make_record(
                run_id, task="toy-acc", status=RunStatus.QUEUED, tags=[tag],
                environment_id=toy.descriptor.environment_id, sweep_id=spec.id,
            )
        )  # fmt: skip
    notifier = primed(toy, settings_for(), clock)

    def finish(run_id: str) -> None:
        toy.update_run(
            run_id,
            "run.finished",
            lambda r: r.model_copy(update={"status": RunStatus.FINISHED, "ended_at": T0}),
        )

    finish("y0")  # batch 1: y0 ended, y1 still queued
    real_since = toy.events.since
    calls = {"n": 0}

    def since(after: int, limit: int) -> list[Event]:
        calls["n"] += 1
        if calls["n"] == 2:
            finish("y1")  # the last run ends while batch 1 is being read
        return real_since(after, limit)

    monkeypatch.setattr(toy.events, "since", since)
    (entry,) = notifier.scan()
    assert entry.notice.kind == "sweep" and entry.notice.sweep_id == "s-0009"


def test_folded_sweeps_follow_the_rule_events(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    def sweep(sweep_id: str, statuses: list[RunStatus]) -> None:
        values = [str(i) for i in range(len(statuses))]
        spec = SweepSpec(
            id=sweep_id, project="toy", task="toy-acc", host=None,
            grid=[SweepParam(name="x", values=values)], seeds=[1],
            command_template=["echo", "{x}"], created_by="human:sv", created_at=T0,
        )  # fmt: skip
        save_sweep(toy.layout, spec)
        tag = sweep_tag(toy.descriptor.environment_id, sweep_id)
        for i, status in enumerate(statuses):
            run_id = f"x{sweep_id[-1]}{i}"
            toy.create_run(
                make_record(
                    run_id, task="toy-acc", status=RunStatus.QUEUED, tags=[tag],
                    environment_id=toy.descriptor.environment_id, sweep_id=sweep_id,
                )
            )  # fmt: skip
            toy.update_run(
                run_id,
                f"run.{status.value}",
                lambda r, s=status: r.model_copy(update={"status": s, "ended_at": T0}),
            )

    notifier = primed(toy, settings_for(events=["failed", "lost"]), clock)
    sweep("s-0002", [RunStatus.FINISHED, RunStatus.FINISHED])
    assert notifier.scan() == []  # all finished: a failure-only rule hears nothing
    sweep("s-0003", [RunStatus.FINISHED, RunStatus.FAILED])
    (entry,) = notifier.scan()
    assert entry.notice.kind == "sweep" and entry.notice.sweep_id == "s-0003"
    notifier.settings = settings_for(events=[])
    sweep("s-0004", [RunStatus.FAILED])
    assert notifier.scan() == []


def small_sweep(ctx: Context, sweep_id: str, n: int) -> str:
    spec = SweepSpec(
        id=sweep_id, project="toy", task="toy-acc", host=None,
        grid=[SweepParam(name="x", values=[str(i) for i in range(n)])], seeds=[1],
        command_template=["echo", "{x}"], created_by="human:sv", created_at=T0,
    )  # fmt: skip
    save_sweep(ctx.layout, spec)
    return sweep_tag(ctx.descriptor.environment_id, sweep_id)


def test_a_foreign_sweep_with_the_same_id_is_not_folded(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    mine = small_sweep(toy, "s-0005", 2)
    toy.create_run(
        make_record(
            "own0", task="toy-acc", status=RunStatus.QUEUED, tags=[mine],
            environment_id=toy.descriptor.environment_id, sweep_id="s-0005",
        )
    )  # fmt: skip
    notifier = primed(toy, settings_for(), clock)
    # another hub's sweep s-0005, mirrored here from a host both hubs use
    foreign = sweep_tag("ffffffff00000000", "s-0005")
    end_run(toy, "far0", "failed", tags=[foreign], sweep_id="s-0005")
    (entry,) = notifier.scan()
    assert entry.notice.kind == "run" and entry.notice.run_id == "far0"


def test_a_sweep_still_launching_waits_for_its_last_run(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    tag = small_sweep(toy, "s-0006", 2)
    notifier = primed(toy, settings_for(), clock)
    lock = sweep_path(toy.layout, "toy", "s-0006").with_suffix(".lock")
    with lock.open("a") as fh:  # launch_sweep holds the sweep's lock while it issues runs
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        assert sweep_issuing(toy.layout, "toy", "s-0006")
        end_run(toy, "q0", "finished", tags=[tag], sweep_id="s-0006")  # a short first run
        assert notifier.scan() == []  # 1 of 2 runs exists: never "1/1"
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    assert not sweep_issuing(toy.layout, "toy", "s-0006")
    end_run(toy, "q1", "finished", tags=[tag], sweep_id="s-0006")
    (entry,) = notifier.scan()
    assert entry.notice.title == "✓ toy sweep s-0006 2/2"
    # a launch that failed after one run: nothing is issuing, so what exists is final
    part = small_sweep(toy, "s-0007", 3)
    end_run(toy, "p0", "failed", tags=[part], sweep_id="s-0007")
    (partial,) = notifier.scan()
    assert partial.notice.title == "✗ toy sweep s-0007 1/1"


def test_partial_sweep_notifies_after_issuance_failure_without_new_events(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    tag = small_sweep(toy, "s-0008", 3)
    settings = settings_for()
    notifier = primed(toy, settings, clock)
    lock = sweep_path(toy.layout, "toy", "s-0008").with_suffix(".lock")
    with lock.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        end_run(toy, "partial0", "failed", tags=[tag], sweep_id="s-0008")
        assert notifier.scan() == []
        cursor = toy.events.last_sequence()
        pending = toy.layout.home / "notify" / "pending-sweeps.json"
        assert json.loads(pending.read_text())
        assert stat.S_IMODE(pending.stat().st_mode) == 0o600
        toy.events.append("run.created", project="toy", run_id="partial0", payload={})
        assert notifier.scan() == []
        assert json.loads(pending.read_text())  # unrelated nonterminal event cannot erase it
        cursor = toy.events.last_sequence()
        # Restart while still issuing. It must neither lose the trigger nor emit early.
        notifier = Notifier(toy, settings, now=clock)
        assert notifier.scan() == []
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)  # later launch failed, no further run exists
    assert toy.events.last_sequence() == cursor
    (entry,) = notifier.scan()
    assert entry.notice.title == "✗ toy sweep s-0008 1/1"
    assert json.loads(pending.read_text()) == {}
    assert notifier.scan() == []
    assert Notifier(toy, settings, now=clock).scan() == []


@pytest.mark.parametrize("state", ["preparing", "queued", "issuing", "settling"])
@pytest.mark.parametrize("terminal", ["issued", "incomplete", "interrupted"])
def test_durable_issuance_defers_without_lock_and_retries_after_restart(
    toy: Context,
    hook: FakeWebhook,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    terminal: str,
) -> None:
    from hypothex.core.sweeps import SweepIssuance, SweepSummary, summarize_sweep

    tag = small_sweep(toy, "s-0009", 1)
    settings = settings_for()
    notifier = primed(toy, settings, clock)
    end_run(toy, "durable0", "failed", tags=[tag], sweep_id="s-0009")
    summary = summarize_sweep(toy, "toy", "s-0009")
    current = [state]

    def fresh(_self: Notifier, _record: RunRecord) -> SweepSummary:
        issuance = SweepIssuance.model_validate(
            {
                "state": current[0],
                "episode": 1,
                "revision": 2,
                "planned": 1,
                "accepted_at": T0,
                "updated_at": T0,
            }
        )
        return summary.model_copy(update={"issuance": issuance})

    monkeypatch.setattr(Notifier, "_sweep", fresh)
    assert not sweep_issuing(toy.layout, "toy", "s-0009")
    assert summary.counts["total"] == 1  # full observed count still cannot finish issuance
    assert notifier.scan() == []
    cursor = toy.events.last_sequence()
    notifier = Notifier(toy, settings, now=clock)
    assert notifier.scan() == []
    current[0] = terminal
    assert toy.events.last_sequence() == cursor  # no new event needed for durable retry
    (entry,) = notifier.scan()
    assert entry.notice.title == "✗ toy sweep s-0009 1/1"
    assert notifier.scan() == []
    assert Notifier(toy, settings, now=clock).scan() == []


def test_unconfigured_channels_are_not_enqueued(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    settings = settings_for()
    settings.notify.projects["toy"] = ProjectRule(channels=["slack", "email"])
    notifier = primed(toy, settings, clock)
    end_run(toy, "a", "failed")
    assert [e.channel for e in notifier.scan()] == ["slack"]


def test_stored_notices_are_redacted(toy: Context, hook: FakeWebhook, clock: Clock) -> None:
    notifier = primed(toy, settings_for(), clock)
    record = end_run(toy, "leaky", "failed")
    (toy.run_dir(record) / "logs" / "stderr.log").write_text(f"POST {hook.url} -> 500\n")
    toy.events.append("run.failed", project="toy", run_id="leaky", payload={})
    (entry,) = notifier.scan()
    path = toy.layout.home / "notify" / "outbox" / f"{entry.id}.slack.json"
    text = path.read_text()
    assert hook.secret not in text and "***" in text
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert OutboxEntry.model_validate_json(text).status == "pending"


def outbox(ctx: Context) -> list[OutboxEntry]:
    folder = ctx.layout.home / "notify" / "outbox"
    return [OutboxEntry.model_validate_json(p.read_text()) for p in sorted(folder.glob("*.json"))]


def finals(ctx: Context) -> list[dict]:
    return read_jsonl(ctx.layout.home / "notify" / "sent.jsonl")


def test_deliver_sends_once_per_channel(
    toy: Context, hook: FakeWebhook, smtp: FakeSmtp, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(smtp), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    before = toy.events.last_sequence()
    done = notifier.deliver()
    assert sorted((e.channel, e.status, e.attempts) for e in done) == [
        ("email", "sent", 1),
        ("slack", "sent", 1),
    ]
    assert hook.requests[0]["body"]["text"].startswith("✗ toy/toy-acc a")
    assert smtp.received[0].message["Subject"].startswith("✗ toy/toy-acc a")
    assert outbox(toy) == [] and len(finals(toy)) == 2
    events = toy.events.since(before)
    assert [e.type for e in events] == ["notify.sent", "notify.sent"]
    keys = {"entry_id", "channel", "kind", "run_id", "attempts", "error_class"}
    assert set(events[0].payload) == keys
    assert notifier.deliver() == []


def test_slack_429_waits_for_retry_after_or_the_schedule(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    hook.queue(Reply(429, retry_after=7), Reply(429, retry_after=500))
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    (first,) = notifier.deliver()
    assert (first.status, first.attempts, first.last_error) == ("pending", 1, "http_429")
    assert first.next_at == clock() + timedelta(seconds=30)  # max(7, 30)
    clock.tick(29)
    assert notifier.deliver() == []
    clock.tick(1)
    (second,) = notifier.deliver()
    assert second.next_at == clock() + timedelta(seconds=500)  # max(500, 120)
    clock.tick(500)
    (third,) = notifier.deliver()
    assert third.status == "sent" and third.attempts == 3 and len(hook.requests) == 3


def test_three_retries_then_failed(toy: Context, hook: FakeWebhook, clock: Clock) -> None:
    hook.queue(*[Reply(500)] * 4)
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    for delay in (30, 120, 600):
        (entry,) = notifier.deliver()
        assert entry.status == "pending" and entry.next_at == clock() + timedelta(seconds=delay)
        clock.tick(delay)
    before = toy.events.last_sequence()
    (last,) = notifier.deliver()
    assert (last.status, last.attempts, last.last_error) == ("failed", 4, "http_500")
    (event,) = toy.events.since(before)
    assert event.type == "notify.failed" and event.payload["error_class"] == "http_500"


def test_permanent_errors_fail_at_once(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook.queue(Reply(404))
    with FakeSmtp(user="sv", password="right") as smtp:
        settings = settings_for(smtp)
        assert settings.notify.email is not None
        settings.notify.email = settings.notify.email.model_copy(
            update={"username": "sv", "password_env": "HX_TEST_SMTP"}
        )
        monkeypatch.setenv("HX_TEST_SMTP", "wrong")
        notifier = primed(toy, settings, clock)
        end_run(toy, "a", "failed")
        notifier.scan()
        done = {e.channel: e for e in notifier.deliver()}
    assert (done["slack"].status, done["slack"].last_error) == ("failed", "http_404")
    assert (done["email"].status, done["email"].last_error) == ("failed", "smtp_535")
    assert "wrong" not in (toy.layout.home / "notify" / "sent.jsonl").read_text()


def test_unset_secret_skips(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    monkeypatch.delenv("HX_TEST_HOOK")
    (entry,) = notifier.deliver()
    assert (entry.status, entry.last_error) == ("skipped", "unset:HX_TEST_HOOK")
    assert hook.requests == []


def test_entry_left_sending_by_a_crash_is_retried_once(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    real_finish = Notifier._finish
    calls = {"n": 0}

    def crash_once(self: Notifier, entry: OutboxEntry) -> OutboxEntry:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("hub died after the send, before the record")
        return real_finish(self, entry)

    monkeypatch.setattr(Notifier, "_finish", crash_once)
    with pytest.raises(RuntimeError):
        notifier.deliver()
    (left,) = outbox(toy)
    assert left.status == "sending" and left.next_at == clock() + timedelta(seconds=60)
    assert notifier.deliver() == []  # not yet due
    clock.tick(60)
    (again,) = notifier.deliver()
    assert again.status == "sent" and len(hook.requests) == 2  # at least once
    clock.tick(3600)
    assert notifier.deliver() == [] and len(hook.requests) == 2


def test_an_entry_recorded_before_a_crash_is_not_sent_again(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    (sent,) = notifier.deliver()
    assert sent.status == "sent" and len(hook.requests) == 1
    # a crash between the sent.jsonl append and the outbox unlink leaves both behind
    notifier._write(sent.model_copy(update={"status": "sending", "next_at": clock()}))
    restarted = Notifier(toy, settings_for(), now=clock)
    clock.tick(60)
    assert restarted.deliver() == [] and len(hook.requests) == 1
    assert outbox(toy) == []


def test_recent_lists_final_and_pending_newest_first(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    notifier.deliver()
    clock.tick(10)
    end_run(toy, "b", "failed")
    notifier.scan()
    recent = notifier.recent()
    assert [(e.notice.run_id, e.status) for e in recent] == [("b", "pending"), ("a", "sent")]
    assert len(notifier.recent(limit=1)) == 1


def test_tick_scans_and_delivers(toy: Context, hook: FakeWebhook, clock: Clock) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "lost")
    notifier.tick()
    assert [r["status"] for r in finals(toy)] == ["sent"]


def test_loop_rereads_settings_and_stops(toy: Context, hook: FakeWebhook) -> None:
    from hypothex.core.settings import save_settings

    save_settings(toy.layout, settings_for())
    stop = threading.Event()
    thread = threading.Thread(target=run_notifier_loop, args=(toy, stop), kwargs={"interval": 0.05})
    thread.start()
    try:
        cursor = toy.layout.home / "notify" / "cursor.json"
        for _ in range(100):
            if cursor.exists():
                break
            stop.wait(0.05)
        end_run(toy, "a", "failed", ended=datetime.now(UTC))
        for _ in range(100):
            if hook.requests:
                break
            stop.wait(0.05)
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive() and len(hook.requests) == 1


def test_digest_goes_out_once_per_week(
    toy: Context, hook: FakeWebhook, smtp: FakeSmtp, clock: Clock
) -> None:
    settings = settings_for(smtp)
    settings.digest = DigestSettings(
        enabled=True, weekday="sun", hour=0, timezone="UTC", channels=["slack", "email"]
    )
    notifier = primed(toy, settings, clock)  # 2026-10-04 is a Sunday
    notifier.tick()
    assert [r["body"]["text"].split(" · ")[0] for r in hook.requests] == ["Σ toy 2026-W40"]
    assert smtp.received[0].message["Subject"].startswith("Σ toy 2026-W40")
    state = json.loads((toy.layout.home / "notify" / "digest.json").read_text())
    assert state == {"toy": "2026-W40"}
    clock.tick(3600)
    assert notifier.digests() == []
    notifier.settings = settings.model_copy(update={"digest": DigestSettings(enabled=False)})
    clock.tick(7 * 86400)
    assert notifier.digests() == []


def test_a_digest_sent_again_after_a_crash_is_queued_and_saved_once(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    settings = settings_for()
    settings.digest = DigestSettings(
        enabled=True, weekday="sun", hour=0, timezone="UTC", channels=["slack"]
    )
    assert primed(toy, settings, clock).digests() == ["toy"]
    (toy.layout.home / "notify" / "digest.json").unlink()  # crashed before the checkpoint
    clock.tick(3600)
    assert Notifier(toy, settings, now=clock).digests() == ["toy"]
    assert len(list((toy.layout.home / "notify" / "outbox").glob("*.slack.json"))) == 1
    assert read_day(toy, "toy", date(2026, 10, 4)).text.count("— digest") == 1


def test_a_digest_note_never_carries_a_secret(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    settings = settings_for()
    settings.digest = DigestSettings(
        enabled=True, weekday="sun", hour=0, timezone="UTC", channels=["slack"]
    )
    when = clock() - timedelta(days=1)
    append_entry(toy, "toy", f"hook is {hook.url}", "human:sv", day=when.date(), now=when)
    assert primed(toy, settings, clock).digests() == ["toy"]
    (path,) = (toy.layout.home / "notify" / "outbox").glob("*.slack.json")
    assert hook.secret not in path.read_text() and "***" in path.read_text()


def test_a_full_notebook_day_never_stops_digests_or_delivery(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for()
    settings.digest = DigestSettings(
        enabled=True, weekday="sun", hour=0, timezone="UTC", channels=["slack"]
    )
    notifier = primed(toy, settings, clock)
    monkeypatch.setattr(notebook_module, "NOTEBOOK_MAX_BYTES", 10)  # today's page is full
    end_run(toy, "r1", "failed")
    notifier.tick()
    assert sorted(r["body"]["text"][:1] for r in hook.requests) == ["Σ", "✗"]
    state = json.loads((toy.layout.home / "notify" / "digest.json").read_text())
    assert state == {"toy": "2026-W40"}  # sent once: the next tick does not retry the week
    assert "— digest" not in read_day(toy, "toy", date(2026, 10, 4)).text


def test_all_notice_text_and_file_secret_values_are_redacted(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.notify.messages import test_notice as make_notice

    monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", "SECRETHUBVALUE")
    secrets = toy.layout.home / "secrets.env"
    secrets.write_text("CUSTOM_SECRET=SECRETFILEVALUE\n")
    secrets.chmod(0o600)
    notifier = primed(toy, settings_for(), clock)
    notice = make_notice("slack").model_copy(
        update={
            "title": "SECRETHUBVALUE SECRETFILEVALUE",
            "lines": [hook.url],
            "url": "https://example/SECRETHUBVALUE",
            "status": "SECRETFILEVALUE",
        }
    )
    (entry,) = notifier.enqueue(notice, ["slack"])
    text = notifier._path(entry.id, entry.channel).read_text()
    assert all(secret not in text for secret in ("SECRETHUBVALUE", "SECRETFILEVALUE", hook.secret))


def test_recent_zero_is_empty(toy: Context, hook: FakeWebhook, clock: Clock) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.tick()
    assert notifier.recent(0) == []


def test_reused_notifier_observes_other_instance_final_records(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    from hypothex.notify.messages import test_notice as make_notice

    notifier = primed(toy, settings_for(), clock)
    notice = make_notice("slack")
    notifier.enqueue(notice, ["slack"])
    Notifier(toy, settings_for(), now=clock).deliver()
    assert notifier.enqueue(notice, ["slack"]) == []
    assert len(hook.requests) == 1


def test_partial_history_line_does_not_hide_the_next_final(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.scan()
    history = notifier.root / "sent.jsonl"
    history.write_bytes(b'{"id":"partial')
    notifier.deliver()
    assert len(finals(toy)) == 1
    assert stat.S_IMODE(history.stat().st_mode) == 0o600


def test_digest_failure_does_not_stop_delivery(
    toy: Context,
    hook: FakeWebhook,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")

    def fail() -> list[str]:
        raise RuntimeError(hook.url)

    monkeypatch.setattr(notifier, "digests", fail)
    notifier.tick()
    assert len(hook.requests) == 1
    assert "RuntimeError" in caplog.text and hook.secret not in caplog.text


def test_send_test_is_immediate_and_status_omits_secrets(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.notify.notifier import notify_status

    settings = settings_for()
    notifier = primed(toy, settings, clock)
    assert notifier.send_test("slack") == {"ok": True, "error_class": None}
    assert hook.requests[0]["body"]["text"] == "✓ hypothex test · slack"
    assert notifier.recent() == []
    body = notify_status(toy, settings)
    assert body["channels"]["slack"] == {"configured": True, "env": "HX_TEST_HOOK", "set": True}
    assert hook.secret not in json.dumps(body)
    monkeypatch.delenv("HX_TEST_HOOK")
    assert notifier.send_test("slack") == {"ok": False, "error_class": "unset:HX_TEST_HOOK"}
    assert notifier.send_test("email") == {"ok": False, "error_class": "unconfigured"}


def test_two_notifiers_enqueue_and_deliver_one_notice(
    toy: Context, hook: FakeWebhook, clock: Clock
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from hypothex.notify.messages import test_notice as make_notice

    first = primed(toy, settings_for(), clock)
    second = Notifier(toy, settings_for(), now=clock)
    notice = make_notice("slack")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(n.enqueue, notice, ["slack"]) for n in (first, second)]
        assert sum(len(f.result()) for f in futures) == 1
        futures = [pool.submit(n.deliver) for n in (first, second)]
        assert sum(len(f.result()) for f in futures) == 1
    assert len(hook.requests) == 1 and len(finals(toy)) == 1


def test_history_stream_skips_oversized_lines_and_bounds_recent(
    toy: Context, hook: FakeWebhook, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    notifier = primed(toy, settings_for(), clock)
    end_run(toy, "a", "failed")
    notifier.tick()
    history = notifier.root / "sent.jsonl"
    with history.open("ab") as fh:
        fh.write(b"x" * 2_000_000 + b"\n")
    original = Path.read_text

    def guard(self: Path, *args: object, **kwargs: object) -> str:
        assert self != history, "history reads must stream rather than load every notice"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guard)
    restarted = Notifier(toy, settings_for(), now=clock)
    assert [e.notice.run_id for e in restarted.recent(1)] == ["a"]
    assert restarted.deliver() == []


@pytest.mark.parametrize("refusal", [450, 550])
def test_partial_recipient_delivery_preserves_outbox_failure_state(
    toy: Context, clock: Clock, refusal: int
) -> None:
    from hypothex.notify.messages import test_notice as make_notice

    rejected = "SECRETRECIPIENT@lab.invalid"
    with FakeSmtp(refusals={rejected: (refusal, "SECRETSMTPREPLY")}) as smtp:
        settings = settings_for(smtp)
        assert settings.notify.email is not None
        settings.notify.email.to = ["accepted@lab.invalid", rejected]
        notifier = primed(toy, settings, clock)
        notifier.enqueue(make_notice("email"), ["email"])
        before = toy.events.last_sequence()
        (entry,) = notifier.deliver()
        assert smtp.received[0].rcpt_tos == ["accepted@lab.invalid"]
        assert entry.last_error == f"smtp_{refusal}" and entry.sent_at is None
        if refusal == 450:
            assert (entry.status, entry.attempts) == ("pending", 1)
            assert entry.next_at == clock() + timedelta(seconds=30)
            assert len(outbox(toy)) == 1 and finals(toy) == []
            assert toy.events.since(before) == []
            # Recovery retries the whole channel batch: the accepted recipient
            # can receive another copy, while the previously rejected one now gets it.
            smtp.refusals.clear()
            clock.tick(30)
            (recovered,) = notifier.deliver()
            assert (recovered.status, recovered.attempts, recovered.last_error) == ("sent", 2, None)
            assert smtp.received[1].rcpt_tos == ["accepted@lab.invalid", rejected]
        else:
            assert (entry.status, entry.attempts) == ("failed", 1)
            assert outbox(toy) == []
            assert [row["status"] for row in finals(toy)] == ["failed"]
            assert [event.type for event in toy.events.since(before)] == ["notify.failed"]
        persisted = "\n".join(path.read_text() for path in notifier.root.rglob("*.json*"))
        assert rejected not in persisted and "SECRETSMTPREPLY" not in persisted


def test_mixed_partial_recipient_refusals_retry_transient_recipient(
    toy: Context, clock: Clock
) -> None:
    from hypothex.notify.messages import test_notice as make_notice

    transient = "temporary@lab.invalid"
    permanent = "permanent@lab.invalid"
    with FakeSmtp(
        refusals={transient: (450, "SECRETTRANSIENT"), permanent: (550, "SECRETPERMANENT")}
    ) as smtp:
        settings = settings_for(smtp)
        assert settings.notify.email is not None
        settings.notify.email.to = ["accepted@lab.invalid", transient, permanent]
        notifier = primed(toy, settings, clock)
        notifier.enqueue(make_notice("email"), ["email"])
        (first,) = notifier.deliver()
        assert (first.status, first.last_error) == ("pending", "smtp_450")
        assert len(outbox(toy)) == 1 and finals(toy) == []
        del smtp.refusals[transient]
        clock.tick(30)
        (second,) = notifier.deliver()
        assert (second.status, second.attempts, second.last_error) == ("failed", 2, "smtp_550")
        assert second.sent_at is None and outbox(toy) == []
        assert [r.rcpt_tos for r in smtp.received] == [
            ["accepted@lab.invalid"],
            ["accepted@lab.invalid", transient],
        ]
        assert [row["status"] for row in finals(toy)] == ["failed"]
        assert notifier.deliver() == []
        persisted = (notifier.root / "sent.jsonl").read_text()
        assert "SECRETTRANSIENT" not in persisted and "SECRETPERMANENT" not in persisted


def test_partial_recipient_retries_remain_bounded(toy: Context, clock: Clock) -> None:
    from hypothex.notify.messages import test_notice as make_notice

    with FakeSmtp(refusals={"rejected@lab.invalid": (450, "temporary rejection")}) as smtp:
        settings = settings_for(smtp)
        assert settings.notify.email is not None
        settings.notify.email.to = ["accepted@lab.invalid", "rejected@lab.invalid"]
        notifier = primed(toy, settings, clock)
        notifier.enqueue(make_notice("email"), ["email"])
        for attempts, delay in enumerate((30, 120, 600), start=1):
            (entry,) = notifier.deliver()
            assert (entry.status, entry.attempts, entry.last_error) == (
                "pending",
                attempts,
                "smtp_450",
            )
            assert entry.next_at == clock() + timedelta(seconds=delay)
            assert len(outbox(toy)) == 1 and finals(toy) == []
            clock.tick(delay)
        (failed,) = notifier.deliver()
        assert (failed.status, failed.attempts, failed.last_error) == ("failed", 4, "smtp_450")
        assert failed.sent_at is None and outbox(toy) == []
        assert [row["status"] for row in finals(toy)] == ["failed"]
        assert [received.rcpt_tos for received in smtp.received] == [["accepted@lab.invalid"]] * 4
        assert notifier.deliver() == []
