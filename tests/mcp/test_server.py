import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from mcp import Client
from mcp.types import TextContent

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, RunError, StoreError
from hypothex.core.evaluation import evaluate_run
from hypothex.mcp.server import MCPServer, build_server, require_agent_hypothesis
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
    "connect_host",
    "list_sweeps",
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


def test_views_of_a_host_copy_never_use_a_folder_at_its_repo_path(
    ctx: Context, toy_repo: Path
) -> None:
    from hypothex.mcp.server import (
        list_task_views,
        put_view,
        query_task_view,
        remove_view,
        view_document,
    )

    entry = ctx.register_project(toy_repo)
    views = toy_repo / ".hypothex" / "views" / "toy-acc"
    views.mkdir(parents=True)
    (views / "mine.yaml").write_text(GOOD_VIEW)
    assert [v.name for v in list_task_views(ctx, "toy-acc")] == ["overview", "mine"]
    # a copy from gpu1: its repo names gpu1's folder, which here is also a local folder.
    # Its config has an inline view of the same name as the file here.
    task = entry.config.tasks["toy-acc"]
    inline = {"mine": {**yaml.safe_load(GOOD_VIEW), "title": "inline one"}}
    tasks = {**entry.config.tasks, "toy-acc": task.model_copy(update={"views": inline})}
    config = entry.config.model_copy(update={"tasks": tasks})
    ctx.store.save_project(entry.model_copy(update={"remote_host": "gpu1", "config": config}))
    listed = list_task_views(ctx, "toy-acc")
    assert [(v.name, v.origin) for v in listed] == [("overview", "preset"), ("mine", "inline")]
    doc = view_document(ctx, "toy-acc", "mine")
    assert doc["info"]["origin"] == "inline" and doc["view"]["title"] == "inline one"
    with pytest.raises(StoreError, match="unknown view 'nope'"):
        view_document(ctx, "toy-acc", "nope")
    assert view_document(ctx, "toy-acc", "overview")["info"]["origin"] == "preset"
    assert query_task_view(ctx, "toy-acc", name="mine")["panels"][0]["title"] == "board"
    assert query_task_view(ctx, "toy-acc")["panels"]  # the preset still draws
    with pytest.raises(ConfigError, match="copied from host gpu1"):
        put_view(ctx, "toy-acc", "other", GOOD_VIEW)
    with pytest.raises(ConfigError, match="copied from host gpu1"):
        remove_view(ctx, "toy-acc", "mine")
    assert sorted(p.name for p in views.iterdir()) == ["mine.yaml"]  # nothing written here
