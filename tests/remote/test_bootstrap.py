"""Tests for hypothex.remote.bootstrap, run through a fake ssh into a temp home."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from hypothex.remote import bootstrap as bs
from hypothex.remote.bootstrap import BootstrapError, ProbeResult, probe
from hypothex.remote.ssh import SshTarget
from tests.fakes import install_fake_remote

PY = sys.executable
# Real tools the fake host may use. Linked one by one into a "toolbin" so the
# fake host's PATH holds exactly these plus the test's fakes: no stray python3.x,
# uv, nvidia-smi, or sbatch from the machine running the tests.
HOST_TOOLS = (
    "sh", "uname", "sed", "grep", "tr", "head", "tail", "cat", "mkdir", "rm", "mv", "cp",
    "hostname", "find", "ps", "sleep", "nohup", "env", "curl", "wc", "chmod", "ls",
    "od", "rmdir", "touch", "cut",
)  # fmt: skip


def _write_exec(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


@dataclass
class FakeHost:
    """The fake host ``gpu1`` of the shared fake ssh/scp (``tests/fakes``)."""

    remote_home: Path
    fakebin: Path
    target: SshTarget
    log: Path

    @property
    def hx_home(self) -> Path:
        return self.remote_home / ".hypothex"

    def add_tool(self, name: str, body: str) -> Path:
        """Put an executable ``sh`` script ``name`` on the host's PATH."""
        return _write_exec(self.fakebin / name, "#!/bin/sh\n" + body)

    def calls(self) -> list[list[str]]:
        """Each fake ssh/scp call as ``[prog, *argv]``."""
        if not self.log.exists():
            return []
        rows = [json.loads(line) for line in self.log.read_text().splitlines() if line]
        return [[row["prog"], *row["argv"]] for row in rows]


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeHost:
    fake = install_fake_remote(tmp_path / "fake-remote", monkeypatch)
    remote_home = fake.add_host("gpu1")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    toolbin = tmp_path / "toolbin"
    toolbin.mkdir()
    for name in HOST_TOOLS:
        found = shutil.which(name)
        if found is None:
            pytest.skip(f"{name} not found on this machine")
        (toolbin / name).symlink_to(found)
    # The host's PATH is exactly these two folders (no ~/.local/bin, as with a
    # non-interactive ssh that reads no rc files).
    monkeypatch.setenv("HYPOTHEX_FAKE_REMOTE_PATH", f"{fakebin}:{toolbin}")
    return FakeHost(
        remote_home=remote_home, fakebin=fakebin, target=fake.target("gpu1"), log=fake.log_path
    )


# ---------------------------------------------------------------- scripts, parsing
def test_parse_output_ignores_banner_noise() -> None:
    text = "Welcome to gpu1!\nos=linux\nHX:os=linux\nHX:log=a=1\nHX:junk\nHX:log=b\n"
    values, logs = bs._parse_output(text)
    assert values == {"os": "linux"}
    assert logs == ["a=1", "b"]


def test_render_quotes_parameters() -> None:
    script = bs._render("probe", HX_HOME="/tmp/a b'c")
    assert script.splitlines()[0] == "HX_HOME='/tmp/a b'\"'\"'c'"
    assert "hx_expand_home()" in script
    with pytest.raises(ValueError, match="bad script parameter"):
        bs._render("probe", home="/x")


def test_scripts_are_valid_posix_sh(tmp_path: Path) -> None:
    shells = [s for s in ("sh", "dash") if shutil.which(s)]
    for name, text in bs.BOOTSTRAP_SCRIPTS.items():
        path = tmp_path / f"{name}.sh"
        path.write_text(text, encoding="utf-8")
        for shell in shells:
            done = subprocess.run([shell, "-n", str(path)], capture_output=True, text=True)
            assert done.returncode == 0, (name, shell, done.stderr)


# -------------------------------------------------------------------------- probe
def test_probe_reports_tools(host: FakeHost) -> None:
    host.add_tool("python3", f'exec {PY} "$@"\n')
    host.add_tool("uv", 'echo "uv 0.9.2 (141369ce7 2025-10-10)"\n')
    host.add_tool(
        "nvidia-smi", 'echo "GPU 0: NVIDIA A100 (UUID: a)"\necho "GPU 1: NVIDIA A100 (UUID: b)"\n'
    )
    host.add_tool("sbatch", 'echo "slurm 23.02.7"\n')
    result = probe(host.target, "~/.hypothex")
    v = sys.version_info
    assert result == ProbeResult(
        os=platform.system().lower(),
        arch=platform.machine(),
        python=f"{v.major}.{v.minor}.{v.micro}",
        uv="0.9.2",
        gpus=2,
        slurm="23.02.7",
        home=str(host.hx_home),
    )
    assert host.calls()[0][0] == "ssh" and "gpu1" in host.calls()[0]
    assert not (host.remote_home / "~").exists()


