from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from hypothex.core.records import CostTotals, RunRecord, RunStatus
from hypothex.core.settings import EmailSettings
from hypothex.core.sweeps import SweepParam, SweepSpec, SweepSummary
from hypothex.notify.messages import (
    cost_text,
    fmt_duration,
    notice_id,
    render_email,
    render_slack,
    run_notice,
    sweep_notice,
)
from hypothex.notify.messages import test_notice as make_test_notice  # not a test
from tests.factories import PREDS_075, seed_finished_run

T0 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
EMAIL = EmailSettings(host="127.0.0.1", sender="hx@lab.org", to=["sv@lab.org", "al@lab.org"])


def ended(ctx: Context, run_id: str, status: RunStatus, *, minutes: float = 12) -> RunRecord:
    def mutate(r: RunRecord) -> RunRecord:
        return r.model_copy(
            update={
                "status": status,
                "started_at": T0,
                "ended_at": T0 + timedelta(minutes=minutes),
                "exit_code": 0 if status == RunStatus.FINISHED else 1,
                "created_by": "human:alice",
                "cost": CostTotals(
                    gpu_hours=0.4, gpu_usd=0.84, total_usd=0.84, gpu_pricing_complete=True
                ),
            }
        )

    return ctx.update_run(run_id, f"run.{status.value}", mutate)


@pytest.mark.parametrize(
    ("seconds", "text"), [(45, "45s"), (720, "12m"), (3900, "1h05m"), (183600, "2d03h")]
)
def test_fmt_duration(seconds: float, text: str) -> None:
    assert fmt_duration(seconds) == text


@pytest.mark.parametrize("complete", [False, None, True])
@pytest.mark.parametrize("total", [0.0, 0.25])
def test_cost_notice_preserves_unknown_and_genuine_zero(
    ctx: Context, toy_repo: Path, complete: bool | None, total: float
) -> None:
    seed_finished_run(ctx, toy_repo, "cost-case")
    record = ended(ctx, "cost-case", RunStatus.FINISHED)
    record.cost = CostTotals(total_usd=total, gpu_pricing_complete=complete)
    expected = f"${total:.2f}" if complete is True else f"Cost unknown · ${total:.2f} recorded"
    notice = run_notice(ctx, record, base_url=None)
    assert expected in notice.lines[0]
    assert expected in render_slack(notice)["text"]
    assert expected in render_email(notice, EMAIL).get_content()
    assert cost_text(total, complete) == expected


