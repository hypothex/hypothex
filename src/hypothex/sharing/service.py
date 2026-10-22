"""Public dataset/model publishing and verified download operations."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from pydantic import ValidationError

from hypothex.core.fsutil import fsync_dir
from hypothex.core.layout import default_home
from hypothex.sharing.files import install_directory, snapshot, verify_file
from hypothex.sharing.models import (
    MAX_MANIFEST_BYTES,
    AccessInfo,
    ArtifactKind,
    Manifest,
    Receipt,
    Reference,
    ShareLink,
    SharingError,
    Target,
)
from hypothex.sharing.provider import Provider


def get_provider(target: Target | Reference, *, profile: str | None = None) -> Provider:
    """Construct an optional provider adapter using SDK credential discovery.

    Parameters
    ----------
    target : Target or Reference
        Provider location and non-secret connection options.
    profile : str, optional
        AWS shared-configuration profile; never stored in a receipt.

    Returns
    -------
    Provider
        Hugging Face or S3 adapter. Missing extras raise ``SharingError``.
    """
    if target.provider == "hf":
        if profile is not None:
            raise SharingError("AWS profiles apply only to S3")
        from hypothex.sharing.huggingface import HuggingFaceProvider

        return HuggingFaceProvider()
    from hypothex.sharing.s3 import S3Provider

    return S3Provider(profile=profile, endpoint_url=target.endpoint_url, region=target.region)


def _receipt_id(reference: Reference, manifest: Manifest) -> str:
    value = json.dumps(reference.model_dump(mode="json"), sort_keys=True).encode()
    return hashlib.sha256(value + manifest.to_bytes()).hexdigest()


def _receipts_dir(home: Path | None) -> Path:
    return (home or default_home()).expanduser() / "publications"


def _save(receipt: Receipt, home: Path | None) -> None:
    folder = _receipts_dir(home)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(dir=folder, prefix=".receipt-", delete=False) as output:
            temporary = Path(output.name)
            output.write(receipt.model_dump_json(indent=2).encode())
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, folder / f"{receipt.id}.json")
        fsync_dir(folder)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def publish(
    source: Path | str,
    target: Target,
    *,
    kind: ArtifactKind,
    home: Path | None = None,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    metadata: dict[str, str] | None = None,
    profile: str | None = None,
    provider: Provider | None = None,
) -> Receipt:
    """Publish a stable file snapshot and save a completed local receipt.

    Parameters
    ----------
    source : Path or str
        Regular file or directory. Directory contents become publication paths.
    target : HuggingFaceTarget or S3Target
        Destination repository or bucket/prefix.
    kind : {"dataset", "model"}
        Artifact type; selects the native Hugging Face repository type.
    home : Path, optional
        Hypothex home for local receipts; defaults to the usual home.
    include, exclude : sequence of str, optional
        POSIX-relative fnmatch patterns. Exclusion takes precedence.
    metadata : dict of str to str, optional
        Explicit provenance, such as a run ID. No environment is captured.
    profile : str, optional
        AWS profile for credential discovery.
    provider : Provider, optional
        Custom adapter, useful for controlled integrations and tests.

    Returns
    -------
    Receipt
        Completed publication and pinned remote reference.

    Examples
    --------
    >>> receipt = publish(  # doctest: +SKIP
    ...     "./dataset", HuggingFaceTarget(repo_id="team/my-data"), kind="dataset"
    ... )
    """
    with snapshot(
        Path(source).expanduser(), kind, include=include, exclude=exclude, metadata=metadata
    ) as (staged, manifest):
        if len(manifest.to_bytes()) > MAX_MANIFEST_BYTES:
            raise SharingError("publication manifest exceeds the size limit")
        adapter = provider or get_provider(target, profile=profile)
        reference = adapter.publish(staged, manifest, target)
        if reference.provider != target.provider or reference.kind != kind:
            raise SharingError("provider returned an inconsistent publication reference")
        if reference.provider == "s3" and reference.revision != manifest.digest:
            raise SharingError("provider returned an inconsistent content digest")
        receipt = Receipt(
            id=_receipt_id(reference, manifest),
            reference=reference,
            manifest=manifest,
            created_at=datetime.now(UTC),
        )
        try:
            _save(receipt, home)
        except OSError:
            raise SharingError(
                "publication completed remotely but its local receipt could not be saved"
            ) from None
        return receipt


def read_manifest(
    reference: Reference, *, provider: Provider | None = None, profile: str | None = None
) -> Manifest:
    """Read and validate a pinned publication's bounded manifest.

    Parameters
    ----------
    reference : Reference
        Immutable provider locator.
    provider : Provider, optional
        Explicit adapter.
    profile : str, optional
        AWS credential profile.

    Returns
    -------
    Manifest
        Validated file inventory; S3 also verifies its content-addressed digest.
    """
    raw = (provider or get_provider(reference, profile=profile)).load_manifest(reference)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise SharingError("publication manifest exceeds the size limit")
    try:
        manifest = Manifest.model_validate_json(raw)
    except ValueError:
        raise SharingError("publication manifest is invalid") from None
    if manifest.kind != reference.kind:
        raise SharingError("publication kind does not match its reference")
    if reference.provider == "s3" and manifest.digest != reference.revision:
        raise SharingError("publication manifest failed content-address verification")
    return manifest


def download(
    reference: Reference,
    destination: Path | str,
    *,
    profile: str | None = None,
    provider: Provider | None = None,
    max_bytes: int | None = None,
) -> Path:
    """Install a fully verified publication into a new directory.

    Parameters
    ----------
    reference : Reference
        Pinned publication reference, usually from a receipt.
    destination : Path or str
        New directory. Existing destinations are always refused.
    profile : str, optional
        AWS credential profile.
    provider : Provider, optional
        Explicit adapter.
    max_bytes : int, optional
        Refuse manifests exceeding this total byte budget before file transfers.

    Returns
    -------
    Path
        Installed directory containing exactly the manifest's files.
    """
    destination = Path(destination).expanduser().absolute()
    if os.path.lexists(destination):
        raise SharingError("download destination already exists")
    if max_bytes is not None and max_bytes < 0:
        raise SharingError("download byte budget must be nonnegative")
    adapter = provider or get_provider(reference, profile=profile)
    manifest = read_manifest(reference, provider=adapter)
    if max_bytes is not None and sum(f.size for f in manifest.files) > max_bytes:
        raise SharingError("publication exceeds the download byte budget")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".hx-download-", dir=destination.parent) as temporary:
            staged = Path(temporary) / "files"
            staged.mkdir()
            for entry in manifest.files:
                target = staged / entry.path
                target.parent.mkdir(parents=True, exist_ok=True)
                adapter.download_file(reference, entry, target)
                verify_file(target, entry)
            install_directory(staged, destination)
        return destination
    except OSError:
        raise SharingError(
            "download failed: check local paths, disk space and permissions"
        ) from None


def load_receipt(receipt_id: str, *, home: Path | None = None) -> Receipt:
    """Read one validated local publication receipt.

    Parameters
    ----------
    receipt_id : str
        Full 64-character ID returned by ``publish``.
    home : Path, optional
        Hypothex home containing the receipt.

    Returns
    -------
    Receipt
        Validated receipt, including manifest and provider connection options.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", receipt_id):
        raise SharingError("invalid publication receipt ID")
    try:
        with (_receipts_dir(home) / f"{receipt_id}.json").open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES * 2 + 1)
        if len(raw) > MAX_MANIFEST_BYTES * 2:
            raise SharingError("publication receipt exceeds the size limit")
        receipt = Receipt.model_validate_json(raw)
        if receipt.id != receipt_id or receipt.id != _receipt_id(
            receipt.reference, receipt.manifest
        ):
            raise SharingError("publication receipt identity mismatch")
        if receipt.reference.kind != receipt.manifest.kind or (
            receipt.reference.provider == "s3"
            and receipt.reference.revision != receipt.manifest.digest
        ):
            raise SharingError("publication receipt manifest mismatch")
        return receipt
    except (OSError, ValidationError):
        raise SharingError("publication receipt is missing, unreadable or invalid") from None


