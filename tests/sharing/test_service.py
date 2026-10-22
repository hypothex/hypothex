"""Public transfer, failure atomicity and receipt contracts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from hypothex.sharing import (
    FileEntry,
    HuggingFaceTarget,
    Manifest,
    Reference,
    S3Target,
    SharingError,
    access,
    download,
    files,
    list_receipts,
    load_receipt,
    publish,
    read_manifest,
    service,
    set_visibility,
    share,
)
from hypothex.sharing.models import MAX_MANIFEST_BYTES, AccessInfo, ShareLink, Target


class MemoryProvider:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.raw: bytes = b""
        self.publish_calls = 0
        self.download_calls = 0
        self.fail_publish = False
        self.fail_download = False
        self.corrupt = False
        self.race_destination: Path | None = None
        self.mutate_source: Path | None = None

    def publish(self, snapshot: Path, manifest: Manifest, target: Target) -> Reference:
        self.publish_calls += 1
        if self.fail_publish:
            raise SharingError("controlled upload failure")
        if self.mutate_source:
            self.mutate_source.write_bytes(b"changed after snapshot")
        self.data = {entry.path: (snapshot / entry.path).read_bytes() for entry in manifest.files}
        self.raw = manifest.to_bytes()
        if isinstance(target, HuggingFaceTarget):
            return Reference(
                provider="hf", kind=manifest.kind, location=target.repo_id, revision="a" * 40
            )
        return Reference(
            provider="s3",
            kind=manifest.kind,
            location=target.bucket,
            prefix=target.prefix,
            revision=manifest.digest,
            endpoint_url=target.endpoint_url,
            region=target.region,
        )

    def load_manifest(self, reference: Reference) -> bytes:
        return self.raw

    def download_file(self, reference: Reference, entry: FileEntry, destination: Path) -> None:
        self.download_calls += 1
        destination.write_bytes(b"bad" if self.corrupt else self.data[entry.path])
        if self.race_destination:
            self.race_destination.mkdir()
            self.race_destination = None
        if self.fail_download:
            raise SharingError("controlled transfer failure")

    def access(self, reference: Reference) -> AccessInfo:
        return AccessInfo(provider=reference.provider, visibility="private", details="controlled")

    def share(
        self, reference: Reference, manifest: Manifest, file: str | None, expires_in: int
    ) -> ShareLink:
        return ShareLink(url="https://example.invalid/private", file=file)

    def set_visibility(self, reference: Reference, *, private: bool) -> AccessInfo:
        return AccessInfo(
            provider=reference.provider,
            visibility="private" if private else "public",
            details="controlled",
        )


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    (root / "weights.bin").write_bytes(b"weights" * 200000)
    (root / "nested").mkdir()
    (root / "nested" / "config.json").write_text('{"layers": 3}')
    return root


@pytest.mark.parametrize(
    "target",
    [HuggingFaceTarget(repo_id="team/model"), S3Target(bucket="artifacts", prefix="models")],
)
def test_public_roundtrip_and_private_receipt(
    source: Path, home: Path, tmp_path: Path, target: Target
) -> None:
    provider = MemoryProvider()
    receipt = publish(
        source, target, kind="model", home=home, provider=provider, metadata={"run_id": "r-123"}
    )
    assert load_receipt(receipt.id, home=home) == receipt
    assert list_receipts(home=home) == [receipt]
    assert receipt.manifest.metadata == {"run_id": "r-123"}
    assert (home / "publications" / f"{receipt.id}.json").stat().st_mode & 0o777 == 0o600
    result = download(receipt.reference, tmp_path / "fetched", provider=provider)
    assert sorted(str(p.relative_to(result)) for p in result.rglob("*") if p.is_file()) == [
        "nested/config.json",
        "weights.bin",
    ]
    for file in receipt.manifest.files:
        assert (result / file.path).read_bytes() == (source / file.path).read_bytes()
    assert access(receipt.reference, provider=provider).visibility == "private"
    assert share(receipt.reference, file="weights.bin", provider=provider).file == "weights.bin"
    if target.provider == "hf":
        assert (
            set_visibility(receipt.reference, private=False, provider=provider).visibility
            == "public"
        )
    else:
        with pytest.raises(SharingError, match="IAM"):
            set_visibility(receipt.reference, private=False, provider=provider)


def test_snapshot_bytes_do_not_change_with_source(source: Path, home: Path) -> None:
    provider = MemoryProvider()
    original = (source / "weights.bin").read_bytes()
    provider.mutate_source = source / "weights.bin"
    receipt = publish(
        source, S3Target(bucket="artifacts"), kind="model", home=home, provider=provider
    )
    assert provider.data["weights.bin"] == original
    assert (
        next(e.sha256 for e in receipt.manifest.files if e.path == "weights.bin")
        == hashlib.sha256(original).hexdigest()
    )


def test_upload_failure_has_no_completed_receipt(source: Path, home: Path) -> None:
    provider = MemoryProvider()
    provider.fail_publish = True
    with pytest.raises(SharingError, match="upload failure"):
        publish(source, S3Target(bucket="artifacts"), kind="model", home=home, provider=provider)
    assert list_receipts(home=home) == []


@pytest.mark.parametrize("failure", ["fail_download", "corrupt"])
def test_download_failure_discards_partial_tree(
    source: Path, home: Path, tmp_path: Path, failure: str
) -> None:
    provider = MemoryProvider()
    receipt = publish(
        source, S3Target(bucket="artifacts"), kind="model", home=home, provider=provider
    )
    setattr(provider, failure, True)
    destination = tmp_path / "download"
    with pytest.raises(SharingError):
        download(receipt.reference, destination, provider=provider)
    assert not destination.exists()
    assert not list(tmp_path.glob(".hx-download-*"))


@pytest.mark.parametrize("existing", ["file", "directory", "dangling-symlink"])
def test_existing_destination_is_refused_before_network(
    source: Path, home: Path, tmp_path: Path, existing: str
) -> None:
    provider = MemoryProvider()
    receipt = publish(
        source, S3Target(bucket="artifacts"), kind="model", home=home, provider=provider
    )
    destination = tmp_path / "existing"
    if existing == "file":
        destination.write_text("preserve")
    elif existing == "directory":
        destination.mkdir()
    else:
        destination.symlink_to(tmp_path / "missing")
    with pytest.raises(SharingError, match="already exists"):
        download(receipt.reference, destination, provider=provider)
    assert os.path.lexists(destination)
    assert provider.download_calls == 0


def test_concurrent_empty_destination_is_not_replaced(
    source: Path, home: Path, tmp_path: Path
) -> None:
    provider = MemoryProvider()
    receipt = publish(
        source, S3Target(bucket="artifacts"), kind="model", home=home, provider=provider
    )
    destination = tmp_path / "created-during-transfer"
    provider.race_destination = destination
    with pytest.raises(SharingError, match="destination exists"):
        download(receipt.reference, destination, provider=provider)
    assert destination.is_dir() and list(destination.iterdir()) == []


def test_byte_budget_refuses_before_file_transfer(source: Path, home: Path, tmp_path: Path) -> None:
    provider = MemoryProvider()
    receipt = publish(
        source, S3Target(bucket="artifacts"), kind="model", home=home, provider=provider
    )
    with pytest.raises(SharingError, match="byte budget"):
        download(receipt.reference, tmp_path / "download", max_bytes=1, provider=provider)
    assert provider.download_calls == 0


@pytest.mark.parametrize("raw", [b"not json", b" " * (MAX_MANIFEST_BYTES + 1)])
def test_invalid_manifest_refused(raw: bytes) -> None:
    provider = MemoryProvider()
    provider.raw = raw
    with pytest.raises(SharingError, match="manifest"):
        read_manifest(
            Reference(provider="hf", kind="model", location="team/repo", revision="a" * 40),
            provider=provider,
        )


def test_s3_manifest_digest_and_kind_are_verified(source: Path, home: Path) -> None:
    provider = MemoryProvider()
    receipt = publish(
        source, S3Target(bucket="artifacts"), kind="model", home=home, provider=provider
    )
    with pytest.raises(SharingError, match="content-address"):
        read_manifest(
            receipt.reference.model_copy(update={"revision": "0" * 64}), provider=provider
        )
    with pytest.raises(SharingError, match="kind"):
        read_manifest(receipt.reference.model_copy(update={"kind": "dataset"}), provider=provider)


def test_invalid_share_selection_and_expiry(source: Path, home: Path) -> None:
    provider = MemoryProvider()
    receipt = publish(
        source, S3Target(bucket="artifacts"), kind="model", home=home, provider=provider
    )
    with pytest.raises(SharingError, match="not in"):
        share(receipt.reference, file="../not-selected", provider=provider)
    for expiry in (0, 604801):
        with pytest.raises(SharingError, match="expiry"):
            share(receipt.reference, expires_in=expiry, provider=provider)


def test_receipt_identity_tampering_refused(source: Path, home: Path) -> None:
    receipt = publish(
        source, S3Target(bucket="artifacts"), kind="model", home=home, provider=MemoryProvider()
    )
    path = home / "publications" / f"{receipt.id}.json"
    raw = json.loads(path.read_text())
    raw["reference"]["location"] = "other-bucket"
    path.write_text(json.dumps(raw))
    with pytest.raises(SharingError, match="identity"):
        load_receipt(receipt.id, home=home)
    with pytest.raises(SharingError, match="invalid"):
        load_receipt("../escape", home=home)


def test_receipt_write_failure_is_explicit(
    source: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object) -> None:
        raise OSError("local failure")

    monkeypatch.setattr(service, "_save", fail)
    with pytest.raises(SharingError, match="completed remotely"):
        publish(
            source, S3Target(bucket="artifacts"), kind="model", home=home, provider=MemoryProvider()
        )


def test_selection_and_default_exclusions(source: Path, home: Path) -> None:
    (source / ".env").write_text("SECRET=example")
    (source / ".env.production").write_text("SECRET=example")
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("do not upload")
    receipt = publish(
        source,
        S3Target(bucket="artifacts"),
        kind="dataset",
        home=home,
        include=["*"],
        exclude=["nested/*"],
        provider=MemoryProvider(),
    )
    assert [f.path for f in receipt.manifest.files] == ["weights.bin"]


def test_single_file_keeps_basename(source: Path, home: Path) -> None:
    receipt = publish(
        source / "weights.bin",
        S3Target(bucket="artifacts"),
        kind="model",
        home=home,
        provider=MemoryProvider(),
    )
    assert [f.path for f in receipt.manifest.files] == ["weights.bin"]


def test_empty_selection_refused_before_upload(source: Path, home: Path) -> None:
    provider = MemoryProvider()
    with pytest.raises(SharingError, match="no publishable files"):
        publish(
            source,
            S3Target(bucket="artifacts"),
            kind="model",
            home=home,
            include=["*.does-not-exist"],
            provider=provider,
        )
    assert provider.publish_calls == 0


def test_unreadable_subdirectory_cannot_silently_disappear(source: Path, home: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory read permissions")
    provider = MemoryProvider()
    nested = source / "nested"
    nested.chmod(0)
    try:
        with pytest.raises(SharingError, match="cannot snapshot"):
            publish(
                source, S3Target(bucket="artifacts"), kind="model", home=home, provider=provider
            )
    finally:
        nested.chmod(0o700)
    assert provider.publish_calls == 0


@pytest.mark.parametrize("node", ["symlink-file", "symlink-dir", "fifo", "reserved"])
def test_unsafe_source_entries_refused(source: Path, home: Path, node: str) -> None:
    if node == "symlink-file":
        (source / "alias").symlink_to(source / "weights.bin")
    elif node == "symlink-dir":
        (source / "alias").symlink_to(source / "nested", target_is_directory=True)
    elif node == "fifo":
        os.mkfifo(source / "pipe")
    else:
        (source / ".hypothex").mkdir()
        (source / ".hypothex" / "manifest.json").write_text("bad")
    provider = MemoryProvider()
    with pytest.raises(SharingError):
        publish(source, S3Target(bucket="artifacts"), kind="model", home=home, provider=provider)
    assert provider.publish_calls == 0


def test_symlink_root_refused(source: Path, home: Path, tmp_path: Path) -> None:
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(SharingError, match="symlink"):
        publish(
            alias, S3Target(bucket="artifacts"), kind="model", home=home, provider=MemoryProvider()
        )


def test_mutation_during_snapshot_refused(
    source: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_fstat = os.fstat
    seen: dict[int, int] = {}

    def changed(fd: int) -> os.stat_result:
        value = original_fstat(fd)
        if value.st_size > 1000000:
            seen[fd] = seen.get(fd, 0) + 1
            if seen[fd] == 2:
                with (source / "weights.bin").open("ab") as output:
                    output.write(b"changed")
                return original_fstat(fd)
        return value

    monkeypatch.setattr(files.os, "fstat", changed)
    with pytest.raises(SharingError, match="changed"):
        publish(
            source, S3Target(bucket="artifacts"), kind="model", home=home, provider=MemoryProvider()
        )
