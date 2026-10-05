import contextlib
import functools
import http.server
import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import psutil
import pytest
from pydantic import ValidationError

from hypothex.remote import ssh as ssh_module
from hypothex.remote.ssh import (
    SshError,
    SshTarget,
    Tunnel,
    _free_port,
    copy_from,
    copy_to,
    reap_stale_tunnels,
    run_remote,
)
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


# --------------------------------------------------------------------------- copy


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """The hub's pull work folder (``<hub home>/pulls``), outside every destination."""
    return tmp_path / "hub-home" / "pulls"


def test_copy_to_file_lands_at_remote_path(fake_remote: FakeRemote, tmp_path: Path) -> None:
    home = fake_remote.add_host("gpu1")
    target = fake_remote.target("gpu1")
    run_remote(target, "mkdir -p .hypothex/runtime/wheels")
    wheel = tmp_path / "hypothex-0.2.0-py3-none-any.whl"
    wheel.write_bytes(b"PK\x03\x04wheel")
    copy_to(target, wheel, "~/.hypothex/runtime/wheels/hx.whl")
    assert (home / ".hypothex/runtime/wheels/hx.whl").read_bytes() == b"PK\x03\x04wheel"
    argv = fake_remote.calls("scp")[-1]
    assert argv[:2] == ["-o", "BatchMode=yes"]
    assert argv[-5:] == ["-s", "-q", "-r", str(wheel), "gpu1:~/.hypothex/runtime/wheels/hx.whl"]


def test_copy_to_relative_path_and_directory(fake_remote: FakeRemote, tmp_path: Path) -> None:
    home = fake_remote.add_host("gpu1")
    src = tmp_path / "bundle"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("a")
    (src / "sub" / "b.txt").write_text("b")
    copy_to(fake_remote.target("gpu1"), src, "bundle")
    assert (home / "bundle" / "a.txt").read_text() == "a"
    assert (home / "bundle" / "sub" / "b.txt").read_text() == "b"


def test_copy_to_missing_remote_parent_raises(fake_remote: FakeRemote, tmp_path: Path) -> None:
    fake_remote.add_host("gpu1")
    src = tmp_path / "f.txt"
    src.write_text("x")
    with pytest.raises(SshError, match="No such file or directory"):
        copy_to(fake_remote.target("gpu1"), src, "~/missing/dir/f.txt")


def test_copy_to_missing_local_raises_before_scp(fake_remote: FakeRemote, tmp_path: Path) -> None:
    fake_remote.add_host("gpu1")
    with pytest.raises(SshError, match="no such file"):
        copy_to(fake_remote.target("gpu1"), tmp_path / "nope.whl", "~/nope.whl")
    assert fake_remote.calls("scp") == []


def test_copy_to_unknown_host_raises(fake_remote: FakeRemote, tmp_path: Path) -> None:
    src = tmp_path / "f.txt"
    src.write_text("x")
    with pytest.raises(SshError, match="Could not resolve hostname nohost"):
        copy_to(fake_remote.target("nohost"), src, "~/f.txt")


def test_copy_rejects_newline_in_remote_path(
    fake_remote: FakeRemote, tmp_path: Path, work: Path
) -> None:
    fake_remote.add_host("gpu1")
    src = tmp_path / "f.txt"
    src.write_text("x")
    with pytest.raises(SshError, match="invalid remote path"):
        copy_to(fake_remote.target("gpu1"), src, "a\nb")
    with pytest.raises(SshError, match="invalid remote path"):
        copy_from(fake_remote.target("gpu1"), "", tmp_path / "out", work=work)


@pytest.mark.parametrize(
    "remote_path", ["/x;rm -rf ~", "/x $(id)", "/a/`id`", "~/a b", "/a/../etc/passwd", "../up"]
)
def test_copy_rejects_shell_and_parent_paths(
    fake_remote: FakeRemote, tmp_path: Path, work: Path, remote_path: str
) -> None:
    fake_remote.add_host("gpu1")
    src = tmp_path / "f.txt"
    src.write_text("x")
    with pytest.raises(SshError, match="invalid remote path"):
        copy_to(fake_remote.target("gpu1"), src, remote_path)
    with pytest.raises(SshError, match="invalid remote path"):
        copy_from(fake_remote.target("gpu1"), remote_path, tmp_path / "out", work=work)
    assert fake_remote.calls("scp") == []


