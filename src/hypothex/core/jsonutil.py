"""Shared JSON-shaping helpers for the CLI and API layers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def to_jsonable(obj: Any) -> Any:
    """
    Recursively convert an object into a JSON-ready value.

    Pydantic models are dumped with ``model_dump(mode="json")``; dicts,
    lists, and tuples are walked recursively; everything else is passed
    through unchanged.

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
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [to_jsonable(v) for v in obj]
    return obj
