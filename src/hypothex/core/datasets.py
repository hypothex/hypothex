"""Dataset fingerprints, drift detection, and split-overlap checks."""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import xxhash
from pydantic import BaseModel

from hypothex.core.config import DatasetSpec
from hypothex.core.fsutil import atomic_write_text
from hypothex.core.ids import utcnow
from hypothex.core.records import DatasetRef, RunRecord

FULL_HASH_LIMIT = 2 * 1024**3
SAMPLE_BYTES = 4 * 1024**2
_CHUNK = 1024 * 1024


class Fingerprint(BaseModel):
    """Content fingerprint of a file or directory."""

    hash: str
    mode: Literal["full", "manifest"]
    size: int


def _hash_file_full(path: Path) -> str:
    h = xxhash.xxh3_128()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _hash_file_sample(path: Path, size: int) -> str:
    h = xxhash.xxh3_128()
    with path.open("rb") as fh:
        h.update(fh.read(SAMPLE_BYTES))
        if size > SAMPLE_BYTES:
            fh.seek(max(size - SAMPLE_BYTES, SAMPLE_BYTES))
            h.update(fh.read(SAMPLE_BYTES))
    return h.hexdigest()


def fingerprint(path: Path, full_limit: int = FULL_HASH_LIMIT) -> Fingerprint:
    """
    Fingerprint a dataset file or directory.

    Files up to ``full_limit`` bytes get a full content hash. Larger files and
    directories get a manifest hash over (relative path, size, mtime, head+tail sample).

    Parameters
    ----------
    path : Path
        File or directory.
    full_limit : int
        Size limit for full hashing.

    Returns
    -------
    Fingerprint

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.

    Examples
    --------
    >>> import tempfile, pathlib
    >>> p = pathlib.Path(tempfile.mkdtemp()) / "x.txt"; _ = p.write_text("hi")
    >>> fingerprint(p).mode
    'full'
    """
    if path.is_file():
        size = path.stat().st_size
        if size <= full_limit:
            return Fingerprint(hash="xxh3:" + _hash_file_full(path), mode="full", size=size)
        files, base = [path], path.parent
    elif path.is_dir():
        files, base = sorted(p for p in path.rglob("*") if p.is_file()), path
    else:
        raise FileNotFoundError(path)
    h = xxhash.xxh3_128()
    total = 0
    for f in files:
        st = f.stat()
        total += st.st_size
        rel = f.relative_to(base).as_posix()
        sample = _hash_file_sample(f, st.st_size)
        h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\0{sample}\n".encode())
    return Fingerprint(hash="xxh3m:" + h.hexdigest(), mode="manifest", size=total)


