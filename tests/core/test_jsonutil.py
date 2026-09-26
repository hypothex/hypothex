from pydantic import BaseModel

from hypothex.core.jsonutil import to_jsonable


class _Inner(BaseModel):
    n: int


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
