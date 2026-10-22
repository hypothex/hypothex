"""Native Hub contracts with real SDK operations and controlled clients."""

from __future__ import annotations

import builtins
import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hypothex.sharing.huggingface import HuggingFaceProvider
from hypothex.sharing.models import (
    MANIFEST_PATH,
    MAX_MANIFEST_BYTES,
    ArtifactKind,
    FileEntry,
    HuggingFaceTarget,
    Manifest,
    Reference,
    S3Target,
    SharingError,
)

PARENT = "a" * 40
COMMIT = "b" * 40


class FakeHub:
    """Record provider calls, checking their real SDK signatures when installed."""

    def __init__(self, tmp_path: Path, *, private: bool = True) -> None:
        self.cache = tmp_path / "cache"
        self.cache.mkdir()
        self.files: dict[str, Path] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.private = private
        self.fail: str | None = None
        self.parent = PARENT
        self.commit = COMMIT
        self.manifest_size: int | None = None
        self.advertised_sizes: dict[str, int] = {}

    def _record(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, kwargs))
        try:
            from huggingface_hub import HfApi
        except ImportError:
            pass
        else:
            inspect.signature(getattr(HfApi, name)).bind(None, **kwargs)
        if self.fail == name:
            raise RuntimeError("https://token-secret@private.invalid/?token=secret")

    def put(self, name: str, data: bytes) -> None:
        path = self.cache / str(len(self.files))
        path.write_bytes(data)
        self.files[name] = path

    def create_repo(self, **kwargs: Any) -> None:
        self._record("create_repo", kwargs)

    def repo_info(self, **kwargs: Any) -> SimpleNamespace:
        self._record("repo_info", kwargs)
        return SimpleNamespace(sha=self.parent, private=self.private)

    def get_paths_info(self, **kwargs: Any) -> list[SimpleNamespace]:
        self._record("get_paths_info", kwargs)
        name = kwargs["paths"][0]
        if name not in self.files:
            return []
        size = self.manifest_size if name == MANIFEST_PATH else self.advertised_sizes.get(name)
        if size is None:
            size = self.files[name].stat().st_size
        return [SimpleNamespace(path=name, size=size)]

    def hf_hub_download(self, **kwargs: Any) -> str:
        self._record("hf_hub_download", kwargs)
        return str(self.files[kwargs["filename"]])

    def create_commit(self, **kwargs: Any) -> SimpleNamespace:
        self._record("create_commit", kwargs)
        return SimpleNamespace(oid=self.commit)

    def update_repo_settings(self, **kwargs: Any) -> None:
        self._record("update_repo_settings", kwargs)
        self.private = kwargs["private"]


def _manifest(*names: str, kind: ArtifactKind = "dataset") -> Manifest:
    return Manifest(
        kind=kind,
        files=tuple(
            FileEntry(
                path=name, size=len(name.encode()), sha256=hashlib.sha256(name.encode()).hexdigest()
            )
            for name in names
        ),
    )


def _snapshot(tmp_path: Path, manifest: Manifest) -> Path:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    for entry in manifest.files:
        file = snapshot / entry.path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(entry.path.encode())
    return snapshot


def _reference(kind: ArtifactKind = "dataset") -> Reference:
    return Reference(provider="hf", kind=kind, location="owner/repo", revision=COMMIT)


