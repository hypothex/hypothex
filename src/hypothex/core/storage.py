"""Bytes per project, host, and kind; plan-then-apply cleanup of archived runs' artifacts.

Sizes are allocated bytes (``st_blocks * 512``) from an ``lstat`` walk that
never follows a symlink. Cleanup never deletes a run's records: only recorded
artifact paths of archived, unstarred, ended runs, and files in a run's
``pulled/`` folder, and never a protected path.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import shutil
import stat
from collections import defaultdict
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from hypothex.core.context import Context
from hypothex.core.errors import HypothexError, StoreError
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.ids import utcnow
from hypothex.core.layout import HX_DIR, Layout
from hypothex.core.records import TERMINAL_STATUSES, RunRecord, RunStatus
from hypothex.core.settings import StorageSettings, write_private
from hypothex.core.store import dir_lock, run_lock

if TYPE_CHECKING:
    from hypothex.remote.client import EnvClient

StorageKind = Literal["run", "artifact", "pulled"]
LOCAL_HOST = "local"
CLEANABLE_SUBDIRS = ("artifacts", "pulled")


class StorageItem(BaseModel):
    """Bytes of one run folder, artifact, or pulled file, with its run's flags."""

    project: str
    run_id: str
    host: str
    environment_id: str
    kind: StorageKind
    artifact_kind: str | None
    path: str
    bytes: int
    files: int
    mtime: float | None
    exists: bool
    archived: bool
    starred: bool
    status: RunStatus
    ended_at: datetime | None


class StorageReport(BaseModel):
    """Every item, sums by project, host, and kind, and hosts that did not answer."""

    items: list[StorageItem]
    by_project: dict[str, int]
    by_host: dict[str, int]
    by_kind: dict[str, int]
    total_bytes: int
    errors: list[dict[str, str]]
    generated_at: datetime


class CleanPolicy(BaseModel, extra="forbid"):
    """What a cleanup may take: always archived runs only (spec 9)."""

    archived: Literal[True] = True
    older_than_days: int = Field(30, ge=0)
    kinds: list[str] = Field(default_factory=lambda: ["checkpoint"])
    projects: list[str] | None = None
    hosts: list[str] | None = None
    include_pulled: bool = True


class CleanItem(BaseModel):
    """One path a plan would delete."""

    project: str
    run_id: str
    host: str
    environment_id: str
    kind: Literal["artifact", "pulled"]
    artifact_kind: str | None
    path: str
    bytes: int
    mtime: float | None
    reason: str


class CleanPlan(BaseModel):
    """A dry run, stored in ``<home>/storage/plans/<plan_id>.json`` until applied or expired."""

    plan_id: str
    policy: CleanPolicy
    items: list[CleanItem]
    refused: list[dict[str, str]]
    total_bytes: int
    created_at: datetime
    expires_at: datetime
    created_by: str


class CleanResult(BaseModel):
    """What an apply deleted, skipped, and could not reach."""

    plan_id: str
    deleted: list[CleanItem]
    skipped: list[dict[str, Any]]
    freed_bytes: int
    errors: list[dict[str, str]]


class CleanedArtifact(BaseModel):
    """A deleted artifact, as recorded in ``<run_dir>/.hx/cleaned.json``."""

    path: str
    environment_id: str | None = None
    """Deletion target environment; None only for legacy manifests with unknown location."""
    bytes: int
    at: datetime
    actor: str
    plan_id: str


class CleanRefusedError(HypothexError):
    """An apply with an unknown or expired plan, or a wrong byte confirmation (HTTP 400)."""


class HostClients(Protocol):
    """The hub's connected hosts (``api.app.HubManager`` satisfies it)."""

    def names(self) -> list[str]:
        """Remote host names."""
        ...

    def client(self, name: str) -> EnvClient:
        """A connected host's client; ``HostUnavailableError`` when not connected."""
        ...

    def host_for_environment(self, environment_id: str) -> str | None:
        """The host that serves an environment, or None."""
        ...


def _allocated(info: os.stat_result) -> int:
    blocks = getattr(info, "st_blocks", None)
    return int(blocks) * 512 if blocks is not None else int(info.st_size)


def measure_path(path: Path) -> tuple[int, int, float | None]:
    """
    Measure a file or folder without following symlinks.

    Parameters
    ----------
    path : Path

    Returns
    -------
    tuple of (int, int, float or None)
        ``(bytes, files, newest mtime)``; ``(0, 0, None)`` when the path is
        missing. A symlink counts as one small file (the link itself).
    """
    try:
        info = os.lstat(path)
    except OSError:
        return 0, 0, None
    if not stat.S_ISDIR(info.st_mode):
        return _allocated(info), 1, info.st_mtime
    fd: int | None = None
    try:
        fd, _ = _open_cleanup_parent(str(path))
        return _measure_at(fd, path.name)
    except (OSError, RuntimeError):
        return 0, 0, None
    finally:
        if fd is not None:
            os.close(fd)


