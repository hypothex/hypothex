"""Wheel-only assertions; copied outside the checkout and executed with Python -I.

Only stdlib imports occur at module import time. Product imports inside operations
must resolve from the installed environment; maintainer generators additionally
use ``snapshot`` under their pinned historical interpreters to freeze oracles.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

FIXED_NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def snapshot(ctx: Any, schema: int) -> dict[str, Any]:
    """Read complete persisted evidence and deterministic workspace responses.

    Parameters
    ----------
    ctx : Context
        Open context from the interpreter being checked.
    schema : int
        Original fixture schema; schema 4 additionally exercises UI-v5 contracts.

    Returns
    -------
    dict
        JSON-compatible observations from public queries and file-backed records.
    """
    from hypothex.core import queries as q

    records = sorted(ctx.store.iter_records(), key=lambda record: record.run_id)
    result: dict[str, Any] = {
        "projects": [entry.model_dump(mode="json") for entry in q.list_projects(ctx)],
        "records": {r.run_id: r.model_dump(mode="json") for r in records},
        "scores": {
            r.run_id: [
                score.model_dump(mode="json")
                for score in ctx.store.read_scores(r.project, r.run_id)
            ]
            for r in records
        },
        "tasks": [task.model_dump(mode="json") for task in q.list_tasks(ctx)],
        "comparison": q.compare_examples(ctx, "a", "b", "accuracy", require_bound=True).model_dump(
            mode="json"
        ),
        "history": [point.model_dump(mode="json") for point in q.metric_history(ctx, "a")],
    }
    if schema == 4:
        from hypothex.core import overview
        from hypothex.core.panels import query_panel
        from hypothex.core.taskruns import task_runs
        from hypothex.core.views import PanelSpec, validate_view_text, view_context

        tasks = [name for entry in q.list_projects(ctx) for name in entry.config.tasks]
        result["workspace"] = {
            name: task_runs(ctx, name, "toy").model_dump(mode="json") for name in tasks
        }
        with (
            patch.object(overview, "utcnow", return_value=FIXED_NOW),
            patch.object(overview, "today_start", return_value=FIXED_NOW.replace(hour=0)),
        ):
            result["home"] = overview.build_overview(
                ctx, since=FIXED_NOW.replace(day=1)
            ).model_dump(mode="json")
        result["search"] = {}
        for search in ("%", "_", "wide %_", "a", "parent", "missing"):
            rows = ctx.index.list_runs(search=search, limit=2)
            after = (rows[-1].created_at, rows[-1].run_id) if rows else None
            result["search"][search] = {
                "count": ctx.index.count_runs(search=search),
                "first": [r.run_id for r in rows],
                "next": [
                    r.run_id for r in ctx.index.list_runs(search=search, limit=2, before=after)
                ]
                if after
                else [],
            }
        result["boards"] = {}
        for task, primary in (
            ("direction", "up"),
            ("direction", "down"),
            ("bench", "latency/p95"),
            ("matrix", None),
        ):
            result["boards"][f"{task}:{primary}"] = q.get_leaderboard(
                ctx, task, "toy", primary=primary
            ).model_dump(mode="json")
        entry = ctx.store.load_project("toy")
        saved = Path(entry.repo) / ".hypothex/views/matrix/package.yaml"
        text = saved.read_text()
        known_metrics, known_fields = view_context(ctx, "toy", "matrix")
        view, issues = validate_view_text(text, known_metrics, known_fields)
        assert view is not None and not issues
        result["view"] = {
            "text": text,
            "issues": [item.model_dump(mode="json") for item in issues],
            "spec": view.model_dump(mode="json"),
            "panels": [
                query_panel(ctx, "toy", "matrix", panel).model_dump(mode="json")
                for panel in view.panels
            ],
        }
        invalid = text.replace("render: bars", "render: chart")
        _, issues = validate_view_text(invalid, known_metrics, known_fields)
        assert issues
        result["view"]["invalid_issues"] = [list(item) for item in issues]
        result["curves"] = query_panel(
            ctx,
            "toy",
            "toy-acc",
            PanelSpec.model_validate(
                {"type": "curves", "data": {"metrics": ["loss"], "pick": "all"}}
            ),
        ).model_dump(mode="json")
    return json.loads(json.dumps(result))


def validate_assets(ui: Path) -> list[str]:
    """Validate every local HTML asset without falling back to source files.

    Parameters
    ----------
    ui : Path
        Installed or synthetic UI directory.

    Returns
    -------
    list of str
        Local asset URL paths, including at least one JavaScript and CSS file.

    Raises
    ------
    AssertionError
        An entrypoint, referenced asset, or production resource is missing.
    """
    import re
    from urllib.parse import urlsplit

    entry = ui / "index.html"
    assert entry.is_file(), "packaged UI is missing index.html"
    html = entry.read_text()
    assert "@vite/client" not in html and "localhost:5173" not in html
    urls = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', html)
    assets = []
    for url in urls:
        parsed = urlsplit(url)
        assert not parsed.scheme and not parsed.netloc, "packaged asset points outside the wheel"
        path = parsed.path.lstrip("/")
        if not path or path.startswith("#"):
            continue
        candidate = (ui / path).resolve()
        assert candidate.is_relative_to(ui.resolve()), "asset path escapes installed UI"
        assert candidate.is_file(), f"packaged asset is missing: {path}"
        assets.append("/" + path)
    assert any(path.endswith(".js") for path in assets), "packaged UI has no JavaScript"
    assert any(path.endswith(".css") for path in assets), "packaged UI has no CSS"
    return assets


def _provenance(checkout: Path) -> dict[str, Any]:
    """Require product imports inside this isolated interpreter's site-packages."""
    import os
    import sys
    import sysconfig

    import hypothex

    package = Path(hypothex.__file__).resolve()
    purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
    assert package.is_relative_to(purelib)
    assert not package.is_relative_to(checkout.resolve())
    assert "PYTHONPATH" not in os.environ
    assert not any(name.startswith("PG") for name in os.environ)
    assert sys.flags.isolated == 1
    return {"module": str(package), "purelib": str(purelib), "sys_path": sys.path}


