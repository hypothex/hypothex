import fcntl
import json
import os
import stat
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import hypothex.core.storage as storage_module
from hypothex.core.context import Context
from hypothex.core.execution import RunRequest, prepare_run
from hypothex.core.ids import utcnow
from hypothex.core.queries import show_run
from hypothex.core.records import Artifact, RunRecord, RunStatus
from hypothex.core.settings import StorageSettings
from hypothex.core.storage import (
    LOCAL_HOST,
    CleanedArtifact,
    CleanItem,
    CleanPlan,
    CleanPolicy,
    CleanRefusedError,
    StorageItem,
    apply_clean,
    cleaned_artifacts,
    cleanup_lock,
    delete_artifacts,
    input_paths,
    local_usage,
    measure_path,
    plan_clean,
    plans_dir,
    protected_reason,
    record_cleaned,
    storage_report,
)
from hypothex.remote.client import EnvUnreachableError
from hypothex.remote.config import EnvironmentsFile, HostSpec, save_hosts
from tests.factories import make_record


def blocks(path: Path) -> int:
    info = os.lstat(path)
    return info.st_blocks * 512 if hasattr(info, "st_blocks") else info.st_size


def ended_run(
    ctx: Context,
    run_id: str,
    *,
    days_ago: float = 40,
    artifacts: list[tuple[str, Path]] | None = None,
    archived: bool = True,
    starred: bool = False,
    status: RunStatus = RunStatus.FINISHED,
    parent: str | None = None,
    environment_id: str | None = None,
    vars: dict[str, Any] | None = None,
    cwd: str | None = None,
) -> RunRecord:
    ended = utcnow() - timedelta(days=days_ago)
    record = make_record(
        run_id,
        status=status,
        archived=archived,
        starred=starred,
        parent=parent,
        vars=vars or {},
        **({"cwd": cwd} if cwd is not None else {}),
        started_at=ended - timedelta(hours=1),
        ended_at=None if status == RunStatus.RUNNING else ended,
        artifacts=[Artifact(kind=k, path=str(p)) for k, p in artifacts or []],
        environment_id=environment_id or ctx.descriptor.environment_id,
    )
    ctx.create_run(record)
    return record


