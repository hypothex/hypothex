"""
Session-wide network guard: tests reach loopback only (HARD RULE).

``tests/conftest.py`` installs it in ``pytest_configure`` (before any module or
session fixture) and again for every test. A connect, a name lookup, or a
``psycopg`` connection to anything but a loopback address raises
``NetworkBlockedError``, so no test can reach a real Slack workspace, SMTP
server, Postgres server, or tailnet by mistake. ``psycopg`` talks through
libpq (C), so its connect functions are wrapped separately.

Examples
--------
>>> allowed_address("127.0.0.1"), allowed_address("hooks.slack.com")
(True, False)
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

SECRET_VARS = (
    "HYPOTHEX_SLACK_WEBHOOK",
    "HYPOTHEX_SMTP_PASSWORD",
    "HYPOTHEX_INDEX_PASSWORD",
    "HYPOTHEX_HUB_TOKEN",
)
"""Secret variables no test may inherit from the developer's shell."""
LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_GETADDRINFO = socket.getaddrinfo
_PSYCOPG: dict[str, Any] = {}
_TAILSCALE_STUB = "#!/bin/sh\necho 'hypothex tests: real tailscale is blocked' >&2\nexit 255\n"


class NetworkBlockedError(OSError):
    """A test tried to reach an address that is not loopback."""


def allowed_address(host: object) -> bool:
    """
    Tell whether a test may connect to (or look up) ``host``.

    Parameters
    ----------
    host : object
        A host name, an IP literal, ``None`` (a wildcard lookup), or bytes.

    Returns
    -------
    bool
        True for ``None``, ``""``, the loopback names, and loopback or
        unspecified IP addresses; False for every other name and address.

    Examples
    --------
    >>> [allowed_address(h) for h in ("::1", "0.0.0.0", None, "203.0.113.1", "db.lab")]
    [True, True, True, False, False]
    """
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    name = host.strip().strip("[]").split("%", 1)[0].lower()
    if name == "" or name in LOCAL_NAMES:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _blocked(host: object) -> NetworkBlockedError:
    return NetworkBlockedError(f"tests never reach the network: {host!r} is blocked")


def _connect(self: socket.socket, address: Any) -> None:
    if self.family in (socket.AF_INET, socket.AF_INET6) and not allowed_address(address[0]):
        raise _blocked(address[0])
    _REAL_CONNECT(self, address)


def _connect_ex(self: socket.socket, address: Any) -> int:
    if self.family in (socket.AF_INET, socket.AF_INET6) and not allowed_address(address[0]):
        return 111  # ECONNREFUSED: connect_ex reports errors as numbers
    return _REAL_CONNECT_EX(self, address)


def _getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    if not allowed_address(host):
        raise _blocked(host)
    return _REAL_GETADDRINFO(host, *args, **kwargs)


def scrub_pg_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Remove every PostgreSQL environment default before fixtures run.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Session or test patch owner. Includes connection, service, password-file,
        TLS and future PG-prefixed variables without maintaining a partial list.
    """
    for name in tuple(os.environ):
        if name.startswith("PG"):
            monkeypatch.delenv(name, raising=False)


def pg_child_environment(environment: dict[str, str]) -> dict[str, str]:
    """
    Copy a child environment without any PostgreSQL defaults.

    Parameters
    ----------
    environment : dict[str, str]
        Parent environment plus scenario overrides, neither of which is mutated.

    Returns
    -------
    dict[str, str]
        Fresh mapping; fixtures pass synthetic database credentials explicitly.

    Examples
    --------
    >>> pg_child_environment({"PGHOSTADDR": "203.0.113.1", "USER": "sv"})
    {'USER': 'sv'}
    """
    return {name: value for name, value in environment.items() if not name.startswith("PG")}


def _psycopg_parameters(conninfo: str, kwargs: dict[str, Any]) -> dict[str, str]:
    from psycopg.conninfo import conninfo_to_dict

    # These are Python connection options, not libpq parameters. None-valued
    # conninfo overrides are ignored by the documented psycopg parser.
    options = {"autocommit", "prepare_threshold", "context", "row_factory", "cursor_factory"}
    parsed = conninfo_to_dict(conninfo, **{k: v for k, v in kwargs.items() if k not in options})
    params = {key: str(value) for key, value in parsed.items() if value is not None}
    # No ambient PG configuration is allowed in tests. Reject even a safe new
    # default: fixtures must pass explicit values. Do not print secret values.
    ambient = sorted(name for name in os.environ if name.startswith("PG"))
    if ambient:
        raise NetworkBlockedError("tests block PG defaults: " + ", ".join(ambient))
    if "service" in params:
        raise NetworkBlockedError("tests never resolve PostgreSQL services: service blocked")
    params.setdefault("host", "/tmp")  # intentional macOS/Linux test-only socket default
    for key in ("host", "hostaddr"):
        if key not in params:
            continue
        pinned: list[str] = []
        for host in params[key].split(","):
            if not host:
                pinned.append("/tmp" if key == "host" else "")
                continue
            if key == "host" and host.startswith("/"):
                pinned.append(host)  # absolute local Unix socket directory
                continue
            if key == "host" and host.lower() in LOCAL_NAMES:
                host = "::1" if host.lower() == "ip6-localhost" else "127.0.0.1"
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                raise _blocked(host) from None
            if not address.is_loopback:
                raise _blocked(host)
            pinned.append(str(address))
        params[key] = ",".join(pinned)
    return params


def _guard_psycopg(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        import psycopg
    except ImportError:
        return
    if not _PSYCOPG:
        _PSYCOPG["connect"] = psycopg.Connection.__dict__["connect"]
    real: Callable[..., Any] = _PSYCOPG["connect"].__func__

    def guarded(cls: type, conninfo: str = "", **kwargs: Any) -> Any:
        params = _psycopg_parameters(conninfo, kwargs)
        # Pin validated host aliases before real preprocessing; no local-name DNS
        # or unvalidated kwargs override can change the accepted destinations.
        destinations = {key: params[key] for key in ("host", "hostaddr") if key in params}
        return real(cls, conninfo, **{**kwargs, **destinations})

    def connect(conninfo: str = "", **kwargs: Any) -> Any:
        return psycopg.Connection.connect(conninfo, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "connect", classmethod(guarded))
    monkeypatch.setattr(psycopg, "connect", connect)


def guard_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Refuse every non-loopback connect, lookup, and Postgres connection.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        The patches are undone with it (a session ``MonkeyPatch`` is never undone).
    """
    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    _guard_psycopg(monkeypatch)


def refuse_tailscale(base: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Point ``HYPOTHEX_TAILSCALE`` at a stub that always fails.

    Parameters
    ----------
    base : Path
        Directory for the stub (created if missing).
    monkeypatch : pytest.MonkeyPatch
        Used to set the variable.

    Returns
    -------
    Path
        The stub.
    """
    base.mkdir(parents=True, exist_ok=True)
    stub = base / "tailscale-refuse"
    if not stub.exists():
        stub.write_text(_TAILSCALE_STUB)
        stub.chmod(0o755)
    monkeypatch.setenv("HYPOTHEX_TAILSCALE", str(stub))
    return stub