def _resources(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute installed migration files and require complete static/dependency resources."""
    from importlib import metadata, resources, util

    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text

    from hypothex.core.index import HEAD_REVISION, SCHEMA_VERSION, Base
    from hypothex.core.migrations import alembic_config

    result = _provenance(Path(payload["checkout"]))
    root = resources.files("hypothex")
    ui = Path(str(root.joinpath("ui_dist")))
    result["assets"] = validate_assets(ui)
    for name in ("__init__.py", "env.py", "script.py.mako", "versions/0001_phase3.py"):
        assert root.joinpath("core/migrations", name).is_file(), name
    for name in ("pytest", "aiosmtpd", "trustme", "sklearn", "sphinx"):
        assert util.find_spec(name) is None, name
    for dependency in metadata.requires("hypothex") or []:
        assert not any(
            dependency.lower().startswith(name) and "extra ==" not in dependency
            for name in ("pytest", "aiosmtpd", "trustme", "sphinx")
        )
    scratch = Path(payload["scratch"])
    scratch.mkdir(parents=True, exist_ok=True)
    config = alembic_config(f"sqlite:///{scratch / 'migration-check.db'}", None)
    assert ScriptDirectory.from_config(config).get_current_head() == HEAD_REVISION == "0001_phase3"
    command.upgrade(config, "head")
    engine = create_engine(config.attributes["url"])
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == HEAD_REVISION
        )
        assert (
            connection.execute(text("SELECT value FROM meta WHERE key='schema_version'")).scalar()
            == str(SCHEMA_VERSION)
            == "5"
        )
        assert (
            compare_metadata(
                MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata
            )
            == []
        )
        assert {"name", "owner", "parent"} <= set(Base.metadata.tables["runs"].columns.keys())
        assert {"ix_runs_name", "ix_runs_owner", "ix_runs_parent"} <= {
            index.name for index in Base.metadata.tables["runs"].indexes
        }
    engine.dispose()
    result.update(
        migration_head=HEAD_REVISION, schema=SCHEMA_VERSION, requires=metadata.requires("hypothex")
    )
    return result


def _equal_old(expected: Any, actual: Any, path: str = "", *, schema: int) -> None:
    """Compare every frozen field, allowing only documented Phase 3 additions."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        additions = {"owner", "baselines", "cleaned"}
        if schema == 3:
            additions |= {"name", "config_format", "n_finished"}
        assert set(actual) - set(expected) <= additions, (path, sorted(set(actual) - set(expected)))
        for key, value in expected.items():
            assert key in actual, (path, key)
            _equal_old(value, actual[key], path + "/" + key, schema=schema)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(expected) == len(actual), path
        for i, (before, after) in enumerate(zip(expected, actual, strict=True)):
            _equal_old(before, after, path + f"/{i}", schema=schema)
    else:
        assert actual == expected, (path, expected, actual)


def _preserve(payload: dict[str, Any]) -> dict[str, Any]:
    """Compare installed upgrade/restart/reindex state against the historical oracle."""
    import hashlib
    import sqlite3

    from hypothex.core.context import Context

    home = Path(payload["home"])
    schema = payload["schema"]
    expected = payload["expected"]
    ctx = Context.open(home)
    actual = snapshot(ctx, schema)
    for key, value in actual.items():
        if schema == 3 and key == "projects":
            # Schema 3 predates direction tri-state/config_format=2; identity/config
            # source bytes are preserved, while the historical default migrates.
            assert [entry["project"] for entry in value] == [
                entry["project"] for entry in expected[key]
            ]
            assert [entry["repo"] for entry in value] == [entry["repo"] for entry in expected[key]]
        else:
            _equal_old(expected[key], value, key, schema=schema)
    assert all(record.get("owner") is None for record in actual["records"].values())
    assert all(score["per_example_hash"] is None for score in actual["scores"]["legacy"])
    raw_hashes = {}
    for relative, digest in payload["post_relocation_hashes"].items():
        if relative.endswith("run.yaml") or relative in payload["protected_bytes"]:
            data = (Path(payload["fixture_root"]) / relative).read_bytes()
            got = hashlib.sha256(data).hexdigest()
            assert got == digest, relative
            raw_hashes[relative] = got
    with sqlite3.connect(home / "index.db") as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == ("5",)
        assert not list(home.glob("index.db.corrupt*"))
        columns = [row[1] for row in db.execute("PRAGMA table_info(runs)")]
        indexes = [row[1] for row in db.execute("PRAGMA index_list(runs)")]
        assert {"name", "owner", "parent"} <= set(columns)
        assert {"ix_runs_name", "ix_runs_owner", "ix_runs_parent"} <= set(indexes)
        assert db.execute("SELECT count(*) FROM runs WHERE owner IS NOT NULL").fetchone() == (0,)
        state = expected["index_state"]
        cursors = [list(row) for row in db.execute("SELECT * FROM host_cursors ORDER BY 1")]
        assert cursors == state["carried"]["host_cursors"]
        changes = dict(db.execute("SELECT run_id,generation FROM run_changes"))
        assert all(
            changes[rid] >= generation for rid, generation in state["carried"]["run_changes"]
        )
        generation = int(db.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0])
        assert generation >= state["generation"]
        assert db.execute("SELECT count(*) FROM scores_stale").fetchone() == (0,)
        assert db.execute(
            "SELECT count(*) FROM metric_points_pending WHERE run_id='a'"
        ).fetchone() == (0,)
    assert [
        score.model_dump(mode="json") for score in ctx.index.scores_for(["legacy"])["legacy"]
    ] == expected["scores"]["legacy"]
    ctx.index.engine.dispose()
    return {
        "schema": 5,
        "source_schema": schema,
        "raw_hashes": raw_hashes,
        "comparison": actual["comparison"],
        "records": sorted(actual["records"]),
        "cursors": cursors,
        "generation": generation,
        "stale_repaired": True,
        "deferred_history": actual["history"],
    }


