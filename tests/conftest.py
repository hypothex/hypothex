from pathlib import Path

import pytest

from hypothex.core.context import Context
from tests.factories import write_toy_project


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "hxhome"
    monkeypatch.setenv("HYPOTHEX_HOME", str(h))
    monkeypatch.delenv("HYPOTHEX_AGENT", raising=False)
    return h


@pytest.fixture
def ctx(home: Path) -> Context:
    return Context.open(home)


@pytest.fixture
def toy_repo(tmp_path: Path) -> Path:
    return write_toy_project(tmp_path / "toy")
