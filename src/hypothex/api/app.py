"""HTTP + WebSocket API. The UI and remote clients use only this."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import logging
import os
import re
import stat
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

import httpx
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.types import Scope

from hypothex._version import __version__
from hypothex.api.security import OriginGuard, TokenGuard, allowed_hosts, bearer_matches
from hypothex.core import control
from hypothex.core import queries as q
from hypothex.core.config import load_project_config, parse_metric_version
from hypothex.core.context import Context
from hypothex.core.cost import cost_since, today_start
from hypothex.core.errors import ConfigError, HypothexError, RunError, StoreError
from hypothex.core.evaluation import EvalReport, reeval
from hypothex.core.events import CommandInterruptedError
from hypothex.core.execution import RunRequest
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.gitinfo import DIFF_LIMIT_BYTES, capture_diff, head_commit
from hypothex.core.gpus import GpuInfo, gpu_status, query_gpus
from hypothex.core.ids import utcnow
from hypothex.core.index import RunRow
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.layout import reserved_run_path
from hypothex.core.overview import build_overview
from hypothex.core.panels import query_panel
from hypothex.core.records import Artifact, RunRecord, RunStatus
from hypothex.core.scheduler import Scheduler, run_scheduler_loop
from hypothex.core.slurm import SlurmPoller, comment_accounting, require_flock
from hypothex.core.sweeps import (
    Launcher,
    SweepParam,
    SweepSpec,
    SweepSummary,
    cancel_queued,
    extend_sweep,
    launch_sweep,
    list_sweeps,
    mark_sweep,
    parse_sweep_tag,
    stop_if_queued,
    summarize_sweep,
)
from hypothex.core.views import PanelData, PanelSpec, ViewSpec
from hypothex.mcp.server import (
    LOCAL_HOST,
    ViewValidationError,
    build_server,
    find_sweep,
    is_remote,
    list_task_views,
    put_view,
    query_task_view,
    remove_view,
    require_agent_hypothesis,
    ssh_target,
    validate_view,
    view_document,
)
from hypothex.remote.client import (
    DIR_HEADER,
    SIZE_HEADER,
    EnvClient,
    EnvRequestError,
    EnvUnreachableError,
)
from hypothex.remote.config import EnvironmentsFile, HostSpec, SlurmDefaults, load_hosts
from hypothex.remote.hub import HostState, HostUnavailableError, Hub
from hypothex.remote.ssh import SshError, copy_from

log = logging.getLogger(__name__)

REPAIR_INTERVAL_SECONDS = 30.0
SCHEDULER_INTERVAL_SECONDS = 5.0
ENV_KINDS = ("local", "ssh", "slurm")
COST_WINDOW_DAYS = 7
MIRROR_WAIT_SECONDS = 10.0
REEVAL_FORWARD_SECONDS = 600.0
"""Read timeout of a reeval sent to a host: scoring can outlast the client's 10 s, and a
timeout counts the host as unreachable (a task reeval then skips its other runs)."""
PULL_MAX_BYTES = 64 * 1024**3
PULL_REMOTE_PATH = re.compile(r"^/[A-Za-z0-9_.+@/=-]+$")
"""An absolute host path that ``pull`` may hand to ``scp``: shell-safe characters only."""
PULL_RESERVED_PREFIX = ".hx-"
"""``pull`` refuses a destination whose name starts with this (contract: 400)."""
PULL_WORK_DIR = "pulls"
"""``<hub home>/pulls``: ``copy_from``'s staging, transaction records, and backups (Task 6)."""
WS_POLL_SECONDS = 0.5
WS_BATCH = 500
UI_DIST = Path(__file__).resolve().parent.parent / "ui_dist"
NO_UI_FALLBACK = frozenset({"api", "mcp", ".well-known", "assets"})
FILE_MAX_BYTES = 200 * 1024 * 1024
FILE_CHUNK_BYTES = 64 * 1024
GPU_CACHE_SECONDS = 10.0
PUBLIC_DESCRIPTOR_FIELDS = ("environment_id", "protocol_version", "hx_version")
"""What the descriptor tells a client without the bearer token (``start.sh`` needs the id)."""
GZIP_MIN_BYTES = 2048
"""Responses at least this big are gzipped for clients that accept it (JSON compresses ~8x)."""
GZIP_LEVEL = 6
GZIP_SKIP_TYPES = (*DEFAULT_EXCLUDED_CONTENT_TYPES, "application/octet-stream")
"""Run files (``application/octet-stream``, up to ``FILE_MAX_BYTES``) are sent as they are."""
_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class SpaStaticFiles(StaticFiles):
    """
    Serve the built UI; unknown client-side routes get ``index.html``.

    The UI routes (``/t/...``, ``/r/...``, ``/x/...``) exist only in the browser, so a
    reload must still load the app. Paths under ``api``, ``mcp``, ``.well-known``, and
    ``assets`` keep their 404, so a missing API route stays a JSON error and a missing
    script is not answered with HTML.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        """
        Return the file at ``path``, or ``index.html`` for unknown UI routes.

        Parameters
        ----------
        path : str
            Path relative to the UI folder.
        scope : Scope
            ASGI scope.

        Returns
        -------
        Response
        """
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            parts = Path(path).parts
            if exc.status_code != 404 or (parts and parts[0] in NO_UI_FALLBACK):
                raise
            return await super().get_response("index.html", scope)


class ActionBody(BaseModel):
    """Common fields of every POST body."""

    command_id: str | None = None
    created_by: str = "api"


class RunFields(ActionBody):
    """Fields of a launch, shared by env servers and the hub's host launches."""

    task: str | None = None
    stage: str | None = None
    command: list[str] | None = None
    hypothesis: str = ""
    seed: int | None = None
    tags: list[str] = Field(default_factory=list)
    params: dict[str, str] = Field(default_factory=dict)
    vars: dict[str, str] = Field(default_factory=dict)
    gpus: int = Field(0, ge=0)
    queue: bool = False
    slurm: SlurmDefaults | None = None
    commit: str | None = None
    diff: str | None = None
    sweep_id: str | None = None


class LaunchBody(RunFields):
    """Body of ``POST /api/v1/runs``: start a run in this environment."""

    repo: str


class StopBody(ActionBody):
    """Body of ``POST /api/v1/runs/{id}/stop``; ``only_queued`` leaves started runs alone."""

    only_queued: bool = False


class HostLaunchBody(RunFields):
    """
    Body of ``POST /api/v1/hosts/{host}/runs``.

    ``project`` names the project (what the UI, CLI, and MCP send). ``repo`` is
    used only when it is a folder on the hub: a client-local path from another
    machine is ignored. The host runs in its own mapped checkout (``hx hosts map``).
    """

    repo: str | None = None
    project: str | None = None


class SweepBody(ActionBody):
    """
    Body of ``POST /api/v1/sweeps``.

    ``commit`` and ``diff`` are optional: ``hx sweep --host`` sends the client
    checkout's commit and diff, so a hub without that checkout runs the client's code.
    """

    project: str
    task: str | None = None
    host: str | None = None
    grid: list[SweepParam]
    random: int | None = Field(None, ge=1)
    seeds: list[int] = Field(min_length=1)
    command: list[str] = Field(min_length=1)
    hypothesis: str
    gpus: int = Field(0, ge=0)
    queue: bool = False
    commit: str | None = None
    diff: str | None = None


class SeedsBody(ActionBody):
    """Body of ``POST /api/v1/sweeps/{project}/{id}/extend``."""

    seeds: list[int] = Field(min_length=1)


class PullBody(ActionBody):
    """Body of ``POST /api/v1/runs/{id}/pull``: an artifact kind or a path."""

    artifact: str = "checkpoint"


class SubscribeMessage(BaseModel):
    """
    The first WebSocket message: ``{type: subscribe, after_sequence, max_replay?}``.

    ``after_sequence`` is the last sequence the client has (``0`` replays the whole
    log) or ``"latest"``: no replay, live events from now on (a page that has just
    loaded its data). ``max_replay`` caps the replay: when more than that many
    events are missing, the server sends ``{type: reset, last_sequence}`` instead
    of them, and the client reloads its data. Without it every missing event is
    replayed, which the hub's mirror needs.
    """

    type: Literal["subscribe"]
    after_sequence: Annotated[int, Field(ge=0)] | Literal["latest"] = 0
    max_replay: int | None = Field(default=None, ge=1)


class ReinferBody(ActionBody):
    """Body of ``POST /api/v1/runs/{id}/reinfer``."""

    checkpoint: str | None = None


class ReevalBody(ActionBody):
    """Body of a ``reeval`` action."""

    metric: str | None = None
    force: bool = False


class TagBody(ActionBody):
    """Body of ``POST /api/v1/runs/{id}/tags``."""

    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


class FlagBody(ActionBody):
    """Body of ``star``/``archive`` actions."""

    on: bool = True


class NoteBody(ActionBody):
    """Body of ``POST /api/v1/runs/{id}/notes``."""

    text: str
    author: str = "api"


class ViewTextBody(BaseModel):
    """Body of ``POST /api/v1/tasks/{project}/{task}/views/validate``."""

    text: str


class ViewPutBody(ActionBody):
    """Body of ``PUT /api/v1/tasks/{project}/{task}/views/{name}``."""

    text: str


class ViewQueryBody(BaseModel):
    """Body of ``POST .../views/query``: one panel, an unsaved view, or a saved view's name."""

    view: ViewSpec | None = None
    name: str | None = None
    panel: PanelSpec | None = None


async def client_left(ws: WebSocket, seconds: float) -> bool:
    """
    Wait up to ``seconds`` for a client message; tell whether the client disconnected.

    The event stream polls the log while idle. Waiting on ``receive`` instead of
    sleeping lets it notice a closed subscription at once, so a hub that reconnects
    never leaves a polling task behind, and server shutdown is not held up.

    Parameters
    ----------
    ws : WebSocket
        Accepted WebSocket.
    seconds : float
        Longest wait.

    Returns
    -------
    bool
        ``True`` when the client disconnected; ``False`` on timeout or any other message.
    """
    try:
        message = await asyncio.wait_for(ws.receive(), seconds)
    except TimeoutError:
        return False
    return message["type"] == "websocket.disconnect"


