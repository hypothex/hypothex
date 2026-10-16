from datetime import timedelta

import pytest

from hypothex.core.errors import RunError, RunNameError
from hypothex.core.ids import utcnow
from hypothex.core.naming import (
    NAME_MAX,
    clean_run_name,
    derive_names,
    display_name,
    group_display_name,
    run_settings,
    short_run_id,
    varying_keys,
)
from tests.factories import make_record

T0 = utcnow()


def test_varying_keys_keep_first_seen_order_and_skip_constant_keys() -> None:
    params = [
        {"db": "v3", "lr": "1e-3", "beam": "5"},
        {"db": "v3", "lr": "3e-4", "beam": "10"},
    ]
    assert varying_keys(params) == ["lr", "beam"]


def test_varying_keys_count_a_missing_key_as_a_difference() -> None:
    assert varying_keys([{"lr": "1e-3"}, {}]) == ["lr"]


@pytest.mark.parametrize(
    "values",
    [
        ["0123456789abcdef", "fedcba9876543210"],  # hex hashes (>= 16 hex digits)
        ["https://x.io/a", "https://x.io/b"],  # URLs
        ["data/train/v3.jsonl", "data/train/v4.jsonl"],  # paths
        ["a" * 25, "b" * 25],  # longer than 24 characters
    ],
)
def test_varying_keys_never_use_unreadable_values(values: list[str]) -> None:
    assert varying_keys([{"x": v} for v in values]) == []


def test_varying_keys_keep_short_values_with_a_slash() -> None:
    assert varying_keys([{"split": "a/b"}, {"split": "a/c"}]) == ["split"]


def test_varying_keys_skip_the_seed() -> None:
    assert varying_keys([{"seed": "1", "lr": "1"}, {"seed": "2", "lr": "1"}]) == []


def test_run_settings_put_params_first_and_keep_their_values() -> None:
    run = make_record(params={"lr": "1e-3"}, vars={"beam": "5", "lr": "x"})
    assert run_settings(run) == {"lr": "1e-3", "beam": "5"}


def test_derive_names_join_varying_params_and_vars() -> None:
    a = make_record("a", params={"lr": "1e-3", "db": "v3"}, vars={"beam": "5"})
    b = make_record("b", params={"lr": "3e-4", "db": "v3"}, vars={"beam": "10"})
    assert derive_names([a, b]) == {"a": "lr 1e-3 · beam 5", "b": "lr 3e-4 · beam 10"}


def test_derive_names_leave_out_keys_a_run_lacks() -> None:
    a = make_record("a", params={"lr": "1e-3"})
    b = make_record("b", params={"lr": "3e-4", "beam": "10"})
    assert derive_names([a, b]) == {"a": "lr 1e-3", "b": "lr 3e-4 · beam 10"}


def test_derive_names_fall_back_to_hypothesis_tag_then_short_id() -> None:
    runs = [
        make_record("20261015-064419-apt-eval-588f929f", hypothesis="Back-fill the db, then score"),
        make_record("r2", tags=["sweep:me:abc", "baseline"]),
        make_record("20261015-064419-apt-eval-0ede7700"),
    ]
    assert derive_names(runs) == {
        "20261015-064419-apt-eval-588f929f": "Back-fill the db",
        "r2": "baseline",
        "20261015-064419-apt-eval-0ede7700": "0ede7700",
    }


def test_derive_names_skip_a_hypothesis_that_is_only_a_rerun_prefix() -> None:
    runs = [
        make_record("r1", hypothesis="Rerun of r0:", tags=["baseline"]),
        make_record("20261015-064419-apt-eval-0ede7700", hypothesis="Rerun of r0:"),
    ]
    assert derive_names(runs) == {
        "r1": "baseline",
        "20261015-064419-apt-eval-0ede7700": "0ede7700",
    }


def test_short_run_id_keeps_ids_of_another_shape() -> None:
    assert short_run_id("20261015-064419-apt-eval-588f929f") == "588f929f"
    assert short_run_id("r1") == "r1"


def test_a_rename_wins_over_the_derived_name() -> None:
    run = make_record("a", name="wide beam")
    assert display_name(run, {"a": "beam 10"}) == "wide beam"
    assert display_name(make_record("a"), {"a": "beam 10"}) == "beam 10"


def test_a_group_takes_the_name_of_its_newest_renamed_run() -> None:
    old = make_record("a", name="first try", created_at=T0)
    new = make_record("b", name="baseline", created_at=T0 + timedelta(minutes=1))
    plain = make_record("c", created_at=T0 + timedelta(minutes=2))
    derived = {"a": "lr 1e-3", "b": "lr 1e-3", "c": "lr 1e-3"}
    assert group_display_name([plain, new, old], derived) == "baseline"


def test_an_unrenamed_group_takes_the_derived_name_of_its_newest_run() -> None:
    old = make_record("a", created_at=T0)
    new = make_record("b", created_at=T0 + timedelta(minutes=1))
    assert group_display_name([new, old], {"a": "old", "b": "new"}) == "new"


def test_clean_run_name_trims_and_resets_blank_names() -> None:
    assert clean_run_name("  wide beam ") == "wide beam"
    assert clean_run_name("") is None
    assert clean_run_name(None) is None


@pytest.mark.parametrize("bad", ["two\nlines", "carriage\rreturn", "x" * (NAME_MAX + 1)])
def test_clean_run_name_rejects_long_or_multiline_names(bad: str) -> None:
    with pytest.raises(RunNameError) as caught:
        clean_run_name(bad)
    assert isinstance(caught.value, RunError) and isinstance(caught.value, ValueError)


def test_clean_run_name_accepts_exactly_80_characters() -> None:
    assert clean_run_name("x" * NAME_MAX) == "x" * NAME_MAX
