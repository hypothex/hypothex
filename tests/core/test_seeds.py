import math

import pytest

from hypothex.core.seeds import (
    clamp,
    config_hash,
    intervals_overlap,
    run_fingerprint,
    summarize,
)


def test_config_hash_ignores_seed_and_key_order() -> None:
    assert config_hash({"lr": 1, "seed": 1}) == config_hash({"seed": 2, "lr": 1})
    assert config_hash({"lr": 1}) != config_hash({"lr": 2})
    assert config_hash({"a": 1}).startswith("sha256:")


def test_run_fingerprint_drops_seed_everywhere() -> None:
    a = run_fingerprint(
        command_template=["python", "t.py", "--seed", "{seed}"],
        stage=None,
        user_config={"lr": 0.1, "seed": 1},
        params={"seed": "1"},
        vars={},
    )
    b = run_fingerprint(
        command_template=["python", "t.py", "--seed", "{seed}"],
        stage=None,
        user_config={"lr": 0.1, "seed": 7},
        params={"seed": "7"},
        vars={},
    )
    assert config_hash(a) == config_hash(b)


def test_summarize_single_and_many() -> None:
    one = summarize([0.5])
    assert (one.mean, one.std, one.n, one.ci_low, one.ci_high) == (0.5, 0.0, 1, None, None)
    three = summarize([1.0, 2.0, 3.0])
    assert three.mean == 2.0 and three.std == 1.0 and three.n == 3
    half = 4.303 / math.sqrt(3)
    assert three.ci_low == pytest.approx(2.0 - half)
    assert three.ci_high == pytest.approx(2.0 + half)


def test_intervals_overlap() -> None:
    a = summarize([0.80, 0.82, 0.81])
    b = summarize([0.805, 0.815, 0.81])
    c = summarize([0.70, 0.71, 0.69])
    assert intervals_overlap(a, b) is True
    assert intervals_overlap(a, c) is False
    assert intervals_overlap(a, summarize([0.9])) is None


def test_clamp_keeps_the_interval_in_range() -> None:
    s = summarize([0.98, 1.0, 1.0])
    assert s.ci_high is not None and s.ci_high > 1.0
    c = clamp(s, 0.0, 1.0)
    assert c.ci_high == 1.0 and c.ci_low == s.ci_low
    assert (c.mean, c.std, c.n) == (s.mean, s.std, s.n)
    low = clamp(summarize([0.0, 0.02, 0.0]), 0.0, 1.0)
    assert low.ci_low == 0.0
    one = summarize([1.0])
    assert clamp(one, 0.0, 1.0) == one  # no interval to clip


def test_run_fingerprint_ignores_params_that_repeat_a_var() -> None:
    def fp(params: dict[str, str], vars: dict[str, str]) -> str:
        return config_hash(
            run_fingerprint(
                command_template=["python", "t.py", "--C", "{C}"],
                stage="train",
                user_config=None,
                params=params,
                vars=vars,
            )
        )

    swept = fp({"C": "1.0"}, {"C": "1.0"})  # a sweep stores the grid value in both
    assert swept == fp({}, {"C": "1.0"})  # a manual --var C=1.0 joins the cell
    assert swept != fp({}, {"C": "10"})
    assert fp({"C": "2"}, {"C": "1.0"}) != swept  # a param that differs still counts
    assert fp({"version": "v2"}, {"C": "1.0"}) != swept
