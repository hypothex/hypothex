import re
from pathlib import Path

import typer

from hypothex.cli.main import app

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
