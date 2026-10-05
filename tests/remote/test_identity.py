"""Host identity reservations use fake descriptors and temporary homes only."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

import hypothex.remote.hub as hub_module
from hypothex.api.app import HubManager
from hypothex.core.context import Context
from hypothex.core.environment import EnvironmentDescriptor
from hypothex.core.index import rebuild_index
from hypothex.core.queries import show_run
from hypothex.core.records import Artifact, DatasetRef
from hypothex.remote.client import EnvRequestError
from hypothex.remote.config import EnvironmentsFile, HostSpec, save_hosts
from hypothex.remote.hub import CLAIMS_DIR, Hub, _Supervisor, mirror_run, mirror_source
from tests.remote.test_hub import FakeClient, seed_run, until

ENVIRONMENT = "shared-environment"


def hosts(*names: str) -> EnvironmentsFile:
    """Return URL hosts whose clients are replaced by the fixture."""
    return EnvironmentsFile(
        environments={name: HostSpec(route="url", url=f"http://{name}.invalid") for name in names}
    )


@pytest.fixture
def identity_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Context:
    """Replace every remote operation with an idle fake connection."""
    ctx = Context.open(tmp_path / "hub")
    descriptor = ctx.descriptor.model_copy(update={"environment_id": ENVIRONMENT})

    class IdentityClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def descriptor(self) -> EnvironmentDescriptor:
            return descriptor

        def close(self) -> None:
            pass

    async def idle(*args: object) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(hub_module, "EnvClient", IdentityClient)
    monkeypatch.setattr(Hub, "_consume", idle)
    monkeypatch.setattr(Hub, "_watch", idle)
    return ctx


def test_identity_is_reserved_before_cursor_io(
    identity_context: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    hub = Hub(identity_context, hosts("a"))
    read_cursor = hub._read_cursor

    def pause(sup: _Supervisor, environment_id: str) -> int:
        if sup.name == "a":
            entered.set()
            assert release.wait(5)
        return read_cursor(sup, environment_id)

    monkeypatch.setattr(hub, "_read_cursor", pause)

    async def main() -> None:
        await hub.start()
        try:
            await until(entered.is_set, timeout=3)
            await hub.add_host("b", hosts("b").environments["b"])
            await until(lambda: hub.state("b").state in {"connected", "error"}, timeout=3)
            assert hub.state("b").state == "error"
            assert "host a" in hub.state("b").message
        finally:
            release.set()
            await hub.stop()

    asyncio.run(main())


@pytest.mark.parametrize("maintenance", ["restart", "reset", "rebuild"])
def test_known_environment_stays_reserved_for_an_offline_configured_host(
    identity_context: Context, maintenance: str
) -> None:
    ctx = identity_context
    ctx.index.set_cursor("a", ENVIRONMENT, 0)
    if maintenance == "reset":
        ctx.index.reset_cursor("a", ENVIRONMENT)
    elif maintenance == "rebuild":
        rebuild_index(ctx.index, ctx.store)
    hub = Hub(Context.open(ctx.layout.home), hosts("a", "b"))

    async def main() -> None:
        # The old owner's supervisor stays offline while only b tries to connect.
        await hub.connect("b")
        try:
            await until(lambda: hub.state("b").state in {"connected", "error"}, timeout=3)
            assert hub.state("b").state == "error"
            assert "host a" in hub.state("b").message
        finally:
            await hub.stop()

    asyncio.run(main())


def test_cursor_reset_preserves_zero_sequence_identity(identity_context: Context) -> None:
    ctx = identity_context
    ctx.index.set_cursor("a", ENVIRONMENT, 7)
    generation = ctx.index.generation()
    ctx.index.reset_cursor("a", ENVIRONMENT)
    with ctx.index.engine.connect() as conn:
        rows = conn.execute(text("SELECT host, environment_id, last_sequence FROM host_cursors"))
        assert list(rows) == [("a", ENVIRONMENT, 0)]
    assert ctx.index.generation() == generation


def test_cursor_hosts_includes_zero_sequence_reservations(identity_context: Context) -> None:
    index = identity_context.index
    index.set_cursor("b", ENVIRONMENT, 0)
    index.set_cursor("a", ENVIRONMENT, 2)
    index.set_cursor("c", "another-environment", 3)
    assert index.cursor_hosts(ENVIRONMENT) == ["a", "b"]
    assert index.cursor_hosts("missing") == []


@pytest.mark.parametrize("seen", [False, True])
def test_removed_cursor_alias_does_not_hide_current_owner(
    identity_context: Context, seen: bool
) -> None:
    ctx = identity_context
    ctx.index.set_cursor("a", ENVIRONMENT, 7)
    ctx.index.set_cursor("b", ENVIRONMENT, 0)
    save_hosts(ctx.layout, hosts("b"))
    manager = HubManager(ctx)
    if seen:
        manager._seen[ENVIRONMENT] = "a"
    assert manager.host_for_environment(ENVIRONMENT) == "b"
    assert manager.mirrored_from(ENVIRONMENT) == "b"


def test_legacy_claim_only_owner_is_preserved(identity_context: Context, tmp_path: Path) -> None:
    ctx, remote = identity_context, Context.open(tmp_path / "remote")
    seed_run(remote, "r1")
    assert mirror_run(ctx, FakeClient(remote), "a", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
    hub = Hub(Context.open(ctx.layout.home), hosts("a", "b"))

    async def main() -> None:
        await hub.connect("b")
        try:
            await until(lambda: hub.state("b").state in {"connected", "error"}, timeout=3)
            assert hub.state("b").state == "error"
        finally:
            await hub.stop()

    asyncio.run(main())
    assert mirror_source(ctx, ctx.find_record("r1")) == "host:a"


def test_a_different_host_cannot_overwrite_a_mirrored_claim(
    identity_context: Context, tmp_path: Path
) -> None:
    ctx = identity_context
    a, b = Context.open(tmp_path / "a"), Context.open(tmp_path / "b")
    seed_run(a, "r1", value=0.1)
    seed_run(b, "r1", value=0.9)
    assert mirror_run(ctx, FakeClient(a), "a", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
    assert mirror_run(ctx, FakeClient(b), "b", ENVIRONMENT, "toy", "r1") is None  # type: ignore[arg-type]
    assert ctx.store.read_scores("toy", "r1")[0].value == 0.1
    assert mirror_source(ctx, ctx.find_record("r1")) == "host:a"


def test_removing_the_old_host_allows_an_explicit_alias_transfer(
    identity_context: Context, tmp_path: Path
) -> None:
    ctx, remote = identity_context, Context.open(tmp_path / "remote")
    seed_run(remote, "r1", value=0.1)
    assert mirror_run(ctx, FakeClient(remote), "a", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
    ctx.index.set_cursor("a", ENVIRONMENT, 7)
    hub = Hub(ctx, hosts("a"))

    async def main() -> None:
        await hub.remove_host("a")
        await hub.add_host("b", hosts("b").environments["b"])
        await hub.connect("b")
        try:
            await until(lambda: hub.state("b").state in {"connected", "error"}, timeout=3)
            assert hub.state("b").state == "connected"
            assert mirror_source(ctx, ctx.find_record("r1")) == "host:b"
            assert mirror_run(ctx, FakeClient(remote), "b", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
        finally:
            await hub.stop()

    asyncio.run(main())


@pytest.mark.parametrize("paths_available", [True, False])
def test_alias_transfer_refreshes_cached_paths_from_the_verified_owner(
    identity_context: Context, tmp_path: Path, toy_repo: Path, paths_available: bool
) -> None:
    ctx, remote = identity_context, Context.open(tmp_path / "remote")
    remote.register_project(toy_repo)
    original = seed_run(remote, "r1").model_copy(
        update={
            "artifacts": [Artifact(kind="checkpoint", path="/remote/model.pt")],
            "datasets": [DatasetRef(name="data", version="1", path="/remote/data.jsonl")],
        }
    )
    remote.store.write_record(original)
    client = FakeClient(remote)
    assert mirror_run(ctx, client, "old", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
    cache = ctx.run_dir(ctx.find_record("r1")) / hub_module.HOST_PATHS_FILE
    assert json.loads(cache.read_text())["host"] == "old"
    ctx.index.set_cursor("old", ENVIRONMENT, 7)
    hub = Hub(ctx, hosts("old"))

    class NewOwnerClient(FakeClient):
        def get_json(self, path: str, **params: Any) -> Any:
            if path == "/api/v1/runs/r1" and not paths_available:
                raise EnvRequestError("paths unavailable", status_code=503)
            return super().get_json(path, **params)

    async def main() -> None:
        await hub.remove_host("old")
        await hub.add_host("new", hosts("new").environments["new"])
        await hub.connect("new")
        try:
            await until(lambda: hub.state("new").state in {"connected", "error"}, timeout=3)
            assert hub.state("new").state == "connected"
            assert mirror_run(  # type: ignore[arg-type]
                ctx, NewOwnerClient(remote), "new", ENVIRONMENT, "toy", "r1"
            )
            mirrored = ctx.find_record("r1")
            assert mirror_source(ctx, mirrored) == "host:new"
            assert mirrored.artifacts[0].host == mirrored.datasets[0].host == "new"
            paths = hub_module.host_paths(ctx, mirrored)
            assert paths["cwd"] == f"new:{original.cwd}"
            if paths_available:
                assert json.loads(cache.read_text())["host"] == "new"
                shown = show_run(ctx, "r1").paths
                assert shown["run_dir"] == f"new:{remote.run_dir(original)}"
                assert shown["repo"] == f"new:{toy_repo}"
                assert shown["stdout"].startswith("new:")
            else:
                assert paths == {"cwd": f"new:{original.cwd}"}
                assert mirror_run(ctx, client, "new", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
                assert json.loads(cache.read_text())["host"] == "new"
            assert mirror_run(ctx, client, "old", ENVIRONMENT, "toy", "r1") is None  # type: ignore[arg-type]
            assert mirror_source(ctx, ctx.find_record("r1")) == "host:new"
            assert ctx.index.get_cursor("old", ENVIRONMENT) == 7
        finally:
            await hub.stop()

    asyncio.run(main())


def test_alias_transfer_refreshes_the_proven_projects_snapshot(
    identity_context: Context, tmp_path: Path, toy_repo: Path
) -> None:
    ctx, remote = identity_context, Context.open(tmp_path / "remote")
    entry = remote.register_project(toy_repo)
    seed_run(remote, "r1")
    client = FakeClient(remote)
    assert mirror_run(ctx, client, "old", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
    ctx.index.set_cursor("old", ENVIRONMENT, 7)
    hub = Hub(ctx, hosts("new"))
    hub._reserve_environment(ENVIRONMENT, "new")
    assert ctx.store.load_project("toy").remote_host == "new"
    assert ctx.index.get_project("toy") == ctx.store.load_project("toy")
    for description in ("new snapshot", "next snapshot"):
        changed = entry.model_copy(
            update={
                "repo": "/remote/moved/toy",
                "config": entry.config.model_copy(update={"description": description}),
            }
        )
        remote.store.save_project(changed)
        assert mirror_run(ctx, client, "new", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
        copied = ctx.store.load_project("toy")
        assert copied.remote_host == "new"
        assert copied.repo == "/remote/moved/toy"
        assert copied.config.description == description
        assert ctx.index.get_project("toy") == copied


@pytest.mark.parametrize(
    "missing_proof",
    ["local", "other_environment", "missing_cursor", "missing_claim", "configured", "unreadable"],
)
def test_alias_transfer_preserves_projects_without_exclusive_provenance(
    identity_context: Context, tmp_path: Path, toy_repo: Path, missing_proof: str
) -> None:
    ctx, remote = identity_context, Context.open(tmp_path / "remote")
    remote.register_project(toy_repo)
    seed_run(remote, "r1")
    client = FakeClient(remote)
    assert mirror_run(ctx, client, "old", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
    if missing_proof != "missing_cursor":
        ctx.index.set_cursor("old", ENVIRONMENT, 7)
    if missing_proof == "local":
        ctx.register_project(toy_repo)
    elif missing_proof == "other_environment":
        claim = ctx.layout.store / CLAIMS_DIR / "other.json"
        claim.write_text(json.dumps({"project": "toy", "environment_id": "another", "host": "old"}))
        ctx.index.set_cursor("old", "another", 8)
    elif missing_proof == "missing_claim":
        (ctx.layout.store / CLAIMS_DIR / "r1.json").unlink()
    elif missing_proof == "unreadable":
        (ctx.layout.store / CLAIMS_DIR / "unknown.json").write_text("not readable")
    before = ctx.store.load_project("toy")
    configured = hosts("old", "new") if missing_proof == "configured" else hosts("new")
    hub = Hub(ctx, configured)
    if missing_proof == "configured":
        with pytest.raises(hub_module._EnvironmentTakenError, match="host old"):
            hub._reserve_environment(ENVIRONMENT, "new")
    else:
        hub._reserve_environment(ENVIRONMENT, "new")
        assert mirror_run(ctx, client, "new", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
    assert ctx.store.load_project("toy") == before
    assert ctx.index.get_project("toy") == before


@pytest.mark.parametrize("crash_after", ["project", "index", "claim"])
def test_alias_project_transfer_resumes_after_an_interrupted_write(
    identity_context: Context,
    tmp_path: Path,
    toy_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_after: str,
) -> None:
    ctx, remote = identity_context, Context.open(tmp_path / "remote")
    remote.register_project(toy_repo)
    seed_run(remote, "r1")
    assert mirror_run(ctx, FakeClient(remote), "old", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
    ctx.index.set_cursor("old", ENVIRONMENT, 7)
    hub = Hub(ctx, hosts("new"))
    target, attribute = {
        "project": (ctx.store, "save_project"),
        "index": (ctx.index, "upsert_project"),
        "claim": (hub_module, "atomic_write_text"),
    }[crash_after]
    write = getattr(target, attribute)

    def interrupt(*args: Any, **kwargs: Any) -> None:
        write(*args, **kwargs)
        raise OSError("interrupted project transfer")

    with monkeypatch.context() as failing:
        failing.setattr(target, attribute, interrupt)
        with pytest.raises(OSError, match="interrupted project transfer"):
            hub._reserve_environment(ENVIRONMENT, "new")
    restarted = Hub(Context.open(ctx.layout.home), hosts("new"))
    restarted._reserve_environment(ENVIRONMENT, "new")
    copied = restarted.ctx.store.load_project("toy")
    assert copied.remote_host == "new"
    assert restarted.ctx.index.get_project("toy") == copied
    assert mirror_source(ctx, ctx.find_record("r1")) == "host:new"


def test_alias_transfer_waits_for_the_old_hosts_pending_mirrors(
    identity_context: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = identity_context
    ctx.index.set_cursor("a", ENVIRONMENT, 0)
    configured = {"a", "b"}
    hub = Hub(ctx, hosts("a"), configured_hosts=lambda: configured)
    draining, drained = asyncio.Event(), asyncio.Event()
    halt = hub._halt

    async def pause_halt(sup: _Supervisor) -> None:
        if sup.name == "a":
            draining.set()
            await drained.wait()
        await halt(sup)

    monkeypatch.setattr(hub, "_halt", pause_halt)

    async def main() -> None:
        configured.remove("a")  # a file reload has removed a, whose writes must drain first
        removal = asyncio.create_task(hub.remove_host("a"))
        try:
            await asyncio.wait_for(draining.wait(), 3)
            await hub.add_host("b", hosts("b").environments["b"])
            await hub.connect("b")
            await until(lambda: hub.state("b").state in {"connected", "error"}, timeout=3)
            assert hub.state("b").state == "error"
            drained.set()
            await removal
            await hub.connect("b")
            await until(lambda: hub.state("b").state in {"connected", "error"}, timeout=3)
            assert hub.state("b").state == "connected"
        finally:
            drained.set()
            await removal
            await hub.stop()

    asyncio.run(main())


def test_disabled_configured_host_keeps_ownership_across_manager_reload(
    identity_context: Context,
) -> None:
    ctx = identity_context
    ctx.index.set_cursor("a", ENVIRONMENT, 0)
    save_hosts(ctx.layout, hosts("a", "b"))
    (ctx.layout.home / "hosts_disabled.json").write_text(
        json.dumps({"a": "2026-01-01T00:00:00+00:00"})
    )
    manager = HubManager(ctx)

    async def main() -> None:
        await manager.start()
        try:
            await until(lambda: manager.state("b").state in {"connected", "error"}, timeout=3)
            assert manager.state("a").state == "disabled"
            assert manager.state("b").state == "error"
            await manager.reload()
            await manager.connect("b")
            await until(lambda: manager.state("b").state in {"connected", "error"}, timeout=3)
            assert manager.state("b").state == "error"
            # Removing a from the configured file deliberately frees the identity.
            save_hosts(ctx.layout, hosts("b"))
            await manager.reload()
            await manager.connect("b")
            await until(lambda: manager.state("b").state in {"connected", "error"}, timeout=3)
            assert manager.state("b").state == "connected"
        finally:
            await manager.stop()

    asyncio.run(main())


def legacy_claim(ctx: Context, run_id: str = "r1") -> Path:
    """Write the claim shape used before host provenance was recorded."""
    path = ctx.layout.store / CLAIMS_DIR / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"project": "toy", "environment_id": ENVIRONMENT}))
    return path


def test_upgrade_migrates_hostless_claims_only_for_the_saved_cursor_owner(
    identity_context: Context, tmp_path: Path
) -> None:
    ctx, remote = identity_context, Context.open(tmp_path / "remote")
    seed_run(remote, "r1")
    claim = legacy_claim(ctx)
    ctx.index.set_cursor("a", ENVIRONMENT, 7)
    hub = Hub(ctx, hosts("a", "b"))
    with pytest.raises(hub_module._EnvironmentTakenError, match="host a"):
        hub._reserve_environment(ENVIRONMENT, "b")
    assert "host" not in json.loads(claim.read_text())
    hub._reserve_environment(ENVIRONMENT, "a")
    assert json.loads(claim.read_text())["host"] == "a"
    assert ctx.index.get_cursor("a", ENVIRONMENT) == 7
    assert mirror_run(ctx, FakeClient(remote), "a", ENVIRONMENT, "toy", "r1")  # type: ignore[arg-type]
    assert mirror_source(ctx, ctx.find_record("r1")) == "host:a"
    assert mirror_run(ctx, FakeClient(remote), "b", ENVIRONMENT, "toy", "r1") is None  # type: ignore[arg-type]


@pytest.mark.parametrize("cursor_names", [(), ("a", "b")])
def test_upgrade_refuses_hostless_claims_without_an_unambiguous_cursor_owner(
    identity_context: Context, cursor_names: tuple[str, ...]
) -> None:
    ctx = identity_context
    claim = legacy_claim(ctx)
    before = claim.read_bytes()
    for name in cursor_names:
        ctx.index.set_cursor(name, ENVIRONMENT, 7)
    hub = Hub(ctx, hosts("a", "b"))
    with pytest.raises(hub_module._EnvironmentTakenError, match="legacy.*owner"):
        hub._reserve_environment(ENVIRONMENT, "a")
    assert claim.read_bytes() == before
    assert ctx.index.cursor_hosts(ENVIRONMENT) == list(cursor_names)


def test_upgrade_can_transfer_a_verified_legacy_owner_after_removal(
    identity_context: Context,
) -> None:
    ctx = identity_context
    claim = legacy_claim(ctx)
    ctx.index.set_cursor("old", ENVIRONMENT, 7)
    hub = Hub(ctx, hosts("new"))
    hub._reserve_environment(ENVIRONMENT, "new")
    assert json.loads(claim.read_text())["host"] == "new"
    assert ctx.index.cursor_hosts(ENVIRONMENT) == ["new", "old"]


def test_direct_legacy_mirror_reports_the_needed_owner_migration(
    identity_context: Context, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ctx, remote = identity_context, Context.open(tmp_path / "remote")
    seed_run(remote, "r1")
    legacy_claim(ctx)
    assert mirror_run(ctx, FakeClient(remote), "a", ENVIRONMENT, "toy", "r1") is None  # type: ignore[arg-type]
    assert "legacy claim" in caplog.text and "reconnect" in caplog.text


@pytest.mark.parametrize("crash_after", ["normalize", "cursor", "claim"])
def test_upgrade_alias_transfer_resumes_after_an_interrupted_write(
    identity_context: Context, monkeypatch: pytest.MonkeyPatch, crash_after: str
) -> None:
    ctx = identity_context
    claims = [legacy_claim(ctx, run_id) for run_id in ("r1", "r2")]
    ctx.index.set_cursor("old", ENVIRONMENT, 7)
    hub = Hub(ctx, hosts("new"))
    set_cursor, write_claim = ctx.index.set_cursor, hub_module.atomic_write_text

    def interrupt_cursor(host: str, environment_id: str, sequence: int) -> None:
        set_cursor(host, environment_id, sequence)
        raise OSError("interrupted after durable cursor write")

    def interrupt_claim(path: Path, data: str) -> None:
        write_claim(path, data)
        target = "old" if crash_after == "normalize" else "new"
        if json.loads(data).get("host") == target:
            raise OSError("interrupted after durable claim write")

    with monkeypatch.context() as failing:
        if crash_after == "cursor":
            failing.setattr(ctx.index, "set_cursor", interrupt_cursor)
        else:
            failing.setattr(hub_module, "atomic_write_text", interrupt_claim)
        with pytest.raises(OSError, match="interrupted"):
            hub._reserve_environment(ENVIRONMENT, "new")

    restarted = Hub(Context.open(ctx.layout.home), hosts("new"))
    restarted._reserve_environment(ENVIRONMENT, "new")
    assert all(json.loads(path.read_text())["host"] == "new" for path in claims)
    assert restarted.ctx.index.get_cursor("old", ENVIRONMENT) == 7
    assert restarted.ctx.index.cursor_hosts(ENVIRONMENT) == ["new", "old"]