def write(path: Path, size: int = 10_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


class FakeHost:
    """A connected host's env client: answers the usage route with fixed rows."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.posted: list[dict[str, Any]] = []

    def get_json(self, path: str, **params: Any) -> Any:
        assert path == "/api/v1/storage/usage"
        return [
            r for r in self.rows if "project" not in params or r["project"] == params["project"]
        ]

    def post_json(self, path: str, body: dict[str, Any]) -> Any:
        if path == "/api/v1/storage/check":
            return []  # read-only preflight; dedicated tests inject alias refusals
        assert path == "/api/v1/storage/delete"
        self.posted.append(body)
        return {"plan_id": body["plan_id"], "deleted": body["items"], "skipped": [],
                "freed_bytes": sum(i["bytes"] for i in body["items"]), "errors": []}  # fmt: skip


class FakeHosts:
    """``HostClients`` with one live host (``gpu1``) and one that does not answer."""

    def __init__(self, gpu1: FakeHost) -> None:
        self.gpu1 = gpu1

    def names(self) -> list[str]:
        return ["gpu1", "dead"]

    def client(self, name: str) -> Any:
        if name == "dead":
            raise EnvUnreachableError("dead did not answer")
        return self.gpu1

    def host_for_environment(self, environment_id: str) -> str | None:
        return "gpu1" if environment_id == "env-gpu1" else None


def remote_row(run_id: str, path: str, *, kind: str = "artifact", **over: Any) -> dict[str, Any]:
    ended = (utcnow() - timedelta(days=40)).isoformat()
    row: dict[str, Any] = {
        "project": "toy", "run_id": run_id, "host": "local", "environment_id": "env-gpu1",
        "kind": kind, "artifact_kind": "checkpoint" if kind == "artifact" else None,
        "path": path, "bytes": 4096, "files": 1, "mtime": 1.0, "exists": True,
        "archived": True, "starred": False, "status": "finished", "ended_at": ended,
    }  # fmt: skip
    row.update(over)
    return row


@pytest.fixture
def toy(ctx: Context, toy_repo: Path) -> Context:
    ctx.register_project(toy_repo)
    return ctx


def test_measure_path(tmp_path: Path) -> None:
    a = write(tmp_path / "d" / "a.bin", 5000)
    b = write(tmp_path / "d" / "sub" / "b.bin", 9000)
    size, files, mtime = measure_path(tmp_path / "d")
    assert (size, files) == (blocks(a) + blocks(b), 2) and mtime is not None
    assert measure_path(a)[:2] == (blocks(a), 1)
    link = tmp_path / "link.bin"
    link.symlink_to(b)
    assert measure_path(link)[0] == blocks(link)  # the link, never its target
    assert measure_path(tmp_path / "missing") == (0, 0, None)


def test_protected_paths(toy: Context, toy_repo: Path, tmp_path: Path) -> None:
    record = ended_run(toy, "r1")
    run_dir = toy.run_dir(record)
    never = [
        Path("/"),
        Path.home(),
        toy.layout.home,
        toy_repo,
        toy_repo.parent,
        run_dir / "run.yaml",
        run_dir / "artifacts",
        toy.layout.store,
    ]
    for path in never:
        assert protected_reason(toy, str(path)) == "protected", path
    assert protected_reason(toy, str(run_dir / "artifacts" / "step_1.pt")) is None
    assert protected_reason(toy, str(run_dir / "pulled" / "x" / "y.pt")) is None
    assert protected_reason(toy, str(tmp_path / "scratch" / "ckpt.pt")) is None


@pytest.mark.parametrize("relocate", ["home", "store"])
def test_storage_base_aliases_protect_metadata_and_allow_artifacts(
    tmp_path: Path,
    toy_repo: Path,
    relocate: str,
) -> None:
    home = tmp_path / "home"
    if relocate == "home":
        real = tmp_path / "real-home"
        real.mkdir()
        home.symlink_to(real, target_is_directory=True)
    else:
        home.mkdir()
        real = tmp_path / "real-store"
        real.mkdir()
        (home / "store").symlink_to(real, target_is_directory=True)
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    record = ended_run(ctx, "aliased")
    folder = ctx.run_dir(record)
    for base in (folder, folder.resolve()):
        for name in ("run.yaml", "metrics.jsonl", "scores.jsonl", "predictions", "artifacts"):
            assert protected_reason(ctx, str(base / name)) == "protected"
        assert protected_reason(ctx, str(base)) == "protected"
        assert protected_reason(ctx, str(base / "artifacts" / "model.pt")) is None
        assert protected_reason(ctx, str(base / "pulled" / "model.pt")) is None
    outside = write(tmp_path / "outside" / "keep.pt")
    (folder / "pulled").symlink_to(outside.parent, target_is_directory=True)
    assert protected_reason(ctx, str(folder / "pulled" / outside.name)) == "protected"


def test_a_symlinked_pulled_folder_is_never_entered(toy: Context, tmp_path: Path) -> None:
    keep = write(tmp_path / "unrelated" / "keep.bin")
    run_dir = toy.run_dir(ended_run(toy, "r1"))
    (run_dir / "pulled").symlink_to(keep.parent, target_is_directory=True)
    assert [i for i in local_usage(toy) if i.kind == "pulled"] == []
    # the path reads as inside pulled/, but the folder links elsewhere: never ours to delete
    assert protected_reason(toy, str(run_dir / "pulled" / "keep.bin")) == "protected"
    assert keep.exists()


def test_local_usage_lists_runs_artifacts_and_pulled(toy: Context, tmp_path: Path) -> None:
    ckpt = write(tmp_path / "scratch" / "r1.pt")
    record = ended_run(toy, "r1", artifacts=[("checkpoint", ckpt), ("log", tmp_path / "nope")])
    inside = write(toy.run_dir(record) / "artifacts" / "best.pt", 20_000)
    pulled = write(toy.run_dir(record) / "pulled" / "remote.pt", 30_000)
    items = {(i.kind, Path(i.path).name): i for i in local_usage(toy)}
    run = items[("run", "r1")]
    assert run.host == LOCAL_HOST and run.archived and run.status == RunStatus.FINISHED
    assert run.bytes > 0 and run.bytes < blocks(inside)  # artifacts/ and pulled/ left out
    art = items[("artifact", "r1.pt")]
    assert (art.artifact_kind, art.bytes, art.exists) == ("checkpoint", blocks(ckpt), True)
    assert items[("artifact", "nope")].exists is False and items[("artifact", "nope")].bytes == 0
    assert items[("pulled", "remote.pt")].bytes == blocks(pulled)


def test_mirrored_runs_list_only_their_local_copies(toy: Context, tmp_path: Path) -> None:
    record = ended_run(toy, "m1", environment_id="env-gpu1",
                       artifacts=[("checkpoint", Path("/scratch/m1.pt"))])  # fmt: skip
    write(toy.run_dir(record) / "pulled" / "m1.pt")
    kinds = sorted(i.kind for i in local_usage(toy))
    assert kinds == ["pulled", "run"]


def test_report_sums_local_and_remote(toy: Context, tmp_path: Path) -> None:
    ended_run(toy, "r1", artifacts=[("checkpoint", write(tmp_path / "s" / "r1.pt"))])
    hosts = FakeHosts(FakeHost([remote_row("g1", "/scratch/g1.pt", bytes=1_000_000)]))
    report = storage_report(toy, hosts)
    assert report.errors == [{"host": "dead", "error": "dead did not answer"}]
    remote = [i for i in report.items if i.host == "gpu1"]
    assert [(i.run_id, i.bytes) for i in remote] == [("g1", 1_000_000)]
    assert report.by_host["gpu1"] == 1_000_000
    assert report.total_bytes == sum(i.bytes for i in report.items)
    assert sum(report.by_kind.values()) == sum(report.by_project.values()) == report.total_bytes
    assert all(isinstance(i, StorageItem) for i in report.items)
    local_only = storage_report(toy, hosts, remote=False)
    assert {i.host for i in local_only.items} == {LOCAL_HOST} and local_only.errors == []


SETTINGS = StorageSettings(plan_ttl_minutes=60)


def plan(ctx: Context, host_clients: Any = None, **policy: Any) -> CleanPlan:
    return plan_clean(
        ctx, host_clients, CleanPolicy(**policy), created_by="human:sv", settings=SETTINGS
    )


@pytest.fixture
def lab(toy: Context, tmp_path: Path) -> Context:
    scratch = tmp_path / "scratch"
    ended_run(toy, "old", artifacts=[("checkpoint", write(scratch / "old.pt"))])
    ended_run(toy, "recent", days_ago=10, artifacts=[("checkpoint", write(scratch / "recent.pt"))])
    ended_run(toy, "starred", starred=True, artifacts=[("checkpoint", write(scratch / "s.pt"))])
    ended_run(toy, "visible", archived=False, artifacts=[("checkpoint", write(scratch / "v.pt"))])
    ended_run(toy, "logs", artifacts=[("log", write(scratch / "train.log"))])
    shared = write(scratch / "shared.pt")
    ended_run(toy, "parent", artifacts=[("checkpoint", shared)])
    # what control.reinfer really writes: the input in vars, no child artifact
    ended_run(toy, "child", archived=False, parent="parent", vars={"checkpoint": str(shared)})
    return toy


def test_plan_lists_only_eligible_artifacts(lab: Context) -> None:
    result = plan(lab)
    assert [i.run_id for i in result.items] == ["old"]
    assert result.items[0].reason == "archived 40d"
    assert result.refused == [
        {"path": result.refused[0]["path"], "run_id": "parent", "reason": "used by child"}
    ]
    assert result.total_bytes == result.items[0].bytes
    assert sorted(i.run_id for i in plan(lab, kinds=["*"]).items) == ["logs", "old"]
    assert sorted(i.run_id for i in plan(lab, older_than_days=7).items) == ["old", "recent"]


def test_a_folder_artifact_holding_a_kept_file_is_refused(toy: Context, tmp_path: Path) -> None:
    models = tmp_path / "scratch" / "models"
    best = write(models / "best.pt")
    ended_run(toy, "old", artifacts=[("checkpoint", models)])
    ended_run(toy, "kept", starred=True, artifacts=[("checkpoint", best)])
    result = plan(toy)
    assert result.items == []
    assert result.refused == [{"path": str(models), "run_id": "old", "reason": "used by kept"}]


@pytest.mark.parametrize("alias", ["relative", "parent-symlink", "leaf-symlink"])
def test_plan_protects_checkpoint_input_aliases(toy: Context, tmp_path: Path, alias: str) -> None:
    checkpoint = write(tmp_path / "data" / "p.pt")
    parent = tmp_path / "alias"
    parent.symlink_to(checkpoint.parent, target_is_directory=True)
    leaf = tmp_path / "input.pt"
    leaf.symlink_to(checkpoint)
    value = {
        "relative": "data/p.pt",
        "parent-symlink": str(parent / "p.pt"),
        "leaf-symlink": str(leaf),
    }[alias]
    ended_run(toy, "parent", artifacts=[("checkpoint", checkpoint)])
    ended_run(toy, "reader", archived=False, vars={"checkpoint": value}, cwd=str(tmp_path))
    result = plan(toy)
    assert result.items == [] and checkpoint.exists()
    assert [row["reason"] for row in result.refused] == ["used by reader"]


def test_protected_artifacts_are_refused(toy: Context, toy_repo: Path) -> None:
    ended_run(toy, "bad", artifacts=[("checkpoint", toy_repo)])
    result = plan(toy)
    assert result.items == []
    assert result.refused == [{"path": str(toy_repo), "run_id": "bad", "reason": "protected"}]


def test_pulled_files_follow_include_pulled(toy: Context) -> None:
    record = ended_run(toy, "m1", environment_id="env-gpu1")
    write(toy.run_dir(record) / "pulled" / "m1.pt")
    assert [i.kind for i in plan(toy).items] == ["pulled"]
    assert plan(toy, include_pulled=False).items == []


def test_plan_file_event_and_expiry(lab: Context) -> None:
    before = lab.events.last_sequence()
    result = plan(lab)
    assert result.plan_id.startswith("cp-") and len(result.plan_id) == 11
    assert result.expires_at - result.created_at == timedelta(minutes=60)
    path = plans_dir(lab.layout) / f"{result.plan_id}.json"
    assert CleanPlan.model_validate_json(path.read_text()) == result
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    (event,) = [e for e in lab.events.since(before) if e.type == "storage.plan_created"]
    assert event.payload == {
        "plan_id": result.plan_id,
        "total_bytes": result.total_bytes,
        "n_items": 1,
    }
    later = plan_clean(
        lab, None, CleanPolicy(), created_by="human:sv", settings=SETTINGS,
        now=result.expires_at + timedelta(seconds=1),
    )  # fmt: skip
    assert not path.exists() and (plans_dir(lab.layout) / f"{later.plan_id}.json").exists()


def test_project_and_host_filters(lab: Context) -> None:
    assert plan(lab, projects=["other"]).items == []
    assert plan(lab, hosts=["gpu1"]).items == []


def test_unavailable_remote_preflight_refuses_candidates(toy: Context) -> None:
    class NoCheck(FakeHost):
        def post_json(self, path: str, body: dict[str, Any]) -> Any:
            if path == "/api/v1/storage/check":
                raise EnvUnreachableError("check unavailable")
            return super().post_json(path, body)

    result = plan(toy, FakeHosts(NoCheck([remote_row("g1", "/scratch/g1.pt")])))
    assert result.items == [] and result.total_bytes == 0
    assert result.refused[0]["reason"].startswith("host check failed:")


def test_remote_items_and_remote_protection(toy: Context) -> None:
    save_hosts(
        toy.layout,
        EnvironmentsFile(
            environments={
                "gpu1": HostSpec(route="url", url="http://127.0.0.1:9", home="/home/hx/.hypothex",
                                 projects={"toy": "/home/hx/toy"}),
            }
        ),
    )  # fmt: skip
    run_dir = "/home/hx/.hypothex/store/toy/runs/g1"
    rows = [
        remote_row("g1", run_dir, kind="run"),
        remote_row("g1", "/scratch/g1.pt"),
        remote_row("g1", f"{run_dir}/predictions/p.jsonl"),
        remote_row("g2", "/home/hx/toy"),
        remote_row("g3", "/scratch/live.pt", archived=False),
        remote_row("g4", "/scratch/live.pt"),
    ]
    result = plan(toy, FakeHosts(FakeHost(rows)))
    assert [(i.host, i.path) for i in result.items] == [("gpu1", "/scratch/g1.pt")]
    reasons = {(r["run_id"], r["reason"]) for r in result.refused}
    assert reasons == {("g1", "protected"), ("g2", "protected"), ("g4", "used by g3")}


@pytest.mark.parametrize("relocate", ["home", "store"])
@pytest.mark.parametrize("name", ["run.yaml", "metrics.jsonl", "scores.jsonl"])
def test_alias_metadata_is_refused_at_plan_and_apply(
    tmp_path: Path,
    toy_repo: Path,
    relocate: str,
    name: str,
) -> None:
    home = tmp_path / "home"
    real = tmp_path / "real"
    real.mkdir()
    if relocate == "home":
        home.symlink_to(real, target_is_directory=True)
    else:
        home.mkdir()
        (home / "store").symlink_to(real, target_is_directory=True)
    ctx = Context.open(home)
    ctx.register_project(toy_repo)
    target = (ctx.layout.store / "toy" / "runs" / "aliased" / name).resolve()
    record = ended_run(ctx, "aliased", artifacts=[("checkpoint", target)])
    if not target.exists():
        target.write_text("metadata\n")
    before = target.read_bytes()
    size, _, mtime = measure_path(target)
    proposed = plan(ctx)
    assert not any(item.path == str(target) for item in proposed.items)
    assert any(
        item["path"] == str(target) and item["reason"] == "protected" for item in proposed.refused
    )
    # A saved or tampered plan cannot bypass the apply-time metadata guard.
    forged = CleanItem(
        project="toy",
        run_id=record.run_id,
        host=LOCAL_HOST,
        environment_id=ctx.descriptor.environment_id,
        kind="artifact",
        artifact_kind="checkpoint",
        path=str(target),
        bytes=size,
        mtime=mtime,
        reason="test",
    )
    result = delete_artifacts(ctx, [forged], actor="test", plan_id="cp-test", older_than_days=30)
    assert result.deleted == [] and result.freed_bytes == 0
    assert result.skipped[0]["reason"] == "protected"
    assert target.read_bytes() == before


def test_apply_frees_exactly_the_planned_bytes(lab: Context) -> None:
    result = plan(lab)
    (item,) = result.items
    record = lab.find_record("old")
    run_yaml = (lab.run_dir(record) / "run.yaml").read_bytes()
    before = lab.events.last_sequence()
    total = result.total_bytes
    done = apply_clean(lab, None, result.plan_id, confirm_bytes=total, actor="human:sv")
    assert done.freed_bytes == total and done.deleted == [item] and done.skipped == []
    assert not Path(item.path).exists()
    assert (lab.run_dir(record) / "run.yaml").read_bytes() == run_yaml
    (cleaned,) = cleaned_artifacts(lab, record)
    assert (cleaned.path, cleaned.bytes, cleaned.actor, cleaned.plan_id) == (
        item.path,
        item.bytes,
        "human:sv",
        result.plan_id,
    )
    assert show_run(lab, "old").cleaned == [cleaned]
    events = {e.type: e for e in lab.events.since(before)}
    assert events["run.artifacts_cleaned"].payload == {
        "paths": [item.path],
        "freed_bytes": item.bytes,
        "plan_id": result.plan_id,
    }
    assert events["storage.cleaned"].payload == {
        "plan_id": result.plan_id,
        "freed_bytes": item.bytes,
        "n_deleted": 1,
        "n_skipped": 0,
    }
    with pytest.raises(CleanRefusedError, match="unknown plan"):
        apply_clean(lab, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")


def test_pulled_copy_records_local_deletion_environment(toy: Context) -> None:
    record = ended_run(toy, "mirror", environment_id="env-host")
    path = write(toy.run_dir(record) / "pulled" / "weights.pt")
    row = next(i for i in local_usage(toy) if i.path == str(path))
    assert row.environment_id == toy.descriptor.environment_id
    proposed = plan(toy)
    (item,) = proposed.items
    assert item.environment_id == toy.descriptor.environment_id
    done = apply_clean(toy, None, proposed.plan_id, confirm_bytes=proposed.total_bytes, actor="x")
    assert done.deleted == [item] and not path.exists()
    (cleaned,) = cleaned_artifacts(toy, record)
    assert cleaned.environment_id == toy.descriptor.environment_id != record.environment_id


def test_wrong_target_environment_cannot_delete_local_path(lab: Context) -> None:
    (item,) = plan(lab).items
    forged = item.model_copy(update={"environment_id": "env-other"})
    result = delete_artifacts(lab, [forged], actor="x", plan_id="cp-test", older_than_days=30)
    assert result.deleted == [] and result.skipped[0]["reason"] == "wrong environment"
    assert Path(item.path).exists()


def test_cleaned_manifest_preserves_distinct_environments_and_legacy(lab: Context) -> None:
    (item,) = plan(lab).items
    record = lab.find_record(item.run_id)
    raw = {
        "path": item.path,
        "bytes": item.bytes,
        "at": utcnow().isoformat(),
        "actor": "old",
        "plan_id": "cp-old",
    }
    legacy = CleanedArtifact.model_validate(raw)
    assert legacy.environment_id is None
    manifest = lab.run_dir(record) / ".hx" / "cleaned.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps([raw]))
    local = item.model_copy(update={"environment_id": lab.descriptor.environment_id})
    remote = item.model_copy(update={"environment_id": "env-host", "host": "gpu1"})
    # Manifest append takes actual completed items; identical spelling is not identity.
    record_cleaned(lab, item.run_id, [local, remote], actor="x", plan_id="cp-test")
    rows = cleaned_artifacts(lab, record)
    assert [r.path for r in rows] == [item.path] * 3
    assert [r.environment_id for r in rows] == [None, lab.descriptor.environment_id, "env-host"]


def test_wrong_confirmation_or_expired_plan_deletes_nothing(lab: Context) -> None:
    result = plan(lab)
    path = Path(result.items[0].path)
    with pytest.raises(CleanRefusedError, match="confirm"):
        apply_clean(lab, None, result.plan_id, confirm_bytes=result.total_bytes - 1, actor="x")
    assert path.exists() and (plans_dir(lab.layout) / f"{result.plan_id}.json").exists()
    with pytest.raises(CleanRefusedError, match="expired"):
        apply_clean(
            lab, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x",
            now=result.expires_at,
        )  # fmt: skip
    assert path.exists()
    with pytest.raises(CleanRefusedError, match="unknown plan"):
        apply_clean(lab, None, "../../etc/passwd", confirm_bytes=0, actor="x")


def test_changed_or_unarchived_items_are_skipped_at_apply(toy: Context, tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    for run_id in ("a", "b", "c", "d"):
        ended_run(toy, run_id, artifacts=[("checkpoint", write(scratch / f"{run_id}.pt"))])
    result = plan(toy)
    assert len(result.items) == 4
    write(scratch / "a.pt", 50_000)  # rewritten by a job after the plan
    toy.update_run("b", "run.archived", lambda r: r.model_copy(update={"archived": False}))
    toy.update_run("c", "run.starred", lambda r: r.model_copy(update={"starred": True}))
    done = apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    reasons = {s["run_id"]: s["reason"] for s in done.skipped}
    assert reasons == {"a": "changed since plan", "b": "not archived", "c": "starred"}
    assert [i.run_id for i in done.deleted] == ["d"] and not (scratch / "d.pt").exists()
    assert all((scratch / f"{r}.pt").exists() for r in "abc")
    assert done.freed_bytes == done.deleted[0].bytes


def test_a_reinfer_child_queued_after_the_plan_keeps_its_input(
    toy: Context, tmp_path: Path
) -> None:
    checkpoint = write(tmp_path / "scratch" / "p.pt")
    ended_run(toy, "parent", artifacts=[("checkpoint", checkpoint)])
    result = plan(toy)
    assert [i.run_id for i in result.items] == ["parent"]
    ended_run(
        toy, "child", archived=False, status=RunStatus.RUNNING, parent="parent",
        vars={"checkpoint": str(checkpoint)},
    )  # fmt: skip
    done = apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    assert done.deleted == [] and checkpoint.exists()
    assert done.skipped == [
        {"path": str(checkpoint), "run_id": "parent", "host": "local", "reason": "used by child"}
    ]


@pytest.mark.parametrize("alias", ["relative", "parent-symlink", "leaf-symlink"])
def test_apply_rechecks_new_readers_through_aliases(
    toy: Context, tmp_path: Path, alias: str
) -> None:
    checkpoint = write(tmp_path / "data" / "p.pt")
    ended_run(toy, "parent", artifacts=[("checkpoint", checkpoint)])
    planned = plan(toy)
    parent = tmp_path / "alias"
    parent.symlink_to(checkpoint.parent, target_is_directory=True)
    leaf = tmp_path / "input.pt"
    leaf.symlink_to(checkpoint)
    value = {
        "relative": "data/p.pt",
        "parent-symlink": str(parent / "p.pt"),
        "leaf-symlink": str(leaf),
    }[alias]
    ended_run(
        toy,
        "reader",
        archived=False,
        status=RunStatus.RUNNING,
        vars={"checkpoint": value},
        cwd=str(tmp_path),
    )
    done = apply_clean(toy, None, planned.plan_id, confirm_bytes=planned.total_bytes, actor="x")
    assert done.deleted == [] and checkpoint.exists()
    assert [row["reason"] for row in done.skipped] == ["used by reader"]


def test_apply_skips_a_folder_that_holds_a_kept_file(toy: Context, tmp_path: Path) -> None:
    models = tmp_path / "scratch" / "models"
    best = write(models / "best.pt")
    ended_run(toy, "old", artifacts=[("checkpoint", models)])
    result = plan(toy)
    assert [i.path for i in result.items] == [str(models)]
    # starred after the plan: a run that records a file inside the planned folder
    ended_run(toy, "kept", starred=True, artifacts=[("checkpoint", best)])
    done = apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    assert done.deleted == [] and best.exists()
    assert [s["reason"] for s in done.skipped] == ["used by kept"]


def test_symlink_artifact_removes_the_link_only(toy: Context, tmp_path: Path) -> None:
    target = write(tmp_path / "keep" / "real.pt")
    link = tmp_path / "scratch" / "link.pt"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    ended_run(toy, "sym", artifacts=[("checkpoint", link)])
    result = plan(toy)
    apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    assert not os.path.lexists(link) and target.exists()


def test_forged_items_are_rechecked(toy: Context, toy_repo: Path) -> None:
    record = ended_run(toy, "r1", artifacts=[("checkpoint", toy_repo)])
    size, _, mtime = measure_path(toy_repo)
    forged = CleanItem(
        project="toy", run_id="r1", host="local", environment_id=record.environment_id,
        kind="artifact", artifact_kind="checkpoint", path=str(toy_repo), bytes=size,
        mtime=mtime, reason="archived 40d",
    )  # fmt: skip
    not_ours = forged.model_copy(update={"path": "/etc/hosts"})
    done = delete_artifacts(
        toy, [forged, not_ours], actor="x", plan_id="cp-00000000", older_than_days=30
    )
    assert done.deleted == [] and toy_repo.is_dir()
    assert {s["reason"] for s in done.skipped} == {"protected", "not an artifact of the run"}


def test_apply_keeps_the_plan_age_for_runs_made_after_it(toy: Context, tmp_path: Path) -> None:
    checkpoint = write(tmp_path / "scratch" / "p.pt")
    ended_run(toy, "parent", artifacts=[("checkpoint", checkpoint)])
    result = plan(toy)  # older_than_days=30
    # an archived child that ended today reads the checkpoint: settled, but not 30 days old
    ended_run(toy, "child", days_ago=0, parent="parent", vars={"checkpoint": str(checkpoint)})
    done = apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    assert done.deleted == [] and checkpoint.exists()
    assert [s["reason"] for s in done.skipped] == ["used by child"]
    young = CleanItem.model_validate({**result.items[0].model_dump(), "run_id": "child"})
    again = delete_artifacts(toy, [young], actor="x", plan_id="cp-00000001", older_than_days=30)
    assert [s["reason"] for s in again.skipped] == ["too recent"]


def test_apply_checks_and_deletes_under_the_cleanup_lock(
    toy: Context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ended_run(toy, "a", artifacts=[("checkpoint", write(tmp_path / "scratch" / "a.pt"))])
    result = plan(toy)
    real_remove = storage_module._remove
    held: list[bool] = []

    def remove(
        ctx: Context, item: CleanItem, users: list[tuple[str, RunRecord]], cutoff: datetime
    ) -> str | None:
        with (toy.layout.home / "storage" / ".lock").open("a") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                held.append(True)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                held.append(False)
        return real_remove(ctx, item, users, cutoff)

    monkeypatch.setattr(storage_module, "_remove", remove)
    apply_clean(toy, None, result.plan_id, confirm_bytes=result.total_bytes, actor="x")
    assert held == [True]


def test_a_run_that_reads_an_input_waits_for_a_cleanup_in_progress(
    toy: Context, toy_repo: Path, tmp_path: Path
) -> None:
    checkpoint = write(tmp_path / "scratch" / "p.pt")
    request = RunRequest(
        repo=toy_repo,
        command=[sys.executable, "-c", "pass"],
        hypothesis="reads p.pt",
        vars={"checkpoint": str(checkpoint)},
    )
    made: list[RunRecord] = []
    worker = threading.Thread(target=lambda: made.append(prepare_run(toy, request)))
    with cleanup_lock(toy.layout):  # an apply is checking and deleting
        worker.start()
        worker.join(2)  # git info and dataset fingerprints take well under a second here
        assert worker.is_alive() and made == []
        assert [r for r in toy.index.list_runs(limit=None) if input_paths(r)] == []
    worker.join(30)
    assert len(made) == 1 and input_paths(made[0]) == [str(checkpoint)]


def test_remote_hosts_delete_their_items(toy: Context, tmp_path: Path) -> None:
    ended_run(toy, "g1", environment_id="env-gpu1")  # the hub's mirror of gpu1's run
    ended_run(toy, "local1", artifacts=[("checkpoint", write(tmp_path / "s" / "l.pt"))])
    gpu1 = FakeHost([remote_row("g1", "/scratch/g1.pt")])
    result = plan(toy, FakeHosts(gpu1))
    assert sorted(i.host for i in result.items) == ["gpu1", "local"]
    done = apply_clean(
        toy, FakeHosts(gpu1), result.plan_id, confirm_bytes=result.total_bytes, actor="human:sv"
    )
    assert sorted(i.run_id for i in done.deleted) == ["g1", "local1"]
    assert gpu1.posted[0]["plan_id"] == result.plan_id and gpu1.posted[0]["actor"] == "human:sv"
    assert gpu1.posted[0]["command_id"] == f"{result.plan_id}:gpu1"
    hub_file = toy.run_dir(toy.find_record("g1")) / ".hx" / "cleaned.json"
    assert [c["path"] for c in json.loads(hub_file.read_text())] == ["/scratch/g1.pt"]
    assert [c["environment_id"] for c in json.loads(hub_file.read_text())] == ["env-gpu1"]


def test_unreachable_host_lands_in_errors(toy: Context, tmp_path: Path) -> None:
    ended_run(toy, "local1", artifacts=[("checkpoint", write(tmp_path / "s" / "l.pt"))])
    rows = [remote_row("g9", "/scratch/g9.pt", host="local")]
    hosts = FakeHosts(FakeHost(rows))
    result = plan(toy, hosts)
    stuck = [i.model_copy(update={"host": "dead"}) for i in result.items if i.host == "gpu1"]
    stored = result.model_copy(update={"items": [*result.items, *stuck]})
    stored = stored.model_copy(update={"total_bytes": sum(i.bytes for i in stored.items)})
    path = plans_dir(toy.layout) / f"{result.plan_id}.json"
    path.write_text(stored.model_dump_json())
    done = apply_clean(toy, hosts, result.plan_id, confirm_bytes=stored.total_bytes, actor="x")
    assert {e["host"] for e in done.errors} == {"dead"}
    assert {i.run_id for i in done.deleted} == {"local1", "g9"}


@pytest.mark.parametrize("name", ["run.yaml", "metrics.jsonl", "scores.jsonl"])
def test_parent_symlink_swap_after_recheck_preserves_metadata(
    toy: Context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    protected_run = ended_run(toy, "protected")
    target = toy.run_dir(protected_run) / name
    if not target.exists():
        target.write_bytes(b"protected metadata\n")
    before = target.read_bytes()
    parent = tmp_path / "scratch"
    candidate = write(parent / name)
    ended_run(toy, "artifact-owner", artifacts=[("checkpoint", candidate)])
    proposed = plan(toy)
    assert [i.path for i in proposed.items] == [str(candidate)]
    original = storage_module._recheck
    calls = 0

    def recheck(
        ctx: Context, item: CleanItem, users: list[tuple[str, RunRecord]], cutoff: datetime
    ) -> str | None:
        nonlocal calls
        why = original(ctx, item, users, cutoff)
        if why is None and calls == 0:
            calls += 1
            parent.rename(tmp_path / "old-scratch")
            parent.symlink_to(target.parent, target_is_directory=True)
        return why

    monkeypatch.setattr(storage_module, "_recheck", recheck)
    done = apply_clean(
        toy, None, proposed.plan_id, confirm_bytes=proposed.total_bytes, actor="test"
    )
    assert calls == 1
    assert target.read_bytes() == before
    assert done.deleted == [] and done.freed_bytes == 0
    assert len(done.skipped) == 1
    assert cleaned_artifacts(toy, toy.find_record("artifact-owner")) == []


@pytest.mark.parametrize(
    "amount,expected",
    [
        (512, "512 B"),
        (4100, "4.1 KB"),
        (412_300_000_000, "412.3 GB"),
        (1_800_000_000_000, "1.8 TB"),
    ],
)
def test_fmt_bytes(amount: int, expected: str) -> None:
    assert storage_module.fmt_bytes(amount) == expected


def test_same_raw_path_deletions_keep_both_environment_identities(toy: Context) -> None:
    record = ended_run(toy, "g1", environment_id="env-gpu1")
    path = write(toy.run_dir(record) / "pulled" / "weights.pt")
    hosts = FakeHosts(FakeHost([remote_row("g1", str(path))]))
    proposed = plan(toy, hosts)
    assert len(proposed.items) == 2
    assert {i.environment_id for i in proposed.items} == {toy.descriptor.environment_id, "env-gpu1"}
    done = apply_clean(toy, hosts, proposed.plan_id, confirm_bytes=proposed.total_bytes, actor="x")
    assert len(done.deleted) == 2
    markers = cleaned_artifacts(toy, record)
    assert [m.path for m in markers] == [str(path), str(path)]
    assert [m.environment_id for m in markers] == [toy.descriptor.environment_id, "env-gpu1"]
    expected_keys = {"path", "environment_id", "bytes", "at", "actor", "plan_id"}
    assert all(set(m.model_dump()) == expected_keys for m in markers)


def test_owner_check_is_read_only_and_rechecks_age_and_identity(lab: Context) -> None:
    (item,) = plan(lab).items
    assert storage_module.check_artifacts(lab, [item], older_than_days=30) == []
    wrong = item.model_copy(update={"environment_id": "wrong"})
    refused = storage_module.check_artifacts(lab, [wrong], older_than_days=30)
    assert refused[0]["reason"] == "wrong environment"
    assert Path(item.path).exists() and cleaned_artifacts(lab, lab.find_record(item.run_id)) == []