def test_finished_run_notice(ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    notice = run_notice(ctx, ended(ctx, "r1", RunStatus.FINISHED), base_url="https://hub.ts.net")
    assert notice.title == "✓ toy/toy-acc r1 accuracy 0.750"
    assert notice.lines == ["human:alice · 0.4 GPU-h · $0.84 · 12m"]
    assert notice.url == "https://hub.ts.net/r/r1"
    assert (notice.kind, notice.project, notice.run_id) == ("run", "toy", "r1")
    assert notice.status == "finished"
    assert notice.id == notice_id("run", "toy", "r1", "finished") and len(notice.id) == 16


def test_failed_run_quotes_the_last_stderr_line(ctx: Context, toy_repo: Path) -> None:
    record = seed_finished_run(ctx, toy_repo, "r2")
    stderr = ctx.run_dir(record) / "logs" / "stderr.log"
    stderr.write_text("warming up\nTraceback ...\nValueError: " + "x" * 300 + "\n\n")
    notice = run_notice(ctx, ended(ctx, "r2", RunStatus.FAILED), base_url=None)
    assert notice.title == "✗ toy/toy-acc r2" and notice.url is None
    assert notice.lines[1].startswith("exit 1 · ValueError: x")
    assert len(notice.lines[1]) == len("exit 1 · ") + 200


@pytest.mark.parametrize(
    ("status", "glyph", "line"),
    [(RunStatus.LOST, "?", "lost · no exit record"), (RunStatus.KILLED, "⊘", "killed")],
)
def test_lost_and_killed(
    ctx: Context, toy_repo: Path, status: RunStatus, glyph: str, line: str
) -> None:
    seed_finished_run(ctx, toy_repo, "r3")
    notice = run_notice(ctx, ended(ctx, "r3", status), base_url=None)
    assert notice.title.startswith(glyph + " ") and notice.lines[-1] == line
    assert notice.id != notice_id("run", "toy", "r3", "finished")


def test_sweep_notice(ctx: Context) -> None:
    spec = SweepSpec(
        id="s-7f3a",
        project="toy",
        task="toy-acc",
        host="gpu1",
        grid=[SweepParam(name="lr", values=["1e-4", "3e-4"])],
        seeds=[1, 2, 3],
        command_template=["python", "train.py", "{lr}"],
        created_by="agent:tuner@sv",
        created_at=T0,
    )
    counts = {"queued": 0, "running": 0, "finished": 4, "failed": 1, "killed": 0, "lost": 1}
    summary = SweepSummary(
        spec=spec,
        counts={**counts, "total": 6},
        cells=[],
        best={"params": {"lr": "3e-4"}, "mean": 0.6131},
        headline="",
        total_usd=12.5,
        cost_complete=True,
    )
    notice = sweep_notice(ctx, summary, base_url="https://hub.ts.net")
    assert notice.title == "✗ toy sweep s-7f3a 6/6"
    assert notice.lines == ["✓4 ✗1 ?1 ⊘0 · $12.50", "best lr=3e-4 0.613"]
    assert notice.url == "https://hub.ts.net/s/toy/s-7f3a"
    assert notice.id == notice_id("sweep", "toy", "s-7f3a", "done", 6)


def test_test_notice_and_renderers() -> None:
    notice = make_test_notice("slack")
    assert notice.kind == "test" and notice.title == "✓ hypothex test · slack"
    full = notice.model_copy(update={"lines": ["a · b"], "url": "https://hub/r/x"})
    assert render_slack(full) == {"text": "✓ hypothex test · slack\na · b\nhttps://hub/r/x"}
    email = render_email(full, EMAIL)
    assert email["Subject"] == "✓ hypothex test · slack"
    assert email["From"] == "hx@lab.org" and email["To"] == "sv@lab.org, al@lab.org"
    assert email.get_content_type() == "text/plain"
    assert email.get_content() == "a · b\nhttps://hub/r/x\n"


@pytest.mark.parametrize(("complete", "total"), [(False, 12.5), (False, 0), (True, 0)])
def test_sweep_unknown_and_complete_zero(complete: bool, total: float, ctx: Context) -> None:
    spec = SweepSpec(
        id="s-0001",
        project="toy",
        task="toy-acc",
        host=None,
        grid=[SweepParam(name="x", values=["1"])],
        seeds=[1],
        command_template=["echo", "{x}"],
        created_by="human",
        created_at=T0,
    )
    summary = SweepSummary(
        spec=spec,
        counts={"total": 0},
        cells=[],
        best=None,
        headline="",
        total_usd=total,
        cost_complete=complete,
    )
    notice = sweep_notice(ctx, summary, base_url=None)
    expected = f"${total:.2f}" if complete else f"Cost unknown · ${total:.2f} recorded"
    assert expected in notice.lines[0]
    assert expected in render_slack(notice)["text"]
    assert expected in render_email(notice, EMAIL).get_content()


def test_run_without_cost_retains_usage_and_unknown_gpu(ctx: Context, toy_repo: Path) -> None:
    from hypothex.core.records import ExecutorInfo, UsageTotals

    record = seed_finished_run(ctx, toy_repo, "missing")
    record = record.model_copy(
        update={
            "cost": None,
            "usage": UsageTotals(usd=0.25),
            "executor": ExecutorInfo(gpus=[0]),
            "started_at": T0,
            "ended_at": T0 + timedelta(hours=1),
        }
    )
    notice = run_notice(ctx, record, base_url=None)
    assert "1.0 GPU-h · Cost unknown · $0.25 recorded" in notice.lines[0]
