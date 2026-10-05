"""Durable sweep acceptances are distinct from completed experiment runs."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

import hypothex.cli.main as cli
import hypothex.mcp.server as mcp
from hypothex.core.context import Context
from tests.mcp.test_server import call

runner = CliRunner()


def summary(state: str | None = "queued") -> dict[str, Any]:
    issuance = (
        None
        if state is None
        else {
            "state": state,
            "episode": 1,
            "revision": 1,
            "planned": 12,
            "accepted_at": None if state == "preparing" else "2026-10-05T00:00:00Z",
            "updated_at": "2026-10-05T00:00:00Z",
            "cancel_requested": False,
            "reason": None,
            "error": None,
            "resume": None,
        }
    )
    return {
        "spec": {"id": "s-1", "project": "toy", "task": "t", "host": None, "grid": []},
        "headline": "No scored runs yet",
        "counts": {"total": 0, "queued": 0, "running": 0},
        "cells": [],
        "best": None,
        "total_usd": 0,
        "run_ids": [],
        "issuance": issuance,
    }


@pytest.mark.parametrize(
    "state", ["preparing", "queued", "issuing", "settling", "issued", "incomplete", "interrupted"]
)
def test_sweep_text_identifies_issuance_state_without_inventing_run_counts(
    state: str, capsys: pytest.CaptureFixture[str]
) -> None:
    cli._sweep_out(summary(state), False)
    text = capsys.readouterr().out
    assert f"issuance: {state}" in text and "planned cells: 12" in text
    assert "total 0" in text and "queued 0" in text
    if state == "queued":
        assert "accepted" in text and "hx sweep show s-1" in text
    if state == "preparing":
        assert "not yet accepted" in text
    if state == "issued":
        assert "runs may still be running" in text


def test_sweep_text_retains_cancel_and_resume_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = summary("settling")
    out["issuance"]["cancel_requested"] = True
    cli._sweep_out(out, False)
    assert "cancellation requested" in capsys.readouterr().out
    out = summary("interrupted")
    out["issuance"].update(
        reason="cancelled",
        error={"type": "SweepInterruptedError", "message": "drained"},
        resume={"seeds": [1, 2], "message": "Running members continue"},
    )
    cli._sweep_out(out, False)
    text = capsys.readouterr().out
    assert "cancelled" in text and "drained" in text
    assert "hx sweep extend s-1 --project toy --seeds 1,2" in text
    assert "Running members continue" in text


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("action", ["cancel", "extend"])
def test_local_durable_sweep_actions_use_hub_but_legacy_actions_stay_direct(
    durable: bool, action: str, ctx: Context, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = SimpleNamespace(project="toy", id="s-1", host=None)
    out = summary("queued" if durable else None)
    seen: list[dict[str, Any]] = []
    direct: list[str] = []
    monkeypatch.setattr(mcp, "locate_sweep", lambda *a, **kw: (spec, True))
    monkeypatch.setattr(
        type(ctx.events),
        "sweep_operation",
        lambda *a, **kw: {"issuance": out["issuance"]} if durable else None,
    )

    def hub(method: str, path: str, body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        seen.append({"method": method, "path": path, "body": body, **kwargs})
        return out

    def local(*args: Any, **kwargs: Any) -> Any:
        direct.append(action)
        return out

    monkeypatch.setattr(mcp, "hub_call", hub)
    monkeypatch.setattr(
        mcp.core_sweeps, "cancel_queued" if action == "cancel" else "extend_sweep", local
    )
    args = ["sweep", action, "s-1", "--project", "toy", "--json"]
    if action == "extend":
        args += ["--seeds", "1,2"]
    result = runner.invoke(cli.app, args, catch_exceptions=False)
    assert result.exit_code == 0 and json.loads(result.stdout) == out
    tool_args: dict[str, Any] = {"project": "toy", "sweep_id": "s-1"}
    if action == "extend":
        tool_args["seeds"] = [1, 2]
    err, answer = call(
        home,
        f"{action}_sweep",
        tool_args,
        server=mcp.build_server(home, agent="named", hub_token="selected"),
    )
    assert not err and answer == out
    if durable:
        assert not direct and len(seen) == 2
        assert all(c["method"] == "POST" and c["body"]["command_id"] for c in seen)
        assert seen[1]["body"]["created_by"] == "agent:named" and seen[1]["token"] == "selected"
    else:
        assert not seen and direct == [action, action]


@pytest.mark.parametrize("state", ["queued", "incomplete", "interrupted", "issued"])
def test_sweeps_list_exposes_zero_member_issuance_state(
    state: str, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    row = {
        "id": "s-1",
        "project": "toy",
        "created_at": datetime(2026, 10, 5, tzinfo=UTC),
        "n_runs": 0,
        "best": None,
        "issuance": summary(state)["issuance"],
    }
    monkeypatch.setattr(cli.q, "list_sweeps", lambda *a: [row])
    monkeypatch.setattr(cli, "_hub_sweeps", lambda *a: [])
    result = runner.invoke(cli.app, ["sweeps"], catch_exceptions=False)
    assert "issuance" in result.stdout and state in result.stdout
    result = runner.invoke(cli.app, ["sweeps", "--json"], catch_exceptions=False)
    assert json.loads(result.stdout)[0]["issuance"]["state"] == state