def _forms(path: str) -> set[Path]:
    """The literal absolute path, and the same name under its resolved parent folder."""
    literal = Path(os.path.abspath(path))
    forms = {literal}
    with contextlib.suppress(OSError, RuntimeError):
        forms.add(literal.parent.resolve() / literal.name)
    return forms


def _base_forms(root: Path) -> set[Path]:
    """Return both spellings of a trusted storage base, resolving the base itself."""
    forms = {Path(os.path.abspath(root))}
    with contextlib.suppress(OSError, RuntimeError):
        forms.add(root.resolve())
    return forms


def _roots(ctx: Context) -> set[Path]:
    roots = {Path("/"), Path.home(), ctx.layout.home, ctx.layout.store}
    for entry in ctx.store.list_projects():
        roots.update(Path(p) for p in [entry.repo, *entry.previous_repos])
    resolved = set()
    for root in roots:
        resolved.add(Path(os.path.abspath(root)))
        with contextlib.suppress(OSError, RuntimeError):
            resolved.add(root.resolve())
    return resolved


def _linked_below(home: Path, path: Path) -> bool:
    """True when a folder between ``home`` and ``path`` is a symlink (its target is not ours)."""
    folder = home
    for part in path.relative_to(home).parts[:-1]:
        folder = folder / part
        if folder.is_symlink():
            return True
    return False


def protected_reason(ctx: Context, path: str) -> str | None:
    """
    Tell whether cleanup must never delete a path.

    Parameters
    ----------
    ctx : Context
    path : str
        Absolute path on this machine.

    Returns
    -------
    str or None
        ``"protected"`` for ``/``, the user's home, the Hypothex home, a
        registered repo or any of their ancestors, any path in the Hypothex
        home outside a run's ``artifacts/`` or ``pulled/``, and any path in
        the Hypothex store below a nested symlinked folder (a ``pulled/``
        that links elsewhere reads as ours but is not); else None. Trusted
        home/store relocation is checked in both literal and resolved forms.
    """
    roots = _roots(ctx)
    homes = _base_forms(ctx.layout.home)
    stores = _base_forms(ctx.layout.store)
    for form in _forms(path):
        if any(root == form or root.is_relative_to(form) for root in roots):
            return "protected"
        matched_stores = [base for base in stores if form.is_relative_to(base)]
        for base in matched_stores:
            parts = form.relative_to(base).parts
            in_run = len(parts) >= 5 and parts[1] == "runs"
            if not (in_run and parts[3] in CLEANABLE_SUBDIRS) or _linked_below(base, form):
                return "protected"
        if not matched_stores and any(form.is_relative_to(base) for base in homes):
            return "protected"
    return None


def _run_folder_bytes(run_dir: Path) -> tuple[int, int, float | None]:
    total, files, newest = 0, 0, None
    try:
        entries = list(os.scandir(run_dir))
    except OSError:
        return 0, 0, None
    for entry in entries:
        if entry.name in CLEANABLE_SUBDIRS:
            continue
        size, count, mtime = measure_path(Path(entry.path))
        total, files = total + size, files + count
        if mtime is not None:
            newest = mtime if newest is None else max(newest, mtime)
    return total, files, newest


def _item(
    ctx: Context, record: RunRecord, kind: StorageKind, path: Path | str, **extra: Any
) -> StorageItem:
    size, files, mtime = measure_path(Path(path))
    return StorageItem(
        project=record.project,
        run_id=record.run_id,
        host=LOCAL_HOST,
        environment_id=ctx.descriptor.environment_id,
        kind=kind,
        artifact_kind=extra.get("artifact_kind"),
        path=str(path),
        bytes=extra.get("bytes", size),
        files=extra.get("files", files),
        mtime=extra.get("mtime", mtime),
        exists=os.path.lexists(path),
        archived=record.archived,
        starred=record.starred,
        status=record.status,
        ended_at=record.ended_at,
    )


def _records(ctx: Context, project: str | None = None) -> list[RunRecord]:
    """Read authoritative run files, including file-first writes absent from the index.

    Unlike the store's best-effort iterator, unreadable known records abort the
    check: an unknown reader or owner cannot safely authorize cleanup.
    """
    return [
        ctx.store.read_record(owner, run_id)
        for run_id, owner in sorted(ctx.store.list_run_ids().items())
        if project is None or owner == project
    ]


def _local_pulled_paths(ctx: Context, record: RunRecord) -> list[Path]:
    """List genuine local copies independently of the source run's environment."""
    pulled = ctx.run_dir(record) / "pulled"
    if not pulled.is_dir() or protected_reason(ctx, str(pulled / "_entry")) is not None:
        return []
    return sorted(pulled.iterdir())


