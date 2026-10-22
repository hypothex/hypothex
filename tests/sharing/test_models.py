"""Malformed remote inventories cannot escape a download staging directory."""

import pytest
from pydantic import ValidationError

from hypothex.sharing import FileEntry, HuggingFaceTarget, Manifest, Reference, S3Target


@pytest.mark.parametrize(
    "path",
    [
        "/absolute",
        "../escape",
        "a/../b",
        "a//b",
        "a/./b",
        "a\\b",
        "x:y",
        "a\x00b",
        ".hypothex/manifest.json",
        ".HYPOTHEX/x",
        "",
    ],
)
def test_invalid_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        FileEntry(path=path, size=1, sha256="0" * 64)


@pytest.mark.parametrize("paths", [("a", "a"), ("a", "A"), ("a", "a/b"), ("a", "A/b")])
def test_collisions(paths: tuple[str, str]) -> None:
    with pytest.raises(ValidationError):
        Manifest(
            kind="dataset", files=tuple(FileEntry(path=p, size=0, sha256="0" * 64) for p in paths)
        )


def test_canonical_encoding_and_metadata_bounds() -> None:
    entry = FileEntry(path="weights.bin", size=4, sha256="1" * 64)
    first = Manifest(kind="model", files=(entry,), metadata={"b": "2", "a": "1"})
    second = Manifest(kind="model", files=(entry,), metadata={"a": "1", "b": "2"})
    assert first.to_bytes() == second.to_bytes()
    assert first.digest == second.digest
    with pytest.raises(ValidationError):
        Manifest(kind="model", files=(entry,), metadata={"k": "x" * 4097})


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:password@host",
        "https://host?token=secret",
        "https://host#fragment",
        "file:///tmp/object",
    ],
)
def test_endpoint_cannot_embed_credentials(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        S3Target(bucket="artifacts", endpoint_url=endpoint)


def test_pinned_references_and_private_default() -> None:
    assert HuggingFaceTarget(repo_id="org/repo").private
    with pytest.raises(ValidationError):
        Reference(provider="hf", kind="model", location="org/repo", revision="main")
    with pytest.raises(ValidationError):
        Reference(provider="s3", kind="dataset", location="artifacts", revision="latest")
    assert (
        Reference(provider="hf", kind="model", location="org/repo", revision="a" * 40).uri
        == f"hf://models/org/repo@{'a' * 40}"
    )
    assert (
        Reference(
            provider="s3", kind="model", location="artifacts", prefix="models", revision="b" * 64
        ).uri
        == f"s3://artifacts/models/{'b' * 64}"
    )
