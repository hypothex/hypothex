"""Run metric functions inside a project's own Python environment.

Hypothex invokes this module as::

    python -m hypothex.eval_worker {evaluate|describe} --request REQ.json --out OUT.json

It must be importable in the project's environment, so it only uses the standard
library and light ``hypothex`` modules.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from hypothex.core.fsutil import atomic_write_text, read_jsonl
from hypothex.metrics import Example, normalize_result


def import_fn(ref: str) -> Any:
    """
    Import ``module:function``.

    Parameters
    ----------
    ref : str
        Reference of the form ``module:function``.

    Returns
    -------
    Any
        The imported attribute.
    """
    module_name, _, attr = ref.partition(":")
    return getattr(importlib.import_module(module_name), attr)


def source_hash(fn: Any) -> str | None:
    """
    Return a short sha256 of the function's source.

    Parameters
    ----------
    fn : Any
        Callable to hash.

    Returns
    -------
    str or None
        ``sha256:<hex>`` digest, or None if the source is unavailable.
    """
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return None
    return "sha256:" + hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]


def load_examples(run_dir: Path, dataset: dict[str, Any] | None) -> list[Example]:
    """
    Load predictions and join references from the dataset when rows lack them.

    Parameters
    ----------
    run_dir : Path
        Run directory containing ``predictions/predictions.jsonl``.
    dataset : dict or None
        ``{"path", "id_field", "reference_field"}`` for the task's dataset split.

    Returns
    -------
    list of Example

    Raises
    ------
    FileNotFoundError
        If ``predictions/predictions.jsonl`` is missing.
    """
    path = run_dir / "predictions" / "predictions.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"no predictions at {path}")
    rows = [r for r in read_jsonl(path) if "id" in r]
    refs: dict[str, Any] = {}
    if dataset and any("reference" not in r for r in rows):
        id_field, ref_field = dataset["id_field"], dataset["reference_field"]
        for row in read_jsonl(Path(dataset["path"])):
            if id_field in row:
                refs[str(row[id_field])] = row.get(ref_field)
    return [
        Example(
            id=str(r["id"]),
            prediction=r.get("prediction"),
            reference=r["reference"] if "reference" in r else refs.get(str(r["id"])),
            meta=r.get("meta") or {},
        )
        for r in rows
    ]


def evaluate(request: dict[str, Any]) -> dict[str, Any]:
    """
    Run each requested metric; one metric failing does not stop the others.

    Parameters
    ----------
    request : dict
        ``{"repo", "run_dir", "dataset", "metrics": [{"name","version","fn","params"}]}``.

    Returns
    -------
    dict
        ``{"n_examples": int, "results": [{"name","version","values","error","source_hash"}]}``.
    """
    sys.path.insert(0, request["repo"])
    run_dir = Path(request["run_dir"])
    examples = load_examples(run_dir, request.get("dataset"))
    results: list[dict[str, Any]] = []
    for m in request["metrics"]:
        entry: dict[str, Any] = {
            "name": m["name"],
            "version": m["version"],
            "values": {},
            "error": None,
            "source_hash": None,
        }
        try:
            fn = import_fn(m["fn"])
            entry["source_hash"] = source_hash(fn)
            result = normalize_result(fn(examples, **m.get("params", {})))
            entry["values"] = result.values
            if result.per_example:
                out = run_dir / "predictions" / f"scores.{m['name']}@{m['version']}.jsonl"
                atomic_write_text(
                    out,
                    "".join(
                        json.dumps({"id": k, **v}, default=str) + "\n"
                        for k, v in result.per_example.items()
                    ),
                )
        except Exception:
            entry["error"] = traceback.format_exc(limit=5)
        results.append(entry)
    return {"n_examples": len(examples), "results": results}


def describe(request: dict[str, Any]) -> dict[str, Any]:
    """
    Check that each metric imports and return its source hash.

    Parameters
    ----------
    request : dict
        ``{"repo", "metrics": [{"name","fn"}]}``.

    Returns
    -------
    dict
        ``{"metrics": {name: {"importable","error","source_hash"}}}``.
    """
    sys.path.insert(0, request["repo"])
    out: dict[str, Any] = {}
    for m in request["metrics"]:
        try:
            fn = import_fn(m["fn"])
            out[m["name"]] = {
                "importable": True,
                "error": None,
                "source_hash": source_hash(fn),
            }
        except Exception as exc:
            out[m["name"]] = {
                "importable": False,
                "error": f"{type(exc).__name__}: {exc}",
                "source_hash": None,
            }
    return {"metrics": out}


def main(argv: list[str] | None = None) -> int:
    """
    Command-line entry point; writes the result JSON to ``--out``.

    Parameters
    ----------
    argv : list of str, optional
        Arguments to parse instead of ``sys.argv``.

    Returns
    -------
    int
        ``0`` on success, ``2`` if a fatal (unhandled) error occurred.
    """
    parser = argparse.ArgumentParser(prog="hypothex.eval_worker")
    parser.add_argument("action", choices=["evaluate", "describe"])
    parser.add_argument("--request", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    try:
        result = evaluate(request) if args.action == "evaluate" else describe(request)
    except Exception:
        result = {"fatal": traceback.format_exc(limit=5)}
    Path(args.out).write_text(json.dumps(result, default=str), encoding="utf-8")
    return 2 if "fatal" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
