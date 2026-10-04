import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.headlines import overview_headline
from hypothex.core.ids import utcnow
from hypothex.core.overview import build_overview
from hypothex.core.records import CostTotals, GitInfo, RunRecord, RunStatus, ScoreRecord
from tests.factories import make_record

# Wilson 95% interval for 4/4 successes: lower = n / (n + z^2) = 4 / (4 + 1.959964^2)
# = 0.510109 (closed form of the Wilson score interval at p_hat = 1; Wilson 1927).
WILSON_4_OF_4_LO = 0.510109


def _run(
    ctx: Context,
    repo: Path,
    run_id: str,
    *,
    ago: timedelta,
    now: datetime,
    status: RunStatus = RunStatus.FINISHED,
    config_hash: str = "sha256:aaaa",
    commit: str = "c1",
    correct: list[bool] | None = None,
    task: str | None = "toy-acc",
    **overrides: object,
) -> RunRecord:
    """Create a run; with ``correct``, also write per-example and run scores."""
    ctx.register_project(repo)
    record = make_record(
        run_id,
        project="toy",
        task=task,
        status=status,
        config_hash=config_hash,
        git=GitInfo(commit=commit),
        created_at=now - ago,
        cwd=str(repo),
        **overrides,
    )
    ctx.create_run(record)
    if correct is not None:
        per_example = ctx.run_dir(record) / "predictions" / "scores.accuracy@v1.jsonl"
        per_example.write_text(
            "".join(
                json.dumps({"id": f"ex-{i}", "correct": ok}) + "\n" for i, ok in enumerate(correct)
            )
        )
        value = sum(correct) / len(correct)
        ctx.add_score(
            record,
            ScoreRecord(
                metric="accuracy", version="v1", key="value", value=value, created_at=now - ago
            ),
        )
    return record


@pytest.fixture
def scene(ctx: Context, toy_repo: Path) -> datetime:
    """
    Runs of project ``toy`` relative to ``now`` (returned):

    a1, a2   group aaaa@c1, 0.75 each (identical seeds), human, 120/119 min ago
    f1       group bbbb@c0, failed exit 2, agent, 90 min ago, same hypothesis as b1
    b1       group bbbb@c1, 1.0, agent, 60 min ago (current best)
    f2       group eeee@c1, failed exit 1, human, 30 min ago, never retried
    x1       group ffff@c1, finished but archived, 20 min ago
    e1       exploratory (no task), finished, 15 min ago
    r1       group cccc@c1, running, 10 min ago
    o1       group dddd@c1, 0.5, 3 days ago (outside the default window)
    """
    now = utcnow()
    three_of_four = [True, True, True, False]
    _run(
        ctx,
        toy_repo,
        "a1",
        ago=timedelta(minutes=120),
        now=now,
        correct=three_of_four,
        seed=1,
        hypothesis="baseline logreg",
    )
    _run(
        ctx,
        toy_repo,
        "a2",
        ago=timedelta(minutes=119),
        now=now,
        correct=three_of_four,
        seed=2,
        hypothesis="baseline logreg",
    )
    _run(
        ctx,
        toy_repo,
        "f1",
        ago=timedelta(minutes=90),
        now=now,
        status=RunStatus.FAILED,
        config_hash="sha256:bbbb",
        commit="c0",
        exit_code=2,
        created_by="agent:x",
        hypothesis="SVM, tuned",
    )
    _run(
        ctx,
        toy_repo,
        "b1",
        ago=timedelta(minutes=60),
        now=now,
        config_hash="sha256:bbbb",
        correct=[True, True, True, True],
        seed=1,
        created_by="agent:x",
        hypothesis="SVM, tuned",
    )
    _run(
        ctx,
        toy_repo,
        "f2",
        ago=timedelta(minutes=30),
        now=now,
        status=RunStatus.FAILED,
        config_hash="sha256:eeee",
        exit_code=1,
        hypothesis="doomed idea",
    )
    _run(
        ctx,
        toy_repo,
        "x1",
        ago=timedelta(minutes=20),
        now=now,
        config_hash="sha256:ffff",
        archived=True,
        hypothesis="debug",
    )
    _run(
        ctx,
        toy_repo,
        "e1",
        ago=timedelta(minutes=15),
        now=now,
        task=None,
        config_hash="sha256:9999",
        hypothesis="",
        tags=["poke"],
    )
    _run(
        ctx,
        toy_repo,
        "r1",
        ago=timedelta(minutes=10),
        now=now,
        status=RunStatus.RUNNING,
        config_hash="sha256:cccc",
        hypothesis="",
    )
    _run(
        ctx,
        toy_repo,
        "o1",
        ago=timedelta(days=3),
        now=now,
        config_hash="sha256:dddd",
        correct=[True, True, False, False],
        hypothesis="old idea",
    )
    return now


