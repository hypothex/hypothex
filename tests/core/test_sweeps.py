"""Tests for hypothex.core.sweeps: expansion, storage, summary, launch, cancel, extend."""

from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

import hypothex.core.sweeps as sweeps_module
from hypothex.core.context import Context
from hypothex.core.control import wait_for_run
from hypothex.core.errors import RunError, StoreError
from hypothex.core.execution import RunRequest
from hypothex.core.ids import utcnow
from hypothex.core.records import (
    CostTotals,
    GitInfo,
    RunRecord,
    RunStatus,
    ScoreRecord,
    UsageTotals,
)
from hypothex.core.scheduler import Scheduler
from hypothex.core.seeds import config_hash
from hypothex.core.sweeps import (
    MAX_SWEEP_RUNS,
    SweepError,
    SweepParam,
    SweepSpec,
    cancel_queued,
    expand,
    extend_sweep,
    launch_sweep,
    list_sweeps,
    load_sweep,
    new_sweep_id,
    parse_sweep_tag,
    planned_runs,
    run_command_id,
    save_sweep,
    stop_if_queued,
    summarize_sweep,
    sweep_combos,
    sweep_path,
    sweep_tag,
    unknown_task_headline,
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
        ({"diff": "diff --git a/x b/x\n"}, "a diff needs the commit"),
        ({"commit": "HEAD; rm -rf /"}, "pattern"),
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


def test_pinned_code_round_trips_and_old_files_pin_nothing(ctx: Context) -> None:
    pinned = spec_of(commit="3b8e06d" * 5 + "abcde", diff="diff --git a/t.py b/t.py\n")
    save_sweep(ctx.layout, pinned)
    assert load_sweep(ctx.layout, "toy", "s-0001") == pinned
    # a file written before sweeps stored their code: no keys, nothing pinned
    path = sweep_path(ctx.layout, "toy", "s-0001")
    old = yaml.safe_load(path.read_text())
    del old["commit"], old["diff"]
    path.write_text(yaml.safe_dump(old))
    loaded = load_sweep(ctx.layout, "toy", "s-0001")
    assert (loaded.commit, loaded.diff) == (None, None)


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


def test_unknown_task_headline() -> None:
    assert unknown_task_headline("toy-acc") == "Unknown task toy-acc: not in the project config"


def test_summary_with_unknown_task_says_so(
    ctx: Context, toy_repo: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # the task was renamed after the sweep ran: the scored runs must not look unscored
    ctx.register_project(toy_repo)
    save_sweep(ctx.layout, spec_of(task="old-name"))
    add_run(ctx, "a1", "1e-4", 1, RunStatus.FINISHED, 0.7)
    with caplog.at_level("WARNING", logger="hypothex.core.sweeps"):
        summary = summarize_sweep(ctx, "toy", "s-0001")
    assert summary.headline == "Unknown task old-name: not in the project config"
    assert summary.best is None
    assert summary.cells[0]["mean"] is None and summary.cells[0]["run_ids"] == ["a1"]
    assert summary.counts["finished"] == 1 and summary.run_ids == ["a1"]
    assert "toy/s-0001 names task 'old-name'" in caplog.text


def test_unreadable_project_file_raises(ctx: Context, toy_sweep: SweepSpec) -> None:
    # a corrupt project file never turns scored runs into "No scored runs yet"
    (ctx.layout.project_dir("toy") / "project.json").write_text("{")
    with pytest.raises(StoreError):
        summarize_sweep(ctx, "toy", "s-0001")
    with pytest.raises(StoreError):
        list_sweeps(ctx, "toy")


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


# --------------------------------------------------------------------------- Task 40 launch
class FakeLauncher:
    """
    A host: creates a queued run per new command id (no process); keeps receipts.

    ``fail_at`` refuses the n-th new run; ``lose_answer_at`` starts the n-th run
    and then fails (its answer was lost); ``mirrored=False`` keeps runs off the
    hub's index until ``mirror_all()``.
    """

    def __init__(
        self,
        ctx: Context,
        fail_at: int | None = None,
        *,
        lose_answer_at: int | None = None,
        mirrored: bool = True,
    ) -> None:
        self.ctx = ctx
        self.fail_at = fail_at
        self.lose_answer_at = lose_answer_at
        self.mirrored = mirrored
        self.requests: list[RunRequest] = []
        self.command_ids: list[str] = []
        self.receipts: dict[str, RunRecord] = {}
        self.unmirrored: list[RunRecord] = []

    def mirror_all(self) -> None:
        for record in self.unmirrored:
            self.ctx.create_run(record)
        self.unmirrored.clear()

    def __call__(self, req: RunRequest, command_id: str) -> RunRecord:
        if command_id in self.receipts:  # a repeat: the run it already started
            return self.receipts[command_id]
        if self.fail_at is not None and len(self.requests) == self.fail_at:
            raise RunError("host refused the run")
        self.requests.append(req)
        self.command_ids.append(command_id)
        record = make_record(
            f"r{len(self.requests):02d}",
            project="toy",
            task=req.task,
            hypothesis=req.hypothesis,
            params=req.params,
            vars=req.vars,
            seed=req.seed,
            tags=sorted(req.tags),
            created_by=req.created_by,
            gpus_requested=req.gpus,
            config_hash=config_hash({"params": req.params}),
            cwd=str(req.repo),
        )
        if self.mirrored:
            record = self.ctx.create_run(record)
        else:
            self.unmirrored.append(record)
        self.receipts[command_id] = record
        if self.lose_answer_at is not None and len(self.requests) == self.lose_answer_at:
            raise RunError("connection reset: the answer was lost")
        return record


LR = SweepParam(name="lr", values=["1e-4", "3e-4"])
BEAM = SweepParam(name="beam", values=["1", "5"])
CMD = ["python", "train.py", "--lr", "{lr}", "--beam", "{beam}", "--seed", "{seed}"]


def test_launch_creates_file_and_one_run_per_cell_and_seed(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    fake = FakeLauncher(ctx)
    summary = launch_sweep(
        ctx,
        project="toy",
        task="toy-acc",
        grid=[LR, BEAM],
        seeds=[1, 2],
        command=CMD,
        hypothesis="lr 3e-4 beats 1e-4",
        gpus=2,
        queue=True,
        created_by="agent:tuner",
        host="gpu1",
        launch=fake,
    )
    sid = summary.spec.id
    assert sid.startswith("s-") and len(sid) == 6
    assert sweep_path(ctx.layout, "toy", sid).is_file()
    assert summary.spec.host == "gpu1"
    assert summary.run_ids == [f"r{i:02d}" for i in range(1, 9)]
    assert len(set(fake.command_ids)) == 8 and all(len(c) == 16 for c in fake.command_ids)
    assert summary.counts["total"] == 8
    assert summary.counts["queued"] == 8
    # seed-major: seed 1 of every cell first
    assert [(r.seed, r.params) for r in fake.requests[:4]] == [
        (1, {"lr": "1e-4", "beam": "1"}),
        (1, {"lr": "1e-4", "beam": "5"}),
        (1, {"lr": "3e-4", "beam": "1"}),
        (1, {"lr": "3e-4", "beam": "5"}),
    ]
    assert [r.seed for r in fake.requests[4:]] == [2, 2, 2, 2]
    first = fake.requests[0]
    assert first.tags == [f"sweep:{ctx.descriptor.environment_id[:8]}:{sid}"]
    assert first.vars == {"lr": "1e-4", "beam": "1"}
    assert first.command == CMD
    assert first.task == "toy-acc"
    assert first.hypothesis == "lr 3e-4 beats 1e-4"
    assert first.created_by == "agent:tuner"
    assert (first.gpus, first.queue) == (2, True)
    assert first.repo == toy_repo.resolve()
    assert [c["run_ids"] for c in summary.cells] == [
        ["r01", "r05"],
        ["r02", "r06"],
        ["r03", "r07"],
        ["r04", "r08"],
    ]


def test_launch_random_sweep_uses_its_own_combos(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    fake = FakeLauncher(ctx)
    summary = launch_sweep(
        ctx,
        project="toy",
        grid=[SweepParam(name="lr", low=1e-5, high=1e-2, log=True)],
        random=3,
        seeds=[7],
        command=["python", "train.py", "{lr}"],
        launch=fake,
    )
    assert [r.params for r in fake.requests] == sweep_combos(summary.spec)
    assert len(fake.requests) == 3
    assert all(r.seed == 7 for r in fake.requests)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"command": ["python", "train.py", "{lrr}"]}, r"command uses \{lrr\}"),
        ({"command": ["python", "{checkpoint}"]}, r"\{checkpoint\}"),
        ({"task": None, "command": ["python", "{dataset.path}"]}, r"\{dataset.path\}"),
        ({"task": "nope"}, "unknown task 'nope'"),
        ({"seeds": []}, "invalid sweep: seeds"),
        ({"grid": [SweepParam(name="lr", low=0.1, high=1.0)]}, "random=N"),
        ({"gpus": -1}, "gpus must be 0 or more"),
        ({"command": ["python", "train.py", "{seed}"]}, r"never uses \{lr\}"),
        (
            {
                "grid": [
                    SweepParam(name="a", values=[str(i) for i in range(40)]),
                    SweepParam(name="b", values=[str(i) for i in range(30)]),
                ],
                "command": ["python", "{a}", "{b}"],
            },
            f"2400 runs; the limit is {MAX_SWEEP_RUNS}",
        ),
    ],
)
def test_invalid_launch_creates_nothing(
    ctx: Context, toy_repo: Path, kwargs: dict[str, Any], message: str
) -> None:
    ctx.register_project(toy_repo)
    fake = FakeLauncher(ctx)
    args: dict[str, Any] = {
        "project": "toy",
        "task": "toy-acc",
        "grid": [LR],
        "seeds": [1, 2],
        "command": ["python", "train.py", "{lr}", "{seed}", "{dataset.path}"],
        "launch": fake,
    }
    args.update(kwargs)
    with pytest.raises(SweepError, match=message):
        launch_sweep(ctx, **args)
    assert fake.requests == []
    assert list_sweeps(ctx, "toy") == []
    assert not any(ctx.layout.project_dir("toy").glob("sweeps/*.yaml"))


