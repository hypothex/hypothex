"""
HTTP and WebSocket client for one env server (spec 5.2, 5.3, 5.5).

The hub talks to every host through this class: snapshots and commands over HTTP,
run files over ``GET /api/v1/runs/{id}/files/{path}``, and the event stream over the
``/api/v1/ws`` WebSocket. The base URL is the local end of an SSH tunnel
(``http://127.0.0.1:<port>``) or, for ``route: url`` hosts, a direct URL.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from hypothex.core.environment import EnvironmentDescriptor
from hypothex.core.errors import HypothexError

DIR_HEADER = "X-Hypothex-Dir"
SIZE_HEADER = "X-Hypothex-Size"
FILE_CHUNK_BYTES = 64 * 1024


class EnvRequestError(HypothexError):
    """
    An env server answered a request with an error.

    Parameters
    ----------
    message : str
        Human-readable reason, including the server's own error text.
    status_code : int, optional
        HTTP status of the answer; ``None`` when there was no answer.
    error_type : str, optional
        The server's error class name (the ``type`` field of its JSON error).
    """

    def __init__(
        self, message: str, *, status_code: int | None = None, error_type: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


class EnvUnreachableError(EnvRequestError):
    """The env server could not be reached, timed out, or dropped the connection."""


def _error_from(resp: httpx.Response, what: str) -> EnvRequestError:
    """
    Build an :class:`EnvRequestError` from an error response.

    Parameters
    ----------
    resp : httpx.Response
        A response with a 4xx or 5xx status; its body must already be read.
    what : str
        Short request description, e.g. ``GET /api/v1/runs``.

    Returns
    -------
    EnvRequestError
    """
    error_type: str | None = None
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and "error" in body:
        detail = str(body["error"])
        error_type = str(body["type"]) if body.get("type") else None
    elif isinstance(body, dict) and "detail" in body:
        detail = json.dumps(body["detail"])
    else:
        detail = resp.text[:500]
    return EnvRequestError(
        f"{what} -> {resp.status_code}: {detail}",
        status_code=resp.status_code,
        error_type=error_type,
    )


class RemoteFile(BaseModel):
    """
    One file in a run-folder listing; ``path`` is relative to the run folder.

    ``mtime_ns`` is the file's modification time on the host (0 when unknown).
    """

    path: str
    size: int
    mtime_ns: int = 0


def _local_parts(entry: str, base: PurePosixPath) -> tuple[str, ...] | None:
    """
    Return the parts of ``entry`` below ``base``, or ``None`` when it is not safely below.

    A listing comes from another machine, so a bad entry (absolute, ``..``, or outside
    the listed folder) must never pick where the hub writes.

    Parameters
    ----------
    entry : str
        Listed path, relative to the run folder.
    base : PurePosixPath
        The listed folder, relative to the run folder.

    Returns
    -------
    tuple of str or None
    """
    path = PurePosixPath(entry)
    if path.is_absolute() or ".." in path.parts or "\x00" in entry:
        return None
    if path.parts[: len(base.parts)] != base.parts or len(path.parts) <= len(base.parts):
        return None
    return path.parts[len(base.parts) :]


class EnvClient:
    """
    Client for one env server's HTTP and WebSocket API.

    Parameters
    ----------
    base_url : str
        Server root, e.g. ``http://127.0.0.1:43117``.
    timeout : float
        Seconds for connect, read, and the WebSocket handshake.
    token : str, optional
        The env server's bearer token (``ServerInfo.token``); sent as
        ``Authorization: Bearer <token>`` on every request and the WebSocket.

    Examples
    --------
    >>> client = EnvClient("http://127.0.0.1:7777/", token="t0k")
    >>> client.base_url, client.auth_headers()
    ('http://127.0.0.1:7777', {'Authorization': 'Bearer t0k'})
    >>> client.close()
    """

    def __init__(self, base_url: str, *, timeout: float = 10, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token
        self._http = httpx.Client(
            base_url=self.base_url, timeout=timeout, headers=self.auth_headers()
        )

    def auth_headers(self) -> dict[str, str]:
        """
        Return the ``Authorization`` header for this server ({} without a token).

        Returns
        -------
        dict of str to str
        """
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def close(self) -> None:
        """Close the HTTP connection pool."""
        self._http.close()

    def __enter__(self) -> EnvClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _unreachable(self, exc: Exception) -> EnvUnreachableError:
        reason = str(exc) or type(exc).__name__
        return EnvUnreachableError(f"cannot reach {self.base_url}: {reason}")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Send one request and return its decoded JSON body."""
        what = f"{method} {path}"
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise self._unreachable(exc) from exc
        if resp.is_error:
            raise _error_from(resp, what)
        try:
            return resp.json()
        except ValueError as exc:
            raise EnvRequestError(
                f"{what} -> {resp.status_code}: answer is not JSON", status_code=resp.status_code
            ) from exc

    def _file_url(self, run_id: str, rel_path: str) -> str:
        return f"/api/v1/runs/{quote(run_id, safe='')}/files/{quote(rel_path, safe='/')}"

    def descriptor(self) -> EnvironmentDescriptor:
        """
        Fetch the server's environment descriptor.

        Returns
        -------
        EnvironmentDescriptor

        Raises
        ------
        EnvUnreachableError
            The server cannot be reached.
        EnvRequestError
            The server answered with an error or an invalid descriptor.
        """
        body = self._request("GET", "/.well-known/hypothex/environment")
        try:
            return EnvironmentDescriptor.model_validate(body)
        except ValidationError as exc:
            raise EnvRequestError(f"{self.base_url} sent an invalid descriptor: {exc}") from exc

    def get_json(self, path: str, **params: Any) -> Any:
        """
        ``GET`` a JSON endpoint.

        Parameters
        ----------
        path : str
            Path on the server, e.g. ``/api/v1/runs``.
        **params : Any
            Query parameters; ``None`` values are left out, lists repeat the key.

        Returns
        -------
        Any
            Decoded JSON body.

        Raises
        ------
        EnvUnreachableError
            The server cannot be reached.
        EnvRequestError
            The server answered with a 4xx/5xx status (``status_code`` and
            ``error_type`` copy the server's answer).
        """
        query = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", path, params=query)

    def post_json(self, path: str, body: dict[str, Any]) -> Any:
        """
        ``POST`` a JSON body to an endpoint.

        Parameters
        ----------
        path : str
            Path on the server, e.g. ``/api/v1/runs/r1/stop``.
        body : dict
            JSON body; keep the caller's ``command_id`` so retries stay idempotent.

        Returns
        -------
        Any
            Decoded JSON body.

        Raises
        ------
        EnvUnreachableError
            The server cannot be reached.
        EnvRequestError
            The server answered with a 4xx/5xx status.
        """
        return self._request("POST", path, json=body)

    def list_files(self, run_id: str, rel_dir: str = "") -> list[RemoteFile]:
        """
        List the files under a folder of a run (recursive, hidden files left out).

        Parameters
        ----------
        run_id : str
            Run id.
        rel_dir : str
            Folder relative to the run folder; ``""`` lists the whole run.

        Returns
        -------
        list of RemoteFile
            Paths relative to the run folder, sorted.

        Raises
        ------
        EnvRequestError
            The run or folder does not exist (``status_code == 404``) or
            ``rel_dir`` is a file.
        """
        url = self._file_url(run_id, rel_dir)
        try:
            resp = self._http.get(url, params={"max_bytes": 0})
        except httpx.TransportError as exc:
            raise self._unreachable(exc) from exc
        if resp.status_code == 413 or (not resp.is_error and not resp.headers.get(DIR_HEADER)):
            raise EnvRequestError(f"{rel_dir!r} of run {run_id} is a file, not a folder")
        if resp.is_error:
            raise _error_from(resp, f"GET {url}")
        return [RemoteFile.model_validate(item) for item in resp.json()]

    def fetch_file(
        self,
        run_id: str,
        rel_path: str,
        dest: Path,
        *,
        max_bytes: int,
        tail: bool = False,
    ) -> bool:
        """
        Copy one run file (or every file of a run folder) to ``dest``.

        A file is written to a temporary name next to ``dest`` and renamed when
        complete, so readers never see half a file. For a folder, ``dest`` becomes a
        folder and each listed file is fetched under it with the same limit; files
        over the limit are skipped.

        Parameters
        ----------
        run_id : str
            Run id.
        rel_path : str
            Path relative to the run folder, e.g. ``scores.jsonl`` or ``predictions``.
        dest : Path
            Local file (or folder) to write.
        max_bytes : int
            Largest file to copy.
        tail : bool
            For a file over ``max_bytes``, copy its last ``max_bytes`` bytes instead
            of skipping it (for log tails).

        Returns
        -------
        bool
            ``False`` when skipped: missing, or over ``max_bytes`` without ``tail``.
            ``True`` when the file, or the folder listing, was fetched.

        Raises
        ------
        EnvUnreachableError
            The connection failed or dropped mid-transfer (``dest`` is unchanged).
        EnvRequestError
            The server answered with an error other than 404/413.

        Examples
        --------
        >>> with EnvClient(url) as c:  # doctest: +SKIP
        ...     c.fetch_file("r1", "run.yaml", mirror / "run.yaml", max_bytes=200 * 2**20)
        True
        """
        url = self._file_url(run_id, rel_path)
        params: dict[str, Any] = {"max_bytes": max_bytes, "tail": tail}
        try:
            with self._http.stream("GET", url, params=params) as resp:
                if resp.status_code in (404, 413):
                    return False
                if resp.is_error:
                    resp.read()
                    raise _error_from(resp, f"GET {url}")
                if not resp.headers.get(DIR_HEADER):
                    return self._write_stream(resp, dest, max_bytes)
                listing = [RemoteFile.model_validate(item) for item in json.loads(resp.read())]
        except httpx.TransportError as exc:
            raise self._unreachable(exc) from exc
        base = PurePosixPath(rel_path)
        for entry in listing:
            parts = _local_parts(entry.path, base)
            if parts is None or (entry.size > max_bytes and not tail):
                continue
            self.fetch_file(
                run_id, entry.path, dest.joinpath(*parts), max_bytes=max_bytes, tail=tail
            )
        return True

    @staticmethod
    def _write_stream(resp: httpx.Response, dest: Path, max_bytes: int) -> bool:
        """Stream ``resp`` into ``dest`` atomically; ``False`` if it exceeds ``max_bytes``."""
        declared = resp.headers.get("content-length")
        if declared is not None and int(declared) > max_bytes:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".part", dir=dest.parent)
        done = False
        try:
            with os.fdopen(fd, "wb") as fh:
                written = 0
                for chunk in resp.iter_bytes(FILE_CHUNK_BYTES):
                    written += len(chunk)
                    if written > max_bytes:
                        return False
                    fh.write(chunk)
            os.replace(tmp_name, dest)
            done = True
            return True
        finally:
            if not done:
                Path(tmp_name).unlink(missing_ok=True)
