"""Stdlib-only owner of isolated wheel builds, processes, fixtures, and evidence."""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

# Pytest must not render private argument values; command errors are sanitized explicitly.
__tracebackhide__ = True

ROOT_MARKER = "__HX_FIXTURE_ROOT__"
PYTHON_MARKER = "__HX_FIXTURE_PYTHON__"
REVISIONS = {
    3: "a4441256f39d014d9ad43dea976af1b448f163e3",
    4: "e73b8105df32a1d2488477c48e680cb5de922771",
}
REFUSED_TOOLS = (
    "ssh",
    "scp",
    "nvidia-smi",
    "sbatch",
    "squeue",
    "sacct",
    "scancel",
    "sinfo",
    "scontrol",
    "srun",
    "salloc",
    "tailscale",
)


class CommandFailure(RuntimeError):
    """A failed controlled command whose raw diagnostics remain private attributes."""

    def __init__(self, operation: str, result: subprocess.CompletedProcess[str]) -> None:
        self.result = result
        super().__init__(f"{operation} exited {result.returncode}")


def child_environment(
    parent: dict[str, str], overrides: dict[str, str] | None = None
) -> dict[str, str]:
    """Copy a child environment, stripping implicit routing and every PG default.

    Parameters
    ----------
    parent : dict
        Caller environment, never mutated.
    overrides : dict, optional
        Explicit scenario settings; PG-prefixed overrides are also removed.

    Returns
    -------
    dict
        Fresh environment retaining ordinary OS variables and explicit non-PG settings.
    """
    clean = {
        key: value
        for key, value in parent.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
        and not key.startswith(("PG", "HYPOTHEX_", "HX_DEMO_"))
        and not key.lower().endswith("_proxy")
    }
    clean.update(overrides or {})
    return {key: value for key, value in clean.items() if not key.startswith("PG")}


def _process_identities() -> dict[int, tuple[int, str, str]]:
    """Read PID, parent, start identity and state without signaling any process."""
    result = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,lstart=,stat="],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
        env=child_environment(dict(os.environ)),
    )
    return {
        int(parts[0]): (int(parts[1]), " ".join(parts[2:7]), parts[7])
        for line in result.stdout.splitlines()
        if len(parts := line.split()) >= 8
    }


def _descendant_identities(pid: int) -> dict[int, str]:
    """Capture descendants, including children that created a separate process group."""
    processes = _process_identities()
    owned = {pid}
    while True:
        children = {child for child, (parent, _, _) in processes.items() if parent in owned}
        expanded = owned | children
        if expanded == owned:
            break
        owned = expanded
    return {child: processes[child][1] for child in owned - {pid}}


def _remaining_descendants(identities: dict[int, str]) -> list[int]:
    """Return only still-live captured identities; never treat a reused PID as owned."""
    processes = _process_identities()
    return [
        pid
        for pid, identity in identities.items()
        if pid in processes
        and processes[pid][1] == identity
        and not processes[pid][2].startswith("Z")
    ]


def _group_alive(group: int) -> bool:
    """Read process-group membership, ignoring reaped-awaiting zombie descendants."""
    result = subprocess.run(
        ["ps", "-eo", "pid=,pgid=,stat="],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
        env=child_environment(dict(os.environ)),
    )
    return any(
        len(parts := line.split()) >= 3 and int(parts[1]) == group and not parts[2].startswith("Z")
        for line in result.stdout.splitlines()
    )


def _terminate(process: subprocess.Popen[str], timeout: float = 5) -> None:
    """Terminate only this owned process group and prove no live members remain."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    if _group_alive(process.pid):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        deadline = time.monotonic() + 5
        while _group_alive(process.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _group_alive(process.pid), "owned process group leaked"


def run_checked(
    argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run a bounded owned process and propagate nonzero or timeout failures.

    Parameters
    ----------
    argv : list of str
        Explicit argument vector.
    cwd : Path
        Explicit working directory.
    env : dict
        Final scenario environment; PG keys are filtered again at launch.
    timeout : float
        Maximum running time in seconds.

    Returns
    -------
    subprocess.CompletedProcess
        Privately captured stdout and stderr on success.

    Raises
    ------
    CommandFailure
        The process exited nonzero; raw diagnostics are private attributes.
    subprocess.TimeoutExpired
        The owned group exceeded its deadline and was terminated.
    """
    final = {key: value for key, value in env.items() if not key.startswith("PG")}
    assert not any(key.startswith("PG") for key in final)
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=final,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate(process)
        process.communicate(timeout=10)
        raise
    result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    if result.returncode:
        raise CommandFailure(Path(argv[0]).name, result)
    return result


