"""Validate documented project examples against the actual config and CLI."""

import re
import shlex
import textwrap
from pathlib import Path

import pytest
import yaml
from typer.main import get_command

from hypothex.cli.main import app
from hypothex.core.config import ProjectConfig

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "document",
    ["docs/project_file.rst", "docs/superpowers/specs/2026-09-26-hypothex-design.md"],
)
def test_documented_project_stage_commands_exist(document: str) -> None:
    source = (ROOT / document).read_text()
    if document.endswith(".rst"):
        match = re.search(r"\.\. code-block:: yaml\n\n((?: {3}.*\n|\n)+)", source)
        assert match is not None
        example = textwrap.dedent(match.group(1))
    else:
        match = re.search(r"```yaml\n(project: deepretro\n.*?)```", source, re.DOTALL)
        assert match is not None
        example = match.group(1)
    config = ProjectConfig.model_validate(yaml.safe_load(example))
    commands = get_command(app).commands
    for name, command in config.stages.items():
        argv = shlex.split(command)
        if argv and argv[0] == "hx":
            assert len(argv) > 1 and argv[1] in commands, (
                f"{document}: stage {name} uses unsupported {argv[:2]}"
            )
