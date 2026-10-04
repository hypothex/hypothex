import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.types import TextContent

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.errors import RemoteProjectError, RunError, StoreError
from hypothex.core.evaluation import evaluate_run
from hypothex.mcp.server import (
    MCPServer,
    build_server,
    list_task_views,
    put_view,
    query_task_view,
    remove_view,
    require_agent_hypothesis,
    view_document,
)
from tests.factories import PREDS_075, seed_finished_run

EXPECTED_TOOLS = {
    "list_projects",
    "list_tasks",
    "get_task",
    "get_leaderboard",
    "list_runs",
    "get_run",
    "compare_runs",
    "launch_run",
    "rerun",
    "reinfer",
    "reevaluate",
    "stop_run",
    "add_note",
    "tag_run",
    "get_predictions",
    "list_views",
    "get_view",
    "add_view",
    "query_view",
    "list_hosts",
    "launch_sweep",
    "get_sweep",
    "cancel_sweep",
    "extend_sweep",
    "pull_artifact",
}

GOOD_VIEW = """\
title: acc only
panels:
  - type: leaderboard
    title: board
    data: {metrics: [accuracy]}
"""
# "acuracy" is one letter off; difflib.get_close_matches("acuracy", ["accuracy"]) ->
# ["accuracy"]. The bad name sits on line 5 (1-based) of the text.
BAD_VIEW = GOOD_VIEW.replace("[accuracy]", "[acuracy]")


def call(
    home: Path,
    name: str,
    args: dict[str, Any] | None = None,
    *,
    server: MCPServer | None = None,
) -> tuple[bool, Any]:
    server = server or build_server(home)

    async def go() -> tuple[bool, Any]:
        async with Client(server) as client:
            result = await client.call_tool(name, args or {})
            block = result.content[0]
            assert isinstance(block, TextContent)
            if result.is_error:
                return True, block.text
            if result.structured_content is not None:
                return False, result.structured_content
            return False, json.loads(block.text)

    return asyncio.run(go())


def test_all_tools_are_listed(home: Path) -> None:
    server = build_server(home)

    async def go() -> set[str]:
        async with Client(server) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert asyncio.run(go()) == EXPECTED_TOOLS


