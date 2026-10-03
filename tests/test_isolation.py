import os
import shutil
import subprocess

import pytest

from hypothex.core.context import Context
from hypothex.core.environment import count_gpus
from tests.fakes import DEAD_HUB, REFUSED_EXIT, REFUSED_TOOLS


@pytest.fixture(scope="module")
def module_env() -> dict[str, str | None]:
    """What a module-scoped fixture sees: it runs before the per-test ``isolate_remote``."""
    return {
        "hub": os.environ.get("HYPOTHEX_HUB_URL"),
        "fake_gpus": os.environ.get("HYPOTHEX_FAKE_GPUS"),
        "ssh": os.environ.get("HYPOTHEX_SSH"),
        "nvidia-smi": shutil.which("nvidia-smi"),
        "sbatch": shutil.which("sbatch"),
    }


def test_module_fixtures_already_run_fail_closed(module_env: dict[str, str | None]) -> None:
    # the session baseline (pytest_configure) covers fixtures that start before any test
    assert module_env["hub"] == DEAD_HUB and module_env["fake_gpus"] is None
    for tool in ("nvidia-smi", "sbatch"):
        found = module_env[tool]
        assert found is not None and "refused-tools" in found, tool
    ssh = module_env["ssh"]
    assert ssh is not None
    assert subprocess.run([ssh, "gpu1", "true"], capture_output=True).returncode == 255


@pytest.mark.parametrize("tool", REFUSED_TOOLS)
def test_real_gpu_and_slurm_tools_are_blocked(tool: str) -> None:
    found = shutil.which(tool)
    assert found is not None and "refused-tools" in found
    done = subprocess.run([tool, "--version"], capture_output=True, text=True)
    assert done.returncode == REFUSED_EXIT and "blocked" in done.stderr


def test_hub_and_ssh_are_dead_ends() -> None:
    assert os.environ["HYPOTHEX_HUB_URL"] == DEAD_HUB
    assert "HYPOTHEX_FAKE_GPUS" not in os.environ
    for var in ("HYPOTHEX_SSH", "HYPOTHEX_SCP"):
        done = subprocess.run([os.environ[var], "gpu1", "true"], capture_output=True)
        assert done.returncode == 255


def test_gpu_count_and_context_never_reach_a_real_nvidia_smi(ctx: Context) -> None:
    assert count_gpus() == 0
    assert ctx.descriptor.gpus == 0
