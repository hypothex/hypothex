"""Unit files that keep an env server running across reboots and logouts.

``hx service install`` writes a systemd user unit (Linux) or a launchd agent
(macOS) and prints the commands that enable it. Hypothex never runs
``systemctl``, ``loginctl``, or ``launchctl`` itself.

Examples
--------
>>> from pathlib import Path
>>> service_file(Path("/home/sv/.hypothex"), "slurm", "linux").path.endswith(
...     ".config/systemd/user/hypothex.service")
True
"""

from __future__ import annotations

import plistlib
import shlex
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from hypothex.core.errors import ConfigError
from hypothex.core.fsutil import atomic_write_text

Platform = Literal["linux", "darwin"]
SYSTEMD_UNIT = "hypothex.service"
LAUNCHD_LABEL = "dev.hypothex.serve"


class ServiceFile(BaseModel):
    """
    A unit file and the shell commands the user runs around it.

    Attributes
    ----------
    platform : Platform
    path : str
        Where the file goes.
    text : str
        File contents.
    enable : list of str
        Commands to run after install.
    disable : list of str
        Commands that stop the running server after uninstall.
    """

    platform: Platform
    path: str
    text: str
    enable: list[str]
    disable: list[str]


def current_platform() -> Platform:
    """
    Return the service platform of this machine.

    Returns
    -------
    Platform

    Raises
    ------
    ConfigError
        On anything but Linux or macOS.
    """
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    raise ConfigError(
        f"hx service supports Linux (systemd) and macOS (launchd), not {sys.platform}"
    )


def serve_argv(home: Path, kind: str | None) -> list[str]:
    """
    Return the ``hx serve`` command the service runs (this Python, this home).

    Parameters
    ----------
    home : Path
        Hypothex home of the env server.
    kind : str or None
        ``ssh`` or ``slurm``.

    Returns
    -------
    list of str
    """
    argv = [
        sys.executable,
        "-m",
        "hypothex.cli.main",
        "--home",
        str(home),
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "0",
    ]
    if kind is not None:
        argv += ["--kind", kind]
    return argv


def unit_path(platform: Platform) -> Path:
    """
    Return where the unit file goes.

    Parameters
    ----------
    platform : Platform

    Returns
    -------
    Path
        ``~/.config/systemd/user/hypothex.service`` or
        ``~/Library/LaunchAgents/dev.hypothex.serve.plist``.
    """
    if platform == "linux":
        return Path.home() / ".config" / "systemd" / "user" / SYSTEMD_UNIT
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def systemd_unit(argv: list[str], home: Path) -> str:
    """
    Render the systemd user unit.

    Parameters
    ----------
    argv : list of str
        Command to run.
    home : Path
        Value of ``HYPOTHEX_HOME``.

    Returns
    -------
    str
    """
    exec_start = shlex.join(argv).replace("%", "%%")
    return (
        "[Unit]\n"
        "Description=Hypothex env server\n"
        "After=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exec_start}\n"
        f'Environment="HYPOTHEX_HOME={home}"\n'
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def launchd_plist(argv: list[str], home: Path) -> str:
    """
    Render the launchd agent.

    Parameters
    ----------
    argv : list of str
        Command to run.
    home : Path
        Value of ``HYPOTHEX_HOME``; the log goes to ``<home>/serve/service.log``.

    Returns
    -------
    str
    """
    log = str(home / "serve" / "service.log")
    return plistlib.dumps(
        {
            "Label": LAUNCHD_LABEL,
            "ProgramArguments": argv,
            "EnvironmentVariables": {"HYPOTHEX_HOME": str(home)},
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "StandardOutPath": log,
            "StandardErrorPath": log,
        }
    ).decode("utf-8")


def service_file(
    home: Path, kind: str | None = None, platform: Platform | None = None
) -> ServiceFile:
    """
    Build (not write) the unit file for this machine.

    Parameters
    ----------
    home : Path
    kind : str or None
    platform : Platform, optional
        Default: ``current_platform()``.

    Returns
    -------
    ServiceFile
    """
    platform = platform or current_platform()
    argv = serve_argv(home, kind)
    path = unit_path(platform)
    if platform == "linux":
        return ServiceFile(
            platform=platform,
            path=str(path),
            text=systemd_unit(argv, home),
            enable=[
                'loginctl enable-linger "$USER"',
                "systemctl --user daemon-reload",
                f"systemctl --user enable --now {SYSTEMD_UNIT}",
            ],
            disable=[f"systemctl --user stop {SYSTEMD_UNIT}", "systemctl --user daemon-reload"],
        )
    return ServiceFile(
        platform=platform,
        path=str(path),
        text=launchd_plist(argv, home),
        enable=[f"launchctl bootstrap gui/$(id -u) {shlex.quote(str(path))}"],
        disable=[f"launchctl bootout gui/$(id -u)/{LAUNCHD_LABEL}"],
    )


def install_service(
    home: Path, kind: str | None = None, platform: Platform | None = None
) -> ServiceFile:
    """
    Write the unit file; the caller prints ``enable`` for the user to run.

    Parameters
    ----------
    home : Path
    kind : str or None
    platform : Platform, optional

    Returns
    -------
    ServiceFile
    """
    sf = service_file(home, kind, platform)
    atomic_write_text(Path(sf.path), sf.text)
    return sf


def uninstall_service(home: Path, platform: Platform | None = None) -> tuple[ServiceFile, bool]:
    """
    Remove the unit file (and systemd's ``default.target.wants`` link).

    Parameters
    ----------
    home : Path
    platform : Platform, optional

    Returns
    -------
    tuple of (ServiceFile, bool)
        The service description (``disable`` stops the running server) and
        whether a file was removed.
    """
    sf = service_file(home, None, platform)
    path = Path(sf.path)
    removed = path.is_file()
    path.unlink(missing_ok=True)
    if sf.platform == "linux":
        wants = path.parent / "default.target.wants" / SYSTEMD_UNIT
        if wants.is_symlink():
            wants.unlink()
    return sf, removed
