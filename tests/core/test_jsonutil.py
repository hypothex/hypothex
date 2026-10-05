from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from hypothex.core.jsonutil import to_jsonable


class _Inner(BaseModel):
    n: int


class _Stamped(BaseModel):
    created_at: datetime


class _Outer(BaseModel):
    inner: _Inner
    tags: list[str]


def test_to_jsonable_passes_through_plain_values() -> None:
    assert to_jsonable(1) == 1
    assert to_jsonable("x") == "x"
    assert to_jsonable(None) is None


def test_to_jsonable_dumps_nested_models_dicts_and_tuples() -> None:
    model = _Outer(inner=_Inner(n=1), tags=["a"])
    payload = {"model": model, "items": (model, 2), "plain": [1, 2]}
    assert to_jsonable(payload) == {
        "model": {"inner": {"n": 1}, "tags": ["a"]},
        "items": [{"inner": {"n": 1}, "tags": ["a"]}, 2],
        "plain": [1, 2],
    }


def test_to_jsonable_writes_datetimes_and_paths_like_the_api() -> None:
    created = datetime(2026, 10, 4, 12, 54, 26, 655792, tzinfo=UTC)
    model = _Stamped(created_at=created)
    out = to_jsonable({"created_at": created, "where": Path("/a/b"), "model": model})
    assert out == {
        "created_at": "2026-10-04T12:54:26.655792Z",
        "where": "/a/b",
        "model": {"created_at": "2026-10-04T12:54:26.655792Z"},
    }


def test_to_jsonable_turns_unknown_leaves_into_text() -> None:
    class Odd:
        def __str__(self) -> str:
            return "odd"

    assert to_jsonable([Odd(), 1.5, True]) == ["odd", 1.5, True]
