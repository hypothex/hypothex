"""Identity and capabilities of this Hypothex environment."""

from __future__ import annotations

import json
import platform
import socket
import subprocess
import uuid

from pydantic import BaseModel

from hypothex._version import __version__
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.layout import Layout

PROTOCOL_VERSION = 1
CAPABILITIES: tuple[str, ...] = (
    "run",
    "launch",
    "stop",
    "rerun",
    "reinfer",
    "reeval",
    "events-ws",
)


class EnvironmentDescriptor(BaseModel):
    """What ``GET /.well-known/hypothex/environment`` returns."""

    environment_id: str
    label: str
    kind: str = "local"
    os: str
    arch: str
    hostname: str
    hx_version: str
    protocol_version: int
    gpus: int
    capabilities: list[str]


def count_gpus() -> int:
    """
    Return the number of NVIDIA GPUs visible to ``nvidia-smi``, or 0.

    Returns
    -------
    int
        GPU count; 0 if ``nvidia-smi`` is missing, times out, or fails.
    """
    try:
        out = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if out.returncode != 0:
        return 0
    return sum(1 for line in out.stdout.splitlines() if line.startswith("GPU "))


def load_descriptor(layout: Layout) -> EnvironmentDescriptor:
    """
    Load this environment's descriptor, creating a stable id on first use.

    Parameters
    ----------
    layout : Layout
        Home layout; the id lives in ``environment.json``.

    Returns
    -------
    EnvironmentDescriptor
        Descriptor with the persisted id and label and live system facts.
    """
    path = layout.environment_json
    if path.is_file():
        identity = json.loads(path.read_text(encoding="utf-8"))
    else:
        identity = {"environment_id": uuid.uuid4().hex, "label": socket.gethostname()}
        atomic_write_text(path, json.dumps(identity, indent=2))
    return EnvironmentDescriptor(
        environment_id=identity["environment_id"],
        label=identity["label"],
        os=platform.system().lower(),
        arch=platform.machine(),
        hostname=socket.gethostname(),
        hx_version=__version__,
        protocol_version=PROTOCOL_VERSION,
        gpus=count_gpus(),
        capabilities=list(CAPABILITIES),
    )
