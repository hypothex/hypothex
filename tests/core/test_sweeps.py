"""Tests for hypothex.core.sweeps: expansion, storage, summary, launch, cancel, extend."""

from __future__ import annotations

import math
import time
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hypothex.core.context import Context
from hypothex.core.errors import StoreError
from hypothex.core.ids import utcnow
from hypothex.core.records import (
    CostTotals,
    GitInfo,
    RunRecord,
    RunStatus,
    ScoreRecord,
    UsageTotals,
)
from hypothex.core.seeds import config_hash
from hypothex.core.sweeps import (
    SweepParam,
    SweepSpec,
    expand,
    list_sweeps,
    load_sweep,
    new_sweep_id,
    parse_sweep_tag,
    planned_runs,
    save_sweep,
    summarize_sweep,
    sweep_combos,
    sweep_path,
    sweep_tag,
)
from tests.factories import make_record, write_toy_project

NOW = "2026-10-03T09:12:00Z"


def spec_of(**overrides: object) -> SweepSpec:
    base: dict[str, object] = {
        "id": "s-0001",
        "project": "toy",
        "task": "toy-acc",
        "host": None,
        "grid": [{"name": "lr", "values": ["1e-4", "3e-4"]}],
        "seeds": [1, 2],
        "command_template": ["python", "train.py", "--lr", "{lr}", "--seed", "{seed}"],
        "created_by": "human",
        "created_at": NOW,
    }
    base.update(overrides)
    return SweepSpec.model_validate(base)


# --------------------------------------------------------------------------- Task 37 expand
def test_grid_product_in_param_order() -> None:
    spec = spec_of(
        grid=[
            {"name": "lr", "values": ["1e-4", "3e-4"]},
            {"name": "beam", "values": ["1", "5", "10"]},
        ]
    )
    assert expand(spec) == [
        {"lr": "1e-4", "beam": "1"},
        {"lr": "1e-4", "beam": "5"},
        {"lr": "1e-4", "beam": "10"},
        {"lr": "3e-4", "beam": "1"},
        {"lr": "3e-4", "beam": "5"},
        {"lr": "3e-4", "beam": "10"},
    ]
    assert planned_runs(spec) == 12


def test_numbers_in_values_become_strings() -> None:
    param = SweepParam.model_validate({"name": "beam", "values": [1, 5]})
    assert param.values == ["1", "5"]


def test_no_params_gives_one_empty_combination() -> None:
    assert expand(spec_of(grid=[])) == [{}]


def test_log_samples_are_seeded_and_inside_the_range() -> None:
    spec = spec_of(grid=[{"name": "lr", "low": 1e-5, "high": 1e-2, "log": True}], random=4)
    first = expand(spec, rng_seed=0)
    assert first == expand(spec, rng_seed=0)
    assert first != expand(spec, rng_seed=1)
    assert first == [
        {"lr": "0.003414"},
        {"lr": "0.001879"},
        {"lr": "0.0001827"},
        {"lr": "5.981e-05"},
    ]
    assert all(1e-5 <= float(c["lr"]) <= 1e-2 for c in first)
    assert planned_runs(spec) == 8


def test_log_scale_spreads_over_decades() -> None:
    spec = spec_of(grid=[{"name": "lr", "low": 1e-6, "high": 1.0, "log": True}], random=200)
    values = [float(c["lr"]) for c in expand(spec, rng_seed=3)]
    below = sum(v < 1e-3 for v in values)
    # log-uniform puts half the mass below the geometric mean 1e-3; uniform would put ~0.1%
    assert 70 <= below <= 130


def test_random_samples_are_shared_by_every_grid_cell() -> None:
    spec = spec_of(
        grid=[
            {"name": "beam", "values": ["1", "5"]},
            {"name": "dropout", "low": 0.0, "high": 0.5},
        ],
        random=2,
    )
    combos = expand(spec, rng_seed=0)
    assert combos == [
        {"beam": "1", "dropout": "0.4222"},
        {"beam": "1", "dropout": "0.379"},
        {"beam": "5", "dropout": "0.4222"},
        {"beam": "5", "dropout": "0.379"},
    ]


