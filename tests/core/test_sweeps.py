"""Tests for hypothex.core.sweeps: expansion, storage, summary, launch, cancel, extend."""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from hypothex.core.context import Context
from hypothex.core.errors import StoreError
from hypothex.core.sweeps import (
    SweepParam,
    SweepSpec,
    expand,
    load_sweep,
    new_sweep_id,
    parse_sweep_tag,
    planned_runs,
    save_sweep,
    sweep_combos,
    sweep_path,
    sweep_tag,
)

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
