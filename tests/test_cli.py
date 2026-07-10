from typer.testing import CliRunner

from aero_kb.cli import app

runner = CliRunner()


def test_cli_help_shows_app_description():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "AERO-KB" in result.output
