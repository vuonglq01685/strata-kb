"""The root `kb` group turns any KbError a command lets escape into one red
line and exit 1 (1.15.0). The five errors that joined the family in 1.15.0
used to escape as tracebacks."""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from strata_kb import cli
from strata_kb.codeingest.core import CodeIngestError
from strata_kb.errors import KbError
from strata_kb.gitio import GitError
from strata_kb.llm import RunnerError
from strata_kb.searchdb import IndexBusyError
from strata_kb.svcnote import SvcNoteError

runner = CliRunner()

JOINED = [GitError, IndexBusyError, CodeIngestError, SvcNoteError, RunnerError]


@pytest.fixture
def register():
    """Add a throwaway command to a typer app; removed again afterwards."""
    added: list[typer.Typer] = []

    def _add(target: typer.Typer, name: str, fn) -> None:
        target.command(name)(fn)
        added.append(target)

    yield _add
    for target in added:
        target.registered_commands.pop()


@pytest.mark.parametrize("exc_type", JOINED, ids=lambda t: t.__name__)
def test_joined_errors_are_kb_errors(exc_type):
    assert issubclass(exc_type, KbError)


@pytest.mark.parametrize("exc_type", JOINED, ids=lambda t: t.__name__)
def test_an_escaping_error_is_one_line_and_exit_1(register, exc_type):
    def boom() -> None:
        raise exc_type("the cause, named once")

    register(cli.app, "zz-boom", boom)
    result = runner.invoke(cli.app, ["zz-boom"])
    assert result.exit_code == 1
    assert result.output.strip() == "the cause, named once"
    assert "Traceback" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_the_guard_covers_sub_apps(register):
    def boom() -> None:
        raise GitError("not a git repository")

    register(cli.ticket_app, "zz-boom", boom)
    result = runner.invoke(cli.app, ["ticket", "zz-boom"])
    assert result.exit_code == 1
    assert result.output.strip() == "not a git repository"


def test_a_command_s_own_exit_code_passes_through(register):
    def stale() -> None:
        raise typer.Exit(2)

    register(cli.app, "zz-stale", stale)
    assert runner.invoke(cli.app, ["zz-stale"]).exit_code == 2


def test_a_non_kb_error_is_not_swallowed(register):
    def bug() -> None:
        raise ZeroDivisionError("a real bug")

    register(cli.app, "zz-bug", bug)
    result = runner.invoke(cli.app, ["zz-bug"])
    assert isinstance(result.exception, ZeroDivisionError)
