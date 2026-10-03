"""SSH host end to end against a throwaway sshd container (never the user's hosts)."""

from __future__ import annotations

import json
import shlex
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hypothex import __version__
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.core.environment import PROTOCOL_VERSION
from hypothex.remote.bootstrap import ensure_server, probe
from hypothex.remote.config import load_hosts
from tests.docker.conftest import (
    DESCRIPTOR_PY,
    REMOTE_HOME,
    SshBox,
    docker_skip_reason,
    make_ssh_access,
    run_cmd,
)

runner = CliRunner()


# harness checks (no Docker needed) ------------------------------------------------------
def test_ssh_access_never_uses_the_users_ssh_setup(tmp_path: Path) -> None:
    if shutil.which("ssh") is None or shutil.which("ssh-keygen") is None:
        pytest.skip("OpenSSH client not found")
    access = make_ssh_access(tmp_path / "ssh", "hx-unit", 2222)
    text = access.config.read_text()
    assert text.startswith("Host hx-unit\n")
    assert "  IdentitiesOnly yes\n" in text
    assert "  IdentityAgent none\n" in text
    assert "~" not in text
    assert str(Path.home() / ".ssh") not in text
    assert f"-F {shlex.quote(str(access.config))}" in access.ssh.read_text()
    assert f"-F {shlex.quote(str(access.config))}" in access.scp.read_text()
    assert access.public_key.startswith("ssh-ed25519 ")
    assert access.public_key.endswith(" hypothex-docker-test")
    assert access.target().ssh_bin == str(access.ssh)
    assert access.env() == {"HYPOTHEX_SSH": str(access.ssh), "HYPOTHEX_SCP": str(access.scp)}
    # `ssh -G` prints the effective config without connecting anywhere
    effective = run_cmd([str(access.ssh), "-G", "hx-unit"]).stdout
    lines = {line.lower() for line in effective.splitlines()}
    assert "hostname 127.0.0.1" in lines
    assert "port 2222" in lines
    assert "user hx" in lines
    assert "identityagent none" in lines
    assert f"identityfile {tmp_path / 'ssh' / 'id_ed25519'}".lower() in lines
    assert f"userknownhostsfile {tmp_path / 'ssh' / 'known_hosts'}".lower() in lines


def test_docker_skip_reason_without_docker_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert docker_skip_reason() == "docker CLI not found"


# against the container ------------------------------------------------------------------
@pytest.fixture
def hub_ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sshd_box: SshBox) -> Context:
    """A fresh hub home whose ssh/scp are the box's isolated wrappers."""
    home = tmp_path / "hub"
    monkeypatch.setenv("HYPOTHEX_HOME", str(home))
    for key, value in sshd_box.access.env().items():
        monkeypatch.setenv(key, value)
    return Context.open(home)


def server_json(box: SshBox) -> dict:
    return json.loads(box.sh("cat ~/.hypothex/serve/server.json"))


@pytest.mark.docker
def test_hosts_add_bootstraps_a_managed_server(sshd_box: SshBox, hub_ctx: Context) -> None:
    home = str(hub_ctx.layout.home)
    argv = ["--home", home, "hosts", "add", "box", "--ssh", sshd_box.access.alias, "--json"]
    result = runner.invoke(app, argv, catch_exceptions=False)
    assert result.exit_code == 0, result.output

    spec = load_hosts(hub_ctx.layout).environments["box"]
    assert (spec.route, spec.kind, spec.ssh_alias, spec.home) == (
        "ssh",
        "ssh",
        "hx-docker-sshd",
        "~/.hypothex",
    )
    wheels = sshd_box.sh("ls ~/.hypothex/runtime/wheels").split()
    assert f"hypothex-{__version__}-py3-none-any.whl" in wheels

    info = server_json(sshd_box)
    assert info["managed"] is True
    assert info["hx_version"] == __version__
    assert info["protocol_version"] == PROTOCOL_VERSION
    sshd_box.exec("kill", "-0", str(info["pid"]))  # alive (raises if not)
    descriptor = json.loads(sshd_box.exec("python3", "-c", DESCRIPTOR_PY, str(info["port"])))
    assert descriptor["kind"] == "ssh"
    assert descriptor["hx_version"] == __version__
    assert descriptor["hostname"] == sshd_box.exec("hostname").strip()

    # a second bootstrap reuses the healthy server instead of starting another
    again = ensure_server(sshd_box.access.target(), REMOTE_HOME)
    assert (again.pid, again.port, again.managed) == (info["pid"], info["port"], True)
    assert info["token"] and again.token == info["token"]  # env server auth (Task 47)
    mode = sshd_box.sh("stat -c %a ~/.hypothex/serve/server.json").strip()
    assert mode == "600"


@pytest.mark.docker
def test_probe_reports_the_box(sshd_box: SshBox) -> None:
    result = probe(sshd_box.access.target(), REMOTE_HOME)
    assert result.os.lower() == "linux"
    assert result.arch == sshd_box.exec("uname", "-m").strip()
    assert result.python is not None and "3.12" in result.python
    assert result.uv is not None and "0.8.22" in result.uv
    assert result.gpus == 0
    assert result.slurm is None
    assert result.home.endswith("/.hypothex")