def test_read_tools(home: Path, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    err, projects = call(home, "list_projects")
    assert not err and projects["projects"][0]["project"] == "toy"
    err, board = call(home, "get_leaderboard", {"task": "toy-acc"})
    assert not err and board["rows"][0]["run_ids"] == ["r1"]
    err, run = call(home, "get_run", {"run_id": "r1"})
    assert not err and run["paths"]["repo"] == str(toy_repo.resolve())


def test_launch_requires_hypothesis(home: Path, toy_repo: Path) -> None:
    err, message = call(
        home, "launch_run", {"repo": str(toy_repo), "hypothesis": " ", "command": ["true"]}
    )
    assert err and "hypothesis" in message


def test_require_agent_hypothesis() -> None:
    require_agent_hypothesis("human", "")  # people may launch without one
    require_agent_hypothesis("api", " ")
    require_agent_hypothesis("agent:claude", "bigger lr helps")
    for hypothesis in ("", "  \n"):
        with pytest.raises(RunError, match="hypothesis"):
            require_agent_hypothesis("agent:claude", hypothesis)


def test_build_server_uses_a_given_context(home: Path, tmp_path: Path, toy_repo: Path) -> None:
    # $HYPOTHEX_HOME (``home``) is empty; the given Context is another home
    other = Context.open(tmp_path / "other")
    seed_finished_run(other, toy_repo, "r1", predictions=PREDS_075)
    server = build_server(context=other)

    async def go() -> Any:
        async with Client(server) as client:
            return await client.call_tool("list_runs", {})

    result = asyncio.run(go())
    assert not result.is_error
    assert [r["run_id"] for r in result.structured_content["runs"]] == ["r1"]


def test_reevaluate_note_and_tag(home: Path, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    err, report = call(home, "reevaluate", {"run_id": "r1"})
    assert not err and report["evaluated"] == ["r1"]
    assert call(home, "add_note", {"run_id": "r1", "text": "fine"}) == (False, {"ok": True})
    err, tagged = call(home, "tag_run", {"run_id": "r1", "add": ["mcp"]})
    assert tagged["run"]["tags"] == ["mcp"]


def test_mcp_is_served_over_http(home: Path) -> None:
    app = create_app(home, background_repair=False)
    with TestClient(app, base_url="http://127.0.0.1:7777") as client:
        resp = client.post(
            "/mcp/",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        assert resp.status_code == 200
        assert "hypothex" in resp.text


def test_view_tools(home: Path, ctx: Context, toy_repo: Path) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    path = toy_repo.resolve() / ".hypothex" / "views" / "toy-acc" / "acc.yaml"

    err, listed = call(home, "list_views", {"task": "toy-acc"})
    assert not err
    assert [(v["name"], v["origin"]) for v in listed["views"]] == [("overview", "preset")]

    err, bad = call(home, "add_view", {"task": "toy-acc", "name": "acc", "yaml_text": BAD_VIEW})
    assert not err and bad["ok"] is False
    assert (bad["issues"][0]["line"], bad["issues"][0]["suggestion"]) == (5, "accuracy")
    assert not path.exists()

    err, good = call(home, "add_view", {"task": "toy-acc", "name": "acc", "yaml_text": GOOD_VIEW})
    assert not err and good["ok"] is True
    assert (good["info"]["name"], good["info"]["path"]) == ("acc", str(path))
    assert path.read_text() == GOOD_VIEW

    err, doc = call(home, "get_view", {"task": "toy-acc", "name": "acc"})
    assert not err and doc["text"] == GOOD_VIEW and doc["view"]["title"] == "acc only"
    assert "from_" not in doc["view"]

    err, result = call(home, "query_view", {"task": "toy-acc", "name": "acc"})
    assert not err
    assert [p["type"] for p in result["panels"]] == ["leaderboard"]
    assert [r["run_ids"] for r in result["panels"][0]["rows"]] == [["r1"]]

    err, message = call(home, "get_view", {"task": "toy-acc", "name": "nope"})
    assert err and "unknown view 'nope'" in message
    err, message = call(
        home, "add_view", {"task": "toy-acc", "name": "overview", "yaml_text": GOOD_VIEW}
    )
    assert err and "preset view" in message


def test_views_are_never_written_under_a_host_copys_repo_path(ctx: Context, toy_repo: Path) -> None:
    # the repo path of a project copied from a host is the host's, even when it is a
    # folder here: a view is never saved into it or deleted from it
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    put_view(ctx, "toy-acc", "kept", GOOD_VIEW)
    kept = toy_repo.resolve() / ".hypothex" / "views" / "toy-acc" / "kept.yaml"
    entry = ctx.store.load_project("toy").model_copy(update={"remote_host": "gpu1"})
    ctx.store.save_project(entry)
    ctx.index.upsert_project(entry)
    with pytest.raises(RemoteProjectError, match="copied from host gpu1"):
        put_view(ctx, "toy-acc", "acc", GOOD_VIEW)
    assert not kept.with_name("acc.yaml").exists()
    with pytest.raises(RemoteProjectError, match="copied from host gpu1"):
        remove_view(ctx, "toy-acc", "kept")
    assert kept.read_text() == GOOD_VIEW


def test_views_are_never_read_from_a_host_copys_repo_path(ctx: Context, toy_repo: Path) -> None:
    # the view files and hypothex.yaml under a host copy's repo path are the host's, even
    # when the path is a folder here: only the snapshot's preset and inline views are served
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    put_view(ctx, "toy-acc", "kept", GOOD_VIEW)
    entry = ctx.store.load_project("toy").model_copy(update={"remote_host": "gpu1"})
    ctx.store.save_project(entry)
    ctx.index.upsert_project(entry)
    (toy_repo / "hypothex.yaml").write_text("project: [not, valid\n")  # never parsed
    views = [(v.name, v.origin) for v in list_task_views(ctx, "toy-acc")]
    assert views == [("overview", "preset")]
    with pytest.raises(StoreError, match="unknown view 'kept'"):
        view_document(ctx, "toy-acc", "kept")
    panels = query_task_view(ctx, "toy-acc")["panels"]
    assert [p["type"] for p in panels] and all("error" not in p for p in panels)
