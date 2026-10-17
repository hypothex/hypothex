"""Slack and SMTP delivery; every failure leaves as an error class, never a secret."""

from __future__ import annotations

import ipaddress
import logging
import math
import smtplib
import ssl
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from hypothex.core.errors import HypothexError
from hypothex.core.settings import EmailSettings, is_loopback_host


class ChannelError(HypothexError):
    """
    A delivery failed; the message is only the error class (no URL, no login).

    Parameters
    ----------
    error_class : str
        ``http_429``, ``smtp_535``, ``timeout``, ``unset:<VAR>``, ...
    permanent : bool
        True when retrying cannot help.
    retry_after : float, optional
        Seconds the server asked to wait (Slack ``Retry-After``).
    """

    def __init__(
        self, error_class: str, *, permanent: bool, retry_after: float | None = None
    ) -> None:
        super().__init__(error_class)
        self.error_class = error_class
        self.permanent = permanent
        self.retry_after = retry_after


def redact(text: str, secrets: Iterable[SecretStr | str | None]) -> str:
    """
    Replace every secret value, and the path of a webhook URL, with ``***``.

    Parameters
    ----------
    text : str
        Any text that may quote a secret.
    secrets : iterable of SecretStr, str, or None
        Values to hide; None and empty values are skipped.

    Returns
    -------
    str

    Examples
    --------
    >>> redact("pw=hunter2", ["hunter2"])
    'pw=***'
    """
    values: set[str] = set()
    for secret in secrets:
        if secret is None:
            continue
        value = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        if not value:
            continue
        values.add(value)
        try:
            parts = urlsplit(value)
        except ValueError:
            continue
        if parts.scheme in ("http", "https") and len(parts.path) > 1:
            values.add(parts.path)
            if parts.path.startswith("/services/"):
                values.add(parts.path.rsplit("/", 1)[-1])
    out = text
    for value in sorted(values, key=len, reverse=True):
        if value:
            out = out.replace(value, "***")
    return out


class _DropSecret(logging.Filter):
    """Drop log records that quote a secret (httpx logs every request URL at INFO)."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self.secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep a record unless its message holds the secret."""
        return self.secret not in record.getMessage()


@contextmanager
def _quiet(secret: str) -> Iterator[None]:
    """Keep ``secret`` out of the ``httpx`` and ``httpcore`` logs for one call."""
    drop = _DropSecret(secret)
    # Logger filters are not inherited by children. Handler filters also cover
    # httpcore's dynamically created child loggers and propagated DEBUG records.
    names = {"httpx", "httpcore"} | {
        name for name in logging.root.manager.loggerDict if name.startswith(("httpx.", "httpcore."))
    }
    loggers = [logging.getLogger(name) for name in names]
    handlers = {
        handler for logger in [logging.getLogger(), *loggers] for handler in logger.handlers
    }
    targets = [*loggers, *handlers]
    for target in targets:
        target.addFilter(drop)
    try:
        yield
    finally:
        for target in targets:
            target.removeFilter(drop)


def _retry_after(header: str | None) -> float | None:
    try:
        value = float(header) if header is not None else None
        return value if value is not None and math.isfinite(value) and value >= 0 else None
    except ValueError:
        return None