def test_timeline_is_window_oldest_first_with_best_and_archived(
    ctx: Context, scene: datetime
) -> None:
    summary = build_overview(ctx)
    assert [t.run_id for t in summary.timeline] == ["a1", "a2", "f1", "b1", "f2", "x1", "e1", "r1"]
    by_id = {t.run_id: t for t in summary.timeline}
    assert [t.run_id for t in summary.timeline if t.is_best] == ["b1"]
    assert by_id["x1"].archived and not by_id["a1"].archived
    assert by_id["a1"].group_id == "aaaa@c1" and by_id["f1"].group_id == "bbbb@c0"
    board = q.get_leaderboard(ctx, "toy-acc", "toy")
    labels = {row.group_id: row.label for row in board.rows}
    assert by_id["a1"].label == labels["aaaa@c1"]
    assert by_id["b1"].label == labels["bbbb@c1"]
    assert by_id["f1"].label == "SVM"  # failed group is not on the board: first clause
    assert by_id["r1"].label == "group cccc@c1"  # no hypothesis, no tags
    assert by_id["e1"].label == "poke" and by_id["e1"].task is None


def test_ideas_one_per_unarchived_group_newest_first(ctx: Context, scene: datetime) -> None:
    summary = build_overview(ctx)
    assert [(i.task, i.group_id) for i in summary.ideas] == [
        ("toy-acc", "cccc@c1"),
        (None, "9999@c1"),
        ("toy-acc", "eeee@c1"),
        ("toy-acc", "bbbb@c1"),
        ("toy-acc", "bbbb@c0"),
        ("toy-acc", "aaaa@c1"),
    ]
    ideas = {i.group_id: i for i in summary.ideas}
    logreg = ideas["aaaa@c1"]
    assert logreg.statuses == [RunStatus.FINISHED, RunStatus.FINISHED]
    assert logreg.primary is not None
    assert logreg.primary.mean == 0.75 and logreg.primary.n == 2
    assert logreg.identical_seeds is True
    assert logreg.created_by == "human" and logreg.created_at == scene - timedelta(minutes=120)
    best = ideas["bbbb@c1"]
    assert best.best_band is not None and best.best_band == best.test_interval
    assert best.best_band.lo == pytest.approx(WILSON_4_OF_4_LO, abs=1e-6)
    assert best.best_band.hi == pytest.approx(1.0)
    assert logreg.best_band == best.test_interval
    assert ideas["cccc@c1"].statuses == [RunStatus.RUNNING] and ideas["cccc@c1"].primary is None
    assert ideas["9999@c1"].best_band is None  # exploratory runs have no leaderboard
    assert ideas["eeee@c1"].identical_seeds is False and ideas["eeee@c1"].test_interval is None


def test_running_failures_counts_and_headline(ctx: Context, scene: datetime) -> None:
    summary = build_overview(ctx)
    assert [r.run_id for r in summary.running] == ["r1"]
    assert [(f.run_id, f.exit_code, f.retried_ok) for f in summary.failures] == [
        ("f2", 1, False),
        ("f1", 2, True),
    ]
    assert summary.failures[1].label == "SVM"
    assert summary.failures[0].stderr_path == str(
        ctx.layout.run_dir("toy", "f2") / "logs" / "stderr.log"
    )
    assert summary.counts == {
        "total": 8,
        "queued": 0,
        "running": 1,
        "finished": 5,
        "failed": 2,
        "killed": 0,
        "lost": 0,
        "archived": 1,
        "agent": 2,
        "human": 6,
    }
    # The newest scored idea is bbbb@c1 (SVM, 1.0), so the focus task is toy-acc and its
    # leaderboard goes in as board=. Runner-up aaaa@c1 (0.75) has 1 discordant example
    # (ex-3: SVM right, logreg wrong): sign_test(1, 0) = 1.0 -> "p = 1.00".
    board = q.get_leaderboard(ctx, "toy-acc", "toy")
    assert summary.headline == overview_headline(summary, board=board)
    assert summary.headline == "1 running. SVM leads toy-acc by 0.250, p = 1.00"


def test_headline_without_scored_ideas_has_no_board(ctx: Context, toy_repo: Path) -> None:
    now = utcnow()
    _run(ctx, toy_repo, "r1", ago=timedelta(minutes=5), now=now, status=RunStatus.RUNNING)
    summary = build_overview(ctx)
    assert summary.headline == overview_headline(summary) == "1 running. No scored runs yet"


