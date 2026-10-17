"""
A fake Slack incoming webhook on 127.0.0.1: records requests and plays scripted replies.

Examples
--------
>>> with FakeWebhook([Reply(429, retry_after=7)]) as hook:  # doctest: +SKIP
...     httpx.post(hook.url, json={"text": "hi"}).status_code
429
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Reply:
    """One scripted answer: status, optional ``Retry-After``, and a stall before it."""

    status: int = 200
    retry_after: float | None = None
    stall: float = 0.0
    body: str = "ok"


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Stay quiet when a client gave up (a timeout test)."""


class FakeWebhook:
    """
    A webhook receiver; replies follow ``script``, then 200.

    Parameters
    ----------
    script : list of Reply, optional
        Replies for the first requests, in order.
    """

    def __init__(self, script: list[Reply] | None = None) -> None:
        self.script: list[Reply] = list(script or [])
        self.requests: list[dict[str, Any]] = []
        self.secret = "SECRETHOOK" + secrets.token_hex(6)
        self._lock = threading.Lock()
        self.server = _Server(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        """The webhook URL; its path holds the secret, as Slack's does."""
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}/services/T000/B000/{self.secret}"

    def queue(self, *replies: Reply) -> None:
        """Add replies to the end of the script."""
        with self._lock:
            self.script.extend(replies)

    def _next(self) -> Reply:
        with self._lock:
            return self.script.pop(0) if self.script else Reply()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                reply = fake._next()
                with fake._lock:
                    fake.requests.append(
                        {
                            "path": self.path,
                            "body": json.loads(raw or b"null"),
                            "headers": dict(self.headers),
                        }
                    )
                if reply.stall:
                    time.sleep(reply.stall)
                body = reply.body.encode()
                self.send_response(reply.status)
                if reply.retry_after is not None:
                    self.send_header("Retry-After", str(int(reply.retry_after)))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        return Handler

    def start(self) -> FakeWebhook:
        """Start serving; returns self."""
        self.thread.start()
        return self

    def stop(self) -> None:
        """Stop serving and close the socket."""
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> FakeWebhook:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
