import pytest

from hypothex.api.security import allowed_hosts, origin_allowed


@pytest.mark.parametrize(
    ("bind", "expected"),
    [
        (None, ["127.0.0.1", "localhost", "[::1]"]),
        ("127.0.0.1", ["127.0.0.1", "localhost", "[::1]"]),
        ("0.0.0.0", ["127.0.0.1", "localhost", "[::1]"]),
        ("::", ["127.0.0.1", "localhost", "[::1]"]),
        ("10.0.0.5", ["127.0.0.1", "localhost", "[::1]", "10.0.0.5"]),
        ("fe80::1", ["127.0.0.1", "localhost", "[::1]", "[fe80::1]"]),
    ],
)
def test_allowed_hosts(bind: str | None, expected: list[str]) -> None:
    assert allowed_hosts(bind) == expected


@pytest.mark.parametrize(
    ("origin", "ok"),
    [
        ("http://127.0.0.1:7777", True),
        ("http://localhost:5173", True),
        ("https://localhost", True),
        ("http://[::1]:7777", True),
        ("http://attacker.example", False),
        ("http://127.0.0.1.attacker.example", False),
        ("null", False),
        ("file://", False),
        ("http://[bad", False),
    ],
)
def test_origin_allowed(origin: str, ok: bool) -> None:
    assert origin_allowed(origin, allowed_hosts()) is ok
