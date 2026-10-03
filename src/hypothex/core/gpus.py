"""GPU inventory from ``nvidia-smi`` and which hx runs hold which GPUs."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from hypothex.core.context import Context
from hypothex.core.errors import ConfigError
from hypothex.core.records import ACTIVE_STATUSES

FAKE_GPUS_ENV = "HYPOTHEX_FAKE_GPUS"
NVIDIA_SMI_TIMEOUT_SECONDS = 10.0
GPU_QUERY: tuple[str, ...] = (
    "nvidia-smi",
    "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total",
    "--format=csv,noheader,nounits",
)
APPS_QUERY: tuple[str, ...] = (
    "nvidia-smi",
    "--query-compute-apps=gpu_uuid,pid",
    "--format=csv,noheader,nounits",
)
_FAKE_DEFAULTS: dict[str, Any] = {
    "name": "Fake GPU",
    "util": 0.0,
    "mem_used_mb": 0,
    "mem_total_mb": 81920,
    "external": False,
}


class GpuInfo(BaseModel):
    """
    One GPU on this host.

    ``util`` is the utilization in percent (0-100). ``external`` is True when a
    process that is not an hx run uses the GPU; ``run_id`` names the hx run
    holding it.
    """

    index: int
    name: str
    util: float
    mem_used_mb: int
    mem_total_mb: int
    external: bool
    run_id: str | None = None


def _number(text: str) -> float:
    """Parse an ``nvidia-smi`` number; ``[N/A]`` and similar read as 0."""
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_nvidia_smi(gpu_csv: str, apps_csv: str | None) -> list[GpuInfo]:
    """
    Parse the two ``nvidia-smi`` CSV queries into GPU rows.

    Parameters
    ----------
    gpu_csv : str
        Output of ``GPU_QUERY``: ``index, uuid, name, util, mem used, mem total``.
    apps_csv : str or None
        Output of ``APPS_QUERY``: ``gpu_uuid, pid`` per compute process. None
        when that query failed: then every GPU counts as external (busy).

    Returns
    -------
    list of GpuInfo
        Sorted by index; lines that are not GPU rows are skipped.

    Examples
    --------
    >>> gpus = parse_nvidia_smi("0, GPU-a, A100, 37, 1024, 81920", "GPU-a, 4242")
    >>> (gpus[0].index, gpus[0].util, gpus[0].external)
    (0, 37.0, True)
    """
    busy: set[str] | None = None
    if apps_csv is not None:
        busy = set()
        for line in apps_csv.splitlines():
            uuid, sep, _pid = line.partition(",")
            if sep and uuid.strip():
                busy.add(uuid.strip())
    gpus: list[GpuInfo] = []
    for line in gpu_csv.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        gpus.append(
            GpuInfo(
                index=int(parts[0]),
                name=", ".join(parts[2:-3]),
                util=_number(parts[-3]),
                mem_used_mb=int(_number(parts[-2])),
                mem_total_mb=int(_number(parts[-1])),
                external=True if busy is None else parts[1] in busy,
            )
        )
    return sorted(gpus, key=lambda g: g.index)


def _smi(args: tuple[str, ...]) -> str | None:
    """Run one ``nvidia-smi`` query; None when it is missing, hangs, or fails."""
    try:
        out = subprocess.run(
            list(args), capture_output=True, text=True, timeout=NVIDIA_SMI_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def _load_fake(path: Path) -> list[GpuInfo]:
    """Read a ``HYPOTHEX_FAKE_GPUS`` file (tests and demos)."""
    if not path.is_file():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise TypeError(f"top level is {type(items).__name__}")
        gpus = [GpuInfo.model_validate({**_FAKE_DEFAULTS, **item}) for item in items]
    except (ValueError, TypeError, ValidationError) as exc:
        raise ConfigError(f"{FAKE_GPUS_ENV}={path} is not a JSON list of GPUs: {exc}") from exc
    return sorted(gpus, key=lambda g: g.index)


def query_gpus() -> list[GpuInfo]:
    """
    List this host's GPUs as ``nvidia-smi`` sees them.

    ``external`` is True for a GPU with any compute process on it (hx runs
    included; use ``gpu_status`` to tell them apart). ``HYPOTHEX_FAKE_GPUS``
    set to a JSON file replaces ``nvidia-smi`` (tests, demos).

    Returns
    -------
    list of GpuInfo
        Sorted by index; empty when ``nvidia-smi`` is missing or fails.

    Raises
    ------
    ConfigError
        If the fake GPU file is not a JSON list of GPU objects.
    """
    fake = os.environ.get(FAKE_GPUS_ENV)
    if fake:
        return _load_fake(Path(fake))
    gpu_csv = _smi(GPU_QUERY)
    if gpu_csv is None:
        return []
    return parse_nvidia_smi(gpu_csv, _smi(APPS_QUERY))


def held_gpus(ctx: Context) -> dict[int, str]:
    """
    Map GPU index to the id of this environment's active run that holds it.

    Parameters
    ----------
    ctx : Context

    Returns
    -------
    dict of int to str
        GPUs listed in ``executor.gpus`` of queued or running runs.
    """
    held: dict[int, str] = {}
    mine = ctx.descriptor.environment_id
    for status in sorted(ACTIVE_STATUSES):
        for run in ctx.index.list_runs(status=status, include_archived=True, limit=None):
            if run.environment_id != mine:
                continue
            for index in run.executor.gpus:
                held.setdefault(index, run.run_id)
    return held


def gpu_status(ctx: Context, gpus: list[GpuInfo] | None = None) -> list[GpuInfo]:
    """
    List GPUs with the hx run holding each one.

    A GPU held by an hx run is never ``external``, even though the run's own
    process shows up in ``nvidia-smi``.

    Parameters
    ----------
    ctx : Context
    gpus : list of GpuInfo, optional
        GPUs as ``nvidia-smi`` sees them; default ``query_gpus()``.

    Returns
    -------
    list of GpuInfo
        Sorted by index.
    """
    held = held_gpus(ctx)
    seen = query_gpus() if gpus is None else gpus
    return [
        g.model_copy(
            update={"run_id": held.get(g.index), "external": g.external and g.index not in held}
        )
        for g in seen
    ]


def free_gpus(gpus: list[GpuInfo]) -> list[int]:
    """
    Return the indices no hx run holds and no other process uses.

    Parameters
    ----------
    gpus : list of GpuInfo
        Usually ``gpu_status(ctx)``.

    Returns
    -------
    list of int
        Sorted ascending.

    Examples
    --------
    >>> a = GpuInfo(index=1, name="x", util=0, mem_used_mb=0, mem_total_mb=1, external=False)
    >>> b = a.model_copy(update={"index": 0, "external": True})
    >>> free_gpus([a, b])
    [1]
    """
    return sorted(g.index for g in gpus if g.run_id is None and not g.external)
