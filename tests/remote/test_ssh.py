import functools
import http.server
import json
import os
import socket
import socketserver
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from hypothex.remote.ssh import (
    SshError,
    SshTarget,
    Tunnel,
    _free_port,
    copy_from,
    copy_to,
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
