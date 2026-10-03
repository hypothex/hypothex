import shutil
import tempfile
from pathlib import Path

import pytest

from hypothex.core.context import Context
from tests.factories import write_toy_project
from tests.fakes import DEAD_HUB, refuse_host_tools, refuse_remote


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "hxhome"
    monkeypatch.setenv("HYPOTHEX_HOME", str(h))
    monkeypatch.delenv("HYPOTHEX_AGENT", raising=False)
    return h


@pytest.fixture
def ctx(home: Path) -> Context:
    return Context.open(home)


@pytest.fixture
def toy_repo(tmp_path: Path) -> Path:
    return write_toy_project(tmp_path / "toy")


def pytest_configure(config: pytest.Config) -> None:
    """
    Install the fail-closed baseline for the whole session (HARD RULE).

    pytest calls this before it imports any test module and before any
    session- or module-scoped fixture runs, so even those never see the
    user's hub, ``ssh``, ``nvidia-smi``, or SLURM. The values stay for the
    whole run (this ``MonkeyPatch`` is never undone); ``isolate_remote``
    sets them again for every test.
    """
    base = Path(tempfile.mkdtemp(prefix="hx-test-isolation-"))
    config.add_cleanup(lambda: shutil.rmtree(base, ignore_errors=True))
    session = pytest.MonkeyPatch()
    session.setenv("HYPOTHEX_HUB_URL", DEAD_HUB)
    session.delenv("HYPOTHEX_FAKE_GPUS", raising=False)
    refuse_remote(base / "no-ssh", session)
    refuse_host_tools(base, session)


@pytest.fixture(scope="session")
def _isolation_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("isolation")


@pytest.fixture(autouse=True)
def isolate_remote(_isolation_bin: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep every test away from real hosts, a real hub, real GPUs, and real SLURM.

    The session baseline (``pytest_configure``) already holds these values;
    this fixture sets them again per test (undone afterwards), so one test's
    overrides never leak into the next. ``HYPOTHEX_HUB_URL`` points at a dead
    port, ``HYPOTHEX_SSH``/``HYPOTHEX_SCP`` at a script that always fails, and
    ``nvidia-smi`` plus the SLURM commands on ``PATH`` at stubs that refuse to
    run, for every test (``docker`` tests too).
    Fixtures that need fakes (``fake_remote``, fake GPUs, fake SLURM) or the
    Docker wrappers (``tests/docker/conftest.py``) set their own values
    afterwards, so one that forgets fails closed instead of using the real tool.
    """
    monkeypatch.setenv("HYPOTHEX_HUB_URL", DEAD_HUB)
    monkeypatch.delenv("HYPOTHEX_FAKE_GPUS", raising=False)
    refuse_remote(_isolation_bin / "no-ssh", monkeypatch)
    refuse_host_tools(_isolation_bin, monkeypatch)
