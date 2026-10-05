"""Shared JSON-shaping helpers for the CLI and API layers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic_core import to_jsonable_python


def to_jsonable(obj: Any) -> Any:
    """
    Recursively convert an object into a JSON-ready value.

    Pydantic models are dumped with ``model_dump(mode="json")``; dicts,
    lists, and tuples are walked recursively; JSON scalars are passed
    through unchanged; any other value is converted the way pydantic does
    (``to_jsonable_python``: a datetime becomes ISO 8601 text with ``Z`` for
    UTC, a path its text), and a value pydantic does not know becomes
    ``str(value)``. So the CLI's ``--json`` output matches the API.

    Parameters
    ----------
    obj : Any
        Value to convert. May be a pydantic ``BaseModel``, ``dict``,
        ``list``/``tuple``, or any JSON-serializable value.

    Returns
    -------
    Any
        A structure containing only JSON-serializable values.

    Examples
    --------
    >>> to_jsonable({"a": [1, 2]})
    {'a': [1, 2]}
    >>> from datetime import UTC, datetime
    >>> to_jsonable(datetime(2026, 10, 4, 12, 0, tzinfo=UTC))
    '2026-10-04T12:00:00Z'
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [to_jsonable(v) for v in obj]
    if obj is None or isinstance(obj, str | int | float):
        return obj
    return to_jsonable_python(obj, fallback=str)
