"""Exercise the imported guard with inert driver, socket, and DNS boundaries."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from tests.fakes import network


class _BoundaryReached(Exception):
    """Stop before the driver generator can enter libpq connection I/O."""


@pytest.fixture
def inert(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Install the inert boundary before invoking or reinstalling the guard.

    Returns
    -------
    list of dict
        Actual conninfo passed to the installed driver's connection generator.
    """
    calls: list[dict[str, Any]] = []

    def stop(cls: type, conninfo: str) -> NoReturn:
        calls.append(conninfo_to_dict(conninfo))
        raise _BoundaryReached

    def no_io(*args: Any, **kwargs: Any) -> NoReturn:
        raise AssertionError("PostgreSQL probes must not perform socket or DNS I/O")

    monkeypatch.setattr(psycopg.Connection, "_connect_gen", classmethod(stop))
    for name in ("_REAL_CONNECT", "_REAL_CONNECT_EX", "_REAL_GETADDRINFO"):
        monkeypatch.setattr(network, name, no_io)
    monkeypatch.setattr(socket.socket, "connect", no_io)
    monkeypatch.setattr(socket.socket, "connect_ex", no_io)
    monkeypatch.setattr(socket, "getaddrinfo", no_io)
    network.guard_network(monkeypatch)
    return calls


@pytest.mark.parametrize("api", ["module", "class"])
@pytest.mark.parametrize(
    ("conninfo", "kwargs"),
    [
        ("host=203.0.113.5", {}),
        ("host=db.example.org", {}),
        ("host=2001:db8::1", {}),
        ("host=127.0.0.1 hostaddr=203.0.113.5", {}),
        ("host=127.0.0.1 hostaddr=2001:db8::1", {}),
        ("host=db.example.org hostaddr=127.0.0.1", {}),
        ("host=127.0.0.1 hostaddr=/tmp", {}),
        ("host=0.0.0.0", {}),
        ("host=::", {}),
        ("host=127.0.0.1 hostaddr=0.0.0.0", {}),
        ("host=127.0.0.1,203.0.113.5", {}),
        ("host=localhost,localhost hostaddr=127.0.0.1,203.0.113.5", {}),
        ("host=localhost,db.example.org hostaddr=127.0.0.1,", {}),
        ("service=synthetic", {}),
        ("", {"service": ""}),
        ("postgresql://hx@localhost/synthetic?service=", {}),
        ("host=localhost service=synthetic", {"service": None}),
        ("host=127.0.0.1", {"host": "203.0.113.5"}),
        ("host=127.0.0.1", {"hostaddr": "203.0.113.5"}),
        ("host=203.0.113.5", {"host": None}),
        ("hostaddr=203.0.113.5", {"hostaddr": None}),
        ("host=127.0.0.1 host=203.0.113.5", {}),
        ("host=127.0.0.1", {"host": "127.1"}),
        ("host=127.0.0.1", {"host": "[::1]"}),
        ("postgresql://hx:synthetic@127.0.0.1/db?hostaddr=203.0.113.5", {}),
    ],
)
def test_forbidden_destinations_never_reach_driver(
    inert: list[dict[str, Any]], api: str, conninfo: str, kwargs: dict[str, Any]
) -> None:
    """Reject every effective destination before the first driver attempt."""
    connect = psycopg.connect if api == "module" else psycopg.Connection.connect
    with pytest.raises(network.NetworkBlockedError) as error:
        connect(conninfo, password="synthetic-secret", **kwargs)
    assert "synthetic-secret" not in str(error.value)
    assert inert == []