def local_usage(ctx: Context, *, project: str | None = None) -> list[StorageItem]:
    """
    List the bytes of this machine's run folders, artifacts, and pulled files.

    Parameters
    ----------
    ctx : Context
    project : str, optional

    Returns
    -------
    list of StorageItem
        ``host`` is ``local`` (the hub renames rows it gets from hosts).
    """
    own = ctx.descriptor.environment_id
    labels = {"local", ctx.descriptor.label}
    items: list[StorageItem] = []
    for record in _records(ctx, project):
        run_dir = ctx.run_dir(record)
        size, files, mtime = _run_folder_bytes(run_dir)
        items.append(_item(ctx, record, "run", run_dir, bytes=size, files=files, mtime=mtime))
        if record.environment_id == own:
            kinds = {a.path: a.kind for a in record.artifacts if a.host in labels}
            for path, kind in kinds.items():
                items.append(_item(ctx, record, "artifact", path, artifact_kind=kind))
        for entry in _local_pulled_paths(ctx, record):
            items.append(_item(ctx, record, "pulled", entry))
    return items


def _brief(exc: BaseException) -> str:
    return (str(exc).strip() or type(exc).__name__)[:300]


def _remote_usage(
    hosts: HostClients, project: str | None
) -> tuple[list[StorageItem], list[dict[str, str]]]:
    items: list[StorageItem] = []
    errors: list[dict[str, str]] = []
    params = {"project": project} if project else {}
    for name in hosts.names():
        try:
            rows = hosts.client(name).get_json("/api/v1/storage/usage", **params)
            items += [StorageItem.model_validate(r).model_copy(update={"host": name}) for r in rows]
        except (HypothexError, ValueError, ValidationError, TypeError) as exc:
            errors.append({"host": name, "error": _brief(exc)})
    return items, errors


def _sums(items: list[StorageItem], key: str) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for item in items:
        out[getattr(item, key)] += item.bytes
    return dict(sorted(out.items()))


def storage_report(
    ctx: Context,
    hosts: HostClients | None,
    *,
    project: str | None = None,
    remote: bool = True,
) -> StorageReport:
    """
    Report bytes here and, through the hub's host clients, on every host.

    Parameters
    ----------
    ctx : Context
    hosts : HostClients or None
        None on an env server or with no hub.
    project : str, optional
    remote : bool
        Ask the hosts too.

    Returns
    -------
    StorageReport
    """
    items = local_usage(ctx, project=project)
    errors: list[dict[str, str]] = []
    if remote and hosts is not None:
        more, errors = _remote_usage(hosts, project)
        items += more
    return StorageReport(
        items=items,
        by_project=_sums(items, "project"),
        by_host=_sums(items, "host"),
        by_kind=_sums(items, "kind"),
        total_bytes=sum(i.bytes for i in items),
        errors=errors,
        generated_at=utcnow(),
    )


STORAGE_DIR = "storage"
PLANS_DIR = "plans"
PLAN_ID = re.compile(r"^cp-[0-9a-f]{8}$")


def plans_dir(layout: Layout) -> Path:
    """
    Return the folder of stored cleanup plans.

    Parameters
    ----------
    layout : Layout

    Returns
    -------
    Path
        ``<home>/storage/plans``.
    """
    return layout.home / STORAGE_DIR / PLANS_DIR


def eligible(item: StorageItem, cutoff: datetime) -> bool:
    """
    Tell whether an item's run may lose its artifacts.

    Parameters
    ----------
    item : StorageItem
    cutoff : datetime
        ``now - older_than_days``.

    Returns
    -------
    bool
        Archived, unstarred, ended, and ended at or before ``cutoff``.
    """
    return (
        item.archived
        and not item.starred
        and item.status in TERMINAL_STATUSES
        and item.ended_at is not None
        and item.ended_at <= cutoff
    )


def input_paths(record: RunRecord, *, local: bool = False) -> list[str]:
    """List checkpoint inputs, relative to the run's recorded working directory.

    Parameters
    ----------
    record : RunRecord
    local : bool
        Resolve filesystem aliases only on the environment that owns the run.
        Readers follow a final symlink; artifact deletion only unlinks that leaf.

    Returns
    -------
    list of str
        Absolute lexical path and, locally, its resolved input target.
    """
    value = record.vars.get("checkpoint")
    if not isinstance(value, str) or not value:
        return []
    path = Path(value)
    if not path.is_absolute():
        path = Path(record.cwd) / path
    paths = {os.path.normpath(str(path))}
    if local:
        with contextlib.suppress(OSError, RuntimeError):
            paths.add(str(path.resolve()))
    return sorted(paths)


def overlaps(a: str, b: str, *, local: bool = False) -> bool:
    """Compare equal/ancestor paths, resolving parent aliases only on their owner.

    Parameters
    ----------
    a, b : str
        Absolute POSIX paths; reader targets have already passed ``input_paths``.
    local : bool
        Include parent-resolved forms without following the deletion leaf.

    Returns
    -------
    bool
        Whether deleting either path touches the other.
    """
    left = _forms(a) if local else {Path(os.path.normpath(a))}
    right = _forms(b) if local else {Path(os.path.normpath(b))}
    return any(x == y or x in y.parents or y in x.parents for x in left for y in right)