def test_projects_table_counts_finished_runs_and_best(ctx: Context, scene: datetime) -> None:
    rows = [(p.project, p.task, p.runs, p.best, p.kind) for p in build_overview(ctx).projects]
    # finished, unarchived runs of toy-acc: a1, a2, b1, o1
    assert rows == [
        ("toy", "toy-acc", 4, 1.0, "generic"),
        ("toy", "toy-broken", 0, None, "generic"),
    ]


def test_ideas_and_projects_carry_the_primary_unit(ctx: Context, toy_repo: Path) -> None:
    config = yaml.safe_load((toy_repo / "hypothex.yaml").read_text())
    config["metrics"]["accuracy"]["unit"] = "pts"
    (toy_repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    now = utcnow()
    _run(ctx, toy_repo, "a1", ago=timedelta(minutes=5), now=now, correct=[True, False])
    _run(ctx, toy_repo, "n1", ago=timedelta(minutes=4), now=now, task=None)
    summary = build_overview(ctx)
    assert {(i.task, i.unit) for i in summary.ideas} == {("toy-acc", "pts"), (None, "")}
    # both tasks rank by accuracy, so both carry its unit
    assert [(p.task, p.unit) for p in summary.projects] == [
        ("toy-acc", "pts"),
        ("toy-broken", "pts"),
    ]


def test_since_widens_window_and_naive_since_is_utc(ctx: Context, scene: datetime) -> None:
    wide = build_overview(ctx, since=scene - timedelta(days=4))
    assert wide.timeline[0].run_id == "o1" and wide.counts["total"] == 9
    naive = (scene - timedelta(minutes=25)).replace(tzinfo=None)
    narrow = build_overview(ctx, since=naive)
    assert [t.run_id for t in narrow.timeline] == ["x1", "e1", "r1"]
    assert narrow.failures == []


def test_retry_by_parent_counts_as_retried(ctx: Context, toy_repo: Path) -> None:
    now = utcnow()
    _run(
        ctx,
        toy_repo,
        "p1",
        ago=timedelta(minutes=50),
        now=now,
        status=RunStatus.FAILED,
        config_hash="sha256:1111",
        exit_code=137,
        hypothesis="first try",
    )
    _run(
        ctx,
        toy_repo,
        "p2",
        ago=timedelta(minutes=40),
        now=now,
        config_hash="sha256:2222",
        hypothesis="second try",
        parent="p1",
    )
    _run(
        ctx,
        toy_repo,
        "l1",
        ago=timedelta(minutes=30),
        now=now,
        status=RunStatus.LOST,
        config_hash="sha256:3333",
        hypothesis="lost one",
    )
    failures = build_overview(ctx).failures
    assert [(f.run_id, f.retried_ok) for f in failures] == [("l1", False), ("p1", True)]


def test_empty_home(ctx: Context) -> None:
    summary = build_overview(ctx)
    assert summary.timeline == [] and summary.ideas == [] and summary.projects == []
    assert summary.counts["total"] == 0 and summary.running == []


def test_overview_sums_cost_in_the_window_and_today(ctx: Context, toy_repo: Path) -> None:
    now = utcnow()
    _run(
        ctx,
        toy_repo,
        "c1",
        ago=timedelta(minutes=30),
        now=now,
        ended_at=now,
        cost=CostTotals(gpu_usd=1.0, api_usd=0.5, total_usd=1.5),
    )
    _run(
        ctx,
        toy_repo,
        "c2",
        ago=timedelta(days=3),
        now=now,
        ended_at=now - timedelta(days=3),
        cost=CostTotals(total_usd=9.0),
    )
    summary = build_overview(ctx)
    assert summary.cost_usd == 1.5  # c2 was created before the 24 h window
    assert summary.cost_today_usd == 1.5


def test_headline_counts_queued_runs_as_waiting(ctx: Context, toy_repo: Path) -> None:
    # UI-F5a: 2 queued runs and 1 running run read "3 running." before the fix
    now = utcnow()
    _run(ctx, toy_repo, "q1", ago=timedelta(minutes=3), now=now, status=RunStatus.QUEUED)
    _run(ctx, toy_repo, "q2", ago=timedelta(minutes=2), now=now, status=RunStatus.QUEUED)
    _run(ctx, toy_repo, "r1", ago=timedelta(minutes=1), now=now, status=RunStatus.RUNNING)
    summary = build_overview(ctx)
    assert [r.run_id for r in summary.running] == ["r1", "q2", "q1"]
    assert (summary.counts["running"], summary.counts["queued"]) == (1, 2)
    assert summary.headline == "1 running, 2 waiting. No scored runs yet"
