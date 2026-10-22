"""Native Hub contracts with real SDK operations and controlled clients."""

from __future__ import annotations

import hashlib
import importlib
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
        self.cache_count = 0

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
        path = self.cache / str(self.cache_count)
        self.cache_count += 1
        path.write_bytes(data)
        self.files[name] = path

    def create_repo(self, **kwargs: Any) -> None:
        self._record("create_repo", kwargs)

    def repo_info(self, **kwargs: Any) -> SimpleNamespace:
        self._record("repo_info", kwargs)
        return SimpleNamespace(sha=self.parent, private=self.private)

    def get_paths_info(self, **kwargs: Any) -> list[SimpleNamespace]:
        self._record("get_paths_info", kwargs)
        entries = []
        for name in kwargs["paths"]:
            if name not in self.files:
                continue
            size = self.manifest_size if name == MANIFEST_PATH else self.advertised_sizes.get(name)
            data = self.files[name].read_bytes()
            if size is None:
                size = len(data)
            entries.append(
                SimpleNamespace(
                    path=name,
                    size=size,
                    lfs=None,
                    blob_id=hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(),
                )
            )
        return entries

    def hf_hub_download(self, **kwargs: Any) -> str:
        self._record("hf_hub_download", kwargs)
        return str(self.files[kwargs["filename"]])

    def create_commit(self, **kwargs: Any) -> SimpleNamespace:
        self._record("create_commit", kwargs)
        for operation in kwargs["operations"]:
            if type(operation).__name__ == "CommitOperationDelete":
                self.files.pop(operation.path_in_repo, None)
            else:
                with operation.as_file() as stream:
                    self.put(operation.path_in_repo, stream.read())
        return SimpleNamespace(oid=self.commit)

    def preupload_lfs_files(self, **kwargs: Any) -> None:
        self._record("preupload_lfs_files", kwargs)
        for operation in kwargs["additions"]:
            operation._should_ignore = False

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
    commit = next(call for name, call in client.calls if name == "create_commit")
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
            assert call["revision"] in {PARENT, COMMIT}


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
    commit = next(call for name, call in client.calls if name == "create_commit")
    assert commit["revision"] == "release"
    assert all(type(op).__name__ == "CommitOperationAdd" for op in commit["operations"])


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
    original = importlib.import_module

    def blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "huggingface_hub":
            raise ImportError("blocked optional dependency")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", blocked_import)
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


