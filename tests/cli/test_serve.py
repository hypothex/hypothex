import json
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from hypothex.cli import main as cli_main
from tests.api.envserver import wait_until

HX = [sys.executable, "-m", "hypothex.cli.main"]


def test_serve_writes_server_json_and_reports_kind(tmp_path: Path) -> None:
    home = tmp_path / "h"
    info_path = home / "serve" / "server.json"
    proc = subprocess.Popen(
        [*HX, "--home", str(home), "serve", "--port", "0", "--kind", "ssh"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        info = wait_until(lambda: json.loads(info_path.read_text()), timeout=30)
        assert info["pid"] == proc.pid and info["managed"] is False and info["port"] > 0
        url = f"http://127.0.0.1:{info['port']}/.well-known/hypothex/environment"
        good = {"Authorization": f"Bearer {info['token']}"}
        descriptor = wait_until(lambda: httpx.get(url, headers=good, timeout=2).json(), timeout=30)
        assert descriptor["kind"] == "ssh"
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    assert not info_path.exists()


def test_serve_on_a_taken_port_is_a_clean_error(tmp_path: Path) -> None:
    home = tmp_path / "h"
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        result = subprocess.run(
            [*HX, "--home", str(home), "serve", "--port", str(port)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert result.returncode == 1
    assert f"cannot listen on 127.0.0.1:{port}" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (home / "serve" / "server.json").exists()


def test_serve_rejects_an_unknown_kind(tmp_path: Path) -> None:
    result = subprocess.run(
        [*HX, "--home", str(tmp_path / "h"), "serve", "--kind", "gpu"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1 and "--kind must be ssh or slurm" in result.stderr


def _serve(home: Path, *extra: str, token: str | None = None) -> subprocess.Popen[bytes]:
    env = {k: v for k, v in os.environ.items() if k != "HYPOTHEX_SERVE_TOKEN"}
    if token is not None:
        env["HYPOTHEX_SERVE_TOKEN"] = token
    return subprocess.Popen(
        [*HX, "--home", str(home), "serve", "--port", "0", "--kind", "ssh", *extra],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_env_server_requires_its_token(tmp_path: Path) -> None:
    # any local user can reach 127.0.0.1:<port>; without the token they get nothing
    home = tmp_path / "h"
    proc = _serve(home, token="a1" * 24)
    try:
        info_path = home / "serve" / "server.json"
        info = wait_until(lambda: json.loads(info_path.read_text()), timeout=30)
        assert info["token"] == "a1" * 24
        assert info_path.stat().st_mode & 0o777 == 0o600
        assert info_path.parent.stat().st_mode & 0o777 == 0o700
        base = f"http://127.0.0.1:{info['port']}"
        wait_until(lambda: httpx.get(f"{base}/.well-known/hypothex/environment").json())
        assert httpx.get(f"{base}/api/v1/runs").status_code == 401
        wrong = {"Authorization": "Bearer nope"}
        assert httpx.post(f"{base}/api/v1/runs", json={}, headers=wrong).status_code == 401
        assert httpx.get(f"{base}/api/v1/runs/x/files/run.yaml").status_code == 401
        good = {"Authorization": f"Bearer {'a1' * 24}"}
        assert httpx.get(f"{base}/api/v1/runs", headers=good).status_code == 200
    finally:
        proc.terminate()
        proc.wait(timeout=30)


def test_no_auth_serves_without_a_token(tmp_path: Path) -> None:
    home = tmp_path / "h"
    proc = _serve(home, "--no-auth")
    try:
        info = wait_until(
            lambda: json.loads((home / "serve" / "server.json").read_text()), timeout=30
        )
        assert info["token"] is None
        url = f"http://127.0.0.1:{info['port']}/api/v1/runs"
        assert wait_until(lambda: httpx.get(url, timeout=2).status_code, timeout=30) == 200
    finally:
        proc.terminate()
        proc.wait(timeout=30)


def _serve_once(home: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "HYPOTHEX_SERVE_TOKEN"}
    return subprocess.run(
        [*HX, "--home", str(home), "serve", "--port", "0", "--kind", "ssh"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _record(home: Path, **fields: object) -> Path:
    path = home / "serve" / "server.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    base: dict[str, object] = {"pid": 1, "port": 9, "managed": False, "token": None}
    path.write_text(json.dumps({**base, **fields}))
    return path


def test_a_second_serve_keeps_the_live_owner(tmp_path: Path) -> None:
    # one server per home: a second `hx serve` must not take over server.json
    home = tmp_path / "h"
    proc = _serve(home)
    info_path = home / "serve" / "server.json"
    try:
        info = wait_until(lambda: json.loads(info_path.read_text()), timeout=30)
        url = f"http://127.0.0.1:{info['port']}/.well-known/hypothex/environment"
        wait_until(lambda: httpx.get(url, timeout=2).json(), timeout=30)
        second = _serve_once(home)
        assert second.returncode == 1, second.stderr
        assert f"pid {proc.pid}" in second.stderr and "already serves" in second.stderr
        assert "Traceback" not in second.stderr
        assert json.loads(info_path.read_text())["pid"] == proc.pid
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    assert not info_path.exists()


def test_serve_refuses_a_live_unanswering_or_foreign_owner(tmp_path: Path) -> None:
    home = tmp_path / "h"
    # a live pid (this test) that does not answer for the home on its port
    path = _record(home, pid=os.getpid(), hostname=socket.gethostname())
    result = _serve_once(home)
    assert result.returncode == 1 and "does not answer" in result.stderr
    assert json.loads(path.read_text())["pid"] == os.getpid()
    _record(home, pid=os.getpid(), hostname="other-login-node")
    result = _serve_once(home)
    assert result.returncode == 1 and "other-login-node" in result.stderr


def test_serve_replaces_the_record_of_a_dead_server(tmp_path: Path) -> None:
    home = tmp_path / "h"
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    path = _record(home, pid=gone.pid, hostname=socket.gethostname())
    proc = _serve(home)
    try:
        wait_until(lambda: json.loads(path.read_text())["pid"] == proc.pid or None, timeout=30)
    finally:
        proc.terminate()
        proc.wait(timeout=30)


def test_write_private_ignores_a_stale_tmp_mode(tmp_path: Path) -> None:
    path = tmp_path / "serve" / "server.json"
    path.parent.mkdir()
    stale = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    stale.write_text("old")
    stale.chmod(0o644)
    cli_main._write_private(path, '{"token": "t"}')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text() == '{"token": "t"}'


def test_write_private_removes_its_tmp_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "serve" / "server.json"

    def failing_replace(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(cli_main.os, "replace", failing_replace)
    with pytest.raises(OSError, match="disk full"):
        cli_main._write_private(path, "{}")
    assert not path.with_name(f".{path.name}.{os.getpid()}.tmp").exists()
    assert not path.exists()


def test_serve_kind_goes_back_to_local_after_a_trial_ssh(tmp_path: Path) -> None:
    # The local role is persisted independently of default token authentication.
    home = tmp_path / "h"
    assert cli_main.resolve_serve_kind(home, "ssh") == "ssh"
    assert cli_main.resolve_serve_kind(home, None) == "ssh"  # the saved kind sticks
    cli_main.check_serve_kind("local")
    assert cli_main.resolve_serve_kind(home, "local") == "local"
    assert cli_main.resolve_serve_kind(home, None) == "local"
    assert json.loads((home / "environment.json").read_text())["kind"] == "local"
    assert cli_main._serve_token("127.0.0.1", "local", False) is not None
    with pytest.raises(cli_main.ConfigError, match="or local to serve as the hub"):
        cli_main.check_serve_kind("gpu")


def test_local_default_restart_rotates_token_and_owner_helper(tmp_path: Path) -> None:
    home = tmp_path / "h"
    previous: str | None = None
    environment: str | None = None
    for _ in range(2):
        proc = _serve(home, "--kind", "local")
        try:
            info = wait_until(
                lambda: json.loads((home / "serve" / "server.json").read_text()), timeout=30
            )
            assert info["home"] == str(home.resolve())
            assert isinstance(info["pid_create_time"], float)
            assert info["environment_id"]
            if environment is not None:
                assert info["environment_id"] == environment
            environment = info["environment_id"]
            base = f"http://127.0.0.1:{info['port']}"
            wait_until(
                lambda base=base: (
                    httpx.get(base + "/.well-known/hypothex/environment").status_code == 200
                )
            )
            result = subprocess.run(
                [*HX, "--home", str(home), "token"], capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0 and result.stdout.strip() == info["token"]
            assert result.stderr == ""
            assert httpx.get(base + "/api/v1/projects").status_code == 401
            if previous is not None:
                assert info["token"] != previous
                assert (
                    httpx.get(
                        base + "/api/v1/projects", headers={"Authorization": "Bearer " + previous}
                    ).status_code
                    == 401
                )
            good = {"Authorization": "Bearer " + info["token"]}
            assert httpx.get(base + "/api/v1/projects", headers=good).status_code == 200
            previous = info["token"]
        finally:
            proc.terminate()
            proc.wait(timeout=30)
    with pytest.raises(cli_main.ConfigError):
        cli_main.local_server_token(home)
