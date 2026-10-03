"""Hub side of remote hosts: one connection supervisor per host, and the run mirror.

The hub keeps one supervisor task per host in ``environments.yaml``. A supervisor
opens the route (a plain URL, or SSH bootstrap plus a tunnel), checks the
descriptor, subscribes to the host's event log after the saved cursor, and mirrors
every ``run.*`` event into the hub store. Mirrored runs keep the host's
``environment_id``; the hub re-emits each one as ``mirror.run_updated`` so UI
streams update. Spec sections 5.3, 5.5, 5.6, and 8A.2-8A.3.
"""

from __future__ import annotations

import asyncio
import contextlib
import filecmp
import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeVar

import yaml
from pydantic import BaseModel

from hypothex.core.context import Context
from hypothex.core.cost import price_record
from hypothex.core.environment import PROTOCOL_VERSION
from hypothex.core.errors import HypothexError, StoreError
from hypothex.core.events import Event
from hypothex.core.fsutil import atomic_write_text, read_yaml
from hypothex.core.ids import utcnow
from hypothex.core.index import index_run
from hypothex.core.layout import HX_DIR, reserved_run_path
from hypothex.core.records import ACTIVE_STATUSES, Artifact, RunRecord
from hypothex.core.store import ProjectEntry, dir_lock, run_lock
from hypothex.remote.bootstrap import BootstrapError, ensure_server
from hypothex.remote.client import EnvClient, EnvRequestError, RemoteFile
from hypothex.remote.config import EnvironmentsFile, HostKind, HostSpec
from hypothex.remote.ssh import SshTarget, Tunnel

log = logging.getLogger(__name__)

ConnState = Literal[
    "connecting", "bootstrapping", "connected", "stale", "upgrade", "error", "disabled"
]

MIRROR_FILES = (
    "run.yaml",
    "scores.jsonl",
    "metrics.jsonl",
    "metrics_nonfinite.jsonl",
    "notes.md",
    "usage.jsonl",
    "config.yaml",
    "git.diff",
    "git.stat",
)
MIRROR_DIRS = ("predictions", "traces", "samples", "env", "logs")
MIRROR_MAX_BYTES = 200 * 1024 * 1024
LOG_TAIL_BYTES = 8 * 1024 * 1024
"""Logs are mirrored as tails (spec 5.3, 8A.3): at most the last 8 MiB of each, fetched whole."""
CLAIMS_DIR = ".claims"
"""``<store>/.claims/<run_id>.json``: the project and environment that own a mirrored run id."""
INDEX_PENDING = ".mirror-index-pending"
"""Written (durably) before a mirror first changes a run folder and removed after its index
and manifest; seen again (a replay, or the next hub start), the index is redone."""
SKIPS_FILE = f"{HX_DIR}/mirror-skips.json"
"""``<run_dir>/.hx/mirror-skips.json``: ``{path: {reason, size, max_bytes}}`` for every listed file
the hub does not hold. ``.hx/`` is reserved (``reserved_run_path``): no host path can address it."""

BACKOFF_SECONDS: tuple[float, ...] = (3.0, 4.0, 8.0, 16.0)
STABLE_AFTER_SECONDS = 30.0
STALE_AFTER_SECONDS = 60.0
PING_INTERVAL_SECONDS = 10.0
PING_TIMEOUT_SECONDS = 5.0
REMOTE_FILE_KIND = "remote_file"
MANIFEST_NAME = ".mirror.json"
_SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,200}")
_MESSAGE_LIMIT = 2000


class HostUnavailableError(HypothexError):
    """The host is unknown or not connected, so nothing can be forwarded to it."""


class HostState(BaseModel):
    """
    Connection state of one host, as the hub sees it.

    ``since`` is when ``state`` last changed; for ``stale`` it is the time of the
    last successful contact.

    Examples
    --------
    >>> from hypothex.core.ids import utcnow
    >>> HostState(name="gpu1", kind="ssh", state="connecting", since=utcnow()).last_sequence
    0
    """

    name: str
    kind: HostKind | Literal["local"]  # "local": the hub's own row in GET /api/v1/hosts
    state: ConnState
    since: datetime
    message: str = ""
    environment_id: str | None = None
    hx_version: str | None = None
    last_sequence: int = 0
    local_port: int | None = None


class Backoff:
    """
    Reconnect delays 3/4/8/16 s; the sequence restarts after a stable connection.

    Parameters
    ----------
    delays : tuple of float
        Delays in order; the last one repeats.
    stable_after : float
        A connection that lasted at least this long resets the sequence.

    Examples
    --------
    >>> b = Backoff()
    >>> [b.next_delay(0.0) for _ in range(5)]
    [3.0, 4.0, 8.0, 16.0, 16.0]
    >>> b.connected(100.0)
    >>> b.next_delay(131.0)
    3.0
    """

    def __init__(
        self,
        delays: tuple[float, ...] = BACKOFF_SECONDS,
        stable_after: float = STABLE_AFTER_SECONDS,
    ) -> None:
        if not delays:
            raise ValueError("delays must not be empty")
        self.delays = tuple(delays)
        self.stable_after = stable_after
        self.attempt = 0
        self._connected_at: float | None = None

    def connected(self, now: float) -> None:
        """
        Record that a connection was established.

        Parameters
        ----------
        now : float
            Monotonic time of the connection.
        """
        self._connected_at = now

    def next_delay(self, now: float) -> float:
        """
        Return the delay before the next attempt and advance the sequence.

        Parameters
        ----------
        now : float
            Monotonic time of the failure or disconnect.

        Returns
        -------
        float
            Seconds to wait.
        """
        if self._connected_at is not None and now - self._connected_at >= self.stable_after:
            self.attempt = 0
        self._connected_at = None
        delay = self.delays[min(self.attempt, len(self.delays) - 1)]
        self.attempt += 1
        return delay


