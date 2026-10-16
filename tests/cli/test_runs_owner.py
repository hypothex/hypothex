"""Owner filtering retains the existing local/hub merge and presentation."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from typer.testing import CliRunner

from hypothex.cli import main as cli_main
from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.records import RunStatus
from hypothex.mcp.server import HubUnavailableError
from tests.factories import make_record

runner = CliRunner()
STAMP = datetime(2026, 10, 1, 12, tzinfo=UTC)


def rows(*args: str) -> list[dict[str, Any]]:
    """Return the actual CLI's JSON list for the supplied options."""
    result = runner.invoke(cli_main.app, ["runs", *args, "--json"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


@pytest.mark.parametrize("owner", [None, "alice", "me"])
def test_owner_preserves_merged_filters_and_presentation(
    home: Path, monkeypatch: pytest.MonkeyPatch, owner: str | None
) -> None:
    ctx = Context.open(home)
    eid = ctx.descriptor.environment_id
    for run_id, who in (("a-local", "alice"), ("b-dup", "alice"), ("x-local", "sv")):
        ctx.create_run(
            make_record(
                run_id,
                owner=who,
                environment_id=eid,
                created_at=STAMP,
                status=RunStatus.RUNNING,
                task="toy-acc",
                tags=["team"],
            )
        )
    remote = [
        {
            **to_jsonable(
                make_record(
                    run_id,
                    owner=who,
                    created_at=STAMP,
                    status=RunStatus.RUNNING,
                    task="toy-acc",
                    tags=["team"],
                    hypothesis="hub version",
                )
            ),
            "host_state": "disabled",
        }
        for run_id, who in (("b-dup", "alice"), ("c-hub", "alice"), ("y-hub", "sv"))
    ]
    seen: list[tuple[str, dict[str, list[str]]]] = []
    # A different OS/local-owner name must never resolve --owner me.
    monkeypatch.setenv("USER", "sv")

    def hub(method: str, path: str, *args: Any, **kwargs: Any) -> Any:
        assert method == "GET"
        parts = urlsplit(path)
        query = parse_qs(parts.query)
        seen.append((parts.path, query))
        if parts.path == "/api/v1/auth/me":
            return {"auth": "on", "user": "alice"}
        assert parts.path == "/api/v1/runs"
        wanted = {
            "project": ["toy"],
            "task": ["toy-acc"],
            "status": ["running"],
            "tag": ["team"],
            "archived": ["true"],
            "limit": ["3"],
        }
        if owner is not None:
            wanted["owner"] = [owner]  # literal me, never rewritten to alice
        assert query == wanted
        resolved = "alice" if owner == "me" else owner
        return [r for r in remote if resolved is None or r["owner"] == resolved]

    monkeypatch.setattr(cli_main, "_hub", hub)
    args = [
        "--project",
        "toy",
        "--task",
        "toy-acc",
        "--status",
        "running",
        "--tag",
        "team",
        "--archived",
        "--limit",
        "3",
    ]
    if owner is not None:
        args += ["--owner", owner]
    result = rows(*args)
    expected = ["y-hub", "x-local", "c-hub"] if owner is None else ["c-hub", "b-dup", "a-local"]
    assert [r["run_id"] for r in result] == expected
    assert all("host_state" in r for r in result)
    assert all(
        r["host_state"] == (None if r["run_id"].endswith("local") else "disabled") for r in result
    )
    if owner is not None:
        assert result[1]["hypothesis"] == "hub version"  # hub wins duplicate
    assert sum(path == "/api/v1/auth/me" for path, _ in seen) == (owner == "me")
    monkeypatch.setattr(cli_main, "_local", lambda when: "LOCAL-TIME-SENTINEL")
    output = runner.invoke(cli_main.app, ["runs", *args], catch_exceptions=False)
    assert output.exit_code == 0
    assert "host disabled" in output.stdout and "LOCAL-TIME-SENTINEL" in output.stdout


@pytest.mark.parametrize("owner", [None, "alice"])
def test_local_owner_filter_without_hub(
    home: Path, monkeypatch: pytest.MonkeyPatch, owner: str | None
) -> None:
    ctx = Context.open(home)
    for run_id, who in (("a", "alice"), ("b", "sv")):
        ctx.create_run(make_record(run_id, owner=who, environment_id=ctx.descriptor.environment_id))

    def unavailable(method: str, path: str, *args: Any, **kwargs: Any) -> Any:
        assert path.startswith("/api/v1/runs")  # no /auth/me for named/no owner
        raise HubUnavailableError("offline")

    monkeypatch.setattr(cli_main, "_hub", unavailable)
    result = rows(*([] if owner is None else ["--owner", owner]))
    assert {r["run_id"] for r in result} == ({"a", "b"} if owner is None else {"a"})
    assert all(r["host_state"] is None for r in result)


def test_owner_me_auth_off_is_unfiltered(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = Context.open(home)
    # Historical owned rows also remain visible when auth is subsequently off.
    ctx.create_run(make_record("local", owner="sv", environment_id=ctx.descriptor.environment_id))
    called: list[str] = []

    def hub(method: str, path: str, *args: Any, **kwargs: Any) -> Any:
        called.append(path)
        if path == "/api/v1/auth/me":
            return {"auth": "off"}
        assert parse_qs(urlsplit(path).query)["owner"] == ["me"]
        return [{**to_jsonable(make_record("remote")), "host_state": "connected"}]

    monkeypatch.setattr(cli_main, "_hub", hub)
    assert {r["run_id"] for r in rows("--owner", "me")} == {"local", "remote"}
    assert len(called) == 2


def test_owner_me_without_identity_is_error(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(method: str, path: str, *args: Any, **kwargs: Any) -> Any:
        assert path == "/api/v1/auth/me"
        raise HubUnavailableError("offline")

    monkeypatch.setattr(cli_main, "_hub", unavailable)
    with pytest.raises(ConfigError, match="--owner me needs a hub"):
        rows("--owner", "me")