@pytest.mark.parametrize("kind", ["dataset", "model"])
def test_publish_native_atomic_commit_preserves_visibility_and_unmanaged_files(
    tmp_path: Path,
    kind: ArtifactKind,
) -> None:
    sdk = pytest.importorskip("huggingface_hub")
    manifest = _manifest("nested/new.bin", "kept.bin", kind=kind)
    snapshot = _snapshot(tmp_path, manifest)
    client = FakeHub(tmp_path, private=False)
    client.put(MANIFEST_PATH, _manifest("gone.bin", "kept.bin", kind=kind).to_bytes())
    client.put("README.md", b"unmanaged")
    reference = HuggingFaceProvider(client).publish(
        snapshot, manifest, HuggingFaceTarget(repo_id="owner/repo")
    )
    assert reference == _reference(kind)
    assert client.private is False
    assert client.calls[0] == (
        "create_repo",
        {"repo_id": "owner/repo", "repo_type": kind, "private": True, "exist_ok": True},
    )
    assert not any(name == "update_repo_settings" for name, _ in client.calls)
    assert client.calls[-1][0] == "create_commit"
    commit = client.calls[-1][1]
    assert commit["parent_commit"] == PARENT and commit["revision"] == "main"
    assert commit["repo_type"] == kind
    operations = commit["operations"]
    assert [op.path_in_repo for op in operations] == [
        "gone.bin",
        "nested/new.bin",
        "kept.bin",
        MANIFEST_PATH,
    ]
    assert isinstance(operations[0], sdk.CommitOperationDelete)
    assert operations[0].is_folder is False
    assert all(isinstance(op, sdk.CommitOperationAdd) for op in operations[1:])
    assert operations[-1].path_or_fileobj == manifest.to_bytes()
    for op in operations[1:-1]:
        assert Path(op.path_or_fileobj).read_bytes() == op.path_in_repo.encode()
    assert client.files["README.md"].read_bytes() == b"unmanaged"
    for name, call in client.calls:
        if name in {"get_paths_info", "hf_hub_download"}:
            assert call["revision"] == PARENT


def test_new_public_model_and_nondefault_branch(tmp_path: Path) -> None:
    pytest.importorskip("huggingface_hub")
    manifest = _manifest("weights.bin", kind="model")
    client = FakeHub(tmp_path)
    reference = HuggingFaceProvider(client).publish(
        _snapshot(tmp_path, manifest),
        manifest,
        HuggingFaceTarget(repo_id="owner/repo", private=False, revision="release"),
    )
    assert reference == _reference("model")
    assert client.calls[0][1]["private"] is False
    assert client.calls[1][1]["revision"] == "release"
    assert client.calls[-1][1]["revision"] == "release"
    assert all(
        type(op).__name__ == "CommitOperationAdd" for op in client.calls[-1][1]["operations"]
    )


@pytest.mark.parametrize("prior", [b"not JSON secret", _manifest("old", kind="model").to_bytes()])
def test_corrupt_or_wrong_kind_prior_inventory_blocks_commit(tmp_path: Path, prior: bytes) -> None:
    pytest.importorskip("huggingface_hub")
    manifest = _manifest("new")
    client = FakeHub(tmp_path)
    client.put(MANIFEST_PATH, prior)
    with pytest.raises(SharingError) as caught:
        HuggingFaceProvider(client).publish(
            _snapshot(tmp_path, manifest), manifest, HuggingFaceTarget(repo_id="owner/repo")
        )
    assert "secret" not in str(caught.value)
    assert not any(name == "create_commit" for name, _ in client.calls)


@pytest.mark.parametrize("failure", ["create_repo", "repo_info", "get_paths_info", "create_commit"])
def test_publication_failure_redacts_credentials(tmp_path: Path, failure: str) -> None:
    pytest.importorskip("huggingface_hub")
    manifest = _manifest("data")
    client = FakeHub(tmp_path)
    client.fail = failure
    with pytest.raises(SharingError, match="Hugging Face publication failed") as caught:
        HuggingFaceProvider(client).publish(
            _snapshot(tmp_path, manifest), manifest, HuggingFaceTarget(repo_id="owner/repo")
        )
    assert "secret" not in str(caught.value) and caught.value.__suppress_context__


