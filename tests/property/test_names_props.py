"""Property tests for names: metric refs, config hashes, file stems, task and view names."""

import datetime as dt
import hashlib
import json
import random
import re
import string
from pathlib import PurePosixPath
from typing import Any

import pytest
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from hypothex.core.config import (
    NAME_PATTERN,
    ProjectConfig,
    parse_metric_key,
    parse_metric_version,
)
from hypothex.core.errors import ConfigError
from hypothex.core.seeds import config_hash
from hypothex.core.store import MAX_STEM, safe_stem
from hypothex.core.views import _valid_name, check_view_name, views_dir

FAST = settings(max_examples=80, deadline=None)
text = st.text(max_size=20)


# metric references ----------------------------------------------------------------------
@FAST
@given(text.filter(lambda s: "/" not in s), text)
def test_metric_key_round_trip(name: str, key: str) -> None:
    assert parse_metric_key(f"{name}/{key}") == (name, key)
    assert parse_metric_key(name) == (name, "value")


@FAST
@given(text.filter(lambda s: "@" not in s), text)
def test_metric_version_round_trip(name: str, version: str) -> None:
    assert parse_metric_version(f"{name}@{version}") == (name, version)
    assert parse_metric_version(name) == (name, None)


@FAST
@given(
    text.filter(lambda s: not set(s) & {"/", "@"}),
    text.filter(lambda s: "/" not in s),
    text,
)
def test_versioned_metric_key_round_trip(name: str, version: str, key: str) -> None:
    head, got_key = parse_metric_key(f"{name}@{version}/{key}")
    assert got_key == key
    assert parse_metric_version(head) == (name, version)


@FAST
@given(text)
def test_metric_parsers_reassemble_any_ref(ref: str) -> None:
    name, key = parse_metric_key(ref)
    assert (name if "/" not in ref else f"{name}/{key}") == ref
    base, version = parse_metric_version(ref)
    assert (base if version is None else f"{base}@{version}") == ref


# config_hash ----------------------------------------------------------------------------
scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-(10**6), 10**6),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=8),
)
str_keyed = st.recursive(
    scalars,
    lambda kids: st.one_of(
        st.lists(kids, max_size=4), st.dictionaries(st.text(max_size=6), kids, max_size=4)
    ),
    max_leaves=12,
)
any_key = st.one_of(
    st.text(max_size=4), st.integers(-5, 5), st.booleans(), st.none(), st.dates(), st.floats(0, 4)
)
mixed_keyed = st.recursive(
    scalars,
    lambda kids: st.one_of(st.lists(kids, max_size=4), st.dictionaries(any_key, kids, max_size=4)),
    max_leaves=12,
)


def _shuffled(value: Any, rng: random.Random) -> Any:
    """The same value with every mapping's key order shuffled."""
    if isinstance(value, dict):
        items = list(value.items())
        rng.shuffle(items)
        return {k: _shuffled(v, rng) for k, v in items}
    if isinstance(value, list):
        return [_shuffled(v, rng) for v in value]
    return value


@FAST
@given(st.dictionaries(st.text(max_size=6), str_keyed, max_size=5), scalars, scalars)
def test_config_hash_ignores_seed_and_key_order(
    cfg: dict[str, Any], seed1: Any, seed2: Any
) -> None:
    h = config_hash(cfg)
    assert re.fullmatch(r"sha256:[0-9a-f]{16}", h)
    assert config_hash({**cfg, "seed": seed1}) == config_hash({**cfg, "seed": seed2})
    assert config_hash(_shuffled(cfg, random.Random(0))) == h
    assert config_hash(_shuffled(cfg, random.Random(1))) == h


@FAST
@given(st.dictionaries(st.text(max_size=6), str_keyed, max_size=5))
def test_config_hash_is_unchanged_for_json_sortable_configs(cfg: dict[str, Any]) -> None:
    # the canonical fallback must never change hashes already stored in run.yaml
    payload = {k: v for k, v in cfg.items() if k != "seed"}
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    assert config_hash(cfg) == "sha256:" + hashlib.sha256(blob.encode()).hexdigest()[:16]


@FAST
@given(
    st.dictionaries(st.text(max_size=6), str_keyed, max_size=4),
    st.dictionaries(st.text(max_size=6), str_keyed, max_size=4),
)
def test_config_hash_tells_different_configs_apart(a: dict[str, Any], b: dict[str, Any]) -> None:
    def canon(c: dict[str, Any]) -> str:
        return json.dumps({k: v for k, v in c.items() if k != "seed"}, sort_keys=True)

    assume(canon(a) != canon(b))
    assert config_hash(a) != config_hash(b)


@FAST
@given(st.dictionaries(any_key, mixed_keyed, max_size=5), scalars)
@example({1: "a", "b": 2}, 0)
@example({"layers": {1: 64, "out": 10}}, 0)
@example({dt.date(2026, 1, 1): "x"}, 0)
def test_config_hash_never_raises_on_yaml_keys(cfg: dict[Any, Any], seed: Any) -> None:
    h = config_hash(cfg)
    assert re.fullmatch(r"sha256:[0-9a-f]{16}", h)
    assert config_hash(_shuffled(cfg, random.Random(2))) == h
    assert config_hash({**cfg, "seed": seed}) == h or "seed" in cfg