@pytest.mark.parametrize("api", ["module", "class"])
@pytest.mark.parametrize(
    ("conninfo", "kwargs", "expected"),
    [
        ("host=127.0.0.1", {}, {"host": "127.0.0.1", "hostaddr": "127.0.0.1"}),
        ("host=::1", {}, {"host": "::1"}),
        ("host=localhost", {}, {"host": "127.0.0.1", "hostaddr": "127.0.0.1"}),
        ("host=localhost.localdomain", {}, {"host": "127.0.0.1", "hostaddr": "127.0.0.1"}),
        ("host=ip6-localhost", {}, {"host": "::1"}),
        ("", {}, {"host": "/tmp"}),
        ("host=''", {}, {"host": "/tmp"}),
        ("host=/tmp/synthetic", {}, {"host": "/tmp/synthetic"}),
        ("host=,127.0.0.1", {}, {"host": "/tmp"}),
        ("host=127.0.0.1,", {}, {"host": "127.0.0.1", "hostaddr": "127.0.0.1"}),
        ("host=localhost,/tmp/s hostaddr=,::1", {}, {"host": "127.0.0.1", "hostaddr": "127.0.0.1"}),
        ("host=/tmp/s,localhost hostaddr=::1,", {}, {"host": "/tmp/s", "hostaddr": "::1"}),
        ("host=203.0.113.5", {"host": "127.0.0.1"}, {"host": "127.0.0.1", "hostaddr": "127.0.0.1"}),
        ("host=127.0.0.1", {"host": None}, {"host": "127.0.0.1", "hostaddr": "127.0.0.1"}),
        ("hostaddr=203.0.113.5", {"hostaddr": ""}, {"host": "/tmp", "hostaddr": ""}),
        ("host=203.0.113.5 host=127.0.0.1", {}, {"host": "127.0.0.1", "hostaddr": "127.0.0.1"}),
        (
            "postgresql://hx@203.0.113.5/db",
            {"host": "localhost", "hostaddr": "::1"},
            {"host": "127.0.0.1", "hostaddr": "::1"},
        ),
    ],
)
def test_safe_destinations_reach_only_inert_driver(
    inert: list[dict[str, Any]],
    api: str,
    conninfo: str,
    kwargs: dict[str, Any],
    expected: dict[str, str],
) -> None:
    """Retain parser precedence and inspect numeric or Unix destinations after preprocessing."""
    connect = psycopg.connect if api == "module" else psycopg.Connection.connect
    with pytest.raises(_BoundaryReached):
        connect(conninfo, dbname="synthetic", autocommit=True, prepare_threshold=None, **kwargs)
    assert len(inert) == 1
    assert {key: inert[0][key] for key in ("host", "hostaddr") if key in inert[0]} == expected


def _pg_names() -> list[str]:
    """Return libpq's documented defaults and file, future, and prefix edge cases."""
    names = {
        option.envvar.decode() for option in psycopg.pq.Conninfo.get_defaults() if option.envvar
    }
    return sorted(names | {"PGSERVICEFILE", "PGSYSCONFDIR", "PGPASSFILE", "PG", "PGFUTURE"})