# mirror ------------------------------------------------------------------------------
def wanted_path(rel: str) -> bool:
    """
    Return True when a run-relative path is one the hub mirrors.

    Only ``MIRROR_FILES`` and files inside ``MIRROR_DIRS`` qualify; absolute,
    non-normalised, and ``..`` paths never do.

    Parameters
    ----------
    rel : str
        POSIX path relative to the run folder.

    Returns
    -------
    bool

    Examples
    --------
    >>> wanted_path("scores.jsonl"), wanted_path("predictions/predictions.jsonl")
    (True, True)
    >>> wanted_path("artifacts/model.pt"), wanted_path("logs/../../x"), wanted_path("/etc/passwd")
    (False, False, False)
    """
    path = PurePosixPath(rel)
    if not rel or "\\" in rel or path.is_absolute() or str(path) != rel:
        return False
    if any(part in (".", "..") for part in path.parts):
        return False
    if rel in MIRROR_FILES:
        return True
    return len(path.parts) > 1 and path.parts[0] in MIRROR_DIRS


def _safe_name(name: str | None) -> bool:
    return name is not None and name not in (".", "..") and _SAFE_NAME.fullmatch(name) is not None


def _read_manifest(run_dir: Path) -> dict[str, list[int]]:
    try:
        data = json.loads((run_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, list) and _mirrored_path(k)}


def _mirrored_path(rel: object) -> bool:
    """A path the mirror may hold in ``.mirror.json`` and so may delete (never ``run.yaml``)."""
    return (
        isinstance(rel, str)
        and rel != "run.yaml"
        and wanted_path(rel)
        and not reserved_run_path(rel)
    )


def _read_local(ctx: Context, project: str, run_id: str) -> RunRecord | None:
    try:
        return ctx.store.read_record(project, run_id)
    except StoreError:
        return None


def _claim_path(ctx: Context, run_id: str) -> Path:
    return ctx.layout.store / CLAIMS_DIR / f"{run_id}.json"


