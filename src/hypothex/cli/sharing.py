"""Provider publishing commands, independent of project/run configuration."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import typer
from pydantic import ValidationError

from hypothex.sharing import service
from hypothex.sharing.models import (
    MAX_MANIFEST_BYTES,
    ArtifactKind,
    HuggingFaceTarget,
    Receipt,
    Reference,
    S3Target,
    SharingError,
    Target,
)

Json = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]
Profile = Annotated[str | None, typer.Option(help="AWS shared-configuration profile.")]
Publication = Annotated[str, typer.Argument(help="Local receipt ID or exported receipt JSON file.")]


def _reference(value: str, home: Path) -> Reference:
    if re.fullmatch(r"[0-9a-f]{64}", value):
        return service.load_receipt(value, home=home).reference
    try:
        with Path(value).expanduser().open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES * 2 + 1)
        if len(raw) > MAX_MANIFEST_BYTES * 2:
            raise SharingError("publication receipt exceeds the size limit")
        receipt = Receipt.model_validate_json(raw)
        if receipt.id != service._receipt_id(receipt.reference, receipt.manifest):
            raise SharingError("publication receipt identity mismatch")
        return receipt.reference
    except (OSError, ValidationError):
        raise SharingError("expected a local receipt ID or exported receipt JSON file") from None


def _target(
    destination: str,
    public: bool,
    revision: str,
    endpoint_url: str | None,
    region: str | None,
) -> Target:
    parsed = urlsplit(destination)
    if parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port:
        raise SharingError("destination must be hf://owner/repo or s3://bucket/prefix")
    if parsed.scheme == "hf":
        if endpoint_url is not None or region is not None:
            raise SharingError("endpoint and region options apply only to S3")
        return HuggingFaceTarget(
            repo_id=parsed.netloc + parsed.path, private=not public, revision=revision
        )
    if parsed.scheme == "s3":
        if public or revision != "main":
            raise SharingError("--public and --revision apply only to Hugging Face")
        return S3Target(
            bucket=parsed.netloc,
            prefix=parsed.path.removeprefix("/").removesuffix("/"),
            endpoint_url=endpoint_url,
            region=region,
        )
    raise SharingError("destination must be hf://owner/repo or s3://bucket/prefix")


def _print(value: Any) -> None:
    typer.echo(json.dumps(value, indent=2))


def create_app(home: Callable[[], Path]) -> typer.Typer:
    """Build the artifact publishing command group.

    Parameters
    ----------
    home : callable
        Reads the top-level CLI's current Hypothex home.

    Returns
    -------
    typer.Typer
        Standalone publish/download/share command group.
    """
    app = typer.Typer(no_args_is_help=True, help="Publish, download and share datasets/models.")

    @app.command("publish")
    def publish_command(
        source: Annotated[Path, typer.Argument(help="Local file or directory to publish.")],
        to: Annotated[str, typer.Option("--to", help="hf://owner/repo or s3://bucket/prefix")],
        kind: Annotated[str, typer.Option(help="dataset or model")],
        public: Annotated[bool, typer.Option(help="Create a new PUBLIC Hub repository.")] = False,
        revision: Annotated[
            str, typer.Option(help="Existing Hub branch (default: main).")
        ] = "main",
        include: Annotated[
            list[str] | None, typer.Option(help="Relative fnmatch pattern; repeatable.")
        ] = None,
        exclude: Annotated[
            list[str] | None, typer.Option(help="Excluded relative pattern; repeatable.")
        ] = None,
        metadata: Annotated[
            list[str] | None, typer.Option(help="Explicit KEY=VALUE provenance; repeatable.")
        ] = None,
        endpoint_url: Annotated[
            str | None, typer.Option(help="S3-compatible endpoint URL.")
        ] = None,
        region: Annotated[str | None, typer.Option(help="S3 region.")] = None,
        profile: Profile = None,
        json_: Json = False,
    ) -> None:
        """Publish a snapshot and save a pinned receipt. Existing Hub visibility is preserved."""
        if kind not in {"dataset", "model"}:
            raise SharingError("artifact kind must be dataset or model")
        artifact_kind: ArtifactKind = "dataset" if kind == "dataset" else "model"
        provenance: dict[str, str] = {}
        for item in metadata or []:
            key, separator, value = item.partition("=")
            if not separator or not key or key in provenance:
                raise SharingError("metadata requires unique, nonempty KEY=VALUE pairs")
            provenance[key] = value
        try:
            target = _target(to, public, revision, endpoint_url, region)
        except ValueError:
            raise SharingError("invalid destination or provider options") from None
        receipt = service.publish(
            source,
            target,
            kind=artifact_kind,
            home=home(),
            include=include or (),
            exclude=exclude or (),
            metadata=provenance,
            profile=profile,
        )
        if json_:
            _print(receipt.model_dump(mode="json"))
        else:
            typer.echo(f"Published {receipt.reference.uri}\nReceipt: {receipt.id}")

    @app.command("list")
    def list_command(json_: Json = False) -> None:
        """List completed local publication receipts."""
        receipts = service.list_receipts(home=home())
        if json_:
            _print([r.model_dump(mode="json") for r in receipts])
        else:
            for receipt in receipts:
                typer.echo(f"{receipt.id}  {receipt.reference.kind}  {receipt.reference.uri}")

    @app.command("show")
    def show_command(
        publication: Annotated[str, typer.Argument(help="Local publication receipt ID.")],
        json_: Json = False,
    ) -> None:
        """Inspect a local receipt; --json exports it for another machine."""
        receipt = service.load_receipt(publication, home=home())
        if json_:
            _print(receipt.model_dump(mode="json"))
        else:
            typer.echo(
                f"{receipt.reference.uri}\n{len(receipt.manifest.files)} files, "
                f"{sum(f.size for f in receipt.manifest.files)} bytes"
            )

    @app.command("download")
    def download_command(
        publication: Publication,
        destination: Annotated[Path, typer.Argument(help="New directory; never overwritten.")],
        max_bytes: Annotated[
            int | None, typer.Option(min=0, help="Maximum total manifest bytes.")
        ] = None,
        profile: Profile = None,
        json_: Json = False,
    ) -> None:
        """Download pinned files, verify SHA-256, then install the complete directory."""
        result = service.download(
            _reference(publication, home()),
            destination,
            profile=profile,
            max_bytes=max_bytes,
        )
        _print({"path": str(result)}) if json_ else typer.echo(str(result))

    @app.command("access")
    def access_command(
        publication: Publication, profile: Profile = None, json_: Json = False
    ) -> None:
        """Inspect Hub visibility or S3 provider-managed access."""
        result = service.access(_reference(publication, home()), profile=profile)
        _print(result.model_dump(mode="json")) if json_ else typer.echo(
            f"{result.visibility}: {result.details}"
        )

    @app.command("share")
    def share_command(
        publication: Publication,
        file: Annotated[
            str | None, typer.Option(help="Manifest-relative file (required for multi-file S3).")
        ] = None,
        expires_in: Annotated[
            int, typer.Option(min=1, max=604800, help="S3 link lifetime in seconds.")
        ] = 3600,
        profile: Profile = None,
        json_: Json = False,
    ) -> None:
        """Print a pinned Hub URL or temporary S3 bearer URL; never saves signed links."""
        result = service.share(
            _reference(publication, home()),
            file=file,
            expires_in=expires_in,
            profile=profile,
        )
        _print(result.model_dump(mode="json")) if json_ else typer.echo(result.url)

    @app.command("visibility")
    def visibility_command(
        publication: Publication,
        visibility: Annotated[
            str, typer.Argument(help="private or public; applies to the ENTIRE Hub repo.")
        ],
        json_: Json = False,
    ) -> None:
        """Explicitly change repository-wide Hub visibility, including all revisions."""
        if visibility not in {"private", "public"}:
            raise SharingError("visibility must be private or public")
        result = service.set_visibility(
            _reference(publication, home()), private=visibility == "private"
        )
        _print(result.model_dump(mode="json")) if json_ else typer.echo(result.visibility)

    return app
