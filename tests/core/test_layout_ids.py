import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hypothex.core.ids import new_command_id, new_run_id
from hypothex.core.layout import Layout, default_home


def test_default_home_respects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HYPOTHEX_HOME", str(tmp_path / "h"))
    assert default_home() == tmp_path / "h"


def test_layout_paths(tmp_path: Path) -> None:
    lay = Layout(tmp_path)
    assert lay.run_dir("p", "r") == tmp_path / "store" / "p" / "runs" / "r"
    assert lay.worktrees_dir("p") == tmp_path / "store" / "p" / "worktrees"
    assert lay.index_db == tmp_path / "index.db"
    lay.ensure()
    assert lay.store.is_dir()


def test_new_run_id_format_and_uniqueness() -> None:
    when = datetime(2026, 9, 26, 14, 32, 5, tzinfo=UTC)
    rid = new_run_id("USPTO 50k Top-K!", now=when)
    assert re.fullmatch(r"20260926-143205-uspto-50k-top-k-[0-9a-f]{8}", rid)
    assert new_run_id(None, now=when).split("-")[2] == "explore"
    assert len({new_run_id("t", now=when) for _ in range(2000)}) == 2000  # 32 random bits
    assert re.fullmatch(r"[0-9a-f]{16}", new_command_id())


def test_reserved_run_path_ignores_case_and_unicode_form() -> None:
    from hypothex.core.layout import reserved_run_path

    for path in (".hx/a", ".HX/a", ".Hx", "./.hX/mirror-skips.json", "．hx/a"):
        assert reserved_run_path(path), path
    for path in ("", "predictions/.HX", "hx/a", ".hxx/a", "a/.hx"):
        assert not reserved_run_path(path), path
