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