def test_random_without_ranges_keeps_n_grid_combinations() -> None:
    spec = spec_of(
        grid=[
            {"name": "lr", "values": ["1", "2", "3"]},
            {"name": "beam", "values": ["a", "b", "c"]},
        ],
        random=4,
    )
    combos = expand(spec, rng_seed=0)
    assert combos == [
        {"lr": "1", "beam": "a"},
        {"lr": "1", "beam": "c"},
        {"lr": "3", "beam": "a"},
        {"lr": "3", "beam": "c"},
    ]
    assert expand(spec_of(grid=spec.grid, random=99)) == expand(spec_of(grid=spec.grid))


def test_sweep_combos_depend_on_the_sweep_id() -> None:
    grid = [{"name": "lr", "low": 1e-5, "high": 1e-2, "log": True}]
    a = spec_of(id="s-aaaa", grid=grid, random=3)
    b = spec_of(id="s-bbbb", grid=grid, random=3)
    assert sweep_combos(a) == sweep_combos(a)
    assert sweep_combos(a) != sweep_combos(b)


@pytest.mark.parametrize(
    ("param", "message"),
    [
        ({"name": "lr", "values": ["1"], "low": 0.1, "high": 1.0}, "not both"),
        ({"name": "lr"}, "give values, or both low and high"),
        ({"name": "lr", "low": 0.1}, "give values, or both low and high"),
        ({"name": "lr", "values": []}, "non-empty"),
        ({"name": "lr", "values": ["1", ""]}, "non-empty"),
        ({"name": "lr", "values": ["1", "1"]}, "duplicate values"),
        ({"name": "lr", "values": ["1"], "log": True}, "log applies to low/high only"),
        ({"name": "lr", "low": 1.0, "high": 1.0}, "low must be below high"),
        ({"name": "lr", "low": 0.0, "high": 1.0, "log": True}, "log scale needs low > 0"),
        ({"name": "lr", "low": 0.0, "high": float("inf")}, "finite"),
        ({"name": "seed", "values": ["1"]}, "reserved"),
        ({"name": "run_dir", "values": ["1"]}, "reserved"),
        ({"name": "1lr", "values": ["1"]}, "pattern"),
        ({"name": "lr", "low": 1e-5, "high": 1e-2, "log_scale": True}, "Extra inputs"),
        ({"name": "lr", "values": ["1"], "scale": "log"}, "Extra inputs"),
    ],
)
def test_bad_params_are_rejected(param: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        SweepParam.model_validate(param)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"grid": [{"name": "lr", "values": ["1"]}, {"name": "lr", "values": ["2"]}]}, "lr"),
        ({"seeds": [1, 1]}, "duplicate seeds"),
        ({"seeds": []}, "at least 1"),
        ({"grid": [{"name": "lr", "low": 0.1, "high": 1.0}]}, "random=N"),
        ({"random": 0}, "greater than or equal to 1"),
        ({"id": "../etc"}, "pattern"),
        ({"project": "Toy Project"}, "pattern"),
        ({"command_template": []}, "at least 1"),
        ({"gpus": 2}, "Extra inputs"),
    ],
)
def test_bad_specs_are_rejected(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        spec_of(**overrides)


def test_sweep_tag_names_its_owner() -> None:
    env = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
    assert sweep_tag(env, "s-7f3a") == "sweep:0a1b2c3d:s-7f3a"
    assert sweep_tag(env, "s-7f3a") != sweep_tag("ffffffff" + env[8:], "s-7f3a")
    assert parse_sweep_tag("sweep:0a1b2c3d:s-7f3a") == ("0a1b2c3d", "s-7f3a")
    for other in ["sweep:s-7f3a", "best", "sweep::s-7f3a", "sweep:0a1b2c3d:Bad Id"]:
        assert parse_sweep_tag(other) is None


def test_random_subset_of_a_huge_grid_never_builds_the_product() -> None:
    # 10 params x 100 values = 10^20 combinations; random=3 keeps 3 of them
    grid = [{"name": f"p{i}", "values": [str(v) for v in range(100)]} for i in range(10)]
    spec = spec_of(grid=grid, random=3, seeds=[1], command_template=["train"])
    started = time.monotonic()
    combos = expand(spec, rng_seed=7)
    assert time.monotonic() - started < 1
    assert len(combos) == 3 and all(list(c) == [f"p{i}" for i in range(10)] for c in combos)
    assert expand(spec, rng_seed=7) == combos
    assert planned_runs(spec) == 3


def test_random_subset_decodes_the_same_combinations_as_the_product() -> None:
    grid = [{"name": "a", "values": ["1", "2", "3"]}, {"name": "b", "values": ["x", "y"]}]
    spec = spec_of(grid=grid, random=4, seeds=[1], command_template=["train"])
    full = expand(spec_of(grid=grid, seeds=[1], command_template=["train"]))
    subset = expand(spec, rng_seed=3)
    assert len(subset) == 4 and all(c in full for c in subset)
    assert subset == sorted(subset, key=full.index)  # grid order is kept


# --------------------------------------------------------------------------- Task 38 storage
def test_save_and_load_round_trip(ctx: Context) -> None:
    spec = spec_of()
    path = save_sweep(ctx.layout, spec)
    assert path == ctx.layout.store / "toy" / "sweeps" / "s-0001.yaml"
    assert load_sweep(ctx.layout, "toy", "s-0001") == spec
    assert "run_ids" not in path.read_text()  # the definition only: members are tagged runs
    with pytest.raises(ValidationError):
        spec_of(run_ids=["r1"])


def test_load_missing_sweep_is_a_store_error(ctx: Context) -> None:
    with pytest.raises(StoreError, match="unknown sweep 's-9999' in project 'toy'"):
        load_sweep(ctx.layout, "toy", "s-9999")


@pytest.mark.parametrize(
    ("project", "sweep_id"), [("toy", "../x"), ("../toy", "s-1"), ("toy", "s-1\n")]
)
def test_unsafe_names_never_build_a_path(ctx: Context, project: str, sweep_id: str) -> None:
    with pytest.raises(StoreError, match="unknown sweep"):
        sweep_path(ctx.layout, project, sweep_id)


@pytest.mark.parametrize(
    "text", ["grid: [\n", "id: s-0001\nproject: toy\n", "- just\n- a list\n", ""]
)
def test_corrupt_sweep_file_is_a_store_error(ctx: Context, text: str) -> None:
    path = sweep_path(ctx.layout, "toy", "s-0001")
    path.parent.mkdir(parents=True)
    path.write_text(text)
    with pytest.raises(StoreError, match="unreadable sweep file"):
        load_sweep(ctx.layout, "toy", "s-0001")


def test_file_under_the_wrong_name_is_a_store_error(ctx: Context) -> None:
    save_sweep(ctx.layout, spec_of(id="s-0001"))
    src = sweep_path(ctx.layout, "toy", "s-0001")
    src.rename(src.with_name("s-0002.yaml"))
    with pytest.raises(StoreError, match="holds toy/s-0001"):
        load_sweep(ctx.layout, "toy", "s-0002")


def test_new_sweep_id_reserves_a_fresh_file(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = iter(["abcd", "abcd", "beef"])
    monkeypatch.setattr("hypothex.core.sweeps.secrets.token_hex", lambda n: next(tokens))
    assert new_sweep_id(ctx.layout, "toy") == "s-abcd"
    assert new_sweep_id(ctx.layout, "toy") == "s-beef"
    assert sweep_path(ctx.layout, "toy", "s-abcd").read_text() == ""
    assert sweep_path(ctx.layout, "toy", "s-beef").is_file()


# --------------------------------------------------------------------------- Task 39 summary
def add_run(
    ctx: Context,
    run_id: str,
    lr: str,
    seed: int,
    status: RunStatus,
    value: float | None = None,
    *,
    sweep: str = "s-0001",
    owner: str | None = None,
    cost_usd: float | None = None,
    usage_usd: float | None = None,
    commit: str | None = None,
) -> RunRecord:
    record = make_record(
        run_id,
        project="toy",
        task="toy-acc",
        params={"lr": lr},
        vars={"lr": lr},
        seed=seed,
        tags=[sweep_tag(owner or ctx.descriptor.environment_id, sweep)],
        status=status,
        config_hash=config_hash({"params": {"lr": lr}}),
        environment_id=ctx.descriptor.environment_id,
        cost=CostTotals(total_usd=cost_usd) if cost_usd is not None else None,
        usage=UsageTotals(usd=usage_usd) if usage_usd is not None else None,
        git=GitInfo(commit=commit),
    )
    ctx.create_run(record)
    if value is not None:
        ctx.add_score(
            record,
            ScoreRecord(
                metric="accuracy", version="v1", key="value", value=value, created_at=utcnow()
            ),
        )
    return record


@pytest.fixture
def toy_sweep(ctx: Context, toy_repo: Path) -> SweepSpec:
    """lr 1e-4 / 3e-4 / 1e-3 x seeds 1, 2; 1e-3 still queued/running."""
    ctx.register_project(toy_repo)
    spec = spec_of(grid=[{"name": "lr", "values": ["1e-4", "3e-4", "1e-3"]}])
    save_sweep(ctx.layout, spec)
    add_run(ctx, "a1", "1e-4", 1, RunStatus.FINISHED, 0.70, cost_usd=1.25)
    add_run(ctx, "b1", "3e-4", 1, RunStatus.FINISHED, 0.80, cost_usd=1.25)
    add_run(ctx, "c1", "1e-3", 1, RunStatus.RUNNING, usage_usd=0.5)
    add_run(ctx, "a2", "1e-4", 2, RunStatus.FINISHED, 0.74, cost_usd=1.0)
    add_run(ctx, "b2", "3e-4", 2, RunStatus.FINISHED, 0.84, cost_usd=1.0)
    add_run(ctx, "c2", "1e-3", 2, RunStatus.QUEUED)
    return spec


def test_summary_counts_cells_best_and_cost(ctx: Context, toy_sweep: SweepSpec) -> None:
    summary = summarize_sweep(ctx, "toy", "s-0001")
    assert summary.spec == toy_sweep
    assert summary.counts == {
        "queued": 1,
        "running": 1,
        "finished": 4,
        "failed": 0,
        "killed": 0,
        "lost": 0,
        "total": 6,
    }
    assert sorted(summary.run_ids) == ["a1", "a2", "b1", "b2", "c1", "c2"]
    assert [c["params"] for c in summary.cells] == [{"lr": "1e-4"}, {"lr": "3e-4"}, {"lr": "1e-3"}]
    low, high, pending = summary.cells
    assert low["run_ids"] == ["a1", "a2"]
    assert low["n"] == 2
    assert low["mean"] == pytest.approx(0.72)
    # t(1) = 12.706, std / sqrt(2) = 0.02 -> half-width 0.25412
    assert low["lo"] == pytest.approx(0.72 - 0.25412)
    assert low["hi"] == pytest.approx(0.72 + 0.25412)
    assert low["std"] == pytest.approx(math.sqrt(0.0008))
    assert high["mean"] == pytest.approx(0.82)
    assert high["group_id"] == config_hash({"params": {"lr": "3e-4"}})[7:15] + "@nogit"
    assert pending["mean"] is None
    assert pending["n"] == 0
    assert pending["group_id"] is None
    assert pending["run_ids"] == ["c1", "c2"]
    assert pending["runs"] == [
        {"run_id": "c1", "status": "running", "seed": 1},
        {"run_id": "c2", "status": "queued", "seed": 2},
    ]
    assert summary.best == high
    assert summary.headline == "lr 3e-4: 0.820 accuracy, +0.100 over lr 1e-4, p = 0.07"
    assert summary.total_usd == pytest.approx(1.25 + 1.25 + 0.5 + 1.0 + 1.0)


def test_headline_p_compares_the_two_cells_it_names(ctx: Context, toy_sweep: SweepSpec) -> None:
    # a third lr 3e-4 run at another commit forms its own group: one run, the board's
    # top row, but not the row the cell shows (the cell keeps its larger group)
    add_run(ctx, "b3", "3e-4", 3, RunStatus.FINISHED, 0.99, commit="c0ffee")
    summary = summarize_sweep(ctx, "toy", "s-0001")
    assert summary.best is not None and summary.best["run_ids"] == ["b1", "b2", "b3"]
    assert summary.best["mean"] == pytest.approx(0.82) and summary.best["n"] == 2
    # the p of lr 3e-4 (b1, b2) against lr 1e-4 (a1, a2), not against the b3 group
    assert summary.headline == "lr 3e-4: 0.820 accuracy, +0.100 over lr 1e-4, p = 0.07"


def test_headline_names_only_the_params_that_differ(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    save_sweep(
        ctx.layout,
        spec_of(
            grid=[
                {"name": "lr", "values": ["1e-4", "3e-4"]},
                {"name": "beam", "values": ["5"]},
            ],
            seeds=[1],
            command_template=["python", "train.py", "{lr}", "{beam}"],
        ),
    )
    for run_id, lr, value in [("x1", "1e-4", 0.6), ("x2", "3e-4", 0.9)]:
        record = make_record(
            run_id,
            project="toy",
            task="toy-acc",
            params={"lr": lr, "beam": "5"},
            seed=1,
            tags=[sweep_tag(ctx.descriptor.environment_id, "s-0001")],
            status=RunStatus.FINISHED,
            config_hash=config_hash({"params": {"lr": lr, "beam": "5"}}),
        )
        ctx.create_run(record)
        ctx.add_score(
            record,
            ScoreRecord(
                metric="accuracy", version="v1", key="value", value=value, created_at=utcnow()
            ),
        )
    summary = summarize_sweep(ctx, "toy", "s-0001")
    assert summary.headline == "lr 3e-4, beam 5: 0.900 accuracy, +0.300 over lr 1e-4"


def test_summary_without_scores_says_so(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    save_sweep(ctx.layout, spec_of())
    add_run(ctx, "q1", "1e-4", 1, RunStatus.QUEUED)
    summary = summarize_sweep(ctx, "toy", "s-0001")
    assert summary.headline == "No scored runs yet"
    assert summary.best is None
    assert summary.counts["queued"] == 1
    assert summary.counts["total"] == 1 and summary.run_ids == ["q1"]
    assert summary.total_usd == 0.0


def test_summary_without_task_has_no_stats(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    save_sweep(ctx.layout, spec_of(task=None))
    add_run(ctx, "a1", "1e-4", 1, RunStatus.FINISHED, 0.7)
    summary = summarize_sweep(ctx, "toy", "s-0001")
    assert summary.best is None
    assert summary.cells[0]["mean"] is None
    assert summary.cells[0]["run_ids"] == ["a1"]
    assert summary.headline == "No scored runs yet"


def test_membership_is_the_sweep_tag(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    save_sweep(ctx.layout, spec_of())
    add_run(ctx, "late", "3e-4", 1, RunStatus.FINISHED, 0.9)
    add_run(ctx, "other", "3e-4", 1, RunStatus.FINISHED, 0.1, sweep="s-0002")
    summary = summarize_sweep(ctx, "toy", "s-0001")
    assert summary.counts["total"] == 1 and summary.run_ids == ["late"]
    assert summary.best is not None
    assert summary.best["run_ids"] == ["late"]
    assert summary.tag == sweep_tag(ctx.descriptor.environment_id, "s-0001")


def test_two_hubs_with_the_same_sweep_id_never_share_runs(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    # hub A (ctx) and hub B both made sweep s-0001 on one host; the host's runs of both
    # are mirrored to both hubs
    other = Context.open(tmp_path / "hub-b")
    assert other.descriptor.environment_id[:8] != ctx.descriptor.environment_id[:8]
    for hub in (ctx, other):
        hub.register_project(toy_repo)
        save_sweep(hub.layout, spec_of())
    for hub in (ctx, other):
        add_run(hub, f"a-{hub is ctx}", "1e-4", 1, RunStatus.FINISHED, 0.7)
        add_run(hub, f"b-{hub is ctx}", "3e-4", 1, RunStatus.FINISHED, 0.9, owner="b0b0b0b0")
    add_run(ctx, "from-b", "3e-4", 2, RunStatus.QUEUED, owner=other.descriptor.environment_id)
    add_run(other, "from-a", "1e-4", 2, RunStatus.QUEUED, owner=ctx.descriptor.environment_id)
    mine = summarize_sweep(ctx, "toy", "s-0001")
    theirs = summarize_sweep(other, "toy", "s-0001")
    assert mine.run_ids == ["a-True"] and mine.counts["total"] == 1
    assert theirs.run_ids == ["a-False"] and theirs.counts["total"] == 1
    assert mine.tag != theirs.tag


def test_lower_is_better_picks_the_smallest_mean(ctx: Context, tmp_path: Path) -> None:
    repo = write_toy_project(tmp_path / "lowtoy")
    config = yaml.safe_load((repo / "hypothex.yaml").read_text())
    config["metrics"]["accuracy"]["higher_is_better"] = False
    (repo / "hypothex.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    ctx.register_project(repo)
    save_sweep(ctx.layout, spec_of(seeds=[1]))
    add_run(ctx, "a1", "1e-4", 1, RunStatus.FINISHED, 0.2)
    add_run(ctx, "b1", "3e-4", 1, RunStatus.FINISHED, 0.5)
    summary = summarize_sweep(ctx, "toy", "s-0001")
    assert summary.best is not None
    assert summary.best["params"] == {"lr": "1e-4"}
    assert summary.headline == "lr 1e-4: 0.200 accuracy, −0.300 over lr 3e-4"


def test_cell_split_across_commits_uses_the_larger_seed_group(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    save_sweep(ctx.layout, spec_of(grid=[{"name": "lr", "values": ["1e-4"]}], seeds=[1, 2, 3]))
    add_run(ctx, "a1", "1e-4", 1, RunStatus.FINISHED, 0.70, commit="c1")
    add_run(ctx, "a2", "1e-4", 2, RunStatus.FINISHED, 0.74, commit="c1")
    add_run(ctx, "a3", "1e-4", 3, RunStatus.FINISHED, 0.90, commit="c2")
    (cell,) = summarize_sweep(ctx, "toy", "s-0001").cells
    assert cell["run_ids"] == ["a1", "a2", "a3"]
    assert cell["n"] == 2
    assert cell["mean"] == pytest.approx(0.72)
    assert cell["group_id"].endswith("@c1")


def test_list_sweeps_newest_first(ctx: Context, toy_sweep: SweepSpec) -> None:
    save_sweep(ctx.layout, spec_of(id="s-0002", created_at="2026-10-04T00:00:00Z"))
    broken = sweep_path(ctx.layout, "toy", "s-0003")
    broken.write_text("grid: [\n")
    rows = list_sweeps(ctx, "toy")
    assert [r["id"] for r in rows] == ["s-0002", "s-0001"]
    assert rows[1]["n_runs"] == 6
    assert rows[1]["best"]["params"] == {"lr": "3e-4"}
    assert rows[0]["best"] is None
    assert list_sweeps(ctx, "nothing-here") == []
