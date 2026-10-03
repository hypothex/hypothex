"""
Bootstrap ``hx`` on a remote host over the user's own ``ssh``.

Four steps, each a POSIX ``sh`` script from ``hypothex/remote/scripts`` run with
:func:`hypothex.remote.ssh.run_remote`: probe the host, build and copy this
package's wheel, install it with ``uv tool install`` under ``<home>/runtime``,
and start (or reuse) ``hx serve`` bound to ``127.0.0.1``.

Scripts report results as stdout lines ``HX:<key>=<value>`` (``HX:log=`` may
repeat, ``HX:error=`` means failure); any other output, such as a login banner,
is ignored.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import uuid
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, Field

import hypothex
from hypothex._version import __version__
from hypothex.core.errors import HypothexError
from hypothex.remote.ssh import SshTarget, run_remote

_PREFIX = "HX:"
_PARAM = re.compile(r"^HX_[A-Z_]+$")
_SKIP_DIRS = {"__pycache__"}
_SKIP_SUFFIXES = {".pyc", ".pyo"}


class BootstrapError(HypothexError):
    """Probing, installing, or starting ``hx`` on a remote host failed."""


class ProbeResult(BaseModel):
    """
    Facts about a remote host, from the ``probe`` script.

    Parameters
    ----------
    os : str
        Lower-case ``uname -s``, e.g. ``"linux"``.
    arch : str
        ``uname -m``, e.g. ``"x86_64"``.
    python : str or None
        Version of the first Python >= 3.11 on ``PATH``, else None.
    uv : str or None
        ``uv`` version (``PATH``, ``~/.local/bin``, or ``~/.cargo/bin``), else None.
    gpus : int
        Number of ``GPU`` lines from ``nvidia-smi -L``; 0 without ``nvidia-smi``.
    slurm : str or None
        SLURM version from ``sbatch --version``, else None.
    home : str
        Absolute Hypothex home on the host (``~`` expanded).
    """

    os: str
    arch: str
    python: str | None
    uv: str | None
    gpus: int
    slurm: str | None
    home: str


class ServerInfo(BaseModel):
    """
    One env server, as recorded in ``<home>/serve/server.json``.

    Parameters
    ----------
    pid : int
        Process id on the host.
    port : int
        Port on the host's ``127.0.0.1``.
    managed : bool
        True when Hypothex started it (and so may stop it).
    hx_version : str
        Version from the server's descriptor.
    protocol_version : int
        Protocol version from the server's descriptor.
    token : str or None
        Bearer token the env server requires (``Authorization: Bearer``); None
        for a server without one. Kept out of ``model_dump`` and ``repr`` so it
        is never printed (``hx hosts add --json``).
    """

    pid: int
    port: int
    managed: bool
    hx_version: str
    protocol_version: int
    token: str | None = Field(default=None, repr=False, exclude=True)


def _load_scripts() -> dict[str, str]:
    folder = resources.files("hypothex.remote") / "scripts"
    common = (folder / "common.sh").read_text(encoding="utf-8")
    scripts: dict[str, str] = {}
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".sh") and entry.name != "common.sh":
            scripts[entry.name[: -len(".sh")]] = common + entry.read_text(encoding="utf-8")
    return scripts


BOOTSTRAP_SCRIPTS: dict[str, str] = _load_scripts()
"""Script name -> full POSIX ``sh`` text (``common.sh`` prelude + body)."""


def _render(name: str, **params: str) -> str:
    """
    Return script ``name`` with shell-quoted ``HX_*`` assignments in front.

    Parameters
    ----------
    name : str
        A key of :data:`BOOTSTRAP_SCRIPTS`.
    **params : str
        Variables such as ``HX_HOME``; names must match ``HX_[A-Z_]+``.

    Returns
    -------
    str
        Script text ready for ``sh -s``.

    Examples
    --------
    >>> _render("probe", HX_HOME="~/.hypothex").splitlines()[0]
    "HX_HOME='~/.hypothex'"
    """
    lines = []
    for key, value in params.items():
        if not _PARAM.match(key):
            raise ValueError(f"bad script parameter name {key!r}")
        lines.append(f"{key}={shlex.quote(value)}")
    return "\n".join(lines) + "\n" + BOOTSTRAP_SCRIPTS[name]


def _parse_output(text: str) -> tuple[dict[str, str], list[str]]:
    """
    Split script stdout into ``HX:key=value`` results and ``HX:log=`` lines.

    Parameters
    ----------
    text : str
        Script stdout; lines without the ``HX:`` prefix are ignored.

    Returns
    -------
    tuple of (dict of str to str, list of str)
        Results (last value wins) and log lines in order.

    Examples
    --------
    >>> _parse_output("Welcome!\\nHX:os=linux\\nHX:log=a\\nHX:log=b\\n")
    ({'os': 'linux'}, ['a', 'b'])
    """
    values: dict[str, str] = {}
    logs: list[str] = []
    for line in text.splitlines():
        if not line.startswith(_PREFIX):
            continue
        key, sep, value = line[len(_PREFIX) :].partition("=")
        if not sep:
            continue
        if key == "log":
            logs.append(value)
        else:
            values[key] = value
    return values, logs


def _run_script(
    target: SshTarget, name: str, *, timeout: float = 120, **params: str
) -> tuple[dict[str, str], list[str]]:
    """
    Run one bootstrap script on ``target`` and return its parsed output.

    Raises
    ------
    BootstrapError
        The script exited non-zero or reported ``HX:error=``; the message
        carries the error and any ``HX:log=`` lines.
    """
    proc = run_remote(target, _render(name, **params), timeout=timeout)
    values, logs = _parse_output(proc.stdout.decode("utf-8", "replace"))
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-20:]
        raise BootstrapError(
            "\n".join([f"{target.alias}: {name} script exited {proc.returncode}", *stderr, *logs])
        )
    if "error" in values:
        raise BootstrapError("\n".join([f"{target.alias}: {values['error']}", *logs]))
    return values, logs


def probe(target: SshTarget, home: str) -> ProbeResult:
    """
    Report OS, arch, Python, uv, GPUs, and SLURM on a host.

    Parameters
    ----------
    target : SshTarget
        Host to probe.
    home : str
        Hypothex home on the host; ``~`` is expanded there.

    Returns
    -------
    ProbeResult
        The host's facts; ``home`` is absolute.

    Raises
    ------
    BootstrapError
        The probe script failed.

    Examples
    --------
    >>> probe(SshTarget(alias="gpu1"), "~/.hypothex").gpus  # doctest: +SKIP
    4
    """
    values, _ = _run_script(target, "probe", HX_HOME=home)
    try:
        return ProbeResult(
            os=values["os"],
            arch=values["arch"],
            python=values.get("python") or None,
            uv=values.get("uv") or None,
            gpus=int(values.get("gpus") or 0),
            slurm=values.get("slurm") or None,
            home=values["home"],
        )
    except (KeyError, ValueError) as exc:
        raise BootstrapError(f"{target.alias}: probe output is incomplete: {exc}") from exc


def _source_root() -> Path | None:
    """
    Return the source checkout this ``hypothex`` was imported from, if any.

    Returns
    -------
    Path or None
        The folder holding ``pyproject.toml`` (named ``hypothex``) two levels
        above the package, or None for an installed wheel.
    """
    root = Path(hypothex.__file__).resolve().parents[2]
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and 'name = "hypothex"' in pyproject.read_text(encoding="utf-8"):
        return root
    return None


def _source_digest(root: Path) -> str:
    """
    Hash ``pyproject.toml`` and every file under ``src/hypothex``.

    Paths and contents both count, so an edit, a new file, or a rename gives a
    new digest. ``__pycache__`` folders and ``.pyc`` files are skipped.

    Parameters
    ----------
    root : Path
        Source checkout root.

    Returns
    -------
    str
        First 12 hex digits of a SHA-256.
    """
    digest = hashlib.sha256()
    files = [root / "pyproject.toml"]
    for dirpath, dirnames, filenames in os.walk(root / "src" / "hypothex"):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        files.extend(
            Path(dirpath) / f for f in sorted(filenames) if Path(f).suffix not in _SKIP_SUFFIXES
        )
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()[:12]


def _uv_bin() -> str:
    """Return the hub's ``uv`` executable or raise :class:`BootstrapError`."""
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (Path.home() / ".local/bin/uv", Path.home() / ".cargo/bin/uv"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise BootstrapError(
        "uv is needed on this machine to build the hypothex wheel; "
        "install it from https://docs.astral.sh/uv/"
    )


def _uv_build(root: Path, out_dir: Path) -> Path:
    """
    Run ``uv build --wheel`` for ``root`` into ``out_dir``.

    Returns
    -------
    Path
        The single ``hypothex-*.whl`` produced.
    """
    proc = subprocess.run(
        [_uv_bin(), "build", "--wheel", "--out-dir", str(out_dir), str(root)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-20:]
        raise BootstrapError("\n".join(["uv build --wheel failed:", *tail]))
    wheels = sorted(out_dir.glob("hypothex-*.whl"))
    if len(wheels) != 1:
        raise BootstrapError(f"uv build produced {len(wheels)} hypothex wheels in {out_dir}")
    return wheels[0]


def _download_wheel(out_dir: Path) -> Path:
    """
    Download this exact hypothex release from the package index into ``out_dir``.

    For an installed (non-checkout) hub. uv has no ``pip download``, so a
    throwaway pip runs under ``uv tool run --from pip``.

    Returns
    -------
    Path
        The single ``hypothex-<version>-*.whl`` downloaded.

    Raises
    ------
    BootstrapError
        The download failed (no network, or this version is not published).
    """
    argv = [_uv_bin(), "tool", "run", "--from", "pip", "pip", "download"]
    argv += [f"hypothex=={__version__}", "--no-deps", "--only-binary=:all:", "--dest", str(out_dir)]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    wheels = sorted(out_dir.glob(f"hypothex-{__version__}-*.whl"))
    if proc.returncode != 0 or len(wheels) != 1:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
        raise BootstrapError(
            "\n".join(
                [
                    f"cannot get a wheel of hypothex {__version__} from the package index; "
                    "run hx from a source checkout or publish this version",
                    *tail,
                ]
            )
        )
    return wheels[0]


def build_wheel(cache_dir: Path) -> Path:
    """
    Return a wheel of the running ``hypothex``, building it once per version.

    The cache key is the version; for a source checkout it is the version plus a
    digest of the sources, so editing code without a version bump still ships the
    new code. A wheel already in ``cache_dir/<key>/`` is reused. A source checkout
    is built with ``uv build --wheel``; an installed hub downloads its own
    release from the package index.

    Parameters
    ----------
    cache_dir : Path
        Folder for cached wheels, e.g. ``<hub home>/cache/wheels``.

    Returns
    -------
    Path
        Path of ``hypothex-<version>-py3-none-any.whl``.

    Raises
    ------
    BootstrapError
        ``uv`` missing, the build failed, or (installed hub) this release could
        not be downloaded.

    Examples
    --------
    >>> build_wheel(Path("~/.hypothex/cache/wheels").expanduser()).name  # doctest: +SKIP
    'hypothex-0.1.0.dev0-py3-none-any.whl'
    """
    root = _source_root()
    key = __version__ if root is None else f"{__version__}-{_source_digest(root)}"
    final = cache_dir / key
    cached = sorted(final.glob("hypothex-*.whl"))
    if cached:
        return cached[0]
    cache_dir.mkdir(parents=True, exist_ok=True)
    staging = cache_dir / f".build-{key}-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    try:
        wheel = _uv_build(root, staging) if root is not None else _download_wheel(staging)
        try:
            staging.rename(final)
        except OSError:  # another build won the race; use its wheel
            shutil.rmtree(staging, ignore_errors=True)
            return sorted(final.glob("hypothex-*.whl"))[0]
        return final / wheel.name
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
