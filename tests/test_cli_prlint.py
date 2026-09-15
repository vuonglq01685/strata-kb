"""Tests for `kb pr lint` — the CLI wrapper over prlint.lint_body."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.prlint import REQUIRED_SECTIONS

runner = CliRunner()

GOOD = "\n\n".join(
    "## Verification\n\n```\n12 passed in 0.4s\n```"
    if name == "Verification"
    else "## TDD exemptions\n\nNone."
    if name == "TDD exemptions"
    else f"## {name}\n\nfilled"
    for name in REQUIRED_SECTIONS
)


def test_a_filled_description_exits_zero(tmp_path: Path):
    body = tmp_path / "body.md"
    body.write_text(GOOD, encoding="utf-8")
    result = runner.invoke(app, ["pr", "lint", str(body)])
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output


def test_a_missing_section_exits_one_and_names_it(tmp_path: Path):
    body = tmp_path / "body.md"
    body.write_text(GOOD.replace("## Usage", "## Notes"), encoding="utf-8")
    result = runner.invoke(app, ["pr", "lint", str(body)])
    assert result.exit_code == 1
    assert "Usage" in result.output
    assert "missing-section" in result.output


def test_stdin_source(tmp_path: Path):
    result = runner.invoke(app, ["pr", "lint", "-"], input=GOOD)
    assert result.exit_code == 0, result.output


def test_json_output(tmp_path: Path):
    body = tmp_path / "body.md"
    body.write_text(GOOD, encoding="utf-8")
    result = runner.invoke(app, ["pr", "lint", str(body), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"passed": True, "findings": []}


def test_a_missing_file_exits_nonzero_with_the_path(tmp_path: Path):
    result = runner.invoke(app, ["pr", "lint", str(tmp_path / "nope.md")])
    assert result.exit_code != 0
    assert "nope.md" in result.output


def test_a_non_utf8_file_is_reported_as_such(tmp_path: Path):
    body = tmp_path / "body.md"
    body.write_bytes(b"## Ticket\n\n\xff\xfe not utf-8\n")
    result = runner.invoke(app, ["pr", "lint", str(body)])
    assert result.exit_code == 1
    assert "not valid UTF-8" in result.output
