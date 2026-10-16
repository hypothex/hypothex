"""Tailscale HTTPS for the hub: ``tailscale serve`` in front of 127.0.0.1 (no relay)."""

from __future__ import annotations

import json
import os
import subprocess

from hypothex.core.errors import HypothexError

SERVE_TIMEOUT_SECONDS = 30.0


class TailscaleError(HypothexError):
    """``tailscale`` is missing, logged out, or failed."""


def tailscale_bin() -> str:
    """
    Return the ``tailscale`` program to run.

    Returns
    -------
    str
        ``$HYPOTHEX_TAILSCALE`` (tests point it at a fake), else ``tailscale``.
    """
    return os.environ.get("HYPOTHEX_TAILSCALE") or "tailscale"


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [tailscale_bin(), *args], capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        raise TailscaleError(
            "tailscale is not installed; install it, then run tailscale up"
        ) from None
    except subprocess.TimeoutExpired:
        raise TailscaleError(f"tailscale {args[0]} gave no answer in {timeout:g}s") from None


def _why(proc: subprocess.CompletedProcess[str]) -> str:
    lines = [line.strip() for line in proc.stderr.splitlines() if line.strip()]
    return lines[-1][:200] if lines else f"exit {proc.returncode}"


def tailscale_dns_name(*, timeout: float = 10) -> str:
    """
    Return this node's MagicDNS name.

    Parameters
    ----------
    timeout : float
        Seconds.

    Returns
    -------
    str
        E.g. ``hub.tail1234.ts.net`` (no trailing dot).

    Raises
    ------
    TailscaleError
        Not installed, failed, or logged out (names ``tailscale up``).
    """
    proc = _run(["status", "--json"], timeout)
    if proc.returncode != 0:
        raise TailscaleError(f"tailscale status failed ({_why(proc)}); run tailscale up")
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise TailscaleError("tailscale status --json gave no JSON; run tailscale up") from None
    name = str((data.get("Self") or {}).get("DNSName") or "").rstrip(".")
    if data.get("BackendState") != "Running" or not name:
        raise TailscaleError("tailscale is logged out; run tailscale up")
    return name


def serve_https(port: int, *, https_port: int = 443) -> str:
    """
    Publish ``http://127.0.0.1:<port>`` on the tailnet over HTTPS.

    Parameters
    ----------
    port : int
        The hub's local port.
    https_port : int
        The tailnet port.

    Returns
    -------
    str
        ``https://<dns name>`` (``:<https_port>`` when not 443): the hub's public URL.

    Raises
    ------
    TailscaleError
    """
    name = tailscale_dns_name()
    target = f"http://127.0.0.1:{port}"
    proc = _run(["serve", "--bg", f"--https={https_port}", target], SERVE_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise TailscaleError(f"tailscale serve failed ({_why(proc)}); run tailscale up")
    return f"https://{name}" if https_port == 443 else f"https://{name}:{https_port}"


def unserve(https_port: int = 443) -> None:
    """
    Remove the HTTPS mapping ``serve_https`` set.

    Parameters
    ----------
    https_port : int

    Raises
    ------
    TailscaleError
    """
    proc = _run(["serve", f"--https={https_port}", "off"], SERVE_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise TailscaleError(f"tailscale serve off failed ({_why(proc)})")
