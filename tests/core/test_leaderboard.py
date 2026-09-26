from datetime import timedelta

import pytest

from hypothex.core.config import ProjectConfig
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import build_leaderboard
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord
from tests.factories import make_record

CFG = ProjectConfig.model_validate(
    {
        "project": "toy",
        "datasets": {"d": {"version": "v1", "path": "x"}},
        "metrics": {
            "acc": {"version": "v2", "fn": "m:acc"},
            "loss": {"version": "v1", "fn": "m:loss", "higher_is_better": False},
        },
        "tasks": {
            "t": {"dataset": "d", "metrics": ["acc"], "primary": "acc"},
            "tl": {"dataset": "d", "metrics": ["loss"], "primary": "loss"},
        },
    }
)
T0 = utcnow()


def run(
    rid: str,
    group: str,
    *,
    task: str = "t",
    status: RunStatus = RunStatus.FINISHED,
    archived: bool = False,
    minute: int = 0,
) -> RunRecord:
    return make_record(
        rid,
        task=task,
        status=status,
        archived=archived,
        config_hash=f"sha256:{group}",
        git=GitInfo(commit="c1"),
        created_at=T0 + timedelta(minutes=minute),
    )


def score(
    metric: str, value: float | None, version: str = "v2", error: str | None = None
) -> ScoreRecord:
    return ScoreRecord(
        metric=metric, version=version, key="value", value=value, error=error, created_at=utcnow()
    )


def test_groups_sorts_and_flags() -> None:
    runs, scores = [], {}
    for i, v in enumerate([0.80, 0.82, 0.81]):
        runs.append(run(f"a{i}", "a", minute=i))
        scores[f"a{i}"] = [score("acc", v)]
    for i, v in enumerate([0.800, 0.805, 0.810]):  # mean 0.805, CI overlaps group a
        runs.append(run(f"b{i}", "b"))
        scores[f"b{i}"] = [score("acc", v)]
    for i, v in enumerate([0.70, 0.71, 0.69]):
        runs.append(run(f"c{i}", "c"))
        scores[f"c{i}"] = [score("acc", v)]
    runs += [
        run("stale", "d"),
        run("none", "e"),
        run("fail", "f", status=RunStatus.FAILED),
        run("arch", "g", archived=True),
    ]
    scores["stale"] = [score("acc", 0.99, version="v1")]
    scores["fail"] = [score("acc", 1.0)]
    scores["arch"] = [score("acc", 1.0)]

    board = build_leaderboard("toy", "t", CFG, runs, scores)

    assert board.metric_versions == {"acc": "v2"} and board.primary == "acc/value"
    assert [r.config_hash for r in board.rows] == ["sha256:a", "sha256:b", "sha256:c"]
    best, second, third = board.rows
    assert best.n == 3 and best.latest_run_id == "a2" and not best.single_seed
    assert best.scores["acc/value"].mean == pytest.approx(0.81)
    assert second.within_noise_of_best is True
    assert third.within_noise_of_best is False
    assert board.needs_reeval == ["stale"]
    assert board.unscored == ["none"]


def test_lower_is_better() -> None:
    runs = [run("x", "x", task="tl"), run("y", "y", task="tl")]
    scores = {"x": [score("loss", 0.2, version="v1")], "y": [score("loss", 0.1, version="v1")]}
    board = build_leaderboard("toy", "tl", CFG, runs, scores)
    assert [r.run_ids for r in board.rows] == [["y"], ["x"]]
    assert board.rows[0].single_seed and board.rows[1].within_noise_of_best is None


def test_leaderboard_ignores_error_scores() -> None:
    runs = [run("ok", "a"), run("err", "b")]
    scores = {"ok": [score("acc", 0.5)], "err": [score("acc", None, error="Traceback...")]}
    board = build_leaderboard("toy", "t", CFG, runs, scores)
    assert [r.run_ids for r in board.rows] == [["ok"]]
    assert board.unscored == ["err"]


def test_version_override_and_latest_score_wins() -> None:
    runs = [run("r", "a")]
    scores = {"r": [score("acc", 0.1, version="v1"), score("acc", 0.3, version="v1")]}
    board = build_leaderboard("toy", "t", CFG, runs, scores, versions={"acc": "v1"})
    assert board.rows[0].scores["acc/value"].mean == 0.3
    assert board.metric_versions == {"acc": "v1"}
