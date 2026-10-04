"""Rebuilds stay isolated even where advisory file locking is unavailable."""

import errno
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from hypothex.core import index as index_module
from hypothex.core.context import Context
from hypothex.core.store import RunStore
from tests.factories import make_record


@pytest.mark.parametrize("mutation", ["none", "update", "create", "delete"])
def test_overlapping_rebuilds_without_flock_keep_separate_staging_files(
    ctx: Context, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    ctx.create_run(make_record("kept"))
    staged, resume = Event(), Event()
    original_build = index_module._build_fresh
    builds = 0

    def unsupported_lock(fd: int, operation: int) -> None:
        raise OSError(errno.ENOLCK, "filesystem has no advisory locks")

    def build_then_pause(path: Path, store: RunStore) -> int:
        nonlocal builds
        builds += 1
        first = builds == 1
        count = original_build(path, store)
        if first:
            staged.set()
            assert resume.wait(10)
        return count

    monkeypatch.setattr(
        index_module,
        "fcntl",
        SimpleNamespace(
            flock=unsupported_lock,
            LOCK_EX=index_module.fcntl.LOCK_EX,
            LOCK_UN=index_module.fcntl.LOCK_UN,
        ),
    )
    monkeypatch.setattr(index_module, "_build_fresh", build_then_pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(index_module.rebuild_index, ctx.index, ctx.store)
        try:
            assert staged.wait(10)
            if mutation == "update":
                ctx.update_run(
                    "kept", "run.tagged", lambda r: r.model_copy(update={"tags": ["new"]})
                )
            elif mutation == "create":
                ctx.create_run(make_record("added"))
            elif mutation == "delete":
                shutil.rmtree(ctx.run_dir(ctx.find_record("kept")))
                ctx.index.delete_run("kept")
            expected = ctx.store.list_run_ids()
            second = pool.submit(index_module.rebuild_index, ctx.index, ctx.store)
            assert second.result(timeout=10) == len(expected)
        finally:
            resume.set()
        assert first.result(timeout=10) == 1
    assert ctx.index.run_ids() == set(expected)
    for run_id, project in expected.items():
        assert ctx.index.get_run(run_id) == ctx.store.read_record(project, run_id)
    assert not list(ctx.index.path.parent.glob(ctx.index.path.name + ".tmp*"))
