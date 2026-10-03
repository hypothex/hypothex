"""
HTTP and WebSocket client for one env server (spec 5.2, 5.3, 5.5).

The hub talks to every host through this class: snapshots and commands over HTTP,
run files over ``GET /api/v1/runs/{id}/files/{path}``, and the event stream over the
``/api/v1/ws`` WebSocket. The base URL is the local end of an SSH tunnel
(``http://127.0.0.1:<port>``) or, for ``route: url`` hosts, a direct URL.
"""

from __future__ import annotations

import json
from types import TracebackType
from typing import Any

import httpx
from pydantic import ValidationError

from hypothex.core.environment import EnvironmentDescriptor
from hypothex.core.errors import HypothexError

DIR_HEADER = "X-Hypothex-Dir"
SIZE_HEADER = "X-Hypothex-Size"


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
