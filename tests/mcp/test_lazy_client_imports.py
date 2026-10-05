"""Import boundaries and logging side effects of the MCP SDK."""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import hypothex.cli.main as cli
import hypothex.mcp.server as server


def test_cli_hub_helpers_do_not_import_external_mcp_sdk(home: Path) -> None:
    code = """
import sys
from hypothex.cli import main
from hypothex.mcp.server import acts_through_hub, hub_call, resolve_hub_token
loaded = sorted(k for k in sys.modules if k == 'mcp' or k.startswith('mcp.'))
assert not loaded, loaded
"""
    process = subprocess.run(
        [sys.executable, "-c", code], env=dict(os.environ), capture_output=True, text=True
    )
    assert process.returncode == 0, process.stderr


def test_sdk_logging_does_not_enable_http_debug_noise(
    home: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import mcp.server.mcpserver as sdk

    actual_init = sdk.MCPServer.__init__
    constructed: list[sdk.MCPServer] = []
    loggers = [logging.getLogger("httpx"), logging.getLogger("httpcore")]
    levels = [log.level for log in loggers]

    def noisy_init(instance: sdk.MCPServer, *args: Any, **kwargs: Any) -> None:
        actual_init(instance, *args, **kwargs)
        constructed.append(instance)
        for log in loggers:
            log.setLevel(logging.INFO)

    # Preserve the SDK class so the lazy caller-aware implementation can subclass it.
    monkeypatch.setattr(sdk.MCPServer, "__init__", noisy_init)
    try:
        built = server.build_server(home)
        assert constructed == [built]
        assert all(log.level == logging.WARNING for log in loggers)
        with caplog.at_level(logging.WARNING, logger="hypothex.test"):
            logging.getLogger("hypothex.test").warning("application warning remains")
        assert "application warning remains" in caplog.text
    finally:
        for log, level in zip(loggers, levels, strict=True):
            log.setLevel(level)


@pytest.mark.parametrize("kind", ["local", "ssh", "slurm"])
def test_environment_server_disables_access_logging(
    kind: str, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uvicorn

    configs: list[Any] = []

    def run(instance: Any, sockets: list[Any] | None = None) -> None:
        configs.append(instance.config)
        for sock in sockets or []:
            sock.close()

    monkeypatch.setattr(uvicorn.Server, "run", run)
    result = CliRunner().invoke(
        cli.app, ["serve", "--kind", kind, "--port", "0"], catch_exceptions=False
    )
    assert result.exit_code == 0 and len(configs) == 1
    assert configs[0].access_log is False
