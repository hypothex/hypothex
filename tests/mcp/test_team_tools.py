import asyncio
from pathlib import Path

from hypothex.auth.store import Principal
from hypothex.core.context import Context
from hypothex.core.evaluation import evaluate_run
from hypothex.mcp.server import acting_as, build_server, tool_scopes
from tests.factories import PREDS_075, seed_finished_run
from tests.mcp.test_server import call

ALICE = Principal(user="alice", scope="launch", session_id="s_00000000000a", client="cli")
NEW = {
    "export_table": "read",
    "export_compare": "read",
    "get_baselines": "read",
    "get_notebook": "read",
    "add_notebook_entry": "launch",
    "get_digest": "read",
    "storage_report": "admin",
    "plan_storage_clean": "admin",
    "whoami": "read",
}


def scored(home: Path, toy_repo: Path) -> Context:
    ctx = Context.open(home)
    seed_finished_run(ctx, toy_repo, "r1", predictions=PREDS_075)
    seed_finished_run(ctx, toy_repo, "r2", predictions=PREDS_075, config_hash="sha256:bbbb")
    evaluate_run(ctx, "r1")
    evaluate_run(ctx, "r2")
    return ctx


def test_new_tools_and_their_scopes(home: Path) -> None:
    scopes = tool_scopes(build_server(home))
    assert {name: scopes[name] for name in NEW} == NEW


def test_no_tool_deletes_sends_or_manages_people(home: Path) -> None:
    names = {t.name for t in asyncio.run(build_server(home).list_tools())}
    for word in ("apply", "delete", "clean_apply", "send", "notify", "user", "session"):
        assert not any(word in name for name in names), word


def test_export_tools(home: Path, toy_repo: Path) -> None:
    scored(home, toy_repo)
    err, out = call(home, "export_table", {"task": "toy-acc", "format": "latex"})
    assert not err and out["text"].startswith("% requires \\usepackage{booktabs}")
    err, out = call(home, "export_compare", {"run_ids": ["r1", "r2"]})
    assert not err and out["text"].startswith("| run | n | accuracy/value ↑ |")
    err, out = call(home, "get_baselines", {"task": "toy-acc"})
    assert not err and out == {"baselines": []}


def test_registered_export_tool_primary_schema_and_ranking(home: Path, toy_repo: Path) -> None:
    import csv
    import io

    from tests.core.test_backlog_backend import indexed

    indexed(Context.open(home), toy_repo)
    schemas = {
        tool.name: tool.input_schema for tool in asyncio.run(build_server(home).list_tools())
    }
    schema = schemas["export_table"]
    assert "primary" not in schema.get("required", [])
    assert schema["properties"]["primary"]["default"] is None
    assert {item["type"] for item in schema["properties"]["primary"]["anyOf"]} == {"string", "null"}
    assert "primary" not in schemas["export_compare"]["properties"]
    args = {"task": "t", "project": "toy", "format": "csv", "metrics": ["acc/value"]}
    err, default = call(home, "export_table", args)
    assert not err
    err, selected = call(home, "export_table", {**args, "primary": "latency/p95"})
    assert not err
    first = list(csv.DictReader(io.StringIO(default["text"])))
    second = list(csv.DictReader(io.StringIO(selected["text"])))
    assert [row["label"] for row in first] == ["A", "B"]
    assert [row["label"] for row in second] == ["B", "A"]
    assert {row["metric"] for row in first + second} == {"acc/value"}


def test_notebook_tools(home: Path, toy_repo: Path) -> None:
    scored(home, toy_repo)
    with acting_as(ALICE):
        err, day = call(
            home,
            "add_notebook_entry",
            {"project": "toy", "text": "r1 wins [[run:r1]]", "agent": "claude"},
        )
    assert not err and "— agent:claude@alice" in day["text"]
    err, again = call(home, "get_notebook", {"project": "toy", "day": day["day"]})
    assert not err and again["runs"][0]["run_id"] == "r1"
    reader = ALICE.model_copy(update={"scope": "read"})
    with acting_as(reader):
        err, message = call(home, "add_notebook_entry", {"project": "toy", "text": "x"})
    assert err and "launch scope needed" in message


def test_digest_and_whoami(home: Path, toy_repo: Path) -> None:
    scored(home, toy_repo)
    err, digest = call(home, "get_digest", {"project": "toy", "days": 7})
    assert not err and digest["counts"]["started"] == 2
    with acting_as(ALICE):
        err, me = call(home, "whoami")
    assert not err and me == {"user": "alice", "scope": "launch"}


def test_storage_tools_need_admin_and_never_apply(home: Path, toy_repo: Path) -> None:
    scored(home, toy_repo)
    with acting_as(ALICE):
        err, message = call(home, "storage_report")
    assert err and "admin scope needed" in message
    err, report = call(home, "storage_report")  # no hub answers: this machine only
    assert not err and report["errors"] == [] and report["total_bytes"] > 0
    err, plan = call(home, "plan_storage_clean", {"older_than_days": 30})
    assert not err and plan["plan_id"].startswith("cp-") and plan["items"] == []