def _enable_auth(payload: dict[str, Any]) -> dict[str, Any]:
    """Enable scoped auth without replacing any other configured settings."""
    from hypothex.core.layout import Layout
    from hypothex.core.settings import load_settings, save_settings

    layout = Layout(Path(payload["home"]))
    settings = load_settings(layout)
    settings.server.auth = "on"
    save_settings(layout, settings)
    assert load_settings(layout) == settings
    return {"auth": "on"}


def _mcp(payload: dict[str, Any]) -> dict[str, Any]:
    """Exercise actual installed MCP transport with the caller's own scoped credential."""
    import asyncio
    import ipaddress
    from urllib.parse import urlsplit

    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import TextContent

    parsed = urlsplit(payload["url"])
    assert parsed.hostname and ipaddress.ip_address(parsed.hostname).is_loopback

    async def call() -> dict[str, Any]:
        async with (
            httpx2.AsyncClient(
                headers={"Authorization": "Bearer " + payload["token"]}, trust_env=False, timeout=20
            ) as http,
            Client(
                streamable_http_client(payload["url"] + "/mcp", http_client=http),
                read_timeout_seconds=20,
            ) as client,
        ):
            result = await client.call_tool(payload["tool"], payload.get("arguments", {}))
            assert result.is_error == payload.get("expect_error", False)
            content = result.structured_content
            if content is None:
                block = result.content[0]
                assert isinstance(block, TextContent)
                text = block.text
                if result.is_error:
                    return {"error": True}
                content = json.loads(text)
            return {"error": result.is_error, "result": content}

    return asyncio.run(call())


