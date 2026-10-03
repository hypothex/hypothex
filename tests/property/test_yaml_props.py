"""Property tests for YAML guards (``scan_yaml``), view loading, and the Vega-Lite validator."""

import contextlib
import itertools
import tempfile
from pathlib import Path
from typing import Any

import yaml
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from hypothex.core.config import (
    CONFIG_FILENAME,
    YAML_MAX_DEPTH,
    ProjectConfig,
    has_cycle,
    load_project_config,
    scan_yaml,
)
from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout
from hypothex.core.views import (
    VEGA_MAX_DEPTH,
    ViewSpec,
    _file_body,
    validate_view_text,
    vega_spec_problems,
)
from hypothex.remote.config import ENVIRONMENTS_FILENAME, load_hosts

FAST = settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
yamlish = st.text(alphabet="[]{}:-,&*!|>'\"#%@`? \n\tab1.", max_size=60)


# a generator of flow-style YAML with anchors and aliases, and what it contains ------------
@st.composite
def anchored_docs(draw: st.DrawFn) -> tuple[str, dict[str, bool]]:
    """
    One-line flow YAML (a mapping) with random anchors and aliases.

    Returns the text and the facts a correct scan must report: any anchor or
    alias, any at or under ``tasks.<task>.views``, and any alias to a collection
    that is still open (a cycle).
    """
    names = itertools.count()
    done: list[str] = []
    open_: list[str] = []
    facts = {"anchor": False, "views": False, "cycle": False}

    def in_views(path: tuple[Any, ...]) -> bool:
        return len(path) >= 3 and path[0] == "tasks" and path[2] == "views"

    def mark(path: tuple[Any, ...]) -> None:
        facts["anchor"] = True
        facts["views"] = facts["views"] or in_views(path)

    def node(depth: int, path: tuple[Any, ...], kind: str | None = None) -> str:
        if kind is None:
            kinds = ["scalar", "alias", "list", "map"] if depth < 4 else ["scalar", "alias"]
            kind = draw(st.sampled_from(kinds))
        if kind == "alias":
            pool = done + open_
            if not pool:
                kind = "scalar"
            else:
                target = draw(st.sampled_from(pool))
                mark(path)
                facts["cycle"] = facts["cycle"] or target in open_
                return f"*{target}"
        anchor = f"a{next(names)}" if draw(st.booleans()) else None
        prefix = ""
        if anchor is not None:
            mark(path)
            prefix = f"&{anchor} "
        if kind == "scalar":
            if anchor is not None:
                done.append(anchor)
            return prefix + draw(st.sampled_from(["x", "1", "views", "tasks", "''", "null"]))
        if anchor is not None:
            open_.append(anchor)
        if kind == "list":
            n = draw(st.integers(0, 3))
            body = "[" + ", ".join(node(depth + 1, (*path, None)) for _ in range(n)) + "]"
        else:
            keys = draw(
                st.lists(st.sampled_from(["tasks", "t", "views", "a"]), unique=True, max_size=3)
            )
            body = "{" + ", ".join(f"{k}: {node(depth + 1, (*path, k))}" for k in keys) + "}"
        if anchor is not None:
            open_.remove(anchor)
            done.append(anchor)
        return prefix + body

    if draw(st.booleans()):  # make inline views likely
        first = node(1, ("a",))  # generated in text order: aliases only point back
        inner = node(3, ("tasks", "t", "views"), "map")
        text = f"{{a: {first}, tasks: {{t: {{views: {inner}}}}}}}"
    else:
        text = node(0, (), "map")
    return text, facts


@FAST
@given(anchored_docs())
@example(("{a: &a [1, *a]}", {"anchor": True, "views": False, "cycle": True}))
@example(
    ("{n: &k x, tasks: {t: {views: {v: *k}}}}", {"anchor": True, "views": True, "cycle": False})
)
def test_scan_yaml_finds_anchors_views_and_cycles(doc: tuple[str, dict[str, bool]]) -> None:
    text, facts = doc
    scan = scan_yaml(text)
    assert scan.problem is None
    assert (scan.first_anchor is not None) == facts["anchor"]
    assert (scan.views_anchor is not None) == facts["views"]
    assert (scan.cycle is not None) == facts["cycle"]
    # and the loader agrees: a cycle in the text is a cycle in the value
    assert has_cycle(yaml.safe_load(text)) == facts["cycle"]


@FAST
@given(anchored_docs())
def test_views_with_anchors_are_rejected_not_raised(doc: tuple[str, dict[str, bool]]) -> None:
    text, facts = doc
    view, issues = validate_view_text(text, set(), {})
    if facts["anchor"]:
        assert view is None and len(issues) == 1 and "anchors" in issues[0].message
    assert view is None or isinstance(view, ViewSpec)


@settings(max_examples=40, deadline=None)
@given(st.integers(1, 3000), st.sampled_from(["[", "{a: "]), st.booleans())
@example(YAML_MAX_DEPTH, "[", False)
@example(YAML_MAX_DEPTH + 1, "[", False)
def test_scan_yaml_depth_guard(depth: int, opener: str, under_key: bool) -> None:
    closer = "]" if opener == "[" else "}"
    body = opener * depth + "x" + closer * depth
    text = f"k: {body}" if under_key else body
    total = depth + (1 if under_key else 0)
    scan = scan_yaml(text)  # never RecursionError, however deep
    if total > YAML_MAX_DEPTH:
        assert scan.problem is not None and "deeply" in scan.problem[0]
        view, issues = validate_view_text(text, set(), {})
        assert view is None and "deeply" in issues[0].message
    else:
        assert scan.problem is None


