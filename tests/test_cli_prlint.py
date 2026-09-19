"""Tests for `kb pr lint` — the CLI wrapper over prlint.lint_body."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.prlint import REQUIRED_SECTIONS

runner = CliRunner()

GOOD = "\n\n".join(
    "## Verification\n\n```\n12 passed in 0.4s\n```"
    if name == "Verification"
    else "## TDD exemptions\n\nNone."
    if name == "TDD exemptions"
    else "## Review\n\nBlocking: No"
    if name == "Review"
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
    # No ABC-12 ticket id in GOOD's "filled" Ticket section, so the default
    # --plan-dir also produces a ticket-id-unparsed warning; passed stays
    # True and it is the only non-error finding.
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert all(f["level"] == "warning" for f in payload["findings"])


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


def test_plan_dir_defaults_to_docs_impl_and_warns_when_absent(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    body = tmp_path / "body.md"
    body.write_text(GOOD.replace("## Ticket\n\nfilled", "## Ticket\n\nATM-7 x"), encoding="utf-8")
    result = runner.invoke(app, ["pr", "lint", str(body)])
    assert result.exit_code == 0, result.output
    assert "plan-missing" in result.output


def test_plan_dir_flag_enforces_cmd_test(tmp_path: Path):
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "ATM-7-plan.md").write_text("# p\n\ncmd.test: pytest -q\n", encoding="utf-8")
    body = tmp_path / "body.md"
    body.write_text(GOOD.replace("## Ticket\n\nfilled", "## Ticket\n\nATM-7 x"), encoding="utf-8")
    result = runner.invoke(app, ["pr", "lint", str(body), "--plan-dir", str(plans)])
    assert result.exit_code == 1
    assert "verification-missing-cmd" in result.output
