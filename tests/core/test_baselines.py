import math
from datetime import timedelta
from typing import Any

import pytest

from hypothex.core.config import BaselineSpec, ProjectConfig
from hypothex.core.ids import utcnow
from hypothex.core.leaderboard import baseline_url, build_leaderboard
from hypothex.core.records import GitInfo, RunRecord, RunStatus, ScoreRecord
from tests.factories import make_record

T0 = utcnow()


def config(baselines: list[dict[str, Any]], primary: str = "acc") -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "project": "toy",
            "datasets": {"d": {"version": "v1", "path": "x"}},
            "metrics": {
                "acc": {"version": "v2", "fn": "m:acc"},
                "loss": {"version": "v1", "fn": "m:loss", "higher_is_better": False},
            },
            "tasks": {
                "t": {
                    "dataset": "d",
                    "metrics": ["acc", "loss"],
                    "primary": primary,
                    "baselines": baselines,
                }
            },
        }
    )


HE = {
    "name": "He 2016",
    "values": {"acc": 0.9, "loss/value": 1.2},
    "std": {"acc": 0.01},
    "source": "arXiv:1512.03385",
    "metric_version_equivalent": {"acc": "v2"},
}
LEE = {
    "name": "Lee",
    "values": {"acc": 0.95},
    "source": "doi:10.1000/xyz",
    "metric_version_equivalent": "v1",
}


def runs_and_scores(
    metric: str, groups: dict[str, list[float]]
) -> tuple[list[RunRecord], dict[str, list[ScoreRecord]]]:
    runs: list[RunRecord] = []
    scores: dict[str, list[ScoreRecord]] = {}
    for group, values in groups.items():
        for i, value in enumerate(values):
            rid = f"{group}{i}"
            runs.append(
                make_record(
                    rid,
                    status=RunStatus.FINISHED,
                    config_hash=f"sha256:{group}",
                    git=GitInfo(commit="c1"),
                    created_at=T0 + timedelta(minutes=i),
                )
            )
            version = "v2" if metric == "acc" else "v1"
            score = ScoreRecord(
                metric=metric, version=version, key="value", value=value, created_at=T0
            )
            scores[rid] = [score]
    return runs, scores


def test_valid_baselines_parse() -> None:
    task = config([HE, LEE]).tasks["t"]
    assert [b.name for b in task.baselines] == ["He 2016", "Lee"]
    assert task.baselines[0].equivalent_version("acc") == "v2"
    assert task.baselines[0].equivalent_version("loss") is None
    assert task.baselines[1].equivalent_version("loss") == "v1"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"values": {"f1": 0.5}}, "unknown metric 'f1'"),
        ({"std": {"loss/p90": 0.1}}, "std without a value: loss/p90"),
        ({"metric_version_equivalent": {"f1": "v1"}}, "metric_version_equivalent names 'f1'"),
        ({"values": {"acc": math.nan}}, "finite number"),
        ({"source": "my paper"}, "should match pattern"),
    ],
)
def test_bad_baselines_are_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        config([{**HE, **change}])


def test_duplicate_names_are_refused() -> None:
    with pytest.raises(ValueError, match="baseline name 'He 2016' is repeated"):
        config([HE, HE])


def test_baseline_url() -> None:
    assert baseline_url("arXiv:1512.03385") == "https://arxiv.org/abs/1512.03385"
    assert baseline_url("doi:10.1000/xyz") == "https://doi.org/10.1000/xyz"
    assert baseline_url("https://example.org/p") == "https://example.org/p"
    assert BaselineSpec.model_validate(HE).source == "arXiv:1512.03385"


def test_leaderboard_lists_baselines_after_the_groups() -> None:
    runs, scores = runs_and_scores("acc", {"a": [0.92, 0.93], "b": [0.85]})
    board = build_leaderboard("toy", "t", config([HE, LEE]), runs, scores)
    assert [r.group_id[:1] for r in board.rows] == ["a", "b"]
    he, lee = board.baselines
    assert he.values == {"acc/value": 0.9, "loss/value": 1.2} and he.std == {"acc/value": 0.01}
    assert he.source_url == "https://arxiv.org/abs/1512.03385"
    assert he.version_match == {"acc": True, "loss": False}
    assert lee.version_match == {"acc": False, "loss": True}
    assert he.primary == 0.9 and he.delta_vs_best == pytest.approx(0.025)
    assert lee.delta_vs_best == pytest.approx(-0.025)
    assert all(r.vs_best is None or r.vs_best.delta <= 0 for r in board.rows)


def test_lower_is_better_delta_is_positive_when_we_win() -> None:
    runs, scores = runs_and_scores("loss", {"a": [1.0]})
    board = build_leaderboard("toy", "t", config([HE], primary="loss"), runs, scores)
    assert board.baselines[0].delta_vs_best == pytest.approx(0.2)


def test_empty_board_has_baselines_without_delta() -> None:
    board = build_leaderboard("toy", "t", config([HE]), [], {})
    assert board.rows == [] and board.baselines[0].delta_vs_best is None


def test_baselines_do_not_change_ranked_groups_or_statistics() -> None:
    runs, scores = runs_and_scores("acc", {"a": [0.92, 0.93], "b": [0.85, 0.86]})
    plain = build_leaderboard("toy", "t", config([]), runs, scores)
    papers = build_leaderboard("toy", "t", config([HE, LEE]), runs, scores)
    assert papers.model_dump(exclude={"baselines"}) == plain.model_dump(exclude={"baselines"})


def test_selected_key_and_version_control_baseline_values() -> None:
    baseline = {**HE, "values": {"acc": 0.9, "acc/p95": 0.7}, "std": {}}
    cfg = config([baseline])
    runs, scores = runs_and_scores("acc", {"a": [0.8]})
    scores["a0"].append(
        ScoreRecord(metric="acc", version="v2", key="p95", value=0.6, created_at=T0)
    )
    board = build_leaderboard("toy", "t", cfg, runs, scores, primary="acc/p95")
    assert board.baselines[0].primary == 0.7
    assert board.baselines[0].delta_vs_best == pytest.approx(-0.1)
    assert board.baselines[0].version_match["acc"]
    older = build_leaderboard("toy", "t", cfg, [], {}, versions={"acc": "v1"})
    assert older.baselines[0].version_match["acc"] is False
    assert older.baselines[0].delta_vs_best is None
    cfg.tasks["t"].baselines[0].values.pop("acc/p95")
    missing = build_leaderboard("toy", "t", cfg, runs, scores, primary="acc/p95")
    assert missing.baselines[0].primary is None
    assert missing.baselines[0].delta_vs_best is None


def test_missing_version_declarations_never_match() -> None:
    from hypothex.core.leaderboard import baseline_rows

    cfg = config([{**HE, "metric_version_equivalent": {}}])
    board = build_leaderboard("toy", "t", cfg, [], {})
    board.metric_versions.clear()
    assert baseline_rows(cfg.tasks["t"], board)[0].version_match == {"acc": False, "loss": False}


@pytest.mark.parametrize("field", ["values", "std"])
@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_nonfinite_baseline_numbers_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValueError, match="finite number"):
        config([{**HE, field: {"acc": value}}])
