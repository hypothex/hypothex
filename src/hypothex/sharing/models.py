"""Portable publication manifests and provider references."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from hypothex.core.errors import HypothexError

ArtifactKind = Literal["dataset", "model"]
MANIFEST_PATH = ".hypothex/manifest.json"
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_FILES = 10000


class SharingError(HypothexError):
    """A publication or transfer cannot be completed."""


def safe_path(value: str) -> str:
    """Validate a portable, relative artifact file path.

    Parameters
    ----------
    value : str
        POSIX path within a publication.

    Returns
    -------
    str
        The unchanged, validated path.
    """
    parts = value.split("/")
    if (
        not value
        or len(value.encode("utf-8")) > 1024
        or any(p in {"", ".", ".."} for p in parts)
        or any(ord(c) < 32 or c in "\\:" for c in value)
        or parts[0].casefold() == ".hypothex"
    ):
        raise ValueError("artifact paths must be safe relative POSIX paths")
    return value


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FileEntry(_Model):
    """One file's path, byte length and complete SHA-256 digest."""

    path: str
    size: int = Field(ge=0, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    _path = field_validator("path")(safe_path)


class Manifest(_Model):
    """Versioned file inventory, with optional explicitly supplied provenance."""

    schema_version: Literal[1] = 1
    kind: ArtifactKind
    files: tuple[FileEntry, ...] = Field(min_length=1, max_length=MAX_FILES)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def _validate_inventory(self) -> Self:
        names: set[str] = set()
        for entry in self.files:
            name = entry.path.casefold()
            if name in names:
                raise ValueError("manifest has duplicate or case-colliding paths")
            names.add(name)
        for name in names:
            if any(str(parent) in names for parent in PurePosixPath(name).parents):
                raise ValueError("manifest contains a file/directory collision")
        if any(len(k) > 128 or len(v) > 4096 for k, v in self.metadata.items()):
            raise ValueError("manifest metadata exceeds the size limit")
        return self

    def to_bytes(self) -> bytes:
        """Return canonical UTF-8 JSON for content addressing.

        Returns
        -------
        bytes
            Stable encoding independent of metadata key order.
        """
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()

    @property
    def digest(self) -> str:
        """SHA-256 of the canonical manifest, including explicit provenance."""
        return hashlib.sha256(self.to_bytes()).hexdigest()


class HuggingFaceTarget(_Model):
    """Native Hub repository; ``private`` applies only when creating it."""

    provider: Literal["hf"] = "hf"
    repo_id: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*$")
    private: bool = True
    revision: str = Field(default="main", min_length=1, max_length=256)


def _endpoint(value: str | None) -> str | None:
    if value is not None:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "endpoint must be an HTTP(S) URL without credentials, query or fragment"
            )
    return value


def _prefix(value: str) -> str:
    if value:
        safe_path(value)
    return value


class S3Target(_Model):
    """Bucket and optional prefix; SDK credentials are never part of the target."""

    provider: Literal["s3"] = "s3"
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    prefix: str = ""
    endpoint_url: str | None = None
    region: str | None = None
    _valid_prefix = field_validator("prefix")(_prefix)
    _valid_endpoint = field_validator("endpoint_url")(_endpoint)


Target = HuggingFaceTarget | S3Target


class Reference(_Model):
    """A pinned provider location; contains no tokens or signed URLs."""

    provider: Literal["hf", "s3"]
    kind: ArtifactKind
    location: str
    revision: str
    prefix: str = ""
    endpoint_url: str | None = None
    region: str | None = None

    @model_validator(mode="after")
    def _valid_reference(self) -> Self:
        if self.provider == "hf":
            HuggingFaceTarget(repo_id=self.location)
            if not re.fullmatch(r"[0-9a-f]{40}", self.revision):
                raise ValueError("Hub references require a full commit SHA")
            if self.prefix or self.endpoint_url or self.region:
                raise ValueError("Hub references cannot contain S3 options")
        else:
            S3Target(
                bucket=self.location,
                prefix=self.prefix,
                endpoint_url=self.endpoint_url,
                region=self.region,
            )
            if not re.fullmatch(r"[0-9a-f]{64}", self.revision):
                raise ValueError("S3 references require a manifest SHA-256")
        return self

    @property
    def uri(self) -> str:
        """Human-readable pinned locator (S3 connection options live in the receipt)."""
        if self.provider == "hf":
            return f"hf://{self.kind}s/{self.location}@{self.revision}"
        prefix = f"{self.prefix}/" if self.prefix else ""
        return f"s3://{self.location}/{prefix}{self.revision}"


class AccessInfo(_Model):
    """Provider-reported visibility, without claiming effective IAM authorization."""

    provider: Literal["hf", "s3"]
    visibility: Literal["private", "public", "provider-managed"]
    url: str | None = None
    details: str


class ShareLink(_Model):
    """A provider URL; a signed S3 link is a temporary bearer credential."""

    url: str
    file: str | None = None
    expires_in: int | None = None
    bearer: bool = False


class Receipt(_Model):
    """A local record written only after the provider completes publication."""

    id: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference: Reference
    manifest: Manifest
    created_at: AwareDatetime