def _settled_by(record: RunRecord, cutoff: datetime) -> bool:
    return (
        record.archived
        and not record.starred
        and record.status in TERMINAL_STATUSES
        and record.ended_at is not None
        and record.ended_at <= cutoff
    )


def _input_readers(
    ctx: Context, hosts: HostClients | None
) -> dict[str, list[tuple[str, RunRecord]]]:
    """Host name (``"*"`` when unknown) -> ``[(input path, run)]`` for runs that read inputs."""
    own = ctx.descriptor.environment_id
    out: dict[str, list[tuple[str, RunRecord]]] = defaultdict(list)
    for record in _records(ctx):
        paths = input_paths(record, local=record.environment_id == own)
        if not paths:
            continue
        if record.environment_id == own:
            host: str | None = LOCAL_HOST
        else:
            host = hosts.host_for_environment(record.environment_id) if hosts else None
        out[host or "*"] += [(path, record) for path in paths]
    return out


def _wanted(item: StorageItem, policy: CleanPolicy) -> bool:
    if item.kind == "run" or not item.exists:
        return False
    if policy.projects is not None and item.project not in policy.projects:
        return False
    if policy.hosts is not None and item.host not in policy.hosts:
        return False
    if item.kind == "pulled":
        return policy.include_pulled
    return "*" in policy.kinds or item.artifact_kind in policy.kinds


def _covers(root: str, path: str) -> bool:
    """True when ``path`` is ``root`` or one of its ancestors (POSIX paths)."""
    root_parts = Path(root).parts
    path_parts = Path(path).parts
    return root_parts[: len(path_parts)] == path_parts


def _remote_protected(ctx: Context, item: StorageItem, items: list[StorageItem]) -> str | None:
    """What the hub can tell about a host path; the host checks everything again."""
    from hypothex.core.errors import ConfigError
    from hypothex.remote.config import load_hosts

    if item.path in ("/", ""):
        return "protected"
    for run in items:
        if run.kind == "run" and run.host == item.host and run.run_id == item.run_id:
            parts = Path(item.path).parts
            base = Path(run.path).parts
            if parts[: len(base)] == base:
                inside = parts[len(base) :]
                if len(inside) < 2 or inside[0] not in CLEANABLE_SUBDIRS:
                    return "protected"
    try:
        spec = load_hosts(ctx.layout).environments.get(item.host)
    except ConfigError:
        spec = None
    roots = [] if spec is None else [*spec.projects.values(), spec.home]
    if any(r.startswith("/") and _covers(r, item.path) for r in roots):
        return "protected"
    return None


def _prune_plans(layout: Layout, now: datetime) -> None:
    folder = plans_dir(layout)
    for path in folder.glob("cp-*.json") if folder.is_dir() else []:
        try:
            if CleanPlan.model_validate_json(path.read_text(encoding="utf-8")).expires_at <= now:
                path.unlink(missing_ok=True)
        except (OSError, ValidationError):
            path.unlink(missing_ok=True)


