"""Strict bearer syntax and non-secret diagnostics."""

import pytest

from hypothex.core.errors import ConfigError
from hypothex.core.tokens import redact_bearer_token, validate_bearer_token


@pytest.mark.parametrize("token", ["abc", "AZaz09-._~+/==", "a" * 4096])
def test_valid_bearer(token: str) -> None:
    assert validate_bearer_token(token) == token


@pytest.mark.parametrize(
    "token", ["", " ", "secret\r\nheader", "secret\t", "secreté", "a=b", "=", "a" * 4097, None, 42]
)
def test_invalid_bearer_is_not_disclosed(token: object) -> None:
    with pytest.raises(ConfigError, match="invalid bearer token") as error:
        validate_bearer_token(token)
    assert "secret" not in str(error.value)


def test_redaction() -> None:
    assert redact_bearer_token("Bearer secret; secret", "secret") == "Bearer [redacted]; [redacted]"
    assert redact_bearer_token("ordinary", None) == "ordinary"
