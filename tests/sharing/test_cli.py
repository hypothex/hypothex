"""User-visible publishing flow using controlled storage and the real Typer app."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hypothex.cli.main import app
from hypothex.sharing import Receipt, SharingError, service
from hypothex.sharing.models import Reference, Target
from tests.sharing.test_service import MemoryProvider

runner = CliRunner()


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> MemoryProvider:
    adapter = MemoryProvider()

    def factory(target: Target | Reference, *, profile: str | None = None) -> MemoryProvider:
        return adapter

    monkeypatch.setattr(service, "get_provider", factory)
    return adapter


@pytest.mark.parametrize("destination", ["hf://team/data", "s3://artifacts/data"])
def test_publish_export_download_and_inspect(
    home: Path, tmp_path: Path, provider: MemoryProvider, destination: str
) -> None:
    source = tmp_path / "rows.jsonl"
    source.write_text('{"label": 1}\n')
    result = runner.invoke(
        app,
        [
            "--home",
            str(home),
            "artifacts",
            "publish",
            str(source),
            "--kind",
            "dataset",
            "--to",
            destination,
            "--metadata",
            "project=example",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    receipt = Receipt.model_validate_json(result.output)
    for command in ("list", "show", "access"):
        arguments = ["artifacts", command]
        if command != "list":
            arguments.append(receipt.id)
        result = runner.invoke(app, [*arguments, "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)
    exported = tmp_path / "receipt.json"
    shown = runner.invoke(app, ["artifacts", "show", receipt.id, "--json"])
    exported.write_text(shown.output)
    target = tmp_path / "download"
    result = runner.invoke(
        app,
        [
            "--home",
            str(tmp_path / "another-home"),
            "artifacts",
            "download",
            str(exported),
            str(target),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["path"] == str(target)
    assert (target / source.name).read_bytes() == source.read_bytes()
    result = runner.invoke(
        app,
        ["artifacts", "share", receipt.id, "--file", source.name, "--expires-in", "60", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["file"] == source.name
    if destination.startswith("hf:"):
        result = runner.invoke(app, ["artifacts", "visibility", receipt.id, "public", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["visibility"] == "public"


@pytest.mark.parametrize(
    "args",
    [
        ["--kind", "weights", "--to", "hf://team/repo"],
        ["--kind", "model", "--to", "https://example.invalid/repo"],
        ["--kind", "model", "--to", "s3://bucket/prefix", "--public"],
        ["--kind", "model", "--to", "hf://team/repo", "--endpoint-url", "https://example.invalid"],
        ["--kind", "model", "--to", "hf://team/repo", "--metadata", "no-equals"],
    ],
)
def test_invalid_publish_never_uploads(
    home: Path, tmp_path: Path, provider: MemoryProvider, args: list[str]
) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"test")
    result = runner.invoke(app, ["artifacts", "publish", str(source), *args])
    assert result.exit_code != 0
    assert isinstance(result.exception, SharingError)
    assert provider.publish_calls == 0


def test_help_includes_workflow_without_loading_sdks(home: Path) -> None:
    result = runner.invoke(app, ["artifacts", "--help"])
    assert result.exit_code == 0
    for command in ("publish", "download", "list", "show", "access", "share", "visibility"):
        assert command in result.output