def plan_clean(
    ctx: Context,
    hosts: HostClients | None,
    policy: CleanPolicy,
    *,
    created_by: str,
    settings: StorageSettings,
    now: datetime | None = None,
) -> CleanPlan:
    """
    Make a dry-run cleanup plan and store it until it is applied or expires.

    Parameters
    ----------
    ctx : Context
    hosts : HostClients or None
        The hub's hosts (their artifacts are planned too).
    policy : CleanPolicy
    created_by : str
        Who asked (``human:<user>``).
    settings : StorageSettings
        ``plan_ttl_minutes``.
    now : datetime, optional

    Returns
    -------
    CleanPlan
        Planned items, refused paths with reasons, and the byte total to confirm.
    """
    moment = now or utcnow()
    _prune_plans(ctx.layout, moment)
    report = storage_report(ctx, hosts)
    cutoff = moment - timedelta(days=policy.older_than_days)
    # host -> every recorded artifact or pulled file there; a folder artifact that holds
    # another run's file (or sits inside one) is "used" as much as the same path is
    users: dict[str, list[StorageItem]] = defaultdict(list)
    for item in report.items:
        if item.kind != "run":
            users[item.host].append(item)
    readers = _input_readers(ctx, hosts)
    items: list[CleanItem] = []
    refused: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in report.items:
        if not _wanted(item, policy) or not eligible(item, cutoff):
            continue
        key = (item.host, item.path)
        blockers = [
            o.run_id
            for o in users[item.host]
            if o.run_id != item.run_id
            and overlaps(o.path, item.path, local=item.host == LOCAL_HOST)
            and not eligible(o, cutoff)
        ]
        blockers += [
            r.run_id
            for path, r in [*readers.get(item.host, []), *readers.get("*", [])]
            if r.run_id != item.run_id
            and overlaps(
                path,
                item.path,
                local=item.host == LOCAL_HOST and r.environment_id == ctx.descriptor.environment_id,
            )
            and not _settled_by(r, cutoff)
        ]
        if blockers:
            reason = f"used by {blockers[0]}"
            refused.append({"path": item.path, "run_id": item.run_id, "reason": reason})
            continue
        if item.host == LOCAL_HOST:
            why = protected_reason(ctx, item.path)
        else:
            why = _remote_protected(ctx, item, report.items)
        if why is not None:
            refused.append({"path": item.path, "run_id": item.run_id, "reason": why})
            continue
        if key in seen:
            continue
        seen.add(key)
        assert item.ended_at is not None
        items.append(
            CleanItem(
                project=item.project,
                run_id=item.run_id,
                host=item.host,
                environment_id=item.environment_id,
                kind="pulled" if item.kind == "pulled" else "artifact",
                artifact_kind=item.artifact_kind,
                path=item.path,
                bytes=item.bytes,
                mtime=item.mtime,
                reason=f"archived {(moment - item.ended_at).days}d",
            )
        )
    # The hub cannot resolve aliases in a host filesystem. Ask each owner to
    # perform the same read-only checks it will repeat under the delete lock.
    remote: dict[str, list[CleanItem]] = defaultdict(list)
    for candidate in items:
        if candidate.host != LOCAL_HOST:
            remote[candidate.host].append(candidate)
    for host, candidates in remote.items():
        try:
            if hosts is None:
                raise HypothexError(f"host {host} is not connected")
            answer = hosts.client(host).post_json(
                "/api/v1/storage/check",
                {
                    "items": [i.model_dump(mode="json") for i in candidates],
                    "older_than_days": policy.older_than_days,
                },
            )
            if not isinstance(answer, list) or any(
                not isinstance(row, dict)
                or not all(isinstance(row.get(k), str) for k in ("path", "run_id", "reason"))
                for row in answer
            ):
                raise ValueError("invalid storage check response")
            blocked = {(row["run_id"], row["path"]): row["reason"] for row in answer}
        except (HypothexError, ValueError, TypeError) as exc:
            blocked = {(i.run_id, i.path): f"host check failed: {_brief(exc)}" for i in candidates}
        for candidate in candidates:
            reason = blocked.get((candidate.run_id, candidate.path))
            if reason is not None:
                items.remove(candidate)
                refused.append(
                    {"path": candidate.path, "run_id": candidate.run_id, "reason": reason}
                )
    result = CleanPlan(
        plan_id=f"cp-{secrets.token_hex(4)}",
        policy=policy,
        items=items,
        refused=refused,
        total_bytes=sum(i.bytes for i in items),
        created_at=moment,
        expires_at=moment + timedelta(minutes=settings.plan_ttl_minutes),
        created_by=created_by,
    )
    path = plans_dir(ctx.layout) / f"{result.plan_id}.json"
    write_private(path, result.model_dump_json(indent=2))
    payload = {"plan_id": result.plan_id, "total_bytes": result.total_bytes, "n_items": len(items)}
    ctx.events.append("storage.plan_created", payload=payload)
    return result


CLEANED_FILE = "cleaned.json"


def cleanup_lock(layout: Layout) -> AbstractContextManager[None]:
    """
    Hold the cleanup lock, ``<home>/storage/.lock`` (exclusive, across processes).

    ``delete_artifacts`` holds it while it checks and deletes. Creating a run
    that reads an input path, starring a run, and archiving or unarchiving one
    take it too, so none of them lands between a check and its deletion.

    Parameters
    ----------
    layout : Layout

    Returns
    -------
    contextlib.AbstractContextManager
        Enter to hold the lock.
    """
    return dir_lock(layout.home / STORAGE_DIR)


def _cleaned_path(ctx: Context, record: RunRecord) -> Path:
    return ctx.run_dir(record) / HX_DIR / CLEANED_FILE


def cleaned_artifacts(ctx: Context, record: RunRecord) -> list[CleanedArtifact]:
    """
    List a run's deleted artifacts (``<run_dir>/.hx/cleaned.json``).

    Parameters
    ----------
    ctx : Context
    record : RunRecord

    Returns
    -------
    list of CleanedArtifact
        Oldest first; ``[]`` when nothing was cleaned or the file is unreadable.
    """
    try:
        raw = json.loads(_cleaned_path(ctx, record).read_text(encoding="utf-8"))
        return [CleanedArtifact.model_validate(r) for r in raw]
    except (OSError, ValueError, TypeError, ValidationError):
        return []