def _seed_sweep(payload: dict[str, Any]) -> dict[str, Any]:
    """Add one local finished synthetic sweep for installed redirect coverage."""
    from datetime import datetime

    from hypothex.core.context import Context
    from hypothex.core.records import RunRecord, RunStatus
    from hypothex.core.sweeps import SweepParam, SweepSpec, save_sweep, sweep_tag

    ctx = Context.open(Path(payload["home"]))
    project, task = payload["mapping"].split("/")
    sweep_id = "package-smoke"
    now = datetime(2026, 10, 6, 12, tzinfo=UTC)
    save_sweep(
        ctx.layout,
        SweepSpec(
            id=sweep_id,
            project=project,
            task=task,
            host=None,
            grid=[SweepParam(name="package_smoke", values=["1"])],
            seeds=[1],
            command_template=["true"],
            created_by="package-fixture",
            created_at=now,
        ),
    )
    ctx.create_run(
        RunRecord(
            run_id="package-sweep-run",
            project=project,
            task=task,
            command=["true"],
            command_template=["true"],
            cwd=ctx.store.load_project(project).repo,
            environment_id=ctx.descriptor.environment_id,
            host=ctx.descriptor.label,
            config_hash="sha256:package-smoke",
            status=RunStatus.FINISHED,
            created_at=now,
            started_at=now,
            ended_at=now,
            created_by="package-fixture",
            seed=1,
            params={"package_smoke": "1"},
            sweep_id=sweep_id,
            tags=[sweep_tag(ctx.descriptor.environment_id, sweep_id)],
        )
    )
    ctx.index.engine.dispose()
    return {"project": project, "sweep": sweep_id, "run_id": "package-sweep-run"}


def main() -> None:
    """Run one private installed assertion request and print only its structured result."""
    import sys

    payload = json.loads(Path(sys.argv[1]).read_text())
    _provenance(Path(payload["checkout"]))
    operations = {
        "resources": _resources,
        "preserve": _preserve,
        "enable-auth": _enable_auth,
        "mcp": _mcp,
        "seed-sweep": _seed_sweep,
    }
    result = operations[payload["operation"]](payload)
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
