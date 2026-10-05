import json
import os
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hypothex.cli import main
from hypothex.core.errors import ConfigError


@pytest.mark.parametrize("kind", ["local", "ssh", "slurm", None])
def test_all_serve_kinds_generate_fresh_tokens(
    kind: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HYPOTHEX_SERVE_TOKEN", raising=False)
    first = main._serve_token("127.0.0.1", kind, False)
    second = main._serve_token("0.0.0.0", kind, False)
    assert first and second and len(first) == 48 and first != second


@pytest.mark.parametrize(
    "value", ["", "secret\r\nvalue", "space value", "ésecret", "token!", "x" * 4097]
)
def test_explicit_token_invalid_is_fixed_nonsecret_error(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYPOTHEX_SERVE_TOKEN", value)
    with pytest.raises(
        ConfigError, match="^invalid bearer token: expected 1..4096 ASCII bearer characters$"
    ):
        main._serve_token("127.0.0.1", "local", False)
    assert "HYPOTHEX_SERVE_TOKEN" not in os.environ


def record(home: Path) -> dict[str, object]:
    from hypothex.core.environment import load_descriptor
    from hypothex.core.execution import process_create_time
    from hypothex.core.layout import Layout

    identity = load_descriptor(Layout(home)).model_dump()
    body = {
        "pid": os.getpid(),
        "pid_create_time": process_create_time(os.getpid()),
        "hostname": socket.gethostname(),
        "home": str(home.resolve()),
        "environment_id": identity["environment_id"],
        "token": "synthetic-owner-token",
        "host": "192.0.2.1",
    }
    (home / "serve").mkdir(exist_ok=True)
    (home / "serve" / "server.json").write_text(json.dumps(body))
    return body


def test_token_command_reads_only_selected_local_home(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    def network_forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("network called")

    monkeypatch.setattr(httpx, "get", network_forbidden)
    record(home)
    result = CliRunner().invoke(main.app, ["--home", str(home), "token"], catch_exceptions=False)
    assert result.exit_code == 0 and result.stdout == "synthetic-owner-token\n"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("pid_create_time", 0.0),
        ("pid_create_time", None),
        ("hostname", "foreign"),
        ("home", "/tmp/other-home"),
        ("environment_id", "foreign"),
        ("token", None),
        ("token", "bad secret"),
    ],
)
def test_token_command_rejects_untrusted_record(home: Path, key: str, value: object) -> None:
    body = record(home)
    body[key] = value
    (home / "serve" / "server.json").write_text(json.dumps(body))
    with pytest.raises(ConfigError) as exc:
        CliRunner().invoke(main.app, ["--home", str(home), "token"], catch_exceptions=False)
    assert "synthetic-owner-token" not in str(exc.value)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("pid", True),
        ("pid", -1),
        ("pid", 10**200),
        ("pid_create_time", True),
        ("pid_create_time", 10**2000),
        ("pid_create_time", float("nan")),
    ],
)
def test_token_rejects_malformed_numeric_identity(home: Path, key: str, value: object) -> None:
    body = record(home)
    body[key] = value
    (home / "serve" / "server.json").write_text(json.dumps(body))
    with pytest.raises(ConfigError, match="no verifiable"):
        main.local_server_token(home)


@pytest.mark.parametrize("failure", ["birth-change", "dead", "zombie", "denied"])
def test_token_rejects_unverifiable_process(
    home: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import psutil

    body = record(home)
    if failure == "birth-change":
        monkeypatch.setattr(main, "process_create_time", lambda pid: body["pid_create_time"] + 0.01)
    elif failure == "dead":
        monkeypatch.setattr(main, "process_create_time", lambda pid: None)
    elif failure == "zombie":
        monkeypatch.setattr(main, "process_alive", lambda pid, birth: False)
    else:

        def denied(pid: int) -> float | None:
            raise psutil.AccessDenied(pid)

        monkeypatch.setattr(main, "process_create_time", denied)
    with pytest.raises(ConfigError, match="no verifiable"):
        main.local_server_token(home)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "::1", "192.0.2.1"])
def test_token_ignores_remote_configuration_and_bind(
    home: Path, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    body = record(home)
    body["host"] = host
    (home / "serve" / "server.json").write_text(json.dumps(body))
    monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", "not-the-owner")
    monkeypatch.setenv("HYPOTHEX_HUB_URL", "https://do-not-contact.invalid")
    assert main.local_server_token(home) == body["token"]


def test_token_supported_legacy_birth(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    body = record(home)
    del body["pid_create_time"]
    body["pid_start"] = "Mon Oct  5 02:11:12 2026"
    (home / "serve" / "server.json").write_text(json.dumps(body))

    def ps(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args == ["ps", "-p", str(body["pid"]), "-o", "lstart="]
        return subprocess.CompletedProcess(args, 0, stdout=body["pid_start"] + "\n")

    monkeypatch.setattr(subprocess, "run", ps)
    assert main.local_server_token(home) == body["token"]


def test_direct_create_app_rejects_bad_token_before_context(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex.api import app as api

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("created context before validation")

    monkeypatch.setattr(api.Context, "open", forbidden)
    with pytest.raises(ConfigError, match="invalid bearer token"):
        api.create_app(home, auth_token="synthetic\r\nsecret")


def test_noauth_explicitly_ignores_and_removes_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPOTHEX_SERVE_TOKEN", "malformed ignored\nsecret")
    assert main._serve_token("127.0.0.1", "local", True) is None
    assert "HYPOTHEX_SERVE_TOKEN" not in os.environ


def test_token_missing_or_malformed_record_never_uses_env(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYPOTHEX_HUB_TOKEN", "not-selected")
    with pytest.raises(ConfigError):
        main.local_server_token(home)
    body = record(home)
    path = home / "serve" / "server.json"
    for text in [
        "[]",
        "bad json",
        '{"token":"synthetic-owner-token"}',
        json.dumps({**body, "pid": 0}),
    ]:
        path.write_text(text)
        with pytest.raises(ConfigError) as failure:
            main.local_server_token(home)
        assert "synthetic-owner-token" not in str(failure.value)
