"""The Web UI docs page is in the toctree and names what a user needs in UI v5."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
UI = ROOT / "ui" / "src"
SHOTS = ("home", "task", "eval", "runs", "run", "sweep")


def _page() -> str:
    return (DOCS / "ui.rst").read_text()


def test_ui_page_is_in_toctree_after_views() -> None:
    index = (DOCS / "index.rst").read_text()
    assert "   views\n   ui\n" in index


def test_ui_page_covers_v5_screens_and_routes() -> None:
    page = _page()
    for screen in (
        "Home",
        "Task",
        "Charts",
        "Runs",
        "Sweeps",
        "Run",
        "Hosts",
        "Queue",
        "Examples",
        "View editor",
        "Launch dialog",
    ):
        assert f"**{screen}**" in page, screen
    for route in (
        "/t/<project>/<task>?tab=<tab>",
        "/t/<project>/<task>/edit/<view>",
        "/r/<run_id>?tab=<tab>",
        "/s/<project>/<sweep_id>",
        "/x/<a>/<b>?metric=<name>",
        "/hosts",
        "/queue",
    ):
        assert route in page, route
    # v4 screens are gone, not documented
    for gone in ("**Overview**", "lettered", "Ideas are grouped"):
        assert gone not in page, gone


def test_ui_page_names_every_task_and_run_tab() -> None:
    page = _page()
    for tab in ("charts", "runs", "sweeps", "examples", "view:<name>"):
        assert f"``{tab}``" in page, tab
    labels = re.findall(r'^\s+\w+: "(\w+)",$', (UI / "run" / "runContext.ts").read_text(), re.M)
    assert labels == ["Overview", "Charts", "Logs", "Files", "Examples"]
    for label in labels:
        assert f"``{label}``" in page, label


def test_ui_page_filter_table_matches_run_filter() -> None:
    page = _page()
    source = (UI / "lib" / "runFilter.ts").read_text()
    fields = re.findall(r'case "(\w+)":', source)
    assert fields == ["tag", "status", "by", "name"]
    for field in fields:
        assert f"``{field}:" in page, field
    for form in ("``lr=3e-4``", "``lr = 3e-4``", "``model!=resnet*``", "``*``"):
        assert form in page, form


def test_ui_page_names_every_selection_url_key() -> None:
    page = _page()
    source = (UI / "task" / "useRunSelection.ts").read_text()
    keys = sorted(set(re.findall(r'params\.get\("(\w+)"\)', source)))
    assert keys == ["col", "filter", "group", "hide", "sort", "sup"]
    for key in keys:
        assert f"``{key}=" in page, key


def test_ui_page_covers_colour_compare_rename_and_keyboard() -> None:
    page = _page()
    for text in (
        "9th",
        "neutral",
        "score_keys",
        ":doc:`project_file`",
        "``compare``",
        ":doc:`views`",
        "Table | Bars",
        "Save as view",
        "+ Panel",
        "By config",
        "Each run",
        "superseded",
        "N/M shown",
        "Reset name",
        "hx rename",
        "rename_run",
        "POST /api/v1/runs/{run_id}/name",
        "GET /api/v1/tasks/{project}/{task}/runs",
        "1–80",
        "⌘K",
        "⌘.",
        "Escape",
        "Enter",
    ):
        assert text in page, text


def test_ui_page_covers_hosts_queue_sweeps_launch_and_run_details() -> None:
    page = _page()
    for text in (
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
        "run.lost",
        "Resend seed N",
        "archived runs",
        "Re-infer",
        "Re-evaluate",
        "Reconnect",
        "Reload",
    ):
        assert text in page, text


def test_ui_page_covers_build_dev_and_e2e() -> None:
    page = _page()
    for command in (
        "hx serve",
        "bun run build",
        "uv build",
        "bun run dev",
        "HX_API",
        "bun test",
        "bunx playwright test",
        "HX_E2E_PORT",
        "hx demo --with-hosts",
        "free port",
        "HYPOTHEX_SSH=false",
        "environment.json",
        "shutdown-check.ts",
        "ui/e2e/.runs/run-XXXXXX",
        "HX_E2E_RUN_DIR",
        "scripts/screenshots.ts",
    ):
        assert command in page, command


def test_ui_page_embeds_every_light_screenshot_and_files_exist() -> None:
    page = _page()
    for name in SHOTS:
        assert f".. image:: _static/ui/{name}-light.png" in page, name
        for theme in ("light", "dark"):
            assert (DOCS / "_static" / "ui" / f"{name}-{theme}.png").is_file(), (name, theme)
    script = (ROOT / "ui" / "scripts" / "screenshots.ts").read_text()
    for name in SHOTS:
        assert f"{name}:" in script, name


def test_readme_shows_the_task_screenshot() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "](docs/_static/ui/task-light.png)" in readme
    assert "Overview with" not in readme