def _hash(path: Path) -> str:
    """Hash exact file bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hashes(root: Path) -> dict[str, str]:
    """Snapshot every regular file in a directory, rejecting symlinks."""
    paths = sorted(root.rglob("*"))
    assert not any(path.is_symlink() for path in paths), "fixture contains a symlink"
    return {path.relative_to(root).as_posix(): _hash(path) for path in paths if path.is_file()}


def source_provenance(checkout: Path, status: str) -> dict[str, Any]:
    """Record checkout dirtiness and hashes of build inputs independently of HEAD.

    Parameters
    ----------
    checkout : Path
        Actual source root used for the build.
    status : str
        Git porcelain status including untracked paths.

    Returns
    -------
    dict
        Explicit dirty state, status lines, and hashes of source/resource inputs.
    """
    paths = [checkout / name for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE")]
    paths.extend((checkout / "src").rglob("*"))
    inputs = {
        path.relative_to(checkout).as_posix(): _hash(path)
        for path in sorted(paths)
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    return {
        "source_dirty": bool(status.strip()),
        "source_status": status.splitlines(),
        "source_files": inputs,
    }


def _path(root: Path, relative: str) -> Path:
    """Resolve a manifest path only inside its explicit root."""
    candidate = (root / relative).resolve()
    assert candidate.is_relative_to(root.resolve()), "manifest path escapes fixture"
    return candidate


def _replace(value: Any, destination: Path, interpreter: Path) -> Any:
    """Replace fixture markers in an already allowlisted structured value."""
    if isinstance(value, str):
        return value.replace(ROOT_MARKER, str(destination)).replace(PYTHON_MARKER, str(interpreter))
    if isinstance(value, list):
        return [_replace(item, destination, interpreter) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, destination, interpreter) for key, item in value.items()}
    return value


def _relocate_document(
    value: Any, pointers: list[list[Any]], destination: Path, interpreter: Path
) -> Any:
    """Relocate only manifest-listed leaves, rejecting an unexpected pointer or marker."""
    for pointer in pointers:
        parent = value
        for key in pointer[:-1]:
            parent = parent[key]
        old = parent[pointer[-1]]
        assert isinstance(old, str) and (ROOT_MARKER in old or PYTHON_MARKER in old)
        parent[pointer[-1]] = _replace(old, destination, interpreter)
    encoded = json.dumps(value)
    assert ROOT_MARKER not in encoded and PYTHON_MARKER not in encoded
    return value


def assert_installed_path(module: Path, purelib: Path, checkout: Path) -> None:
    """Require a product module under external site-packages, never the checkout.

    Parameters
    ----------
    module, purelib, checkout : Path
        Observed module, interpreter site-packages, and forbidden source root.

    Raises
    ------
    AssertionError
        Import provenance is not an installed wheel outside the checkout.
    """
    module, purelib, checkout = module.resolve(), purelib.resolve(), checkout.resolve()
    assert module.is_relative_to(purelib), "product import is outside installed site-packages"
    assert not module.is_relative_to(checkout), "product import came from the checkout"
    assert not purelib.is_relative_to(checkout), "installed interpreter is inside the checkout"


def _loopback(url: str) -> str:
    """Validate an HTTP origin before any request, without resolving hostnames."""
    parsed = urllib.parse.urlsplit(url)
    assert parsed.scheme in {"http", "https"} and parsed.hostname
    assert parsed.username is None and parsed.password is None
    assert parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
    return url


def request(
    url: str, *, token: str | None = None, body: dict[str, Any] | None = None, method: str = "GET"
) -> tuple[int, Any, dict[str, str]]:
    """Request only loopback HTTP with no inherited proxy or redirects.

    Parameters
    ----------
    url : str
        Explicit loopback target.
    token : str, optional
        Private bearer credential.
    body : dict, optional
        JSON request body.
    method : str
        HTTP method.

    Returns
    -------
    tuple
        Status, parsed JSON or text, and response headers; HTTP denials are data.
    """
    _loopback(url)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    raw = None if body is None else json.dumps(body).encode()
    if raw:
        headers["Content-Type"] = "application/json"

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(
            self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
        ) -> None:
            """Refuse every redirect before an additional connection is made."""
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(url, data=raw, headers=headers, method=method)
    try:
        response = opener.open(req, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        _loopback(response.url)
        text = response.read().decode()
        content_type = response.headers.get("Content-Type", "")
        value = json.loads(text) if "json" in content_type else text
        assert response.status is not None
        return int(response.status), value, dict(response.headers)


@dataclass
class Server:
    """An owned installed server and its private log handle."""

    process: subprocess.Popen[str]
    home: Path
    url: str
    environment_id: str
    log: TextIO
    token: str = field(repr=False)
    scenario: str


@dataclass
class PackageRun:
    """Own one external installation and independent package-acceptance scenarios."""

    checkout: Path
    root: Path
    destination: Path
    secrets: set[str] = field(default_factory=set, repr=False)
    processes: list[Server] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)
    browser_reports: list[dict[str, Any]] = field(default_factory=list)
    prepared: bool = False
    closed: bool = False

    @classmethod
    def create(cls, *, checkout: Path) -> PackageRun:
        """Allocate separate external installation, private state, and report roots.

        Parameters
        ----------
        checkout : Path
            Source used only for building, fixtures, and browser test control.

        Returns
        -------
        PackageRun
            Owner with refusing host tools installed before child execution.
        """
        checkout = checkout.resolve()
        root = Path(tempfile.mkdtemp(prefix="hx-package-")).resolve()
        assert not root.is_relative_to(checkout)
        given = os.environ.get("HX_PACKAGE_ARTIFACTS")
        destination = (
            Path(given).resolve()
            if given
            else Path(tempfile.mkdtemp(prefix="hx-package-artifacts-")).resolve()
        )
        assert not destination.is_relative_to(root)
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("cwd", "bin", "private", "artifacts", "build"):
            (root / name).mkdir(mode=0o700)
        for name in REFUSED_TOOLS:
            target = root / "bin" / name
            target.write_text(
                "#!/bin/sh\necho 'package acceptance: real host tools blocked' >&2\nexit 255\n"
            )
            target.chmod(0o755)
        instance = cls(checkout, root, destination)
        instance.write_report(
            "preparation.json",
            {"status": "allocated", "source": str(checkout), "root_external": True},
        )
        return instance

    @property
    def interpreter(self) -> Path:
        """Return the absolute wheel interpreter path."""
        return self.root / "venv/bin/python"

    @property
    def cli(self) -> Path:
        """Return the absolute installed CLI path."""
        return self.root / "venv/bin/hx"

    def environment(
        self, overrides: dict[str, str] | None = None, *, scenario: str = ""
    ) -> dict[str, str]:
        """Construct an isolated child mapping, pinning USER only for the team scenario.

        Parameters
        ----------
        overrides : dict, optional
            Explicit scenario routing and synthetic credentials.
        scenario : str
            Team children use USER=sv; all others preserve the caller's user.

        Returns
        -------
        dict
            Final PG-free mapping with private HOME and refusing host tools.
        """
        explicit = {
            "HOME": str(self.root / "private/os-home"),
            "XDG_CONFIG_HOME": str(self.root / "private/config"),
            "XDG_DATA_HOME": str(self.root / "private/data"),
            "PATH": str(self.root / "bin") + os.pathsep + os.environ.get("PATH", ""),
            "HYPOTHEX_SSH": str(self.root / "bin/ssh"),
            "HYPOTHEX_SCP": str(self.root / "bin/scp"),
            "HYPOTHEX_TAILSCALE": str(self.root / "bin/tailscale"),
        }
        explicit.update(overrides or {})
        if scenario == "team":
            explicit["USER"] = "sv"
        return child_environment(dict(os.environ), explicit)

    def redact(self, text: str) -> str:
        """Remove registered secrets and common credential shapes from diagnostic text.

        Parameters
        ----------
        text : str
            Private raw diagnostic.

        Returns
        -------
        str
            Safe diagnostic without raw or URL-encoded registered values.
        """
        for secret in sorted(self.secrets, key=len, reverse=True):
            if secret:
                for variant in {
                    secret,
                    urllib.parse.quote(secret, safe=""),
                    urllib.parse.quote_plus(secret),
                }:
                    text = text.replace(variant, "[redacted]")
        text = re.sub(r"(/pair#)[^\s\"'<>]+", r"\1[redacted]", text)
        text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+", r"\1[redacted]", text)
        text = re.sub(
            r'(?i)("(?:token|secret|password|cookie)"\s*:\s*")[^"\n]*(")', r"\1[redacted]\2", text
        )
        return text

    def write_report(self, name: str, value: Any) -> None:
        """Write sanitized structured evidence inside the staging artifacts directory.

        Parameters
        ----------
        name : str
            Relative JSON filename.
        value : object
            Nonsecret report data.
        """
        target = _path(self.root / "artifacts", name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.redact(json.dumps(value, indent=2, default=str)) + "\n")

    def command(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        overrides: dict[str, str] | None = None,
        scenario: str = "",
        timeout: float = 120,
    ) -> subprocess.CompletedProcess[str]:
        """Run one controlled child and retain only sanitized failure diagnostics.

        Parameters
        ----------
        argv : list
            Explicit argument vector.
        cwd : Path, optional
            Defaults to the external working directory.
        overrides : dict, optional
            Explicit scenario environment.
        scenario : str
            Child identity policy, notably team USER pinning.
        timeout : float
            Deadline in seconds.

        Returns
        -------
        subprocess.CompletedProcess
            Private captured output.
        """
        self.commands.append([self.redact(item) for item in argv])
        try:
            return run_checked(
                argv,
                cwd=cwd or self.root / "cwd",
                env=self.environment(overrides, scenario=scenario),
                timeout=timeout,
            )
        except CommandFailure as error:
            self.write_report(
                f"failure-{len(self.commands)}.json",
                {
                    "operation": Path(argv[0]).name,
                    "returncode": error.result.returncode,
                    "stdout": error.result.stdout,
                    "stderr": error.result.stderr,
                },
            )
            raise AssertionError(
                self.redact(f"{error}\n{error.result.stdout}\n{error.result.stderr}")
            ) from None

    def prepare(self) -> None:
        """Build via Bun and ordinary uv build, then install only the wheel externally.

        Raises
        ------
        AssertionError
            Build output, isolated import prerequisites, or dependency closure is missing.
        """
        assert not self.closed
        if self.prepared:
            return
        self.command(
            ["bun", "install", "--cwd", "ui", "--frozen-lockfile"], cwd=self.checkout, timeout=180
        )
        self.command(["bun", "run", "--cwd", "ui", "build"], cwd=self.checkout, timeout=180)
        build_inputs = source_provenance(self.checkout, "")["source_files"]
        self.command(
            ["uv", "build", "--out-dir", str(self.root / "build")], cwd=self.checkout, timeout=180
        )
        wheels, sdists = (
            list((self.root / "build").glob("*.whl")),
            list((self.root / "build").glob("*.tar.gz")),
        )
        assert len(wheels) == len(sdists) == 1
        self.command(["uv", "venv", "--python", "3.13", str(self.root / "venv")], timeout=180)
        self.command(
            ["uv", "pip", "install", "--python", str(self.interpreter), str(wheels[0])], timeout=180
        )
        shutil.copyfile(
            self.checkout / "tests/packaging/installed_checks.py",
            self.root / "private/installed_checks.py",
        )
        dependencies = self.command(
            ["uv", "pip", "list", "--python", str(self.interpreter), "--format", "json"]
        )
        revision = self.command(["git", "rev-parse", "HEAD"], cwd=self.checkout).stdout.strip()
        status = self.command(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=self.checkout
        ).stdout
        provenance = source_provenance(self.checkout, status)
        assert provenance["source_files"] == build_inputs, (
            "source build inputs changed during build"
        )
        versions = {
            name: self.command([name, "--version"]).stdout.strip() for name in ("uv", "bun")
        }
        products = {}
        for path in [*wheels, *sdists]:
            shutil.copyfile(path, self.root / "artifacts" / path.name)
            products[path.suffix] = {
                "path": str(self.destination / path.name),
                "sha256": _hash(path),
            }
        self.write_report(
            "build.json",
            {
                "source_sha": revision,
                **provenance,
                "products": products,
                "commands": self.commands,
                "versions": versions,
                "dependencies": json.loads(dependencies.stdout),
            },
        )
        self.prepared = True

    def checker(
        self, operation: str, payload: dict[str, Any], *, scenario: str = ""
    ) -> dict[str, Any]:
        """Execute wheel assertions under -I using private external input/output files.

        Parameters
        ----------
        operation : str
            Checker operation.
        payload : dict
            Structured private input; never passed as command-line credentials.
        scenario : str
            Child identity policy.

        Returns
        -------
        dict
            Checker observations after its hard assertions pass.
        """
        assert self.prepared
        task = self.root / "private" / f"check-{len(self.commands)}.json"
        task.write_text(
            json.dumps(
                {
                    **payload,
                    "checkout": str(self.checkout),
                    "root": str(self.root),
                    "operation": operation,
                }
            )
        )
        task.chmod(0o600)
        out = self.command(
            [
                str(self.interpreter),
                "-I",
                str(self.root / "private/installed_checks.py"),
                str(task),
            ],
            scenario=scenario,
        )
        return json.loads(out.stdout)

    def check_resources(self) -> None:
        """Assert wheel imports, UI resources, dependencies, and executable migrations."""
        result = self.checker("resources", {"scratch": str(self.root / "private/migration")})
        assert_installed_path(Path(result["module"]), Path(result["purelib"]), self.checkout)
        self.write_report("installed.json", result)

    def _restore(self, schema: int, destination: Path, interpreter: Path) -> dict[str, Any]:
        """Restore immutable old files and SQL before any Phase 3 import."""
        fixture = self.checkout / f"tests/fixtures/package-schema{schema}"
        original = _hashes(fixture)
        manifest = json.loads((fixture / "manifest.json").read_text())
        assert manifest["schema"] == schema and manifest["source_revision"] == REVISIONS[schema]
        for relative, digest in manifest["files"].items():
            assert _hash(_path(fixture, relative)) == digest, relative
        destination = destination.resolve()
        assert not destination.is_relative_to(self.checkout) and not destination.exists()
        shutil.copytree(fixture / "tree", destination)
        for relative, pointers in manifest["path_fields"].items():
            assert relative not in manifest["protected_bytes"]
            path = _path(destination, relative)
            value = _relocate_document(
                json.loads(path.read_text()), pointers, destination, interpreter
            )
            path.write_text(json.dumps(value, indent=2) + "\n")
        for name in ("index", "events"):
            with sqlite3.connect(destination / f"home/{name}.db") as db:
                db.executescript((fixture / f"{name}.sql").read_text())
                for qualified in manifest["sql_path_columns"][f"{name}.sql"]:
                    table, column = qualified.split(".")
                    assert re.fullmatch(r"[a-z_]+", table) and re.fullmatch(r"[a-z_]+", column)
                    for rowid, raw in db.execute(
                        f'SELECT rowid, "{column}" FROM "{table}"'
                    ).fetchall():
                        if isinstance(raw, str) and (ROOT_MARKER in raw or PYTHON_MARKER in raw):
                            try:
                                structured = json.loads(raw)
                            except ValueError:
                                relocated = _replace(raw, destination, interpreter)
                            else:
                                relocated = json.dumps(
                                    _replace(structured, destination, interpreter)
                                )
                            db.execute(
                                f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?',
                                (relocated, rowid),
                            )
                assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                if name == "index":
                    assert db.execute(
                        "SELECT value FROM meta WHERE key='schema_version'"
                    ).fetchone() == (str(schema),)
                for (table,) in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall():
                    for row in db.execute(f'SELECT * FROM "{table}"'):
                        assert all(
                            not isinstance(value, str)
                            or (ROOT_MARKER not in value and PYTHON_MARKER not in value)
                            for value in row
                        )
        for relative, digest in manifest["protected_bytes"].items():
            assert _hash(_path(destination, relative)) == digest, relative
        expected = _relocate_document(
            json.loads((fixture / "expected.json").read_text()),
            manifest["expected_path_fields"],
            destination,
            interpreter,
        )
        for path in destination.rglob("*"):
            if path.is_file() and path.suffix not in {".db"}:
                assert (
                    ROOT_MARKER.encode() not in path.read_bytes()
                    and PYTHON_MARKER.encode() not in path.read_bytes()
                )
        # A known exited child supplies a genuinely stale PID, never an arbitrary process.
        dead = run_checked(
            [
                str(interpreter),
                "-I",
                "-c",
                "import json, os, psutil; "
                "print(json.dumps([os.getpid(), psutil.Process().create_time()]))",
            ],
            cwd=self.root / "cwd",
            env=self.environment(),
            timeout=10,
        )
        pid, birth = json.loads(dead.stdout)
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, 0)
            raise AssertionError("restoration child PID is not dead")
        server = destination / "home/serve/server.json"
        saved = json.loads(server.read_text())
        identity = json.loads((destination / "home/environment.json").read_text())
        saved.update(
            pid=pid,
            pid_create_time=birth,
            hostname=socket.gethostname(),
            home=str(destination / "home"),
            environment_id=identity["environment_id"],
        )
        server.write_text(json.dumps(saved))
        server.chmod(0o600)
        server.parent.chmod(0o700)
        assert _hashes(fixture) == original
        receipt = {
            "schema": schema,
            "source_revision": manifest["source_revision"],
            "expected": expected,
            "protected_bytes": manifest["protected_bytes"],
            "post_relocation_hashes": _hashes(destination),
            "fixture_hashes": original,
            "home": str(destination / "home"),
            "fixture_root": str(destination),
        }
        self.write_report(
            f"fixture-schema{schema}.json",
            {key: value for key, value in receipt.items() if key != "expected"},
        )
        return receipt

    def restore_schema3(self, destination: Path, interpreter: Path) -> dict[str, Any]:
        """Restore the immutable genuine schema-3 fixture with only allowlisted relocation.

        Parameters
        ----------
        destination, interpreter : Path
            New external root and Python to use in relocated fixture commands.

        Returns
        -------
        dict
            Full oracle and before/after byte-hash receipts.
        """
        return self._restore(3, destination, interpreter)

    def restore_schema4(self, destination: Path, interpreter: Path) -> dict[str, Any]:
        """Restore the independent genuine schema-4 fixture with schema/name-index proof.

        Parameters
        ----------
        destination, interpreter : Path
            New external root and Python to use in relocated fixture commands.

        Returns
        -------
        dict
            Full oracle and before/after byte-hash receipts.
        """
        return self._restore(4, destination, interpreter)

    def close(self) -> None:
        """Stop owned servers, reject artifact secrets, publish evidence, and erase private state.

        Raises
        ------
        AssertionError
            An owned process leaked or a generated secret remains in staged evidence.
        """
        if self.closed:
            return
        failures: list[str] = []
        for server in list(self.processes):
            try:
                self.stop(server)
            except Exception as error:
                failures.append(self.redact(str(error)))
        self.write_report(
            "process-cleanup.json",
            {
                "owned_servers": len(self.reports),
                "remaining": len(self.processes),
                "descendants_verified": sum(
                    report.get("descendants_verified", 0) for report in self.reports
                ),
                "failures": failures,
            },
        )
        self.write_report("commands.json", self.commands)
        self.write_report("browser-summary.json", self.browser_reports)
        try:
            checked = 0
            for path in (self.root / "artifacts").rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix not in {".whl", ".gz"}:
                    checked += 1
                    data = path.read_text()
                    for secret in self.secrets:
                        if secret:
                            assert (
                                secret not in data
                                and urllib.parse.quote(secret, safe="") not in data
                            ), "secret in staged artifact"
            self.write_report("artifact-scan.json", {"text_files": checked, "passed": True})
            for path in (self.root / "artifacts").rglob("*"):
                if not path.is_file():
                    continue
                target = self.destination / path.relative_to(self.root / "artifacts")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            assert not failures, failures
        finally:
            shutil.rmtree(self.root)
            self.closed = True

    def cli_json(
        self,
        home: Path,
        arguments: list[str],
        *,
        server: Server | None = None,
        scenario: str = "",
        overrides: dict[str, str] | None = None,
    ) -> Any:
        """Run the absolute installed CLI with an explicit home and optional hub routing.

        Parameters
        ----------
        home : Path
            Explicit isolated home, including a paired remote client's home.
        arguments : list
            CLI arguments ending in --json.
        server : Server, optional
            Only HYPOTHEX_HUB_URL is supplied; credential discovery remains real.
        scenario : str
            Identity policy.
        overrides : dict, optional
            Extra explicit settings for precedence and denial checks.

        Returns
        -------
        object
            Parsed CLI JSON.
        """
        env = {"HYPOTHEX_HUB_URL": server.url} if server else {}
        env.update(overrides or {})
        done = self.command(
            [str(self.cli), "--home", str(home), *arguments],
            overrides=env,
            scenario=scenario or (server.scenario if server else ""),
        )
        return json.loads(done.stdout)

    def start(self, home: Path, *, port: int = 0, auth: bool = False, scenario: str = "") -> Server:
        """Start an installed server and verify PID, home, and public environment identity.

        Parameters
        ----------
        home : Path
            Owned scenario home.
        port : int
            Ephemeral for first start, identical explicit port for restart.
        auth : bool
            Add --auth when scoped authentication is requested.
        scenario : str
            Identity policy; team pins USER=sv.

        Returns
        -------
        Server
            Ready installed server with a privately discovered credential.
        """
        assert self.prepared and home.resolve().is_relative_to(self.root)
        assert self.interpreter.parent.resolve().is_relative_to(self.root)
        identity = json.loads((home / "environment.json").read_text())["environment_id"]
        if port == 0:
            with socket.socket() as reserved:
                reserved.bind(("127.0.0.1", 0))
                port = reserved.getsockname()[1]
        record_path = home / "serve/server.json"
        if record_path.exists():
            old = json.loads(record_path.read_text())
            pid = old["pid"]
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("stale server PID is alive; never signal it")
            old["port"] = port
            record_path.write_text(json.dumps(old))
            record_path.chmod(0o600)
        args = [
            str(self.cli),
            "--home",
            str(home),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        if auth:
            args.append("--auth")
        log = (self.root / "private" / f"server-{len(self.reports)}.log").open("w+")
        final = self.environment(scenario=scenario)
        assert not any(key.startswith("PG") for key in final)
        process = subprocess.Popen(
            args,
            cwd=self.root / "cwd",
            env=final,
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        server = Server(process, home, f"http://127.0.0.1:{port}", identity, log, "", scenario)
        self.processes.append(server)
        self.commands.append(args)
        self.reports.append({"pid": process.pid, "home": str(home), "scenario": scenario})
        deadline = time.monotonic() + 60
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log.flush()
                    log.seek(0)
                    raise AssertionError(
                        self.redact("installed server exited before readiness:\n" + log.read())
                    )
                if record_path.exists():
                    record = json.loads(record_path.read_text())
                    if record.get("pid") == process.pid:
                        assert record.get("home") == str(home.resolve())
                        assert record.get("environment_id") == identity
                        try:
                            status, public, _ = request(
                                server.url + "/.well-known/hypothex/environment"
                            )
                        except (OSError, urllib.error.URLError):
                            pass
                        else:
                            assert status == 200 and public["environment_id"] == identity
                            token = self.command(
                                [str(self.cli), "--home", str(home), "token"], scenario=scenario
                            ).stdout.strip()
                            # Scoped startup replaces the provisional token during lifespan.
                            # Read the ownership record again after readiness and CLI discovery.
                            ready_record = json.loads(record_path.read_text())
                            assert ready_record["pid"] == process.pid
                            assert ready_record["environment_id"] == identity
                            assert token and token == ready_record["token"], (
                                "credential discovery mismatch"
                            )
                            self.secrets.add(token)
                            server.token = token
                            return server
                time.sleep(0.1)
            raise AssertionError("installed server readiness timed out")
        except BaseException:
            self.stop(server)
            raise

    def stop(self, server: Server) -> None:
        """Stop only an owned server group and require removal of its ownership file.

        Parameters
        ----------
        server : Server
            Handle returned by start; no preexisting PID is accepted.
        """
        assert server in self.processes, "server is not owned by this package run"
        descendants = _descendant_identities(server.process.pid)
        _terminate(server.process, timeout=90)
        assert server.process.poll() is not None
        remaining = _remaining_descendants(descendants)
        assert not remaining, f"owned server descendants survived shutdown: {remaining}"
        for report in self.reports:
            if report["pid"] == server.process.pid:
                report["descendants_verified"] = len(descendants)
        server.log.close()
        self.processes.remove(server)
        assert not (server.home / "serve/server.json").exists(), (
            "owned server.json survived shutdown"
        )

    def browser(self, descriptor: Path) -> None:
        """Run standalone Playwright against this live installed server, never Vite.

        Parameters
        ----------
        descriptor : Path
            Private descriptor under this run's external root.
        """
        assert descriptor.resolve().is_relative_to(self.root / "private")
        assert descriptor.stat().st_mode & 0o777 == 0o600
        cache = Path.home() / ("Library/Caches" if sys.platform == "darwin" else ".cache")
        browser_cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(cache / "ms-playwright"))
        self.command(
            ["bunx", "playwright", "test", "--config", "playwright.package.config.ts"],
            cwd=self.checkout / "ui",
            overrides={
                "HX_PACKAGE_DESCRIPTOR": str(descriptor),
                "HX_PACKAGE_BROWSER_OUTPUT": str(self.root / "private" / "browser-results"),
                "PLAYWRIGHT_BROWSERS_PATH": browser_cache,
            },
            timeout=240,
        )

    def _browser(
        self, server: Server, scenario: str, stage: str, demo: dict[str, Any] | None = None
    ) -> None:
        """Write a private server descriptor and collect a sanitized browser stage summary."""
        descriptor = self.root / "private" / f"browser-{scenario}-{stage}.json"
        descriptor.write_text(
            json.dumps(
                {
                    "url": server.url,
                    "environment_id": server.environment_id,
                    "scenario": scenario,
                    "stage": stage,
                    "root": str(self.root),
                    "home": str(server.home),
                    "interpreter": str(self.interpreter),
                    "cli": str(self.cli),
                    "demo": demo or {},
                    "environment": self.environment(scenario=server.scenario),
                }
            )
        )
        descriptor.chmod(0o600)
        self.browser(descriptor)
        result = {"scenario": scenario, "stage": stage, "themes": ["light", "dark"], "passed": True}
        self.browser_reports.append(result)
        self.write_report(f"browser-{scenario}-{stage}.json", result)

    def _surface(self, server: Server, run_id: str) -> None:
        """Verify packaged HTML, assets, deep links and JSON API token denial."""
        status, root, headers = request(server.url + "/")
        assert status == 200 and "text/html" in headers.get(
            "content-type", headers.get("Content-Type", "")
        )
        assert isinstance(root, str) and "<html" in root.lower()
        assets = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', root)
        for asset in assets:
            if not asset.startswith("/"):
                continue
            status, _, headers = request(server.url + asset)
            assert status == 200, asset
            content = headers.get("content-type", headers.get("Content-Type", ""))
            if asset.endswith(".js"):
                assert "javascript" in content
            elif asset.endswith(".css"):
                assert "text/css" in content
        for path in (
            "/hosts",
            "/queue",
            "/settings",
            "/storage",
            "/n/toy-classifier",
            "/n/toy-classifier/2026-10-06",
            "/pair",
            f"/r/{run_id}",
        ):
            status, body, headers = request(server.url + path)
            assert status == 200 and isinstance(body, str) and "<html" in body.lower(), path
        status, denied, headers = request(server.url + "/api/v1/projects")
        assert status == 401 and isinstance(denied, dict)
        assert "json" in headers.get("content-type", headers.get("Content-Type", ""))
        assert request(server.url + "/api/v1/projects", token=server.token)[0] == 200

    def _paired(
        self, server: Server, home: Path, *, user: str, scope: str, new_user: bool = False
    ) -> dict[str, Any]:
        """Create a CLI offer and redeem it through the installed CLI's saved-login path."""
        args = ["pair", "--user", user, "--scope", scope, "--client", "cli", "--json"]
        if new_user:
            args.append("--new-user")
        offer = self.cli_json(server.home, args, server=server)
        link = offer["url"]
        assert (
            urllib.parse.urlsplit(link)._replace(path="", query="", fragment="").geturl()
            == server.url
        )
        self.secrets.add(link)
        self.secrets.add(urllib.parse.urlsplit(link).fragment)
        result = self.cli_json(
            home, ["login", link, "--device", "package-cli", "--json"], server=server
        )
        tokens = home / "auth/hub-tokens.json"
        assert tokens.stat().st_mode & 0o777 == 0o600
        saved = json.loads(tokens.read_text())[server.url]
        token = saved["token"]
        self.secrets.add(token)
        assert token not in json.dumps(result)
        assert result["user"] == user and result["scope"] == scope
        return {
            "home": home,
            "user": user,
            "scope": scope,
            "session_id": result["session_id"],
            "token": token,
        }

    def _paired_assertions(self, server: Server, login: dict[str, Any]) -> dict[str, Any]:
        """Verify real saved CLI discovery and matching owner/collaborator project data."""
        me = self.cli_json(login["home"], ["whoami", "--json"], server=server)
        assert (me["user"], me["scope"], me["session_id"]) == (
            login["user"],
            login["scope"],
            login["session_id"],
        )
        assert self.cli_json(login["home"], ["projects", "--json"], server=server) == self.cli_json(
            server.home, ["projects", "--json"], server=server
        )
        status, via_http, _ = request(server.url + "/api/v1/projects", token=login["token"])
        assert status == 200
        assert via_http == request(server.url + "/api/v1/projects", token=server.token)[1]
        return me

    def _expect_cli_denied(
        self, home: Path, server: Server, overrides: dict[str, str] | None = None
    ) -> None:
        """Require an actual authentication failure from a controlled installed child."""
        env = self.environment(
            {"HYPOTHEX_HUB_URL": server.url, **(overrides or {})}, scenario=server.scenario
        )
        try:
            run_checked(
                [str(self.cli), "--home", str(home), "whoami", "--json"],
                cwd=self.root / "cwd",
                env=env,
                timeout=30,
            )
        except CommandFailure as error:
            assert error.result.returncode != 0
            text = error.result.stdout + error.result.stderr
            assert "401" in text or "auth" in text.lower() or "token" in text.lower()
        else:
            raise AssertionError("empty or wrongly overridden client unexpectedly authenticated")

    def check_token_start_restart(self) -> None:
        """Exercise installed fresh default-token behavior, packaged UI, and credential rotation."""
        home = self.root / "private/token/home"
        demo = self.cli_json(home, ["demo", "--json"])
        assert set(demo) == {
            "generic",
            "training",
            "agent_eval",
            "agent_iteration",
            "system_bench",
            "eval_matrix",
        }
        selective = self.cli_json(
            self.root / "private/token/kinds-home", ["demo", "--kinds", "generic", "--json"]
        )
        assert set(selective) == {"generic"}
        self.checker("seed-sweep", {"home": str(home), "mapping": demo["generic"]})
        server = self.start(home, scenario="token")
        try:
            old_token, identity = server.token, server.environment_id
            rows = request(server.url + "/api/v1/runs?limit=1", token=server.token)[1]
            run_id = rows[0]["run_id"] if isinstance(rows, list) else rows["runs"][0]["run_id"]
            self._surface(server, run_id)
            self._browser(server, "token", "start", demo)
            projects = request(server.url + "/api/v1/projects", token=server.token)[1]
            port = urllib.parse.urlsplit(server.url).port
            assert port is not None
            self.stop(server)
            server = self.start(home, port=port, scenario="token")
            assert server.environment_id == identity and server.token != old_token
            assert request(server.url + "/api/v1/projects", token=old_token)[0] == 401
            assert request(server.url + "/api/v1/projects", token=server.token)[1] == projects
            self._surface(server, run_id)
            self._browser(server, "token", "restart", demo)
            self.write_report(
                "token.json",
                {
                    "demo_keys": sorted(demo),
                    "explicit_kinds": sorted(selective),
                    "environment_preserved": True,
                    "old_token_rejected": True,
                    "restart": True,
                },
            )
        finally:
            if server in self.processes:
                self.stop(server)

    def check_team_pair_login_restart(self) -> None:
        """Exercise installed team seeding, pairing, saved login, sends, and restart persistence."""
        home = self.root / "private/team/home"
        demo = self.cli_json(home, ["demo", "--with-team", "--json"], scenario="team")
        assert set(demo) == {
            "generic",
            "training",
            "agent_eval",
            "agent_iteration",
            "system_bench",
            "eval_matrix",
            "team",
        }
        self.checker("seed-sweep", {"home": str(home), "mapping": demo["generic"]}, scenario="team")
        server = self.start(home, auth=True, scenario="team")
        try:
            links = json.loads((home / "demo-team/pairing.json").read_text())
            assert {"sv", "alice"} <= set(links)
            for link in links.values():
                _loopback(link)
                assert link.startswith(server.url + "/pair#")
                self.secrets.add(link)
            owner = self.cli_json(home, ["whoami", "--json"], server=server)
            assert (
                owner["user"] == "sv" and owner["scope"] == "admin" and owner["client"] == "local"
            )
            login = self._paired(
                server, self.root / "private/team/alice", user="alice", scope="launch"
            )
            self._paired_assertions(server, login)
            self._expect_cli_denied(self.root / "private/team/empty", server)
            self._expect_cli_denied(
                login["home"], server, {"HYPOTHEX_HUB_TOKEN": "synthetic-wrong"}
            )
            owner_mcp = self.checker(
                "mcp", {"url": server.url, "token": server.token, "tool": "whoami"}, scenario="team"
            )
            assert owner_mcp["result"] == {"user": "sv", "scope": "admin"}
            alice_mcp = self.checker(
                "mcp",
                {"url": server.url, "token": login["token"], "tool": "whoami"},
                scenario="team",
            )
            assert alice_mcp["result"] == {"user": "alice", "scope": "launch"}
            assert request(server.url + "/api/v1/storage", token=login["token"])[0] == 403
            notebook = {str(path.relative_to(home)): _hash(path) for path in home.rglob("*.md")}
            self._browser(server, "team", "start", demo)
            old_token, old_session = server.token, owner["session_id"]
            port = urllib.parse.urlsplit(server.url).port
            assert port is not None
            self.stop(server)
            server = self.start(home, port=port, auth=True, scenario="team")
            me = self.cli_json(home, ["whoami", "--json"], server=server)
            assert me["session_id"] != old_session and server.token != old_token
            assert request(server.url + "/api/v1/projects", token=old_token)[0] == 401
            self._paired_assertions(server, login)
            assert {
                str(path.relative_to(home)): _hash(path) for path in home.rglob("*.md")
            } == notebook
            hosts = request(server.url + "/api/v1/hosts", token=server.token)[1]
            assert any(row["state"]["state"] == "connected" for row in hosts)
            channels = {}
            for channel in ("slack", "email"):
                sent = self.cli_json(home, ["notify", "test", channel, "--json"], server=server)
                assert sent == {"ok": True, "error_class": None}, sent
                channels[channel] = sent
            self._browser(server, "team", "restart", demo)
            self.write_report(
                "team.json",
                {
                    "demo_keys": sorted(demo),
                    "owner": me["user"],
                    "paired_session_preserved": True,
                    "local_session_rotated": True,
                    "notebook_preserved": True,
                    "send_results": channels,
                    "mcp": {"owner": owner_mcp["result"], "alice": alice_mcp["result"]},
                },
            )
        finally:
            if server in self.processes:
                self.stop(server)

    def _upgrade(self, schema: int) -> None:
        """Exercise one independent frozen home's real automatic upgrade and auth lifecycle."""
        scenario = f"schema{schema}-upgraded"
        root = self.root / "private" / scenario
        restore = self.restore_schema3 if schema == 3 else self.restore_schema4
        receipt = restore(root, self.interpreter)
        home = Path(receipt["home"])
        self.secrets.add(f"schema{schema}-synthetic-root")
        # First installed product open, after restoration established the actual old schema.
        projects = self.cli_json(home, ["projects", "--json"])
        assert projects
        self.write_report(
            f"{scenario}-after-upgrade.json",
            self.checker("preserve", {**receipt, "schema": schema}),
        )
        server = self.start(home, scenario=scenario)
        try:
            assert (
                request(server.url + "/api/v1/projects", token=f"schema{schema}-synthetic-root")[0]
                == 401
            )
            self._surface(server, "a")
            strict_url = (
                server.url + "/api/v1/compare/examples?a=a&b=b&metric=accuracy&require_bound=true"
            )
            status, compared, _ = request(strict_url, token=server.token)
            assert status == 200 and compared == receipt["expected"]["comparison"]
            port = urllib.parse.urlsplit(server.url).port
            assert port is not None
            self.stop(server)
            self.checker("enable-auth", {"home": str(home)})
            server = self.start(home, port=port, auth=True, scenario=scenario)
            me = self.cli_json(home, ["whoami", "--json"], server=server)
            assert me["scope"] == "admin" and me["client"] == "local"
            login = self._paired(
                server,
                self.root / "private" / f"schema{schema}-alice",
                user="alice",
                scope="launch",
                new_user=True,
            )
            self._paired_assertions(server, login)
            assert request(strict_url, token=login["token"])[1] == receipt["expected"]["comparison"]
            self.cli_json(
                home,
                [
                    "note",
                    "--project",
                    "toy",
                    "package upgrade [[run:a]]",
                    "--day",
                    "2026-10-06",
                    "--json",
                ],
                server=server,
            )
            saved = {
                str(path.relative_to(home)): _hash(path)
                for path in [home / "config.yaml", *home.rglob("*.md")]
            }
            revoked = self._paired(
                server,
                self.root / "private" / f"schema{schema}-revoked",
                user="alice",
                scope="read",
            )
            self.cli_json(
                home, ["sessions", "revoke", revoked["session_id"], "--json"], server=server
            )
            assert request(server.url + "/api/v1/projects", token=revoked["token"])[0] == 401
            # Exercise installed MCP reads and a genuinely scoped mutation refusal.
            read = self._paired(
                server, self.root / "private" / f"schema{schema}-reader", user="alice", scope="read"
            )
            mcp_me = self.checker(
                "mcp", {"url": server.url, "token": read["token"], "tool": "whoami"}
            )
            assert mcp_me["result"] == {"user": "alice", "scope": "read"}
            self.checker(
                "mcp",
                {
                    "url": server.url,
                    "token": read["token"],
                    "tool": "rename_run",
                    "arguments": {"run_id": "a", "name": "forbidden"},
                    "expect_error": True,
                },
            )
            if schema == 4:
                reset = self.cli_json(home, ["rename", "a", "--reset", "--json"], server=server)
                assert reset["name"] is None
                assert (
                    request(server.url + "/api/v1/runs/a", token=server.token)[1]["record"]["name"]
                    is None
                )
                named = self.checker(
                    "mcp",
                    {
                        "url": server.url,
                        "token": server.token,
                        "tool": "rename_run",
                        "arguments": {"run_id": "a", "name": "package renamed"},
                    },
                )
                assert named["result"]["run"]["name"] == "package renamed"
                assert (
                    self.cli_json(home, ["show", "a", "--json"], server=server)["record"]["name"]
                    == "package renamed"
                )

                # Only the explicit rename's exact text is changed in the frozen oracle.
                def renamed(value: Any) -> Any:
                    if isinstance(value, dict):
                        return {key: renamed(child) for key, child in value.items()}
                    if isinstance(value, list):
                        return [renamed(child) for child in value]
                    return "package renamed" if value == "wide %_ beam" else value

                receipt["expected"] = renamed(receipt["expected"])
                # Search predicates formerly matching the old name no longer match a.
                for search in ("%", "_", "wide %_"):
                    receipt["expected"]["search"][search] = {"count": 0, "first": [], "next": []}
                run_yaml = "home/store/toy/runs/a/run.yaml"
                receipt["post_relocation_hashes"][run_yaml] = _hash(root / run_yaml)
            self._browser(server, scenario, "upgraded")
            for stage in ("restart", "reindex"):
                old_token, old_session = (
                    server.token,
                    self.cli_json(home, ["whoami", "--json"], server=server)["session_id"],
                )
                self.stop(server)
                if stage == "reindex":
                    self.cli_json(home, ["reindex", "--json"])
                server = self.start(home, port=port, auth=True, scenario=scenario)
                me = self.cli_json(home, ["whoami", "--json"], server=server)
                assert me["session_id"] != old_session and server.token != old_token
                assert request(server.url + "/api/v1/projects", token=old_token)[0] == 401
                assert request(server.url + "/api/v1/projects", token=revoked["token"])[0] == 401
                self._paired_assertions(server, login)
                assert {relative: _hash(home / relative) for relative in saved} == saved
                assert (
                    request(strict_url, token=login["token"])[1]
                    == receipt["expected"]["comparison"]
                )
                result = self.checker("preserve", {**receipt, "schema": schema})
                result.update(
                    paired_session_preserved=True,
                    local_session_rotated=True,
                    revocation_preserved=True,
                    settings_notebook_hashes=saved,
                )
                self.write_report(f"{scenario}-{stage}.json", result)
                self._browser(server, scenario, stage)
        finally:
            if server in self.processes:
                self.stop(server)

    def check_schema3_upgrade_restart_reindex(self) -> None:
        """Preserve genuine schema-3 evidence and new auth through upgrade/restart/reindex."""
        self._upgrade(3)

    def check_schema4_upgrade_restart_reindex(self) -> None:
        """Preserve schema-4 workspace, carried state and bindings through all lifecycle stages."""
        self._upgrade(4)
