import re
import textwrap
from pathlib import Path

import typer

from hypothex.cli.main import app
from hypothex.core.views import validate_view_text

SKILL = Path(__file__).resolve().parents[1] / "skills" / "hypothex" / "SKILL.md"


def test_skill_frontmatter() -> None:
    text = SKILL.read_text()
    assert text.startswith("---\nname: hypothex\ndescription: Use when")


def test_every_hx_command_in_skill_exists() -> None:
    group = typer.main.get_command(app)
    known = set(group.commands)  # ty: ignore[unresolved-attribute]
    used = set(re.findall(r"\bhx ([a-z]+)", SKILL.read_text()))
    assert used, "skill mentions no commands"
    assert used <= known, f"unknown commands in SKILL.md: {used - known}"


def test_every_hx_view_subcommand_in_skill_exists() -> None:
    group = typer.main.get_command(app)
    view_group = group.commands["view"]  # ty: ignore[unresolved-attribute]
    known = set(view_group.commands)  # ty: ignore[unresolved-attribute]
    used = set(re.findall(r"\bhx view ([a-z]+)", SKILL.read_text()))
    assert used == {"list", "show", "init", "validate", "add"}
    assert used <= known, f"unknown view commands in SKILL.md: {used - known}"


def test_skill_names_mcp_view_tools() -> None:
    text = SKILL.read_text()
    for tool in ("list_views", "get_view", "add_view", "query_view"):
        assert f"`{tool}`" in text, tool
    assert ".hypothex/views/<task>/<name>.yaml" in text


def test_views_docs_page_is_in_toctree() -> None:
    docs = SKILL.parents[2] / "docs"
    assert "   views\n" in (docs / "index.rst").read_text()
    page = (docs / "views.rst").read_text()
    for command in ("hx view list", "hx view init", "hx view add", "hx view validate"):
        assert command in page, command


def test_views_docs_example_validates() -> None:
    # The page's own example must pass `hx view validate` for a task whose metric is solved.
    page = (SKILL.parents[2] / "docs" / "views.rst").read_text()
    example = page.split("Example\n-------\n", 1)[1]
    block = example.split(".. code-block:: yaml\n\n", 1)[1].split("\n\n", 1)[0]
    view, issues = validate_view_text(textwrap.dedent(block), {"solved"}, {})
    assert view is not None and view.title == "route quality"
    assert issues == []  # e.g. `x: cost` would report "unknown metric cost"
    scatter = next(p for p in view.panels if p.type == "scatter")
    assert (scatter.data.x, scatter.data.y) == ("usage.usd", "solved")


def test_skill_remote_section_uses_real_commands_and_tools() -> None:
    text = SKILL.read_text()
    group = typer.main.get_command(app)
    expected = {"hosts": {"status", "map", "connect"}, "sweep": {"show", "extend", "cancel"}}
    for sub, used_expected in expected.items():
        known = set(group.commands[sub].commands)  # ty: ignore[unresolved-attribute]
        used = set(re.findall(rf"\bhx {sub} ([a-z]+)", text))
        assert used == used_expected, sub
        assert used <= known, f"unknown {sub} commands in SKILL.md: {used - known}"
    for tool in (
        "list_hosts",
        "launch_run",
        "launch_sweep",
        "get_sweep",
        "cancel_sweep",
        "extend_sweep",
        "pull_artifact",
    ):
        assert f"`{tool}" in text, tool


def test_remote_docs_page_is_in_toctree_and_names_real_commands() -> None:
    docs = SKILL.parents[2] / "docs"
    assert "   ui\n   remote\n" in (docs / "index.rst").read_text()
    page = (docs / "remote.rst").read_text()
    group = typer.main.get_command(app)
    top = set(group.commands)  # ty: ignore[unresolved-attribute]
    used = set(re.findall(r"\bhx ([a-z]+)", page))
    assert used <= top, f"unknown commands in remote.rst: {used - top}"
    for sub in ("hosts", "sweep", "service"):
        known = set(group.commands[sub].commands)  # ty: ignore[unresolved-attribute]
        named = set(re.findall(rf"\bhx {sub} ([a-z]+)", page))
        assert named <= known, f"unknown {sub} commands in remote.rst: {named - known}"
    for phrase in (
        "hx hosts add",
        "hx hosts map",
        "hx launch --host",
        "hx sweep -t",
        "hx sweep extend",
        "hx pull",
        "hx service install",
        "demo --with-hosts",
        "HYPOTHEX_HUB_URL",
        "environments.yaml",
        "pull_artifact",
    ):
        assert phrase in page, phrase