def _claim_owner(ctx: Context, run_id: str) -> dict[str, str] | None:
    """The ``{project, environment_id}`` that claimed ``run_id``, or None."""
    try:
        data = json.loads(_claim_path(ctx, run_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):  # unreadable: never taken over
        return {"project": "?", "environment_id": "?"}
    return {"project": str(data.get("project")), "environment_id": str(data.get("environment_id"))}


def _conflict(ctx: Context, environment_id: str, project: str, run_id: str) -> str | None:
    """
    Return why a remote run must not be written here, or None.

    Run ids are unique across the hub: the claim, the index, and every
    project folder of the store are checked, not only this project.
    """
    owner = _claim_owner(ctx, run_id)
    if owner is not None:
        if owner != {"project": project, "environment_id": environment_id}:
            return (
                f"run {run_id} is claimed by environment {owner['environment_id']} "
                f"in project {owner['project']!r}"
            )
        return None
    store = ctx.layout.store
    for folder in sorted(store.iterdir()) if store.is_dir() else []:
        other = folder.name != project and not folder.name.startswith(".")
        if other and (folder / "runs" / run_id).exists():
            return f"run {run_id} already exists in project {folder.name!r}"
    indexed = ctx.index.get_run(run_id)
    if indexed is not None and indexed.project != project:
        return f"run {run_id} already exists in project {indexed.project!r}"
    local = _read_local(ctx, project, run_id) or indexed
    if local is not None and local.environment_id != environment_id:
        return f"run {run_id} belongs to environment {local.environment_id}"
    return None


def _claim(ctx: Context, environment_id: str, project: str, run_id: str) -> str | None:
    """
    Claim ``run_id`` hub-wide for this project and environment, before any install.

    Under the shared claim lock the conflict check runs again and, when it
    passes, ``<store>/.claims/<run_id>.json`` is written. The claim stays when a
    later install or index fails, so no other project or environment can take
    the id in between.

    Returns
    -------
    str or None
        Why the run must not be installed here, or None when the claim is ours.
    """
    with dir_lock(ctx.layout.store / CLAIMS_DIR):
        reason = _conflict(ctx, environment_id, project, run_id)
        if reason is None and _claim_owner(ctx, run_id) is None:
            owner = {"project": project, "environment_id": environment_id}
            atomic_write_text(_claim_path(ctx, run_id), json.dumps(owner))
        return reason


def _read_remote_record(path: Path) -> RunRecord | None:
    try:
        return RunRecord.model_validate(read_yaml(path))
    except (ValueError, yaml.YAMLError):
        return None


def _ensure_project(ctx: Context, client: EnvClient, host: str, project: str) -> None:
    """
    Copy a project from the host, or refresh this host's copy (spec 5.2: the hub holds the index).

    Without its ``ProjectEntry`` (the ``hypothex.yaml`` snapshot) a project
    registered only on the host would show no tasks, leaderboards, or sweep
    stats on the hub. The copy is marked ``remote_host`` and is fetched again
    on every mirror, so a task or metric version added on the host reaches
    the hub. A project registered on the hub (or copied from another host) is
    never replaced; a later ``hx register`` of a checkout on the hub replaces
    the copy.
    """
    known: ProjectEntry | None = None
    with contextlib.suppress(StoreError):
        known = ctx.store.load_project(project)
    if known is not None and known.remote_host != host:
        return
    try:
        data = client.get_json(f"/api/v1/projects/{project}/entry")
        entry = ProjectEntry.model_validate(data).model_copy(update={"remote_host": host})
    except (HypothexError, ValueError) as exc:
        log.info("host %s: project %s not copied: %s", host, project, exc)
        return
    if entry.project != project or entry == known:
        return
    ctx.store.save_project(entry)
    ctx.index.upsert_project(entry)


def _hosted(artifacts: list[Artifact], host: str) -> list[Artifact]:
    """Mark the host's own artifacts (``host: local`` there) with the host's name."""
    return [a.model_copy(update={"host": host}) if a.host == "local" else a for a in artifacts]


def mirror_run(
    ctx: Context,
    client: EnvClient,
    host: str,
    environment_id: str,
    project: str,
    run_id: str,
    *,
    usd_per_gpu_hour: float | None = None,
) -> tuple[RunRecord, bool] | None:
    """
    Copy one remote run's small files into the hub store and index it.

    ``run.yaml`` is fetched first; a run without one (deleted on the host) is
    skipped. Then every listed file that ``wanted_path`` accepts is fetched
    whole into a per-run staging folder, except files whose size and mtime
    match the last mirror (``.mirror.json``) and files larger than
    ``MIRROR_MAX_BYTES`` (recorded as ``remote_file`` artifacts with the host
    name). A file mirrored before (in ``.mirror.json``) that the host no
    longer lists, or no longer serves, is deleted here. ``logs/*`` are tails:
    at most the last ``LOG_TAIL_BYTES`` (spec 5.3, 8A.3). Only when every
    fetch succeeded is the run id claimed hub-wide (``_claim``) and are the
    files installed, in one pass under the run lock (``_install``); nothing is
    ever appended. Artifacts the host recorded as ``local`` get the host's
    name, and an ended run gets its ``cost`` at the host's price
    (``price_record``). A project the hub does not know is copied from the
    host first, and a copy from this host is refreshed (``_ensure_project``).

    Parameters
    ----------
    ctx : Context
        The hub context.
    client : EnvClient
        Client of the host's env server.
    host : str
        Host name from ``environments.yaml``.
    environment_id : str
        The host's environment id; written into the mirrored record.
    project : str
        Project of the run.
    run_id : str
        Run id.
    usd_per_gpu_hour : float, optional
        The host's price per GPU hour from ``environments.yaml``.

    Returns
    -------
    tuple of (RunRecord, bool) or None
        The mirrored record and whether any file changed; None when the run was
        skipped (unsafe name, owned by another environment, or gone).
    """
    if not (_safe_name(project) and _safe_name(run_id)):
        log.warning("host %s: skipping run with unsafe name %r/%r", host, project, run_id)
        return None
    reason = _conflict(ctx, environment_id, project, run_id)
    if reason is not None:
        log.warning("host %s: not mirroring: %s", host, reason)
        return None
    run_dir = ctx.layout.run_dir(project, run_id)
    ctx.layout.home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ctx.layout.home, prefix=f".mirror-{run_id}-") as tmp:
        staging = Path(tmp)
        if not client.fetch_file(
            run_id, "run.yaml", staging / "run.yaml", max_bytes=MIRROR_MAX_BYTES
        ):
            return None
        record = _read_remote_record(staging / "run.yaml")
        if record is None or record.run_id != run_id or record.project != project:
            log.warning("host %s: run.yaml of %s is unreadable or mismatched", host, run_id)
            return None
        _ensure_project(ctx, client, host, project)
        manifest = _read_manifest(run_dir)
        staged: list[tuple[RemoteFile, Path]] = []
        remote_only: list[Artifact] = []
        skipped: dict[str, dict[str, object]] = {}
        unfetched: list[RemoteFile] = []
        listed: set[str] = set()
        for entry in client.list_files(run_id):
            listed.add(entry.path)
            if entry.path == "run.yaml" or reserved_run_path(entry.path):
                continue  # .hx/ holds the hub's own state: never taken from a host
            if not wanted_path(entry.path):
                continue
            if _too_big(entry):
                remote_only.append(_remote_artifact(entry, host))
                skipped[entry.path] = _skip_note("too big", entry)
                continue
            unchanged = manifest.get(entry.path) == [entry.size, entry.mtime_ns]
            if unchanged and (run_dir / entry.path).is_file():
                continue
            fetched = _fetch(client, run_id, staging, entry)
            if fetched is None:
                unfetched.append(entry)
            else:
                staged.append((entry, fetched))
        # mirrored before but no longer listed: deleted on the host, so its copy here goes
        gone: list[str] = [rel for rel in manifest if rel not in listed]
        if unfetched:
            # listed but not served: deleted since the listing (404) or grown too big (413)
            relisted = {f.path: f for f in client.list_files(run_id)}
            for entry in unfetched:
                now = relisted.get(entry.path)
                if now is None:
                    gone.append(entry.path)  # still missing: its stale copy here goes
                elif _too_big(now):
                    remote_only.append(_remote_artifact(now, host))
                    skipped[now.path] = _skip_note("too big", now)
                else:
                    fetched = _fetch(client, run_id, staging, now)
                    if fetched is None:
                        skipped[now.path] = _skip_note("not served", now)
                    else:
                        staged.append((now, fetched))
        record = price_record(
            record.model_copy(
                update={
                    "environment_id": environment_id,
                    "artifacts": [*_hosted(record.artifacts, host), *remote_only],
                }
            ),
            usd_per_gpu_hour,
        )
        # every file is here: claim the id hub-wide, then install everything at once
        reason = _claim(ctx, environment_id, project, run_id)
        if reason is not None:
            log.warning("host %s: not mirroring: %s", host, reason)
            return None
        with run_lock(run_dir):
            changed = _install(ctx, run_dir, staged, manifest, record, gone, skipped)
    return record, changed