def record_cleaned(
    ctx: Context, run_id: str, items: list[CleanItem], *, actor: str, plan_id: str
) -> None:
    """
    Append deleted items to a run's ``cleaned.json`` and emit ``run.artifacts_cleaned``.

    Parameters
    ----------
    ctx : Context
    run_id : str
    items : list of CleanItem
        Items of this run that were deleted.
    actor : str
    plan_id : str
    """
    record = ctx.find_record(run_id)
    now = utcnow()
    with run_lock(ctx.run_dir(record)):
        done = cleaned_artifacts(ctx, record)
        done += [
            CleanedArtifact(
                path=i.path,
                environment_id=i.environment_id,
                bytes=i.bytes,
                at=now,
                actor=actor,
                plan_id=plan_id,
            )
            for i in items
        ]
        text = json.dumps([d.model_dump(mode="json") for d in done], indent=2)
        atomic_write_text(_cleaned_path(ctx, record), text)
    payload = {
        "paths": [i.path for i in items],
        "freed_bytes": sum(i.bytes for i in items),
        "plan_id": plan_id,
    }
    ctx.emit("run.artifacts_cleaned", record, payload)


def _recheck(
    ctx: Context,
    item: CleanItem,
    users: list[tuple[str, RunRecord]],
    cutoff: datetime,
) -> str | None:
    if item.environment_id != ctx.descriptor.environment_id:
        return "wrong environment"
    try:
        record = ctx.find_record(item.run_id)
    except StoreError:
        return "run not found"
    if item.project != record.project:
        return "wrong project"
    if not record.archived:
        return "not archived"
    if record.starred:
        return "starred"
    if record.status not in TERMINAL_STATUSES:
        return "not ended"
    if record.ended_at is None or record.ended_at > cutoff:
        return "too recent"
    if item.kind == "artifact":
        if record.environment_id != ctx.descriptor.environment_id:
            return "wrong artifact environment"
        kinds = {
            a.kind
            for a in record.artifacts
            if a.path == item.path and a.host in {LOCAL_HOST, ctx.descriptor.label}
        }
        if not kinds:
            return "not an artifact of the run"
        if item.artifact_kind not in kinds:
            return "not an artifact of the run"
    else:
        pulled = ctx.run_dir(record) / "pulled"
        if protected_reason(ctx, str(pulled / "_entry")) is not None:
            return "protected"
        if not any(
            form.is_relative_to(base) for form in _forms(item.path) for base in _base_forms(pulled)
        ):
            return "not in pulled/"
    for path, other in users:  # owners and readers; a folder holding the path counts too
        if (
            other.run_id != record.run_id
            and overlaps(path, item.path, local=True)
            and not _settled_by(other, cutoff)
        ):
            return f"used by {other.run_id}"
    why = protected_reason(ctx, item.path)
    if why is not None:
        return why
    if not os.path.lexists(item.path):
        return "gone"
    size, _, mtime = measure_path(Path(item.path))
    if size != item.bytes or mtime != item.mtime:
        return "changed since plan"
    return None


def _local_users(ctx: Context) -> list[tuple[str, RunRecord]]:
    """Read current owner/input records on this filesystem under cleanup_lock."""
    users: list[tuple[str, RunRecord]] = []
    for record in _records(ctx):
        # Mirrored runs can own local pulled copies. These protect overlapping
        # candidates even when include_pulled=False or their source is remote.
        users.extend((str(path), record) for path in _local_pulled_paths(ctx, record))
        if record.environment_id != ctx.descriptor.environment_id:
            continue  # never interpret a mirrored source artifact/input locally
        users.extend(
            (artifact.path, record)
            for artifact in record.artifacts
            if artifact.host in {LOCAL_HOST, ctx.descriptor.label}
        )
        users.extend((path, record) for path in input_paths(record, local=True))
    return users


def check_artifacts(
    ctx: Context, items: list[CleanItem], *, older_than_days: int
) -> list[dict[str, str]]:
    """Check candidate artifacts on their owning environment without deleting.

    Parameters
    ----------
    ctx : Context
    items : list of CleanItem
    older_than_days : int
        Cleanup policy age cutoff.

    Returns
    -------
    list of dict
        Refused items with path, run_id, host, and reason.
    """
    cutoff = utcnow() - timedelta(days=older_than_days)
    refused: list[dict[str, str]] = []
    with cleanup_lock(ctx.layout):
        try:
            users = _local_users(ctx)
        except (StoreError, OSError):
            return [
                {
                    "path": i.path,
                    "run_id": i.run_id,
                    "host": i.host,
                    "reason": "run metadata unavailable",
                }
                for i in items
            ]
        for item in items:
            why = _recheck(ctx, item, users, cutoff)
            if why is not None:
                refused.append(
                    {"path": item.path, "run_id": item.run_id, "host": item.host, "reason": why}
                )
    return refused


def _open_cleanup_parent(path: str) -> tuple[int, Path]:
    """Pin the resolved parent with no-follow opens for every physical component.

    The caller checks both the literal and physical target against the storage
    policy. Resolving a trusted home/store alias does not authorize its target.
    Every descriptor belongs to this call and is closed on all error paths.
    """
    physical = Path(path).absolute().parent.resolve(strict=True)
    # Pin ancestors for traversal, without demanding directory-list permission.
    # Keep O_RDONLY in _measure_at: directories being measured must be listable.
    access = getattr(os, "O_PATH", getattr(os, "O_SEARCH", os.O_RDONLY))
    flags = access | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(physical.anchor, flags)
    try:
        for part in physical.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd, physical
    except BaseException:
        os.close(fd)
        raise


