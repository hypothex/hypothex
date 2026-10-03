import sys
from pathlib import Path

import pytest

from hypothex.api import app as app_module
from hypothex.api.app import create_app
from hypothex.core import control
from hypothex.core.context import Context
from hypothex.mcp.server import MCPServer
from tests.api.envserver import remote_hub, wait_until
from tests.factories import PREDS_075, seed_finished_run
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
    err, out = call(home, "launch_sweep", {**base, "command": SWEEP_CMD, "grid": {"x": [1, 2.5]}})
    assert not err
    sid, ids = out["spec"]["id"], out["run_ids"]
    assert sorted(ctx.find_record(i).params["x"] for i in ids) == ["1", "2.5"]
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
        h: Path | None = None, hub_url: str | None = None, *, context: Context | None = None
    ) -> MCPServer:
        seen["hub_url"] = hub_url
        return real(h, hub_url=hub_url, context=context)

    monkeypatch.setattr(app_module, "build_server", spy)
    create_app(home, background_repair=False, hub_url="http://127.0.0.1:5555")
    assert seen == {"hub_url": "http://127.0.0.1:5555"}
