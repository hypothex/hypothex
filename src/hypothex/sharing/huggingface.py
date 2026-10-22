"""Native Hugging Face dataset/model publication through atomic Hub commits."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from hypothex.sharing.models import (
    MANIFEST_PATH,
    MAX_MANIFEST_BYTES,
    AccessInfo,
    FileEntry,
    HuggingFaceTarget,
    Manifest,
    Reference,
    ShareLink,
    SharingError,
    Target,
)

_COPY_BYTES = 1024 * 1024


def _sdk() -> Any:
    try:
        import huggingface_hub
    except ImportError:
        raise SharingError(
            "Hugging Face integration requires hypothex[hf]; "
            "run uv sync --extra hf in a source checkout"
        ) from None
    return huggingface_hub


@contextmanager
def _errors(operation: str) -> Iterator[None]:
    try:
        yield
    except SharingError:
        raise
    except Exception:
        # Provider exceptions can embed credential-bearing request URLs/headers.
        raise SharingError(f"Hugging Face {operation} failed") from None


def _sha(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise SharingError("Hugging Face returned an invalid commit SHA")
    return value


def _check(reference: Reference) -> None:
    if reference.provider != "hf":
        raise SharingError("Hugging Face integration requires an hf reference")


def _url(reference: Reference, file: str | None = None) -> str:
    prefix = "datasets/" if reference.kind == "dataset" else ""
    root = f"https://huggingface.co/{prefix}{reference.location}"
    if file is None:
        return f"{root}/tree/{reference.revision}"
    return f"{root}/blob/{reference.revision}/{quote(file, safe='/')}"


class HuggingFaceProvider:
    """
    Publish native Hub repositories using the SDK's credential discovery.

    Parameters
    ----------
    client : Any, optional
        An injected ``huggingface_hub.HfApi`` client. Omission creates a client
        lazily, without loading the optional SDK at module import time.

    Notes
    -----
    New repositories follow the target's visibility (private by default).
    Publishing preserves existing visibility and unrelated repository files.
    A later publication removes only paths listed in the previous Hypothex
    manifest; those paths remain managed even if edited outside Hypothex.
    The target branch must already exist unless it is the new repo's main branch.

    Examples
    --------
    Constructing a provider does not load the SDK or make network requests::

        provider = HuggingFaceProvider()
        target = HuggingFaceTarget(repo_id="my-team/example-dataset")
    """

    def __init__(self, client: Any | None = None) -> None:
        self._injected_client = client

    def _client(self) -> Any:
        if self._injected_client is None:
            self._injected_client = _sdk().HfApi(
                endpoint="https://huggingface.co", library_name="hypothex"
            )
        return self._injected_client

    def _manifest_path(self, reference: Reference, *, optional: bool = False) -> Path | None:
        client = self._client()
        entries = client.get_paths_info(
            repo_id=reference.location,
            paths=[MANIFEST_PATH],
            repo_type=reference.kind,
            revision=reference.revision,
        )
        if not entries and optional:
            return None
        if len(entries) != 1 or entries[0].path != MANIFEST_PATH:
            raise SharingError("Hugging Face publication manifest is missing")
        size = getattr(entries[0], "size", None)
        if type(size) is not int or not 0 <= size <= MAX_MANIFEST_BYTES:
            raise SharingError("Hugging Face publication manifest exceeds the size limit")
        return Path(
            client.hf_hub_download(
                repo_id=reference.location,
                filename=MANIFEST_PATH,
                repo_type=reference.kind,
                revision=reference.revision,
            )
        )

    @staticmethod
    def _read_manifest(path: Path) -> bytes:
        with path.open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise SharingError("Hugging Face publication manifest exceeds the size limit")
        return raw

    def publish(self, snapshot: Path, manifest: Manifest, target: Target) -> Reference:
        """
        Commit snapshot files and their manifest as one repository revision.

        Parameters
        ----------
        snapshot : Path
            Immutable staged directory containing the manifest's file paths.
        manifest : Manifest
            Exact staged file inventory.
        target : Target
            A HuggingFaceTarget naming a native dataset or model repository.

        Returns
        -------
        Reference
            Full commit SHA identifying the completed publication.

        Raises
        ------
        SharingError
            On invalid target, missing dependency, provider failure, or a
            concurrent repository update. No completed receipt is returned.
        """
        if not isinstance(target, HuggingFaceTarget):
            raise SharingError("Hugging Face integration requires an hf target")
        raw = manifest.to_bytes()
        if len(raw) > MAX_MANIFEST_BYTES:
            raise SharingError("Hugging Face publication manifest exceeds the size limit")
        with _errors("publication"):
            sdk = _sdk()
            client = self._client()
            client.create_repo(
                repo_id=target.repo_id,
                repo_type=manifest.kind,
                private=target.private,
                exist_ok=True,
            )
            info = client.repo_info(
                repo_id=target.repo_id,
                repo_type=manifest.kind,
                revision=target.revision,
            )
            parent = Reference(
                provider="hf",
                kind=manifest.kind,
                location=target.repo_id,
                revision=_sha(info.sha),
            )
            prior_path = self._manifest_path(parent, optional=True)
            old_paths: set[str] = set()
            if prior_path is not None:
                prior = Manifest.model_validate_json(self._read_manifest(prior_path))
                if prior.kind != manifest.kind:
                    raise SharingError("Hugging Face prior manifest has a different artifact kind")
                old_paths = {entry.path for entry in prior.files}
            new_paths = {entry.path for entry in manifest.files}
            operations = [
                sdk.CommitOperationDelete(path_in_repo=path, is_folder=False)
                for path in sorted(old_paths - new_paths)
            ]
            operations.extend(
                sdk.CommitOperationAdd(
                    path_in_repo=entry.path,
                    path_or_fileobj=snapshot / entry.path,
                )
                for entry in manifest.files
            )
            operations.append(
                sdk.CommitOperationAdd(path_in_repo=MANIFEST_PATH, path_or_fileobj=raw)
            )
            commit = client.create_commit(
                repo_id=target.repo_id,
                repo_type=manifest.kind,
                revision=target.revision,
                parent_commit=parent.revision,
                operations=operations,
                commit_message=f"Publish Hypothex {manifest.kind} {manifest.digest[:12]}",
            )
            return Reference(
                provider="hf",
                kind=manifest.kind,
                location=target.repo_id,
                revision=_sha(commit.oid),
            )

    def load_manifest(self, reference: Reference) -> bytes:
        """
        Read a manifest pinned to a full commit SHA within the metadata limit.

        Parameters
        ----------
        reference : Reference
            Pinned Hub publication.

        Returns
        -------
        bytes
            At most ``MAX_MANIFEST_BYTES`` bytes, for core validation.

        Raises
        ------
        SharingError
            On provider failure, missing manifest, or excessive metadata size.
        """
        _check(reference)
        with _errors("manifest download"):
            path = self._manifest_path(reference)
            if path is None:
                raise SharingError("Hugging Face publication manifest is missing")
            return self._read_manifest(path)

    def download_file(self, reference: Reference, entry: FileEntry, destination: Path) -> None:
        """
        Copy a pinned SDK cache file into the caller's staging destination.

        Parameters
        ----------
        reference : Reference
            Pinned Hub publication.
        entry : FileEntry
            File identity and expected size, checked against pinned provider
            metadata before download; the core verifies its digest.
        destination : Path
            Newly allocated staging path, which must not already exist.

        Raises
        ------
        SharingError
            On provider failure, existing destination, or size mismatch.
        """
        _check(reference)
        with _errors("file download"):
            client = self._client()
            entries = client.get_paths_info(
                repo_id=reference.location,
                paths=[entry.path],
                repo_type=reference.kind,
                revision=reference.revision,
            )
            if len(entries) != 1 or entries[0].path != entry.path:
                raise SharingError("Hugging Face publication file is missing")
            size = getattr(entries[0], "size", None)
            if type(size) is not int or size != entry.size:
                raise SharingError("Hugging Face remote file size does not match the manifest")
            cached = Path(
                client.hf_hub_download(
                    repo_id=reference.location,
                    filename=entry.path,
                    repo_type=reference.kind,
                    revision=reference.revision,
                )
            )
            if cached.stat().st_size != entry.size:
                raise SharingError("Hugging Face downloaded file size does not match the manifest")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with cached.open("rb") as source, destination.open("xb") as output:
                remaining = entry.size
                while remaining:
                    chunk = source.read(min(_COPY_BYTES, remaining))
                    if not chunk:
                        raise SharingError("Hugging Face downloaded file was truncated")
                    output.write(chunk)
                    remaining -= len(chunk)
                if source.read(1):
                    raise SharingError("Hugging Face downloaded file grew during copying")

    def access(self, reference: Reference) -> AccessInfo:
        """
        Inspect current repository visibility without changing permissions.

        Parameters
        ----------
        reference : Reference
            Pinned Hub publication.

        Returns
        -------
        AccessInfo
            Repository privacy and canonical pinned URL. Gating and provider
            authorization still govern access independently of visibility.
        """
        _check(reference)
        with _errors("access inspection"):
            info = self._client().repo_info(
                repo_id=reference.location,
                repo_type=reference.kind,
                revision=reference.revision,
            )
            if type(info.private) is not bool:
                raise SharingError("Hugging Face returned invalid visibility metadata")
            return AccessInfo(
                provider="hf",
                visibility="private" if info.private else "public",
                url=_url(reference),
                details="Hugging Face repository permissions and gated access rules apply.",
            )

    def share(
        self,
        reference: Reference,
        manifest: Manifest,
        file: str | None,
        expires_in: int,
    ) -> ShareLink:
        """
        Return a canonical pinned link governed by existing Hub permissions.

        Parameters
        ----------
        reference : Reference
            Pinned Hub publication.
        manifest : Manifest
            Publication inventory used to validate an optional file selection.
        file : str or None
            File to link, or None for the repository revision.
        expires_in : int
            Ignored: canonical Hub links are not expiring bearer credentials.

        Returns
        -------
        ShareLink
            A token-free tree/blob URL; private recipients must authenticate.
        """
        _check(reference)
        if file is not None and file not in {entry.path for entry in manifest.files}:
            raise SharingError("Selected file is not in the publication manifest")
        return ShareLink(url=_url(reference, file), file=file)

    def set_visibility(self, reference: Reference, *, private: bool) -> AccessInfo:
        """
        Explicitly change visibility for the entire Hub repository.

        Parameters
        ----------
        reference : Reference
            Publication in the repository to update; all revisions are affected.
        private : bool
            Whether the repository should be private.

        Returns
        -------
        AccessInfo
            Fresh provider-reported access information after the update.
        """
        _check(reference)
        with _errors("visibility update"):
            self._client().update_repo_settings(
                repo_id=reference.location,
                repo_type=reference.kind,
                private=private,
            )
            return self.access(reference)
