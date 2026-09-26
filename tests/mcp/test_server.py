import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from mcp import Client
from mcp.types import TextContent

from hypothex.api.app import create_app
from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from hypothex.mcp.server import build_server
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
}


def call(home: Path, name: str, args: dict[str, Any] | None = None) -> tuple[bool, Any]:
    server = build_server(home)

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
