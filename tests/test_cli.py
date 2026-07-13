from typer.testing import CliRunner

from center_kb.cli import app

runner = CliRunner()


def test_cli_help_shows_app_description():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "CENTER-KB" in result.output


def test_version_flag_prints_installed_version():
    import importlib.metadata

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == importlib.metadata.version("center-kb")


def test_version_flag_does_not_require_a_subcommand():
    # `app` has no_args_is_help=True; --version must short-circuit before Click
    # complains about a missing command.
    result = runner.invoke(app, ["--version"])

    assert "Missing command" not in result.output
