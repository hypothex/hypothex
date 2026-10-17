"""Real CLI subprocess servers, isolated homes, and loopback-only child networking."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

import httpx
import pytest

from hypothex.core.context import Context
from hypothex.core.layout import Layout
from hypothex.core.settings import ServerSettings, Settings, save_settings
from hypothex.remote.config import HostSpec
from tests.api.envserver import wait_until, write_fake_gpus, write_hosts
from tests.factories import git, write_toy_project
from tests.fakes.network import pg_child_environment

ROOT = Path(__file__).resolve().parents[2]
GUARDED_CLI = """
import runpy
import pytest
from tests.fakes.network import guard_network
patch = pytest.MonkeyPatch()
guard_network(patch)
runpy.run_module('hypothex.cli.main', run_name='__main__')
"""


def child_environment(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build an isolated CLI environment after all scenario overrides.

    Parameters
    ----------
    home : Path
        Synthetic Hypothex home.
    extra : dict, optional
        Scenario-owned credentials and loopback URLs.

    Returns
    -------
    dict
        Environment with no inherited credentials, PG defaults, or proxy routes.
    """
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "VIRTUAL_ENV",
        "HYPOTHEX_SSH",
        "HYPOTHEX_SCP",
        "HYPOTHEX_RSYNC",
        "HYPOTHEX_TAILSCALE",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.update(
        {
            "USER": "sv",
            "HYPOTHEX_HOME": str(home),
            "HYPOTHEX_HUB_URL": "http://127.0.0.1:1",
            "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")]),
            "PYTHONUNBUFFERED": "1",
        }
    )
    environment.update(extra or {})
    return pg_child_environment(environment)


def run_cli(
    home: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
    json_output: bool = True,
    success: bool = True,
) -> Any:
    """Execute the selected checkout CLI as a guarded subprocess.

    Parameters
    ----------
    home : Path
        Selected synthetic client home.
    arguments : str
        CLI arguments.
    environment : dict, optional
        Explicit scenario environment.
    cwd : Path, optional
        Synthetic repository to launch from.
    json_output : bool
        Request and decode JSON.
    success : bool
        Require success or an explicit nonzero exit.

    Returns
    -------
    object
        Decoded JSON, or the process result for an expected refusal.
    """
    argv = ["--home", str(home), *arguments]
    if json_output:
        argv.insert(argv.index("--") if "--" in argv else len(argv), "--json")
    result = subprocess.run(
        [sys.executable, "-c", GUARDED_CLI, *argv],
        env=child_environment(home, environment),
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if not success:
        assert result.returncode != 0, result.stdout
        return result
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if json_output else result.stdout


@dataclass
class LiveServer:
    """One real hx serve process and its private startup record."""

    home: Path
    arguments: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)
    process: subprocess.Popen[str] | None = None
    output: TextIO | None = None
    url: str = ""
    token: str = ""

    def start(self) -> LiveServer:
        """Start serving and wait for the real descriptor endpoint.

        Returns
        -------
        LiveServer
            This ready server, including its fresh startup token.
        """
        self.home.mkdir(parents=True, exist_ok=True)
        self.output = (self.home.parent / f"{self.home.name}-server.log").open("a")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                GUARDED_CLI,
                "--home",
                str(self.home),
                "serve",
                "--port",
                "0",
                *self.arguments,
            ],
            cwd=ROOT,
            env=child_environment(self.home, self.environment),
            stdout=self.output,
            stderr=subprocess.STDOUT,
            text=True,
        )

        def ready() -> dict[str, Any] | None:
            assert self.process is not None
            if self.process.poll() is not None:
                raise RuntimeError("server exited before readiness")
            record = json.loads((self.home / "serve" / "server.json").read_text())
            if record.get("pid") != self.process.pid or not record.get("token"):
                return None
            base = f"http://127.0.0.1:{record['port']}"
            response = httpx.get(base + "/.well-known/hypothex/environment", timeout=2)
            return record if response.status_code == 200 else None

        try:
            record = wait_until(ready, timeout=30)
        except BaseException:
            self.stop()
            raise
        self.url = f"http://127.0.0.1:{record['port']}"
        self.token = record["token"]
        return self

    def stop(self) -> None:
        """Stop the subprocess and release the capture file."""
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.output is not None:
            self.output.close()
            self.output = None

    def __enter__(self) -> LiveServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


