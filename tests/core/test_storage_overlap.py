"""Cleanup policy bindings and shared-path accounting regressions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import hypothex.core.storage as storage
from hypothex.core.context import Context
from hypothex.core.records import Artifact
from tests.core.test_storage import ended_run, plan, write
from tests.core.test_storage import toy as toy
from tests.core.test_storage_safety import tracked_fds as tracked_fds


@pytest.mark.parametrize("same_run", [False, True])
@pytest.mark.parametrize("relation", ["equal", "inside", "above"])
@pytest.mark.parametrize("reverse", [False, True])
def test_plan_refuses_excluded_overlapping_bindings(
    toy: Context, tmp_path: Path, same_run: bool, relation: str, reverse: bool
) -> None:
    folder = tmp_path / "scratch" / "model"
    leaf = write(folder / "weights.pt")
    selected, excluded = {"equal": (leaf, leaf), "inside": (folder, leaf), "above": (leaf, folder)}[
        relation
    ]
    bindings = [("checkpoint", selected), ("log", excluded)]
    if reverse:
        bindings.reverse()
    if same_run:
        ended_run(toy, "owner", artifacts=bindings)
    else:
        ended_run(toy, "owner", artifacts=[("checkpoint", selected)])
        ended_run(toy, "other", artifacts=[("log", excluded)])
    proposed = plan(toy, kinds=["checkpoint"])
    assert proposed.items == [] and proposed.total_bytes == 0
    assert any("not selected" in row["reason"] for row in proposed.refused)
    assert leaf.exists()


@pytest.mark.parametrize("same_run", [False, True])
@pytest.mark.parametrize("relation", ["equal", "inside"])
def test_selected_shared_bindings_delete_once_and_record_each_owner(
    toy: Context,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    same_run: bool,
    relation: str,
) -> None:
    folder = tmp_path / "scratch" / "model"
    leaf = write(folder / "weights.pt")
    outer = folder if relation == "inside" else leaf
    first = ended_run(toy, "a", artifacts=[("checkpoint", outer)])
    if same_run:
        toy.store.write_record(
            first.model_copy(
                update={
                    "artifacts": [
                        Artifact(kind="checkpoint", path=str(outer)),
                        Artifact(kind="log", path=str(leaf)),
                    ]
                }
            )
        )
        records = [first]
    else:
        records = [first, ended_run(toy, "b", artifacts=[("checkpoint", leaf)])]
    physical_bytes = storage.measure_path(outer)[0]
    proposed = plan(toy, kinds=["*"])
    assert len(proposed.items) == 2
    assert proposed.total_bytes == physical_bytes
    calls: list[str] = []
    original = storage._remove

    def remove(ctx: Context, item: storage.CleanItem, users: Any, cutoff: Any) -> str | None:
        calls.append(item.path)
        return original(ctx, item, users, cutoff)

    monkeypatch.setattr(storage, "_remove", remove)
    before = toy.events.last_sequence()
    done = storage.apply_clean(
        toy, None, proposed.plan_id, confirm_bytes=proposed.total_bytes, actor="test"
    )
    assert calls == [str(outer)] and not outer.exists()
    assert done.freed_bytes == physical_bytes and len(done.deleted) == 2 and done.skipped == []
    events = [e for e in toy.events.since(before) if e.type == "run.artifacts_cleaned"]
    assert {e.run_id for e in events} == {r.run_id for r in records}
    for record in records:
        markers = storage.cleaned_artifacts(toy, record)
        expected_paths = {i.path for i in proposed.items if i.run_id == record.run_id}
        assert {m.path for m in markers} == expected_paths
        assert len(markers) == len(expected_paths)
        assert all(m.environment_id == toy.descriptor.environment_id for m in markers)


@pytest.mark.parametrize("same_run", [False, True])
@pytest.mark.parametrize("late_kind", ["checkpoint", "log"])
def test_apply_refuses_new_unselected_binding(
    toy: Context, tmp_path: Path, same_run: bool, late_kind: str
) -> None:
    target = write(tmp_path / "scratch" / "weights.pt")
    owner = ended_run(toy, "owner", artifacts=[("checkpoint", target)])
    proposed = plan(toy)
    if same_run:
        # Same path, a different newly recorded kind; duplicate identical entries add no owner.
        late_kind = "log"
        toy.store.write_record(
            owner.model_copy(
                update={
                    "artifacts": [
                        *owner.artifacts,
                        Artifact(kind=late_kind, path=str(target)),
                    ]
                }
            )
        )
    else:
        ended_run(toy, "late", artifacts=[(late_kind, target)])
    checked = storage.check_artifacts(toy, proposed.items, older_than_days=30)
    assert checked and "not selected" in checked[0]["reason"]
    done = storage.apply_clean(
        toy, None, proposed.plan_id, confirm_bytes=proposed.total_bytes, actor="test"
    )
    assert done.deleted == [] and done.freed_bytes == 0 and target.exists()
    assert storage.cleaned_artifacts(toy, owner) == []


def test_excluding_pulled_copies_protects_overlapping_artifact(toy: Context) -> None:
    mirror = ended_run(toy, "mirror", environment_id="remote")
    target = write(toy.run_dir(mirror) / "pulled" / "weights.pt")
    ended_run(toy, "owner", artifacts=[("checkpoint", target)])
    proposed = plan(toy, include_pulled=False)
    assert proposed.items == [] and "not selected" in proposed.refused[0]["reason"]


def test_shared_group_failure_writes_no_owner_markers(toy: Context, tmp_path: Path) -> None:
    target = write(tmp_path / "scratch" / "weights.pt")
    first = ended_run(toy, "a", artifacts=[("checkpoint", target)])
    second = ended_run(toy, "b", artifacts=[("checkpoint", target)])
    proposed = plan(toy)
    toy.store.write_record(second.model_copy(update={"starred": True}))
    done = storage.apply_clean(
        toy, None, proposed.plan_id, confirm_bytes=proposed.total_bytes, actor="test"
    )
    assert done.deleted == [] and done.freed_bytes == 0 and target.exists()
    assert len(done.skipped) == 2
    assert storage.cleaned_artifacts(toy, first) == storage.cleaned_artifacts(toy, second) == []


@pytest.mark.parametrize("directory", [False, True])
@pytest.mark.parametrize("when", ["before-remove", "during-measure", "syscall"])
def test_group_member_alias_retarget_never_creates_false_marker(
    toy: Context,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directory: bool,
    when: str,
    tracked_fds: set[int],
) -> None:
    import os
    import shutil

    real = tmp_path / "real"
    original = write(real / "weights.pt")
    other = write(tmp_path / "unrelated" / "weights.pt")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    root_path = real if directory else original
    first = ended_run(toy, "a", artifacts=[("checkpoint", root_path)])
    second = ended_run(toy, "b", artifacts=[("checkpoint", alias / "weights.pt")])
    proposed = plan(toy)
    assert len(proposed.items) == 2
    changed = False

    def retarget() -> None:
        nonlocal changed
        if not changed:
            changed = True
            alias.unlink()
            alias.symlink_to(other.parent, target_is_directory=True)

    if when == "before-remove":
        original_remove = storage._remove

        def remove(ctx: Context, item: storage.CleanItem, users: Any, cutoff: Any) -> str | None:
            retarget()
            return original_remove(ctx, item, users, cutoff)

        monkeypatch.setattr(storage, "_remove", remove)
    elif when == "during-measure":
        original_measure = storage._measure_at
        original_remove = storage._remove
        active = False

        def measure(fd: int, name: str) -> tuple[int, int, float]:
            if active:
                retarget()
            return original_measure(fd, name)

        def remove(ctx: Context, item: storage.CleanItem, users: Any, cutoff: Any) -> str | None:
            nonlocal active
            active = True
            return original_remove(ctx, item, users, cutoff)

        monkeypatch.setattr(storage, "_measure_at", measure)
        monkeypatch.setattr(storage, "_remove", remove)
    elif directory:
        original_rmtree = shutil.rmtree

        def rmtree(path: str, *, dir_fd: int | None = None) -> None:
            retarget()
            original_rmtree(path, dir_fd=dir_fd)

        rmtree.avoids_symlink_attacks = True  # type: ignore[attr-defined]
        monkeypatch.setattr(shutil, "rmtree", rmtree)
    else:
        original_unlink = os.unlink

        def unlink(path: Any, *, dir_fd: int | None = None) -> None:
            if path == original.name and dir_fd is not None:
                retarget()
            original_unlink(path, dir_fd=dir_fd)

        monkeypatch.setattr(os, "unlink", unlink)
        monkeypatch.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, unlink})
    done = storage.apply_clean(
        toy, None, proposed.plan_id, confirm_bytes=proposed.total_bytes, actor="test"
    )
    assert changed and other.exists() and (alias / "weights.pt").exists()
    assert storage.cleaned_artifacts(toy, second) == []
    if when == "syscall":
        assert [item.run_id for item in done.deleted] == ["a"]
        assert done.freed_bytes == proposed.total_bytes and not original.exists()
        assert len(storage.cleaned_artifacts(toy, first)) == 1
    else:
        assert done.deleted == [] and done.freed_bytes == 0 and original.exists()
        assert storage.cleaned_artifacts(toy, first) == []


def test_remote_alias_preflight_refuses_uncountable_group_but_direct_delete_is_safe(
    toy: Context, tmp_path: Path
) -> None:
    original = write(tmp_path / "real" / "weights.pt")
    alias = tmp_path / "alias"
    alias.symlink_to(original.parent, target_is_directory=True)
    first = ended_run(toy, "a", artifacts=[("checkpoint", original)])
    second = ended_run(toy, "b", artifacts=[("checkpoint", alias / "weights.pt")])
    local_plan = plan(toy)
    assert local_plan.total_bytes == storage.measure_path(original)[0]
    assert storage.check_artifacts(toy, local_plan.items, older_than_days=30) == []
    forwarded = [item.model_copy(update={"host": "gpu1"}) for item in local_plan.items]
    refused = storage.check_artifacts(toy, forwarded, older_than_days=30)
    assert len(refused) == 2
    assert {row["reason"] for row in refused} == {"filesystem aliases require a local cleanup plan"}
    assert storage.cleaned_artifacts(toy, first) == storage.cleaned_artifacts(toy, second) == []
    done = storage.delete_artifacts(
        toy, forwarded, actor="test", plan_id="cp-test", older_than_days=30
    )
    assert len(done.deleted) == 2 and done.freed_bytes == local_plan.total_bytes
    assert not original.exists()


@pytest.mark.parametrize("relation", ["shallower", "deeper", "reversed-root"])
def test_remote_preflight_refuses_inverse_alias_grouping(
    toy: Context, tmp_path: Path, relation: str
) -> None:
    selected = tmp_path / "deep" / "deeper" / "selected"
    selected.mkdir(parents=True)
    if relation == "reversed-root":
        outside = tmp_path / "deep"
        target = outside
        (selected / "alias").symlink_to(tmp_path, target_is_directory=True)
        child = selected / "alias" / "deep"
        write(outside / "weights.pt")
    else:
        outside = tmp_path / "outside"
        if relation == "deeper":
            outside = outside / "one" / "two" / "three" / "four"
        target = write(outside / "weights.pt")
        (selected / "alias").symlink_to(outside, target_is_directory=True)
        child = selected / "alias" / "weights.pt"
    first = ended_run(toy, "a", artifacts=[("checkpoint", selected)])
    second = ended_run(toy, "b", artifacts=[("checkpoint", child)])
    local_plan = plan(toy)
    assert len(local_plan.items) == 2
    assert storage.check_artifacts(toy, local_plan.items, older_than_days=30) == []
    forwarded = [item.model_copy(update={"host": "gpu1"}) for item in local_plan.items]
    refused = storage.check_artifacts(toy, forwarded, older_than_days=30)
    assert len(refused) == 2
    assert {row["reason"] for row in refused} == {"filesystem aliases require a local cleanup plan"}
    assert target.exists() and selected.exists()
    assert storage.cleaned_artifacts(toy, first) == storage.cleaned_artifacts(toy, second) == []


def test_remote_child_refusal_also_prunes_selected_overlapping_parent(toy: Context) -> None:
    from tests.core.test_storage import FakeHost, FakeHosts, remote_row

    class RefusingChild(FakeHost):
        def post_json(self, path: str, body: dict[str, Any]) -> Any:
            assert path == "/api/v1/storage/check"
            return [{"run_id": "b", "path": "/scratch/model/weights.pt", "reason": "changed"}]

    hosts = FakeHosts(
        RefusingChild(
            [
                remote_row("a", "/scratch/model"),
                remote_row("b", "/scratch/model/weights.pt"),
            ]
        )
    )
    proposed = plan(toy, hosts)
    assert proposed.items == [] and proposed.total_bytes == 0
    assert {row["run_id"] for row in proposed.refused} == {"a", "b"}
    assert (
        next(row["reason"] for row in proposed.refused if row["run_id"] == "a") == "not selected: b"
    )


def test_shared_group_missing_removal_capability_never_opens_or_marks(
    toy: Context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracked_fds: set[int]
) -> None:
    import shutil

    target = write(tmp_path / "scratch" / "weights.pt")
    records = [ended_run(toy, name, artifacts=[("checkpoint", target)]) for name in ("a", "b")]
    proposed = plan(toy)
    monkeypatch.setattr(shutil.rmtree, "avoids_symlink_attacks", False)
    done = storage.apply_clean(
        toy, None, proposed.plan_id, confirm_bytes=proposed.total_bytes, actor="test"
    )
    assert done.deleted == [] and done.freed_bytes == 0 and target.exists()
    assert len(done.skipped) == 2
    assert {row["reason"] for row in done.skipped} == {"safe removal unavailable"}
    assert all(storage.cleaned_artifacts(toy, record) == [] for record in records)
    assert tracked_fds == set()
