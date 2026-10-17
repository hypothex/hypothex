"""Real filesystem regressions for descriptor-pinned cleanup (no external services)."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

import hypothex.core.storage as storage
from hypothex.core.context import Context
from hypothex.core.records import Artifact, RunRecord
from hypothex.core.storage import CleanItem
from tests.core.test_storage import ended_run, plan, write
from tests.core.test_storage import toy as toy


@pytest.fixture
def tracked_fds(monkeypatch: pytest.MonkeyPatch) -> Iterator[set[int]]:
    """Account for every no-follow descriptor opened by the removal code."""
    opened: set[int] = set()
    real_open, real_close = os.open, os.close

    def open_fd(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if flags & os.O_NOFOLLOW:
            opened.add(fd)
        return fd

    def close_fd(fd: int) -> None:
        real_close(fd)
        opened.discard(fd)

    monkeypatch.setattr(os, "open", open_fd)
    monkeypatch.setattr(os, "close", close_fd)
    monkeypatch.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, open_fd})
    yield opened
    assert opened == set(), f"leaked cleanup descriptors: {opened}"


def apply(ctx: Context, proposed: storage.CleanPlan) -> storage.CleanResult:
    return storage.apply_clean(
        ctx, None, proposed.plan_id, confirm_bytes=proposed.total_bytes, actor="test"
    )


def assert_refused(
    ctx: Context, done: storage.CleanResult, run_id: str = "owner", *, n_items: int = 1
) -> None:
    assert done.deleted == [] and done.freed_bytes == 0 and len(done.skipped) == n_items
    assert storage.cleaned_artifacts(ctx, ctx.find_record(run_id)) == []


@pytest.mark.parametrize("directory", [False, True])
@pytest.mark.parametrize("when", ["before-pin", "after-recheck", "syscall"])
def test_parent_replacement_never_follows_new_alias(
    toy: Context,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tracked_fds: set[int],
    directory: bool,
    when: str,
) -> None:
    protected = toy.run_dir(ended_run(toy, "protected"))
    target = (
        write(protected / "predictions" / "scores.jsonl") if directory else protected / "run.yaml"
    )
    before = target.read_bytes()
    parent = tmp_path / "scratch"
    leaf = "predictions" if directory else "run.yaml"
    candidate = parent / leaf
    if directory:
        write(candidate / "data")
        (candidate / "metadata-link").symlink_to(target)
    else:
        write(candidate)
    ended_run(toy, "owner", artifacts=[("checkpoint", candidate)])
    proposed = plan(toy)
    assert len(proposed.items) == 1
    swapped = False

    def swap() -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            parent.rename(tmp_path / "old-scratch")
            parent.symlink_to(protected, target_is_directory=True)

    if when == "before-pin":
        original_open = storage._open_cleanup_parent

        def pin(path: str) -> tuple[int, Path]:
            swap()
            return original_open(path)

        monkeypatch.setattr(storage, "_open_cleanup_parent", pin)
    elif when == "after-recheck":
        original_check = storage._recheck

        def check(
            ctx: Context, item: CleanItem, users: list[tuple[str, RunRecord]], cutoff: datetime
        ) -> str | None:
            reason = original_check(ctx, item, users, cutoff)
            if reason is None:
                swap()
            return reason

        monkeypatch.setattr(storage, "_recheck", check)
    elif directory:
        original_rmtree = shutil.rmtree

        def remove_tree(path: str, *, dir_fd: int | None = None) -> None:
            assert path == leaf and dir_fd is not None
            swap()
            original_rmtree(path, dir_fd=dir_fd)

        remove_tree.avoids_symlink_attacks = True  # type: ignore[attr-defined]
        monkeypatch.setattr(shutil, "rmtree", remove_tree)
    else:
        original_unlink = os.unlink

        def unlink(path: Any, *, dir_fd: int | None = None) -> None:
            if path == leaf and dir_fd is not None:
                swap()
            original_unlink(path, dir_fd=dir_fd)

        monkeypatch.setattr(os, "unlink", unlink)
        monkeypatch.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, unlink})
    done = apply(toy, proposed)
    assert swapped and target.read_bytes() == before
    if when == "syscall":
        # The pathname now points into metadata, but the actual syscall uses the old fd.
        assert len(done.deleted) == 1 and not (tmp_path / "old-scratch" / leaf).exists()
        assert done.freed_bytes == proposed.total_bytes
    else:
        assert_refused(toy, done)
        assert (tmp_path / "old-scratch" / leaf).exists()


@pytest.mark.parametrize("directory", [False, True])
def test_leaf_replacement_during_measure_is_refused(
    toy: Context,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tracked_fds: set[int],
    directory: bool,
) -> None:
    leaf = tmp_path / "scratch" / "candidate"
    write(leaf / "data" if directory else leaf)
    ended_run(toy, "owner", artifacts=[("checkpoint", leaf)])
    proposed = plan(toy)
    before = leaf.stat()
    original_measure = storage._measure_at
    replaced = False
    root_calls = 0

    def measure(parent_fd: int, name: str) -> tuple[int, int, float]:
        nonlocal replaced, root_calls
        if name == leaf.name:
            root_calls += 1
        # Directory reporting walks once in _recheck; files use a direct lstat.
        # Replace only during the subsequent pinned destructive measurement.
        final_walk = 2 if directory else 1
        if name == leaf.name and root_calls == final_walk and not replaced:
            replaced = True
            leaf.rename(leaf.with_name("original"))
            write(leaf / "data" if directory else leaf)
            if directory:
                data = leaf / "data"
                source = leaf.with_name("original") / "data"
                os.utime(data, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns))
            os.utime(leaf, ns=(before.st_atime_ns, before.st_mtime_ns))
        return original_measure(parent_fd, name)

    monkeypatch.setattr(storage, "_measure_at", measure)
    done = apply(toy, proposed)
    assert replaced
    assert_refused(toy, done)
    assert leaf.exists() and leaf.with_name("original").exists()


def test_unreadable_descendant_fails_closed(
    toy: Context, tmp_path: Path, tracked_fds: set[int]
) -> None:
    if os.geteuid() == 0:
        pytest.skip("permission acceptance requires a non-root process")
    folder = tmp_path / "scratch" / "candidate"
    hidden = folder / "hidden"
    target = write(hidden / "keep")
    ended_run(toy, "owner", artifacts=[("checkpoint", folder)])
    hidden.chmod(0o100)
    try:
        proposed = plan(toy)
        done = apply(toy, proposed)
        assert_refused(toy, done)
        assert target.exists()
    finally:
        hidden.chmod(0o700)


def test_missing_safe_rmtree_never_falls_back(
    toy: Context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracked_fds: set[int]
) -> None:
    path = write(tmp_path / "scratch" / "candidate")
    ended_run(toy, "owner", artifacts=[("checkpoint", path)])
    proposed = plan(toy)
    monkeypatch.setattr(shutil.rmtree, "avoids_symlink_attacks", False)
    done = apply(toy, proposed)
    assert_refused(toy, done)
    assert done.skipped[0]["reason"] == "safe removal unavailable" and path.exists()


class ReadOnlyTraversal:
    """Simulate a platform without O_PATH/O_SEARCH without changing global os."""

    def __getattr__(self, name: str) -> Any:
        if name in ("O_PATH", "O_SEARCH"):
            raise AttributeError(name)
        return getattr(os, name)


@pytest.mark.parametrize("mode", [0o100, 0o300, 0o700])
@pytest.mark.parametrize("directory", [False, True])
@pytest.mark.parametrize("fallback_phase", ["native", "before-plan", "after-plan"])
def test_search_only_ancestors(
    toy: Context,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tracked_fds: set[int],
    mode: int,
    directory: bool,
    fallback_phase: str,
) -> None:
    if os.geteuid() == 0:
        pytest.skip("permission acceptance requires a non-root process")
    ancestor = tmp_path / "search-only"
    candidate = ancestor / "writable" / "candidate"
    payload = write(candidate / "data" if directory else candidate)
    before = payload.read_bytes()
    ended_run(toy, "owner", artifacts=[("checkpoint", candidate)])
    ancestor.chmod(mode)
    try:
        if fallback_phase == "before-plan":
            monkeypatch.setattr(storage, "os", ReadOnlyTraversal())
        search_open = hasattr(storage.os, "O_PATH") or hasattr(storage.os, "O_SEARCH")
        proposed = plan(toy)
        assert len(proposed.items) == 1
        if directory and mode != 0o700 and not search_open:
            # Reporting also pins ancestors. Missing search-open support must
            # remain an unavailable measurement, not an unsafe pathname walk.
            assert storage.measure_path(candidate) == (0, 0, None)
            assert proposed.total_bytes == 0 and proposed.items[0].mtime is None
        else:
            assert proposed.total_bytes > 0 and proposed.items[0].mtime is not None
        if fallback_phase == "after-plan":
            monkeypatch.setattr(storage, "os", ReadOnlyTraversal())
            search_open = False
        done = apply(toy, proposed)
        if mode != 0o700 and not search_open:
            assert_refused(toy, done)
            assert done.skipped[0]["reason"] == "changed or inaccessible since plan"
            assert candidate.exists() and payload.read_bytes() == before
        else:
            assert len(done.deleted) == 1 and not candidate.exists()
            assert done.freed_bytes == proposed.total_bytes
    finally:
        ancestor.chmod(0o700)


@pytest.mark.parametrize("fallback", [False, True])
def test_search_only_writable_immediate_parent(
    toy: Context,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tracked_fds: set[int],
    fallback: bool,
) -> None:
    if os.geteuid() == 0:
        pytest.skip("permission acceptance requires a non-root process")
    candidate = write(tmp_path / "search-only" / "candidate")
    before = candidate.read_bytes()
    ended_run(toy, "owner", artifacts=[("checkpoint", candidate)])
    candidate.parent.chmod(0o300)
    try:
        if fallback:
            monkeypatch.setattr(storage, "os", ReadOnlyTraversal())
        search_open = hasattr(storage.os, "O_PATH") or hasattr(storage.os, "O_SEARCH")
        proposed = plan(toy)
        assert len(proposed.items) == 1 and proposed.total_bytes > 0
        done = apply(toy, proposed)
        if search_open:
            assert len(done.deleted) == 1 and not candidate.exists()
            assert done.freed_bytes == proposed.total_bytes
        else:
            assert_refused(toy, done)
            assert done.skipped[0]["reason"] == "changed or inaccessible since plan"
            assert candidate.exists() and candidate.read_bytes() == before
    finally:
        candidate.parent.chmod(0o700)


def test_successful_directory_cleanup_preserves_symlink_target(
    toy: Context, tmp_path: Path, tracked_fds: set[int]
) -> None:
    target = toy.run_dir(ended_run(toy, "protected")) / "run.yaml"
    before = target.read_bytes()
    folder = tmp_path / "scratch" / "folder"
    write(folder / "data")
    (folder / "link").symlink_to(target)
    ended_run(toy, "owner", artifacts=[("checkpoint", folder)])
    proposed = plan(toy)
    done = apply(toy, proposed)
    assert len(done.deleted) == 1 and done.freed_bytes == proposed.total_bytes
    assert not folder.exists() and target.read_bytes() == before


def test_new_file_record_reader_missing_from_index_blocks_cleanup(
    toy: Context, tmp_path: Path
) -> None:
    path = write(tmp_path / "scratch" / "candidate")
    ended_run(toy, "owner", artifacts=[("checkpoint", path)])
    proposed = plan(toy)
    reader = ended_run(toy, "reader", archived=False, vars={"checkpoint": str(path)})
    # Simulate a file-first create whose indexing has not completed.
    toy.index.delete_run(reader.run_id)
    done = apply(toy, proposed)
    assert_refused(toy, done)
    assert path.exists() and done.skipped[0]["reason"] == "used by reader"


def test_current_file_flags_override_stale_index_for_other_owner(
    toy: Context, tmp_path: Path
) -> None:
    path = write(tmp_path / "scratch" / "candidate")
    ended_run(toy, "owner", artifacts=[("checkpoint", path)])
    other = ended_run(toy, "other", artifacts=[("checkpoint", path)])
    proposed = plan(toy)
    assert {item.run_id for item in proposed.items} == {"other", "owner"}
    toy.store.write_record(other.model_copy(update={"starred": True}))
    done = apply(toy, proposed)
    assert_refused(toy, done, n_items=2)
    assert path.exists() and done.skipped[0]["reason"] in {"starred", "used by other"}


def test_remote_host_artifact_label_cannot_authorize_local_delete(
    toy: Context, tmp_path: Path
) -> None:
    path = write(tmp_path / "scratch" / "candidate")
    owner = ended_run(toy, "owner", artifacts=[("checkpoint", path)])
    proposed = plan(toy)
    toy.store.write_record(
        owner.model_copy(
            update={"artifacts": [Artifact(path=str(path), kind="checkpoint", host="gpu1")]}
        )
    )
    done = apply(toy, proposed)
    assert_refused(toy, done)
    assert path.exists()


@pytest.mark.parametrize("name", ["run.yaml", "metrics.jsonl", "scores.jsonl", "run-folder"])
def test_parent_alias_of_home_protects_metadata_and_run_folder(
    tmp_path: Path, toy_repo: Path, name: str
) -> None:
    real_parent = tmp_path / "physical"
    real_parent.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)
    ctx = Context.open(alias / "home")
    ctx.register_project(toy_repo)
    folder = ctx.layout.run_dir("toy", "owner").resolve()
    target = folder if name == "run-folder" else folder / name
    ended_run(ctx, "owner", artifacts=[("checkpoint", target)])
    if not target.exists():
        target.write_text("metadata\n")
    assert storage.protected_reason(ctx, str(target)) == "protected"
    proposed = plan(ctx)
    assert proposed.items == [] and proposed.refused[0]["reason"] == "protected"
    size, _, mtime = storage.measure_path(target)
    forged = CleanItem(
        project="toy",
        run_id="owner",
        host="local",
        environment_id=ctx.descriptor.environment_id,
        kind="artifact",
        artifact_kind="checkpoint",
        path=str(target),
        bytes=size,
        mtime=mtime,
        reason="test",
    )
    done = storage.delete_artifacts(ctx, [forged], actor="x", plan_id="cp-test", older_than_days=30)
    assert_refused(ctx, done)
    assert target.exists()


def test_unreadable_run_record_refuses_cleanup(toy: Context, tmp_path: Path) -> None:
    path = write(tmp_path / "scratch" / "candidate")
    ended_run(toy, "owner", artifacts=[("checkpoint", path)])
    proposed = plan(toy)
    record = ended_run(toy, "reader", archived=False)
    toy.run_dir(record).joinpath("run.yaml").write_text("malformed: [\n")
    done = apply(toy, proposed)
    assert_refused(toy, done)
    assert path.exists() and done.skipped[0]["reason"] == "run metadata unavailable"


def test_measure_does_not_follow_a_directory_swapped_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracked_fds: set[int]
) -> None:
    folder = tmp_path / "candidate"
    write(folder / "own", 10)
    outside = write(tmp_path / "outside" / "secret", 1_000_000)
    original_scandir = os.scandir
    original_open = os.open
    swapped = False

    def swap() -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            folder.rename(tmp_path / "original")
            folder.symlink_to(outside.parent, target_is_directory=True)

    def scandir(path: Any) -> Any:
        if path == folder:
            swap()
        return original_scandir(path)

    def open_fd(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        if path == folder.name and dir_fd is not None:
            swap()
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(os, "open", open_fd)
    monkeypatch.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, open_fd})
    size, _, _ = storage.measure_path(folder)
    assert swapped and size < storage.measure_path(outside)[0]
    assert outside.exists()


@pytest.mark.parametrize("action", ["star", "unarchive"])
def test_curation_waits_for_cleanup(toy: Context, action: str) -> None:
    import threading

    from hypothex.core.queries import archive_run, star_run

    record = ended_run(toy, "owner")
    started = threading.Event()
    finished = threading.Event()

    def curate() -> None:
        started.set()
        if action == "star":
            star_run(toy, record.run_id)
        else:
            archive_run(toy, record.run_id, False)
        finished.set()

    worker = threading.Thread(target=curate)
    with storage.cleanup_lock(toy.layout):
        worker.start()
        assert started.wait(5)
        assert not finished.wait(0.1)
        current = toy.find_record(record.run_id)
        assert current.archived and not current.starred
    worker.join(10)
    assert finished.is_set()


def test_resolved_target_of_symlinked_pulled_folder_is_not_owned(
    toy: Context, tmp_path: Path
) -> None:
    record = ended_run(toy, "owner", environment_id="env-remote")
    outside = write(tmp_path / "outside" / "keep")
    pulled = toy.run_dir(record) / "pulled"
    pulled.symlink_to(outside.parent, target_is_directory=True)
    size, _, mtime = storage.measure_path(outside)
    forged = CleanItem(
        project="toy",
        run_id="owner",
        host="local",
        environment_id=toy.descriptor.environment_id,
        kind="pulled",
        artifact_kind=None,
        path=str(outside),
        bytes=size,
        mtime=mtime,
        reason="test",
    )
    done = storage.delete_artifacts(toy, [forged], actor="x", plan_id="cp-test", older_than_days=30)
    assert_refused(toy, done)
    assert outside.exists()


@pytest.mark.parametrize(
    "name", [".hx/evaluation.json", "src/train.py", "predictions/scores.v1.jsonl"]
)
def test_artifact_labels_cannot_authorize_source_or_score_binding_cleanup(
    toy: Context, name: str
) -> None:
    path = toy.layout.run_dir("toy", "owner") / name
    record = ended_run(toy, "owner", artifacts=[("checkpoint", path)])
    write(path)
    before = path.read_bytes()
    proposed = plan(toy)
    assert proposed.items == [] and proposed.refused[0]["reason"] == "protected"
    size, _, mtime = storage.measure_path(path)
    forged = CleanItem(
        project="toy",
        run_id="owner",
        host="local",
        environment_id=record.environment_id,
        kind="artifact",
        artifact_kind="checkpoint",
        path=str(path),
        bytes=size,
        mtime=mtime,
        reason="test",
    )
    done = storage.delete_artifacts(toy, [forged], actor="x", plan_id="cp-test", older_than_days=30)
    assert_refused(toy, done)
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["starred", "running", "recent"])
@pytest.mark.parametrize("directory", [False, True])
def test_apply_rechecks_local_pulled_ownership_of_mirrored_run(
    toy: Context, directory: bool, change: str
) -> None:
    from datetime import timedelta

    from hypothex.core.ids import utcnow
    from hypothex.core.records import RunStatus

    mirror = ended_run(toy, "b-mirror", environment_id="env-remote")
    candidate = toy.run_dir(mirror) / "pulled" / "checkpoint"
    target = write(candidate / "weights.pt" if directory else candidate)
    owner = ended_run(toy, "a-owner", artifacts=[("checkpoint", candidate)])
    proposed = plan(toy, include_pulled=True)
    assert len(proposed.items) == 2 and proposed.items[0].run_id == owner.run_id
    changes: dict[str, Any] = {
        "starred": {"starred": True},
        "running": {"status": RunStatus.RUNNING, "ended_at": None},
        "recent": {"ended_at": utcnow() - timedelta(days=1)},
    }
    # Keep the index stale: authoritative file state must guard the local copy.
    toy.store.write_record(mirror.model_copy(update=changes[change]))
    fresh = plan(toy, include_pulled=False)
    assert fresh.items == [] and fresh.refused[0]["reason"] == "used by b-mirror"
    checked = storage.check_artifacts(toy, proposed.items, older_than_days=30)
    assert checked and checked[0]["reason"] == "used by b-mirror"
    before = toy.events.last_sequence()
    done = apply(toy, proposed)
    assert_refused(toy, done, owner.run_id, n_items=2)
    assert done.skipped[0]["reason"] == "used by b-mirror" and target.exists()
    assert storage.cleaned_artifacts(toy, mirror) == []
    assert not any(event.type == "run.artifacts_cleaned" for event in toy.events.since(before))


def test_new_unindexed_mirror_pulled_ownership_is_rechecked_at_apply(toy: Context) -> None:
    from datetime import timedelta

    from hypothex.core.ids import utcnow
    from tests.factories import make_record

    target = write(toy.layout.run_dir("toy", "b-mirror") / "pulled" / "weights.pt")
    owner = ended_run(toy, "a-owner", artifacts=[("checkpoint", target)])
    proposed = plan(toy, include_pulled=False)
    mirror = make_record(
        "b-mirror",
        environment_id="env-remote",
        archived=True,
        starred=True,
        ended_at=utcnow() - timedelta(days=40),
    )
    # A mirror arrives after planning, with its local copied files already present.
    toy.store.write_record(mirror)
    assert toy.index.get_run(mirror.run_id) is None
    done = apply(toy, proposed)
    assert_refused(toy, done, owner.run_id)
    assert target.exists() and done.skipped[0]["reason"] == "used by b-mirror"
    assert storage.cleaned_artifacts(toy, mirror) == []


def test_mirrored_source_at_same_raw_path_does_not_own_local_artifact(
    toy: Context, tmp_path: Path
) -> None:
    target = write(tmp_path / "scratch" / "weights.pt")
    owner = ended_run(toy, "a-owner", artifacts=[("checkpoint", target)])
    mirror = ended_run(
        toy,
        "b-mirror",
        environment_id="env-remote",
        starred=True,
        artifacts=[("checkpoint", target)],
    )
    proposed = plan(toy, include_pulled=False)
    assert len(proposed.items) == 1 and proposed.items[0].run_id == owner.run_id
    done = apply(toy, proposed)
    assert done.deleted == proposed.items and done.freed_bytes == proposed.total_bytes
    assert not target.exists() and storage.cleaned_artifacts(toy, mirror) == []
    assert storage.cleaned_artifacts(toy, owner)[0].environment_id == toy.descriptor.environment_id
