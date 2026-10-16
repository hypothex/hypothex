from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.digest import (
    build_digest,
    digest_due,
    digest_notice,
    render_digest_markdown,
    send_digest,
    week_key,
)
from hypothex.core.errors import StoreError
from hypothex.core.notebook import append_entry, read_day
from hypothex.core.records import CostTotals, GitInfo, RunStatus, ScoreRecord
from hypothex.core.settings import DigestSettings, NotifySettings, Settings, SlackSettings
from hypothex.core.sweeps import SweepParam, SweepSpec, save_sweep
from tests.factories import make_record

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)  # a Monday
SINCE = T0 - timedelta(days=7)


def run(
    ctx: Context,
    run_id: str,
    *,
    created: datetime,
    status: RunStatus,
    ended: datetime | None = None,
    chash: str = "sha256:aaaa",
    by: str = "human",
    cost: CostTotals | None = None,
    hypothesis: str = "",
) -> None:
    ctx.create_run(
        make_record(
            run_id,
            task="toy-acc",
            status=status,
            created_at=created,
            started_at=created,
            ended_at=ended,
            config_hash=chash,
            git=GitInfo(commit="c1"),
            created_by=by,
            cost=cost,
            hypothesis=hypothesis,
            environment_id=ctx.descriptor.environment_id,
        )
    )


def score(ctx: Context, run_id: str, value: float, at: datetime) -> None:
    ctx.add_score(
        ctx.find_record(run_id),
        ScoreRecord(metric="accuracy", version="v1", key="value", value=value, created_at=at),
    )


@pytest.fixture
def week(ctx: Context, toy_repo: Path) -> Context:
    ctx.register_project(toy_repo)
    day = timedelta(days=1)
    run(
        ctx,
        "old1",
        created=T0 - 10 * day,
        status=RunStatus.FINISHED,
        ended=T0 - 10 * day + timedelta(hours=1),
    )
    score(ctx, "old1", 0.6, T0 - 10 * day + timedelta(hours=2))
    run(
        ctx,
        "new1",
        created=T0 - 2 * day,
        status=RunStatus.FINISHED,
        ended=T0 - 2 * day + timedelta(hours=1),
        chash="sha256:bbbb",
        by="human:alice",
        cost=CostTotals(gpu_hours=1.0, gpu_usd=1.5, total_usd=1.5, gpu_pricing_complete=True),
        hypothesis="bigger model",
    )
    score(ctx, "new1", 0.7, T0 - 2 * day + timedelta(hours=2))
    run(
        ctx,
        "new2",
        created=T0 - day,
        status=RunStatus.FAILED,
        ended=T0 - day + timedelta(minutes=10),
        by="agent:claude@sv",
        cost=CostTotals(gpu_hours=0.5, api_usd=0.5, total_usd=0.5, gpu_pricing_complete=True),
    )
    run(ctx, "new3", created=T0 - day, status=RunStatus.QUEUED)
    run(
        ctx,
        "lost1",
        created=T0 - 3 * day,
        status=RunStatus.LOST,
        ended=T0 - 3 * day + timedelta(hours=5),
        by="human:alice",
    )
    notes = ctx.run_dir(ctx.find_record("new1")) / "notes.md"
    notes.write_text(
        f"\n## {(T0 - timedelta(days=1)).isoformat()} — human:alice\n\nfound the bug\n"
        f"\n## {(T0 - timedelta(days=9)).isoformat()} — human:alice\n\ntoo old\n"
    )
    late = T0 - timedelta(hours=12)
    append_entry(ctx, "toy", "plan [[run:new1]]", "human:sv", day=late.date(), now=late)
    append_entry(ctx, "toy", "last week's digest", "digest", day=late.date(), now=late)
    save_sweep(
        ctx.layout,
        SweepSpec(
            id="s-0002",
            project="toy",
            task="toy-acc",
            host=None,
            grid=[SweepParam(name="x", values=["1"])],
            seeds=[1],
            command_template=["echo", "{x}"],
            created_by="human:sv",
            created_at=T0 - timedelta(days=1),
        ),
    )
    return ctx


def test_week_key() -> None:
    assert week_key(T0) == "2026-W41"
    assert week_key(datetime(2027, 1, 1, tzinfo=UTC)) == "2026-W53"