class SdkHub:
    """Exercise real SDK preupload/commit behavior through intercepted HTTP."""

    def __init__(self, tmp_path: Path, mode: str) -> None:
        self.mode = mode
        self.root = tmp_path
        self.source = tmp_path / "source"
        self.source.mkdir()
        self.source.joinpath("weights.bin").write_bytes(b"selected weights")
        self.initial_files = {"weights.bin": b"selected weights"}
        if "ignore" in mode:
            self.source.joinpath(".gitignore").write_bytes(b"*.bin\n")
            self.initial_files[".gitignore"] = b"*.bin\n"
        self.manifest = Manifest(
            kind="model",
            files=tuple(
                FileEntry(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
                for name, data in sorted(self.initial_files.items())
            ),
        )
        self.initial_files[MANIFEST_PATH] = self.manifest.to_bytes()
        self.remote: dict[str, dict[str, bytes]] = {
            PARENT: self.initial_files if "noop" in mode else {},
        }
        self.requests: list[tuple[str, str]] = []
        self.preuploads: list[dict[str, Any]] = []
        self.commits: list[list[dict[str, Any]]] = []
        self.downloaded: list[tuple[str, str]] = []
        self.info_count = 0

    def route(self, request: Any) -> Any:
        import base64
        import json

        import httpx

        path = request.url.path
        self.requests.append((request.method, path))
        if path == "/api/repos/create":
            return httpx.Response(200, json={"url": "https://huggingface.co/team/model"})
        if path == "/api/models/team/model/revision/main":
            self.info_count += 1
            sha = PARENT
            if self.info_count > 1 and self.mode in {"noop_race", "noop_file_race"}:
                if self.mode == "noop_race":
                    different = _manifest("different.bin", kind="model")
                    self.remote[COMMIT] = {
                        MANIFEST_PATH: different.to_bytes(),
                        "different.bin": b"new",
                    }
                else:
                    self.remote[COMMIT] = {**self.initial_files, "weights.bin": b"modified weights"}
                sha = COMMIT
            return httpx.Response(200, json={"id": "team/model", "sha": sha, "private": True})
        if "/paths-info/" in path:
            revision = path.rsplit("/", 1)[1]
            from urllib.parse import parse_qs

            names = parse_qs(request.read().decode())["paths"]
            entries = []
            for name in names:
                data = self.remote[revision].get(name)
                if data is None:
                    continue
                entry: dict[str, Any] = {
                    "type": "file",
                    "path": name,
                    "size": len(data),
                    "oid": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(),
                }
                if self.mode in {"lfs_good", "lfs_bad"} and name == "weights.bin":
                    entry["lfs"] = {
                        "size": len(data),
                        "pointerSize": 128,
                        "oid": hashlib.sha256(data).hexdigest()
                        if self.mode == "lfs_good"
                        else "0" * 64,
                    }
                if self.mode == "blob_bad" and name == "weights.bin":
                    entry["oid"] = "0" * 40
                entries.append(entry)
            return httpx.Response(200, json=entries)
        if "/preupload/" in path:
            body = json.loads(request.read())
            self.preuploads.append(body)
            entries = []
            for file in body["files"]:
                name = file["path"]
                ignored = name.endswith(".bin") and (
                    self.mode == "force_ignore"
                    or (self.mode == "respect_ignore" and body.get("gitIgnore") != "")
                )
                ignored = ignored or (self.mode == "ignore_manifest" and name == MANIFEST_PATH)
                entry = {"path": name, "uploadMode": "regular", "shouldIgnore": ignored}
                if "noop" in self.mode:
                    data = self.initial_files[name]
                    entry["oid"] = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
                entries.append(entry)
            return httpx.Response(200, json={"files": entries})
        if "/commit/" in path:
            payload = [json.loads(line) for line in request.read().splitlines()]
            self.commits.append(payload)
            self.remote[COMMIT] = dict(self.remote[PARENT])
            for item in payload:
                if item["key"] == "file":
                    self.remote[COMMIT][item["value"]["path"]] = base64.b64decode(
                        item["value"]["content"]
                    )
            return httpx.Response(
                200,
                json={
                    "commitUrl": f"https://huggingface.co/team/model/commit/{COMMIT}",
                    "commitOid": COMMIT,
                    "commitMessage": "publish",
                    "commitDescription": "",
                },
            )
        raise AssertionError((request.method, path))

    def download(self, filename: str, revision: str) -> str:
        assert filename == MANIFEST_PATH, "Verification must not download full model files"
        self.downloaded.append((filename, revision))
        destination = self.root / f"manifest-{revision}.json"
        destination.write_bytes(self.remote[revision][filename])
        return str(destination)


def _publish_with_sdk(hub: SdkHub) -> Any:
    import httpx

    sdk = pytest.importorskip("huggingface_hub")
    from hypothex.sharing import publish

    class ControlledApi(sdk.HfApi):
        def hf_hub_download(
            self,
            repo_id: str,
            filename: str,
            *,
            repo_type: str,
            revision: str,
        ) -> str:
            return hub.download(filename, revision)

    # Restore global client configuration even when the adapter refuses publication.
    from huggingface_hub.utils import _http

    previous_factory = _http._GLOBAL_CLIENT_FACTORY
    sdk.set_client_factory(lambda: httpx.Client(transport=httpx.MockTransport(hub.route)))
    try:
        return publish(
            hub.source,
            HuggingFaceTarget(repo_id="team/model"),
            kind="model",
            home=hub.root / "home",
            provider=HuggingFaceProvider(
                ControlledApi(endpoint="https://huggingface.co", token=False)
            ),
        )
    finally:
        sdk.set_client_factory(previous_factory)


def test_sdk_gitignore_cannot_silently_omit_selected_file(tmp_path: Path) -> None:
    hub = SdkHub(tmp_path, "respect_ignore")
    receipt = _publish_with_sdk(hub)
    assert hub.remote[receipt.reference.revision]["weights.bin"] == b"selected weights"
    assert all(body["gitIgnore"] == "" for body in hub.preuploads)
    assert hub.remote[receipt.reference.revision][MANIFEST_PATH] == receipt.manifest.to_bytes()


@pytest.mark.parametrize("mode", ["force_ignore", "ignore_manifest"])
def test_sdk_ignored_operation_refused_before_manifest_commit(tmp_path: Path, mode: str) -> None:
    hub = SdkHub(tmp_path, mode)
    with pytest.raises(SharingError, match="ignored"):
        _publish_with_sdk(hub)
    assert not hub.commits
    assert not (tmp_path / "home" / "publications").exists()


def test_sdk_noop_race_cannot_save_other_publication_receipt(tmp_path: Path) -> None:
    hub = SdkHub(tmp_path, "noop_race")
    with pytest.raises(SharingError, match="manifest"):
        _publish_with_sdk(hub)
    assert not hub.commits
    assert not (tmp_path / "home" / "publications").exists()


def test_sdk_noop_race_with_same_manifest_checks_file_identity(tmp_path: Path) -> None:
    hub = SdkHub(tmp_path, "noop_file_race")
    with pytest.raises(SharingError, match="identity"):
        _publish_with_sdk(hub)
    assert not hub.commits
    assert not (tmp_path / "home" / "publications").exists()


def test_sdk_unchanged_noop_is_verified_and_accepted(tmp_path: Path) -> None:
    hub = SdkHub(tmp_path, "noop_good")
    receipt = _publish_with_sdk(hub)
    assert receipt.reference.revision == PARENT
    assert receipt.manifest == hub.manifest
    assert not hub.commits


@pytest.mark.parametrize("mode", ["blob_bad", "lfs_bad"])
def test_sdk_pinned_file_identity_mismatch_prevents_receipt(tmp_path: Path, mode: str) -> None:
    hub = SdkHub(tmp_path, mode)
    with pytest.raises(SharingError, match="identity"):
        _publish_with_sdk(hub)
    assert not (tmp_path / "home" / "publications").exists()


def test_sdk_lfs_metadata_verification_does_not_download_model(tmp_path: Path) -> None:
    hub = SdkHub(tmp_path, "lfs_good")
    receipt = _publish_with_sdk(hub)
    assert receipt.manifest == hub.manifest
    assert hub.downloaded == [(MANIFEST_PATH, COMMIT)]


@pytest.mark.parametrize("state", [None, True, 0, "false"])
def test_unknown_or_ignored_sdk_preupload_state_refuses_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: Any,
) -> None:
    pytest.importorskip("huggingface_hub")
    client = FakeHub(tmp_path)
    manifest = _manifest("data")

    def preupload(**kwargs: Any) -> None:
        for operation in kwargs["additions"]:
            operation._should_ignore = state

    monkeypatch.setattr(client, "preupload_lfs_files", preupload)
    with pytest.raises(SharingError, match="ignored"):
        HuggingFaceProvider(client).publish(
            _snapshot(tmp_path, manifest),
            manifest,
            HuggingFaceTarget(repo_id="owner/repo"),
        )
    assert not any(name == "create_commit" for name, _ in client.calls)
