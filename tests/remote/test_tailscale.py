from pathlib import Path

import pytest

from hypothex.remote.tailscale import (
    TailscaleError,
    serve_https,
    tailscale_bin,
    tailscale_dns_name,
    unserve,
)
from tests.fakes import install_fake_tailscale


def test_dns_name_without_the_trailing_dot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = install_fake_tailscale(tmp_path, monkeypatch)
    assert tailscale_bin() == fake.bin
    assert tailscale_dns_name() == "hub.tail1234.ts.net"


def test_logged_out_names_tailscale_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_tailscale(tmp_path, monkeypatch, logged_in=False)
    with pytest.raises(TailscaleError, match="tailscale up"):
        tailscale_dns_name()
    with pytest.raises(TailscaleError, match="tailscale up"):
        serve_https(7777)


def test_serve_and_unserve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = install_fake_tailscale(tmp_path, monkeypatch)
    assert serve_https(51234) == "https://hub.tail1234.ts.net"
    assert fake.state()["serve"] == {"443": "http://127.0.0.1:51234"}
    assert serve_https(51235, https_port=8443) == "https://hub.tail1234.ts.net:8443"
    unserve()
    assert fake.state()["serve"] == {"8443": "http://127.0.0.1:51235"}
    assert ["serve", "--https=443", "off"] in fake.state()["calls"]


def test_missing_or_refusing_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(TailscaleError):
        tailscale_dns_name()  # the session's refusing stub
    monkeypatch.setenv("HYPOTHEX_TAILSCALE", str(tmp_path / "not-there"))
    with pytest.raises(TailscaleError, match="not installed"):
        tailscale_dns_name()


def test_tailscale_timeout_is_a_domain_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A subprocess timeout becomes a bounded user-facing error."""
    import subprocess
    from typing import Any

    def timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(TailscaleError, match="gave no answer in 0.1s"):
        tailscale_dns_name(timeout=0.1)


def test_invalid_status_json_is_a_domain_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A command returning non-JSON output reports how to recover."""
    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "bad", "")
    )
    with pytest.raises(TailscaleError, match="gave no JSON; run tailscale up"):
        tailscale_dns_name()
