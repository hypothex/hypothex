"""Provider contract for content publication and individual file transfers."""

from pathlib import Path
from typing import Protocol

from hypothex.sharing.models import (
    AccessInfo,
    FileEntry,
    Manifest,
    Reference,
    ShareLink,
    Target,
)


class Provider(Protocol):
    """Adapter methods; transport errors must raise redacted ``SharingError``."""

    def publish(self, snapshot: Path, manifest: Manifest, target: Target) -> Reference:
        """Upload snapshot files and publish the manifest last/atomically."""
        ...

    def load_manifest(self, reference: Reference) -> bytes:
        """Read at most MAX_MANIFEST_BYTES, refusing larger responses."""
        ...

    def download_file(self, reference: Reference, entry: FileEntry, destination: Path) -> None:
        """Transfer one pinned file to a newly allocated staging path."""
        ...

    def access(self, reference: Reference) -> AccessInfo:
        """Inspect provider access without changing it."""
        ...

    def share(
        self,
        reference: Reference,
        manifest: Manifest,
        file: str | None,
        expires_in: int,
    ) -> ShareLink:
        """Return a pinned repo URL or a bounded-expiry link for one selected file."""
        ...

    def set_visibility(self, reference: Reference, *, private: bool) -> AccessInfo:
        """Change Hub repository visibility; S3 must explicitly refuse."""
        ...
