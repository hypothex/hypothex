"""Identity and capabilities of this Hypothex environment."""

from __future__ import annotations

import json
import logging
import platform
import socket
import uuid
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from hypothex._version import __version__
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.fsutil import atomic_write_text, read_yaml
from hypothex.core.layout import Layout

log = logging.getLogger(__name__)

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


class EnvironmentIdentity(BaseModel):
    """Public identity returned before a client sends any credential."""

    environment_id: str
    protocol_version: int
    hx_version: str


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
    from hypothex.core.gpus import query_gpus  # lazy: gpus imports Context

    try:
        return len(query_gpus())
    except ConfigError:
        return 0


def _read_identity(path: Path) -> dict[str, Any]:
    """
    Read ``environment.json``.

    Raises
    ------
    StoreError
        If the file cannot be read, is not JSON, or has no string
        ``environment_id`` and ``label``. The file is left as it is.
    """
    try:
        identity = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problem = str(exc)
    else:
        if isinstance(identity, dict) and all(
            isinstance(identity.get(key), str) for key in ("environment_id", "label")
        ):
            return identity
        problem = "expected an object with string environment_id and label"
    raise StoreError(
        f"{path} is unreadable ({problem}); fix it, or delete it and Hypothex takes "
        "the id back from this host's runs"
    )


def _local_environment_ids(layout: Layout, hostname: str) -> set[str]:
    """Ids from unclaimed runs on ``hostname``, excluding mirrored runs."""
    found: set[str] = set()
    for path in layout.store.glob("*/runs/*/run.yaml"):
        # A host reports its own hostname; matching ours does not make a
        # mirrored run local. Even a damaged claim keeps its run foreign.
        claim = layout.store / ".claims" / f"{path.parent.name}.json"
        if claim.exists() or claim.is_symlink():
            continue
        try:
            data = read_yaml(path)
        except (OSError, ValueError, yaml.YAMLError):  # an unreadable run is skipped
            continue
        if data.get("host") == hostname and isinstance(data.get("environment_id"), str):
            found.add(data["environment_id"])
    return found


def _recover_identity(layout: Layout) -> dict[str, str]:
    """
    Make the identity for a missing ``environment.json``.

    The id of this host's unclaimed runs in the store (``host`` is this
    hostname) is used again, so a lost file does not make every old local run
    foreign. Mirror claims exclude remote runs even when their hostname
    matches this machine. With no such local run a new id is made.

    Raises
    ------
    ConfigError
        If this host's runs name more than one environment id.
    """
    path = layout.environment_json
    hostname = socket.gethostname()
    ids = sorted(_local_environment_ids(layout, hostname))
    if len(ids) > 1:
        raise ConfigError(
            f"{path} is missing and the runs of host {hostname} name {len(ids)} environment "
            f"ids ({', '.join(ids)}); write the right one to {path} as "
            f'{{"environment_id": "<id>", "label": "{hostname}"}}'
        )
    if ids:
        log.warning(
            "%s was missing; took environment id %s back from this host's runs", path, ids[0]
        )
    return {"environment_id": ids[0] if ids else uuid.uuid4().hex, "label": hostname}


def load_descriptor(layout: Layout) -> EnvironmentDescriptor:
    """
    Load this environment's descriptor, creating a stable id on first use.

    When ``environment.json`` is missing and the store has runs of this host
    (``host`` is this hostname, with no mirror claim), their id is used again
    and a warning is logged; with no such run a new id is made. The id is then
    written to the file.

    Parameters
    ----------
    layout : Layout
        Home layout; the id lives in ``environment.json``.

    Returns
    -------
    EnvironmentDescriptor
        Descriptor with the persisted id, label, and kind, and live system facts.

    Raises
    ------
    ConfigError
        If the file is missing and this host's runs name more than one id.
    StoreError
        If the file is there but unreadable; it is never reset.

    Examples
    --------
    >>> import tempfile
    >>> home = Layout(Path(tempfile.mkdtemp()))
    >>> load_descriptor(home).environment_id == load_descriptor(home).environment_id
    True
    """
    path = layout.environment_json
    if path.is_file():
        identity = _read_identity(path)
    else:
        identity = _recover_identity(layout)
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
