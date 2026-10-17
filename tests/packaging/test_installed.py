"""Mandatory installed-wheel acceptance, selected explicitly with -m package."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.packaging.runner import PackageRun

pytestmark = pytest.mark.package


@pytest.fixture(scope="session")
def installed() -> Iterator[PackageRun]:
    """Build one external default-only installation and always clean its owned resources.

    Yields
    ------
    PackageRun
        Isolated installed-wheel harness and sanitized evidence owner.
    """
    run = PackageRun.create(checkout=Path(__file__).resolve().parents[2])
    try:
        run.prepare()
        yield run
    except BaseException as original:
        try:
            run.close()
        except Exception as cleanup:
            original.add_note(f"Package cleanup also failed: {run.redact(str(cleanup))}")
        raise
    else:
        run.close()


def test_wheel_import_resources_and_migration(installed: PackageRun) -> None:
    """Require wheel imports, complete assets, default dependency closure, and migration head."""
    installed.check_resources()


def test_packaged_default_token_start_restart(installed: PackageRun) -> None:
    """Verify packaged token mode and browser behavior across restart."""
    installed.check_token_start_restart()


def test_packaged_team_pair_login_restart(installed: PackageRun) -> None:
    """Verify packaged team pairing, actual fake deliveries, persisted sessions, and browser."""
    installed.check_team_pair_login_restart()


def test_schema3_home_upgrade_restart_and_reindex(installed: PackageRun) -> None:
    """Preserve genuine schema-3 records and bindings through upgrade, restart, and rebuild."""
    installed.check_schema3_upgrade_restart_reindex()


def test_schema4_home_upgrade_restart_and_reindex(installed: PackageRun) -> None:
    """Preserve schema-4 names, directions, workspace, carried state, and raw evidence."""
    installed.check_schema4_upgrade_restart_reindex()