def list_receipts(*, home: Path | None = None) -> list[Receipt]:
    """List completed local publications, newest first.

    Parameters
    ----------
    home : Path, optional
        Hypothex home.

    Returns
    -------
    list of Receipt
        Validated receipts. A damaged receipt is reported instead of hidden.
    """
    records = [load_receipt(p.stem, home=home) for p in _receipts_dir(home).glob("*.json")]
    return sorted(records, key=lambda r: r.created_at, reverse=True)


def access(
    reference: Reference, *, profile: str | None = None, provider: Provider | None = None
) -> AccessInfo:
    """Inspect provider visibility without changing permissions.

    Parameters
    ----------
    reference : Reference
        Publication location.
    profile : str, optional
        AWS profile.
    provider : Provider, optional
        Explicit adapter.

    Returns
    -------
    AccessInfo
        Provider access description; S3 IAM is not summarized as public/private.
    """
    return (provider or get_provider(reference, profile=profile)).access(reference)


def share(
    reference: Reference,
    *,
    file: str | None = None,
    expires_in: int = 3600,
    profile: str | None = None,
    provider: Provider | None = None,
) -> ShareLink:
    """Create a pinned Hub URL or a temporary S3 GET URL for one file.

    Parameters
    ----------
    reference : Reference
        Pinned publication location.
    file : str, optional
        Manifest-relative file; required for S3 publications with multiple files.
    expires_in : int
        S3 expiry in seconds, from 1 to 604800; credentials may expire earlier.
    profile : str, optional
        AWS profile.
    provider : Provider, optional
        Explicit adapter.

    Returns
    -------
    ShareLink
        URL and access semantics. Signed URLs are never saved to receipts.
    """
    if not 1 <= expires_in <= 604800:
        raise SharingError("share expiry must be between 1 and 604800 seconds")
    adapter = provider or get_provider(reference, profile=profile)
    manifest = read_manifest(reference, provider=adapter)
    if file is not None and file not in {entry.path for entry in manifest.files}:
        raise SharingError("selected file is not in the publication manifest")
    return adapter.share(reference, manifest, file, expires_in)


def set_visibility(
    reference: Reference, *, private: bool, provider: Provider | None = None
) -> AccessInfo:
    """Explicitly change an entire Hub repository's visibility.

    Parameters
    ----------
    reference : Reference
        Hub repository identified by a publication reference.
    private : bool
        Desired repository-wide visibility, affecting every revision.
    provider : Provider, optional
        Explicit adapter.

    Returns
    -------
    AccessInfo
        Updated provider visibility. S3 refuses this operation.
    """
    if reference.provider != "hf":
        raise SharingError("S3 visibility is managed through bucket policies and IAM")
    return (provider or get_provider(reference)).set_visibility(reference, private=private)
