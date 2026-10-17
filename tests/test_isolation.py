import os
import shutil
import smtplib
import socket
import subprocess

import httpx
import pytest

from hypothex.core.context import Context
from hypothex.core.environment import count_gpus
from tests.fakes import DEAD_HUB, REFUSED_EXIT, REFUSED_TOOLS
from tests.fakes.network import SECRET_VARS, NetworkBlockedError


@pytest.fixture(scope="module")
def module_env() -> dict[str, str | None]:
    """What a module-scoped fixture sees: it runs before the per-test ``isolate_remote``."""
    return {
        "hub": os.environ.get("HYPOTHEX_HUB_URL"),
        "fake_gpus": os.environ.get("HYPOTHEX_FAKE_GPUS"),
        "ssh": os.environ.get("HYPOTHEX_SSH"),
        "nvidia-smi": shutil.which("nvidia-smi"),
        "sbatch": shutil.which("sbatch"),
    }


def test_module_fixtures_already_run_fail_closed(module_env: dict[str, str | None]) -> None:
    # the session baseline (pytest_configure) covers fixtures that start before any test
    assert module_env["hub"] == DEAD_HUB and module_env["fake_gpus"] is None
    for tool in ("nvidia-smi", "sbatch"):
        found = module_env[tool]
        assert found is not None and "refused-tools" in found, tool
    ssh = module_env["ssh"]
    assert ssh is not None
    assert subprocess.run([ssh, "gpu1", "true"], capture_output=True).returncode == 255


@pytest.mark.parametrize("tool", REFUSED_TOOLS)
def test_real_gpu_and_slurm_tools_are_blocked(tool: str) -> None:
    found = shutil.which(tool)
    assert found is not None and "refused-tools" in found
    done = subprocess.run([tool, "--version"], capture_output=True, text=True)
    assert done.returncode == REFUSED_EXIT and "blocked" in done.stderr


def test_hub_and_ssh_are_dead_ends() -> None:
    assert os.environ["HYPOTHEX_HUB_URL"] == DEAD_HUB
    assert "HYPOTHEX_FAKE_GPUS" not in os.environ
    for var in ("HYPOTHEX_SSH", "HYPOTHEX_SCP"):
        done = subprocess.run([os.environ[var], "gpu1", "true"], capture_output=True)
        assert done.returncode == 255


def test_gpu_count_and_context_never_reach_a_real_nvidia_smi(ctx: Context) -> None:
    assert count_gpus() == 0
    assert ctx.descriptor.gpus == 0


@pytest.fixture(scope="module")
def module_connect() -> str:
    """Return the refusal observed before per-test fixture setup."""
    try:
        socket.create_connection(("192.0.2.10", 443), timeout=1)
    except NetworkBlockedError as exc:
        return str(exc)
    return "connected"


def test_module_fixtures_already_run_behind_the_network_guard(module_connect: str) -> None:
    """Session setup blocks public sockets before module fixtures run."""
    assert "blocked" in module_connect


@pytest.mark.parametrize("url", ["http://203.0.113.7/", "https://hooks.slack.com/services/T0/B0/x"])
def test_httpx_cannot_reach_public_addresses_or_names(url: str) -> None:
    """HTTP clients cannot resolve or connect to real services."""
    with pytest.raises(httpx.ConnectError, match="blocked"):
        httpx.get(url, timeout=1, trust_env=False)


def test_smtplib_cannot_reach_a_public_server() -> None:
    """SMTP refuses external names before opening a socket."""
    with pytest.raises(NetworkBlockedError):
        smtplib.SMTP("smtp.example.org", 587, timeout=1)


def test_raw_socket_connect_is_blocked() -> None:
    """Both socket connection APIs fail closed for public IPs."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(NetworkBlockedError):
            sock.connect(("198.51.100.1", 80))
        assert sock.connect_ex(("198.51.100.1", 80)) != 0


@pytest.mark.parametrize("connect_ex", [False, True])
def test_loopback_still_works(connect_ex: bool) -> None:
    """A local ephemeral listener remains accessible through both APIs."""
    with socket.socket() as server, socket.socket() as client:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(5)
        client.settimeout(5)
        address = ("localhost", server.getsockname()[1])
        if connect_ex:
            assert client.connect_ex(address) == 0
        else:
            client.connect(address)
        connection, _ = server.accept()
        connection.close()


def test_secret_variables_are_unset() -> None:
    """No inherited channel or index credential enters a test."""
    assert all(name not in os.environ for name in SECRET_VARS)
    assert not any(name.startswith("PG") for name in os.environ)


def test_tailscale_points_at_a_refusing_stub() -> None:
    """The session Tailscale executable is an inert refusal stub."""
    done = subprocess.run(
        [os.environ["HYPOTHEX_TAILSCALE"], "status", "--json"], capture_output=True, text=True
    )
    assert done.returncode == 255 and "blocked" in done.stderr