def send_slack(
    webhook: SecretStr,
    payload: dict[str, Any],
    *,
    timeout: float = 10,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """
    POST a payload to a Slack incoming webhook.

    Parameters
    ----------
    webhook : SecretStr
        The webhook URL; ``https://`` unless the host is loopback.
    payload : dict
        JSON body (``render_slack``).
    timeout : float
        Seconds.
    transport : httpx.BaseTransport, optional
        For tests.

    Raises
    ------
    ChannelError
        ``insecure_webhook``/``bad_webhook`` (permanent, nothing sent),
        ``http_429``/``http_5xx``/``timeout``/``transport`` (retryable), other
        ``http_4xx`` (permanent).
    """
    url = webhook.get_secret_value()
    try:
        parts = urlsplit(url)
        if not parts.hostname or parts.username or parts.password:
            raise ValueError("invalid webhook authority")
        _ = parts.port
    except ValueError:
        raise ChannelError("bad_webhook", permanent=True) from None
    local = parts.scheme == "http" and is_loopback_host(parts.hostname or "")
    if parts.scheme != "https" and not local:
        raise ChannelError("insecure_webhook", permanent=True) from None
    try:
        with (
            _quiet(parts.path or url),
            httpx.Client(timeout=timeout, transport=transport, follow_redirects=False) as client,
        ):
            resp = client.post(url, json=payload)
    except httpx.TimeoutException:
        raise ChannelError("timeout", permanent=False) from None
    except (httpx.HTTPError, httpx.InvalidURL):
        raise ChannelError("transport", permanent=False) from None
    if 200 <= resp.status_code < 300:
        return
    error = f"http_{resp.status_code}"
    if resp.status_code == 429 or resp.status_code >= 500:
        retry = _retry_after(resp.headers.get("Retry-After"))
        raise ChannelError(error, permanent=False, retry_after=retry) from None
    raise ChannelError(error, permanent=True) from None


def _smtp_address_literal(address: str) -> str:
    """Render a numeric local address for EHLO without machine-name DNS."""
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        raise OSError("invalid SMTP socket address") from None
    prefix = "IPv6:" if parsed.version == 6 else ""
    return f"[{prefix}{parsed.compressed}]"


def send_email(
    settings: EmailSettings,
    password: SecretStr | None,
    message: EmailMessage,
    *,
    ssl_context: ssl.SSLContext | None = None,
) -> None:
    """
    Send one email over SMTP (STARTTLS, implicit TLS, or plain on loopback).

    The EHLO identity uses the connected socket's numeric local address, so
    discovering the machine's hostname cannot block outside the socket timeout.
    Remote hostname resolution and TLS verification still use ``settings.host``.

    Parameters
    ----------
    settings : EmailSettings
        Server, security, login name.
    password : SecretStr or None
        The SMTP password (needed when ``settings.username`` is set).
    message : EmailMessage
        The message (``render_email``).
    ssl_context : ssl.SSLContext, optional
        Default: the system trust store.

    Raises
    ------
    ChannelError
        ``smtp_<code>`` (5xx and auth permanent, 4xx retryable),
        ``smtp_no_starttls`` and ``tls`` (permanent), ``timeout`` and
        ``connection`` (retryable). Any recipient refusal, including partial
        delivery, is a failure. Mixed 4xx/5xx refusals remain retryable so the
        temporary failures get another attempt. Retries resend the whole
        message and may duplicate delivery to already accepted recipients.
    """
    context = ssl_context or ssl.create_default_context()
    try:
        if settings.security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.host,
                settings.port,
                local_hostname="[127.0.0.1]",
                timeout=settings.timeout,
                context=context,
            )
        else:
            client = smtplib.SMTP(
                settings.host,
                settings.port,
                local_hostname="[127.0.0.1]",
                timeout=settings.timeout,
            )
        with client:
            # smtplib otherwise calls getfqdn/gethostbyname outside its socket
            # timeout. Replace the constructor placeholder before any greeting
            # with the connected socket's RFC 5321 address literal.
            if client.sock is None:
                raise OSError("SMTP socket is closed")
            client.local_hostname = _smtp_address_literal(client.sock.getsockname()[0])
            if settings.security == "starttls":
                client.starttls(context=context)
            if settings.username:
                secret = password.get_secret_value() if password is not None else ""
                client.login(settings.username, secret)
            refused = client.send_message(message)
            if refused:
                # smtplib raises only when every recipient was refused. A
                # nonempty return mapping means partial delivery, not success.
                raise smtplib.SMTPRecipientsRefused(refused)
    except smtplib.SMTPAuthenticationError as exc:
        raise ChannelError(f"smtp_{exc.smtp_code}", permanent=True) from None
    except smtplib.SMTPRecipientsRefused as exc:
        codes = sorted({code for code, _ in exc.recipients.values()})
        # 4xx takes precedence over 5xx in a mixed batch: bounded retries must
        # still reach temporarily refused recipients. Never retain addresses
        # or server reply text in the public error or notification journal.
        code = codes[0] if codes else 550
        raise ChannelError(f"smtp_{code}", permanent=code >= 500) from None
    except smtplib.SMTPResponseException as exc:
        raise ChannelError(f"smtp_{exc.smtp_code}", permanent=exc.smtp_code >= 500) from None
    except smtplib.SMTPNotSupportedError:
        raise ChannelError("smtp_no_starttls", permanent=True) from None
    except smtplib.SMTPServerDisconnected as exc:
        # smtplib reports a read timeout as "Connection unexpectedly closed: timed out"
        error = "timeout" if "timed out" in str(exc) else "connection"
        raise ChannelError(error, permanent=False) from None
    except TimeoutError:
        raise ChannelError("timeout", permanent=False) from None
    except ssl.SSLError:
        raise ChannelError("tls", permanent=True) from None
    except (smtplib.SMTPException, OSError):
        raise ChannelError("connection", permanent=False) from None