def test_counts_owners_and_cost(week: Context) -> None:
    digest = build_digest(week, "toy", since=SINCE, until=T0)
    assert digest.week == "2026-W41"
    assert digest.counts == {
        "started": 4, "finished": 1, "failed": 1, "lost": 1, "killed": 0, "queued": 1,
    }  # fmt: skip
    assert digest.by_owner == {"agent:claude@sv": 1, "human": 1, "human:alice": 2}
    assert digest.cost == CostTotals(
        gpu_hours=1.5, gpu_usd=1.5, api_usd=0.5, total_usd=2.0, gpu_pricing_complete=True
    )


def test_leaderboard_change(week: Context) -> None:
    (change,) = build_digest(week, "toy", since=SINCE, until=T0).tasks
    assert change.task == "toy-acc" and change.primary == "accuracy/value"
    assert (change.before, change.after, change.new_best, change.n_new_runs) == (0.6, 0.7, True, 1)
    assert change.best_label == "bigger model" and change.best_group_id == "bbbb@c1"


def test_notes_and_sweeps(week: Context) -> None:
    digest = build_digest(week, "toy", since=SINCE, until=T0, top_notes=5)
    assert [(n.source, n.author, n.text) for n in digest.notes] == [
        ("notebook", "human:sv", "plan [[run:new1]]"),
        ("run", "human:alice", "found the bug"),
    ]
    assert digest.notes[1].run_id == "new1" and digest.notes[0].day is not None
    assert [(s.id, s.n_runs) for s in digest.sweeps] == [("s-0002", 0)]
    assert len(build_digest(week, "toy", since=SINCE, until=T0, top_notes=1).notes) == 1


def test_markdown_and_notice(week: Context) -> None:
    digest = build_digest(week, "toy", since=SINCE, until=T0)
    assert digest.headline == "▲4 ✓1 ✗1 ?1 · 1.5 GPU-h $2.00 · toy-acc 0.600→0.700 ▲"
    assert render_digest_markdown(digest) == (
        "**2026-W41** · ▲4 ✓1 ✗1 ?1 · 1.5 GPU-h $2.00 · toy-acc 0.600→0.700 ▲\n"
        "\n"
        "- toy-acc 0.600→0.700 ▲ · 1 runs\n"
        "\n"
        "notes\n"
        "- 10-04 21:00 @sv plan [[run:new1]]\n"
        "- 10-04 09:00 @alice [[run:new1]] found the bug\n"
        "\n"
        "sweeps\n"
        "- s-0002 · 0 runs\n"
    )
    notice = digest_notice(digest, base_url="https://hub.ts.net")
    assert notice.kind == "digest" and notice.project == "toy"
    assert notice.title == "Σ toy 2026-W41 · " + digest.headline
    assert notice.lines == [
        "toy-acc 0.600→0.700 ▲ · 1 runs",
        "✎ 10-04 21:00 @sv plan [[run:new1]]",
        "✎ 10-04 09:00 @alice [[run:new1]] found the bug",
    ]  # the top notes travel with the Slack/email summary (spec 9), not only the notebook
    assert notice.url == "https://hub.ts.net/n/toy"


@pytest.mark.parametrize("complete", [False, None, True])
@pytest.mark.parametrize("total", [0.0, 0.25])
def test_digest_cost_truth_reaches_every_representation(
    ctx: Context, toy_repo: Path, complete: bool | None, total: float
) -> None:
    from hypothex.core.settings import EmailSettings
    from hypothex.notify.messages import render_email, render_slack

    ctx.register_project(toy_repo)
    record = make_record(
        "cost-only",
        status=RunStatus.FINISHED,
        created_at=T0,
        started_at=T0,
        ended_at=T0,
        cost=CostTotals(total_usd=total, gpu_pricing_complete=complete),
    )
    ctx.create_run(record)
    digest = build_digest(ctx, "toy", since=SINCE, until=T0)
    expected = f"${total:.2f}" if complete is True else f"Cost unknown · ${total:.2f} recorded"
    assert expected in digest.headline
    assert expected in render_digest_markdown(digest)  # exact notebook body in send_digest
    notice = digest_notice(digest, base_url=None)
    assert expected in notice.title and expected in render_slack(notice)["text"]
    email = render_email(
        notice, EmailSettings(host="127.0.0.1", sender="hx@lab.org", to=["sv@lab.org"])
    )
    assert expected in str(email["Subject"])


