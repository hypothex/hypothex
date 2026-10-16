from pathlib import Path

from typer.testing import CliRunner

from hypothex.cli.main import app

runner = CliRunner()


def test_db_upgrade_refuses_sqlite(home: Path) -> None:
    result = runner.invoke(app, ["db", "upgrade", "--json"])
    assert result.exit_code == 1
    assert "the SQLite index needs no migrations" in str(result.exception)


def test_db_current_refuses_sqlite(home: Path) -> None:
    result = runner.invoke(app, ["db", "current", "--json"])
    assert result.exit_code == 1 and "needs no migrations" in str(result.exception)
