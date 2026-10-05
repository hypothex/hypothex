"""Shared credential-safe HTTP diagnostics for remote and local hub clients."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from hypothex.core.tokens import redact_bearer_token


class TokenSafeHTTPTransport(httpx.HTTPTransport):
    """
    Keep HTTP diagnostics credential-safe without changing shared loggers.

    Parameters
    ----------
    token : str or None
        Already validated bearer selected for this transport; redacted from
        diagnostic output, without changing response bodies or headers.
    unix_socket : Path or None
        Optional private local socket. None uses ordinary direct HTTP transport.
    """

    def __init__(self, token: str | None, *, unix_socket: Path | None) -> None:
        super().__init__(uds=str(unix_socket) if unix_socket is not None else None, trust_env=False)
        self._token = token

    def _trace(self, name: str, info: dict[str, Any]) -> None:
        # httpcore calls this extension before formatting its debug message.
        # Completion/failure dictionaries are fresh diagnostic values, unlike
        # started kwargs that can also be used by the actual network operation.
        if self._token and name.endswith((".complete", ".failed")):
            for key, value in info.items():
                rendered = repr(value)
                if self._token in rendered:
                    info[key] = redact_bearer_token(rendered, self._token)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """
        Send the original request and redact only diagnostic trace/status text.

        Parameters
        ----------
        request : httpx.Request
            Request with the caller's already selected headers.

        Returns
        -------
        httpx.Response
            Original response body and headers; diagnostic reason text is redacted.
        """
        request.extensions["trace"] = self._trace
        response = super().handle_request(request)
        # HTTPX logs the peer's reason phrase at INFO after transport returns.
        # This diagnostic status text has no API semantics; preserve body and
        # every response header, including any reflected credential, unchanged.
        reason = response.extensions.get("reason_phrase")
        if self._token and isinstance(reason, bytes):
            response.extensions["reason_phrase"] = reason.replace(
                self._token.encode("ascii"), b"[redacted]"
            )
        return response
