"""Bearer-token syntax and defense-in-depth diagnostic redaction."""

import re

from hypothex.core.errors import ConfigError

MAX_BEARER_TOKEN_LENGTH = 4096
_BEARER = re.compile(r"[A-Za-z0-9._~+/-]+=*", re.ASCII)


def validate_bearer_token(token: object) -> str:
    """
    Validate one explicitly supplied RFC 6750 bearer value without echoing it.

    Parameters
    ----------
    token : object
        Raw configuration value; absence must be handled by the caller.

    Returns
    -------
    str
        The unchanged valid value.

    Raises
    ------
    ConfigError
        The value is empty, too long, non-ASCII, or has invalid syntax.

    Examples
    --------
    >>> validate_bearer_token("example-token")
    'example-token'
    """
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= MAX_BEARER_TOKEN_LENGTH
        or _BEARER.fullmatch(token) is None
    ):
        raise ConfigError("invalid bearer token: expected 1..4096 ASCII bearer characters")
    return token


def redact_bearer_token(text: str, token: str | None) -> str:
    """
    Remove a known token from a diagnostic.

    Parameters
    ----------
    text : str
        Diagnostic from an untrusted peer.
    token : str or None
        Known session credential.

    Returns
    -------
    str
        Text with every exact occurrence replaced.

    Examples
    --------
    >>> redact_bearer_token("Bearer abc", "abc")
    'Bearer [redacted]'
    """
    return text.replace(token, "[redacted]") if token else text
