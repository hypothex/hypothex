import sys
from pathlib import Path
from typing import Any

import pytest

from hypothex.api import app as app_module
from hypothex.api.app import create_app
from hypothex.core import control
from hypothex.core.context import Context
from hypothex.core.sweeps import list_sweeps
from hypothex.mcp.server import MCPServer, _text
from tests.api.envserver import remote_hub, serve_app, wait_until
from tests.factories import PREDS_075, git, seed_finished_run, write_toy_project
from tests.mcp.test_server import call

PY = sys.executable
SWEEP_CMD = [PY, "-c", "import sys", "{x}", "{seed}"]


def test_list_hosts_through_the_hub(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        err, out = call(home, "list_hosts")
        assert not err and [h["name"] for h in out["hosts"]] == ["local", "gpu1"]


def test_mounted_mcp_calls_its_own_hub_with_the_server_token(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(home, background_repair=False, hub=False, auth_token="hub-secret")
    with serve_app(app) as url:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", url)
        err, out = call(home, "list_hosts", server=app.state.mcp)
        assert not err, out
        assert [h["name"] for h in out["hosts"]] == ["local"]
        err, message = call(home, "list_hosts")  # a client without the token is refused
        assert err and "bearer token" in message


def test_list_hosts_without_a_hub(home: Path) -> None:
    err, message = call(home, "list_hosts")
    assert err and "hx serve" in message


def test_launch_run_on_a_host(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        err, out = call(
            home,
            "launch_run",
            {
                "repo": str(r.hub_repo),
                "hypothesis": "remote via mcp",
                "task": "toy-acc",
                "command": [PY, "-c", "print(1)"],
                "host": "gpu1",
            },
        )
        assert not err and out["host"] == "gpu1"
        assert r.env.find_record(out["run"]["run_id"]).created_by == "agent:mcp"


def test_local_sweep_tools(home: Path, ctx: Context, toy_repo: Path) -> None:
    ctx.register_project(toy_repo)
    base = {"project": "toy", "task": "toy-acc", "hypothesis": "x helps", "seeds": [1]}
    grid = {"x": [1, 0.1234567]}
    err, out = call(home, "launch_sweep", {**base, "command": SWEEP_CMD, "grid": grid})
    assert not err
    sid, ids = out["spec"]["id"], out["run_ids"]
    assert sorted(ctx.find_record(i).params["x"] for i in ids) == ["0.1234567", "1"]
    for rid in ids:
        control.wait_for_run(ctx, rid, timeout=60)
    err, got = call(home, "get_sweep", {"project": "toy", "sweep_id": sid})
    assert not err and got["spec"]["id"] == sid
    err, more = call(home, "extend_sweep", {"project": "toy", "sweep_id": sid, "seeds": [2]})
    assert not err and len(more["run_ids"]) == 4
    for rid in more["run_ids"]:
        control.wait_for_run(ctx, rid, timeout=60)
    err, cancelled = call(home, "cancel_sweep", {"project": "toy", "sweep_id": sid})
    assert not err and cancelled["spec"]["id"] == sid
    err, message = call(
        home, "launch_sweep", {**base, "command": [PY, "{seed}"], "grid": {"x": [1]}}
    )
    assert err and "{x}" in message


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0.0001, "0.0001"),
        (1e-05, "1e-05"),
        (2.5, "2.5"),
        (0.1234567, "0.1234567"),
        (1234567.0, "1234567.0"),
        (3, "3"),
        ("1e-3", "1e-3"),
    ],
)
def test_sweep_values_keep_every_digit(value: str | int | float, text: str) -> None:
    assert _text(value) == text
    if isinstance(value, float):
        assert float(_text(value)) == value


@pytest.mark.parametrize("host", [None, "gpu1"])
def test_launch_sweep_refuses_an_agent_without_a_hypothesis(
    home: Path, ctx: Context, toy_repo: Path, host: str | None
) -> None:
    ctx.register_project(toy_repo)
    err, message = call(
        home,
        "launch_sweep",
        {
            "project": "toy",
            "task": "toy-acc",
            "hypothesis": "  ",
            "command": SWEEP_CMD,
            "grid": {"x": [1]},
            "seeds": [1],
            "host": host,
        },
    )
    assert err and "agents must give a hypothesis" in message
    assert list_sweeps(ctx, "toy") == []  # refused before anything starts


