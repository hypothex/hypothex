"""S3 publication and bounded transfers without changing access policies.

The optional boto3 SDK is loaded only when a transfer or signed link is requested.
Bucket policies, IAM rules and ACLs remain under the bucket owner's control.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from hypothex.sharing.models import (
    MANIFEST_PATH,
    MAX_MANIFEST_BYTES,
    AccessInfo,
    FileEntry,
    Manifest,
    Reference,
    S3Target,
    ShareLink,
    SharingError,
    Target,
)


class _BoundedWriter:
    """Expose sequential writes so managed downloads cannot exceed the inventory."""

    def __init__(self, stream: BinaryIO, limit: int) -> None:
        self.stream = stream
        self.limit = limit
        self.written = 0

    def write(self, data: bytes) -> int:
        if self.written + len(data) > self.limit:
            raise SharingError("S3 file exceeds its declared manifest size")
        count = self.stream.write(data)
        self.written += count
        return count


def _reference(reference: Reference) -> None:
    if reference.provider != "s3":
        raise SharingError("S3 provider requires an S3 reference")


def _key(reference: Reference, path: str) -> str:
    key = "/".join(part for part in (reference.prefix, reference.revision, path) if part)
    if len(key.encode("utf-8")) > 1024:
        raise SharingError("S3 object key exceeds the 1024-byte limit; shorten the prefix or path")
    return key


def _native_endpoint(endpoint: str | None) -> bool:
    if not isinstance(endpoint, str):
        return False
    parts = urlsplit(endpoint)
    hostname = parts.hostname or ""
    if parts.scheme != "https" or parts.netloc != hostname or parts.path not in ("", "/"):
        return False
    return (
        re.fullmatch(r"s3(?:[.-][a-z]{2}(?:-[a-z]+)+-\d+)?\.amazonaws\.com(?:\.cn)?", hostname)
        is not None
    )


class S3Provider:
    """
    Publish content-addressed files through the optional boto3 SDK.

    Parameters
    ----------
    client : object, optional
        Injected S3-compatible boto3 client, principally for controlled tests.
    profile : str, optional
        AWS credential/configuration profile. Credentials are resolved by boto3.
    endpoint_url : str, optional
        Default S3-compatible endpoint; explicit target/reference settings win.
    region : str, optional
        Default signing region; explicit target/reference settings win.

    Notes
    -----
    This adapter never sets object ACLs or changes bucket policies. Content
    lives at ``<prefix>/<manifest digest>/files/<path>``. The canonical manifest
    is uploaded last at ``<prefix>/<digest>/.hypothex/manifest.json``.

    Examples
    --------
    >>> provider = S3Provider(profile="research")
    """

    def __init__(
        self,
        client: Any | None = None,
        *,
        profile: str | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        try:
            S3Target(bucket="validation-bucket", endpoint_url=endpoint_url, region=region)
        except ValueError:
            raise SharingError("S3 endpoint and region settings are invalid") from None
        self._injected = client
        self._profile = profile
        self._endpoint = endpoint_url
        self._region = region
        self._clients: dict[tuple[str | None, str | None], Any] = {}
        self._signing_clients: dict[str, Any] = {}
        self._session: Any | None = None

    def _options(self, location: S3Target | Reference) -> tuple[str | None, str | None]:
        return location.endpoint_url or self._endpoint, location.region or self._region

    def _client(self, location: S3Target | Reference) -> Any:
        if self._injected is not None:
            return self._injected
        options = self._options(location)
        if options not in self._clients:
            try:
                import boto3
                from botocore.config import Config
            except ImportError:
                raise SharingError(
                    "S3 sharing requires the optional SDK; install hypothex[s3] "
                    "(or run uv sync --extra s3 in a source checkout)"
                ) from None
            try:
                if self._session is None:
                    self._session = boto3.Session(profile_name=self._profile)
                self._clients[options] = self._session.client(
                    "s3",
                    endpoint_url=options[0],
                    region_name=options[1],
                    config=Config(signature_version="s3v4"),
                )
            except Exception:
                raise SharingError(
                    "Cannot initialize S3; check SDK credentials and settings"
                ) from None
        return self._clients[options]

    def _signing_client(self, reference: Reference) -> tuple[Any, str | None]:
        client = self._client(reference)
        if not _native_endpoint(getattr(getattr(client, "meta", None), "endpoint_url", None)):
            return client, None
        try:
            response = client.head_bucket(Bucket=reference.location)
        except Exception as error:
            # HeadBucket reports the bucket region even when access is denied.
            # This does not require granting ListBucket merely to sign a GET.
            response = getattr(error, "response", {})
        if not isinstance(response, dict):
            response = {}
        metadata = response.get("ResponseMetadata", {})
        headers = metadata.get("HTTPHeaders", {}) if isinstance(metadata, dict) else {}
        region = response.get("BucketRegion") or (
            headers.get("x-amz-bucket-region") if isinstance(headers, dict) else None
        )
        if not isinstance(region, str) or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", region):
            raise SharingError("Cannot resolve the S3 bucket region for link signing")
        if self._injected is not None:
            if client.meta.region_name != region:
                raise SharingError(
                    "S3 bucket region differs from the injected client; "
                    "inject a client configured for the bucket region and regional endpoint"
                )
            return client, region
        if region not in self._signing_clients:
            from botocore.config import Config

            try:
                assert self._session is not None
                # Explicit virtual addressing disables boto3's global presign
                # endpoint. The SDK safely falls back to paths for dotted buckets.
                self._signing_clients[region] = self._session.client(
                    "s3",
                    region_name=region,
                    config=Config(
                        signature_version="s3v4",
                        ignore_configured_endpoint_urls=True,
                        s3={
                            "addressing_style": "virtual",
                            "us_east_1_regional_endpoint": "regional",
                        },
                    ),
                )
            except Exception:
                raise SharingError("Cannot initialize the regional S3 signing client") from None
        return self._signing_clients[region], region

    def publish(self, snapshot: Path, manifest: Manifest, target: Target) -> Reference:
        """
        Upload staged files, then publish their completion manifest.

        Parameters
        ----------
        snapshot : Path
            Core-owned immutable staging directory containing the manifest files.
        manifest : Manifest
            Complete inventory of the exact staged bytes.
        target : Target
            S3 bucket, prefix and optional connection settings.

        Returns
        -------
        Reference
            Location pinned to the manifest SHA-256, including the SDK's effective
            endpoint and region (also when supplied by environment or profile).

        Raises
        ------
        SharingError
            Wrong provider, oversized manifest/key, unavailable SDK or failed upload.

        Notes
        -----
        Uploads use boto3's managed multipart-capable transfer. Identical retries
        write identical keys and bytes; unrelated keys are never deleted. A failed
        file transfer never publishes a completion marker. Metadata is descriptive,
        not a substitute for verification of downloaded bytes.
        """
        if not isinstance(target, S3Target):
            raise SharingError("S3 provider requires an S3 target")
        contents = manifest.to_bytes()
        if len(contents) > MAX_MANIFEST_BYTES:
            raise SharingError("S3 manifest exceeds the supported size limit")
        client = self._client(target)
        endpoint, region = self._options(target)
        # The SDK also discovers endpoints/regions in environment and profiles.
        # Persist what it actually selected so a later reader cannot drift to
        # another bucket namespace merely because its ambient settings differ.
        meta = getattr(client, "meta", None)
        actual_endpoint = getattr(meta, "endpoint_url", None)
        actual_region = getattr(meta, "region_name", None)
        if isinstance(actual_endpoint, str):
            endpoint = actual_endpoint
        if isinstance(actual_region, str):
            region = actual_region
        try:
            reference = Reference(
                provider="s3",
                kind=manifest.kind,
                location=target.bucket,
                revision=manifest.digest,
                prefix=target.prefix,
                endpoint_url=endpoint,
                region=region,
            )
        except ValueError:
            raise SharingError("S3 SDK resolved invalid endpoint or region settings") from None
        marker = _key(reference, MANIFEST_PATH)
        keys = [_key(reference, f"files/{entry.path}") for entry in manifest.files]
        try:
            for entry, key in zip(manifest.files, keys, strict=True):
                client.upload_file(
                    Filename=str(snapshot / entry.path),
                    Bucket=target.bucket,
                    Key=key,
                    ExtraArgs={"Metadata": {"sha256": entry.sha256}},
                )
            client.put_object(
                Bucket=target.bucket,
                Key=marker,
                Body=contents,
                ContentType="application/json",
            )
        except Exception:
            raise SharingError(
                "S3 upload failed; check credentials and bucket permissions"
            ) from None
        return reference

    def load_manifest(self, reference: Reference) -> bytes:
        """
        Read a pinned manifest with a strict response-size bound.

        Parameters
        ----------
        reference : Reference
            S3 publication whose revision is the manifest digest.

        Returns
        -------
        bytes
            At most ``MAX_MANIFEST_BYTES`` bytes; the core validates their digest.

        Raises
        ------
        SharingError
            Unavailable SDK, wrong provider, unreadable or oversized response.
        """
        _reference(reference)
        key = _key(reference, MANIFEST_PATH)
        client = self._client(reference)
        try:
            response = client.get_object(Bucket=reference.location, Key=key)
            body = response["Body"]
            try:
                if response.get("ContentLength", 0) > MAX_MANIFEST_BYTES:
                    raise SharingError("S3 manifest exceeds the supported size limit")
                contents = body.read(MAX_MANIFEST_BYTES + 1)
                if not isinstance(contents, bytes) or len(contents) > MAX_MANIFEST_BYTES:
                    raise SharingError("S3 manifest exceeds the supported size limit")
            finally:
                body.close()
        except SharingError:
            raise
        except Exception:
            raise SharingError(
                "S3 manifest read failed; check credentials and bucket permissions"
            ) from None
        return contents

    def download_file(self, reference: Reference, entry: FileEntry, destination: Path) -> None:
        """
        Download one pinned object into a new, size-bounded staging file.

        Parameters
        ----------
        reference : Reference
            S3 publication to fetch.
        entry : FileEntry
            Expected file path and size from its verified manifest.
        destination : Path
            New staging file; its parent directory must already exist.

        Raises
        ------
        SharingError
            Failed transfer, existing destination, or bytes exceeding/falling short
            of the declared size. The core discards partial staging and verifies
            the full SHA-256 before installing the result.
        """
        _reference(reference)
        key = _key(reference, f"files/{entry.path}")
        client = self._client(reference)
        try:
            with destination.open("xb") as output:
                writer = _BoundedWriter(output, entry.size)
                client.download_fileobj(Bucket=reference.location, Key=key, Fileobj=writer)
                if writer.written != entry.size:
                    raise SharingError("S3 file size does not match its manifest")
        except SharingError:
            raise
        except Exception:
            raise SharingError(
                "S3 download failed; check credentials and bucket permissions"
            ) from None

    def access(self, reference: Reference) -> AccessInfo:
        """
        Describe S3's access model without guessing effective visibility.

        Parameters
        ----------
        reference : Reference
            S3 publication being inspected.

        Returns
        -------
        AccessInfo
            Provider-managed access; no ACL or policy inspection/change is made.
        """
        _reference(reference)
        return AccessInfo(
            provider="s3",
            visibility="provider-managed",
            details="Access is controlled by IAM, bucket policies and object settings. "
            "Effective access has not been evaluated; no policies or ACLs were changed.",
        )

    def share(
        self, reference: Reference, manifest: Manifest, file: str | None, expires_in: int
    ) -> ShareLink:
        """
        Create a temporary GET-only bearer link for one manifest entry.

        Parameters
        ----------
        reference : Reference
            Pinned S3 publication.
        manifest : Manifest
            Verified manifest matching the reference revision and kind.
        file : str or None
            Exact manifest path; omission is valid only for a single-file manifest.
        expires_in : int
            Requested expiry in seconds, from 1 through 604800 inclusive.

        Returns
        -------
        ShareLink
            Signed URL marked as a bearer credential. Temporary SDK credentials
            may expire before the requested link lifetime.

        Raises
        ------
        SharingError
            Invalid selection/expiry, mismatched manifest or failed signing.

        Notes
        -----
        Standard public AWS endpoints resolve the bucket region with HeadBucket
        before signing at its regional endpoint. Region headers from denied HEAD
        responses are sufficient. Injected clients must already use that region
        and produce regional URLs. Custom endpoints retain their configured route.
        """
        _reference(reference)
        if type(expires_in) is not int or not 1 <= expires_in <= 604800:
            raise SharingError("S3 link expiry must be an integer from 1 to 604800 seconds")
        if manifest.digest != reference.revision or manifest.kind != reference.kind:
            raise SharingError("S3 reference does not match the supplied manifest")
        if file is None:
            if len(manifest.files) != 1:
                raise SharingError(
                    "S3 sharing requires --file for a publication with multiple files"
                )
            file = manifest.files[0].path
        if file not in {entry.path for entry in manifest.files}:
            raise SharingError("Selected file is not in the publication manifest")
        key = _key(reference, f"files/{file}")
        client, bucket_region = self._signing_client(reference)
        try:
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": reference.location, "Key": key},
                ExpiresIn=expires_in,
                HttpMethod="GET",
            )
            if bucket_region is not None:
                host = urlsplit(url).hostname or ""
                regional_hosts = (
                    f"s3.{bucket_region}.amazonaws.com",
                    f"s3.{bucket_region}.amazonaws.com.cn",
                    f"s3-{bucket_region}.amazonaws.com",
                )
                if not any(host == name or host.endswith(f".{name}") for name in regional_hosts):
                    raise SharingError(
                        "S3 signing requires a regional endpoint; "
                        "inject a client configured for the bucket region and regional endpoint"
                    )
            return ShareLink(url=url, file=file, expires_in=expires_in, bearer=True)
        except SharingError:
            raise
        except Exception:
            raise SharingError(
                "S3 link signing failed; check SDK credentials and settings"
            ) from None

    def set_visibility(self, reference: Reference, *, private: bool) -> AccessInfo:
        """
        Refuse visibility changes; S3 permissions stay with the bucket owner.

        Parameters
        ----------
        reference : Reference
            S3 publication.
        private : bool
            Requested visibility, unsupported for either value.

        Raises
        ------
        SharingError
            Always: configure IAM/bucket policies separately, or share a signed link.
        """
        _reference(reference)
        raise SharingError("S3 visibility is managed by IAM and bucket policies; use a signed link")
