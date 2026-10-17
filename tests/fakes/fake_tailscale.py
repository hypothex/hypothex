"""
Fake ``tailscale`` CLI for tests (never a real tailnet).

State lives in the JSON file named by ``HYPOTHEX_FAKE_TAILSCALE_STATE``:
``{"logged_in": bool, "dns_name": str, "serve": {"443": "http://..."}, "calls": [[...]]}``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    """Answer ``status --json`` and ``serve`` like tailscale does; record every call."""
    path = Path(os.environ["HYPOTHEX_FAKE_TAILSCALE_STATE"])
    state = json.loads(path.read_text())
    state.setdefault("calls", []).append(argv)
    code = 0
    if argv[:2] == ["status", "--json"]:
        backend = "Running" if state.get("logged_in") else "NeedsLogin"
        name = state.get("dns_name", "") if state.get("logged_in") else ""
        print(json.dumps({"BackendState": backend, "Self": {"DNSName": name}}))
    elif argv[:1] == ["serve"] and not state.get("logged_in"):
        print("Logged out.", file=sys.stderr)
        code = 1
    elif argv[:2] == ["serve", "--bg"] and len(argv) == 4 and argv[2].startswith("--https="):
        state.setdefault("serve", {})[argv[2].removeprefix("--https=")] = argv[3]
    elif argv[:1] == ["serve"] and len(argv) == 3 and argv[2] == "off":
        state.setdefault("serve", {}).pop(argv[1].removeprefix("--https="), None)
    else:
        print(f"fake tailscale: unsupported {argv}", file=sys.stderr)
        code = 2
    path.write_text(json.dumps(state))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
