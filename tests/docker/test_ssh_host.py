"""SSH host end to end against a throwaway sshd container (never the user's hosts)."""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path

import pytest

from tests.docker.conftest import docker_skip_reason, make_ssh_access, run_cmd


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
