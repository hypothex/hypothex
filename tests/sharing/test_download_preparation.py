"""Batched download metadata preserves pinned identity and integrity checks."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hypothex.sharing import download
from hypothex.sharing.huggingface import HuggingFaceProvider
from hypothex.sharing.models import MANIFEST_PATH, Manifest, SharingError
from tests.sharing.test_huggingface import FakeHub, _manifest, _reference


def _hub(tmp_path: Path, count: int = 2) -> tuple[FakeHub, Manifest]:
    client = FakeHub(tmp_path)
    manifest = _manifest(*(f"{i:04}.txt" for i in range(count)))
    client.put(MANIFEST_PATH, manifest.to_bytes())
    for entry in manifest.files:
        client.put(entry.path, entry.path.encode())
    return client, manifest


def test_public_download_batches_pinned_metadata(tmp_path: Path) -> None:
    client, manifest = _hub(tmp_path, 1001)
    result = download(_reference(), tmp_path / "restored", provider=HuggingFaceProvider(client))
    calls = [kwargs for name, kwargs in client.calls if name == "get_paths_info"]
    assert [len(call["paths"]) for call in calls] == [1, 1000, 1]
    assert all(call["revision"] == _reference().revision for call in calls)
    assert all(call["repo_id"] == _reference().location for call in calls)
    assert all(call["repo_type"] == "dataset" for call in calls)
    assert {p.name for p in result.iterdir()} == {entry.path for entry in manifest.files}
    assert all(
        (result / entry.path).read_bytes() == entry.path.encode() for entry in manifest.files
    )


@pytest.mark.parametrize("failure", ["missing", "duplicate", "extra", "size", "bool", "directory"])
def test_invalid_batch_refused_before_file_transfers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    client, _ = _hub(tmp_path)
    original = client.get_paths_info

    def metadata(**kwargs: Any) -> list[SimpleNamespace]:
        entries = original(**kwargs)
        if kwargs["paths"] == [MANIFEST_PATH]:
            return entries
        if failure == "missing":
            return entries[:-1]
        if failure == "duplicate":
            return [entries[0]] * len(entries)
        if failure == "extra":
            return [*entries, SimpleNamespace(path="unexpected", size=1)]
        if failure == "directory":
            del entries[0].size
        else:
            entries[0].size = True if failure == "bool" else entries[0].size + 1
        return entries

    monkeypatch.setattr(client, "get_paths_info", metadata)
    destination = tmp_path / "restored"
    with pytest.raises(SharingError):
        download(_reference(), destination, provider=HuggingFaceProvider(client))
    assert not destination.exists()
    assert not list(tmp_path.glob(".hx-download-*"))
    assert [kw["filename"] for name, kw in client.calls if name == "hf_hub_download"] == [
        MANIFEST_PATH
    ]


def test_budget_rejects_before_preparing_file_metadata(tmp_path: Path) -> None:
    client, _ = _hub(tmp_path)
    with pytest.raises(SharingError, match="byte budget"):
        download(
            _reference(), tmp_path / "restored", provider=HuggingFaceProvider(client), max_bytes=0
        )
    assert [kw["paths"] for name, kw in client.calls if name == "get_paths_info"] == [
        [MANIFEST_PATH]
    ]


def test_prepared_download_still_hashes_cached_content(tmp_path: Path) -> None:
    client, manifest = _hub(tmp_path)
    entry = manifest.files[0]
    client.files[entry.path].write_bytes(b"!" * entry.size)
    with pytest.raises(SharingError, match="SHA-256"):
        download(_reference(), tmp_path / "restored", provider=HuggingFaceProvider(client))
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".hx-download-*"))


@pytest.mark.parametrize(
    "change", [{"location": "other/repo"}, {"kind": "model"}, {"revision": "c" * 40}]
)
def test_preparation_cannot_cross_reference_boundaries(
    tmp_path: Path, change: dict[str, str]
) -> None:
    client, manifest = _hub(tmp_path)
    provider = HuggingFaceProvider(client)
    prepared = provider.prepare_download(_reference(), manifest)
    before = len(client.calls)
    with pytest.raises(SharingError, match="prepared"):
        prepared.download_file(
            _reference().model_copy(update=change), manifest.files[0], tmp_path / "wrong"
        )
    assert len(client.calls) == before
    assert not (tmp_path / "wrong").exists()


def test_preparation_cannot_reuse_different_inventory(tmp_path: Path) -> None:
    client, manifest = _hub(tmp_path)
    prepared = HuggingFaceProvider(client).prepare_download(_reference(), manifest)
    for entry in (
        manifest.files[0].model_copy(update={"sha256": "0" * 64}),
        manifest.files[0].model_copy(update={"size": 100}),
        _manifest("unknown").files[0],
    ):
        with pytest.raises(SharingError, match="prepared"):
            prepared.download_file(_reference(), entry, tmp_path / "wrong")
    assert not (tmp_path / "wrong").exists()


def test_preparation_does_not_mutate_reusable_provider(tmp_path: Path) -> None:
    client, manifest = _hub(tmp_path)
    provider = HuggingFaceProvider(client)
    first = provider.prepare_download(_reference(), manifest)
    other = _reference().model_copy(update={"revision": "c" * 40})
    second = provider.prepare_download(other, manifest)
    assert first is not second and first is not provider and second is not provider
    client.calls.clear()
    first.download_file(_reference(), manifest.files[0], tmp_path / "first")
    second.download_file(other, manifest.files[0], tmp_path / "second")
    assert not any(name == "get_paths_info" for name, _ in client.calls)
    provider.download_file(_reference(), manifest.files[0], tmp_path / "direct")
    assert len([name for name, _ in client.calls if name == "get_paths_info"]) == 1


def test_later_batch_failure_does_not_leave_preparation_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, manifest = _hub(tmp_path, 1001)
    provider = HuggingFaceProvider(client)
    original = client.get_paths_info

    def metadata(**kwargs: Any) -> list[SimpleNamespace]:
        if kwargs["paths"] == [manifest.files[-1].path]:
            raise RuntimeError("https://secret-token@private.invalid")
        return original(**kwargs)

    monkeypatch.setattr(client, "get_paths_info", metadata)
    with pytest.raises(SharingError) as caught:
        download(_reference(), tmp_path / "failed", provider=provider)
    assert "secret-token" not in str(caught.value)
    assert not (tmp_path / "failed").exists()
    assert not any(
        name == "hf_hub_download" and kw["filename"] != MANIFEST_PATH for name, kw in client.calls
    )
    monkeypatch.setattr(client, "get_paths_info", original)
    client.calls.clear()
    provider.download_file(_reference(), manifest.files[0], tmp_path / "direct")
    assert [name for name, _ in client.calls] == ["get_paths_info", "hf_hub_download"]