@FAST
@given(st.dictionaries(st.text(max_size=4), str_keyed, max_size=3), str_keyed, str_keyed)
def test_config_hash_keeps_nested_seeds(cfg: dict[str, Any], s1: Any, s2: Any) -> None:
    # only the top-level seed is a seed; a nested one is part of the config
    assume(json.dumps(s1, sort_keys=True) != json.dumps(s2, sort_keys=True))
    assert config_hash({**cfg, "model": {"seed": s1}}) != config_hash(
        {**cfg, "model": {"seed": s2}}
    )


def test_regression_config_hash_mixed_keys() -> None:
    # was TypeError: '<' not supported between instances of 'str' and 'int'
    assert config_hash({"layers": {1: 64, "out": 10}}) != config_hash({"layers": {1: 64}})
    assert config_hash({dt.date(2026, 1, 1): "x"}).startswith("sha256:")


# safe_stem ------------------------------------------------------------------------------
names = st.one_of(
    st.text(min_size=1, max_size=40),
    st.sampled_from([".", "..", ".hidden", "../x", "a/../../b", "/abs", "-", "\x00", "a\\b"]),
    st.text(alphabet="./\\-_ab", min_size=1, max_size=12),
    st.text(min_size=190, max_size=400),
)


@settings(max_examples=150, deadline=None)
@given(names)
@example("\ud800")
@example("x" * 300)
def test_safe_stem_stays_in_its_folder(name: str) -> None:
    stem = safe_stem(name)
    assert stem and stem not in (".", "..")
    assert not stem.startswith(".")
    assert re.fullmatch(r"[A-Za-z0-9_.-]+", stem)
    assert len(f"{stem}.jsonl".encode()) <= 255
    parent = PurePosixPath("/runs/r1/traces")
    path = parent / f"{stem}.jsonl"
    assert path.parent == parent and path.name == f"{stem}.jsonl"
    assert safe_stem(name) == stem


@settings(max_examples=150, deadline=None)
@given(names, names)
def test_safe_stem_unchanged_or_hashed(a: str, b: str) -> None:
    sa, sb = safe_stem(a), safe_stem(b)
    hashed = re.compile(r".*-[0-9a-f]{8}")
    assert sa == a or hashed.fullmatch(sa)
    if sa == a:
        assert not re.search(r"-[0-9a-f]{8}\Z", a)
    if a != b and sa == sb:  # only a sha1 prefix collision may join them
        assert hashed.fullmatch(sa)


def test_safe_stem_rejects_empty() -> None:
    with pytest.raises(ValueError):
        safe_stem("")


def test_regression_safe_stem_hidden_long_and_surrogate_names() -> None:
    assert safe_stem(".x").startswith("_x-")  # was ".x" (a hidden file)
    assert safe_stem("..").startswith("_.-")  # was ".."
    assert len(safe_stem("y" * 300)) == MAX_STEM + 9  # was 300 chars (ENAMETOOLONG)
    assert safe_stem("\ud800").startswith("_-")  # was UnicodeEncodeError
    assert safe_stem("a_b") == "a_b"  # plain names keep their stem


# task and view names ----------------------------------------------------------------------
def _config(task: str, view: str | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {"dataset": "d", "metrics": ["m"], "primary": "m"}
    if view is not None:
        spec["views"] = {view: {"title": "t", "panels": []}}
    return {
        "project": "p",
        "datasets": {"d": {"version": "v1", "path": "d.jsonl"}},
        "metrics": {"m": {"version": "v1", "fn": "mod:fn"}},
        "tasks": {task: spec},
    }


name_text = st.one_of(
    st.from_regex(NAME_PATTERN.removesuffix("$"), fullmatch=True).map(lambda s: s[:30]),
    st.text(max_size=12),
    st.from_regex(r"[a-z0-9]{1,5}", fullmatch=True).map(lambda s: s + "\n"),
)


ALNUM = frozenset(string.ascii_lowercase + string.digits)


def _spec_name(name: str, more: str) -> bool:
    """Hand-written oracle: one of ``[a-z0-9]``, then ``[a-z0-9]`` or ``more``."""
    rest = ALNUM | frozenset(more)
    return bool(name) and name[0] in ALNUM and all(c in rest for c in name[1:])


@FAST
@given(name_text)
@example("t\n")
@example("a.b-c_d")
@example(".a")
@example("A")
def test_task_names_follow_the_pattern_exactly(task: str) -> None:
    ok = _spec_name(task, "_.-")
    try:
        ProjectConfig.model_validate(_config(task))
    except ValidationError:
        assert not ok
    else:
        assert ok
        assert task not in (".", "..") and "/" not in task and "\n" not in task
        assert views_dir(PurePosixPath("/r"), task).parent == PurePosixPath("/r/.hypothex/views")


@FAST
@given(name_text)
@example("v\n")
@example("a.b")
@example("overview")
def test_view_names_follow_the_pattern_exactly(view: str) -> None:
    ok = _spec_name(view, "_-") and view != "overview"
    try:
        ProjectConfig.model_validate(_config("t", view))
    except ValidationError:
        assert not ok
    else:
        assert ok
    assert _valid_name(view) == ok
    if ok:
        check_view_name(view)
        assert not view.startswith(".") and "/" not in view
    else:
        with pytest.raises(ConfigError):
            check_view_name(view)
