from pathlib import Path
from typing import Any

import pytest

from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.errors import StoreError
from hypothex.core.records import RunRecord, RunStatus
from hypothex.demo import (
    _SEEDERS,
    DEMO_EPOCH,
    DEMO_TASKS,
    _fixed,
    _js_round,
    _mulberry32,
    _seed_demo,
    seed_demo,
)

REFS = {
    "generic": "toy-classifier/toy-test",
    "training": "rxn-forward/uspto-forward-top1",
    "agent_eval": "retro-agents/retro-bench-200",
    "agent_iteration": "retro-agent/retro-bench-200",
    "system_bench": "route-search/route-api-latency",
}


@pytest.fixture(scope="module")
def demo_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One home seeded with every kind implemented so far (fixed anchor)."""
    home = tmp_path_factory.mktemp("demo")
    _seed_demo(home, list(_SEEDERS), DEMO_EPOCH)
    return home


@pytest.fixture
def dctx(demo_home: Path) -> Context:
    return Context.open(demo_home)


def _runs(ctx: Context, project: str) -> list[RunRecord]:
    """All runs of a project, oldest first."""
    runs = ctx.index.list_runs(project=project, include_archived=True, limit=None)
    return sorted(runs, key=lambda r: (r.created_at, r.run_id))


def _find(runs: list[RunRecord], seed: int | None = None, **params: str) -> RunRecord:
    """The one run with this seed and these params."""
    hits = [
        r
        for r in runs
        if (seed is None or r.seed == seed) and all(r.params.get(k) == v for k, v in params.items())
    ]
    assert len(hits) == 1, [r.run_id for r in hits]
    return hits[0]


def test_js_parity_helpers() -> None:
    # first three draws of mulberry32(20260927), printed by bun from the mockup's function
    draw = _mulberry32(20260927)
    assert [draw(), draw(), draw()] == [0.5817536343820393, 0.3177114331629127, 0.3009456454310566]
    assert _fixed(12.25, 1) == 12.3  # JS (12.25).toFixed(1) === "12.3"
    assert _js_round(-2.5) == -2 and _js_round(2.5) == 3  # JS Math.round


def test_generic_mirrors_ui_v4(dctx: Context) -> None:
    board = q.get_leaderboard(dctx, REFS["generic"])
    assert board.kind == "generic"
    # ui-v4/data.js: SVM 166/180, rf 158/160/160 of 180, knn 156/180, logreg 149/180
    assert [row.primary.mean for row in board.rows if row.primary] == pytest.approx(
        [166 / 180, 478 / 540, 156 / 180, 149 / 180]
    )
    assert board.rows[1].primary is not None
    assert board.rows[1].primary.std == pytest.approx(0.006415002990995819)  # ui-v4 rf std
    assert [row.n for row in board.rows] == [3, 3, 3, 3]
    assert board.rows[0].identical_seeds and not board.rows[1].identical_seeds
    rf3, svm3 = board.rows[1].run_ids[2], board.rows[0].run_ids[2]
    diff = q.compare_examples(dctx, rf3, svm3, "accuracy")
    assert diff.fixed == [
        "test-0", "test-110", "test-116", "test-12", "test-156", "test-177", "test-21",
        "test-63", "test-83",
    ]  # fmt: skip
    assert diff.broken == ["test-137", "test-167", "test-30"]
    assert (diff.both_pass, diff.both_fail) == (157, 11)
    failed = [r for r in _runs(dctx, "toy-classifier") if r.status == RunStatus.FAILED]
    assert [(r.seed, r.exit_code, r.archived) for r in failed] == [
        (1, 2, True),
        (2, 2, True),
        (3, 2, True),
    ]
    stderr = q.read_log(dctx, failed[0].run_id, "stderr").text
    assert "invalid choice: 'svm'" in stderr
    assert "net +6/180" in q.show_run(dctx, svm3).notes


def test_same_anchor_gives_same_data(demo_home: Path, tmp_path: Path) -> None:
    _seed_demo(tmp_path / "again", list(_SEEDERS), DEMO_EPOCH)
    first, second = Context.open(demo_home), Context.open(tmp_path / "again")
    for kind in _SEEDERS:
        project = DEMO_TASKS[kind][0]
        a, b = _runs(first, project), _runs(second, project)
        assert [r.run_id for r in a] == [r.run_id for r in b]
        for ra, rb in zip(a, b, strict=True):
            assert ra.usage == rb.usage
            assert ra.artifacts == rb.artifacts
            da, db = first.run_dir(ra), second.run_dir(rb)
            written = ["scores.jsonl", "predictions/*.jsonl", "samples/*.jsonl", "traces/*.jsonl"]
            files = sorted(p.relative_to(da) for pattern in written for p in da.glob(pattern))
            assert files == sorted(
                p.relative_to(db) for pattern in written for p in db.glob(pattern)
            )
            for rel in files:
                assert (da / rel).read_bytes() == (db / rel).read_bytes(), rel
            pa = first.store.read_metric_points(project, ra.run_id)
            pb = second.store.read_metric_points(project, rb.run_id)
            assert [(p.name, p.step, p.value) for p in pa] == [
                (p.name, p.step, p.value) for p in pb
            ]


def test_refuses_existing_project_and_unknown_kind(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bad: list[Any] = ["generic", "nope"]
    with pytest.raises(ValueError, match="unknown demo kinds"):
        seed_demo(home, bad)
    assert not home.exists()
    assert seed_demo(home, ["generic", "generic"]) == {"generic": REFS["generic"]}
    ctx = Context.open(home)
    before = len(ctx.index.list_runs(include_archived=True, limit=None))
    with pytest.raises(StoreError, match="already exists"):
        seed_demo(home, ["generic"])
    assert len(ctx.index.list_runs(include_archived=True, limit=None)) == before
