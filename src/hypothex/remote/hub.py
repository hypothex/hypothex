"""Hub side of remote hosts: one connection supervisor per host, and the run mirror.

The hub keeps one supervisor task per host in ``environments.yaml``. A supervisor
opens the route (a plain URL, or SSH bootstrap plus a tunnel), checks the
descriptor, subscribes to the host's event log after the saved cursor, and mirrors
every ``run.*`` event into the hub store. Mirrored runs keep the host's
``environment_id``; the hub re-emits each one as ``mirror.run_updated`` so UI
streams update. Spec sections 5.3, 5.5, 5.6, and 8A.2-8A.3.
"""

from __future__ import annotations

import contextlib
import filecmp
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel

from hypothex.core.context import Context
from hypothex.core.cost import price_record
from hypothex.core.errors import HypothexError, StoreError
from hypothex.core.events import Event
from hypothex.core.fsutil import atomic_write_text, read_yaml
from hypothex.core.index import index_run
from hypothex.core.layout import HX_DIR, reserved_run_path
from hypothex.core.records import Artifact, RunRecord
from hypothex.core.store import ProjectEntry, dir_lock, run_lock
from hypothex.remote.client import EnvClient, RemoteFile
from hypothex.remote.config import HostKind

log = logging.getLogger(__name__)

ConnState = Literal[
    "connecting", "bootstrapping", "connected", "stale", "upgrade", "error", "disabled"
]

MIRROR_FILES = (
    "run.yaml",
    "scores.jsonl",
    "metrics.jsonl",
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
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, list)}


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
    Copy a project the hub does not know from the host (spec 5.2: the hub holds the index).

    Without its ``ProjectEntry`` (the ``hypothex.yaml`` snapshot) a project
    registered only on the host would show no tasks, leaderboards, or sweep
    stats on the hub. The copy is marked ``remote_host``; a later ``hx
    register`` of a checkout on the hub replaces it.
    """
    with contextlib.suppress(StoreError):
        ctx.store.load_project(project)
        return
    try:
        data = client.get_json(f"/api/v1/projects/{project}/entry")
        entry = ProjectEntry.model_validate(data).model_copy(update={"remote_host": host})
    except (HypothexError, ValueError) as exc:
        log.info("host %s: project %s not copied: %s", host, project, exc)
        return
    if entry.project != project:
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
    name). ``logs/*`` are tails: at most the last ``LOG_TAIL_BYTES`` (spec
    5.3, 8A.3). Only when every fetch succeeded is the run id claimed
    hub-wide (``_claim``) and are the files installed, in one pass under the
    run lock (``_install``); nothing is ever appended. Artifacts the host
    recorded as ``local`` get the host's name, and an ended run gets its
    ``cost`` at the host's price (``price_record``). A project the hub does
    not know is copied from the host first (``_ensure_project``).

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
        for entry in client.list_files(run_id):
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
        gone: list[str] = []
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


def _drop_local(path: Path) -> bool:
    """Delete a local file the host no longer serves; True when one was there."""
    if path.is_file() or path.is_symlink():
        path.unlink()
        return True
    return False


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
    (``gone``); skipped files are deleted too and listed in
    ``.hx/mirror-skips.json`` (``skipped``), never marked next to the file.

    Returns
    -------
    bool
        Whether any file or the record changed.
    """
    pending = run_dir / INDEX_PENDING
    redo = pending.exists() or ctx.index.get_run(record.run_id) is None
    _durable_touch(pending)  # before the first live change
    changed = False
    for entry, path in staged:
        dst = run_dir / entry.path
        if not (dst.is_file() and filecmp.cmp(path, dst, shallow=False)):
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, dst)
            changed = True
        manifest[entry.path] = [entry.size, entry.mtime_ns]
    for rel in [*gone, *skipped]:
        changed |= _drop_local(run_dir / rel)  # no stale copy of a file the hub does not hold
        manifest.pop(rel, None)
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
