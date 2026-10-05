"""Agent-facing tool schemas and user-visible read contracts."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

import hypothex.mcp.server as server
from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from tests.factories import PREDS_075, seed_finished_run, write_toy_project
from tests.mcp.test_server import call


def schemas(mcp: MCPServer) -> dict[str, Any]:
    async def read() -> dict[str, Any]:
        async with Client(mcp) as client:
            return {t.name: t for t in (await client.list_tools()).tools}

    return asyncio.run(read())


def test_list_runs_resolves_qualified_tasks_and_rejects_ambiguous_or_unknown(
    ctx: Context, toy_repo: Path, tmp_path: Path, home: Path
) -> None:
    seed_finished_run(ctx, toy_repo, "first")
    other = write_toy_project(tmp_path / "other")
    config = other / "hypothex.yaml"
    config.write_text(config.read_text().replace("project: toy", "project: other"))
    seed_finished_run(ctx, other, "second")
    err, out = call(home, "list_runs", {"task": "toy/toy-acc"})
    assert not err and [r["run_id"] for r in out["runs"]] == ["first"]
    err, out = call(home, "list_runs", {"task": "toy-acc"})
    assert err and "several projects" in out
    err, out = call(home, "list_runs", {"task": "typo"})
    assert err and "unknown task" in out
    err, out = call(home, "list_runs")
    assert not err and {r["run_id"] for r in out["runs"]} == {"first", "second"}


def test_list_runs_defaults_to_compact_rows_and_exposes_full_mode(
    ctx: Context, toy_repo: Path, home: Path
) -> None:
    for i in range(50):
        rec = seed_finished_run(ctx, toy_repo, f"r{i}", seed=i)
        ctx.update_run(
            rec.run_id,
            "test.bulky",
            lambda r: r.model_copy(
                update={
                    "vars": {"prompt": "x" * 3000},
                    "command": ["python", "x" * 1000],
                }
            ),
        )
    tool = schemas(server.build_server(home))["list_runs"]
    assert tool.input_schema["properties"]["full"]["default"] is False
    err, compact = call(home, "list_runs")
    assert not err
    err, full = call(home, "list_runs", {"full": True})
    assert not err
    assert len(compact["runs"]) == len(full["runs"]) == 50
    assert len(json.dumps(compact)) < len(json.dumps(full)) / 3
    for small, big in zip(compact["runs"], full["runs"], strict=True):
        for key in ("run_id", "project", "task", "seed", "status", "created_at", "host_state"):
            assert small[key] == big[key]
        assert "vars" not in small and "command" not in small
        assert "vars" in big and "command" in big


def test_get_logs_default_tail_explicit_stream_and_byte_continuation(
    ctx: Context, toy_repo: Path, home: Path
) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    path = ctx.run_dir(rec) / "logs" / "stderr.log"
    path.write_text("".join(f"error {i} é\n" for i in range(250)))
    (ctx.run_dir(rec) / "logs" / "stdout.log").write_text("normal\n")
    tool = schemas(server.build_server(home))["get_logs"]
    props = tool.input_schema["properties"]
    assert props["stream"]["default"] == "stderr" and props["tail"]["default"] == 200
    err, first = call(home, "get_logs", {"run_id": "r1"})
    assert not err, first
    assert len(first["text"].splitlines()) == 200 and first["text"].startswith("error 50 é\n")
    assert first["offset"] == path.stat().st_size
    with path.open("a") as fh:
        fh.write("last é\n")
    err, more = call(home, "get_logs", {"run_id": "r1", "offset": first["offset"], "tail": 1})
    assert not err and more["text"] == "last é\n" and more["offset"] == path.stat().st_size
    err, out = call(home, "get_logs", {"run_id": "r1", "stream": "stdout"})
    assert not err and out["text"] == "normal\n"


@pytest.mark.parametrize("arguments", [{"stream": "../../secret"}, {"offset": -1}, {"tail": 0}])
def test_get_logs_rejects_invalid_options(
    arguments: dict[str, Any], ctx: Context, toy_repo: Path, home: Path
) -> None:
    seed_finished_run(ctx, toy_repo, "r1")
    assert "get_logs" in schemas(server.build_server(home))
    err, out = call(home, "get_logs", {"run_id": "r1", **arguments})
    assert err and out


def test_get_logs_reads_mirrored_logs_and_marks_untrusted_source(
    ctx: Context, toy_repo: Path, home: Path
) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    ctx.update_run("r1", "test.remote", lambda r: r.model_copy(update={"environment_id": "remote"}))
    (ctx.run_dir(rec) / "logs" / "stderr.log").write_text("remote failure\n")
    err, out = call(home, "get_logs", {"run_id": "r1"})
    assert not err and out["text"] == "remote failure\n"
    assert out["untrusted_source"] == "environment:remote"


def test_get_logs_missing_local_uses_hub_and_keeps_selected_credentials(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    def hub(method: str, path: str, body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        seen.append({"method": method, "path": path, **kwargs})
        return {"stream": "stderr", "text": "remote\n", "offset": 7, "size": 7}

    monkeypatch.setattr(server, "hub_call", hub)
    err, out = call(
        home,
        "get_logs",
        {"run_id": "remote-only"},
        server=server.build_server(home, hub_url="http://127.0.0.1:1", hub_token="selected"),
    )
    assert not err and out["text"] == "remote\n"
    assert seen[0]["path"].startswith("/api/v1/runs/remote-only/logs?")
    assert seen[0]["token"] == "selected"


def test_get_logs_unknown_run_reports_missing(home: Path) -> None:
    assert "get_logs" in schemas(server.build_server(home))
    err, out = call(home, "get_logs", {"run_id": "missing"})
    assert err and "no run" in out and "missing" in out


def test_group_instructions_and_example_comparison_tool(
    ctx: Context, toy_repo: Path, home: Path
) -> None:
    assert "vs_best" in server.INSTRUCTIONS and "within_noise_of_best" in server.INSTRUCTIONS
    seed_finished_run(ctx, toy_repo, "a", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "b", predictions=PREDS_075)
    evaluate_run(ctx, "a")
    evaluate_run(ctx, "b")
    tools = schemas(server.build_server(home))
    assert "run IDs only" in tools["compare_runs"].description
    err, out = call(home, "compare_examples", {"a": "a", "b": "b", "metric": "accuracy"})
    assert not err and out == q.compare_examples(ctx, "a", "b", "accuracy").model_dump(mode="json")
    group = q.get_leaderboard(ctx, "toy-acc").rows[0].group_id
    err, out = call(home, "compare_runs", {"run_ids": [group, "a"]})
    assert err and group in out
    seed_finished_run(ctx, toy_repo, "no-examples")
    err, out = call(home, "compare_examples", {"a": "no-examples", "b": "b", "metric": "accuracy"})
    assert err and "no per-example" in out


def test_leaderboard_metric_pins_select_older_version_and_reject_bad_pins(
    ctx: Context, toy_repo: Path, home: Path
) -> None:
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    write_toy_project(toy_repo, accuracy_version="v2")
    tool = schemas(server.build_server(home))["get_leaderboard"]
    assert "metric" in tool.input_schema["properties"]
    err, old = call(home, "get_leaderboard", {"task": "toy-acc", "metric": ["accuracy@v1"]})
    assert not err and old["rows"][0]["run_ids"] == ["r1"]
    err, current = call(home, "get_leaderboard", {"task": "toy-acc"})
    assert not err and current["headline"] == "1 need re-eval"
    for pin in ["accuracy", "accuracy@", "@v1"]:
        err, out = call(home, "get_leaderboard", {"task": "toy-acc", "metric": [pin]})
        assert err and out


def test_metric_pin_preserves_the_existing_version_string_grammar(
    ctx: Context, toy_repo: Path, home: Path
) -> None:
    # The shared parser partitions only on the first @; versions are arbitrary strings.
    write_toy_project(toy_repo, accuracy_version="v1@revision2")
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(ctx, "r1")
    err, out = call(
        home, "get_leaderboard", {"task": "toy-acc", "metric": ["accuracy@v1@revision2"]}
    )
    assert not err, out
    assert out["metric_versions"]["accuracy"] == "v1@revision2"
    assert out["rows"][0]["run_ids"] == ["r1"]
