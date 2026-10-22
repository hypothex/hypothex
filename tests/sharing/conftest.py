"""Keep publication tests away from personal provider credentials."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_provider_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in os.environ:
        if name.startswith(("AWS_", "HF_", "HUGGING_FACE_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