def test_probe_bare_host(host: FakeHost) -> None:
    host.add_tool("python3", "echo 3.9.6\n")  # too old: probe must report None
    result = probe(host.target, "/srv/hx")
    assert result.python is None
    assert result.uv is None
    assert result.gpus == 0
    assert result.slurm is None
    assert result.home == "/srv/hx"


def test_probe_finds_uv_off_path(host: FakeHost) -> None:
    local_bin = host.remote_home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    _write_exec(local_bin / "uv", '#!/bin/sh\necho "uv 0.8.0"\n')
    assert probe(host.target, "~/.hypothex").uv == "0.8.0"


def test_probe_script_crash_is_bootstrap_error(
    host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(bs.BOOTSTRAP_SCRIPTS, "probe", "echo boom >&2\nexit 3\n")
    with pytest.raises(BootstrapError, match="probe script exited 3") as info:
        probe(host.target, "~/.hypothex")
    assert "boom" in str(info.value)


# --------------------------------------------------------------------------- lock
COMMON_SH = Path(bs.__file__).parent / "scripts" / "common.sh"


def _hostname() -> str:
    return subprocess.run(["hostname"], capture_output=True, text=True, check=True).stdout.strip()


def _sh(body: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run ``body`` after the common.sh prelude with this machine's ``sh``."""
    script = COMMON_SH.read_text(encoding="utf-8") + "\n" + body
    return subprocess.run(
        ["sh", "-c", script], capture_output=True, text=True, timeout=60, env={**os.environ, **env}
    )


def _birth(pid: int) -> str:
    return _sh(f"hx_pid_start {pid}").stdout.strip()


def _held_lock(lock: Path, owner: str, *, age: float = 0) -> None:
    """A mkdir lock as another process left it: the owner line, aged ``age`` seconds."""
    lock.mkdir(parents=True)
    (lock / "owner").write_text(owner + "\n")
    os.utime(lock, (time.time() - age, time.time() - age))


LOCK_TOOLS = ("sh", "hostname", "ps", "sleep", "cat", "mkdir", "rm", "rmdir", "sed", "cut", "tr")
LOCK_MODES = ("flock", "python3", "mkdir")


def _lock_path(tmp_path: Path, mode: str) -> str:
    """A ``PATH`` with the tools common.sh needs, plus ``flock`` or ``python3`` for ``mode``."""
    folder = tmp_path / f"lockbin-{mode}"
    folder.mkdir(exist_ok=True)
    tools = {name: shutil.which(name) for name in LOCK_TOOLS}
    if mode == "flock":
        tools["flock"] = shutil.which("flock")
    elif mode == "python3":
        tools["python3"] = PY
    for name, found in tools.items():
        if found is None:
            pytest.skip(f"{name} not found on this machine")
        link = folder / name
        if not link.exists():
            link.symlink_to(found)
    return str(folder)


def _take(lock: Path, path: str | None = None, wait: str = "1") -> str:
    env = {"HX_LOCK_WAIT": wait, **({"PATH": path} if path else {})}
    return _sh(f'hx_lock "{lock}"\necho "HX:mode=$HX_LOCK_MODE"', **env).stdout


def _hold(lock: Path, path: str, *, seconds: int, exec_sleep: bool) -> subprocess.Popen[str]:
    """A script that takes the lock, says so, then sleeps (``exec``: no EXIT trap ever runs)."""
    sleep = f"exec sleep {seconds}" if exec_sleep else f"sleep {seconds}"
    script = (
        COMMON_SH.read_text(encoding="utf-8")
        + f'\nhx_lock "{lock}"\necho "HX:held=$HX_LOCK_MODE"\n{sleep}\n'
    )
    proc = subprocess.Popen(
        ["sh", "-c", script], stdout=subprocess.PIPE, text=True, env={**os.environ, "PATH": path}
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert line.startswith("HX:held="), line
    return proc


def test_pid_start_tells_a_recycled_pid_apart() -> None:
    me = _birth(os.getpid())
    assert me
    assert _sh(f'hx_same_proc {os.getpid()} "{me}" && echo same').stdout == "same\n"
    other = _sh(f'hx_same_proc {os.getpid()} "Mon Jan 1 00:00:00 2001" || echo other')
    assert other.stdout == "other\n"


@pytest.mark.parametrize("mode", LOCK_MODES)
def test_lock_picks_flock_then_python3_then_mkdir(tmp_path: Path, mode: str) -> None:
    assert f"HX:mode={mode}\n" in _take(tmp_path / "L", _lock_path(tmp_path, mode))


@pytest.mark.parametrize("mode", LOCK_MODES)
def test_a_held_lock_excludes_others_and_is_released_on_exit(tmp_path: Path, mode: str) -> None:
    path = _lock_path(tmp_path, mode)
    lock = tmp_path / "L"
    holder = _hold(lock, path, seconds=3, exec_sleep=False)
    try:
        out = _take(lock, path)
        assert "HX:error=lock" in out and str(lock) in out
    finally:
        holder.wait(timeout=30)
    assert f"HX:mode={mode}" in _take(lock, path, wait="5")
    assert not lock.is_dir()  # a mkdir lock is removed by the EXIT trap


@pytest.mark.parametrize("mode", ["flock", "python3"])
def test_an_os_lock_is_released_when_its_holder_is_killed(tmp_path: Path, mode: str) -> None:
    path = _lock_path(tmp_path, mode)
    lock = tmp_path / "L"
    holder = _hold(lock, path, seconds=60, exec_sleep=True)
    holder.kill()  # SIGKILL: no trap runs; the OS lock still goes with its holder
    holder.wait()
    start = time.monotonic()
    assert f"HX:mode={mode}" in _take(lock, path, wait="10")
    assert time.monotonic() - start < 5


def test_mkdir_lock_of_a_dead_owner_on_this_host_is_broken(tmp_path: Path) -> None:
    dead = subprocess.Popen(["true"])
    dead.wait()
    lock = tmp_path / "L"
    _held_lock(lock, f"{_hostname()}|{dead.pid}|")
    assert "HX:mode=mkdir" in _take(lock, _lock_path(tmp_path, "mkdir"))
    assert not lock.exists()  # released when the script exits


def test_mkdir_lock_of_a_recycled_pid_is_broken(tmp_path: Path) -> None:
    lock = tmp_path / "L"
    _held_lock(lock, f"{_hostname()}|{os.getpid()}|Mon Jan 1 00:00:00 2001")
    assert "HX:mode=mkdir" in _take(lock, _lock_path(tmp_path, "mkdir"))


def test_mkdir_lock_of_a_live_owner_is_never_broken(tmp_path: Path) -> None:
    lock = tmp_path / "L"
    owner = f"{_hostname()}|{os.getpid()}|{_birth(os.getpid())}"
    _held_lock(lock, owner, age=3600)  # held for an hour: still alive, still its lock
    out = _take(lock, _lock_path(tmp_path, "mkdir"))
    assert "HX:error=lock" in out and "waited 1s" in out
    assert (lock / "owner").read_text().strip() == owner


def test_mkdir_lock_of_another_host_is_never_broken(tmp_path: Path) -> None:
    # a shared home: another login node's owner cannot be checked, however old its lock
    lock = tmp_path / "L"
    _held_lock(lock, "login2|4242|x", age=86400)
    out = _take(lock, _lock_path(tmp_path, "mkdir"))
    assert "HX:error=lock" in out and f"remove {lock}" in out
    assert (lock / "owner").read_text().strip() == "login2|4242|x"


# ---------------------------------------------------------------------- build_wheel
@pytest.fixture(scope="session")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("uv") is None and not (Path.home() / ".local/bin/uv").exists():
        pytest.skip("uv is not installed")
    return bs.build_wheel(tmp_path_factory.mktemp("wheels"))


def test_build_wheel_contents(wheel: Path) -> None:
    import zipfile

    from hypothex import __version__

    assert wheel.name == f"hypothex-{__version__}-py3-none-any.whl"
    names = set(zipfile.ZipFile(wheel).namelist())
    assert "hypothex/remote/bootstrap.py" in names
    assert {f"hypothex/remote/scripts/{n}.sh" for n in ("common", "probe")} <= names


def test_build_wheel_is_cached(wheel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_build(root: Path, out_dir: Path) -> Path:
        raise AssertionError("must reuse the cached wheel")

    monkeypatch.setattr(bs, "_uv_build", no_build)
    mtime = wheel.stat().st_mtime_ns
    again = bs.build_wheel(wheel.parent.parent)
    assert again == wheel
    assert again.stat().st_mtime_ns == mtime


def test_build_wheel_key_includes_source_digest(wheel: Path) -> None:
    from hypothex import __version__

    root = bs._source_root()
    assert root is not None
    assert wheel.parent.name == f"{__version__}-{bs._source_digest(root)}"


def test_source_digest_tracks_content_not_caches(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "hypothex"
    pkg.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "hypothex"\n')
    (pkg / "a.py").write_text("x = 1\n")
    first = bs._source_digest(tmp_path)
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "a.cpython-311.pyc").write_bytes(b"\x00junk")
    (pkg / "b.pyc").write_bytes(b"\x00junk")
    assert bs._source_digest(tmp_path) == first
    (pkg / "a.py").write_text("x = 2\n")
    second = bs._source_digest(tmp_path)
    assert second != first and len(second) == 12
    (pkg / "a.py").rename(pkg / "c.py")
    assert bs._source_digest(tmp_path) != second


def _installed_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, published: bool) -> Path:
    """Act as a non-editable install whose ``uv`` is a fake; return the fake's call log."""
    from hypothex import __version__

    log = tmp_path / "uv-calls.txt"
    if published:
        result = f'printf PK > "$dest/hypothex-{__version__}-py3-none-any.whl"\n'
    else:
        result = (
            f'echo "ERROR: No matching distribution found for hypothex=={__version__}" >&2\n'
            "exit 1\n"
        )
    fake_uv = _write_exec(
        tmp_path / "uv",
        "#!/bin/sh\n"
        f'echo "$@" >> {log}\n'
        'dest=""\n'
        'while [ $# -gt 0 ]; do [ "$1" = "--dest" ] && dest=$2; shift; done\n' + result,
    )
    monkeypatch.setattr(bs, "_source_root", lambda: None)
    monkeypatch.setattr(bs, "_uv_bin", lambda: str(fake_uv))
    return log


def test_installed_hub_downloads_its_own_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypothex import __version__

    log = _installed_hub(tmp_path, monkeypatch, published=True)
    wheel = bs.build_wheel(tmp_path / "cache")
    assert wheel == tmp_path / "cache" / __version__ / f"hypothex-{__version__}-py3-none-any.whl"
    argv = log.read_text().split()
    assert argv[:6] == ["tool", "run", "--from", "pip", "pip", "download"]
    assert f"hypothex=={__version__}" in argv and "--no-deps" in argv
    assert bs.build_wheel(tmp_path / "cache") == wheel  # cached: no second download
    assert len(log.read_text().splitlines()) == 1


def test_installed_hub_without_a_published_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _installed_hub(tmp_path, monkeypatch, published=False)
    with pytest.raises(
        BootstrapError, match="run hx from a source checkout or publish this version"
    ) as info:
        bs.build_wheel(tmp_path / "cache")
    assert "No matching distribution" in str(info.value)
    assert [p.name for p in (tmp_path / "cache").iterdir()] == []


def test_build_wheel_without_uv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bs.shutil, "which", lambda name: None)
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(BootstrapError, match="uv is needed on this machine"):
        bs.build_wheel(tmp_path / "cache")
    assert [p.name for p in (tmp_path / "cache").iterdir()] == []


# -------------------------------------------------------------------------- install
def _real_uv() -> str:
    found = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    if not Path(found).exists():
        pytest.skip("uv is not installed")
    return found


@pytest.fixture
def uv_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point the host's uv at this machine's cache, offline, with this Python."""
    uv = _real_uv()
    cache = subprocess.run([uv, "cache", "dir"], capture_output=True, text=True, check=True)
    monkeypatch.setenv("UV_CACHE_DIR", cache.stdout.strip())
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_PYTHON", PY)
    return uv


def _installed_version(host: FakeHost) -> str:
    hx = host.hx_home / "runtime" / "bin" / "hx"
    return subprocess.run(
        [str(hx), "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_install_puts_hx_under_runtime(host: FakeHost, wheel: Path, uv_env: str) -> None:
    from hypothex import __version__

    host.add_tool("uv", f'exec {uv_env} "$@"\n')
    bs.install(host.target, "~/.hypothex", wheel)
    runtime = host.hx_home / "runtime"
    assert _installed_version(host) == __version__
    assert (runtime / "wheels" / wheel.name).is_file()
    assert [p.name for p in (runtime / "wheels").iterdir()] == [wheel.name]
    assert (runtime / "tools" / "hypothex").is_dir()
    assert not (runtime / ".lock").exists()
    assert [c[0] for c in host.calls()] == ["ssh", "scp", "ssh"]
    # A second install of the same wheel works (--force) and leaves one wheel.
    bs.install(host.target, "~/.hypothex", wheel)
    assert _installed_version(host) == __version__


def test_install_bootstraps_missing_uv(host: FakeHost, wheel: Path, uv_env: str) -> None:
    from hypothex import __version__

    # Fake curl serves an "installer" that drops a uv shim into $UV_INSTALL_DIR.
    installer = (
        'mkdir -p "$UV_INSTALL_DIR"\n'
        f'printf \'#!/bin/sh\\nexec {uv_env} "$@"\\n\' > "$UV_INSTALL_DIR/uv"\n'
        'chmod +x "$UV_INSTALL_DIR/uv"\n'
    )
    script = host.fakebin / "installer.sh"
    script.write_text(installer)
    host.add_tool(
        "curl", f'case "$*" in *astral.sh/uv/install.sh*) cat {script};; *) exit 7;; esac\n'
    )
    bs.install(host.target, "~/.hypothex", wheel)
    assert (host.remote_home / ".local" / "bin" / "uv").is_file()
    assert _installed_version(host) == __version__


def test_install_without_uv_or_network(host: FakeHost, wheel: Path) -> None:
    host.add_tool("curl", 'echo "curl: (6) Could not resolve host: astral.sh" >&2\nexit 6\n')
    with pytest.raises(BootstrapError, match="uv is missing on the host") as info:
        bs.install(host.target, "~/.hypothex", wheel)
    message = str(info.value)
    assert "https://astral.sh/uv/install.sh" in message
    assert "Could not resolve host" in message
    assert not (host.hx_home / "runtime" / "bin" / "hx").exists()
    assert not (host.hx_home / "runtime" / ".lock").exists()


def test_install_reports_uv_failure_with_log(host: FakeHost, tmp_path: Path, uv_env: str) -> None:
    host.add_tool("uv", f'exec {uv_env} "$@"\n')
    bad = tmp_path / "hypothex-0.0.1-py3-none-any.whl"
    bad.write_bytes(b"not a zip file")
    with pytest.raises(BootstrapError, match="uv tool install failed for hypothex-0.0.1") as info:
        bs.install(host.target, "~/.hypothex", bad)
    assert len(str(info.value).splitlines()) > 1  # carries uv's own output


def test_install_missing_local_wheel(host: FakeHost, tmp_path: Path) -> None:
    with pytest.raises(BootstrapError, match="wheel not found"):
        bs.install(host.target, "~/.hypothex", tmp_path / "nope.whl")
    assert host.calls() == []


def test_install_breaks_stale_lock(host: FakeHost, wheel: Path, uv_env: str) -> None:
    from hypothex import __version__

    host.add_tool("uv", f'exec {uv_env} "$@"\n')
    lock = host.hx_home / "runtime" / ".lock"
    lock.mkdir(parents=True)
    dead = subprocess.Popen(["true"])
    dead.wait()
    (lock / "owner").write_text(f"{_hostname()}|{dead.pid}|\n")
    bs.install(host.target, "~/.hypothex", wheel)
    assert _installed_version(host) == __version__
    assert not lock.exists()


def test_install_waits_for_live_lock(
    host: FakeHost, wheel: Path, uv_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    host.add_tool("uv", f'exec {uv_env} "$@"\n')
    monkeypatch.setenv("HX_LOCK_WAIT", "1")
    lock = host.hx_home / "runtime" / ".lock"
    lock.mkdir(parents=True)
    (lock / "owner").write_text(f"{_hostname()}|{os.getpid()}|{_birth(os.getpid())}\n")
    with pytest.raises(BootstrapError, match=r"lock .*\.lock is held by .*\|\d+\|.*; waited 1s"):
        bs.install(host.target, "~/.hypothex", wheel)
    assert lock.exists()  # a live owner's lock is never broken
    assert not (host.hx_home / "runtime" / "bin" / "hx").exists()