def validation_detail(problems: Sequence[Any]) -> list[dict[str, Any]]:
    """
    Turn FastAPI's validation problems into JSON-safe dicts for a ``422`` body.

    ``input`` is left out: for a body that is not JSON it is the raw bytes, and
    it echoes whatever the client sent. ``ctx`` values that are not plain JSON
    scalars (such as the ``ValueError`` a model validator raised) become text.

    Parameters
    ----------
    problems : sequence of dict
        ``RequestValidationError.errors()``.

    Returns
    -------
    list of dict
        Each problem's ``type``, ``loc``, ``msg`` and ``ctx`` (and any other key
        but ``input``).

    Examples
    --------
    >>> validation_detail([{"type": "dict_type", "loc": ("body",), "msg": "bad", "input": b"{}"}])
    [{'type': 'dict_type', 'loc': ['body'], 'msg': 'bad'}]
    >>> validation_detail([{"type": "value_error", "loc": ("body", "grid"), "msg": "bad",
    ...                     "ctx": {"error": ValueError("bad")}}])[0]["ctx"]
    {'error': 'bad'}
    """
    out: list[dict[str, Any]] = []
    for problem in problems:
        item = {k: v for k, v in problem.items() if k != "input"}
        if isinstance(item.get("ctx"), dict):
            item["ctx"] = {
                k: v if v is None or isinstance(v, str | int | float | bool) else str(v)
                for k, v in item["ctx"].items()
            }
        out.append(to_jsonable(item))
    return out


