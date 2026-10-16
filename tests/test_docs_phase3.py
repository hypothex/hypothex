"""The phase 3 docs pages exist, are in the toctree, and name what a user needs."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PAGES = {
    "team": ("hx pair", "hx login", "hx sessions", "auth: on", "hx serve --auth --tailscale",
             "hx hosts pair", "hx db upgrade", "index_url", "owner", "need admin"),
    "notifications": ("webhook_env", "password_env", "secrets.env", "chmod 600", "hx notify test",
                      "fold_sweeps", "min_seconds", "digest", "max_age_hours"),
    "export": ("hx export", "--format latex", "booktabs", "--noise", "baselines",
               "metric_version_equivalent", "mean ± std"),
    "storage": ("hx storage report", "hx storage clean --archived", "--apply", "protected",
                "used by", "changed since plan", "never through MCP"),
}  # fmt: skip


def test_pages_are_in_the_toctree_after_remote() -> None:
    index = (DOCS / "index.rst").read_text()
    assert "   remote\n   team\n   notifications\n   export\n   storage\n" in index


def test_pages_name_what_a_user_needs() -> None:
    for page, needles in PAGES.items():
        text = (DOCS / f"{page}.rst").read_text()
        for needle in needles:
            assert needle in text, (page, needle)


def test_cli_page_lists_the_new_commands() -> None:
    text = (DOCS / "cli.rst").read_text()
    for command in ("hx export", "hx note --project", "hx notebook show", "hx digest",
                    "hx notify status", "hx storage clean", "hx pair", "hx login", "hx whoami",
                    "hx users", "hx db upgrade", "hx hosts pair"):  # fmt: skip
        assert command in text, command


def test_skill_teaches_team_and_output() -> None:
    text = (ROOT / "skills" / "hypothex" / "SKILL.md").read_text()
    for needle in ("## Team and output", "hx export", "hx note --project", "hx digest",
                   "`export_table`", "`add_notebook_entry`", "`plan_storage_clean`",
                   "Never apply a storage cleanup"):  # fmt: skip
        assert needle in text, needle