def test_digest_missing_cost_keeps_api_subtotal_and_unknown_gpu(
    ctx: Context, toy_repo: Path
) -> None:
    from hypothex.core.records import ExecutorInfo, UsageTotals

    ctx.register_project(toy_repo)
    record = make_record(
        "missing-cost",
        status=RunStatus.FINISHED,
        created_at=T0 - timedelta(hours=2),
        started_at=T0 - timedelta(hours=2),
        ended_at=T0,
        executor=ExecutorInfo(gpus=[0, 1, 2, 3]),
        usage=UsageTotals(usd=0.25),
        cost=None,
    )
    ctx.create_run(record)
    digest = build_digest(ctx, "toy", since=SINCE, until=T0)
    assert digest.cost.gpu_hours == 8 and digest.cost.total_usd == 0.25
    assert digest.cost.gpu_pricing_complete is False
    assert "Cost unknown · $0.25 recorded" in digest.headline


def test_empty_week_and_unknown_project(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    digest = build_digest(ctx, "toy", since=SINCE, until=T0)
    assert (
        digest.tasks == []
        and digest.notes == []
        and digest.cost == CostTotals(gpu_pricing_complete=True)
    )
    assert digest.headline == "▲0 ✓0 ✗0 ?0 · 0.0 GPU-h $0.00"
    assert render_digest_markdown(digest) == "**2026-W41** · ▲0 ✓0 ✗0 ?0 · 0.0 GPU-h $0.00\n"
    with pytest.raises(StoreError):
        build_digest(ctx, "nope", since=SINCE, until=T0)


LONDON = DigestSettings(enabled=True, weekday="mon", hour=9, timezone="Europe/London")


@pytest.mark.parametrize(
    ("now", "last", "due"),
    [
        (datetime(2026, 10, 5, 7, 59, tzinfo=UTC), None, None),  # 08:59 in London (BST)
        (datetime(2026, 10, 5, 8, 0, tzinfo=UTC), None, "2026-W41"),
        (datetime(2026, 10, 5, 8, 0, tzinfo=UTC), "2026-W41", None),
        (datetime(2026, 10, 7, 12, 0, tzinfo=UTC), "2026-W40", "2026-W41"),  # hub was off
        (datetime(2026, 10, 12, 7, 0, tzinfo=UTC), "2026-W40", None),  # W41 missed: never sent
        (datetime(2026, 10, 12, 8, 0, tzinfo=UTC), "2026-W40", "2026-W42"),
    ],
)
def test_digest_due(now: datetime, last: str | None, due: str | None) -> None:
    assert digest_due(LONDON, last, now) == due


def test_send_digest_enqueues_and_saves_to_the_notebook(
    week: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HX_TEST_HOOK", "http://127.0.0.1:9/services/T/B/x")
    settings = Settings(
        notify=NotifySettings(slack=SlackSettings(webhook_env="HX_TEST_HOOK")),
        digest=DigestSettings(enabled=True, channels=["slack", "email"], timezone="UTC"),
    )
    before = week.events.last_sequence()
    assert send_digest(week, settings, "toy", now=T0) == ["slack"]  # email is not configured
    outbox = list((week.layout.home / "notify" / "outbox").glob("*.slack.json"))
    assert len(outbox) == 1 and "Σ toy 2026-W41" in outbox[0].read_text()
    day = read_day(week, "toy", T0.date())
    assert "— digest" in day.text and "**2026-W41**" in day.text
    sent = [e for e in week.events.since(before) if e.type == "digest.sent"]
    assert sent[0].payload == {"project": "toy", "week": "2026-W41", "channels": ["slack"]}


@pytest.mark.parametrize("flag", [False, None])
def test_mixed_costs_survive_notebook_and_outbox(
    ctx: Context, toy_repo: Path, flag: bool | None
) -> None:
    from hypothex.core.settings import EmailSettings
    from hypothex.notify.messages import render_email, render_slack
    from hypothex.notify.notifier import Notifier

    ctx.register_project(toy_repo)
    for name, total, complete in (("complete", 2.0, True), ("partial", 0.25, flag)):
        run(
            ctx,
            name,
            created=T0 - timedelta(days=1),
            ended=T0,
            status=RunStatus.FINISHED,
            cost=CostTotals(total_usd=total, gpu_pricing_complete=complete),
        )
    digest = build_digest(ctx, "toy", since=SINCE, until=T0)
    expected = "Cost unknown · $2.25 recorded"
    assert digest.cost.total_usd == 2.25 and expected in digest.headline
    settings = Settings(notify=NotifySettings(slack=SlackSettings(webhook_env="HX_TEST_HOOK")))
    assert send_digest(ctx, settings, "toy", now=T0) == ["slack"]
    assert render_digest_markdown(digest).strip() in read_day(ctx, "toy", T0.date()).text
    (entry,) = Notifier(ctx, settings).recent()
    assert expected in render_slack(entry.notice)["text"]
    email = render_email(
        entry.notice, EmailSettings(host="127.0.0.1", sender="a@lab.org", to=["b@lab.org"])
    )
    assert expected in str(email["Subject"])


def test_future_ending_does_not_change_historical_leaderboard(week: Context) -> None:
    run(
        week,
        "future-end",
        created=T0 - timedelta(days=1),
        ended=T0 + timedelta(days=1),
        status=RunStatus.FINISHED,
        chash="sha256:cccc",
    )
    score(week, "future-end", 0.99, T0 - timedelta(hours=1))
    (change,) = build_digest(week, "toy", since=SINCE, until=T0).tasks
    assert change.after == 0.7


def test_large_run_notes_keep_the_latest_entry_with_bounded_reads(week: Context) -> None:
    from unittest.mock import patch

    path = week.run_dir(week.find_record("new1")) / "notes.md"
    path.write_text(
        f"## {SINCE.isoformat()} — human:old\n"
        + "x" * 2_000_000
        + f"\n## {T0.isoformat()} — human:new\nnewest\n"
    )
    original = Path.read_text

    def guard(self: Path, *args: object, **kwargs: object) -> str:
        assert self != path, "digest must stream run notes instead of loading the whole file"
        return original(self, *args, **kwargs)

    with patch.object(Path, "read_text", guard):
        digest = build_digest(week, "toy", since=SINCE, until=T0, top_notes=1)
    assert [(note.author, note.text) for note in digest.notes] == [("human:new", "newest")]


def test_notebook_digest_copy_redacts_secrets(
    week: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HX_TEST_HOOK", "https://hooks.example/services/A/B/SECRETNOTE")
    append_entry(
        week,
        "toy",
        "https://hooks.example/services/A/B/SECRETNOTE",
        "human:sv",
        day=T0.date(),
        now=T0,
    )
    settings = Settings(notify=NotifySettings(slack=SlackSettings(webhook_env="HX_TEST_HOOK")))
    send_digest(week, settings, "toy", now=T0)
    text = read_day(week, "toy", T0.date()).text
    assert "SECRETNOTE" not in text.split("— digest\n", 1)[1]


def test_digest_due_disabled_and_dst_schedule() -> None:
    from hypothex.core.digest import digest_due_at

    assert digest_due(DigestSettings(enabled=False), None, T0) is None
    # The current Sunday is GMT, but this week's Monday was still BST.
    now = datetime(2026, 10, 25, 12, tzinfo=UTC)
    assert digest_due_at(LONDON, now).isoformat() == "2026-10-19T09:00:00+01:00"
    assert digest_due(LONDON, None, now) == "2026-W43"
    spring = DigestSettings(enabled=True, weekday="sun", hour=2, timezone="America/New_York")
    assert digest_due(spring, None, datetime(2026, 3, 8, 6, 59, tzinfo=UTC)) is None
    assert digest_due(spring, None, datetime(2026, 3, 8, 7, 0, tzinfo=UTC)) == "2026-W10"


def test_machine_timezone_uses_scheduled_dates_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import time

    from hypothex.core.digest import digest_due_at

    previous = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Europe/London")
    time.tzset()
    try:
        settings = DigestSettings(enabled=True, weekday="mon", hour=9)
        now = datetime(2026, 10, 25, 12, tzinfo=UTC)
        assert digest_due_at(settings, now).isoformat() == "2026-10-19T09:00:00+01:00"
    finally:
        if previous is None:
            monkeypatch.delenv("TZ")
        else:
            monkeypatch.setenv("TZ", previous)
        time.tzset()