@pytest.mark.parametrize("attribute", ["parent", "commit"])
def test_publication_requires_full_provider_commit_sha(tmp_path: Path, attribute: str) -> None:
    pytest.importorskip("huggingface_hub")
    manifest = _manifest("data")
    client = FakeHub(tmp_path)
    setattr(client, attribute, "main")
    with pytest.raises(SharingError, match="commit SHA"):
        HuggingFaceProvider(client).publish(
            _snapshot(tmp_path, manifest), manifest, HuggingFaceTarget(repo_id="owner/repo")
        )


def test_manifest_and_downloads_are_pinned_and_destination_is_exclusive(tmp_path: Path) -> None:
    manifest = _manifest("nested/data")
    client = FakeHub(tmp_path)
    client.put(MANIFEST_PATH, manifest.to_bytes())
    client.put(manifest.files[0].path, manifest.files[0].path.encode())
    provider = HuggingFaceProvider(client)
    assert provider.load_manifest(_reference()) == manifest.to_bytes()
    destination = tmp_path / "staged" / "file"
    provider.download_file(_reference(), manifest.files[0], destination)
    assert destination.read_bytes() == manifest.files[0].path.encode()
    with pytest.raises(SharingError):
        provider.download_file(_reference(), manifest.files[0], destination)
    assert destination.read_bytes() == manifest.files[0].path.encode()
    assert all(call["revision"] == COMMIT for _, call in client.calls)


@pytest.mark.parametrize("metadata_size", [MAX_MANIFEST_BYTES + 1, -1])
def test_manifest_metadata_limit_prevents_download(tmp_path: Path, metadata_size: int) -> None:
    client = FakeHub(tmp_path)
    client.put(MANIFEST_PATH, b"small")
    client.manifest_size = metadata_size
    with pytest.raises(SharingError, match="size limit"):
        HuggingFaceProvider(client).load_manifest(_reference())
    assert not any(name == "hf_hub_download" for name, _ in client.calls)


def test_manifest_content_limit_checks_actual_bytes(tmp_path: Path) -> None:
    client = FakeHub(tmp_path)
    client.put(MANIFEST_PATH, b"x" * (MAX_MANIFEST_BYTES + 1))
    client.manifest_size = 1
    with pytest.raises(SharingError, match="size limit"):
        HuggingFaceProvider(client).load_manifest(_reference())


def test_missing_manifest_and_download_size_mismatch(tmp_path: Path) -> None:
    client = FakeHub(tmp_path)
    provider = HuggingFaceProvider(client)
    with pytest.raises(SharingError, match="missing"):
        provider.load_manifest(_reference())
    client.put("data", b"unexpected length")
    destination = tmp_path / "file"
    with pytest.raises(SharingError, match="size"):
        provider.download_file(_reference(), _manifest("data").files[0], destination)
    assert not destination.exists()


def test_advertised_file_size_mismatch_prevents_sdk_download(tmp_path: Path) -> None:
    client = FakeHub(tmp_path)
    client.put("data", b"data")
    client.advertised_sizes["data"] = 2**40
    destination = tmp_path / "file"
    with pytest.raises(SharingError, match="size"):
        HuggingFaceProvider(client).download_file(
            _reference(),
            _manifest("data").files[0],
            destination,
        )
    assert client.calls == [
        (
            "get_paths_info",
            {
                "repo_id": "owner/repo",
                "paths": ["data"],
                "repo_type": "dataset",
                "revision": COMMIT,
            },
        )
    ]
    assert not destination.exists()


def test_cached_size_is_checked_after_matching_remote_size(tmp_path: Path) -> None:
    client = FakeHub(tmp_path)
    client.put("data", b"oversized cache entry")
    client.advertised_sizes["data"] = 4
    destination = tmp_path / "file"
    with pytest.raises(SharingError, match="size"):
        HuggingFaceProvider(client).download_file(
            _reference(),
            _manifest("data").files[0],
            destination,
        )
    assert client.calls[-1][0] == "hf_hub_download"
    assert not destination.exists()


