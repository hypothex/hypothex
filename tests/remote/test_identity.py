"""Host identity reservations use fake descriptors and temporary homes only."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from sqlalchemy import text

import hypothex.remote.hub as hub_module
from hypothex.api.app import HubManager
from hypothex.core.context import Context
from hypothex.core.environment import EnvironmentDescriptor
from hypothex.core.index import rebuild_index
from hypothex.remote.config import EnvironmentsFile, HostSpec, save_hosts
from hypothex.remote.hub import Hub, _Supervisor, mirror_run, mirror_source
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


def test_removed_cursor_alias_does_not_hide_current_owner(identity_context: Context) -> None:
    ctx = identity_context
    ctx.index.set_cursor("a", ENVIRONMENT, 7)
    ctx.index.set_cursor("b", ENVIRONMENT, 0)
    save_hosts(ctx.layout, hosts("b"))
    assert HubManager(ctx).host_for_environment(ENVIRONMENT) == "b"


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
