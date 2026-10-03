"""Property tests: bootstrap ``_render`` hands any value to ``sh`` byte for byte."""

import re
import shlex
import subprocess

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from hypothex.remote import bootstrap
from hypothex.remote.bootstrap import _render

# sh cannot hold NUL in a variable; every other character must survive
values = st.text(
    st.characters(blacklist_categories=["Cs"], blacklist_characters="\x00"), max_size=40
)


def _assignments(rendered: str) -> str:
    """The ``HX_*=...`` prelude of a rendered script (before the script body)."""
    body = bootstrap.BOOTSTRAP_SCRIPTS["probe"]
    assert rendered.endswith("\n" + body)
    return rendered[: -len(body)]


@settings(max_examples=40, deadline=None)
@given(values, values)
@example("'; touch /tmp/hx-pwned; '", "$(id)`id`\\")
@example("\n\nexport X=1\n", "--")
@example("'\"'\"'", "~/.hypothex")
@example("", "é \t\r")
def test_rendered_values_round_trip_through_sh(first: str, second: str) -> None:
    rendered = _render("probe", HX_X=first, HX_Y=second)
    prelude = _assignments(rendered)
    probe = prelude + 'printf %s "$HX_X"; printf "\\0"; printf %s "$HX_Y"'
    out = subprocess.run(["sh", "-c", probe], capture_output=True, check=True)
    assert out.stdout.decode("utf-8", "surrogateescape").split("\0") == [first, second]
    assert out.stderr == b""


@settings(max_examples=60, deadline=None)
@given(st.text(max_size=12))
@example("HX_A\n")
@example("HX_A\nrm -rf ~\nHX_B")
@example("HX_a")
def test_parameter_names_are_exactly_hx_upper(name: str) -> None:
    if re.fullmatch(r"HX_[A-Z_]+", name):
        assert _render("probe", **{name: "v"}).startswith(f"{name}={shlex.quote('v')}\n")
    else:
        with pytest.raises(ValueError, match="bad script parameter name"):
            _render("probe", **{name: "v"})


def test_regression_parameter_name_with_trailing_newline_is_refused() -> None:
    # re.match("^HX_[A-Z_]+$") accepted "HX_A\n": "$" matches before a final newline
    with pytest.raises(ValueError):
        _render("probe", **{"HX_A\n": "v"})
