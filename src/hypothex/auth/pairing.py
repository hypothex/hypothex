"""Pairing links (secret in the ``#fragment``) and their QR code as plain text."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

import segno

from hypothex.core.errors import ConfigError

_FRAGMENT = re.compile(r"^(p_[0-9a-f]{12})\.([A-Za-z0-9_-]{43})$")
_HALF = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}


def pairing_url(base_url: str, offer_id: str, secret: str) -> str:
    """
    Build a pairing link; the secret stays in the fragment, which browsers never send.

    Parameters
    ----------
    base_url : str
        The hub's public URL (or its local URL).
    offer_id : str
        ``p_<12 hex>``.
    secret : str
        The offer's secret.

    Returns
    -------
    str
        ``<base_url>/pair#<offer_id>.<secret>``.

    Examples
    --------
    >>> pairing_url("http://127.0.0.1:7777/", "p_0123456789ab", "s")
    'http://127.0.0.1:7777/pair#p_0123456789ab.s'
    """
    return f"{base_url.rstrip('/')}/pair#{offer_id}.{secret}"


def parse_pairing_url(url: str) -> tuple[str, str, str]:
    """
    Split a pairing link into the hub URL, the offer id, and the secret.

    Parameters
    ----------
    url : str
        A link from ``hx pair``.

    Returns
    -------
    tuple of (str, str, str)
        ``(base_url, offer_id, secret)``.

    Raises
    ------
    ConfigError
        Not an ``http(s)://.../pair#p_<12 hex>.<43 chars>`` link.
    """
    bad = ConfigError("not a pairing link; copy the whole URL that hx pair printed")
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        raise bad from None
    match = _FRAGMENT.fullmatch(parts.fragment)
    try:
        valid_host = parts.hostname is not None and parts.port != 0
    except ValueError:
        raise bad from None
    if (
        parts.scheme not in ("http", "https")
        or not valid_host
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or any(char.isspace() or ord(char) < 32 for char in url.strip())
        or match is None
    ):
        raise bad
    path = parts.path.rstrip("/")
    if not path.endswith("/pair"):
        raise bad
    base = urlunsplit((parts.scheme, parts.netloc, path[: -len("/pair")], "", ""))
    return base.rstrip("/"), match.group(1), match.group(2)


def qr_text(url: str) -> str:
    """
    Render a QR code of ``url`` with Unicode half blocks (no ANSI codes).

    Two module rows make one text line; a two-module quiet zone surrounds it.
    Dark modules are drawn, so it scans best on a light terminal background.

    Parameters
    ----------
    url : str
        Text to encode.

    Returns
    -------
    str
        Lines of equal width, joined with ``\\n``.
    """
    matrix = [[bool(cell) for cell in row] for row in segno.make_qr(url, error="m").matrix]
    size = len(matrix)
    border = 2
    width = size + 2 * border
    padded = [[False] * width for _ in range(border)]
    padded += [[False] * border + row + [False] * border for row in matrix]
    padded += [[False] * width for _ in range(border)]
    if len(padded) % 2:
        padded.append([False] * width)
    lines = []
    for top, bottom in zip(padded[0::2], padded[1::2], strict=True):
        lines.append("".join(_HALF[(a, b)] for a, b in zip(top, bottom, strict=True)))
    return "\n".join(lines)
