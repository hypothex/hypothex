import json
from pathlib import Path

import pytest

from hypothex.core import datasets as ds
from hypothex.core.config import DatasetSpec
from hypothex.core.records import DatasetRef
from tests.factories import make_record


def test_full_hash_stable_and_content_sensitive(tmp_path: Path) -> None:
    f = tmp_path / "d.jsonl"
    f.write_text("a\nb\n")
    first = ds.fingerprint(f)
    assert first.mode == "full" and first.size == 4 and first.hash.startswith("xxh3:")
    assert ds.fingerprint(f) == first
    f.write_text("a\nc\n")
    assert ds.fingerprint(f).hash != first.hash


def test_manifest_mode_for_big_files_and_dirs(tmp_path: Path) -> None:
    f = tmp_path / "big.bin"
    f.write_bytes(b"x" * 100)
    assert ds.fingerprint(f, full_limit=10).mode == "manifest"
    d = tmp_path / "dir"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_text("1")
    (d / "sub" / "b.txt").write_text("2")
    first = ds.fingerprint(d)
    assert first.mode == "manifest" and first.size == 2
    (d / "sub" / "b.txt").write_text("22")
    assert ds.fingerprint(d).hash != first.hash


def test_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ds.fingerprint(tmp_path / "nope")


def test_cache_avoids_rehash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "d.txt"
    f.write_text("abc")
    cache = ds.FingerprintCache(tmp_path / "cache.json")
    calls: list[Path] = []
    real = ds._hash_file_full

    def counting(path: Path) -> str:
        calls.append(path)
        return real(path)

    monkeypatch.setattr(ds, "_hash_file_full", counting)
    cache.fingerprint(f)
    ds.FingerprintCache(tmp_path / "cache.json").fingerprint(f)  # reloads from disk
    assert len(calls) == 1


def test_dataset_ref_modes(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "t.jsonl").write_text("{}\n")
    cache = ds.FingerprintCache(tmp_path / "c.json")
    spec = DatasetSpec(version="v1", path="data/t.jsonl")
    ref = ds.dataset_ref("d", spec, None, tmp_path, cache, "mac")
    assert ref.hash_mode == "full" and ref.path == str(tmp_path / "data" / "t.jsonl")
    missing = ds.dataset_ref(
        "d", DatasetSpec(version="v1", path="nope.jsonl"), None, tmp_path, cache, "mac"
    )
    assert missing.hash is None and missing.hash_mode == "missing"
    remote = ds.dataset_ref(
        "d", DatasetSpec(version="v1", path="/x", host="gpu1"), None, tmp_path, cache, "mac"
    )
    assert remote.hash_mode == "remote-unchecked"


def test_check_runs_detects_change(tmp_path: Path) -> None:
    f = tmp_path / "t.jsonl"
    f.write_text("a\n")
    cache = ds.FingerprintCache(tmp_path / "c.json")
    fp = cache.fingerprint(f)
    ref = DatasetRef(name="d", version="v1", path=str(f), hash=fp.hash, hash_mode=fp.mode)
    record = make_record("r1", datasets=[ref])
    assert [d.status for d in ds.check_runs([record], cache)] == ["ok"]
    f.write_text("bb\n")  # different size, so the cache cannot hit by mtime resolution luck
    assert [d.status for d in ds.check_runs([record], cache)] == ["changed"]
    f.unlink()
    assert [d.status for d in ds.check_runs([record], cache)] == ["missing"]


def test_overlap_counts_shared_examples(tmp_path: Path) -> None:
    rows = {"train": ["a", "b", "c"], "test": ["c", "d"], "valid": ["d"]}
    splits = {}
    for split, keys in rows.items():
        path = tmp_path / f"{split}.jsonl"
        path.write_text("".join(json.dumps({"smiles": k, "y": 1}) + "\n" for k in keys))
        splits[split] = str(path)
    spec = DatasetSpec(version="v1", path=splits["test"], splits=splits)
    report = ds.overlap("d", spec, tmp_path, key_field="smiles")
    assert report.pairs == {"test/train": 1, "test/valid": 1, "train/valid": 0}
    assert report.examples["test/train"] == ["c"]