@dataclass
class Lab:
    """Two actual servers and a cloned collaborator checkout."""

    hub: LiveServer
    host: LiveServer
    repo: Path
    laptop_repo: Path
    root: Path

    @property
    def owner_environment(self) -> dict[str, str]:
        """Return this test's owner token and loopback hub URL."""
        return {"HYPOTHEX_HUB_URL": self.hub.url, "HYPOTHEX_HUB_TOKEN": self.hub.token}

    def cli(self, home: Path, *args: str, owner: bool = False, **kwargs: Any) -> Any:
        """Invoke a client against the actual hub.

        Parameters
        ----------
        home : Path
            Synthetic client home.
        args : str
            CLI arguments.
        owner : bool
            Explicitly select the startup owner credential.
        kwargs : object
            Other run_cli options.

        Returns
        -------
        object
            CLI result.
        """
        extra = kwargs.pop("environment", {})
        environment = self.owner_environment if owner else {"HYPOTHEX_HUB_URL": self.hub.url}
        return run_cli(home, *args, environment={**environment, **extra}, **kwargs)

    def pair(self, user: str, scope: str = "launch", *, client: str = "cli") -> tuple[Path, str]:
        """Pair a fresh collaborator by invoking real owner and laptop CLIs.

        Parameters
        ----------
        user : str
            New account name.
        scope : str
            Account scope.
        client : str
            Device label.

        Returns
        -------
        tuple
            Client home and its persisted credential.
        """
        offer = self.cli(
            self.hub.home, "pair", "--new-user", "--user", user, "--scope", scope, owner=True
        )
        home = self.root / f"{user}-{client}-home"
        result = self.cli(home, "login", offer["url"], "--device", f"{user}-{client}")
        assert (result["user"], result["scope"]) == (user, scope)
        token = json.loads((home / "auth" / "hub-tokens.json").read_text())[self.hub.url]["token"]
        return home, token


@pytest.fixture
def lab(tmp_path: Path) -> Iterator[Lab]:
    """Serve a real auth hub and real shared host with four synthetic GPUs."""
    repo = write_toy_project(tmp_path / "hub-repo")
    origin = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(repo), str(origin))
    git(repo, "remote", "add", "origin", str(origin))
    host_repo = tmp_path / "host-repo"
    laptop_repo = tmp_path / "laptop-repo"
    git(tmp_path, "clone", "-q", str(origin), str(host_repo))
    git(tmp_path, "clone", "-q", str(origin), str(laptop_repo))
    gpus = write_fake_gpus(tmp_path / "gpus.json", count=4)
    host_token = "synthetic-shared-host-token"
    with LiveServer(
        tmp_path / "host-home",
        ("--kind", "ssh"),
        {
            "HYPOTHEX_SERVE_TOKEN": host_token,
            "HYPOTHEX_FAKE_GPUS": str(gpus),
        },
    ) as host:
        hub_home = tmp_path / "hub-home"
        context = Context.open(hub_home)
        context.register_project(repo)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        save_settings(Layout(hub_home), Settings(server=ServerSettings(auth="on", public_url=url)))
        write_hosts(
            hub_home,
            {
                "shared": HostSpec(
                    kind="ssh",
                    route="url",
                    url=host.url,
                    token_env="HX_ACCEPTANCE_HOST_TOKEN",
                    projects={"toy": str(host_repo.resolve())},
                )
            },
        )
        with LiveServer(
            hub_home,
            ("--auth", "--port", str(port)),
            {
                "HX_ACCEPTANCE_HOST_TOKEN": host_token,
            },
        ) as hub:

            def connected() -> bool:
                response = httpx.get(
                    hub.url + "/api/v1/hosts",
                    headers={"Authorization": f"Bearer {hub.token}"},
                    timeout=5,
                )
                return any(
                    row["name"] == "shared" and row["state"]["state"] == "connected"
                    for row in response.json()
                )

            wait_until(connected, timeout=30)
            yield Lab(hub, host, repo, laptop_repo, tmp_path)