def _too_big(entry: RemoteFile) -> bool:
    """A non-log file over ``MIRROR_MAX_BYTES`` stays on the host (logs are tails)."""
    return entry.size > MIRROR_MAX_BYTES and not entry.path.startswith("logs/")


def _remote_artifact(entry: RemoteFile, host: str) -> Artifact:
    return Artifact(kind=REMOTE_FILE_KIND, path=entry.path, host=host, size=entry.size)


def _skip_note(reason: str, entry: RemoteFile) -> dict[str, object]:
    return {"reason": reason, "size": entry.size, "max_bytes": MIRROR_MAX_BYTES}


def _fetch(client: EnvClient, run_id: str, staging: Path, entry: RemoteFile) -> Path | None:
    """Fetch one listed file whole into staging; None when the host did not serve it."""
    is_log = entry.path.startswith("logs/")
    dest = staging / "files" / entry.path
    dest.parent.mkdir(parents=True, exist_ok=True)
    limit = LOG_TAIL_BYTES if is_log else MIRROR_MAX_BYTES
    if client.fetch_file(run_id, entry.path, dest, max_bytes=limit, tail=is_log):
        return dest
    return None


def _durable_touch(path: Path) -> None:
    """Create ``path`` and make it durable (fsync of the file and its folder)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    folder = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)


def _drop_local(run_dir: Path, rel: str) -> bool:
    """
    Delete a local file the host no longer serves; True when one was there.

    Folders the delete leaves empty go too (never ``run_dir``), so the host may
    put a file where a mirrored folder was.
    """
    path = run_dir / rel
    if not (path.is_file() or path.is_symlink()):
        return False
    path.unlink()
    for parent in path.parents:
        if parent == run_dir or run_dir not in parent.parents:
            break
        try:
            parent.rmdir()
        except OSError:  # not empty (or already gone)
            break
    return True


def _install(
    ctx: Context,
    run_dir: Path,
    staged: list[tuple[RemoteFile, Path]],
    manifest: dict[str, list[int]],
    record: RunRecord,
    gone: list[str],
    skipped: dict[str, dict[str, object]],
) -> bool:
    """
    Install fully fetched files, then ``run.yaml``, then re-index; caller holds the run lock.

    ``.mirror-index-pending`` is made durable before the first change to the
    live folder and removed last, so a crash at any step leaves it: the next
    mirror (or ``reindex_pending`` at hub start) re-indexes. Every file
    replaces its local copy whole (``os.replace``), so installing the same
    bytes again changes nothing. Files the host no longer serves are deleted
    (``gone``) before any install, with the folders that leaves empty, so a
    path that changed between file and folder on the host installs; skipped
    files are deleted too and listed in ``.hx/mirror-skips.json``
    (``skipped``), never marked next to the file.

    Returns
    -------
    bool
        Whether any file or the record changed.
    """
    pending = run_dir / INDEX_PENDING
    redo = pending.exists() or ctx.index.get_run(record.run_id) is None
    _durable_touch(pending)  # before the first live change
    changed = False
    for rel in [*gone, *skipped]:  # first: a new file may take an old file's (or folder's) place
        changed |= _drop_local(run_dir, rel)  # no stale copy of a file the hub does not hold
        manifest.pop(rel, None)
    for entry, path in staged:
        dst = run_dir / entry.path
        if not (dst.is_file() and filecmp.cmp(path, dst, shallow=False)):
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, dst)
            changed = True
        manifest[entry.path] = [entry.size, entry.mtime_ns]
    changed |= _write_skips(run_dir, skipped)
    if _read_local(ctx, record.project, record.run_id) != record:
        ctx.store.write_record(record)  # after the files: never terminal next to stale files
        changed = True
    if changed or redo:
        index_run(ctx.index, ctx.store, record)
    atomic_write_text(run_dir / MANIFEST_NAME, json.dumps(manifest, sort_keys=True))
    pending.unlink()  # last: the whole install is acknowledged
    return changed


def _write_skips(run_dir: Path, skipped: dict[str, dict[str, object]]) -> bool:
    """
    Make ``.hx/mirror-skips.json`` list exactly this mirror's skipped files.

    A skipped file is never in ``.mirror.json``, so every mirror decides it
    again and the list is complete each time; with nothing skipped the file is
    removed. Returns whether the file changed.
    """
    path = run_dir / SKIPS_FILE
    text = json.dumps(skipped, sort_keys=True) if skipped else None
    try:
        old: str | None = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        old = None
    if old == text:
        return False
    if text is None:
        path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, text)
    return True


def reindex_pending(ctx: Context) -> list[str]:
    """
    Re-index every mirrored run left with ``.mirror-index-pending`` (call at hub start).

    A mirror cut short (a crash, a failed ``index_run``) leaves the marker; a
    replay of that run re-indexes too, but a run whose host never sends
    another event would keep a stale index without this.

    Parameters
    ----------
    ctx : Context
        The hub context.

    Returns
    -------
    list of str
        The run ids re-indexed (a run without a ``run.yaml`` yet keeps its
        marker for its next mirror).
    """
    store = ctx.layout.store
    done: list[str] = []
    for marker in sorted(store.glob(f"*/runs/*/{INDEX_PENDING}")) if store.is_dir() else []:
        run_dir = marker.parent
        project, run_id = run_dir.parent.parent.name, run_dir.name
        with run_lock(run_dir):
            record = _read_local(ctx, project, run_id)
            if record is None or not marker.exists():
                continue
            index_run(ctx.index, ctx.store, record)
            marker.unlink()
        done.append(run_id)
    return done


def _reason(event: Event) -> str | None:
    """The ``reason`` of a host event (``run.lost``, ``run.killed``, ``run.failed``), if any."""
    value = event.payload.get("reason") if isinstance(event.payload, dict) else None
    return str(value) if value is not None else None


def _emit_mirror(
    ctx: Context,
    host: str,
    environment_id: str,
    record: RunRecord,
    original_type: str,
    remote_sequence: int | None,
    *,
    reason: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "host": host,
        "environment_id": environment_id,
        "original_type": original_type,
        "remote_sequence": remote_sequence,
        "status": record.status.value,
    }
    if reason is not None:
        payload["reason"] = reason  # why the run ended on the host (e.g. SLURM NODE_FAIL)
    if remote_sequence is None:  # a refresh: no remote event to deduplicate
        ctx.events.append(
            "mirror.run_updated", project=record.project, run_id=record.run_id, payload=payload
        )
        return
    # events.db and the cursor (index.db) are two databases: a crash between this event
    # and the cursor write replays the remote event, and the key drops the repeat
    ctx.events.append_once(
        f"mirror:{host}:{environment_id}:{remote_sequence}",
        "mirror.run_updated",
        project=record.project,
        run_id=record.run_id,
        payload=payload,
    )


def mirror_event(
    ctx: Context,
    client: EnvClient,
    host: str,
    environment_id: str,
    event: Event,
    *,
    usd_per_gpu_hour: float | None = None,
) -> None:
    """
    Mirror the run a remote event is about, then re-emit it as ``mirror.run_updated``.

    Events that are not ``run.*`` or carry no project/run id are ignored. The
    re-emitted payload is ``{host, environment_id, original_type, remote_sequence,
    status}``, plus ``reason`` when the host's event has one.

    Parameters
    ----------
    ctx : Context
        The hub context.
    client : EnvClient
        Client of the host's env server.
    host : str
        Host name from ``environments.yaml``.
    environment_id : str
        The host's environment id.
    event : Event
        Event from the host's log.
    usd_per_gpu_hour : float, optional
        The host's price per GPU hour; ended runs get their ``cost`` at it.
    """
    if not event.type.startswith("run.") or event.run_id is None or event.project is None:
        return
    mirrored = mirror_run(
        ctx,
        client,
        host,
        environment_id,
        event.project,
        event.run_id,
        usd_per_gpu_hour=usd_per_gpu_hour,
    )
    if mirrored is None:
        return
    _emit_mirror(
        ctx, host, environment_id, mirrored[0], event.type, event.sequence, reason=_reason(event)
    )


class _UpgradeRequiredError(Exception):
    """The host speaks another protocol version; retrying cannot help."""


AUTH_FAILURE_STATUSES = frozenset({401, 403})
"""HTTP answers of an env server that does not accept the hub's token (spec 5.3)."""


