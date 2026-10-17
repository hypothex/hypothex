"""Assembled team acceptance through actual CLI, HTTP, WebSocket, hub and host processes."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from hypothex.auth.pairing import parse_pairing_url
from tests.acceptance.conftest import Lab
from tests.api.envserver import wait_until


def auth(token: str) -> dict[str, str]:
    """Build the explicit synthetic credential header."""
    return {"Authorization": f"Bearer {token}"}


def complete(client: httpx.Client, run_id: str) -> dict[str, Any]:
    """Wait for an actual launched run to finish and return its mirrored detail."""

    def finished() -> dict[str, Any] | None:
        response = client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200, response.text
        detail = response.json()
        return (
            detail
            if detail["record"]["status"] in {"finished", "failed", "lost", "killed"}
            else None
        )

    detail = wait_until(finished, timeout=40)
    assert detail["record"]["status"] == "finished", detail["record"]
    return detail


def test_real_collaborators_pair_share_host_and_preserve_owner_receipts(lab: Lab) -> None:
    alice_home, alice = lab.pair("alice")
    bob_home, bob = lab.pair("bob")
    assert lab.cli(alice_home, "projects") == lab.cli(lab.hub.home, "projects", owner=True)
    assert lab.cli(alice_home, "tasks") == lab.cli(lab.hub.home, "tasks", owner=True)
    launched = lab.cli(
        alice_home,
        "launch",
        "--host",
        "shared",
        "-t",
        "toy-acc",
        "-H",
        "shared acceptance",
        "--wait",
        "--",
        sys.executable,
        "-c",
        "print('acceptance worker')",
        cwd=lab.laptop_repo,
    )
    assert launched["status"] == "finished"
    with (
        httpx.Client(base_url=lab.hub.url, headers=auth(alice), timeout=40) as client,
        httpx.Client(base_url=lab.hub.url, headers=auth(lab.hub.token), timeout=40) as owner,
    ):
        record = complete(owner, launched["run_id"])["record"]
        assert (record["owner"], record["created_by"]) == ("alice", "human:alice")
        assert (
            record["environment_id"]
            != owner.get("/.well-known/hypothex/environment").json()["environment_id"]
        )
        owner_rows = lab.cli(lab.hub.home, "runs", owner=True)
        assert record["run_id"] in {row["run_id"] for row in owner_rows}
        body = {
            "project": "toy",
            "task": "toy-acc",
            "command": [sys.executable, "-c", "print('agent')"],
            "hypothesis": "receipt ownership",
            "command_id": "same-user-command",
            "created_by": "human:sv",
            "owner": "sv",
        }
        first = client.post(
            "/api/v1/hosts/shared/runs", json=body, headers={"X-Hypothex-Agent": "acceptance"}
        )
        assert first.status_code == 200, first.text
        repeated = client.post(
            "/api/v1/hosts/shared/runs", json=body, headers={"X-Hypothex-Agent": "acceptance"}
        )
        assert repeated.status_code == 200 and repeated.json()["run_id"] == first.json()["run_id"]
        other = owner.post("/api/v1/hosts/shared/runs", json=body, headers=auth(bob))
        assert other.status_code == 200 and other.json()["run_id"] != first.json()["run_id"]
        a_record = complete(owner, first.json()["run_id"])["record"]
        b_record = complete(owner, other.json()["run_id"])["record"]
        assert (a_record["owner"], a_record["created_by"]) == ("alice", "agent:acceptance@alice")
        assert (b_record["owner"], b_record["created_by"]) == ("bob", "human:bob")
        local_body = {
            "repo": str(lab.repo),
            "task": "toy-acc",
            "command": [sys.executable, "-c", "import time;time.sleep(60)"],
            "hypothesis": "local authorization boundary",
            "command_id": "local-owned",
        }
        denied = client.post("/api/v1/runs", json=local_body)
        assert denied.status_code == 403 and "need admin" in denied.json()["error"]
        local = owner.post("/api/v1/runs", json=local_body)
        assert local.status_code == 200, local.text
        run_id = local.json()["run_id"]
        try:
            denied = client.post(f"/api/v1/runs/{run_id}/stop", json={"command_id": "bad-stop"})
            assert denied.status_code == 403 and "owned by sv" in denied.json()["error"]
        finally:
            stopped = owner.post(f"/api/v1/runs/{run_id}/stop", json={"command_id": "owner-stop"})
            assert stopped.status_code == 200, stopped.text
        for path in ("/api/v1/storage", "/api/v1/auth/users"):
            assert client.get(path).status_code == 403
        own = client.post(
            "/api/v1/hosts/shared/runs",
            json={
                **body,
                "command_id": "long-own",
                "command": [sys.executable, "-c", "import time;time.sleep(60)"],
            },
        )
        assert own.status_code == 200, own.text
        assert lab.cli(alice_home, "stop", own.json()["run_id"])["status"] == "killed"
        # The server process can restart without invalidating paired clients or stored receipts.
        previous_admin = lab.hub.token
        lab.hub.stop()
        lab.hub.start()
        assert lab.hub.token != previous_admin
        assert lab.cli(alice_home, "whoami")["user"] == "alice"
        assert lab.cli(bob_home, "whoami")["user"] == "bob"
        wait_until(
            lambda: any(
                row["name"] == "shared" and row["state"]["state"] == "connected"
                for row in owner.get("/api/v1/hosts", headers=auth(lab.hub.token)).json()
            ),
            timeout=30,
        )
        replay = client.post("/api/v1/hosts/shared/runs", json=body)
        assert replay.status_code == 200 and replay.json()["run_id"] == first.json()["run_id"]


def _rpc(response: httpx.Response) -> dict[str, Any]:
    """Decode the real streamable HTTP response."""
    assert response.status_code == 200, response.text
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return next(
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    )


def test_real_cookie_websocket_and_cli_revocation_and_mcp_forwarding(lab: Lab) -> None:
    laptop, alice = lab.pair("alice")
    offer = lab.cli(lab.hub.home, "pair", "--user", "alice", "--scope", "launch", owner=True)
    _, offer_id, secret = parse_pairing_url(offer["url"])
    with httpx.Client(base_url=lab.hub.url, timeout=40) as browser:
        response = browser.post(
            "/api/v1/auth/pair",
            json={
                "offer_id": offer_id,
                "secret": secret,
                "client": "browser",
                "device": "browser",
            },
        )
        assert response.status_code == 200, response.text
        assert "token" not in response.json()
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        session = browser.get("/api/v1/auth/me").json()["session_id"]
        ticket_response = browser.post("/api/v1/auth/ws-ticket", json={})
        assert ticket_response.status_code == 200
        assert ticket_response.headers["cache-control"] == "no-store"
        ticket = ticket_response.json()["ticket"]
        # Real HTTP MCP with a rejected bearer and the browser's selected cookie.
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer rejected",
        }
        initialized = browser.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "acceptance", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200
        headers["mcp-session-id"] = initialized.headers["mcp-session-id"]
        browser.post(
            "/mcp/", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        me = _rpc(
            browser.post(
                "/mcp/",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "whoami", "arguments": {}},
                },
            )
        )["result"]
        assert me["structuredContent"] == {"user": "alice", "scope": "launch"}
        # connect_host forwards to the hub itself: it succeeds only if the selected
        # cookie credential is forwarded, since the invalid bearer cannot authenticate.
        forwarded = _rpc(
            browser.post(
                "/mcp/",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "connect_host", "arguments": {"name": "shared"}},
                },
            )
        )["result"]
        assert not forwarded.get("isError", False), forwarded
        owner_run = httpx.post(
            lab.hub.url + "/api/v1/hosts/shared/runs",
            headers=auth(lab.hub.token),
            json={
                "project": "toy",
                "task": "toy-acc",
                "command": [sys.executable, "-c", "import time;time.sleep(60)"],
                "hypothesis": "MCP selected credential refusal",
                "command_id": "mcp-owner-run",
            },
            timeout=30,
        )
        assert owner_run.status_code == 200, owner_run.text
        foreign_id = owner_run.json()["run_id"]
        wait_until(
            lambda: (
                httpx.get(
                    lab.hub.url + f"/api/v1/runs/{foreign_id}",
                    headers=auth(lab.hub.token),
                    timeout=5,
                ).status_code
                == 200
            ),
            timeout=30,
        )
        try:
            refused = _rpc(
                browser.post(
                    "/mcp/",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {"name": "stop_run", "arguments": {"run_id": foreign_id}},
                    },
                )
            )["result"]
            assert refused["isError"] is True
            assert "owned by sv" in refused["content"][0]["text"]
        finally:
            cleanup = httpx.post(
                lab.hub.url + f"/api/v1/runs/{foreign_id}/stop",
                headers=auth(lab.hub.token),
                json={"command_id": "owner-mcp-cleanup"},
                timeout=30,
            )
            assert cleanup.status_code == 200, cleanup.text

        async def stream() -> None:
            uri = lab.hub.url.replace("http://", "ws://") + "/api/v1/ws"
            async with websockets.connect(
                uri, subprotocols=["hypothex.v1", f"hx-ticket.{ticket}"]
            ) as ws:
                assert ws.subprotocol == "hypothex.v1"
                await ws.send(json.dumps({"type": "subscribe", "after_sequence": 0}))
                while json.loads(await asyncio.wait_for(ws.recv(), timeout=5))["type"] != "ready":
                    pass
                await asyncio.to_thread(
                    lab.cli, lab.hub.home, "sessions", "revoke", session, owner=True
                )
                start = time.monotonic()
                with pytest.raises(ConnectionClosed) as closed:
                    while True:
                        await asyncio.wait_for(ws.recv(), timeout=31)
                assert closed.value.rcvd is not None and closed.value.rcvd.code == 4401
                assert time.monotonic() - start <= 30
            with pytest.raises(InvalidStatus):
                async with websockets.connect(
                    uri, subprotocols=["hypothex.v1", f"hx-ticket.{ticket}"]
                ):
                    pytest.fail("a revoked browser reconnected with a consumed ticket")

        asyncio.run(stream())
        assert browser.get("/api/v1/auth/me").status_code == 401
        assert browser.post("/api/v1/auth/ws-ticket", json={}).status_code == 401
        assert browser.post("/mcp/", headers=headers, json={}).status_code == 401
    cli_session = lab.cli(laptop, "whoami")["session_id"]
    lab.cli(lab.hub.home, "sessions", "revoke", cli_session, owner=True)
    refused = lab.cli(laptop, "whoami", success=False)
    assert "401" in json.loads(refused.stdout)["error"]
    assert httpx.get(lab.hub.url + "/api/v1/projects", headers=auth(alice)).status_code == 401


def test_selected_primary_exports_match_cli_http_and_mcp(tmp_path: Path) -> None:
    import csv
    import io

    from hypothex.core.context import Context
    from tests.acceptance.conftest import LiveServer, run_cli
    from tests.core.test_backlog_backend import indexed
    from tests.factories import write_toy_project

    home = tmp_path / "export-home"
    indexed(Context.open(home), write_toy_project(tmp_path / "repo"))
    with LiveServer(home, ("--auth",)) as server:
        environment = {"HYPOTHEX_HUB_URL": server.url, "HYPOTHEX_HUB_TOKEN": server.token}
        with httpx.Client(base_url=server.url, headers=auth(server.token), timeout=20) as client:
            params = {"format": "csv", "metrics": "acc/value"}
            default = client.get("/api/v1/tasks/toy/t/export", params=params)
            selected = client.get(
                "/api/v1/tasks/toy/t/export", params={**params, "primary": "latency/p95"}
            )
            assert default.status_code == selected.status_code == 200
            first = list(csv.DictReader(io.StringIO(default.text)))
            second = list(csv.DictReader(io.StringIO(selected.text)))
            assert [row["label"] for row in first] == ["A", "B"]
            assert [row["label"] for row in second] == ["B", "A"]
            assert {row["metric"] for row in first + second} == {"acc/value"}
            cli = run_cli(
                home,
                "export",
                "t",
                "-p",
                "toy",
                "--primary",
                "latency/p95",
                "--metrics",
                "acc/value",
                "--format",
                "csv",
                environment=environment,
            )
            assert cli["text"] == selected.text
            headers = {"Accept": "application/json, text/event-stream"}
            response = client.post(
                "/mcp/",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "export-acceptance", "version": "1"},
                    },
                },
            )
            assert response.status_code == 200
            headers["mcp-session-id"] = response.headers["mcp-session-id"]
            client.post(
                "/mcp/",
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            result = _rpc(
                client.post(
                    "/mcp/",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "export_table",
                            "arguments": {
                                "task": "t",
                                "project": "toy",
                                "format": "csv",
                                "metrics": ["acc/value"],
                                "primary": "latency/p95",
                            },
                        },
                    },
                )
            )["result"]
            assert not result.get("isError", False), result
            assert result["structuredContent"]["text"] == selected.text
            assert (
                client.get(
                    "/api/v1/compare/export", params={"run_ids": "a,b", "primary": "acc/value"}
                ).status_code
                == 400
            )
