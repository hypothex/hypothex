import pytest

from hypothex.core.scorekeys import KeyParts, parse_key_pattern, split_score_key


def test_parse_key_pattern_reads_part_names_in_order() -> None:
    assert parse_key_pattern("{dataset}.{model}.{metric}") == ["dataset", "model", "metric"]
    assert parse_key_pattern("{bench}.{metric}") == ["bench", "metric"]


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("{dataset}.{model}", "needs a {metric} part"),
        ("{metric}", "2 or 3 parts"),
        ("{a}.{b}.{c}.{metric}", "2 or 3 parts"),
        ("{dataset}-{metric}", "one {name} placeholder"),
        ("{data set}.{metric}", "one {name} placeholder"),
        ("{1st}.{metric}", "one {name} placeholder"),
        ("{metric}.{metric}", "must differ"),
    ],
)
def test_parse_key_pattern_rejects_bad_patterns(pattern: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_key_pattern(pattern)


def test_split_score_key_without_a_pattern() -> None:
    assert split_score_key("reported/set-1.m-a.top10") == KeyParts(
        "reported", "set-1", "m-a", "top10"
    )
    assert split_score_key("reported/set-0.old.m-a.max") == KeyParts(
        "reported", "set-0.old", "m-a", "max"
    )
    assert split_score_key("reported/all.frac") == KeyParts("reported", "all", None, "frac")
    assert split_score_key("acc/value") is None


def test_split_score_key_with_a_pattern_maps_parts_by_name() -> None:
    names = ["model", "dataset", "metric"]
    assert split_score_key("r/m-a.set-1.top10", names) == KeyParts("r", "set-1", "m-a", "top10")
    assert split_score_key("r/x.y.z", ["a", "b", "metric"]) == KeyParts("r", "x", "y", "z")
    assert split_score_key("r/old.set-1.top10", ["bench", "metric"]) == KeyParts(
        "r", "old.set-1", None, "top10"
    )
    assert split_score_key("r/top10", ["bench", "metric"]) is None