def _auth_failure(exc: BaseException) -> int | None:
    """The 401/403 status of an authentication failure, else None."""
    if isinstance(exc, EnvRequestError) and exc.status_code in AUTH_FAILURE_STATUSES:
        return exc.status_code
    return None


T = TypeVar("T")


def _run_key(event: Event) -> tuple[str, str] | None:
    """The ``(project, run_id)`` a ``run.*`` event is about, or None."""
    if not event.type.startswith("run.") or event.project is None or event.run_id is None:
        return None
    return event.project, event.run_id


def _brief(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text[-_MESSAGE_LIMIT:]


# supervisors -------------------------------------------------------------------------
REPLAY_BATCH_EVENTS = 500
"""Most events one ``_apply`` call mirrors; each run in a batch is mirrored once."""


@dataclass
class _Supervisor:
    name: str
    spec: HostSpec
    state: HostState
    backoff: Backoff
    lock: threading.Lock = field(default_factory=threading.Lock)
    task: asyncio.Task[None] | None = None
    client: EnvClient | None = None
    tunnel: Tunnel | None = None
    last_ok: float | None = None
    last_ok_at: datetime | None = None
    failure: str = ""
    failed_bootstrap: bool = False
    pending: set[asyncio.Future[Any]] = field(default_factory=set)
    token: str | None = None


class Hub:
    """
    One connection supervisor per remote host, plus the mirror into the hub store.

    Hosts with ``route: local`` are the hub itself: they get no supervisor and
    always report ``connected``. Timing knobs (``backoff_delays``,
    ``stable_after``, ``stale_after``, ``ping_interval``) are attributes so tests
    can shorten them before ``start()``.

    Parameters
    ----------
    ctx : Context
        The hub context; mirrored runs, cursors, and ``host.state`` /
        ``mirror.run_updated`` events go here.
    hosts : EnvironmentsFile
        Parsed ``environments.yaml``.
    """

    def __init__(self, ctx: Context, hosts: EnvironmentsFile) -> None:
        self.ctx = ctx
        self.hosts = hosts
        self.backoff_delays: tuple[float, ...] = BACKOFF_SECONDS
        self.stable_after = STABLE_AFTER_SECONDS
        self.stale_after = STALE_AFTER_SECONDS
        self.ping_interval = PING_INTERVAL_SECONDS
        self._started = False
        self._sups: dict[str, _Supervisor] = {}
        for name, spec in sorted(hosts.environments.items()):
            self._sups[name] = self._new_supervisor(name, spec)

    def _new_supervisor(self, name: str, spec: HostSpec) -> _Supervisor:
        now = utcnow()
        if spec.route == "local":
            state = HostState(
                name=name,
                kind=spec.kind,
                state="connected",
                since=now,
                message="hub",
                environment_id=self.ctx.descriptor.environment_id,
                hx_version=self.ctx.descriptor.hx_version,
            )
        else:
            state = HostState(name=name, kind=spec.kind, state="connecting", since=now)
        return _Supervisor(name=name, spec=spec, state=state, backoff=Backoff())

    # public API ----------------------------------------------------------------------
    async def start(self) -> None:
        """
        Start one supervisor task per remote host (no-op when already started).

        First re-indexes mirrored runs a cut-short mirror left with
        ``.mirror-index-pending`` (``reindex_pending``).
        """
        if self._started:
            return
        self._started = True
        try:
            repaired = reindex_pending(self.ctx)
        except Exception:  # noqa: BLE001 - each run's next mirror redoes it anyway
            log.exception("re-indexing half-mirrored runs failed")
        else:
            if repaired:
                log.info("re-indexed half-mirrored runs: %s", ", ".join(repaired))
        for sup in self._sups.values():
            if sup.spec.route != "local":
                self._launch(sup)

    async def stop(self) -> None:
        """Cancel every supervisor, wait for its shielded mirror work, and close its tunnel."""
        for sup in self._sups.values():
            await self._halt(sup)
        self._started = False

    async def add_host(self, name: str, spec: HostSpec) -> HostState:
        """
        Add a host, or restart only this host's supervisor when its spec changed.

        Other hosts keep their sessions and tunnels (``hx hosts add``, ``map``,
        and ``upgrade`` call this instead of rebuilding the hub).

        Parameters
        ----------
        name : str
            Host name.
        spec : HostSpec
            The host's entry.

        Returns
        -------
        HostState
            The host's state right after the change.
        """
        old = self._sups.get(name)
        if old is not None:
            if old.spec == spec:
                return old.state.model_copy()
            await self._halt(old)
        sup = self._new_supervisor(name, spec)
        self._sups[name] = sup
        self.hosts.environments[name] = spec
        if self._started and spec.route != "local":
            self._launch(sup)
        return sup.state.model_copy()

    async def remove_host(self, name: str) -> None:
        """
        Stop one host's supervisor and forget the host (``hx hosts rm``).

        Parameters
        ----------
        name : str
            Host name; unknown names are ignored.
        """
        sup = self._sups.pop(name, None)
        self.hosts.environments.pop(name, None)
        if sup is not None:
            await self._halt(sup)

    async def connect(self, name: str) -> HostState:
        """
        (Re)start a host's supervisor with a fresh backoff.

        Parameters
        ----------
        name : str
            Host name.

        Returns
        -------
        HostState
            The state right after the restart (usually ``connecting``).
        """
        sup = self._get(name)
        if sup.spec.route != "local":
            await self._halt(sup)
            self._set(sup, "connecting")
            self._launch(sup)
        return sup.state.model_copy()

    async def disconnect(self, name: str) -> HostState:
        """
        Stop a host's supervisor and mark it ``disabled`` until ``connect``.

        Parameters
        ----------
        name : str
            Host name.

        Returns
        -------
        HostState
            The ``disabled`` state.
        """
        sup = self._get(name)
        if sup.spec.route != "local":
            await self._halt(sup)
            self._set(sup, "disabled", "disconnected")
        return sup.state.model_copy()

    def state(self, name: str) -> HostState:
        """
        Return one host's connection state.

        Parameters
        ----------
        name : str
            Host name.

        Returns
        -------
        HostState

        Raises
        ------
        HostUnavailableError
            If no such host is configured.
        """
        return self._get(name).state.model_copy()

    def states(self) -> list[HostState]:
        """
        Return every host's state, sorted by name.

        Returns
        -------
        list of HostState
        """
        return [self._sups[n].state.model_copy() for n in sorted(self._sups)]

    def client(self, name: str) -> EnvClient:
        """
        Return the client of a connected host.

        Parameters
        ----------
        name : str
            Host name.

        Returns
        -------
        EnvClient

        Raises
        ------
        HostUnavailableError
            If the host is unknown, is the hub itself, or is not ``connected``.
        """
        sup = self._get(name)
        if sup.spec.route == "local":
            raise HostUnavailableError(f"host {name!r} is the hub itself")
        if sup.state.state != "connected" or sup.client is None:
            detail = f": {sup.state.message}" if sup.state.message else ""
            raise HostUnavailableError(f"host {name!r} is {sup.state.state}{detail}")
        return sup.client

    # state ---------------------------------------------------------------------------
    def _get(self, name: str) -> _Supervisor:
        try:
            return self._sups[name]
        except KeyError:
            raise HostUnavailableError(f"unknown host {name!r}") from None

    def _set(
        self,
        sup: _Supervisor,
        state: ConnState,
        message: str = "",
        *,
        since: datetime | None = None,
        **fields: object,
    ) -> None:
        changed = sup.state.state != state
        update: dict[str, object] = {"state": state, "message": message, **fields}
        if changed or since is not None:
            update["since"] = since or utcnow()
        sup.state = sup.state.model_copy(update=update)
        if changed:
            self.ctx.events.append("host.state", payload=sup.state.model_dump(mode="json"))

    def _mark_ok(self, sup: _Supervisor) -> None:
        sup.last_ok = time.monotonic()
        sup.last_ok_at = utcnow()
        if sup.state.state == "stale":
            self._set(sup, "connected")

    def _is_stale(self, sup: _Supervisor) -> bool:
        return sup.last_ok is not None and time.monotonic() - sup.last_ok > self.stale_after

    # supervisor loop -----------------------------------------------------------------
    def _launch(self, sup: _Supervisor) -> None:
        sup.backoff = Backoff(self.backoff_delays, self.stable_after)
        sup.task = asyncio.create_task(self._supervise(sup), name=f"hx-hub-{sup.name}")

    async def _halt(self, sup: _Supervisor) -> None:
        task, sup.task = sup.task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._drain(sup)

    async def _drain(self, sup: _Supervisor) -> None:
        """Wait for the shielded worker threads of this host's old session."""
        while sup.pending:
            # asyncio.wait, not gather: a cancel of this wait must not cancel the threads' futures
            await asyncio.wait(list(sup.pending))

    async def _shielded(self, sup: _Supervisor, fn: Callable[..., T], *args: object) -> T:
        """Run ``fn`` in a worker thread that a cancel cannot split; ``_halt`` waits for it."""
        future: asyncio.Future[T] = asyncio.ensure_future(asyncio.to_thread(fn, *args))
        sup.pending.add(future)
        future.add_done_callback(sup.pending.discard)
        return await asyncio.shield(future)

    async def _supervise(self, sup: _Supervisor) -> None:
        while True:
            try:
                await self._session(sup)
                sup.failure, sup.failed_bootstrap = "connection closed", False
            except _UpgradeRequiredError as exc:
                self._set(sup, "upgrade", str(exc))
                return
            except EnvRequestError as exc:
                status = _auth_failure(exc)
                if status is not None:  # retrying with the same token cannot help
                    self._set(
                        sup,
                        "error",
                        f"authentication failed (HTTP {status}); reconnect or re-pair: "
                        f"hx hosts connect {sup.name}",
                    )
                    return
                sup.failure, sup.failed_bootstrap = _brief(exc), False
            except BootstrapError as exc:
                sup.failure, sup.failed_bootstrap = _brief(exc), True
            except Exception as exc:  # noqa: BLE001 - every failure means "retry later"
                sup.failure, sup.failed_bootstrap = _brief(exc), False
            log.info("host %s: %s", sup.name, sup.failure)
            delay = sup.backoff.next_delay(time.monotonic())
            message = f"retry in {delay:g}s: {sup.failure}"
            if self._is_stale(sup):
                self._set(sup, "stale", message, since=sup.last_ok_at)
            elif sup.failed_bootstrap:
                self._set(sup, "error", message)
            else:
                self._set(sup, "connecting", message)
            await self._wait(sup, delay)

    async def _wait(self, sup: _Supervisor, delay: float) -> None:
        end = time.monotonic() + delay
        while (left := end - time.monotonic()) > 0:
            await asyncio.sleep(min(left, 1.0))
            if sup.state.state != "stale" and self._is_stale(sup):
                self._set(sup, "stale", sup.state.message, since=sup.last_ok_at)

    async def _open_route(self, sup: _Supervisor) -> str:
        spec = sup.spec
        if spec.route == "url":
            if not spec.url:
                raise BootstrapError(f"host {sup.name!r} has route url but no url")
            return spec.url.rstrip("/")
        if not spec.ssh_alias:
            raise BootstrapError(f"host {sup.name!r} has route ssh but no ssh_alias")
        target = SshTarget(alias=spec.ssh_alias)  # ssh/scp from $HYPOTHEX_SSH/$HYPOTHEX_SCP
        if sup.state.state != "stale":
            self._set(sup, "bootstrapping")
        info = await self._shielded(sup, lambda: ensure_server(target, spec.home, kind=spec.kind))
        if info.protocol_version != PROTOCOL_VERSION:
            raise _UpgradeRequiredError(
                f"upgrade hx on {sup.name}: protocol {info.protocol_version}, "
                f"hub speaks {PROTOCOL_VERSION}"
            )
        tunnel = Tunnel(target, info.port)
        sup.tunnel = tunnel
        sup.token = info.token  # the env server's bearer token, read from server.json over ssh
        # tracked: a disconnect waits for start() before the session's cleanup stops it
        await self._shielded(sup, tunnel.start)
        return f"http://127.0.0.1:{tunnel.local_port}"

    def _close_route(self, sup: _Supervisor) -> None:
        tunnel, sup.tunnel = sup.tunnel, None
        if tunnel is not None:
            with contextlib.suppress(Exception):
                tunnel.stop()

    async def _session(self, sup: _Supervisor) -> None:
        client: EnvClient | None = None
        pinger: EnvClient | None = None
        try:
            sup.token = None  # route url: no token; route ssh: _open_route sets it
            base_url = await self._open_route(sup)
            client = EnvClient(base_url, token=sup.token)
            pinger = EnvClient(base_url, timeout=PING_TIMEOUT_SECONDS, token=sup.token)
            desc = await asyncio.to_thread(client.descriptor)
            if desc.protocol_version != PROTOCOL_VERSION:
                raise _UpgradeRequiredError(
                    f"upgrade hx on {sup.name}: protocol {desc.protocol_version}, "
                    f"hub speaks {PROTOCOL_VERSION}"
                )
            env_id = desc.environment_id
            cursor = await asyncio.to_thread(self._read_cursor, sup, env_id)
            sup.client = client
            sup.failed_bootstrap = False
            self._mark_ok(sup)
            sup.backoff.connected(time.monotonic())
            self._set(
                sup,
                "connected",
                environment_id=env_id,
                hx_version=desc.hx_version,
                last_sequence=cursor,
                local_port=sup.tunnel.local_port if sup.tunnel is not None else None,
            )
            consume = asyncio.create_task(self._consume(sup, client, env_id, cursor))
            watch = asyncio.create_task(self._watch(sup, pinger, client, env_id))
            try:
                done, _ = await asyncio.wait({consume, watch}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in (consume, watch):
                    task.cancel()
                await asyncio.gather(consume, watch, return_exceptions=True)
            for task in done:
                task.result()
        finally:
            sup.client = None
            # the shielded apply/refresh threads still use `client`: wait for them, even
            # through a cancel (_halt lands here when the session ended on its own), then
            # close both clients and the route, then let the cancel go on
            cancel: asyncio.CancelledError | None = None
            while sup.pending:
                try:
                    await self._drain(sup)
                except asyncio.CancelledError as exc:
                    cancel = exc
            for http in (client, pinger):
                if http is not None:
                    with contextlib.suppress(Exception):
                        http.close()
            self._close_route(sup)
            if cancel is not None:
                raise cancel

    def _read_cursor(self, sup: _Supervisor, env_id: str) -> int:
        with sup.lock:
            return self.ctx.index.get_cursor(sup.name, env_id)

    def _apply(
        self, sup: _Supervisor, client: EnvClient, env_id: str, events: list[Event]
    ) -> int | None:
        """
        Mirror a batch of events and advance the cursor, at most once per sequence.

        Each run the batch is about is mirrored once; then one
        ``mirror.run_updated`` is emitted per event, then the cursor is saved.
        Returns the new cursor, or None when every event was already applied.
        """
        with sup.lock:
            cursor = self.ctx.index.get_cursor(sup.name, env_id)
            fresh = [e for e in events if e.sequence > cursor]
            if not fresh:
                return None
            mirrored: dict[tuple[str, str], RunRecord | None] = {}
            for event in fresh:
                key = _run_key(event)
                if key is None or key in mirrored:
                    continue
                result = mirror_run(
                    self.ctx,
                    client,
                    sup.name,
                    env_id,
                    *key,
                    usd_per_gpu_hour=sup.spec.usd_per_gpu_hour,
                )
                mirrored[key] = result[0] if result is not None else None
            for event in fresh:
                key = _run_key(event)
                record = mirrored.get(key) if key is not None else None
                if record is not None:
                    _emit_mirror(
                        self.ctx,
                        sup.name,
                        env_id,
                        record,
                        event.type,
                        event.sequence,
                        reason=_reason(event),
                    )
            last = fresh[-1].sequence
            self.ctx.index.set_cursor(sup.name, env_id, last)
            return last

    async def _consume(self, sup: _Supervisor, client: EnvClient, env_id: str, cursor: int) -> None:
        # bounded: a long replay waits in the socket, not in the hub's memory
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=2 * REPLAY_BATCH_EVENTS)

        async def read() -> None:
            async for event in client.events(cursor):
                if event.sequence > cursor:
                    await queue.put(event)

        reader = asyncio.create_task(read())
        getter: asyncio.Future[Event] | None = None
        try:
            while True:
                if queue.empty():
                    if reader.done():
                        reader.result()  # the stream ended (or failed): end the session
                        return
                    getter = asyncio.ensure_future(queue.get())
                    await asyncio.wait({getter, reader}, return_when=asyncio.FIRST_COMPLETED)
                    if not getter.done():
                        getter.cancel()
                        continue
                    batch = [getter.result()]
                else:
                    batch = [queue.get_nowait()]
                while not queue.empty() and len(batch) < REPLAY_BATCH_EVENTS:
                    batch.append(queue.get_nowait())
                # shielded: a cancel never splits "mirror + emit" from "save cursor"
                await self._shielded(sup, self._apply, sup, client, env_id, batch)
                cursor = batch[-1].sequence
                sup.state = sup.state.model_copy(update={"last_sequence": cursor})
                self._mark_ok(sup)
        finally:
            if getter is not None:  # a cancel during the wait leaves it pending
                getter.cancel()
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)

    async def _watch(
        self, sup: _Supervisor, pinger: EnvClient, client: EnvClient, env_id: str
    ) -> None:
        while True:
            await asyncio.sleep(self.ping_interval)
            if sup.tunnel is not None and not sup.tunnel.alive():
                raise ConnectionError("ssh tunnel exited")
            try:
                await asyncio.to_thread(pinger.descriptor)
            except Exception as exc:  # noqa: BLE001 - a failed ping only counts toward stale
                if self._is_stale(sup):
                    raise ConnectionError(
                        f"no answer for {self.stale_after:g}s: {_brief(exc)}"
                    ) from exc
                continue
            self._mark_ok(sup)
            await self._shielded(sup, self._refresh_active, sup, client, env_id)

    def _refresh_active(self, sup: _Supervisor, client: EnvClient, env_id: str) -> None:
        """Re-mirror this host's queued/running runs; SDK metric writes emit no event."""
        with sup.lock:
            for status in sorted(ACTIVE_STATUSES):
                for record in self.ctx.index.list_runs(
                    status=status, include_archived=True, limit=None
                ):
                    if record.environment_id != env_id:
                        continue
                    mirrored = mirror_run(
                        self.ctx,
                        client,
                        sup.name,
                        env_id,
                        record.project,
                        record.run_id,
                        usd_per_gpu_hour=sup.spec.usd_per_gpu_hour,
                    )
                    if mirrored is not None and mirrored[1]:
                        _emit_mirror(self.ctx, sup.name, env_id, mirrored[0], "refresh", None)
