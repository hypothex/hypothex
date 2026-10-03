"""HTTP + WebSocket API. The UI and remote clients use only this."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import logging
import os
import stat
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.types import Scope

from hypothex._version import __version__
from hypothex.api.security import OriginGuard, allowed_hosts
from hypothex.core import control
from hypothex.core import queries as q
from hypothex.core.context import Context
from hypothex.core.errors import HypothexError, StoreError
from hypothex.core.evaluation import reeval
from hypothex.core.execution import RunRequest
from hypothex.core.gpus import GpuInfo, gpu_status, query_gpus
from hypothex.core.jsonutil import to_jsonable
from hypothex.core.layout import reserved_run_path
from hypothex.core.overview import build_overview
from hypothex.core.panels import query_panel
from hypothex.core.records import RunStatus
from hypothex.core.scheduler import Scheduler, run_scheduler_loop
from hypothex.core.views import PanelData, PanelSpec, ViewSpec
from hypothex.mcp.server import (
    ViewValidationError,
    build_server,
    list_task_views,
    put_view,
    query_task_view,
    remove_view,
    validate_view,
    view_document,
)
from hypothex.remote.client import DIR_HEADER, SIZE_HEADER

log = logging.getLogger(__name__)

REPAIR_INTERVAL_SECONDS = 30.0
SCHEDULER_INTERVAL_SECONDS = 5.0
ENV_KINDS = ("local", "ssh", "slurm")
WS_POLL_SECONDS = 0.5
WS_BATCH = 500
UI_DIST = Path(__file__).resolve().parent.parent / "ui_dist"
NO_UI_FALLBACK = frozenset({"api", "mcp", ".well-known", "assets"})
FILE_MAX_BYTES = 200 * 1024 * 1024
FILE_CHUNK_BYTES = 64 * 1024
GPU_CACHE_SECONDS = 10.0
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


class LaunchBody(ActionBody):
    """Body of ``POST /api/v1/runs``."""

    repo: str
    task: str | None = None
    stage: str | None = None
    command: list[str] | None = None
    hypothesis: str = ""
    seed: int | None = None
    tags: list[str] = Field(default_factory=list)
    params: dict[str, str] = Field(default_factory=dict)
    vars: dict[str, str] = Field(default_factory=dict)


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


async def _repair_loop(ctx: Context) -> None:
    """Mark orphaned runs lost every ``REPAIR_INTERVAL_SECONDS``."""
    while True:
        await asyncio.sleep(REPAIR_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(control.repair_runs, ctx)
        except Exception:  # noqa: BLE001 - keep the server alive
            log.exception("run repair failed")


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


def create_app(
    home: Path | None = None,
    *,
    background_repair: bool = True,
    host: str | None = None,
    ui_dir: Path | None = None,
    kind: str | None = None,
) -> FastAPI:
    """
    Build the FastAPI application.

    Only local requests are served: the ``Host`` header must name a loopback
    address (or ``host``), else the answer is ``400``; a state-changing request
    or WebSocket handshake with a foreign ``Origin`` is rejected with ``403``.
    This blocks DNS-rebinding and cross-site attacks from a browser page.

    When ``ui_dir`` holds ``index.html`` the UI is served at ``/``; unknown
    non-API paths return ``index.html`` so browser routes survive a reload.

    Parameters
    ----------
    home : Path, optional
        Hypothex home; defaults to ``$HYPOTHEX_HOME`` or ``~/.hypothex``.
    background_repair : bool
        Run the background loops: mark orphaned runs lost every 30 s, and start
        queued runs whose GPUs are free every 5 s unless the kind is ``slurm``.
        Disable in tests.
    host : str, optional
        The address the server binds to; also accepted as ``Host`` unless it is
        a wildcard such as ``0.0.0.0``.
    ui_dir : Path, optional
        Built UI folder; defaults to the packaged ``hypothex/ui_dist``.
    kind : str, optional
        Environment kind this server reports: ``local``, ``ssh``, or ``slurm``
        (``hx serve --kind``). Default: the kind saved in ``environment.json``.

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
    mcp_server = build_server(home)
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
        async with mcp_server.session_manager.run():
            try:
                yield
            finally:
                stop.set()
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                for loop in loops:
                    await asyncio.to_thread(loop.join, 10)

    app = FastAPI(
        title="Hypothex",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.ctx = ctx
    hosts = allowed_hosts(host)
    app.add_middleware(OriginGuard, hosts=hosts)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.exception_handler(HypothexError)
    async def hypothex_error(_: Request, exc: HypothexError) -> JSONResponse:
        status = 404 if isinstance(exc, StoreError) else 400
        content: dict[str, Any] = {"error": str(exc), "type": type(exc).__name__}
        if isinstance(exc, ViewValidationError):
            content["issues"] = to_jsonable(exc.issues)
        return JSONResponse(status_code=status, content=content)

    def once(body: ActionBody, fn: Callable[[], Any]) -> dict[str, Any]:
        return ctx.events.run_once(body.command_id, lambda: to_jsonable(fn()))

    # environment -----------------------------------------------------------------
    @app.get("/.well-known/hypothex/environment")
    def environment() -> dict[str, Any]:
        return ctx.descriptor.model_dump(mode="json")

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
            name, _, version = item.partition("@")
            if version:
                versions[name] = version
        return to_jsonable(q.get_leaderboard(ctx, task, project, versions or None))

    @app.post("/api/v1/tasks/{project}/{task}/reeval")
    def task_reeval(project: str, task: str, body: ReevalBody) -> dict[str, Any]:
        return once(
            body,
            lambda: reeval(ctx, project=project, task=task, metric=body.metric, force=body.force),
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
        archived: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return to_jsonable(
            ctx.index.list_runs(
                project=project,
                task=task,
                status=status,
                tag=tag,
                include_archived=archived,
                limit=limit,
            )
        )

    @app.post("/api/v1/runs")
    def launch(body: LaunchBody) -> dict[str, Any]:
        req = RunRequest(
            repo=Path(body.repo),
            command=body.command,
            stage=body.stage,
            task=body.task,
            hypothesis=body.hypothesis,
            seed=body.seed,
            tags=body.tags,
            params=body.params,
            vars=body.vars,
            created_by=body.created_by,
        )
        return once(body, lambda: control.launch_run(ctx, req))

    @app.get("/api/v1/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        return to_jsonable(q.show_run(ctx, run_id))

    @app.get("/api/v1/runs/{run_id}/metrics")
    def run_metrics(run_id: str) -> list[dict[str, Any]]:
        return to_jsonable(q.metric_history(ctx, run_id))

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
        return once(body, lambda: control.rerun(ctx, run_id, created_by=body.created_by))

    @app.post("/api/v1/runs/{run_id}/reinfer")
    def run_reinfer(run_id: str, body: ReinferBody) -> dict[str, Any]:
        return once(
            body,
            lambda: control.reinfer(
                ctx, run_id, checkpoint=body.checkpoint, created_by=body.created_by
            ),
        )

    @app.post("/api/v1/runs/{run_id}/reeval")
    def run_reeval(run_id: str, body: ReevalBody) -> dict[str, Any]:
        return once(body, lambda: reeval(ctx, run_id=run_id, metric=body.metric, force=body.force))

    @app.post("/api/v1/runs/{run_id}/stop")
    def run_stop(run_id: str, body: ActionBody) -> dict[str, Any]:
        return once(body, lambda: control.stop_run(ctx, run_id))

    @app.post("/api/v1/runs/{run_id}/tags")
    def run_tags(run_id: str, body: TagBody) -> dict[str, Any]:
        return once(body, lambda: q.tag_run(ctx, run_id, body.add, body.remove))

    @app.post("/api/v1/runs/{run_id}/star")
    def run_star(run_id: str, body: FlagBody) -> dict[str, Any]:
        return once(body, lambda: q.star_run(ctx, run_id, body.on))

    @app.post("/api/v1/runs/{run_id}/archive")
    def run_archive(run_id: str, body: FlagBody) -> dict[str, Any]:
        return once(body, lambda: q.archive_run(ctx, run_id, body.on))

    @app.post("/api/v1/runs/{run_id}/notes")
    def run_note(run_id: str, body: NoteBody) -> dict[str, Any]:
        def act() -> dict[str, bool]:
            q.add_note(ctx, run_id, body.text, body.author)
            return {"ok": True}

        return once(body, act)

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
            msg = await ws.receive_json()
            if msg.get("type") != "subscribe":
                await ws.send_json(
                    {
                        "type": "error",
                        "error": "first message must be {type: subscribe, after_sequence: N}",
                    }
                )
                await ws.close()
                return
            last = int(msg.get("after_sequence", 0))
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