def _same_node(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare device, inode and type, never a pathname or file contents."""
    return (left.st_dev, left.st_ino, stat.S_IFMT(left.st_mode)) == (
        right.st_dev,
        right.st_ino,
        stat.S_IFMT(right.st_mode),
    )


def _measure_at(parent_fd: int, name: str) -> tuple[int, int, float]:
    """Measure through pinned directory descriptors without following symlinks.

    Unlike the reporting walk, any unreadable or replaced descendant aborts
    destructive apply. Directory allocation is excluded, as in measure_path.
    """
    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        return _allocated(info), 1, info.st_mtime
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        if not _same_node(info, os.fstat(fd)):
            raise OSError("changed since plan")
        size, count, newest = 0, 0, info.st_mtime
        for child in os.listdir(fd):
            added, files, mtime = _measure_at(fd, child)
            size, count, newest = size + added, count + files, max(newest, mtime)
        after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_node(info, after) or (info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise OSError("changed since plan")
        return size, count, newest
    finally:
        os.close(fd)


def _remove(
    ctx: Context, item: CleanItem, users: list[tuple[str, RunRecord]], cutoff: datetime
) -> str | None:
    """Recheck and remove a candidate through a pinned, no-follow parent.

    Never fall back to path-based deletion. The cleanup lock coordinates
    Hypothex writers; these descriptors prevent an unrelated filesystem writer
    from redirecting unlink/rmtree through a replaced parent symlink.
    """
    if (
        not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
        or os.open not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.unlink not in os.supports_dir_fd
        or not getattr(shutil.rmtree, "avoids_symlink_attacks", False)
    ):
        return "safe removal unavailable"
    fd: int | None = None
    try:
        literal = Path(os.path.abspath(item.path))
        fd, physical = _open_cleanup_parent(item.path)
        original = os.stat(literal.name, dir_fd=fd, follow_symlinks=False)
        why = _recheck(ctx, item, users, cutoff)
        if why is not None:
            return why
        # A parent resolved before _recheck may differ from the one it sees.
        # Both spellings must pass; the actual removal uses only this fd/name.
        if protected_reason(ctx, str(physical / literal.name)) is not None:
            return "protected"
        live_fd, _ = _open_cleanup_parent(item.path)
        try:
            if not _same_node(os.fstat(fd), os.fstat(live_fd)):
                return "changed since plan"
        finally:
            os.close(live_fd)
        current = os.stat(literal.name, dir_fd=fd, follow_symlinks=False)
        if not _same_node(original, current):
            return "changed since plan"
        size, _, mtime = _measure_at(fd, literal.name)
        if size != item.bytes or mtime != item.mtime:
            return "changed since plan"
        # Measurement can take seconds. Verify the leaf again after walking,
        # even when a replacement copied the exact size and timestamps.
        live_fd, _ = _open_cleanup_parent(item.path)
        try:
            if not _same_node(os.fstat(fd), os.fstat(live_fd)):
                return "changed since plan"
        finally:
            os.close(live_fd)
        if protected_reason(ctx, item.path) is not None:
            return "protected"
        final = os.stat(literal.name, dir_fd=fd, follow_symlinks=False)
        if not _same_node(original, final) or (original.st_mtime_ns, original.st_ctime_ns) != (
            final.st_mtime_ns,
            final.st_ctime_ns,
        ):
            return "changed since plan"
        if stat.S_ISDIR(final.st_mode):
            shutil.rmtree(literal.name, dir_fd=fd)
        else:
            os.unlink(literal.name, dir_fd=fd)
    except (OSError, RuntimeError):
        return "changed or inaccessible since plan"
    finally:
        if fd is not None:
            os.close(fd)
    return None


def delete_artifacts(
    ctx: Context, items: list[CleanItem], *, actor: str, plan_id: str, older_than_days: int
) -> CleanResult:
    """
    Delete planned items on this machine, checking each one again first.

    Parameters
    ----------
    ctx : Context
    items : list of CleanItem
        Items whose files live here.
    actor : str
        Who applied the plan.
    plan_id : str
    older_than_days : int
        The plan's policy: the item's run, and every other run that records
        or reads its path, counts as settled only when it ended at or before
        ``now - older_than_days``.

    Returns
    -------
    CleanResult
        Deleted items, ``skipped`` entries ``{path, run_id, host, reason}``,
        and the freed bytes.
    """
    cutoff = utcnow() - timedelta(days=older_than_days)
    deleted: list[CleanItem] = []
    skipped: list[dict[str, Any]] = []
    with cleanup_lock(ctx.layout):
        # read under the lock: a run created, starred, or unarchived later waits for us
        # (path, run) for every artifact a run records and every input it reads
        metadata_error = None
        try:
            users = _local_users(ctx)
        except (StoreError, OSError):
            users = []
            metadata_error = "run metadata unavailable"
        for item in items:
            why = metadata_error or _remove(ctx, item, users, cutoff)
            if why is not None:
                skipped.append(
                    {"path": item.path, "run_id": item.run_id, "host": item.host, "reason": why}
                )
            else:
                deleted.append(item)
        by_run: dict[str, list[CleanItem]] = defaultdict(list)
        for item in deleted:
            by_run[item.run_id].append(item)
        for run_id, done in by_run.items():
            record_cleaned(ctx, run_id, done, actor=actor, plan_id=plan_id)
    return CleanResult(
        plan_id=plan_id,
        deleted=deleted,
        skipped=skipped,
        freed_bytes=sum(i.bytes for i in deleted),
        errors=[],
    )


def apply_clean(
    ctx: Context,
    hosts: HostClients | None,
    plan_id: str,
    *,
    confirm_bytes: int,
    actor: str,
    now: datetime | None = None,
) -> CleanResult:
    """
    Apply a stored plan: delete here and on each host, once.

    Parameters
    ----------
    ctx : Context
    hosts : HostClients or None
    plan_id : str
    confirm_bytes : int
        Must equal the plan's ``total_bytes`` (the number the user typed back).
    actor : str
    now : datetime, optional

    Returns
    -------
    CleanResult

    Raises
    ------
    CleanRefusedError
        Unknown or expired plan, or a wrong ``confirm_bytes``; nothing is deleted.
    """
    unknown = CleanRefusedError(
        f"unknown plan {plan_id!r}; make one with hx storage clean --archived"
    )
    if not PLAN_ID.match(plan_id):
        raise unknown
    path = plans_dir(ctx.layout) / f"{plan_id}.json"
    try:
        plan = CleanPlan.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        raise unknown from None
    if plan.expires_at <= (now or utcnow()):
        path.unlink(missing_ok=True)
        raise CleanRefusedError(f"plan {plan_id} expired; make a new one")
    if confirm_bytes != plan.total_bytes:
        raise CleanRefusedError(
            f"confirm_bytes {confirm_bytes} does not match the plan's {plan.total_bytes}"
        )
    try:
        path.unlink()  # one use, before anything is deleted
    except FileNotFoundError:
        raise unknown from None  # a concurrent apply of the same plan won the race
    local = [i for i in plan.items if i.host == LOCAL_HOST]
    days = plan.policy.older_than_days  # the plan's age rule holds at delete, here and on hosts
    result = delete_artifacts(ctx, local, actor=actor, plan_id=plan_id, older_than_days=days)
    deleted, skipped, errors = list(result.deleted), list(result.skipped), list(result.errors)
    remote: dict[str, list[CleanItem]] = defaultdict(list)
    for item in plan.items:
        if item.host != LOCAL_HOST:
            remote[item.host].append(item)
    for host, items in remote.items():
        try:
            if hosts is None:
                raise HypothexError(f"host {host} is not connected")
            body = {
                "items": [i.model_dump(mode="json") for i in items],
                "plan_id": plan_id,
                "actor": actor,
                "older_than_days": days,
                "command_id": f"{plan_id}:{host}",
            }
            answer = CleanResult.model_validate(
                hosts.client(host).post_json("/api/v1/storage/delete", body)
            )
        except (HypothexError, ValueError, ValidationError, TypeError) as exc:
            errors.append({"host": host, "error": _brief(exc)})
            continue
        done = [i.model_copy(update={"host": host}) for i in answer.deleted]
        mirrored: dict[str, list[CleanItem]] = defaultdict(list)
        for item in done:
            mirrored[item.run_id].append(item)
        for run_id, run_items in mirrored.items():
            try:
                record_cleaned(ctx, run_id, run_items, actor=actor, plan_id=plan_id)
            except StoreError:
                continue  # the hub has no copy of that run
        deleted += done
        skipped += answer.skipped
        errors += answer.errors
    freed = sum(i.bytes for i in deleted)
    ctx.events.append(
        "storage.cleaned",
        payload={
            "plan_id": plan_id,
            "freed_bytes": freed,
            "n_deleted": len(deleted),
            "n_skipped": len(skipped),
        },
    )
    return CleanResult(
        plan_id=plan_id, deleted=deleted, skipped=skipped, freed_bytes=freed, errors=errors
    )


def fmt_bytes(n: int | float) -> str:
    """Format a byte count tersely in base 1000.

    Parameters
    ----------
    n : int or float
        Allocated byte count.

    Returns
    -------
    str
        Bytes or a decimal KB/MB/GB/TB value.

    Examples
    --------
    >>> fmt_bytes(412_300_000_000)
    '412.3 GB'
    """
    value = float(n)
    if abs(value) < 1000:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1000
        if abs(value) < 1000 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"
