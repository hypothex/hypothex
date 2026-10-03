"""Identity and capabilities of this Hypothex environment."""

from __future__ import annotations

import json
import platform
import socket
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
    Return the number of GPUs ``hypothex.core.gpus.query_gpus`` sees, or 0.

    One source for every GPU number: ``HYPOTHEX_FAKE_GPUS`` (tests, demos) or
    ``nvidia-smi``.

    Returns
    -------
    int
        GPU count; 0 if ``nvidia-smi`` is missing, times out, or fails, or the
        fake GPU file is unreadable.
    """
    from hypothex.core.errors import ConfigError
    from hypothex.core.gpus import query_gpus  # lazy: gpus imports Context

    try:
        return len(query_gpus())
    except ConfigError:
        return 0


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
        Descriptor with the persisted id, label, and kind, and live system facts.
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
        kind=identity.get("kind", "local"),
        os=platform.system().lower(),
        arch=platform.machine(),
        hostname=socket.gethostname(),
        hx_version=__version__,
        protocol_version=PROTOCOL_VERSION,
        gpus=count_gpus(),
        capabilities=list(CAPABILITIES),
    )