def test_launch_checks_the_repo_holds_the_project(ctx: Context, toy_repo: Path) -> None:
    with pytest.raises(SweepError, match="holds project 'toy', not 'other'"):
        launch_sweep(
            ctx,
            project="other",
            grid=[LR],
            seeds=[1],
            command=["python", "{lr}"],
            repo=toy_repo,
            launch=FakeLauncher(ctx),
        )


def test_launch_of_unregistered_project_without_repo(ctx: Context) -> None:
    with pytest.raises(StoreError, match="unknown project 'toy'"):
        launch_sweep(ctx, project="toy", grid=[LR], seeds=[1], command=["python", "{lr}"])


def test_host_sweep_needs_no_checkout_on_the_hub(ctx: Context, toy_repo: Path) -> None:
    # a project copied from a host (Task 34), or a hub used from another laptop
    entry = ctx.register_project(toy_repo)
    elsewhere = entry.model_copy(update={"repo": "/nonexistent/toy", "remote_host": "gpu1"})
    ctx.store.save_project(elsewhere)
    fake = FakeLauncher(ctx)
    summary = launch_sweep(
        ctx,
        project="toy",
        task="toy-acc",
        host="gpu1",
        grid=[LR],
        seeds=[1],
        command=CMD[:4],
        launch=fake,
    )
    assert len(summary.run_ids) == 2
    with pytest.raises(SweepError, match="no checkout here"):
        launch_sweep(ctx, project="toy", grid=[LR], seeds=[1], command=CMD[:4])


