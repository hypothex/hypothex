"""The Web UI docs page is in the toctree and names what a user needs."""

from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_ui_page_is_in_toctree_after_views() -> None:
    index = (DOCS / "index.rst").read_text()
    assert "   views\n   ui\n" in index


def test_ui_page_covers_screens_build_dev_and_e2e() -> None:
    page = (DOCS / "ui.rst").read_text()
    for screen in ("Overview", "Task", "Run", "Examples", "View editor"):
        assert f"**{screen}**" in page, screen
    for route in ("/t/<project>/<task>?view=<name>", "/r/<run_id>", "/x/<a>/<b>?metric=<name>"):
        assert route in page, route
    for command in (
        "hx serve",
        "bun run build",
        "uv build",
        "bun run dev",
        "HX_API",
        "bun test",
        "bunx playwright test",
        "HX_E2E_PORT",
    ):
        assert command in page, command


def test_ui_page_covers_phase2_screens() -> None:
    page = (DOCS / "ui.rst").read_text()
    for screen in ("Hosts", "Launch dialog", "Sweep"):
        assert f"**{screen}**" in page, screen
    for text in (
        "/s/<project>/<sweep_id>",
        "Copy as CLI",
        "Cancel queued",
        "Add seeds",
        "Rerun sweep",
        "wait for GPUs",
        "CUDA_VISIBLE_DEVICES",
        "stale",
        "stale_banner_hours",
        "GPU-h",
        ":doc:`remote`",
        "hx demo --with-hosts",
        "free port",
        "HYPOTHEX_SSH=false",
        "environment.json",
        "run.lost",
        "shutdown-check.ts",
        "Resend seed N",
        "archived runs",
        "ui/e2e/.runs/run-XXXXXX",
        "HX_E2E_RUN_DIR",
    ):
        assert text in page, text
