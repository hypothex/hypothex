import json
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from hypothex.cli.main import app
from hypothex.core.errors import ConfigError
from hypothex.remote.service import (
    LAUNCHD_LABEL,
    install_service,
    serve_argv,
    service_file,
    uninstall_service,
)

runner = CliRunner()


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake $HOME, and a subprocess.run that fails the test if a service tool runs."""
    monkeypatch.setenv("HOME", str(tmp_path))
    real_run = subprocess.run

    def guarded(args: Any, *rest: Any, **kwargs: Any) -> Any:
        first = args[0] if isinstance(args, list | tuple) else str(args).split()[0]
        if Path(str(first)).name in {"systemctl", "launchctl", "loginctl"}:
            raise AssertionError(f"hx service ran {first}")
        return real_run(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded)
    return tmp_path


def test_systemd_unit(fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    hx_home = fake_home / "hx home"
    sf = install_service(hx_home, "ssh")
    path = fake_home / ".config" / "systemd" / "user" / "hypothex.service"
    assert sf.path == str(path) and path.read_text() == sf.text
    assert serve_argv(hx_home, "ssh") == [
        sys.executable,
        "-m",
        "hypothex.cli.main",
        "--home",
        str(hx_home),
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "0",
        "--kind",
        "ssh",
    ]
    lines = sf.text.splitlines()
    exec_line = next(line for line in lines if line.startswith("ExecStart="))
    assert shlex.split(exec_line.removeprefix("ExecStart=")) == serve_argv(hx_home, "ssh")
    assert f'Environment="HYPOTHEX_HOME={hx_home}"' in lines
    for line in ("[Service]", "Restart=on-failure", "WantedBy=default.target"):
        assert line in lines
    assert sf.enable == [
        'loginctl enable-linger "$USER"',
        "systemctl --user daemon-reload",
        "systemctl --user enable --now hypothex.service",
    ]


def test_launchd_plist(fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    hx_home = fake_home / "hx"
    sf = install_service(hx_home, None)
    path = fake_home / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
    assert sf.path == str(path)
    data = plistlib.loads(path.read_bytes())
    assert data["Label"] == LAUNCHD_LABEL
    assert data["ProgramArguments"] == serve_argv(hx_home, None)
    assert data["EnvironmentVariables"] == {"HYPOTHEX_HOME": str(hx_home)}
    assert data["RunAtLoad"] is True and data["KeepAlive"] == {"SuccessfulExit": False}
    assert data["StandardOutPath"] == str(hx_home / "serve" / "service.log")
    assert sf.enable == [f"launchctl bootstrap gui/$(id -u) {shlex.quote(str(path))}"]


def test_uninstall_removes_the_unit_and_its_wants_link(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    sf = install_service(fake_home / "hx", None)
    wants = Path(sf.path).parent / "default.target.wants" / "hypothex.service"
    wants.parent.mkdir()
    wants.symlink_to(sf.path)
    out, removed = uninstall_service(fake_home / "hx")
    assert removed and not Path(sf.path).exists() and not wants.is_symlink()
    assert out.disable == [
        "systemctl --user stop hypothex.service",
        "systemctl --user daemon-reload",
    ]
    assert uninstall_service(fake_home / "hx")[1] is False


def test_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ConfigError, match="win32"):
        service_file(Path("/tmp/hx"))


def test_cli_service_install_and_uninstall(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    hx_home = fake_home / "hxh"
    result = runner.invoke(
        app,
        ["--home", str(hx_home), "service", "install", "--kind", "slurm", "--json"],
        catch_exceptions=False,
    )
    out = json.loads(result.stdout)
    assert Path(out["path"]).is_file() and "--kind slurm" in out["text"]
    text = runner.invoke(app, ["--home", str(hx_home), "service", "uninstall"]).stdout
    assert "removed" in text and "systemctl --user stop hypothex.service" in text
    with pytest.raises(ConfigError, match="--kind"):
        runner.invoke(app, ["service", "install", "--kind", "gpu"], catch_exceptions=False)