@pytest.mark.parametrize("kind,prefix", [("dataset", "datasets/"), ("model", "")])
def test_access_visibility_and_canonical_links(
    tmp_path: Path, kind: ArtifactKind, prefix: str
) -> None:
    manifest = _manifest("folder/file #?.bin", kind=kind)
    reference = _reference(kind)
    client = FakeHub(tmp_path)
    provider = HuggingFaceProvider(client)
    root = f"https://huggingface.co/{prefix}owner/repo"
    access = provider.access(reference)
    assert access.visibility == "private" and access.url == f"{root}/tree/{COMMIT}"
    before = list(client.calls)
    tree = provider.share(reference, manifest, None, 60)
    blob = provider.share(reference, manifest, manifest.files[0].path, 60)
    assert tree.url == access.url
    assert blob.url == f"{root}/blob/{COMMIT}/folder/file%20%23%3F.bin"
    assert not blob.bearer and blob.expires_in is None
    assert client.calls == before
    with pytest.raises(SharingError, match="not in"):
        provider.share(reference, manifest, "other", 60)
    updated = provider.set_visibility(reference, private=False)
    assert updated.visibility == "public"
    assert client.calls[-2] == (
        "update_repo_settings",
        {"repo_id": "owner/repo", "repo_type": kind, "private": False},
    )


@pytest.mark.parametrize("operation", ["manifest", "file", "access", "visibility"])
def test_read_and_visibility_errors_redact_provider_details(tmp_path: Path, operation: str) -> None:
    client = FakeHub(tmp_path)
    client.put("data", b"data")
    provider = HuggingFaceProvider(client)
    client.fail = {
        "manifest": "get_paths_info",
        "file": "hf_hub_download",
        "access": "repo_info",
        "visibility": "update_repo_settings",
    }[operation]
    with pytest.raises(SharingError) as caught:
        if operation == "manifest":
            provider.load_manifest(_reference())
        elif operation == "file":
            provider.download_file(_reference(), _manifest("data").files[0], tmp_path / "file")
        elif operation == "access":
            provider.access(_reference())
        else:
            provider.set_visibility(_reference(), private=False)
    assert "secret" not in str(caught.value) and caught.value.__suppress_context__


def test_missing_extra_is_lazy_and_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    original = builtins.__import__

    def blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "huggingface_hub":
            raise ImportError("blocked optional dependency")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    provider = HuggingFaceProvider()
    assert provider.share(_reference(), _manifest("data"), None, 60).url
    with pytest.raises(SharingError, match=r"hypothex\[hf\]"):
        provider.access(_reference())


def test_default_client_uses_official_hub_and_native_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk = pytest.importorskip("huggingface_hub")
    client = FakeHub(tmp_path)
    constructed: list[dict[str, Any]] = []

    def factory(**kwargs: Any) -> FakeHub:
        constructed.append(kwargs)
        return client

    # The constructor is patched, so skip the real HfApi signature checks here.
    monkeypatch.setattr(client, "_record", lambda name, kwargs: client.calls.append((name, kwargs)))
    monkeypatch.setattr(sdk, "HfApi", factory)
    monkeypatch.setenv("HF_ENDPOINT", "https://unrelated.invalid")
    provider = HuggingFaceProvider()
    assert not constructed
    provider.access(_reference())
    provider.access(_reference())
    assert constructed == [{"endpoint": "https://huggingface.co", "library_name": "hypothex"}]


def test_wrong_target_and_reference_rejected_without_io(tmp_path: Path) -> None:
    client = FakeHub(tmp_path)
    provider = HuggingFaceProvider(client)
    with pytest.raises(SharingError, match="hf target"):
        provider.publish(tmp_path, _manifest("data"), S3Target(bucket="test-bucket"))
    wrong = Reference(provider="s3", kind="dataset", location="test-bucket", revision="c" * 64)
    with pytest.raises(SharingError, match="hf reference"):
        provider.load_manifest(wrong)
    assert not client.calls
