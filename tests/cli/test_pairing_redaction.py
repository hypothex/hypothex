"""Pairing credentials stay out of failed CLI responses and HTTP diagnostics."""

from __future__ import annotations

import json
import logging
import sys
import threading
import traceback
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from hypothex.auth.pairing import pairing_url
from hypothex.cli import main as cli_main
from hypothex.core.errors import HypothexError
from hypothex.core.layout import Layout
from hypothex.remote.config import EnvironmentsFile, HostSpec, save_hosts

SECRET = "SYNTHETIC_PAIRING_SECRET_" + "x" * 18
OFFER = "p_0123456789ab"


@pytest.fixture
def http_debug_logging(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Enable actual wire diagnostics even after SDK tests disable shared loggers."""
    caplog.set_level(logging.DEBUG)
    previous_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "disabled", False)
        monkeypatch.setattr(logger, "propagate", True)
        caplog.set_level(logging.DEBUG, logger=name)
    try:
        yield
    finally:
        logging.disable(previous_disable)


@pytest.fixture(params=["message", "structured", "non-json"])
def reflecting_hub(request: pytest.FixtureRequest) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Return a loopback peer reflecting the submitted secret in body and wire metadata."""
    captured: list[dict[str, Any]] = []
    kind = request.param

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler interface
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append({"path": self.path, "body": body, "headers": dict(self.headers)})
            secret = body["secret"]
            if kind == "message":
                reply = json.dumps({"error": f"invalid pairing {secret}; secret={secret}"})
            elif kind == "structured":
                reply = json.dumps({"error": {"invalid": secret}})
            else:
                reply = f"invalid response for {secret}"
            wire = reply.encode("utf-8")
            self.send_response(400, secret)
            self.send_header("X-Diagnostic", secret)
            self.send_header("Content-Length", str(len(wire)))
            self.end_headers()
            self.wfile.write(wire)

        def log_message(self, format: str, *args: Any) -> None:
            """Keep the fake peer's deliberate reflection out of client log capture."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield base, captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def assert_private_diagnostics(
    captured: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    """Verify transport secrecy without accepting a disabled logging false positive."""
    assert len(captured) == 1
    assert captured[0]["body"]["secret"] == SECRET
    assert captured[0]["path"] == "/api/v1/auth/pair"
    assert all(SECRET not in value for value in captured[0]["headers"].values())
    assert "receive_response_headers.complete" in caplog.text
    assert "[redacted]" in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.usefixtures("http_debug_logging")
def test_failed_pairing_traceback_redacts_secret(
    reflecting_hub: tuple[str, list[dict[str, Any]]], caplog: pytest.LogCaptureFixture
) -> None:
    """A failed response never puts the pairing secret in its exception chain."""
    base, captured = reflecting_hub
    with pytest.raises(HypothexError) as failure:
        cli_main._redeem(pairing_url(base, OFFER, SECRET), "cli", "test")
    assert SECRET not in "".join(traceback.format_exception(failure.value))
    assert_private_diagnostics(captured, caplog)


@pytest.mark.parametrize("command", ["login", "hosts_pair"])
@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.usefixtures("http_debug_logging")
def test_failed_pairing_cli_output_and_debug_logs_never_expose_secret(
    reflecting_hub: tuple[str, list[dict[str, Any]]],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
    as_json: bool,
) -> None:
    """The real console entrypoint sanitizes login and host-pair text/JSON failures."""
    base, captured = reflecting_hub
    link = pairing_url(base, OFFER, SECRET)
    home = tmp_path / "home"
    if command == "login":
        args = ["login", link]
    else:
        save_hosts(
            Layout(home), EnvironmentsFile(environments={"lab": HostSpec(route="url", url=base)})
        )
        args = ["hosts", "pair", "lab", link]
    if as_json:
        args.append("--json")
    monkeypatch.setattr(sys, "argv", ["hx", "--home", str(home), *args])
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    with pytest.raises(SystemExit) as failure:
        cli_main.cli()
    assert failure.value.code == 1
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    if as_json:
        assert json.loads(output.out)["type"] == "HypothexError"
    else:
        assert "error:" in output.err
    assert_private_diagnostics(captured, caplog)
    assert not (home / "auth" / "hub-tokens.json").exists()
    assert not (home / "auth" / "host-tokens.json").exists()