@FAST
@given(yamlish)
@example("&a [*a]")
@example("? [a]\n: b")
@example("!!python/object:os.system x")
@example("a: !!binary zz")
def test_view_text_never_raises(text: str) -> None:
    with contextlib.suppress(yaml.YAMLError):
        scan_yaml(text)
    view, issues = validate_view_text(text, {"m"}, {"runs": {"f"}})
    assert view is None or isinstance(view, ViewSpec)
    if view is None:
        assert issues


json_like = st.recursive(
    st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=6), st.floats()),
    lambda kids: st.one_of(
        st.lists(kids, max_size=4), st.dictionaries(st.text(max_size=6), kids, max_size=4)
    ),
    max_leaves=20,
)


@FAST
@given(st.one_of(yamlish, json_like.map(lambda d: yaml.safe_dump(d))))
@example(b"\xff\xfe".decode("latin-1"))
def test_view_files_and_project_files_never_crash(text: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        view_file = root / "v.yaml"
        view_file.write_text(text, encoding="utf-8")
        assert isinstance(_file_body(view_file), dict)
        (root / CONFIG_FILENAME).write_text(text, encoding="utf-8")
        with contextlib.suppress(ConfigError):
            assert isinstance(load_project_config(root), ProjectConfig)
        (root / ENVIRONMENTS_FILENAME).write_text(text, encoding="utf-8")
        with contextlib.suppress(ConfigError):
            load_hosts(Layout(root))


def test_undecodable_view_file_is_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v.yaml"
        path.write_bytes(b"title: \xff\xfe\n")
        assert _file_body(path) == {}


# Vega-Lite validator ---------------------------------------------------------------------
vega_keys = st.sampled_from(
    ["url", "href", "embedOptions", "mark", "data", "layer", "type", "values", "encoding", "x"]
)
vega_leaf = st.one_of(
    st.sampled_from(["image", "point", "bar", "http://evil.example/x.csv", 1, None, True])
)
vega_specs = st.recursive(
    vega_leaf,
    lambda kids: st.one_of(
        st.lists(kids, max_size=4), st.dictionaries(vega_keys, kids, max_size=4)
    ),
    max_leaves=30,
)
BLOCKED = {"url", "href", "embedOptions"}


def _oracle(node: Any, loc: tuple[Any, ...] = ()) -> list[tuple[tuple[Any, ...], str]]:
    """Every blocked key and image mark, in document order, written out on its own."""
    out: list[tuple[tuple[Any, ...], str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = (*loc, str(key))
            if key in BLOCKED:
                out.append((here, "external"))
            elif key == "mark" and (
                value == "image" or (isinstance(value, dict) and value.get("type") == "image")
            ):
                out.append((here, "image"))
            else:
                out.extend(_oracle(value, here))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            out.extend(_oracle(item, (*loc, i)))
    return out


@settings(max_examples=200, deadline=None)
@given(vega_specs)
@example({"layer": [{"mark": "point", "data": {"url": "x.csv"}}]})
@example({"mark": {"type": "image", "url": "x.png"}})
@example({"encoding": {"x": {"href": "javascript:alert(1)"}}})
def test_vega_validator_finds_exactly_the_blocked_parts(spec: Any) -> None:
    got = vega_spec_problems(spec, ("spec",))
    want = _oracle(spec, ("spec",))
    assert [loc for loc, _ in got] == [loc for loc, _ in want]
    for (_, message), (_, kind) in zip(got, want, strict=True):
        assert ("image" in message) == (kind == "image")
    if not want:  # a clean spec mentions no url anywhere a loader would read it
        assert "'url'" not in repr(spec) and "'href'" not in repr(spec)


@settings(max_examples=40, deadline=None)
@given(st.integers(1, 2000), st.booleans(), st.booleans())
@example(VEGA_MAX_DEPTH, True, False)
@example(VEGA_MAX_DEPTH + 1, True, False)
def test_vega_depth_and_cycles_are_bounded(depth: int, use_list: bool, cyclic: bool) -> None:
    spec: Any = {"url": "x"} if not cyclic else {"mark": "point"}
    root = spec
    for _ in range(depth - 1):
        spec = [spec] if use_list else {"layer": spec}
    if cyclic:
        root["layer"] = [spec]  # the innermost node now contains the outermost
    problems = vega_spec_problems(spec, ())
    if cyclic or depth > VEGA_MAX_DEPTH:
        assert problems == [((), f"vega_lite spec is too deep (over {VEGA_MAX_DEPTH} levels)")]
    else:
        assert len(problems) == 1 and "url" in problems[0][1]


@settings(max_examples=10, deadline=None)
@given(st.integers(10_001, 12_000))
def test_vega_size_is_bounded(n: int) -> None:
    problems = vega_spec_problems({"data": {"values": list(range(n))}})
    assert len(problems) == 1 and "too large" in problems[0][1]