def test_remote_sweep_and_pull_tools(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        err, out = call(
            home,
            "launch_sweep",
            {
                "project": "toy",
                "task": "toy-acc",
                "command": SWEEP_CMD,
                "hypothesis": "remote",
                "grid": {"x": ["1", "2"]},
                "seeds": [1],
                "host": "gpu1",
            },
        )
        assert not err and out["spec"]["host"] == "gpu1" and len(out["run_ids"]) == 2
        record = seed_finished_run(r.env, r.env_repo, "e1", predictions=PREDS_075)
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        rel = "predictions/predictions.jsonl"
        err, pulled = call(home, "pull_artifact", {"run_id": "e1", "artifact": rel})
        assert not err
        assert Path(pulled["local_path"]).read_text() == (r.env.run_dir(record) / rel).read_text()


def test_remote_sweep_sends_the_client_checkout(
    home: Path, ctx: Context, toy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hypothex.mcp.server as server_mod

    sent: list[dict[str, Any]] = []

    def record_hub(method: str, path: str, body: dict[str, Any], **kwargs: Any) -> Any:
        sent.append(body)
        return {"ok": True}

    monkeypatch.setattr(server_mod, "hub_call", record_hub)
    ctx.register_project(toy_repo)
    (toy_repo / "data" / "test.jsonl").write_text("{}\n")  # an uncommitted change
    base = {
        "project": "toy",
        "command": SWEEP_CMD,
        "hypothesis": "remote",
        "grid": {"x": ["1"]},
        "seeds": [1],
        "host": "gpu1",
    }
    head = git(toy_repo, "rev-parse", "HEAD")
    err, _ = call(home, "launch_sweep", base)  # the registered checkout of the project
    assert not err
    assert sent[-1]["commit"] == head and "test.jsonl" in sent[-1]["diff"]
    err, _ = call(home, "launch_sweep", {**base, "repo": str(toy_repo)})  # an explicit checkout
    assert not err and sent[-1]["commit"] == head
    other = write_toy_project(tmp_path / "other")
    (other / "hypothex.yaml").write_text(
        (other / "hypothex.yaml").read_text().replace("project: toy", "project: other")
    )
    err, message = call(home, "launch_sweep", {**base, "repo": str(other)})
    assert err and "not 'toy'" in message
    assert len(sent) == 2


def test_remote_sweep_skips_a_host_copy_of_the_project(
    home: Path, ctx: Context, toy_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hypothex.mcp.server as server_mod

    sent: list[dict[str, Any]] = []

    def record_hub(method: str, path: str, body: dict[str, Any], **kwargs: Any) -> Any:
        sent.append(body)
        return {"ok": True}

    monkeypatch.setattr(server_mod, "hub_call", record_hub)
    entry = ctx.register_project(toy_repo)
    # a copy from gpu1: its repo names gpu1's folder, which here is also a local folder
    ctx.store.save_project(entry.model_copy(update={"remote_host": "gpu1"}))
    base = {
        "project": "toy",
        "command": SWEEP_CMD,
        "hypothesis": "remote",
        "grid": {"x": ["1"]},
        "seeds": [1],
        "host": "gpu1",
    }
    err, _ = call(home, "launch_sweep", base)
    assert not err
    assert "commit" not in sent[-1] and "diff" not in sent[-1]  # the host's mapped checkout runs
    err, _ = call(home, "launch_sweep", {**base, "repo": str(toy_repo)})  # an explicit opt-in
    assert not err and sent[-1]["commit"] == git(toy_repo, "rev-parse", "HEAD")


def test_mutation_tools_send_host_runs_through_the_hub(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with remote_hub(tmp_path, threaded=True, hub_home=home) as r:
        monkeypatch.setenv("HYPOTHEX_HUB_URL", r.hub_url)
        seed_finished_run(r.env, r.env_repo, "e1")
        wait_until(lambda: "e1" in r.hub.index.run_ids(), timeout=30)
        err, out = call(home, "tag_run", {"run_id": "e1", "add": ["via-mcp"]})
        assert not err and out["run"]["tags"] == ["via-mcp"]
        assert r.env.find_record("e1").tags == ["via-mcp"]
        err, out = call(home, "add_note", {"run_id": "e1", "text": "mcp note"})
        assert not err and "mcp note" in r.env.store.read_notes("toy", "e1")
        err, message = call(home, "stop_run", {"run_id": "e1"})
        assert err and "only queued or running" in message  # the host answered


def test_create_app_gives_mcp_its_own_url(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str | None] = {}
    real = app_module.build_server

    def spy(
        h: Path | None = None,
        hub_url: str | None = None,
        *,
        context: Context | None = None,
        hub_token: str | None = None,
    ) -> MCPServer:
        seen.update(hub_url=hub_url, hub_token=hub_token)
        return real(h, hub_url=hub_url, context=context, hub_token=hub_token)

    monkeypatch.setattr(app_module, "build_server", spy)
    create_app(home, background_repair=False, hub_url="http://127.0.0.1:5555", auth_token="t")
    assert seen == {"hub_url": "http://127.0.0.1:5555", "hub_token": "t"}
