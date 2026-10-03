import os
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from hypothex.remote.ssh import SshError, SshTarget, run_remote
from tests.fakes import DEAD_HUB, FakeRemote

# --------------------------------------------------------------------------- isolation


def test_tests_never_reach_real_hosts_or_a_real_hub() -> None:
    assert os.environ["HYPOTHEX_HUB_URL"] == DEAD_HUB
    with pytest.raises(SshError, match="tests never reach real hosts"):
        run_remote(SshTarget(alias="gpu1"), "true")


# --------------------------------------------------------------------------- target


def test_target_binaries_default_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPOTHEX_SSH", "/opt/fake/ssh")
    monkeypatch.delenv("HYPOTHEX_SCP", raising=False)
    target = SshTarget(alias="gpu1")
    assert (target.ssh_bin, target.scp_bin, target.connect_timeout) == ("/opt/fake/ssh", "scp", 10)


@pytest.mark.parametrize("alias", ["-oProxyCommand=touch /tmp/pwned", "gpu 1", "gpu1\n", ""])
def test_target_rejects_unsafe_alias(alias: str) -> None:
    with pytest.raises(ValidationError, match="invalid ssh alias"):
        SshTarget(alias=alias)


# --------------------------------------------------------------------------- run_remote


def test_run_remote_runs_script_in_remote_home(fake_remote: FakeRemote) -> None:
    home = fake_remote.add_host("gpu1")
    res = run_remote(fake_remote.target("gpu1"), 'set -e\necho hi\necho "$HOME"\npwd\n')
    assert res.returncode == 0
    assert res.stdout.decode().splitlines() == ["hi", str(home), str(home)]


def test_run_remote_returns_script_failure_without_raising(fake_remote: FakeRemote) -> None:
    fake_remote.add_host("gpu1")
    res = run_remote(fake_remote.target("gpu1"), "echo oops >&2\nexit 3\n")
    assert (res.returncode, res.stdout, res.stderr) == (3, b"", b"oops\n")


def test_run_remote_feeds_input_bytes_to_script(fake_remote: FakeRemote) -> None:
    home = fake_remote.add_host("gpu1")
    data = bytes(range(256)) * 4
    res = run_remote(
        fake_remote.target("gpu1"), "cat > blob.bin && wc -c < blob.bin", input_bytes=data
    )
    assert res.returncode == 0
    assert res.stdout.strip() == b"1024"
    assert (home / "blob.bin").read_bytes() == data


def test_run_remote_command_line_uses_batchmode_and_sh_s(fake_remote: FakeRemote) -> None:
    fake_remote.add_host("gpu1")
    run_remote(fake_remote.target("gpu1", connect_timeout=7), "true")
    assert fake_remote.calls("ssh") == [
        [
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=7",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
            "gpu1",
            "sh",
            "-s",
        ]
    ]


def test_run_remote_hides_hub_home_from_remote(
    fake_remote: FakeRemote, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYPOTHEX_HOME", "/hub/home")
    fake_remote.add_host("gpu1")
    res = run_remote(fake_remote.target("gpu1"), 'echo "${HYPOTHEX_HOME-unset}"')
    assert res.stdout == b"unset\n"


def test_run_remote_unknown_host_raises(fake_remote: FakeRemote) -> None:
    with pytest.raises(SshError, match="Could not resolve hostname nohost"):
        run_remote(fake_remote.target("nohost"), "true")


def test_run_remote_down_host_raises(fake_remote: FakeRemote) -> None:
    fake_remote.add_host("gpu1")
    fake_remote.set_down("gpu1", True)
    with pytest.raises(SshError, match="Connection refused"):
        run_remote(fake_remote.target("gpu1"), "true")
    fake_remote.set_down("gpu1", False)
    assert run_remote(fake_remote.target("gpu1"), "echo up").stdout == b"up\n"


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_run_remote_timeout_kills_whole_process_group(fake_remote: FakeRemote) -> None:
    home = fake_remote.add_host("gpu1")
    started = time.monotonic()
    with pytest.raises(SshError, match=r"timed out after 0\.5s"):
        run_remote(fake_remote.target("gpu1"), "echo $$ > pid\nexec sleep 30\n", timeout=0.5)
    assert time.monotonic() - started < 5
    pid = int((home / "pid").read_text())
    deadline = time.monotonic() + 3
    while not _gone(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _gone(pid)


def test_run_remote_missing_ssh_binary_raises(tmp_path: Path) -> None:
    target = SshTarget(alias="gpu1", ssh_bin=str(tmp_path / "no-ssh"))
    with pytest.raises(SshError, match="not found"):
        run_remote(target, "true")