async def _repair_loop(ctx: Context) -> None:
    """Mark orphaned runs lost every ``REPAIR_INTERVAL_SECONDS``."""
    while True:
        await asyncio.sleep(REPAIR_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(control.repair_runs, ctx)
        except Exception:  # noqa: BLE001 - keep the server alive
            log.exception("run repair failed")


def run_request(body: RunFields, repo: str) -> RunRequest:
    """
    Turn a launch body into a ``RunRequest`` for ``repo``.

    Parameters
    ----------
    body : RunFields
        Launch fields.
    repo : str
        Project checkout on this machine.

    Returns
    -------
    RunRequest

    Raises
    ------
    RunError
        If an agent (``created_by: agent:*``) gives no hypothesis.
    """
    require_agent_hypothesis(body.created_by, body.hypothesis)
    return RunRequest(
        repo=Path(repo),
        command=body.command,
        stage=body.stage,
        task=body.task,
        hypothesis=body.hypothesis,
        seed=body.seed,
        tags=body.tags,
        params=body.params,
        vars=body.vars,
        created_by=body.created_by,
        gpus=body.gpus,
        queue=body.queue,
        slurm=body.slurm,
        commit=body.commit,
        diff=body.diff,
    )


def launch_here(ctx: Context, body: RunFields, repo: str) -> RunRecord:
    """
    Launch a run in this environment and record its sweep.

    Parameters
    ----------
    ctx : Context
        Context of this environment.
    body : RunFields
        Launch fields; ``sweep_id`` marks the new run as a sweep member.
    repo : str
        Project checkout on this machine.

    Returns
    -------
    RunRecord
        The launched run (with ``sweep_id`` set when given).
    """
    record = control.launch_run(ctx, run_request(body, repo))
    if body.sweep_id is not None:
        record = mark_sweep(ctx, record.run_id, body.sweep_id)
    return record


def _unknown_host(name: str) -> ConfigError:
    return ConfigError(f"unknown host {name!r}; add it with `hx hosts add {name} --ssh <alias>`")


DISABLED_HOSTS_FILE = "hosts_disabled.json"
"""``<home>/hosts_disabled.json``: hosts the user disconnected, kept across hub restarts."""


def _load_disabled(ctx: Context) -> dict[str, datetime]:
    try:
        raw = json.loads((ctx.layout.home / DISABLED_HOSTS_FILE).read_text(encoding="utf-8"))
        return {str(k): datetime.fromisoformat(v) for k, v in raw.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def _save_disabled(ctx: Context, disabled: dict[str, datetime]) -> None:
    data = {k: v.isoformat() for k, v in sorted(disabled.items())}
    atomic_write_text(ctx.layout.home / DISABLED_HOSTS_FILE, json.dumps(data, indent=2))


class HubManager:
    """
    The hub's connections to its hosts.

    Owns one contract ``Hub`` for the life of the server. Connecting,
    disconnecting, adding, or removing a host changes only that host's
    supervisor (``Hub.add_host`` / ``remove_host`` / ``connect``); every other
    host keeps its session and tunnel, and no ``ensure_server`` runs again on
    them. Env servers and their runs keep going in every case, because the hub
    stops only supervisors and tunnels. Disconnected hosts are saved in
    ``<home>/hosts_disabled.json``, so a hub restart keeps them disconnected. A
    malformed ``environments.yaml`` never stops the server: the error is
    logged, the hosts known before stay listed in state ``error``, and the
    ``local`` row carries the message. Entries with ``route: local`` are the
    hub itself.

    Parameters
    ----------
    ctx : Context
        The hub's context.
    """

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.hosts = EnvironmentsFile()
        self.error: str | None = None
        self.hub: Hub | None = None
        self.disabled: dict[str, datetime] = _load_disabled(ctx)
        self.started_at = utcnow()
        self._seen: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._read_file()

    def _read_file(self) -> bool:
        """Load ``environments.yaml``; on a bad file keep the last good hosts and report it."""
        try:
            self.hosts = load_hosts(self.ctx.layout)
        except ConfigError as exc:
            log.error("hub: %s", exc)
            self.error = str(exc)
            return False
        self.error = None
        return True

    def names(self) -> list[str]:
        """
        Return the remote host names, in file order.

        Returns
        -------
        list of str
        """
        return [n for n, s in self.hosts.environments.items() if s.route != "local"]

    def spec(self, name: str) -> HostSpec:
        """
        Return a host's entry.

        Parameters
        ----------
        name : str

        Returns
        -------
        HostSpec

        Raises
        ------
        ConfigError
            If no remote host has this name.
        """
        spec = self.hosts.environments.get(name)
        if spec is None or spec.route == "local":
            raise _unknown_host(name)
        return spec

    def _enabled(self) -> dict[str, HostSpec]:
        return {
            n: s
            for n, s in self.hosts.environments.items()
            if s.route != "local" and n not in self.disabled
        }

    async def start(self) -> None:
        """Start the ``Hub`` and connect every enabled host in ``environments.yaml``."""
        async with self._lock:
            if self.hub is None:
                self._read_file()  # fresh: `hx demo` rewrites URLs before the server starts
                self.hub = Hub(
                    self.ctx,
                    EnvironmentsFile(environments=self._enabled()),
                    configured_hosts=self.names,
                )
                await self.hub.start()

    async def stop(self) -> None:
        """Stop every supervisor and tunnel (env servers keep running)."""
        async with self._lock:
            if self.hub is not None:
                await self.hub.stop()
                self.hub = None

    async def reload(self) -> None:
        """
        Re-read ``environments.yaml`` and apply only the hosts that changed.

        New or changed enabled hosts are added (``Hub.add_host`` restarts only a
        host whose entry changed); removed or disabled hosts are stopped. A bad
        file changes nothing.
        """
        async with self._lock:
            await self._apply_file()

    async def _apply_file(self) -> None:
        if not self._read_file():
            return
        stale = [n for n in self.disabled if n not in self.names()]
        if stale:
            for name in stale:
                self.disabled.pop(name)
            _save_disabled(self.ctx, self.disabled)
        if self.hub is None:
            return
        wanted = self._enabled()
        for name in [n for n in self.hub.hosts.environments if n not in wanted]:
            await self.hub.remove_host(name)
        for name, spec in wanted.items():
            await self.hub.add_host(name, spec)

    def _check_file(self, name: str) -> None:
        if self.error is not None:
            raise ConfigError(self.error)
        spec = self.hosts.environments.get(name)
        if spec is None or spec.route == "local":
            raise _unknown_host(name)

    async def connect(self, name: str) -> HostState:
        """
        (Re)connect one host; also picks up hosts added to the file since start.

        Parameters
        ----------
        name : str

        Returns
        -------
        HostState
            The state right after reconnecting (usually ``connecting``).
        """
        async with self._lock:
            self._read_file()
            self._check_file(name)
            if self.disabled.pop(name, None) is not None:
                _save_disabled(self.ctx, self.disabled)
            running = self.hub is not None and name in self.hub.hosts.environments
            await self._apply_file()  # starts a new or re-enabled host
            if running and self.hub is not None:
                await self.hub.connect(name)  # fresh backoff for this host only
        return self.state(name)

    async def disconnect(self, name: str) -> HostState:
        """
        Stop watching one host until ``connect``; its runs keep going on the host.

        The choice is saved, so a hub restart keeps the host disconnected.

        Parameters
        ----------
        name : str

        Returns
        -------
        HostState
            State ``disabled``.
        """
        async with self._lock:
            self._check_file(name)
            self.disabled.setdefault(name, utcnow())
            _save_disabled(self.ctx, self.disabled)
            if self.hub is not None:
                await self.hub.remove_host(name)
        return self.state(name)

    def state(self, name: str) -> HostState:
        """
        Return a host's connection state.

        Parameters
        ----------
        name : str

        Returns
        -------
        HostState
        """
        spec = self.spec(name)
        if self.error is not None:
            return HostState(
                name=name, kind=spec.kind, state="error", since=self.started_at, message=self.error
            )
        if name in self.disabled:
            return HostState(
                name=name,
                kind=spec.kind,
                state="disabled",
                since=self.disabled[name],
                message="disconnected; `hx hosts connect` reconnects",
            )
        if self.hub is None:
            return HostState(
                name=name,
                kind=spec.kind,
                state="disabled",
                since=self.started_at,
                message="hub not started",
            )
        try:
            state = self.hub.state(name)
        except HostUnavailableError:  # in the file, not applied yet: `hx hosts connect`
            return HostState(
                name=name,
                kind=spec.kind,
                state="disabled",
                since=self.started_at,
                message=f"not connected; `hx hosts connect {name}`",
            )
        if state.environment_id:
            self._seen[state.environment_id] = name
        return state

    def states(self) -> list[HostState]:
        """
        Return every remote host's state, in file order.

        Returns
        -------
        list of HostState
        """
        return [self.state(n) for n in self.names()]

    def client(self, name: str) -> EnvClient:
        """
        Return the client of a connected host.

        Parameters
        ----------
        name : str

        Returns
        -------
        EnvClient

        Raises
        ------
        HostUnavailableError
            If the host is disconnected or not connected now.
        """
        if name in self.disabled:
            raise HostUnavailableError(
                f"host {name} is disconnected; connect it with `hx hosts connect {name}`"
            )
        if self.hub is None or name not in self.hub.hosts.environments:
            raise HostUnavailableError(
                f"host {name} is not connected; connect it with `hx hosts connect {name}`"
            )
        return self.hub.client(name)

    def host_for_environment(self, environment_id: str) -> str | None:
        """
        Return the host that serves an environment.

        Looks at the live states, then at environment ids seen earlier in this
        process, then at the hub's persisted cursors (``host_cursors``).

        Parameters
        ----------
        environment_id : str

        Returns
        -------
        str or None
            The host name; None for this hub's own runs and for environments no
            configured host serves (they are handled locally, as in phase 1).
        """
        if environment_id == self.ctx.descriptor.environment_id:
            return None
        if self.hub is not None:
            for name in self.names():
                if name not in self.disabled:
                    self.state(name)
        configured = self.names()
        seen = self._seen.get(environment_id)
        name = seen if seen in configured else self._cursor_host(environment_id)
        return name if name in configured else None

    def mirrored_from(self, environment_id: str) -> str | None:
        """
        Return the host this hub mirrored an environment's runs from, configured or not.

        Unlike :meth:`host_for_environment`, a host since removed from
        ``environments.yaml`` still counts: its mirror cursor stays, and the
        host's copy of each run replaces the hub's whenever it is mirrored again.

        Parameters
        ----------
        environment_id : str

        Returns
        -------
        str or None
            The host name; None for this hub's own runs and for environments
            never mirrored here (such as demo or imported runs).

        Examples
        --------
        >>> manager.mirrored_from("env-of-a-removed-host")  # doctest: +SKIP
        'gpu-old'
        """
        if environment_id == self.ctx.descriptor.environment_id:
            return None
        return (
            self.host_for_environment(environment_id)
            or self._seen.get(environment_id)
            or self._cursor_host(environment_id)
        )

    def environment_ids(self, state: HostState) -> list[str]:
        """
        Return every environment id a host is known to have served.

        The live id first, then ids seen earlier in this process, then the hub's
        persisted cursors (``host_cursors``). A disconnected host has no live id,
        but its mirrored runs stay in the index and still count in its totals.

        Parameters
        ----------
        state : HostState
            The host's current state.

        Returns
        -------
        list of str
            Distinct ids, the live one first; empty when none is known.
        """
        ids = [state.environment_id] if state.environment_id else []
        ids += [eid for eid, host in self._seen.items() if host == state.name]
        try:
            with self.ctx.index.engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT environment_id FROM host_cursors WHERE host = :h"),
                    {"h": state.name},
                ).all()
        except OperationalError:
            rows = []
        ids += [str(row[0]) for row in rows]
        return list(dict.fromkeys(ids))

    def _cursor_host(self, environment_id: str) -> str | None:
        try:
            hosts = self.ctx.index.cursor_hosts(environment_id)
        except OperationalError:
            return None
        configured = self.names()
        # Prefer the active alias, but retain a removed owner for mirrored_from:
        # curation must still refuse a host's mirror when no alias is configured.
        return next((name for name in hosts if name in configured), next(iter(hosts), None))


def environment_runs(ctx: Context, environment_id: str) -> list[RunRecord]:
    """
    Return one environment's runs that are active or were created or ended recently.

    Parameters
    ----------
    ctx : Context
    environment_id : str

    Returns
    -------
    list of RunRecord
        Queued/running runs plus runs created or ended in the last
        ``COST_WINDOW_DAYS`` days (a long run that ended today counts in today's
        cost, however long ago it started).
    """
    floor = (utcnow() - timedelta(days=COST_WINDOW_DAYS)).isoformat()
    active = [RunStatus.QUEUED.value, RunStatus.RUNNING.value]
    ended = func.json_extract(RunRow.record_json, "$.ended_at")
    stmt = select(RunRow.record_json).where(
        RunRow.environment_id == environment_id,
        or_(RunRow.status.in_(active), RunRow.created_at >= floor, ended >= floor),
    )
    with Session(ctx.index.engine) as session:
        return [RunRecord.model_validate_json(j) for j in session.scalars(stmt)]


def host_rows(
    ctx: Context, manager: HubManager, gpu_cache: GpuCache | None = None
) -> list[dict[str, Any]]:
    """
    Build ``GET /api/v1/hosts``: the hub first (``local``), then each host.

    GPUs and queue length come from a connected host's env server; SLURM counts
    and today's cost come from the runs the hub has mirrored.

    Parameters
    ----------
    ctx : Context
    manager : HubManager
    gpu_cache : GpuCache, optional
        The env routes' cache (``app.state.gpu_cache``); the hub's own GPUs are
        read through it, so ``nvidia-smi`` runs at most every 10 s.

    Returns
    -------
    list of dict
        ``{name, kind, state, gpus, queue, slurm, cost_today_usd, usd_per_gpu_hour,
        projects, stale_banner_hours}``.
    """
    since = today_start()
    eid = ctx.descriptor.environment_id
    local_runs = environment_runs(ctx, eid)
    local_state = HostState(
        name=LOCAL_HOST,
        kind="local",
        state="connected",
        since=manager.started_at,
        message="" if manager.error is None else manager.error,
        environment_id=eid,
        hx_version=__version__,
        last_sequence=ctx.events.last_sequence(),
    )
    local_rate = next(
        (s.usd_per_gpu_hour for s in manager.hosts.environments.values() if s.route == "local"),
        None,
    )
    seen_gpus = gpu_cache.get() if gpu_cache is not None else None
    rows: list[dict[str, Any]] = [
        {
            "name": LOCAL_HOST,
            "kind": "local",
            "state": local_state.model_dump(mode="json"),
            "gpus": [g.model_dump(mode="json") for g in gpu_status(ctx, seen_gpus)],
            "queue": sum(1 for r in local_runs if r.status == RunStatus.QUEUED),
            "slurm": None,
            "cost_today_usd": cost_since(local_runs, since),
            "usd_per_gpu_hour": local_rate,
            "projects": sorted(e.project for e in ctx.index.list_projects()),
            "stale_banner_hours": manager.hosts.stale_banner_hours,
        }
    ]
    for state in manager.states():
        spec = manager.spec(state.name)
        gpus: list[Any] = []
        queue = 0
        if state.state == "connected":
            with contextlib.suppress(HypothexError, httpx.HTTPError):
                client = manager.client(state.name)
                gpus = client.get_json("/api/v1/gpus")
                queue = len(client.get_json("/api/v1/queue"))
        # every env id the host served: a disconnected host keeps its totals
        runs = [r for eid in manager.environment_ids(state) for r in environment_runs(ctx, eid)]
        slurm = None
        if spec.kind == "slurm":
            accounting = None  # unknown until the host answers
            if state.state == "connected":
                with contextlib.suppress(HypothexError, httpx.HTTPError, AttributeError):
                    accounting = (
                        manager.client(state.name)
                        .get_json("/api/v1/slurm")
                        .get("comment_accounting")
                    )
            slurm = {
                "pending": sum(1 for r in runs if r.status == RunStatus.QUEUED),
                "running": sum(1 for r in runs if r.status == RunStatus.RUNNING),
                "comment_accounting": accounting,
            }
        rows.append(
            {
                "name": state.name,
                "kind": spec.kind,
                "state": state.model_dump(mode="json"),
                "gpus": gpus,
                "queue": queue,
                "slurm": slurm,
                "cost_today_usd": cost_since(runs, since),
                "usd_per_gpu_hour": spec.usd_per_gpu_hour,
                "projects": sorted(spec.projects),
                "stale_banner_hours": manager.hosts.stale_banner_hours,
            }
        )
    return rows


def _hub_checkout(body: HostLaunchBody) -> str | None:
    """The body's repo only when it is a folder on the hub (a client may send its own path)."""
    return body.repo if body.repo is not None and Path(body.repo).is_dir() else None


def _project_of(body: HostLaunchBody) -> str:
    if body.project:
        return body.project
    checkout = _hub_checkout(body)
    if checkout is not None:
        return load_project_config(Path(checkout)).project
    raise RunError("give the project by name (the hub has no folder at that repo path)")


def _registered_checkout(ctx: Context, project: str) -> str | None:
    """The registered repo of ``project`` when it is a folder on the hub, else None."""
    try:
        repo = ctx.local_repo(project)
    except (StoreError, ConfigError):  # a host's copy (RemoteProjectError): its repo is there
        return None
    return str(repo) if repo.is_dir() else None


def remote_checkout(ctx: Context, host: str, project: str) -> tuple[HostSpec, str]:
    """
    Return a host's entry and its checkout of ``project``.

    Parameters
    ----------
    ctx : Context
        Hub context (reads ``environments.yaml`` fresh, so ``hx hosts map`` needs
        no restart).
    host : str
        Host name.
    project : str
        Project name.

    Returns
    -------
    tuple of (HostSpec, str)
        The host's entry and the checkout path on that host.

    Raises
    ------
    ConfigError
        Unknown host.
    RunError
        The project has no checkout on the host.

    Examples
    --------
    >>> spec, path = remote_checkout(ctx, "gpu1", "toy")  # doctest: +SKIP
    """
    spec = load_hosts(ctx.layout).environments.get(host)
    if spec is None or spec.route == "local":
        raise _unknown_host(host)
    path = spec.projects.get(project)
    if path is None:
        raise RunError(
            f"project {project} has no checkout on {host}; "
            f"run `hx hosts map {project} {host} <path on {host}>`"
        )
    return spec, path


def local_diff(repo: str | None) -> str | None:
    """
    Return the uncommitted diff of a checkout on the hub, as text.

    Parameters
    ----------
    repo : str or None
        Checkout path; None or a missing folder gives None.

    Returns
    -------
    str or None
        ``git diff HEAD --binary`` text, or None when clean.

    Raises
    ------
    RunError
        If the diff is larger than ``DIFF_LIMIT_BYTES`` or is not UTF-8 text.

    Examples
    --------
    >>> local_diff(None) is None
    True
    """
    if repo is None or not Path(repo).is_dir():
        return None
    captured = capture_diff(Path(repo), limit=DIFF_LIMIT_BYTES)
    if captured.too_large:
        raise RunError(
            f"uncommitted changes in {repo} are larger than {DIFF_LIMIT_BYTES} bytes; "
            "commit them before launching on a host"
        )
    if captured.diff is None:
        return None
    try:
        return captured.diff.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RunError(
            f"uncommitted changes in {repo} are not UTF-8 text; "
            "commit them before launching on a host"
        ) from exc


def pin_checkout(repo: str | None) -> tuple[str | None, str | None]:
    """
    Return the commit and diff that pin a hub checkout's code as it is now (spec 8A.4).

    Parameters
    ----------
    repo : str or None
        Checkout path on the hub.

    Returns
    -------
    tuple of (str or None, str or None)
        ``(HEAD, uncommitted diff or None)``; ``(None, None)`` when ``repo`` is
        None, not a folder, or not a git repository with a commit (nothing to pin).

    Raises
    ------
    RunError
        If the diff is larger than ``DIFF_LIMIT_BYTES`` or is not UTF-8 text.

    Examples
    --------
    >>> pin_checkout(None)
    (None, None)
    """
    if repo is None or not Path(repo).is_dir():
        return None, None
    head = head_commit(Path(repo))
    if head is None:
        return None, None
    return head, local_diff(repo)


def _slurm_for(host: str, spec: HostSpec, body: RunFields) -> dict[str, Any] | None:
    if spec.kind != "slurm":
        # `slurm.gpus` alone is harmless (``body.gpus`` rules here): `hx launch --gpus N`
        # sends it to every host, as it cannot tell a SLURM host's default from an explicit N
        if body.slurm is not None and body.slurm.model_fields_set - {"gpus"}:
            raise RunError(f"host {host} is not a SLURM host; drop --partition/--time/--account")
        return None
    merged = (spec.slurm or SlurmDefaults()).model_dump()
    if body.slurm is not None:
        merged.update(body.slurm.model_dump(exclude_unset=True))
    if body.gpus:
        merged["gpus"] = body.gpus
    return SlurmDefaults.model_validate(merged).model_dump(mode="json")


def launch_on_host(
    ctx: Context, manager: HubManager, host: str, body: HostLaunchBody
) -> dict[str, Any]:
    """
    Launch a run on ``host`` (or here, for ``local``).

    The body is forwarded with the same ``command_id``; ``repo`` becomes the
    host's mapped checkout and ``slurm`` the host's defaults overridden by the
    body. The run always pins a commit when the hub has a checkout (spec 8A.4):
    the body's ``commit`` with the body's ``diff`` (None for a clean run), else
    the hub checkout's HEAD with its uncommitted diff. A host-only project (no
    checkout here) sends no commit, and the host runs its checkout as it is.

    Parameters
    ----------
    ctx : Context
        Hub context.
    manager : HubManager
        The hub's host connections.
    host : str
        Host name; ``local`` launches on the hub.
    body : HostLaunchBody
        Launch fields.

    Returns
    -------
    dict
        The run record as the host returns it.

    Raises
    ------
    ConfigError
        Unknown host, or (``local``) a project copied from a host
        (``RemoteProjectError``: its repo path is on that host).
    RunError
        No project, no checkout on the host, an agent launch without a
        hypothesis, SLURM fields for a non-SLURM host, or an unusable diff.
    HostUnavailableError
        The host is not connected.

    Examples
    --------
    >>> launch_on_host(ctx, manager, "gpu1", HostLaunchBody(project="toy"))  # doctest: +SKIP
    """
    if not is_remote(host):
        repo = _hub_checkout(body) or str(ctx.local_repo(_project_of(body)))
        return to_jsonable(launch_here(ctx, body, repo))
    project = _project_of(body)
    spec, checkout = remote_checkout(ctx, host, project)
    require_agent_hypothesis(body.created_by, body.hypothesis)
    hub_repo = _hub_checkout(body) or _registered_checkout(ctx, project)
    slurm = _slurm_for(host, spec, body)
    # spec 8A.4: pin the commit the diff was taken against; the host fetches it if needed
    commit = body.commit or (head_commit(Path(hub_repo)) if hub_repo is not None else None)
    # a client that sent its own commit sends its own diff (or none); else the hub's
    sent = body.diff is not None or body.commit is not None
    diff = body.diff if sent else local_diff(hub_repo)
    payload = body.model_dump(mode="json", exclude={"project"})
    payload.update(repo=checkout, commit=commit, diff=diff, slurm=slurm)
    return manager.client(host).post_json("/api/v1/runs", payload)


def await_mirrored(ctx: Context, run_ids: list[str], timeout: float = MIRROR_WAIT_SECONDS) -> None:
    """
    Wait until the hub's index has every run (the mirror copies them from the host).

    Parameters
    ----------
    ctx : Context
        Hub context.
    run_ids : list of str
        Runs to wait for.
    timeout : float
        Seconds; after that the caller goes on with what is mirrored.

    Examples
    --------
    >>> await_mirrored(ctx, ["r1", "r2"], timeout=5)  # doctest: +SKIP
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        known = ctx.index.run_ids()
        if all(r in known for r in run_ids):
            return
        time.sleep(0.2)


def _find_artifact(artifacts: list[Artifact], wanted: str) -> Artifact | None:
    for artifact in reversed(artifacts):
        if wanted in (artifact.kind, artifact.path):
            return artifact
    return None


def pull_artifact(ctx: Context, manager: HubManager, run_id: str, artifact: str) -> Path:
    """
    Copy one big file of a remote run to the hub, into ``<run dir>/pulled/``.

    A relative path is a file in the run folder on the host, fetched over HTTP
    (any route). An absolute path is copied with ``scp -s`` (route ``ssh``
    only), and only when it is one of the run's own artifacts and is shell-safe
    (``PULL_REMOTE_PATH``, no ``..``, a file name). ``copy_from`` keeps its
    state in ``<hub home>/pulls``, so ``pulled/`` never holds Hypothex state.

    Parameters
    ----------
    ctx : Context
        Hub context.
    manager : HubManager
        The hub's host connections.
    run_id : str
        Run id.
    artifact : str
        An artifact kind (the latest of that kind, e.g. ``checkpoint``), an
        artifact path, or a path relative to the run folder on the host.

    Returns
    -------
    Path
        The local copy (for a local run: the artifact's own path).

    Raises
    ------
    RunError
        Unknown artifact, a path outside the run folder, a missing file, an
        absolute path that is not one of the run's artifacts or is not
        shell-safe, a destination name starting with ``.hx-``, or an absolute
        path on a host that is not reached over ssh.
    HostUnavailableError
        The run is mirrored from a host that is no longer configured.

    Examples
    --------
    >>> pull_artifact(ctx, manager, "r1", "checkpoint")  # doctest: +SKIP
    PosixPath('.../toy/runs/r1/pulled/step_000100.pt')
    """
    record = ctx.find_record(run_id)
    match = _find_artifact(record.artifacts, artifact)
    host = manager.host_for_environment(record.environment_id)
    if host is None:
        if record.environment_id != ctx.descriptor.environment_id:
            raise HostUnavailableError(
                f"run {run_id} belongs to environment {record.environment_id}, "
                "which no configured host serves"
            )
        if match is None:
            raise RunError(f"run {run_id} is local and has no artifact {artifact!r}")
        return Path(match.path)
    pulled = ctx.run_dir(record) / "pulled"
    if match is None and artifact.startswith("/"):
        raise RunError(f"{artifact!r} is not an artifact of run {run_id}")
    remote_path = match.path if match is not None else artifact
    if PurePosixPath(remote_path).name.startswith(PULL_RESERVED_PREFIX):
        raise RunError(
            f"{remote_path!r}: names starting with {PULL_RESERVED_PREFIX!r} are reserved"
        )
    if not remote_path.startswith("/"):
        rel = PurePosixPath(remote_path)
        if ".." in rel.parts:
            raise RunError(f"{artifact!r} is outside the run folder")
        dest = pulled / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not manager.client(host).fetch_file(run_id, str(rel), dest, max_bytes=PULL_MAX_BYTES):
            raise RunError(f"{artifact} is not in run {run_id} on {host} (or is too large)")
        return dest
    name = PurePosixPath(remote_path).name
    if (
        not PULL_REMOTE_PATH.fullmatch(remote_path)
        or ".." in remote_path.split("/")
        or remote_path.endswith("/")
        or name in ("", ".")
    ):
        raise RunError(f"invalid remote path {remote_path!r} for run {run_id}")
    spec = load_hosts(ctx.layout).environments.get(host)
    if spec is None or spec.route != "ssh":
        raise RunError(
            f"host {host} is not reached over ssh; pulling {remote_path} needs route ssh"
        )
    dest = pulled / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = ctx.layout.home / PULL_WORK_DIR  # pull state never lives next to `dest`
    try:
        copy_from(ssh_target(spec), remote_path, dest, work=work)  # scp -s: no remote shell
    except SshError as exc:
        raise RunError(str(exc)) from exc
    return dest


def _run_view(kind: str) -> list[PanelSpec]:
    """
    Run-detail panels for a task kind (spec section 8.4); the UI fills in the run.

    Parameters
    ----------
    kind : str
        Task kind.

    Returns
    -------
    list of PanelSpec
        Fresh panel specs, in display order.
    """
    if kind == "training":
        return [PanelSpec(type="curves", title="curves", data=PanelData(step_metric="step"))]
    if kind in ("agent_eval", "agent_iteration"):
        return [
            PanelSpec(type="trace", title="steps"),
            PanelSpec(type="grid", title="same item across configs"),
            PanelSpec(
                type="table",
                title="tokens per turn",
                data=PanelData(
                    source="traces", fields=["turn", "tokens_in", "tokens_out", "seconds"]
                ),
            ),
        ]
    if kind == "system_bench":
        return [
            PanelSpec(type="curves", title="over time"),
            PanelSpec(
                type="distribution",
                title="latency",
                scale="log",
                data=PanelData(metrics=["latency_ms"]),
            ),
        ]
    return [PanelSpec(type="curves", title="metrics")]


def open_run_path(store: Path, run_dir: Path, rel_path: str) -> int:
    """
    Open ``rel_path`` inside a run folder one name at a time and return its fd.

    The walk starts at a descriptor of the store root, the one trusted path.
    Every name below it, the run folder's own ``<project>/runs/<run_id>``
    included, is opened relative to the descriptor of the folder above it with
    ``O_NOFOLLOW``, so no symlink is ever followed: a link, a run folder
    replaced by a link, or a folder swapped for a link while the request runs,
    is refused like ``../``. Hypothex never writes symlinks into the store.

    Parameters
    ----------
    store : Path
        The store root (``Layout.store``).
    run_dir : Path
        The run folder, below ``store``.
    rel_path : str
        Path relative to the run folder (``/``-separated); ``""`` is the folder itself.

    Returns
    -------
    int
        An open descriptor of the file or folder (``O_NONBLOCK``, so a FIFO
        never hangs); the caller closes it.

    Raises
    ------
    StoreError
        The path is absolute, has ``..`` or a symlink (in the run folder or on
        the way to it), leaves the run folder, is in the reserved ``.hx/``
        folder, or does not exist (all answered with ``404``).

    Examples
    --------
    >>> open_run_path(Path("/tmp"), Path("/tmp/r1"), "../etc/passwd")
    Traceback (most recent call last):
    ...
    hypothex.core.errors.StoreError: '../etc/passwd' is outside the run folder
    """
    pure = PurePosixPath(rel_path)
    if pure.is_absolute() or ".." in pure.parts or "\x00" in rel_path:
        raise StoreError(f"{rel_path!r} is outside the run folder")
    if reserved_run_path(rel_path):  # Hypothex's own state: never served to anyone
        raise StoreError(f"{rel_path!r} is reserved for Hypothex")
    try:
        to_run = run_dir.relative_to(store).parts
    except ValueError:
        raise StoreError(f"run folder {run_dir} is outside the store") from None
    try:
        fd = os.open(store, _OPEN_FLAGS | _DIRECTORY)
    except OSError as exc:
        raise StoreError(f"cannot open the store: {exc.strerror}") from None
    for i, part in enumerate((*to_run, *pure.parts)):
        folder = _DIRECTORY if i < len(to_run) else 0  # down to the run folder: folders only
        try:
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise StoreError(f"run folder has no {rel_path!r}")
            child = os.open(part, _OPEN_FLAGS | _NOFOLLOW | folder, dir_fd=fd)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):  # O_NOFOLLOW met a symlink
                raise StoreError(f"{rel_path!r} is outside the run folder") from None
            if exc.errno in (errno.ENOENT, errno.ENOTDIR):
                raise StoreError(f"run folder has no {rel_path!r}") from None
            raise StoreError(f"cannot read {rel_path!r}: {exc.strerror}") from None
        finally:
            os.close(fd)
        fd = child
    return fd


def list_run_files(dir_fd: int, prefix: str = "") -> list[dict[str, Any]]:
    """
    List the regular files under an open folder, recursively, as ``{path, size, mtime_ns}``.

    The walk goes through folder descriptors (``O_NOFOLLOW`` for each sub-folder),
    so symlinks are never listed or walked, even one that replaces a folder
    during the walk. Hidden names (``.lock``, temporary ``.*.tmp`` files) are
    left out.

    Parameters
    ----------
    dir_fd : int
        Open descriptor of a folder inside the run folder (from
        :func:`open_run_path`); not closed here.
    prefix : str
        That folder's path relative to the run folder, ``""`` or ending in ``/``.

    Returns
    -------
    list of dict
        ``[{"path": "predictions/predictions.jsonl", "size": 123, "mtime_ns": ...}, ...]``,
        sorted by path.
    """
    out: list[dict[str, Any]] = []
    for name in sorted(os.listdir(dir_fd)):
        if name.startswith("."):
            continue
        try:
            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode):
            out.append({"path": prefix + name, "size": info.st_size, "mtime_ns": info.st_mtime_ns})
        elif stat.S_ISDIR(info.st_mode):
            try:
                child = os.open(name, _OPEN_FLAGS | _NOFOLLOW | _DIRECTORY, dir_fd=dir_fd)
            except OSError:
                continue  # gone, or swapped for a symlink since the stat
            try:
                out.extend(list_run_files(child, f"{prefix}{name}/"))
            finally:
                os.close(child)
    return sorted(out, key=lambda item: item["path"])


def read_span(fd: int, start: int, length: int) -> Iterator[bytes]:
    """
    Yield exactly the bytes ``[start, start + length)`` of an open file, then close it.

    The length is fixed when the response starts, so a log that keeps growing
    while it is sent never overruns the declared ``Content-Length``.

    Parameters
    ----------
    fd : int
        Open file descriptor; closed when the iterator finishes or is closed.
    start : int
        First byte offset.
    length : int
        Number of bytes to send at most.

    Yields
    ------
    bytes
        Chunks of up to 64 KiB.
    """
    try:
        offset, end = start, start + length
        while offset < end:
            chunk = os.pread(fd, min(FILE_CHUNK_BYTES, end - offset), offset)
            if not chunk:
                return
            offset += len(chunk)
            yield chunk
    finally:
        os.close(fd)


def file_response(fd: int, rel_path: str, *, max_bytes: int, tail: bool) -> Response:
    """
    Answer a run-file request: the bytes, the last ``max_bytes`` bytes, or ``413``.

    Parameters
    ----------
    fd : int
        Open descriptor from :func:`open_run_path`; this function owns it (it is
        closed here, or by :func:`read_span` once the body is sent).
    rel_path : str
        The requested path, for messages.
    max_bytes : int
        Largest body to send.
    tail : bool
        Send the last ``max_bytes`` bytes of a bigger file instead of ``413``.

    Returns
    -------
    Response
        ``200`` streaming body with ``Content-Length`` and ``X-Hypothex-Size`` (full
        size), or a ``413`` JSON error ``{error, type: "FileTooLargeError", size}``.

    Raises
    ------
    StoreError
        The path is not a regular file (FIFO, socket, device).
    """
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise StoreError(f"{rel_path!r} is not a regular file")
    size = info.st_size
    start, length = 0, size
    if size > max_bytes:
        if not tail:
            os.close(fd)
            return JSONResponse(
                status_code=413,
                content={
                    "error": f"{rel_path} is {size} bytes, over max_bytes={max_bytes}",
                    "type": "FileTooLargeError",
                    "size": size,
                },
            )
        start, length = size - max_bytes, max_bytes
    return StreamingResponse(
        read_span(fd, start, length),
        media_type="application/octet-stream",
        headers={"Content-Length": str(length), SIZE_HEADER: str(size)},
    )


class GpuCache:
    """
    ``query_gpus()`` at most once per ``GPU_CACHE_SECONDS`` (spec 8A.7: every 10 s).

    Thread-safe; FastAPI runs sync routes in a thread pool.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._at: float | None = None
        self._gpus: list[GpuInfo] = []

    def get(self) -> list[GpuInfo]:
        """
        Return the cached GPU list, refreshing it when older than ``GPU_CACHE_SECONDS``.

        Returns
        -------
        list of GpuInfo
        """
        with self._lock:
            now = time.monotonic()
            if self._at is None or now - self._at >= GPU_CACHE_SECONDS:
                self._gpus = query_gpus()
                self._at = now
            return list(self._gpus)


def register_env_routes(app: FastAPI, ctx: Context) -> None:
    """
    Add the env-server routes: run files, GPUs, and the GPU queue (spec 5.5, 8A.5, 8A.7).

    Parameters
    ----------
    app : FastAPI
        The application.
    ctx : Context
        Open context.
    """
    gpu_cache = GpuCache()
    app.state.gpu_cache = gpu_cache  # the hub's own `local` row in GET /api/v1/hosts shares it

    @app.get("/api/v1/runs/{run_id}/files/{path:path}")
    def run_file(
        run_id: str,
        path: str,
        max_bytes: Annotated[int, Query(ge=0)] = FILE_MAX_BYTES,
        tail: bool = False,
    ) -> Response:
        run_dir = ctx.run_dir(ctx.find_record(run_id))
        fd = open_run_path(ctx.layout.store, run_dir, path)
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            rel = "/".join(PurePosixPath(path).parts)
            try:
                listing = list_run_files(fd, f"{rel}/" if rel else "")
            finally:
                os.close(fd)
            return JSONResponse(listing, headers={DIR_HEADER: "1"})
        return file_response(fd, path, max_bytes=max_bytes, tail=tail)

    @app.get("/api/v1/projects/{project}/entry")
    def project_entry(project: str) -> dict[str, Any]:
        # the hub copies a host-only project's config snapshot with this (Task 34)
        return ctx.store.load_project(project).model_dump(mode="json")

    @app.get("/api/v1/gpus")
    def gpus() -> list[dict[str, Any]]:
        # held GPUs carry their run id; mirrored runs of other hosts never mark them
        return to_jsonable(gpu_status(ctx, gpu_cache.get()))

    @app.get("/api/v1/queue")
    def queue() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        positions = Scheduler(ctx).positions()
        for run_id, position in sorted(positions.items(), key=lambda item: item[1]):
            try:
                record = ctx.find_record(run_id)
            except StoreError:
                continue
            rows.append(
                {"run_id": run_id, "position": position, "gpus_requested": record.gpus_requested}
            )
        return rows

    @app.get("/api/v1/slurm")
    def slurm_capabilities() -> dict[str, Any]:
        # the hub shows this on the host row: without job comments in SLURM's accounting
        # an unknown submission can never be proven absent
        if ctx.descriptor.kind != "slurm":
            return {"comment_accounting": None}
        return {"comment_accounting": comment_accounting()}


def create_app(
    home: Path | None = None,
    *,
    background_repair: bool = True,
    host: str | None = None,
    ui_dir: Path | None = None,
    kind: str | None = None,
    auth_token: str | None = None,
    hub: bool = True,
    hub_url: str | None = None,
    lifespan_context: Callable[[], contextlib.AbstractContextManager[object]] | None = None,
) -> FastAPI:
    """
    Build the FastAPI application.

    The ``Host`` header must name a loopback address (or ``host``), else the
    answer is ``400``; a state-changing request or WebSocket handshake with a
    foreign ``Origin`` is rejected with ``403``. This blocks DNS-rebinding and
    cross-site attacks from a browser page, but it is not authentication: any
    other client can send ``Host: localhost``. ``auth_token`` adds that.

    Errors under ``/api/`` are JSON ``{error, type}``: domain errors, ``404``,
    ``405``, and ``422`` (which keeps FastAPI's ``detail`` list too).

    When ``ui_dir`` holds ``index.html`` the UI is served at ``/``; unknown
    non-API paths return ``index.html`` so browser routes survive a reload.

    Parameters
    ----------
    home : Path, optional
        Hypothex home; defaults to ``$HYPOTHEX_HOME`` or ``~/.hypothex``.
    background_repair : bool
        Run the background loops: mark orphaned runs lost every 30 s; start
        queued runs whose GPUs are free every 5 s unless the kind is ``slurm``;
        on a ``slurm`` env server, reconcile SLURM jobs every 30 s
        (``SlurmPoller``). Disable in tests.
    host : str, optional
        The address the server binds to; also accepted as ``Host`` unless it is
        a wildcard such as ``0.0.0.0``.
    ui_dir : Path, optional
        Built UI folder; defaults to the packaged ``hypothex/ui_dist``.
    kind : str, optional
        Environment kind this server reports: ``local``, ``ssh``, or ``slurm``
        (``hx serve --kind``). Default: the kind saved in ``environment.json``.
    auth_token : str, optional
        Require ``Authorization: Bearer <auth_token>`` on every route except the
        descriptor (``hx serve`` sets it from ``HYPOTHEX_SERVE_TOKEN``; see
        ``TokenGuard``).
    hub : bool
        Connect to the hosts in ``environments.yaml`` (the hub role). Off in tests
        that need no live hosts.
    hub_url : str, optional
        This server's own URL, given to the mounted MCP server so its remote tools
        call this hub (``hx serve`` passes it).
    lifespan_context : callable, optional
        Returns a context manager entered when the server starts (before the
        hub connects its hosts) and exited when it stops (after the hub
        stopped), in the ASGI lifespan: inside uvicorn's signal handling, so a
        SIGTERM runs its cleanup too. ``hx serve`` passes the demo hosts.

    Returns
    -------
    FastAPI
        The application; consumers use only this API.

    Raises
    ------
    ValueError
        For an unknown ``kind``.
    """
    if kind is not None and kind not in ENV_KINDS:
        raise ValueError(f"kind must be one of {', '.join(ENV_KINDS)}, got {kind!r}")
    ctx = Context.open(home)
    if kind is not None:
        ctx.descriptor.kind = kind
    manager = HubManager(ctx)
    if ctx.descriptor.kind == "slurm":
        require_flock(ctx.layout.home)  # every run-state write takes the run lock
    # one Context (and descriptor) for HTTP and MCP
    mcp_server = build_server(hub_url=hub_url, context=ctx, hub_token=auth_token)
    mcp_http = mcp_server.streamable_http_app(streamable_http_path="/")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(control.repair_runs, ctx)
        task = asyncio.create_task(_repair_loop(ctx)) if background_repair else None
        stop = threading.Event()
        loops: list[threading.Thread] = []
        if background_repair and ctx.descriptor.kind != "slurm":
            loops.append(
                threading.Thread(
                    target=run_scheduler_loop,
                    args=(ctx, stop),
                    kwargs={"interval": SCHEDULER_INTERVAL_SECONDS},
                    name="hx-scheduler",
                    daemon=True,
                )
            )
        for loop in loops:
            loop.start()
        # SLURM env servers reconcile their jobs every 30 s; lost needs two polls in a row
        poller = SlurmPoller(ctx) if background_repair and ctx.descriptor.kind == "slurm" else None
        if poller is not None:
            poller.start()
        if hub:
            await manager.start()
        async with mcp_server.session_manager.run():
            try:
                yield
            finally:
                try:
                    await manager.stop()
                finally:
                    # the loops stop even when the hub's stop fails
                    stop.set()
                    if poller is not None:
                        # wait for the thread itself: a squeue can block for 60 s, and the
                        # context must not be released under a poll that is still running
                        await asyncio.to_thread(poller.stop)
                    if task is not None:
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                    for loop in loops:
                        await asyncio.to_thread(loop.join, 10)

    @asynccontextmanager
    async def lifespan_with_context(app_: FastAPI) -> AsyncIterator[None]:
        # uvicorn re-raises SIGTERM after its shutdown, which skips any `with` around
        # it; the lifespan's own shutdown always runs first
        with contextlib.ExitStack() as extra:
            if lifespan_context is not None:
                await asyncio.to_thread(extra.enter_context, lifespan_context())
            try:
                async with lifespan(app_):
                    yield
            finally:
                await asyncio.to_thread(extra.close)

    app = FastAPI(
        title="Hypothex",
        version=__version__,
        lifespan=lifespan_with_context,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.ctx = ctx
    app.state.hub = manager
    app.state.mcp = mcp_server
    hosts = allowed_hosts(host)
    # innermost: the guards answer first, and the hub's tunnels carry compressed JSON
    app.add_middleware(
        GZipMiddleware,
        minimum_size=GZIP_MIN_BYTES,
        compresslevel=GZIP_LEVEL,
        exclude_content_types=GZIP_SKIP_TYPES,
    )
    app.add_middleware(OriginGuard, hosts=hosts)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    if auth_token:
        app.add_middleware(TokenGuard, token=auth_token)  # outermost: checked first

    @app.exception_handler(HypothexError)
    async def hypothex_error(_: Request, exc: HypothexError) -> JSONResponse:
        if isinstance(exc, StoreError):
            status = 404
        elif isinstance(exc, HostUnavailableError):
            status = 503
        else:
            status = 400
        if isinstance(exc, CommandInterruptedError):
            status = 409  # the command's outcome is unknown: never replayed
        content: dict[str, Any] = {"error": str(exc), "type": type(exc).__name__}
        if isinstance(exc, ViewValidationError):
            content["issues"] = to_jsonable(exc.issues)
        return JSONResponse(status_code=status, content=content)

    @app.exception_handler(EnvRequestError)
    async def host_error(_: Request, exc: EnvRequestError) -> JSONResponse:
        # a host's error answer keeps its status; no answer at all is 503
        status = 503 if isinstance(exc, EnvUnreachableError) else exc.status_code or 502
        content = {"error": str(exc), "type": exc.error_type or type(exc).__name__}
        return JSONResponse(status_code=status, content=content)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if not request.url.path.startswith("/api/"):
            return await http_exception_handler(request, exc)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": str(exc.detail), "type": "HTTPError"},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Response:
        if not request.url.path.startswith("/api/"):
            return await request_validation_exception_handler(request, exc)
        problems = exc.errors()
        first = problems[0] if problems else {}
        where = ".".join(str(part) for part in first.get("loc", ()))
        message = str(first.get("msg", "invalid request"))
        return JSONResponse(
            status_code=422,
            content={
                "error": f"{where}: {message}" if where else message,
                "type": "RequestValidationError",
                "detail": validation_detail(problems),
            },
        )

    def once(body: ActionBody, fn: Callable[[], Any]) -> dict[str, Any]:
        return ctx.events.run_once(body.command_id, lambda: to_jsonable(fn()))

    def forward(
        run_id: str,
        action: str,
        body: ActionBody,
        local: Callable[[], Any],
        *,
        remote_only: bool = False,
    ) -> dict[str, Any]:
        # A run mirrored from a host is acted on by that host; same body, same command_id.
        # The run is looked up inside `once`, so a replayed command_id gets its receipt
        # first (as in phase 1); an error releases the claim, so a retry runs again.
        def act() -> Any:
            record = ctx.find_record(run_id)
            host = manager.host_for_environment(record.environment_id)
            if host is None:
                source = manager.mirrored_from(record.environment_id)
                foreign = record.environment_id != ctx.descriptor.environment_id
                # remote_only: its pids and paths belong to another machine. A mirrored run:
                # the host's copy replaces the hub's on its next mirror, so an edit made
                # here (tags, star, archive, notes) would be lost without a word
                if foreign and (remote_only or source is not None):
                    mirrored = f" (mirrored from host {source})" if source else ""
                    raise HostUnavailableError(
                        f"run {run_id} belongs to environment {record.environment_id}{mirrored}, "
                        f"which no configured host serves; {action} must run on that host "
                        "(`hx hosts add` / `hx hosts connect`)"
                    )
                return local()
            payload = body.model_dump(mode="json")
            timeout = REEVAL_FORWARD_SECONDS if action == "reeval" else None
            return manager.client(host).post_json(
                f"/api/v1/runs/{run_id}/{action}", payload, timeout=timeout
            )

        return once(body, act)

    def launcher_for(host: str | None, launched: list[str], *, project: str) -> Launcher | None:
        # None: the sweep engine launches here; a host name: forward each run to it.
        # `launched` collects the run ids the host answers with (settled() waits for them)
        if not is_remote(host):
            return None
        target = str(host)
        pinned: dict[str, str | None] = {}

        def launch(req: RunRequest, run_command_id: str) -> RunRecord:
            parsed = [p for p in map(parse_sweep_tag, req.tags) if p is not None]
            sweep_id = parsed[0][1] if parsed else None
            # never a host's copy, whose repo path may also name a folder here
            local = _registered_checkout(ctx, project) is not None and req.repo.is_dir()
            if "commit" not in pinned:
                # spec 8A.4: one commit for every run of this call; the host fetches it.
                # The sweep's stored pin (SweepSpec.commit/diff, so an extend runs the
                # sweep's code); a sweep file that pins nothing: the hub checkout now
                if req.commit is not None:
                    diff = req.diff.decode("utf-8") if isinstance(req.diff, bytes) else req.diff
                    pinned.update(commit=req.commit, diff=diff)
                else:
                    pinned["commit"], pinned["diff"] = pin_checkout(
                        str(req.repo) if local else None
                    )
            body = HostLaunchBody(
                repo=str(req.repo) if local else None,
                project=project,
                commit=pinned["commit"],
                diff=pinned["diff"],
                task=req.task,
                command=req.command,
                hypothesis=req.hypothesis,
                seed=req.seed,
                tags=req.tags,
                params=req.params,
                vars=req.vars,
                gpus=req.gpus,
                queue=req.queue,
                sweep_id=sweep_id,
                created_by=req.created_by,
                command_id=run_command_id,  # the host's receipt makes a repeat the same run
            )
            record = RunRecord.model_validate(launch_on_host(ctx, manager, target, body))
            launched.append(record.run_id)
            return record

        return launch

    def stopper_for(host: str | None, command_id: str | None) -> Callable[[str], object] | None:
        # None: stop_if_queued here; a host name: an only_queued stop on that host
        if not is_remote(host):
            return None
        target = str(host)

        def stop(run_id: str) -> None:
            manager.client(target).post_json(
                f"/api/v1/runs/{run_id}/stop",
                {
                    "command_id": f"{command_id}:{run_id}" if command_id else None,
                    "only_queued": True,
                    "created_by": "hub",
                },
            )

        return stop

    def host_state_of(environment_id: str) -> str | None:
        # the connection state of the host serving a run's environment; None: a hub run
        host = manager.host_for_environment(environment_id)
        return None if host is None else manager.state(host).state

    def settled(spec: SweepSpec, launched: list[str]) -> SweepSummary:
        # members are indexed runs: wait until this call's remote runs are mirrored
        if is_remote(spec.host):
            await_mirrored(ctx, launched)
        return summarize_sweep(ctx, spec.project, spec.id)

    # environment -----------------------------------------------------------------
    @app.get("/.well-known/hypothex/environment")
    def environment(request: Request) -> dict[str, Any]:
        full = ctx.descriptor.model_dump(mode="json")
        if auth_token and not bearer_matches(request.headers.get("authorization"), auth_token):
            # open so start.sh can find its server; host facts only for the token holder
            return {k: full[k] for k in PUBLIC_DESCRIPTOR_FIELDS}
        return full

    # hosts (hub) ---------------------------------------------------------------------
    @app.get("/api/v1/hosts")
    def hosts_list() -> list[dict[str, Any]]:
        return host_rows(ctx, manager, app.state.gpu_cache)

    @app.post("/api/v1/hosts/reload")
    async def hosts_reload(body: ActionBody | None = None) -> list[dict[str, Any]]:
        # `hx hosts add|map|rm` wrote environments.yaml: apply it to the running hub
        await manager.reload()
        # host_rows makes blocking calls to each host: keep them off the hub's event loop
        return await asyncio.to_thread(host_rows, ctx, manager, app.state.gpu_cache)

    @app.post("/api/v1/hosts/{host}/connect")
    async def host_connect(host: str, body: ActionBody | None = None) -> dict[str, Any]:
        return to_jsonable(await manager.connect(host))

    @app.post("/api/v1/hosts/{host}/disconnect")
    async def host_disconnect(host: str, body: ActionBody | None = None) -> dict[str, Any]:
        return to_jsonable(await manager.disconnect(host))

    @app.post("/api/v1/hosts/{host}/runs")
    def host_launch(host: str, body: HostLaunchBody) -> dict[str, Any]:
        return once(body, lambda: launch_on_host(ctx, manager, host, body))

    # overview ----------------------------------------------------------------------
    @app.get("/api/v1/overview")
    def overview(since: datetime | None = None) -> dict[str, Any]:
        if since is not None and since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        return to_jsonable(build_overview(ctx, since))

    # projects & tasks ------------------------------------------------------------
    @app.get("/api/v1/projects")
    def projects() -> list[dict[str, Any]]:
        return [
            {
                "project": e.project,
                "repo": e.repo,
                "description": e.config.description,
                "tasks": sorted(e.config.tasks),
            }
            for e in q.list_projects(ctx)
        ]

    @app.get("/api/v1/tasks")
    def tasks(project: str | None = None) -> list[dict[str, Any]]:
        return to_jsonable(q.list_tasks(ctx, project))

    @app.get("/api/v1/tasks/{project}/{task}")
    def task_detail(project: str, task: str) -> dict[str, Any]:
        return q.get_task(ctx, task, project)

    @app.get("/api/v1/tasks/{project}/{task}/leaderboard")
    def leaderboard(
        project: str, task: str, metric: Annotated[list[str] | None, Query()] = None
    ) -> dict[str, Any]:
        versions = {}
        for item in metric or []:
            name, version = parse_metric_version(item)
            if version is None:
                raise RunError(f"metric needs name@version, got {item!r}")
            versions[name] = version
        return to_jsonable(q.get_leaderboard(ctx, task, project, versions or None))

    @app.post("/api/v1/tasks/{project}/{task}/reeval")
    def task_reeval(project: str, task: str, body: ReevalBody) -> dict[str, Any]:
        # spec 8A.3: a mirrored run is re-scored on its host (the mirror replaces the hub's
        # scores.jsonl with the host's whole file); only the hub's own runs, and runs no
        # host ever mirrored here (demo, imported), are scored here
        def act() -> EvalReport:
            runs = ctx.index.list_runs(
                project=project,
                task=task,
                status=RunStatus.FINISHED,
                include_archived=True,
                limit=None,
            )
            hosts = {e: _mirror_host(e) for e in {r.environment_id for r in runs}}
            if not any(hosts.values()):
                return reeval(ctx, project=project, task=task, metric=body.metric, force=body.force)
            # the hub's own runs in one core call, then each mirrored run on its host
            here = [r.run_id for r in runs if hosts[r.environment_id] is None]
            report = reeval(
                ctx,
                project=project,
                task=task,
                metric=body.metric,
                force=body.force,
                run_ids=here,
            )
            down: dict[str, str] = {}  # host -> why nothing more is sent to it
            for record in reversed(runs):  # oldest first, as core reeval
                host = hosts[record.environment_id]
                if host is None:
                    continue
                if host in down:
                    report.skipped[record.run_id] = down[host]
                    continue
                try:
                    part = EvalReport.model_validate(_reeval_on(host, record.run_id, body))
                except (HostUnavailableError, EnvUnreachableError) as exc:
                    down[host] = report.skipped[record.run_id] = f"host {host}: {exc}"[:500]
                    continue
                except EnvRequestError as exc:
                    report.skipped[record.run_id] = f"host {host}: {exc}"[:500]
                    continue
                report.evaluated += part.evaluated
                report.skipped.update(part.skipped)
                report.warnings += [w for w in part.warnings if w not in report.warnings]
            return report

        return once(body, act)

    def _mirror_host(environment_id: str) -> str | None:
        # None: re-score here; else the host the run was mirrored from (configured or not)
        return manager.host_for_environment(environment_id) or manager.mirrored_from(environment_id)

    def _reeval_on(host: str, run_id: str, body: ReevalBody) -> Any:
        if host not in manager.names():
            raise HostUnavailableError(
                f"it is no longer in environments.yaml; re-evaluate run {run_id} there "
                "(`hx hosts add`)"
            )
        payload = body.model_dump(mode="json")
        # one command id per run, so a retried task reeval re-scores each run at most once
        payload["command_id"] = f"{body.command_id}:{run_id}" if body.command_id else None
        return manager.client(host).post_json(
            f"/api/v1/runs/{run_id}/reeval", payload, timeout=REEVAL_FORWARD_SECONDS
        )

    @app.get("/api/v1/tasks/{project}/{task}/kind")
    def task_kind(project: str, task: str) -> dict[str, Any]:
        entry, name = q.resolve_task(ctx, task, project)
        kind = entry.config.tasks[name].kind
        return {"kind": kind, "run_view": to_jsonable(_run_view(kind))}

    # views -------------------------------------------------------------------------
    @app.get("/api/v1/tasks/{project}/{task}/views")
    def views(project: str, task: str) -> list[dict[str, Any]]:
        return to_jsonable(list_task_views(ctx, task, project))

    @app.post("/api/v1/tasks/{project}/{task}/views/validate")
    def views_validate(project: str, task: str, body: ViewTextBody) -> dict[str, Any]:
        return validate_view(ctx, task, body.text, project)

    @app.post("/api/v1/tasks/{project}/{task}/views/query")
    def views_query(project: str, task: str, body: ViewQueryBody) -> dict[str, Any]:
        return query_task_view(
            ctx, task, project=project, name=body.name, view=body.view, panel=body.panel
        )

    @app.get("/api/v1/tasks/{project}/{task}/views/{name}")
    def view_get(project: str, task: str, name: str) -> dict[str, Any]:
        return view_document(ctx, task, name, project)

    @app.put("/api/v1/tasks/{project}/{task}/views/{name}")
    def view_put(project: str, task: str, name: str, body: ViewPutBody) -> dict[str, Any]:
        return once(body, lambda: put_view(ctx, task, name, body.text, project))

    @app.delete("/api/v1/tasks/{project}/{task}/views/{name}")
    def view_delete(project: str, task: str, name: str) -> dict[str, Any]:
        return remove_view(ctx, task, name, project)

    # runs ----------------------------------------------------------------------------
    @app.get("/api/v1/runs")
    def runs(
        project: str | None = None,
        task: str | None = None,
        status: RunStatus | None = None,
        tag: str | None = None,
        environment_id: str | None = None,
        archived: bool = False,
        limit: Annotated[int, Query(ge=1)] = 200,
        before_created_at: datetime | None = None,
        before_run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        # no cap below `limit`. Keyset paging: the next page starts after the last row of
        # this one (`before_created_at`, `before_run_id`), so a page costs `limit` rows
        if (before_created_at is None) != (before_run_id is None):
            raise RunError("give before_created_at and before_run_id together")
        before = None
        if before_created_at is not None and before_run_id is not None:
            if before_created_at.tzinfo is None:
                before_created_at = before_created_at.replace(tzinfo=UTC)
            before = (before_created_at.astimezone(UTC), before_run_id)
        records = ctx.index.list_runs(
            project=project,
            task=task,
            status=status,
            tag=tag,
            environment_id=environment_id,
            include_archived=archived,
            limit=limit,
            before=before,
        )
        rows = to_jsonable(q.with_queue_positions(ctx, records))
        # like the run detail: the CLI and MCP list runs through the hub and see a stale host
        states: dict[str, str | None] = {}
        for row in rows:
            env = row["environment_id"]
            if env not in states:
                states[env] = host_state_of(env)
            row["host_state"] = states[env]
        return rows

    @app.post("/api/v1/runs")
    def launch(body: LaunchBody) -> dict[str, Any]:
        return once(body, lambda: launch_here(ctx, body, body.repo))

    @app.get("/api/v1/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        detail = q.show_run(ctx, run_id)
        out = to_jsonable(detail)
        out["host_state"] = host_state_of(detail.record.environment_id)
        return out

    @app.get("/api/v1/runs/{run_id}/metrics")
    def run_metrics(
        run_id: str,
        names: Annotated[list[str] | None, Query()] = None,
        max_points: Annotated[int | None, Query(ge=2)] = None,
    ) -> list[dict[str, Any]]:
        # a chart asks for the names it shows, at about its width in points (PERF-F9)
        return to_jsonable(q.metric_history(ctx, run_id, names=names, max_points=max_points))

    @app.get("/api/v1/runs/{run_id}/traces")
    def run_traces(run_id: str) -> list[dict[str, Any]]:
        record = ctx.find_record(run_id)
        return ctx.store.list_traces(record.project, record.run_id)

    # `:path` keeps example ids such as "HumanEval/0" in one parameter.
    @app.get("/api/v1/runs/{run_id}/traces/{example_id:path}")
    def run_trace(run_id: str, example_id: str) -> dict[str, Any]:
        record = ctx.find_record(run_id)
        known = {t["example_id"] for t in ctx.store.list_traces(record.project, record.run_id)}
        if example_id not in known:
            raise StoreError(f"run {run_id} has no trace for example {example_id!r}")
        panel = PanelSpec(
            type="trace",
            title=example_id,
            data=PanelData(run_id=run_id, example_id=example_id),
        )
        return to_jsonable(query_panel(ctx, record.project, record.task or "", panel))

    @app.get("/api/v1/runs/{run_id}/logs")
    def run_logs(run_id: str, stream: str = "stdout", offset: int | None = None) -> dict[str, Any]:
        return to_jsonable(q.read_log(ctx, run_id, stream, offset))

    @app.get("/api/v1/runs/{run_id}/predictions")
    def run_predictions(
        run_id: str,
        offset: int = 0,
        limit: int = 50,
        metric: str | None = None,
        failures_only: bool = False,
        field: str = "correct",
    ) -> dict[str, Any]:
        return to_jsonable(
            q.get_predictions(
                ctx,
                run_id,
                offset=offset,
                limit=limit,
                metric=metric,
                failures_only=failures_only,
                field=field,
            )
        )

    @app.post("/api/v1/runs/{run_id}/rerun")
    def run_rerun(run_id: str, body: ActionBody) -> dict[str, Any]:
        return forward(
            run_id,
            "rerun",
            body,
            lambda: control.rerun(ctx, run_id, created_by=body.created_by),
            remote_only=True,
        )

    @app.post("/api/v1/runs/{run_id}/reinfer")
    def run_reinfer(run_id: str, body: ReinferBody) -> dict[str, Any]:
        return forward(
            run_id,
            "reinfer",
            body,
            lambda: control.reinfer(
                ctx, run_id, checkpoint=body.checkpoint, created_by=body.created_by
            ),
            remote_only=True,
        )

    @app.post("/api/v1/runs/{run_id}/reeval")
    def run_reeval(run_id: str, body: ReevalBody) -> dict[str, Any]:
        return forward(
            run_id,
            "reeval",
            body,
            lambda: reeval(ctx, run_id=run_id, metric=body.metric, force=body.force),
            remote_only=True,
        )

    @app.post("/api/v1/runs/{run_id}/stop")
    def run_stop(run_id: str, body: StopBody) -> dict[str, Any]:
        def act() -> RunRecord:
            if body.only_queued:
                return stop_if_queued(ctx, run_id)
            return control.stop_run(ctx, run_id)

        return forward(run_id, "stop", body, act, remote_only=True)

    @app.post("/api/v1/runs/{run_id}/tags")
    def run_tags(run_id: str, body: TagBody) -> dict[str, Any]:
        return forward(run_id, "tags", body, lambda: q.tag_run(ctx, run_id, body.add, body.remove))

    @app.post("/api/v1/runs/{run_id}/star")
    def run_star(run_id: str, body: FlagBody) -> dict[str, Any]:
        return forward(run_id, "star", body, lambda: q.star_run(ctx, run_id, body.on))

    @app.post("/api/v1/runs/{run_id}/archive")
    def run_archive(run_id: str, body: FlagBody) -> dict[str, Any]:
        return forward(run_id, "archive", body, lambda: q.archive_run(ctx, run_id, body.on))

    @app.post("/api/v1/runs/{run_id}/notes")
    def run_note(run_id: str, body: NoteBody) -> dict[str, Any]:
        def act() -> dict[str, bool]:
            q.add_note(ctx, run_id, body.text, body.author)
            return {"ok": True}

        return forward(run_id, "notes", body, act)

    # sweeps --------------------------------------------------------------------------
    @app.post("/api/v1/sweeps")
    def sweep_create(body: SweepBody) -> dict[str, Any]:
        require_agent_hypothesis(body.created_by, body.hypothesis)

        def act() -> SweepSummary:
            remote = is_remote(body.host)
            if remote:
                remote_checkout(ctx, str(body.host), body.project)  # unknown host or no map
            # spec 8A.4: the sweep stores its code, so an extend runs the same commit and
            # diff: the client's (`hx sweep --host` from a laptop), else the hub checkout's
            if body.commit is not None:
                commit, diff = body.commit, body.diff
            else:
                commit, diff = pin_checkout(_registered_checkout(ctx, body.project))
            launched: list[str] = []
            summary = launch_sweep(
                ctx,
                project=body.project,
                task=body.task,
                host=body.host if remote else None,
                grid=body.grid,
                random=body.random,
                seeds=body.seeds,
                command=body.command,
                hypothesis=body.hypothesis,
                gpus=body.gpus,
                queue=body.queue,
                created_by=body.created_by,
                launch=launcher_for(body.host, launched, project=body.project),
                command_id=body.command_id,  # a retry resumes this sweep (Task 40)
                commit=commit,
                diff=diff,
            )
            return settled(summary.spec, launched)

        # no command receipt: launch_sweep resumes the sweep a command id made (its claim
        # file) and issues only the missing runs, even after a hub crash mid-launch, where
        # a receipt would be `__interrupted__` and refuse the retry
        return to_jsonable(act())

    @app.get("/api/v1/sweeps/{sweep_id}")
    def sweep_get_by_id(sweep_id: str) -> dict[str, Any]:
        # a client on another machine knows the id, not the hub's store
        spec = find_sweep(ctx, sweep_id)
        return to_jsonable(summarize_sweep(ctx, spec.project, spec.id))

    @app.get("/api/v1/sweeps/{project}/{sweep_id}")
    def sweep_get(project: str, sweep_id: str) -> dict[str, Any]:
        spec = find_sweep(ctx, sweep_id, project)
        return to_jsonable(summarize_sweep(ctx, spec.project, spec.id))

    @app.get("/api/v1/projects/{project}/sweeps")
    def project_sweeps(project: str) -> list[dict[str, Any]]:
        return to_jsonable(list_sweeps(ctx, project))

    @app.post("/api/v1/sweeps/{project}/{sweep_id}/cancel_queued")
    def sweep_cancel(project: str, sweep_id: str, body: ActionBody | None = None) -> dict[str, Any]:
        action = body or ActionBody()

        def act() -> SweepSummary:
            spec = find_sweep(ctx, sweep_id, project)
            stop = stopper_for(spec.host, action.command_id)
            return cancel_queued(ctx, spec.project, spec.id, stop=stop)

        return once(action, act)

    @app.post("/api/v1/sweeps/{project}/{sweep_id}/extend")
    def sweep_extend(project: str, sweep_id: str, body: SeedsBody) -> dict[str, Any]:
        def act() -> SweepSummary:
            spec = find_sweep(ctx, sweep_id, project)
            launched: list[str] = []
            launch = launcher_for(spec.host, launched, project=spec.project)
            more = extend_sweep(ctx, spec.project, spec.id, body.seeds, launch=launch)
            return settled(more.spec, launched)

        return once(body, act)

    @app.post("/api/v1/runs/{run_id}/pull")
    def run_pull(run_id: str, body: PullBody) -> dict[str, Any]:
        return once(
            body, lambda: {"local_path": str(pull_artifact(ctx, manager, run_id, body.artifact))}
        )

    # compare & datasets ----------------------------------------------------------------
    @app.get("/api/v1/compare")
    def compare(ids: str) -> dict[str, Any]:
        return to_jsonable(q.compare_runs(ctx, [i for i in ids.split(",") if i]))

    @app.get("/api/v1/compare/examples")
    def compare_examples(a: str, b: str, metric: str, field: str = "correct") -> dict[str, Any]:
        return to_jsonable(q.compare_examples(ctx, a, b, metric, field))

    @app.get("/api/v1/datasets/check")
    def datasets_check(project: str | None = None) -> list[dict[str, Any]]:
        return to_jsonable(q.check_datasets(ctx, project))

    # live events -------------------------------------------------------------------------
    @app.websocket("/api/v1/ws")
    async def events_ws(ws: WebSocket) -> None:
        await ws.accept()
        try:
            first = await ws.receive()
            if first["type"] == "websocket.disconnect":
                return
            try:
                sub = SubscribeMessage.model_validate_json(
                    first.get("text") or first.get("bytes") or ""
                )
            except ValidationError:
                await ws.send_json(
                    {
                        "type": "error",
                        "error": "first message must be {type: subscribe, after_sequence: N}"
                        ' with N an integer >= 0 or "latest" (and an optional max_replay >= 1)',
                    }
                )
                await ws.close()
                return
            head = await asyncio.to_thread(ctx.events.last_sequence)
            if sub.after_sequence == "latest":
                last = head
            elif sub.max_replay is not None and head - sub.after_sequence > sub.max_replay:
                # too far behind to replay cheaply: the client reloads, then goes on live
                await ws.send_json({"type": "reset", "last_sequence": head})
                last = head
            else:
                last = sub.after_sequence
            ready = False
            while True:
                batch = await asyncio.to_thread(ctx.events.since, last, WS_BATCH)
                for event in batch:
                    await ws.send_json({"type": "event", "event": event.model_dump(mode="json")})
                    last = event.sequence
                if len(batch) < WS_BATCH:
                    if not ready:
                        await ws.send_json({"type": "ready", "last_sequence": last})
                        ready = True
                    if await client_left(ws, WS_POLL_SECONDS):
                        return
        except WebSocketDisconnect:
            return

    register_env_routes(app, ctx)
    app.mount("/mcp", mcp_http)

    ui = ui_dir or UI_DIST
    if (ui / "index.html").is_file():
        app.mount("/", SpaStaticFiles(directory=ui, html=True), name="ui")
    return app