class FingerprintCache:
    """
    Cache file fingerprints keyed by (path, size, mtime).

    Directories are always re-fingerprinted (their manifest hash is cheap).

    Parameters
    ----------
    path : Path
        JSON cache file.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict] = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        )

    def fingerprint(self, path: Path) -> Fingerprint:
        """Return a cached fingerprint when the file is unchanged, else compute and store it."""
        resolved = path.resolve()
        if not resolved.is_file():
            return fingerprint(resolved)
        st = resolved.stat()
        key = str(resolved)
        hit = self._data.get(key)
        if hit and hit["size"] == st.st_size and hit["mtime_ns"] == st.st_mtime_ns:
            return Fingerprint.model_validate(hit["fingerprint"])
        fp = fingerprint(resolved)
        self._data[key] = {
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "fingerprint": fp.model_dump(),
        }
        atomic_write_text(self.path, json.dumps(self._data))
        return fp


def resolve_dataset_path(repo: Path, raw: str) -> Path:
    """Resolve a dataset path relative to the repo unless it is absolute."""
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (repo / p)


def dataset_ref(
    name: str,
    spec: DatasetSpec,
    split: str | None,
    repo: Path,
    cache: FingerprintCache,
    local_label: str,
) -> DatasetRef:
    """
    Build the ``DatasetRef`` a run records at launch.

    Parameters
    ----------
    name : str
        Dataset name from ``hypothex.yaml``.
    spec : DatasetSpec
        Dataset spec.
    split : str or None
        Split used by the task.
    repo : Path
        Project repo (for relative paths).
    cache : FingerprintCache
        Fingerprint cache.
    local_label : str
        This environment's label; datasets on other hosts are not hashed.

    Returns
    -------
    DatasetRef
        ``hash_mode`` is ``full``/``manifest``, ``missing`` if the path does not
        exist, or ``remote-unchecked`` for other hosts.
    """
    raw = spec.path_for(split)
    base: dict[str, Any] = {"name": name, "version": spec.version, "split": split}
    if spec.host not in ("local", local_label):
        return DatasetRef(**base, host=spec.host, path=raw, hash_mode="remote-unchecked")
    path = resolve_dataset_path(repo, raw)
    try:
        fp = cache.fingerprint(path)
    except FileNotFoundError:
        return DatasetRef(**base, path=str(path), hash_mode="missing")
    return DatasetRef(
        **base,
        path=str(path),
        hash=fp.hash,
        hash_mode=fp.mode,
        size=fp.size,
        checked_at=utcnow(),
    )


class DatasetDrift(BaseModel):
    """Result of re-checking one dataset of one run."""

    run_id: str
    project: str
    dataset: str
    path: str
    recorded_hash: str | None
    current_hash: str | None
    status: Literal["ok", "changed", "missing", "unchecked"]


def check_runs(records: Iterable[RunRecord], cache: FingerprintCache) -> list[DatasetDrift]:
    """
    Re-fingerprint every local dataset used by ``records``.

    Returns
    -------
    list of DatasetDrift
        One entry per (run, dataset).
    """
    out: list[DatasetDrift] = []
    for record in records:
        for ref in record.datasets:
            base = {
                "run_id": record.run_id,
                "project": record.project,
                "dataset": ref.name,
                "path": ref.path,
                "recorded_hash": ref.hash,
            }
            if ref.hash is None or ref.host != "local":
                out.append(DatasetDrift(**base, current_hash=None, status="unchecked"))
                continue
            try:
                current = cache.fingerprint(Path(ref.path)).hash
            except FileNotFoundError:
                out.append(DatasetDrift(**base, current_hash=None, status="missing"))
                continue
            status = "ok" if current == ref.hash else "changed"
            out.append(DatasetDrift(**base, current_hash=current, status=status))
    return out


class OverlapReport(BaseModel):
    """Examples shared between dataset splits."""

    dataset: str
    pairs: dict[str, int]
    examples: dict[str, list[str]]


def _split_keys(path: Path, key_field: str | None) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if key_field is None:
            keys.add(line)
            continue
        try:
            keys.add(str(json.loads(line)[key_field]))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return keys


def overlap(
    name: str,
    spec: DatasetSpec,
    repo: Path,
    key_field: str | None = None,
    max_examples: int = 20,
) -> OverlapReport:
    """
    Count examples shared between every pair of declared splits.

    Parameters
    ----------
    name : str
        Dataset name.
    spec : DatasetSpec
        Spec with ``splits``.
    repo : Path
        Project repo for relative paths.
    key_field : str, optional
        JSON field identifying an example; default compares whole lines.
    max_examples : int
        Shared keys listed per pair.

    Returns
    -------
    OverlapReport
    """
    keys = {
        split: _split_keys(resolve_dataset_path(repo, p), key_field)
        for split, p in spec.splits.items()
    }
    pairs: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    for a, b in itertools.combinations(sorted(keys), 2):
        shared = keys[a] & keys[b]
        pairs[f"{a}/{b}"] = len(shared)
        examples[f"{a}/{b}"] = sorted(shared)[:max_examples]
    return OverlapReport(dataset=name, pairs=pairs, examples=examples)