@pytest.mark.parametrize("remote_path", ["/", "~", "~/", "/scratch/ckpt/", "/scratch/."])
def test_copy_from_needs_a_file_name(
    fake_remote: FakeRemote, tmp_path: Path, work: Path, remote_path: str
) -> None:
    fake_remote.add_host("gpu1")
    pulled = tmp_path / "pulled"
    pulled.mkdir()
    (pulled / "keep.txt").write_text("k")
    with pytest.raises(SshError, match="invalid remote path"):
        copy_from(fake_remote.target("gpu1"), remote_path, pulled / "x", work=work)
    assert (pulled / "keep.txt").read_text() == "k"
    assert fake_remote.calls("scp") == []


def test_copy_from_forces_sftp(fake_remote: FakeRemote, tmp_path: Path, work: Path) -> None:
    home = fake_remote.add_host("gpu1")
    (home / "f.txt").write_text("x")
    copy_from(fake_remote.target("gpu1"), "f.txt", tmp_path / "f.txt", work=work)
    assert "-s" in fake_remote.calls("scp")[-1]


def test_fake_scp_refuses_paths_outside_fake_root(fake_remote: FakeRemote, tmp_path: Path) -> None:
    fake_remote.add_host("gpu1")
    src = tmp_path / "f.txt"
    src.write_text("x")
    with pytest.raises(SshError, match="outside the fake remote root"):
        copy_to(fake_remote.target("gpu1"), src, "/etc/hypothex-test.txt")
    assert not Path("/etc/hypothex-test.txt").exists()


def test_copy_from_file_creates_local_parents(
    fake_remote: FakeRemote, tmp_path: Path, work: Path
) -> None:
    home = fake_remote.add_host("gpu1")
    (home / "ckpt").mkdir()
    (home / "ckpt" / "best.pt").write_bytes(b"\x00weights")
    dest = tmp_path / "store" / "pulled" / "best.pt"
    copy_from(fake_remote.target("gpu1"), "~/ckpt/best.pt", dest, work=work)
    assert dest.read_bytes() == b"\x00weights"
    assert sorted(p.name for p in dest.parent.iterdir()) == ["best.pt"]


def test_copy_from_directory(fake_remote: FakeRemote, tmp_path: Path, work: Path) -> None:
    home = fake_remote.add_host("gpu1")
    (home / "run" / "ckpt").mkdir(parents=True)
    (home / "run" / "ckpt" / "model.bin").write_bytes(b"m")
    (home / "run" / "ckpt" / "cfg.json").write_text("{}")
    dest = tmp_path / "pulled" / "ckpt"
    copy_from(fake_remote.target("gpu1"), "run/ckpt", dest, work=work)
    assert sorted(p.name for p in dest.iterdir()) == ["cfg.json", "model.bin"]


def test_copy_from_replaces_existing_file_and_dir(
    fake_remote: FakeRemote, tmp_path: Path, work: Path
) -> None:
    home = fake_remote.add_host("gpu1")
    (home / "f.txt").write_text("new")
    (home / "d").mkdir()
    (home / "d" / "new.txt").write_text("n")
    file_dest = tmp_path / "f.txt"
    file_dest.write_text("old")
    dir_dest = tmp_path / "d"
    dir_dest.mkdir()
    (dir_dest / "stale.txt").write_text("s")
    target = fake_remote.target("gpu1")
    copy_from(target, "f.txt", file_dest, work=work)
    copy_from(target, "d", dir_dest, work=work)
    assert file_dest.read_text() == "new"
    assert sorted(p.name for p in dir_dest.iterdir()) == ["new.txt"]


def test_copy_from_missing_remote_leaves_nothing(
    fake_remote: FakeRemote, tmp_path: Path, work: Path
) -> None:
    fake_remote.add_host("gpu1")
    out_dir = tmp_path / "pulled" / "out"
    with pytest.raises(SshError, match="No such file or directory"):
        copy_from(fake_remote.target("gpu1"), "~/nope.pt", out_dir / "nope.pt", work=work)
    assert not (tmp_path / "pulled").exists()  # no empty folder is left behind
    assert list((work / "stage").iterdir()) == []


def test_copy_from_failure_keeps_the_old_file(
    fake_remote: FakeRemote, tmp_path: Path, work: Path
) -> None:
    fake_remote.add_host("gpu1")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dest = out_dir / "best.pt"
    dest.write_text("old")
    with pytest.raises(SshError):
        copy_from(fake_remote.target("gpu1"), "~/nope.pt", dest, work=work)
    assert dest.read_text() == "old"
    assert sorted(p.name for p in out_dir.iterdir()) == ["best.pt"]