@pytest.mark.parametrize("name", _pg_names())
@pytest.mark.parametrize("value", ["", "synthetic-secret", "127.0.0.1"])
def test_every_reintroduced_pg_name_is_rejected(
    inert: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    """Presence alone blocks ambient defaults and reports names without values."""
    monkeypatch.setenv(name, value)
    for connect in (psycopg.connect, psycopg.Connection.connect):
        for conninfo in ("dbname=synthetic", "host=127.0.0.1"):
            with pytest.raises(network.NetworkBlockedError) as error:
                connect(conninfo)
            assert str(error.value) == "tests block PG defaults: " + name
    assert inert == []


@pytest.mark.parametrize("service", ["", "synthetic"])
def test_disposable_service_files_cannot_select_a_destination(
    inert: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, service: str
) -> None:
    """Empty PGSERVICE selects [] in libpq; the guard refuses it before connection I/O."""
    (tmp_path / ".pg_service.conf").write_text(f"[{service}]\nhostaddr=203.0.113.77\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PGSERVICE", service)
    defaults = {
        o.keyword.decode(): (o.val or b"").decode() for o in psycopg.pq.Conninfo.get_defaults()
    }
    assert defaults["hostaddr"] == "203.0.113.77"
    for connect in (psycopg.connect, psycopg.Connection.connect):
        with pytest.raises(network.NetworkBlockedError, match="PGSERVICE"):
            connect(dbname="synthetic")
    assert inert == []


def test_repeated_guard_installation(
    inert: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reinstalling the guard preserves both APIs without recursive wrappers."""
    network.guard_network(monkeypatch)
    network.guard_network(monkeypatch)
    for connect in (psycopg.connect, psycopg.Connection.connect):
        with pytest.raises(_BoundaryReached):
            connect(host="127.0.0.1")
    assert len(inert) == 2


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        (None, True),
        ("", True),
        ("localhost", True),
        (b"::1", True),
        ("127.0.0.2", True),
        ("0.0.0.0", True),
        ("::", True),
        ("[::1]", True),
        ("::1%lo0", True),
        ("203.0.113.1", False),
        ("db.example.org", False),
        (42, False),
        (b"\xff", False),
    ],
)
def test_allowed_address(host: object, expected: bool) -> None:
    """The socket allowlist admits local bind addresses and rejects external ones."""
    assert network.allowed_address(host) is expected


def test_scrub_and_final_child_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip all PG keys after overrides, preserving synthetic explicit fixture values."""
    for name in _pg_names():
        monkeypatch.setenv(name, "")
    network.scrub_pg_environment(monkeypatch)
    assert not any(name.startswith("PG") for name in os.environ)
    parent = {"USER": "runner", "PGHOSTADDR": "203.0.113.1", "PGSERVICE": ""}
    overrides = {
        "PGHOST": "db.example.org",
        "PGPASSWORD": "synthetic",
        "HYPOTHEX_INDEX_PASSWORD": "synthetic-explicit",
        "HOME": "/synthetic",
    }
    before = (dict(parent), dict(overrides))
    final = network.pg_child_environment({**parent, **overrides})
    assert final == {
        "USER": "runner",
        "HOME": "/synthetic",
        "HYPOTHEX_INDEX_PASSWORD": "synthetic-explicit",
    }
    assert before == (parent, overrides)
    assert final is not parent and final is not overrides
    child = subprocess.run(
        [sys.executable, "-c", "import json, os; print(json.dumps(dict(os.environ)))"],
        env=final,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    received = json.loads(child.stdout)
    assert not any(name.startswith("PG") for name in received)
    assert all(received[key] == value for key, value in final.items())


_CHILD_TESTS = """
import os
import psycopg
import pytest
from tests.fakes import network

class Stop(Exception):
    pass

@pytest.fixture(scope="module")
def session_state():
    return [name for name in os.environ if name.startswith("PG") or name in network.SECRET_VARS]

@pytest.fixture(autouse=True)
def inert(monkeypatch):
    def stop(cls, conninfo):
        raise Stop
    monkeypatch.setattr(psycopg.Connection, "_connect_gen", classmethod(stop))

def test_a_session_and_late_default(session_state):
    assert session_state == []
    # Deliberately persist beyond this test: the next autouse scrub must remove it.
    os.environ["PGSERVICE"] = ""
    os.environ["HYPOTHEX_SMTP_PASSWORD"] = "synthetic-late"
    with pytest.raises(network.NetworkBlockedError):
        psycopg.connect(host="127.0.0.1")

def test_b_per_test_scrub():
    assert not any(name.startswith("PG") or name in network.SECRET_VARS for name in os.environ)
    with pytest.raises(Stop):
        psycopg.Connection.connect(host="127.0.0.1")
"""


def test_actual_pytest_bootstrap_scrubs_inherited_and_late_defaults(tmp_path: Path) -> None:
    """Run unchanged repository hooks with deliberately contaminated synthetic child input."""
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "conftest.py").write_text((root / "tests/conftest.py").read_text())
    (tmp_path / "test_child.py").write_text(_CHILD_TESTS)
    environment = network.pg_child_environment(dict(os.environ))
    environment.update(
        {
            "PYTHONPATH": str(root),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PGSERVICE": "",
            "PGHOSTADDR": "203.0.113.8",
            "PGHOST": "",
            "PGPASSWORD": "synthetic-inherited",
        }
    )
    environment.update(dict.fromkeys(network.SECRET_VARS, "synthetic-inherited"))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
    assert "synthetic-inherited" not in result.stdout + result.stderr


def test_runtime_boundary_identity(record_property: Any) -> None:
    """Record actual installed driver versions and imported implementation path in JUnit."""
    record_property("psycopg", psycopg.__version__)
    record_property("libpq", psycopg.pq.version())
    record_property("network_module", str(Path(network.__file__).resolve()))
    record_property("boundary", "Connection._connect_gen intercepted before libpq connection I/O")
    assert Path(network.__file__).resolve() == Path(__file__).resolve().parent / "fakes/network.py"
    assert json.dumps({"psycopg": psycopg.__version__, "libpq": psycopg.pq.version()})


@pytest.mark.parametrize("api", ["module", "class"])
def test_all_safe_multihost_attempts_are_pinned(
    inert: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, api: str
) -> None:
    """Inspect every real preprocessed attempt while the non-driver sentinel stops the first."""
    from psycopg import connection

    attempts: list[dict[str, Any]] = []
    real = connection.conninfo_attempts

    def record(params: Any) -> Any:
        result = real(params)
        attempts.extend(result)
        return result

    monkeypatch.setattr(connection, "conninfo_attempts", record)
    connect = psycopg.connect if api == "module" else psycopg.Connection.connect
    with pytest.raises(_BoundaryReached):
        connect(host="localhost,/tmp/s,ip6-localhost,", hostaddr=",::1,,")
    assert attempts == [
        {"host": "127.0.0.1", "hostaddr": "127.0.0.1"},
        {"host": "/tmp/s", "hostaddr": "::1"},
        {"host": "::1", "hostaddr": ""},
        {"host": "/tmp", "hostaddr": ""},
    ]
    assert inert == [attempts[0]]


def test_refusing_tailscale_install_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated installation selects the same executable refusal stub."""
    stub = network.refuse_tailscale(tmp_path / "stub", monkeypatch)
    assert network.refuse_tailscale(tmp_path / "stub", monkeypatch) == stub
    assert os.environ["HYPOTHEX_TAILSCALE"] == str(stub)
    done = subprocess.run([str(stub), "status"], capture_output=True, text=True, timeout=5)
    assert done.returncode == 255 and "blocked" in done.stderr
