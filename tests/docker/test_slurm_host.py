"""SLURM host end to end against a small Docker SLURM cluster (never the user's hosts)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hypothex import __version__
from hypothex.cli.main import app
from hypothex.core.context import Context
from hypothex.remote.config import load_hosts
from tests.docker.conftest import DESCRIPTOR_PY, SlurmCluster

pytestmark = pytest.mark.docker

runner = CliRunner()


def test_hosts_add_slurm_bootstraps_the_login_node(
    slurm_cluster: SlurmCluster, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "hub"
    monkeypatch.setenv("HYPOTHEX_HOME", str(home))
    for key, value in slurm_cluster.access.env().items():
        monkeypatch.setenv(key, value)
    alias = slurm_cluster.access.alias
    argv = ["--home", str(home), "hosts", "add", "cluster", "--ssh", alias]
    argv += ["--slurm", "--partition", "normal", "--json"]
    result = runner.invoke(app, argv, catch_exceptions=False)
    assert result.exit_code == 0, result.output

    spec = load_hosts(Context.open(home).layout).environments["cluster"]
    assert (spec.route, spec.kind, spec.ssh_alias) == ("ssh", "slurm", "hx-docker-slurm")
    assert spec.slurm is not None and spec.slurm.partition == "normal"

    info = json.loads(slurm_cluster.sh("cat ~/.hypothex/serve/server.json"))
    assert info["managed"] is True
    assert info["hx_version"] == __version__
    descriptor = json.loads(slurm_cluster.exec("python3", "-c", DESCRIPTOR_PY, str(info["port"])))
    assert descriptor["kind"] == "slurm"
    assert descriptor["hostname"] == "slurmctld"
    # the runtime sits on the shared /home, so the compute node sees the same install
    runtime = slurm_cluster.sh("ls ~/.hypothex/runtime/wheels")
    assert slurm_cluster.exec("sh", "-c", "ls ~/.hypothex/runtime/wheels", service="c1") == runtime
