"""
A fake SMTP server on 127.0.0.1 built on aiosmtpd, with a trustme CA for TLS.

``mode`` picks plain SMTP, STARTTLS, or implicit TLS; ``user``/``password`` turn
on AUTH PLAIN/LOGIN; ``fail`` scripts a failure. ``connect_421`` and ``stall``
use a raw socket server instead of aiosmtpd.
The greeting hostname is explicit so startup never needs machine-name DNS.
"""

from __future__ import annotations

import contextlib
import socket
import ssl
import threading
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import Message
from typing import Any, Literal

import trustme
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

Mode = Literal["plain", "starttls", "ssl"]
Failure = Literal["auth", "data_451", "data_550", "connect_421", "stall"]


@dataclass
class Received:
    """One accepted message."""

    mail_from: str
    rcpt_tos: list[str]
    message: Message


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _Handler:
    def __init__(self, fake: FakeSmtp) -> None:
        self.fake = fake

    async def handle_RCPT(
        self, server: Any, session: Any, envelope: Any, address: str, options: Any
    ) -> str:
        """Accept a recipient unless its address has a scripted refusal."""
        if address in self.fake.refusals:
            code, reason = self.fake.refusals[address]
            return f"{code} {reason}"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        if self.fake.fail == "data_451":
            return "451 4.3.0 try again later"
        if self.fake.fail == "data_550":
            return "550 5.7.1 message rejected"
        raw = envelope.original_content or envelope.content
        parsed = message_from_bytes(raw, policy=policy.default)  # decoded headers
        self.fake.received.append(Received(envelope.mail_from, list(envelope.rcpt_tos), parsed))
        return "250 OK"


class _RawServer:
    """Greets with 421 and hangs up, or accepts and never says a word."""

    def __init__(self, port: int, fail: Failure) -> None:
        self.fail = fail
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.listen(8)
        self.sock.settimeout(0.1)
        self.stopping = threading.Event()
        self.held: list[socket.socket] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        while not self.stopping.is_set():
            try:
                conn, _ = self.sock.accept()
            except (TimeoutError, OSError):
                continue
            if self.fail == "connect_421":
                with contextlib.suppress(OSError):
                    conn.sendall(b"421 4.3.2 busy, try again later\r\n")
                conn.close()
            else:
                self.held.append(conn)

    def start(self) -> _RawServer:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.stopping.set()
        self.thread.join(2)
        for conn in self.held:
            conn.close()
        self.sock.close()


class FakeSmtp:
    """
    A fake SMTP server on a free 127.0.0.1 port.

    Parameters
    ----------
    mode : {"plain", "starttls", "ssl"}
        Plain SMTP, STARTTLS offered and required, or TLS from the first byte.
    user, password : str, optional
        Turn on AUTH with this login.
    fail : str, optional
        ``auth``, ``data_451``, ``data_550``, ``connect_421``, or ``stall``.
    refusals : dict of str to (int, str), optional
        Recipient addresses to refuse at RCPT with the supplied code and text.
        Mutate ``refusals`` on the fake between sends to model recovery.
    """

    def __init__(
        self,
        *,
        mode: Mode = "plain",
        user: str | None = None,
        password: str | None = None,
        fail: Failure | None = None,
        refusals: dict[str, tuple[int, str]] | None = None,
    ) -> None:
        self.mode = mode
        self.user = user
        self.password = password
        self.fail = fail
        self.refusals = dict(refusals or {})
        self.received: list[Received] = []
        self.port = _free_port()
        ca = trustme.CA()
        cert = ca.issue_cert("127.0.0.1", "localhost")
        self.server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        cert.configure_cert(self.server_context)
        self.client_context = ssl.create_default_context()
        ca.configure_trust(self.client_context)
        self._controller: Controller | None = None
        self._raw: _RawServer | None = None

    def _authenticate(
        self, server: Any, session: Any, envelope: Any, mechanism: str, auth_data: Any
    ) -> AuthResult:
        ok = (
            self.fail != "auth"
            and isinstance(auth_data, LoginPassword)
            and auth_data.login.decode() == self.user
            and auth_data.password.decode() == self.password
        )
        return AuthResult(success=ok, handled=False)

    def start(self) -> FakeSmtp:
        """Start serving; returns self."""
        if self.fail in ("connect_421", "stall"):
            self._raw = _RawServer(self.port, self.fail).start()
            return self
        options: dict[str, Any] = {}
        if self.user is not None:
            options["authenticator"] = self._authenticate
            options["auth_require_tls"] = self.mode == "starttls"
        if self.mode == "starttls":
            options["tls_context"] = self.server_context
            options["require_starttls"] = True
        self._controller = Controller(
            _Handler(self),
            hostname="127.0.0.1",
            server_hostname="localhost",
            port=self.port,
            ssl_context=self.server_context if self.mode == "ssl" else None,
            **options,
        )
        try:
            self._controller.start()
        except BaseException:
            # __enter__ failures never call __exit__. aiosmtpd may already
            # have a listener and thread even though its startup probe failed.
            self.stop()
            raise
        return self

    def stop(self) -> None:
        """Stop serving."""
        if self._controller is not None:
            self._controller.stop(no_assert=True)
            # On a bind failure aiosmtpd's thread returns before its normal
            # loop-close path. stop() joins that thread but leaves the loop open.
            if not self._controller.loop.is_closed():
                self._controller.loop.close()
            self._controller = None
        if self._raw is not None:
            self._raw.stop()
            self._raw = None

    def __enter__(self) -> FakeSmtp:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
