"""Transport classification, attribution and reinfer variable contracts."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

import hypothex.cli.main as cli
import hypothex.mcp.server as server
from hypothex.core.context import Context
from hypothex.core.errors import HypothexError, RunNotFoundError
from tests.factories import seed_finished_run
from tests.mcp.test_dogfood_tools import schemas
from tests.mcp.test_server import call

runner = CliRunner()


@pytest.mark.parametrize(
    "kind", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout, httpx.ConnectError]
)
def test_hub_timeout_distinguishes_accepted_work_from_unavailable(
    kind: type[httpx.TransportError], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def request(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        raise kind("synthetic transport failure")

    monkeypatch.setattr(server, "_hub_request", request)
    with pytest.raises(HypothexError) as caught:
        server.hub_call("POST", "/api/v1/sweeps", {"command_id": "cmd-fixed"}, token="selected")
    if kind in (httpx.ReadTimeout, httpx.WriteTimeout):
        assert type(caught.value).__name__ == "HubTimeoutError"
        assert not isinstance(caught.value, server.HubUnavailableError)
        assert "still" in str(caught.value) and "hx sweeps" in str(caught.value)
        assert "start" not in str(caught.value)
    else:
        assert type(caught.value) is server.HubUnavailableError
    assert len(calls) == 1 and calls[0]["json"]["command_id"] == "cmd-fixed"
    assert calls[0]["headers"]["Authorization"] == "Bearer selected"


CLI_MUTATIONS = [
    ["stop", "missing"],
    ["tag", "missing", "--add", "a"],
    ["note", "missing", "text"],
    ["rerun", "missing"],
    ["reeval", "missing"],
    ["reinfer", "missing"],
]
MCP_MUTATIONS = [
    ("stop_run", {"run_id": "missing"}),
    ("tag_run", {"run_id": "missing", "add": ["a"]}),
    ("add_note", {"run_id": "missing", "text": "text"}),
    ("rerun", {"run_id": "missing"}),
    ("reevaluate", {"run_id": "missing"}),
    ("reinfer", {"run_id": "missing"}),
]


@pytest.mark.parametrize("args", CLI_MUTATIONS)
def test_cli_missing_mutation_identifies_the_run_when_hub_is_unavailable(
    args: list[str], home: Path
) -> None:
    with pytest.raises(RunNotFoundError, match="no run 'missing'.*hub unavailable"):
        runner.invoke(cli.app, args, catch_exceptions=False)


@pytest.mark.parametrize(("tool", "args"), MCP_MUTATIONS)
def test_mcp_missing_mutation_identifies_the_run_when_hub_is_unavailable(
    tool: str, args: dict[str, Any], home: Path
) -> None:
    err, message = call(home, tool, args)
    assert err and "no run 'missing'" in message and "hub unavailable" in message


@pytest.mark.parametrize("status", [401, 403, 400, 500, 503])
def test_known_mirrored_mutation_preserves_hub_error_and_missing_auth_is_not_rewritten(
    status: int, ctx: Context, toy_repo: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_finished_run(ctx, toy_repo, "remote")
    ctx.update_run(
        "remote", "test.remote", lambda r: r.model_copy(update={"environment_id": "other"})
    )
    message = "host gpu1 unavailable" if status == 503 else f"original {status} diagnostic"
    monkeypatch.setattr(
        server, "_hub_request", lambda *a, **kw: httpx.Response(status, json={"error": message})
    )
    with pytest.raises(HypothexError) as caught:
        runner.invoke(cli.app, ["tag", "remote", "--add", "x"], catch_exceptions=False)
    assert str(caught.value) == message and "no run" not in str(caught.value)
    err, text = call(home, "tag_run", {"run_id": "remote", "add": ["x"]})
    assert err and message in text and "no run" not in text
    if status != 503:
        with pytest.raises(HypothexError) as caught:
            runner.invoke(cli.app, ["tag", "missing", "--add", "x"], catch_exceptions=False)
        assert str(caught.value) == message
        err, text = call(home, "tag_run", {"run_id": "missing", "add": ["x"]})
        assert err and message in text and "no run" not in text


def test_timeout_on_missing_mutation_is_not_rewritten_or_retried(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bodies: list[Any] = []

    def request(*args: Any, **kwargs: Any) -> Any:
        bodies.append(kwargs["json"])
        raise httpx.ReadTimeout("after accepting")

    monkeypatch.setattr(server, "_hub_request", request)
    with pytest.raises(HypothexError) as caught:
        runner.invoke(cli.app, ["tag", "missing", "--add", "x"], catch_exceptions=False)
    assert type(caught.value).__name__ == "HubTimeoutError" and "no run" not in str(caught.value)
    err, text = call(home, "tag_run", {"run_id": "missing", "add": ["x"]})
    assert err and "still" in text and "no run" not in text
    assert len(bodies) == 2 and all(body["command_id"] for body in bodies)


def test_local_existing_mutations_do_not_need_hub(
    ctx: Context, toy_repo: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_finished_run(ctx, toy_repo, "local")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("local mutation used the hub")

    monkeypatch.setattr(server, "_hub_request", forbidden)
    assert (
        runner.invoke(cli.app, ["tag", "local", "--add", "cli"], catch_exceptions=False).exit_code
        == 0
    )
    err, out = call(home, "tag_run", {"run_id": "local", "add": ["mcp"]})
    assert not err and out["run"]["tags"] == ["cli", "mcp"]


@pytest.mark.parametrize("remote", [False, True])
def test_reinfer_vars_cross_cli_and_mcp_without_becoming_params(
    remote: bool, ctx: Context, toy_repo: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = seed_finished_run(ctx, toy_repo, "parent")
    if remote:
        ctx.update_run(
            "parent", "test.remote", lambda r: r.model_copy(update={"environment_id": "remote"})
        )
    seen: list[dict[str, Any]] = []

    def local(c: Context, run_id: str, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return rec

    def hub(method: str, path: str, body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        assert path.endswith("/parent/reinfer")
        seen.append(body or {})
        return rec.model_dump(mode="json")

    monkeypatch.setattr(cli, "reinfer", local)
    monkeypatch.setattr(server.control, "reinfer", local)
    monkeypatch.setattr(server, "hub_call", hub)
    result = runner.invoke(
        cli.app,
        ["reinfer", "parent", "--var", "temperature=2", "--checkpoint", "model.pt", "--json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0 and json.loads(result.stdout)["run_id"] == "parent"
    assert seen[-1]["vars"] == {"temperature": "2"} and seen[-1]["checkpoint"] == "model.pt"
    assert "vars" in schemas(server.build_server(home))["reinfer"].input_schema["properties"]
    err, out = call(
        home,
        "reinfer",
        {"run_id": "parent", "vars": {"temperature": "3"}, "checkpoint": "model.pt"},
    )
    assert not err, out
    assert seen[-1]["vars"] == {"temperature": "3"} and "params" not in seen[-1]
    if remote:
        assert all(item["command_id"] for item in seen)


def test_mcp_server_agent_default_and_explicit_launch_override(
    ctx: Context, toy_repo: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = seed_finished_run(ctx, toy_repo, "r1")
    created: list[str] = []

    def launch(c: Context, request: Any) -> Any:
        created.append(request.created_by)
        return rec

    monkeypatch.setattr(server.control, "launch_run", launch)
    mcp = server.build_server(home, agent="default-agent")
    args = {"repo": str(toy_repo), "hypothesis": "test", "command": ["true"]}
    err, out = call(home, "launch_run", args, server=mcp)
    assert not err, out
    err, out = call(home, "launch_run", {**args, "agent": "override"}, server=mcp)
    assert not err, out
    assert created == ["agent:default-agent", "agent:override"]
    monkeypatch.setenv("HYPOTHEX_AGENT", "ambient")
    err, out = call(home, "launch_run", args, server=server.build_server(home))
    assert not err, out
    assert created[-1] == "agent:mcp"


def test_stdio_passes_environment_agent_to_build_server(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    class FakeServer:
        def run(self) -> None:
            pass

    def build(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return FakeServer()

    monkeypatch.setattr(server, "build_server", build)
    monkeypatch.setenv("HYPOTHEX_AGENT", "named")
    result = runner.invoke(cli.app, ["mcp"], catch_exceptions=False)
    assert result.exit_code == 0 and seen == [{"agent": "named"}]


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        *MCP_MUTATIONS,
        ("connect_host", {"name": "gpu1"}),
        ("cancel_sweep", {"project": "toy", "sweep_id": "s-1"}),
        ("extend_sweep", {"project": "toy", "sweep_id": "s-1", "seeds": [2]}),
        ("pull_artifact", {"run_id": "missing"}),
    ],
)
@pytest.mark.parametrize("override", [None, "override"])
def test_every_command_tool_uses_selected_agent_and_preserves_credentials(
    tool: str,
    args: dict[str, Any],
    override: str | None,
    ctx: Context,
    toy_repo: Path,
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    rec = seed_finished_run(ctx, toy_repo, "missing")
    ctx.update_run(
        "missing", "test.remote", lambda r: r.model_copy(update={"environment_id": "remote"})
    )
    seen: list[dict[str, Any]] = []

    def hub(method: str, path: str, body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        assert method == "POST"
        seen.append({"body": body, **kwargs})
        if path.endswith("/reeval"):
            return {"evaluated": [], "skipped": {}, "warnings": []}
        return rec.model_dump(mode="json")

    monkeypatch.setattr(server, "hub_call", hub)
    monkeypatch.setattr(
        server,
        "locate_sweep",
        lambda *a, **kw: (SimpleNamespace(host="gpu1", project="toy", id="s-1"), True),
    )
    mcp = server.build_server(
        home, agent="default-agent", hub_url="http://127.0.0.1:1", hub_token="selected"
    )
    selected = {**args, **({"agent": override} if override is not None else {})}
    err, out = call(home, tool, selected, server=mcp)
    assert not err, out
    assert len(seen) == 1
    assert seen[0]["body"]["created_by"] == f"agent:{override or 'default-agent'}"
    assert seen[0]["body"]["command_id"] and seen[0]["token"] == "selected"


def test_launch_sweep_and_task_reeval_use_server_agent(
    ctx: Context, toy_repo: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.register_project(toy_repo)
    rec = seed_finished_run(ctx, toy_repo, "remote")
    ctx.update_run(
        "remote", "test.remote", lambda r: r.model_copy(update={"environment_id": "remote"})
    )
    seen: list[dict[str, Any]] = []

    def hub(method: str, path: str, body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        seen.append(body or {})
        return (
            {"evaluated": [], "skipped": {}, "warnings": []}
            if path.endswith("/reeval")
            else {"accepted": True}
        )

    monkeypatch.setattr(server, "hub_call", hub)
    mcp = server.build_server(home, agent="named")
    err, out = call(
        home,
        "launch_sweep",
        {
            "project": "toy",
            "command": ["echo", "{x}"],
            "hypothesis": "why",
            "grid": {"x": [1]},
            "seeds": [1],
            "host": "gpu1",
        },
        server=mcp,
    )
    assert not err, out
    err, out = call(home, "reevaluate", {"task": "toy-acc"}, server=mcp)
    assert not err, out
    assert len(seen) == 2 and all(body["created_by"] == "agent:named" for body in seen)
    assert rec.run_id == "remote"