def test_failed_launch_keeps_the_runs_already_started(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    fake = FakeLauncher(ctx, fail_at=3)
    with pytest.raises(RunError, match="host refused"):
        launch_sweep(ctx, project="toy", grid=[LR], seeds=[1, 2], command=CMD[:4], launch=fake)
    (path,) = ctx.layout.project_dir("toy").glob("sweeps/*.yaml")
    spec = load_sweep(ctx.layout, "toy", path.stem)
    assert summarize_sweep(ctx, "toy", spec.id).run_ids == ["r01", "r02", "r03"]
    assert spec.seeds == [1, 2]


def test_a_failed_first_launch_keeps_the_definition(ctx: Context, toy_repo: Path) -> None:
    # the hub cannot know the host refused it: an error may hide an accepted run
    ctx.register_project(toy_repo)
    with pytest.raises(RunError):
        launch_sweep(
            ctx,
            project="toy",
            grid=[LR],
            seeds=[1],
            command=CMD[:4],
            launch=FakeLauncher(ctx, fail_at=0),
        )
    [listed] = list_sweeps(ctx, "toy")
    assert listed["n_runs"] == 0
    assert sweep_path(ctx.layout, "toy", listed["id"]).is_file()


def test_a_lost_first_response_keeps_the_definition_and_the_run(
    ctx: Context, toy_repo: Path
) -> None:
    # the host accepted the first run, the answer was lost, nothing is mirrored yet
    ctx.register_project(toy_repo)
    fake = FakeLauncher(ctx, lose_answer_at=1, mirrored=False)
    args: dict[str, Any] = {
        "project": "toy",
        "grid": [LR],
        "seeds": [1],
        "command": CMD[:4],
        "launch": fake,
        "command_id": "cmd-1",
    }
    with pytest.raises(RunError, match="answer was lost"):
        launch_sweep(ctx, **args)
    [listed] = list_sweeps(ctx, "toy")
    sid = listed["id"]
    assert sweep_path(ctx.layout, "toy", sid).is_file()  # the accepted run keeps its sweep
    fake.lose_answer_at = None
    summary = launch_sweep(ctx, **args)
    assert summary.spec.id == sid and len(fake.requests) == 2  # run 1 came from its receipt
    fake.mirror_all()
    assert summarize_sweep(ctx, "toy", sid).run_ids == ["r01", "r02"]


def test_launch_with_the_local_launcher_runs_real_commands(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    summary = launch_sweep(
        ctx,
        project="toy",
        grid=[SweepParam(name="lr", values=["0.1", "0.2"])],
        seeds=[1],
        command=[sys.executable, "-c", "print('lr={lr} seed={seed}')"],
    )
    records = [wait_for_run(ctx, rid, timeout=60) for rid in summary.run_ids]
    assert [r.status for r in records] == [RunStatus.FINISHED, RunStatus.FINISHED]
    assert [r.command[-1] for r in records] == ["print('lr=0.1 seed=1')", "print('lr=0.2 seed=1')"]
    assert [r.params for r in records] == [{"lr": "0.1"}, {"lr": "0.2"}]
    assert all(r.sweep_id == summary.spec.id for r in records)
    assert all(sweep_tag(ctx.descriptor.environment_id, summary.spec.id) in r.tags for r in records)
    log = (ctx.run_dir(records[1]) / "logs" / "stdout.log").read_text()
    assert "lr=0.2 seed=1" in log


def test_a_retried_launch_resumes_the_same_sweep(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    fake = FakeLauncher(ctx, fail_at=2)  # the third run fails: the host went away
    args: dict[str, Any] = {
        "project": "toy",
        "grid": [LR],
        "seeds": [1, 2],
        "command": ["python", "train.py", "{lr}"],
        "launch": fake,
        "command_id": "cmd-1",
    }
    with pytest.raises(RunError):
        launch_sweep(ctx, **args)
    [first] = list_sweeps(ctx, "toy")
    fake.fail_at = None  # the client retries the same command
    summary = launch_sweep(ctx, **args)
    assert summary.spec.id == first["id"]
    assert summary.run_ids == ["r01", "r02", "r03", "r04"]
    assert summary.spec.seeds == [1, 2]
    assert [(r.seed, r.params) for r in fake.requests[2:]] == [
        (2, {"lr": "1e-4"}),
        (2, {"lr": "3e-4"}),
    ]
    owner = ctx.descriptor.environment_id
    assert {tuple(r.tags) for r in fake.requests} == {(sweep_tag(owner, first["id"]),)}
    assert [s["id"] for s in list_sweeps(ctx, "toy")] == [first["id"]]
    again = launch_sweep(ctx, **args)  # nothing is missing: nothing starts
    assert again.run_ids == summary.run_ids and len(fake.requests) == 4
    other_args: dict[str, Any] = {**args, "command_id": "cmd-2"}
    other = launch_sweep(ctx, **other_args)  # another command: new sweep
    assert other.spec.id != first["id"]


def test_concurrent_launches_with_one_command_id_make_one_sweep(
    ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # two calls with the same command id race: both must end on one sweep and one run set
    ctx.register_project(toy_repo)
    fake = FakeLauncher(ctx)
    real_new_id = sweeps_module.new_sweep_id

    def slow_new_id(layout: Any, project: str) -> str:
        time.sleep(0.3)  # the other call reads the (absent) claim meanwhile
        return real_new_id(layout, project)

    monkeypatch.setattr(sweeps_module, "new_sweep_id", slow_new_id)
    args: dict[str, Any] = {
        "project": "toy",
        "grid": [LR],
        "seeds": [1],
        "command": ["python", "train.py", "{lr}"],
        "launch": fake,
        "command_id": "cmd-race",
    }
    results: list[str] = []
    errors: list[BaseException] = []

    def call() -> None:
        try:
            results.append(launch_sweep(ctx, **args).spec.id)
        except BaseException as exc:  # noqa: BLE001 - reported by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert len(set(results)) == 1
    assert [s["id"] for s in list_sweeps(ctx, "toy")] == results[:1]
    assert len(fake.requests) == 2  # one run per cell, never twice


def test_a_run_whose_answer_was_lost_is_never_started_twice(ctx: Context, toy_repo: Path) -> None:
    # the host accepted run 3 but the answer was lost; it is not mirrored yet either
    ctx.register_project(toy_repo)
    fake = FakeLauncher(ctx, lose_answer_at=3, mirrored=False)
    args: dict[str, Any] = {
        "project": "toy",
        "grid": [LR],
        "seeds": [1, 2],
        "command": ["python", "train.py", "{lr}"],
        "launch": fake,
        "command_id": "cmd-1",
    }
    with pytest.raises(RunError, match="answer was lost"):
        launch_sweep(ctx, **args)
    fake.lose_answer_at = None
    summary = launch_sweep(ctx, **args)  # every missing run again, with the same command ids
    assert len(fake.requests) == 4  # run 3 came back from its receipt
    assert summary.counts["total"] == 0  # nothing mirrored yet
    fake.mirror_all()
    mirrored = summarize_sweep(ctx, "toy", summary.spec.id)
    assert mirrored.run_ids == ["r01", "r02", "r03", "r04"]
    assert sorted((r.seed, r.params["lr"]) for r in fake.requests) == [
        (1, "1e-4"),
        (1, "3e-4"),
        (2, "1e-4"),
        (2, "3e-4"),
    ]
    assert load_sweep(ctx.layout, "toy", summary.spec.id).seeds == [1, 2]


def test_each_sweep_run_has_one_command_id_on_every_launch(ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    fake = FakeLauncher(ctx)
    summary = launch_sweep(ctx, project="toy", grid=[LR], seeds=[1], command=CMD[:4], launch=fake)
    env = ctx.descriptor.environment_id
    sid = summary.spec.id
    assert fake.command_ids == [
        run_command_id(env, "toy", sid, {"lr": "1e-4"}, 1),
        run_command_id(env, "toy", sid, {"lr": "3e-4"}, 1),
    ]
    assert run_command_id(env, "toy", sid, {"lr": "1e-4"}, 2) not in fake.command_ids


# --------------------------------------------------------------------------- Task 41 cancel/extend
def test_cancel_queued_stops_only_queued_runs(ctx: Context, toy_sweep: SweepSpec) -> None:
    stopped: list[str] = []

    def stop(run_id: str) -> None:
        stopped.append(run_id)
        ctx.update_run(
            run_id, "run.killed", lambda r: r.model_copy(update={"status": RunStatus.KILLED})
        )

    summary = cancel_queued(ctx, "toy", "s-0001", stop=stop)
    assert stopped == ["c2"]
    assert summary.counts["killed"] == 1
    assert summary.counts["queued"] == 0
    assert summary.counts["running"] == 1


def test_cancel_queued_default_stop_marks_killed(ctx: Context, toy_sweep: SweepSpec) -> None:
    summary = cancel_queued(ctx, "toy", "s-0001")
    assert ctx.find_record("c2").status == RunStatus.KILLED
    assert ctx.find_record("c1").status == RunStatus.RUNNING
    assert summary.counts["killed"] == 1


def test_cancel_queued_skips_runs_that_already_ended(ctx: Context, toy_sweep: SweepSpec) -> None:
    def stop(run_id: str) -> None:
        raise RunError(f"run {run_id} is finished")

    summary = cancel_queued(ctx, "toy", "s-0001", stop=stop)
    assert summary.counts["queued"] == 1


def test_cancel_unknown_sweep(ctx: Context) -> None:
    with pytest.raises(StoreError, match="unknown sweep"):
        cancel_queued(ctx, "toy", "s-dead")


def test_stop_if_queued_leaves_running_runs_alone(ctx: Context) -> None:
    mine = ctx.descriptor.environment_id  # a run of another environment is refused (Task 45)
    ctx.create_run(make_record("q1", status=RunStatus.QUEUED, environment_id=mine))
    ctx.create_run(make_record("u1", status=RunStatus.RUNNING, environment_id=mine))
    assert stop_if_queued(ctx, "u1").status == RunStatus.RUNNING
    assert stop_if_queued(ctx, "q1").status == RunStatus.KILLED


def launched(ctx: Context, toy_repo: Path, fake: FakeLauncher, **kwargs: Any) -> str:
    ctx.register_project(toy_repo)
    args: dict[str, Any] = {
        "project": "toy",
        "task": "toy-acc",
        "grid": [LR],
        "seeds": [1],
        "command": CMD[:4],
        "hypothesis": "lr matters",
        "gpus": 2,
        "queue": True,
        "launch": fake,
    }
    args.update(kwargs)
    return launch_sweep(ctx, **args).spec.id


def test_extend_adds_every_cell_for_each_new_seed(ctx: Context, toy_repo: Path) -> None:
    fake = FakeLauncher(ctx)
    sid = launched(ctx, toy_repo, fake)
    summary = extend_sweep(ctx, "toy", sid, [2, 3, 2], launch=fake)
    assert summary.spec.seeds == [1, 2, 3]
    assert summary.run_ids == ["r01", "r02", "r03", "r04", "r05", "r06"]
    assert summary.counts["total"] == 6
    new = fake.requests[2:]
    assert [(r.seed, r.params["lr"]) for r in new] == [
        (2, "1e-4"),
        (2, "3e-4"),
        (3, "1e-4"),
        (3, "3e-4"),
    ]
    # gpus, queue, and hypothesis follow the sweep's first run
    assert all((r.gpus, r.queue, r.hypothesis) == (2, True, "lr matters") for r in new)
    assert all(r.tags == [sweep_tag(ctx.descriptor.environment_id, sid)] for r in new)
    assert load_sweep(ctx.layout, "toy", sid).seeds == [1, 2, 3]


def test_extend_pins_the_code_the_sweep_was_launched_with(ctx: Context, toy_repo: Path) -> None:
    # CONF-1: new seeds must run the sweep's code, or they land in another seed group
    fake = FakeLauncher(ctx)
    commit, diff = "a" * 40, "diff --git a/train.py b/train.py\n"
    sid = launched(ctx, toy_repo, fake, commit=commit, diff=diff)
    spec = load_sweep(ctx.layout, "toy", sid)
    assert (spec.commit, spec.diff) == (commit, diff)
    extend_sweep(ctx, "toy", sid, [2], launch=fake)
    assert len(fake.requests) == 4
    assert all((r.commit, r.diff) == (commit, diff) for r in fake.requests)


def test_a_sweep_without_pinned_code_pins_nothing(ctx: Context, toy_repo: Path) -> None:
    fake = FakeLauncher(ctx)
    sid = launched(ctx, toy_repo, fake)
    extend_sweep(ctx, "toy", sid, [2], launch=fake)
    assert all((r.commit, r.diff) == (None, None) for r in fake.requests)


def test_launch_refuses_a_diff_without_its_commit(ctx: Context, toy_repo: Path) -> None:
    fake = FakeLauncher(ctx)
    with pytest.raises(SweepError, match="a diff needs the commit"):
        launched(ctx, toy_repo, fake, diff="diff --git a/x b/x\n")
    assert fake.requests == [] and list_sweeps(ctx, "toy") == []


def test_extend_explicit_gpus_and_queue_win(ctx: Context, toy_repo: Path) -> None:
    fake = FakeLauncher(ctx)
    sid = launched(ctx, toy_repo, fake)
    extend_sweep(ctx, "toy", sid, [5], gpus=0, launch=fake)
    assert [(r.gpus, r.queue) for r in fake.requests[2:]] == [(0, False), (0, False)]


def test_extend_random_sweep_reuses_its_samples(ctx: Context, toy_repo: Path) -> None:
    fake = FakeLauncher(ctx)
    sid = launched(
        ctx,
        toy_repo,
        fake,
        grid=[SweepParam(name="lr", low=1e-5, high=1e-2, log=True)],
        random=3,
    )
    extend_sweep(ctx, "toy", sid, [2], launch=fake)
    first = [r.params for r in fake.requests[:3]]
    assert [r.params for r in fake.requests[3:]] == first
    summary = summarize_sweep(ctx, "toy", sid)
    assert len(summary.cells) == 3
    assert all(len(c["run_ids"]) == 2 for c in summary.cells)


def test_extend_needs_a_seed(ctx: Context, toy_repo: Path) -> None:
    fake = FakeLauncher(ctx)
    sid = launched(ctx, toy_repo, fake)
    with pytest.raises(SweepError, match="at least one seed"):
        extend_sweep(ctx, "toy", sid, [], launch=fake)
    assert len(fake.requests) == 2
    assert load_sweep(ctx.layout, "toy", sid).seeds == [1]


def test_extend_with_seeds_it_has_issues_only_what_is_missing(ctx: Context, toy_repo: Path) -> None:
    fake = FakeLauncher(ctx)
    sid = launched(ctx, toy_repo, fake)
    same = extend_sweep(ctx, "toy", sid, [1], launch=fake)  # seed 1 is complete
    assert len(fake.requests) == 2 and same.counts["total"] == 2
    grown = extend_sweep(ctx, "toy", sid, [1, 4], launch=fake)
    assert [(r.seed, r.params["lr"]) for r in fake.requests[2:]] == [(4, "1e-4"), (4, "3e-4")]
    assert grown.spec.seeds == [1, 4]


def test_extend_refuses_to_grow_past_the_limit(ctx: Context, toy_repo: Path) -> None:
    fake = FakeLauncher(ctx)
    sid = launched(ctx, toy_repo, fake)
    with pytest.raises(SweepError, match="the limit is 1000"):
        extend_sweep(ctx, "toy", sid, list(range(2, 502)), launch=fake)


def test_extend_partial_failure_then_retry_launches_only_missing_runs(
    ctx: Context, toy_repo: Path
) -> None:
    # extending [2, 3]: seed 2 completes, seed 3 half; the same request again resumes it
    fake = FakeLauncher(ctx)
    sid = launched(ctx, toy_repo, fake)
    fake.fail_at = 5  # 2 original runs + both of seed 2 + one of seed 3, then fail
    with pytest.raises(RunError):
        extend_sweep(ctx, "toy", sid, [2, 3], launch=fake)
    assert load_sweep(ctx.layout, "toy", sid).seeds == [1, 2, 3]  # the definition came first
    assert summarize_sweep(ctx, "toy", sid).run_ids == ["r01", "r02", "r03", "r04", "r05"]
    fake.fail_at = None
    grown = extend_sweep(ctx, "toy", sid, [2, 3], launch=fake)
    assert [(r.seed, r.params["lr"]) for r in fake.requests[5:]] == [(3, "3e-4")]
    assert grown.spec.seeds == [1, 2, 3]
    assert grown.run_ids == ["r01", "r02", "r03", "r04", "r05", "r06"]


def test_extend_while_runs_wait_in_the_queue(
    ctx: Context, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review Focus: more seeds while the first runs still wait for GPUs.
    fake_gpus = tmp_path / "gpus.json"
    fake_gpus.write_text('[{"index": 0, "external": true}]')  # busy: nothing can start
    monkeypatch.setenv("HYPOTHEX_FAKE_GPUS", str(fake_gpus))
    ctx.register_project(toy_repo)
    command = [sys.executable, "-c", "print('{lr}')"]
    first = launch_sweep(
        ctx, project="toy", grid=[LR], seeds=[1], command=command, gpus=1, queue=True
    )
    sid = first.spec.id
    grown = extend_sweep(ctx, "toy", sid, [2])
    assert (grown.counts["queued"], grown.counts["total"]) == (4, 4)
    positions = Scheduler(ctx).positions()
    # the new seed's runs join the queue behind the runs that were already waiting
    assert [positions[run_id] for run_id in grown.run_ids] == [1, 2, 3, 4]
    cancelled = cancel_queued(ctx, "toy", sid)
    assert (cancelled.counts["killed"], cancelled.counts["queued"]) == (4, 0)
    assert Scheduler(ctx).positions() == {}


def test_cancel_queued_never_kills_a_run_the_scheduler_just_started(
    ctx: Context, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.core import control
    from hypothex.core.scheduler import Scheduler

    fake_gpus = tmp_path / "gpus.json"
    fake_gpus.write_text('[{"index": 0}]')
    monkeypatch.setenv("HYPOTHEX_FAKE_GPUS", str(fake_gpus))
    out = tmp_path / "ran.txt"
    code = f"import time; time.sleep(1); open({str(out)!r}, 'a').write('x')"
    req = RunRequest(repo=toy_repo, command=[sys.executable, "-c", code], gpus=1, queue=True)
    rec = control.launch_run(ctx, req)
    real = control._remove_from_queue

    def scheduler_wins(c: Context, run_id: str, run_dir: Path) -> RunRecord | None:
        assert Scheduler(c).tick() == [run_id]  # the scheduler takes the lock first
        wait_for_run(c, run_id, timeout=60, statuses=frozenset({RunStatus.RUNNING}))
        return real(c, run_id, run_dir)

    monkeypatch.setattr(control, "_remove_from_queue", scheduler_wins)
    assert stop_if_queued(ctx, rec.run_id).status == RunStatus.RUNNING
    assert wait_for_run(ctx, rec.run_id, timeout=60).status == RunStatus.FINISHED
    assert out.read_text() == "x"


def test_cancel_takes_the_claim_so_a_supervisor_on_its_way_never_runs(
    ctx: Context, toy_repo: Path, tmp_path: Path
) -> None:
    import psutil

    from hypothex.core.execution import prepare_run, spawn_supervisor

    out = tmp_path / "ran.txt"
    code = f"open({str(out)!r}, 'w').write('x')"
    rec = prepare_run(ctx, RunRequest(repo=toy_repo, command=[sys.executable, "-c", code]))
    assert stop_if_queued(ctx, rec.run_id).status == RunStatus.KILLED
    pid = spawn_supervisor(ctx, ctx.find_record(rec.run_id))  # it was already starting
    psutil.Process(pid).wait(timeout=60)
    assert not out.exists()
    assert ctx.find_record(rec.run_id).status == RunStatus.KILLED