def test_concurrent_pulls_of_one_file_never_share_a_staging_path(
    fake_remote: FakeRemote, tmp_path: Path, work: Path
) -> None:
    home = fake_remote.add_host("gpu1")
    for i in range(4):
        (home / f"v{i}.pt").write_text(f"v{i}" * 50_000)
    dest = tmp_path / "pulled" / "best.pt"
    errors: list[Exception] = []

    def pull(i: int) -> None:
        try:
            copy_from(fake_remote.target("gpu1"), f"v{i}.pt", dest, work=work)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=pull, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert dest.read_text() in {f"v{i}" * 50_000 for i in range(4)}
    assert sorted(p.name for p in dest.parent.iterdir()) == ["best.pt"]


class _Crash(BaseException):
    """The process dies right here (nothing on the way catches it)."""


def test_a_folder_swap_cut_short_is_recovered(
    fake_remote: FakeRemote, tmp_path: Path, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = fake_remote.add_host("gpu1")
    (home / "d").mkdir()
    (home / "d" / "new.txt").write_text("n")
    dest = tmp_path / "out" / "d"
    dest.mkdir(parents=True)
    (dest / "old.txt").write_text("o")
    real = os.replace

    def crash_after_the_old_folder_moved(src: str | Path, dst: str | Path) -> None:
        real(src, dst)
        if Path(dst).parent == work / "backup":
            raise _Crash

    target = fake_remote.target("gpu1")
    monkeypatch.setattr(os, "replace", crash_after_the_old_folder_moved)
    with pytest.raises(_Crash):
        copy_from(target, "d", dest, work=work)
    monkeypatch.setattr(os, "replace", real)
    [backup] = (work / "backup").iterdir()
    [record] = (work / "txn").iterdir()
    assert not dest.exists() and (backup / "old.txt").is_file()
    assert list(dest.parent.iterdir()) == []  # nothing of the swap next to the destination
    assert json.loads(record.read_text()) == {"txn": backup.name, "dest": str(dest)}
    with pytest.raises(SshError):  # the next pull fails, but the old folder comes back
        copy_from(target, "nope", dest, work=work)
    assert sorted(p.name for p in dest.iterdir()) == ["old.txt"]
    copy_from(target, "d", dest, work=work)
    assert sorted(p.name for p in dest.iterdir()) == ["new.txt"]
    assert sorted(p.name for p in dest.parent.iterdir()) == ["d"]
    assert list((work / "txn").iterdir()) == [] and list((work / "backup").iterdir()) == []


def test_a_swap_that_crashed_before_its_first_rename_changes_nothing(
    fake_remote: FakeRemote, tmp_path: Path, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = fake_remote.add_host("gpu1")
    (home / "d").mkdir()
    (home / "d" / "new.txt").write_text("n")
    dest = tmp_path / "out" / "d"
    dest.mkdir(parents=True)
    (dest / "old.txt").write_text("o")
    real = os.replace

    def crash_before_any_rename(src: str | Path, dst: str | Path) -> None:
        raise _Crash

    target = fake_remote.target("gpu1")
    monkeypatch.setattr(os, "replace", crash_before_any_rename)
    with pytest.raises(_Crash):
        copy_from(target, "d", dest, work=work)
    monkeypatch.setattr(os, "replace", real)
    assert sorted(p.name for p in dest.iterdir()) == ["old.txt"]  # the record alone is left
    assert len(list((work / "txn").iterdir())) == 1
    assert sorted(p.name for p in dest.parent.iterdir()) == ["d"]
    copy_from(target, "d", dest, work=work)
    assert sorted(p.name for p in dest.iterdir()) == ["new.txt"]
    assert sorted(p.name for p in dest.parent.iterdir()) == ["d"]
    assert list((work / "txn").iterdir()) == []


def test_a_pull_never_touches_files_it_did_not_record(
    fake_remote: FakeRemote, tmp_path: Path, work: Path
) -> None:
    home = fake_remote.add_host("gpu1")
    (home / "best.pt").write_text("new")
    (home / "d").mkdir()
    (home / "d" / "new.txt").write_text("n")
    x = tmp_path / "x"
    x.mkdir()
    (x / ".best.pt.old").write_text("mine")  # the user's own files, named like backups
    (x / ".d.old").mkdir()
    (x / ".d.old" / "keep.txt").write_text("k")
    (x / ".hx-pull-0123.old").write_text("also mine")
    target = fake_remote.target("gpu1")
    copy_from(target, "best.pt", x / "best.pt", work=work)  # a new file next to .best.pt.old
    copy_from(target, "best.pt", x / "best.pt", work=work)  # and its replacement
    (x / "d").mkdir()
    (x / "d" / "stale.txt").write_text("s")
    copy_from(target, "d", x / "d", work=work)  # a folder swap next to .d.old
    assert (x / "best.pt").read_text() == "new"
    assert (x / ".best.pt.old").read_text() == "mine"
    assert (x / ".d.old" / "keep.txt").read_text() == "k"
    assert (x / ".hx-pull-0123.old").read_text() == "also mine"
    assert sorted(p.name for p in (x / "d").iterdir()) == ["new.txt"]
    assert sorted(p.name for p in x.iterdir()) == [
        ".best.pt.old",
        ".d.old",
        ".hx-pull-0123.old",
        "best.pt",
        "d",
    ]


def test_recovery_never_reads_a_look_alike_record_in_a_destination(
    fake_remote: FakeRemote, tmp_path: Path, work: Path
) -> None:
    # a downloaded artifact named like a transaction record, with matching fields
    home = fake_remote.add_host("gpu1")
    (home / "best.pt").write_text("new")
    (home / "e").mkdir()
    (home / "e" / "new.txt").write_text("n")
    x = tmp_path / "x"
    (x / "e").mkdir(parents=True)
    (x / "e" / "old.txt").write_text("o")
    (x / "kept").mkdir()
    looks: dict[str, str] = {}
    for dest in ("gone", "kept"):  # its dest missing (would be restored), present (deleted)
        txn = uuid.uuid4().hex
        fields = {"txn": txn, "dest": str(x / dest), "backup": f".hx-pull-{txn}.old"}
        (x / f".hx-pull-{txn}.json").write_text(json.dumps(fields))
        (x / f".hx-pull-{txn}.old").mkdir()
        (x / f".hx-pull-{txn}.old" / "mine.txt").write_text(dest)
        looks[dest] = txn
    before = sorted(p.name for p in x.iterdir())
    target = fake_remote.target("gpu1")
    copy_from(target, "best.pt", x / "best.pt", work=work)
    copy_from(target, "e", x / "e", work=work)  # a folder swap in the same folder
    assert sorted(p.name for p in x.iterdir()) == sorted([*before, "best.pt"])
    for dest, txn in looks.items():
        assert (x / f".hx-pull-{txn}.old" / "mine.txt").read_text() == dest
        assert json.loads((x / f".hx-pull-{txn}.json").read_text())["txn"] == txn
    assert not (x / "gone").exists() and list((x / "kept").iterdir()) == []
    assert sorted(p.name for p in (x / "e").iterdir()) == ["new.txt"]
    assert list((work / "txn").iterdir()) == [] and list((work / "backup").iterdir()) == []


@pytest.mark.parametrize("name", [".hx-pull-0123456789abcdef0123456789abcdef.json", ".hx-x"])
def test_any_destination_name_can_be_pulled(
    fake_remote: FakeRemote, tmp_path: Path, work: Path, name: str
) -> None:
    # pull state lives only under work/, so no destination name is reserved
    home = fake_remote.add_host("gpu1")
    (home / "f.txt").write_text("x")
    copy_from(fake_remote.target("gpu1"), "f.txt", tmp_path / "x" / name, work=work)
    assert (tmp_path / "x" / name).read_text() == "x"


@pytest.mark.parametrize("filled", [True, False], ids=["non-empty", "empty"])
def test_a_file_never_replaces_a_folder(
    fake_remote: FakeRemote, tmp_path: Path, work: Path, filled: bool
) -> None:
    home = fake_remote.add_host("gpu1")
    (home / "best.pt").write_text("new")
    dest = tmp_path / "out" / "best.pt"
    dest.mkdir(parents=True)
    if filled:
        (dest / "keep.txt").write_text("k")
    with pytest.raises(SshError, match="is a folder"):
        copy_from(fake_remote.target("gpu1"), "best.pt", dest, work=work)
    assert dest.is_dir()
    assert sorted(p.name for p in dest.iterdir()) == (["keep.txt"] if filled else [])
    assert list((work / "stage").iterdir()) == []


# --------------------------------------------------------------------------- tunnel


class _Echo(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        while data := self.request.recv(65536):
            self.request.sendall(data)


@pytest.fixture
def echo_port() -> Iterator[int]:
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Echo)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield int(server.server_address[1])
    server.shutdown()
    server.server_close()


def _roundtrip(port: int, payload: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


def _refused(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
    except OSError:
        return True
    return False


def test_tunnel_forwards_bytes_both_ways(fake_remote: FakeRemote, echo_port: int) -> None:
    fake_remote.add_host("gpu1")
    payload = os.urandom(1024 * 1024)
    with Tunnel(fake_remote.target("gpu1"), remote_port=echo_port) as tunnel:
        assert tunnel.alive()
        assert tunnel.local_port != echo_port
        assert _roundtrip(tunnel.local_port, payload) == payload
        assert _roundtrip(tunnel.local_port, b"second") == b"second"


def test_tunnel_carries_http(fake_remote: FakeRemote, tmp_path: Path) -> None:
    fake_remote.add_host("gpu1")
    (tmp_path / "www").mkdir()
    (tmp_path / "www" / "descriptor.json").write_text('{"kind": "ssh"}')

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

    handler = functools.partial(Quiet, directory=str(tmp_path / "www"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with Tunnel(fake_remote.target("gpu1"), remote_port=server.server_address[1]) as tunnel:
            for _ in range(3):
                res = httpx.get(f"http://127.0.0.1:{tunnel.local_port}/descriptor.json")
                assert (res.status_code, res.json()) == (200, {"kind": "ssh"})
    finally:
        server.shutdown()
        server.server_close()


def test_tunnel_command_line(fake_remote: FakeRemote) -> None:
    fake_remote.add_host("gpu1")
    tunnel = Tunnel(
        fake_remote.target("gpu1", connect_timeout=4), remote_port=40123, local_port=51000
    )
    expected = [
        "-N",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=4",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        "ExitOnForwardFailure=yes",
        "-L",
        "127.0.0.1:51000:127.0.0.1:40123",
        "gpu1",
    ]
    assert tunnel.argv() == [fake_remote.ssh_bin, *expected]


def test_tunnel_stop_closes_port_and_is_idempotent(fake_remote: FakeRemote, echo_port: int) -> None:
    fake_remote.add_host("gpu1")
    tunnel = Tunnel(fake_remote.target("gpu1"), remote_port=echo_port)
    tunnel.start()
    tunnel.start()
    assert len(fake_remote.calls("ssh")) == 1
    tunnel.stop()
    tunnel.stop()
    assert not tunnel.alive()
    assert _refused(tunnel.local_port)


def test_tunnel_local_port_in_use_raises(fake_remote: FakeRemote, echo_port: int) -> None:
    fake_remote.add_host("gpu1")
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = int(busy.getsockname()[1])
        tunnel = Tunnel(fake_remote.target("gpu1"), remote_port=echo_port, local_port=port)
        with pytest.raises(SshError, match=f"local port {port} is already in use"):
            tunnel.start()
    assert fake_remote.calls("ssh") == []


def test_tunnel_unknown_host_raises_with_ssh_message(fake_remote: FakeRemote) -> None:
    tunnel = Tunnel(fake_remote.target("nohost"), remote_port=40123)
    with pytest.raises(SshError, match="exited 255.*Could not resolve hostname nohost"):
        tunnel.start()
    assert not tunnel.alive()


def test_tunnel_dies_when_host_drops_and_restarts_on_same_port(
    fake_remote: FakeRemote, echo_port: int
) -> None:
    fake_remote.add_host("gpu1")
    tunnel = Tunnel(fake_remote.target("gpu1"), remote_port=echo_port)
    tunnel.start()
    port = tunnel.local_port
    fake_remote.set_down("gpu1", True)
    deadline = time.monotonic() + 3
    while tunnel.alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not tunnel.alive()
    assert "closed by remote host" in tunnel.stderr_tail()
    with pytest.raises(SshError, match="Connection refused"):
        tunnel.start()
    fake_remote.set_down("gpu1", False)
    tunnel.start()
    try:
        assert tunnel.local_port == port
        assert _roundtrip(port, b"back") == b"back"
    finally:
        tunnel.stop()


def test_tunnel_to_closed_remote_port_drops_connections(fake_remote: FakeRemote) -> None:
    fake_remote.add_host("gpu1")
    with Tunnel(fake_remote.target("gpu1"), remote_port=_free_port()) as tunnel:
        try:
            echoed = _roundtrip(tunnel.local_port, b"hello")
        except ConnectionError:  # reset instead of a clean close; both mean "dropped"
            echoed = b""
        assert echoed == b""
        assert tunnel.alive()


def test_tunnel_missing_ssh_binary_raises(tmp_path: Path) -> None:
    target = SshTarget(alias="gpu1", ssh_bin=str(tmp_path / "no-ssh"))
    with pytest.raises(SshError, match="not found"):
        Tunnel(target, remote_port=40123).start()


# --------------------------------------------------------------------------- orphan tunnels

_HOLD_TUNNEL = """
import sys, time
from pathlib import Path
from hypothex.remote.ssh import SshTarget, Tunnel
target = SshTarget(alias="gpu1", ssh_bin=sys.argv[1])
tunnel = Tunnel(target, remote_port=int(sys.argv[2]), registry=Path(sys.argv[3]))
tunnel.start()
print(tunnel.local_port, flush=True)
time.sleep(120)
"""


def _wait_until(pred: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_a_tunnel_records_itself_while_it_runs(
    fake_remote: FakeRemote, echo_port: int, tmp_path: Path
) -> None:
    fake_remote.add_host("gpu1")
    registry = tmp_path / "tunnels"
    tunnel = Tunnel(fake_remote.target("gpu1"), remote_port=echo_port, registry=registry)
    tunnel.start()
    try:
        [record] = list(registry.glob("*.json"))
        data = json.loads(record.read_text())
        assert data["pid"] == int(record.stem)
        assert data["owner"] == os.getpid()
        assert data["argv"] == tunnel.argv()
        assert data["pid_create_time"] == psutil.Process(data["pid"]).create_time()
        assert data["owner_create_time"] == psutil.Process().create_time()
        assert reap_stale_tunnels(registry) == []  # its owner (this process) is alive
        assert tunnel.alive()
    finally:
        tunnel.stop()
    assert list(registry.iterdir()) == []


def test_a_tunnel_left_by_a_killed_process_is_reaped(
    fake_remote: FakeRemote, echo_port: int, tmp_path: Path
) -> None:
    fake_remote.add_host("gpu1")
    registry = tmp_path / "tunnels"
    owner = subprocess.Popen(
        [sys.executable, "-c", _HOLD_TUNNEL, fake_remote.ssh_bin, str(echo_port), str(registry)],
        stdout=subprocess.PIPE,
    )
    assert owner.stdout is not None
    port = int(owner.stdout.readline())
    [record] = list(registry.glob("*.json"))
    pid = int(record.stem)
    try:
        os.kill(owner.pid, signal.SIGKILL)  # the hub dies without stopping its tunnel
        owner.wait()
        assert _roundtrip(port, b"orphan") == b"orphan"  # the ssh -L process lives on
        assert reap_stale_tunnels(registry) == [pid]
        assert _wait_until(lambda: _refused(port))
        assert list(registry.iterdir()) == []
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def test_reaping_never_kills_a_process_that_reused_the_pid(tmp_path: Path) -> None:
    registry = tmp_path / "tunnels"
    registry.mkdir()
    dead = subprocess.Popen(["true"])
    dead.wait()
    other = subprocess.Popen(["sleep", "30"])  # took the pid of a tunnel that is gone
    try:
        argv = ["ssh", "-N", "-L", "127.0.0.1:5:127.0.0.1:6", "gpu1"]
        record = {"pid": other.pid, "owner": dead.pid, "argv": argv}
        (registry / f"{other.pid}.json").write_text(json.dumps(record))
        (registry / "junk.json").write_text("{")
        assert reap_stale_tunnels(registry) == []
        assert other.poll() is None
        # The legacy record has no birth identity: keep its uncertain live
        # process for manual recovery, but discard malformed JSON.
        assert list(registry.iterdir()) == [registry / f"{other.pid}.json"]
    finally:
        other.kill()
        other.wait()


class _ReapProcess:
    """A process double: no test using it sends an operating-system signal."""

    def __init__(self, pid: int, birth: float, argv: list[str]) -> None:
        self.pid = pid
        self.birth = birth
        self.argv = argv
        self.signals: list[int] = []
        self.waits: list[float | None] = []
        self.wait_failures = 0
        self.gone = False
        self.denied = False

    def create_time(self) -> float:
        if self.denied:
            raise psutil.AccessDenied(self.pid)
        return self.birth

    def cmdline(self) -> list[str]:
        if self.denied:
            raise psutil.AccessDenied(self.pid)
        return self.argv

    def status(self) -> str:
        return psutil.STATUS_SLEEPING

    def terminate(self) -> None:
        self.signals.append(signal.SIGTERM)

    def kill(self) -> None:
        self.signals.append(signal.SIGKILL)

    def wait(self, timeout: float | None = None) -> int:
        self.waits.append(timeout)
        if self.wait_failures:
            self.wait_failures -= 1
            raise psutil.TimeoutExpired(timeout or 0, self.pid)
        self.gone = True
        return 0


def _mock_reaper_processes(
    monkeypatch: pytest.MonkeyPatch, processes: dict[int, _ReapProcess]
) -> None:
    """Replace psutil and the old os.kill/ps paths with the same process table."""

    def find(pid: int | None = None) -> _ReapProcess:
        chosen = os.getpid() if pid is None else pid
        proc = processes.get(chosen)
        if proc is None or proc.gone:
            raise psutil.NoSuchProcess(chosen)
        return proc

    def fake_kill(pid: int, sig: int) -> None:
        try:
            proc = find(pid)
        except psutil.NoSuchProcess as exc:
            raise ProcessLookupError(pid) from exc
        if sig:
            proc.signals.append(sig)

    def fake_ps(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del kwargs
        try:
            proc = find(int(args[-1]))
            line = " ".join(proc.cmdline()).encode()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return subprocess.CompletedProcess(args, 1, b"", b"")
        return subprocess.CompletedProcess(args, 0, line, b"")

    monkeypatch.setattr(psutil, "Process", find)
    monkeypatch.setattr(ssh_module.os, "kill", fake_kill)
    monkeypatch.setattr(ssh_module.subprocess, "run", fake_ps)


def _tunnel_record(registry: Path, **changes: object) -> Path:
    registry.mkdir(exist_ok=True)
    data: dict[str, object] = {
        "pid": 880001,
        "owner": 880002,
        "argv": ["ssh", "-N", "-L", "127.0.0.1:5:127.0.0.1:6", "gpu1"],
        "pid_create_time": 100.0,
        "owner_create_time": 50.0,
    }
    data.update(changes)
    record = registry / "880001.json"
    record.write_text(json.dumps(data), encoding="utf-8")
    return record


@pytest.mark.parametrize("field", ["pid", "owner"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "880001", 2**80, float("inf")])
def test_reaper_rejects_malformed_pids_without_process_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    record = _tunnel_record(tmp_path, **{field: value})

    def unexpected(*args: object, **kwargs: object) -> None:
        raise AssertionError("malformed record reached a process operation")

    monkeypatch.setattr(ssh_module.os, "kill", unexpected)
    monkeypatch.setattr(psutil, "Process", unexpected)
    assert reap_stale_tunnels(tmp_path) == []
    assert not record.exists()


def test_reaper_does_not_signal_reused_child_pid_even_with_identical_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _tunnel_record(tmp_path)
    child = _ReapProcess(880001, 200.0, json.loads(record.read_text())["argv"])
    _mock_reaper_processes(monkeypatch, {child.pid: child})
    assert reap_stale_tunnels(tmp_path) == []
    assert child.signals == []
    assert not record.exists()  # the original process is confirmed gone


def test_reaper_handles_reused_owner_pid_and_stops_exact_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _tunnel_record(tmp_path)
    child = _ReapProcess(880001, 100.0, json.loads(record.read_text())["argv"])
    owner = _ReapProcess(880002, 90.0, ["unrelated"])
    _mock_reaper_processes(monkeypatch, {child.pid: child, owner.pid: owner})
    assert reap_stale_tunnels(tmp_path) == [child.pid]
    assert child.signals == [signal.SIGTERM]
    assert child.gone
    assert owner.signals == []
    assert not record.exists()


def test_reaper_preserves_record_when_process_inspection_is_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _tunnel_record(tmp_path)
    child = _ReapProcess(880001, 100.0, json.loads(record.read_text())["argv"])
    child.denied = True
    _mock_reaper_processes(monkeypatch, {child.pid: child})
    assert reap_stale_tunnels(tmp_path) == []
    assert child.signals == []
    assert record.exists()


def test_reaper_keeps_legacy_live_record_without_signalling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _tunnel_record(tmp_path)
    data = json.loads(record.read_text())
    del data["pid_create_time"]
    del data["owner_create_time"]
    record.write_text(json.dumps(data))
    child = _ReapProcess(880001, 100.0, data["argv"])
    _mock_reaper_processes(monkeypatch, {child.pid: child})
    assert reap_stale_tunnels(tmp_path) == []
    assert child.signals == []
    assert record.exists()


@pytest.mark.parametrize("wait_failures", [1, 2])
def test_reaper_bounds_termination_and_preserves_incomplete_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wait_failures: int
) -> None:
    record = _tunnel_record(tmp_path)
    child = _ReapProcess(880001, 100.0, json.loads(record.read_text())["argv"])
    child.wait_failures = wait_failures
    _mock_reaper_processes(monkeypatch, {child.pid: child})
    assert reap_stale_tunnels(tmp_path) == ([child.pid] if wait_failures == 1 else [])
    assert child.signals == [signal.SIGTERM, signal.SIGKILL]
    assert len(child.waits) == 2 and all(t is not None and 0 < t <= 5 for t in child.waits)
    assert record.exists() == (wait_failures == 2)


def test_tunnel_registration_failure_stops_spawned_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = _ReapProcess(880001, 100.0, [])

    def poll() -> int | None:
        return 0 if child.gone else None

    monkeypatch.setattr(child, "poll", poll, raising=False)
    monkeypatch.setattr(ssh_module.subprocess, "Popen", lambda *a, **kw: child)
    monkeypatch.setattr(ssh_module, "_port_open", lambda port: False)

    def fail_registration(*args: object, **kwargs: object) -> None:
        raise OSError("registry unavailable")

    monkeypatch.setattr(ssh_module, "_register_tunnel", fail_registration)
    tunnel = Tunnel(SshTarget(alias="fake"), 7777, local_port=55000, registry=tmp_path)
    with pytest.raises(OSError, match="registry unavailable"):
        tunnel.start()
    assert child.gone
    assert child.signals == [signal.SIGTERM]
    assert not tunnel.alive()


def test_private_tunnel_forwards_without_tcp_and_cleans_up(
    fake_remote: FakeRemote, echo_port: int
) -> None:
    fake_remote.add_host("gpu1")
    tunnel = Tunnel(fake_remote.target("gpu1"), echo_port, private=True)
    assert tunnel.local_port is None
    with tunnel:
        path = tunnel.unix_socket
        assert path is not None and path.is_socket()
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert path.stat().st_mode & 0o777 == 0o600
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(path))
            client.sendall(b"private")
            assert client.recv(7) == b"private"
        assert "StreamLocalBindMask=0177" in tunnel.argv()
        assert "StreamLocalBindUnlink=no" in tunnel.argv()
    assert not path.parent.exists()


def test_private_tunnel_rejects_tcp_port(fake_remote: FakeRemote) -> None:
    with pytest.raises(ValueError, match="private"):
        Tunnel(fake_remote.target("gpu1"), 7777, local_port=7778, private=True)


@pytest.mark.parametrize("stage", ["marker", "partial-marker", "stderr", "popen"])
def test_private_tunnel_constructor_failures_cleanup_owned_directory(
    fake_remote: FakeRemote, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    allocated: list[Path] = []
    original = ssh_module.tempfile.mkdtemp

    def allocate(*args: object, **kwargs: object) -> str:
        path = original(*args, **kwargs)
        allocated.append(Path(path))
        return path

    def fail(*args: object, **kwargs: object) -> None:
        raise PermissionError("injected construction failure")

    monkeypatch.setattr(ssh_module.tempfile, "mkdtemp", allocate)
    if stage == "partial-marker":
        original_write = Path.write_text

        def partial_write(path: Path, text: str, **kwargs: object) -> None:
            original_write(path, text[:2])
            raise PermissionError("injected partial marker failure")

        monkeypatch.setattr(Path, "write_text", partial_write)
    elif stage == "marker":
        monkeypatch.setattr(Path, "write_text", fail)
    elif stage == "stderr":
        monkeypatch.setattr(ssh_module.tempfile, "TemporaryFile", fail)
    else:
        monkeypatch.setattr(ssh_module.subprocess, "Popen", fail)
    tunnel = Tunnel(fake_remote.target("gpu1"), 7777, private=True)
    with pytest.raises(PermissionError):
        tunnel.start()
    assert allocated and not allocated[0].exists()
    assert tunnel.unix_socket is None and tunnel._stderr is None


def test_private_tunnel_cleanup_keeps_replaced_socket(
    fake_remote: FakeRemote, echo_port: int
) -> None:
    fake_remote.add_host("gpu1")
    tunnel = Tunnel(fake_remote.target("gpu1"), echo_port, private=True)
    tunnel.start()
    path = tunnel.unix_socket
    assert path is not None
    path.unlink()
    path.write_text("replacement evidence")
    try:
        tunnel.stop()
        assert path.read_text() == "replacement evidence"
    finally:
        path.unlink()
        (path.parent / ".owner").unlink()
        path.parent.rmdir()


@pytest.mark.parametrize("owner_matches", [True, False])
def test_stale_private_directory_cleanup_requires_owner_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner_matches: bool
) -> None:
    import tempfile

    folder = Path(tempfile.mkdtemp(prefix="hx-tun-", dir="/tmp"))
    owner = uuid.uuid4().hex
    marker = folder / ".owner"
    marker.write_text(owner if owner_matches else "another-owner")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(folder / "s"))
    sock.close()
    record = _tunnel_record(tmp_path / "registry", socket_dir=folder.name, socket_owner=owner)
    _mock_reaper_processes(monkeypatch, {})
    try:
        assert reap_stale_tunnels(record.parent) == []
        assert folder.exists() is not owner_matches
        assert not record.exists()
    finally:
        if folder.exists():
            (folder / "s").unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
            folder.rmdir()
