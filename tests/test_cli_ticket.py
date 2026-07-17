"""Tests for `kb ticket lint` — the CLI wrapper over `ticketlint.lint`.

Hermetic: reuses the `fed_hub` fixture (conftest.py) and the ticket-building
helpers from test_ticketlint.py — no network, no live hub, no LLM.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from center_kb import gitio, kbcontext
from center_kb.cli import app
from tests.test_ticketlint import REFS, _build_ticket, _hub

runner = CliRunner()


def _golden_block(fed_hub: Path) -> str:
    block, warning = kbcontext.build_context_block(
        _hub(fed_hub), REFS, tags=["airspace"]
    )
    assert warning is None
    return block


def _broken_ref_ticket(fed_hub: Path, block: str) -> str:
    rev = gitio.head_commit(gitio.git_root(fed_hub))
    bad_block = (
        f"kb-context:\n  version: {rev}\n  refs:\n    - arinc-kb:arinc-424 §9.9\n"
    )
    return _build_ticket(
        block,
        overrides={
            "## KB context": f"```yaml\n{bad_block}```",
            "## Acceptance Criteria": (
                "- [ ] AC1: Show something per arinc-kb:arinc-424 §9.9"
            ),
        },
    )


def test_lint_golden_ticket_file_passes(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_text(_build_ticket(block), encoding="utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub)]
    )

    assert result.exit_code == 0, result.output
    assert "DoR: PASS" in result.output


def test_lint_broken_ref_ticket_exits_1(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    text = _broken_ref_ticket(fed_hub, block)
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub)]
    )

    assert result.exit_code == 1
    assert "DoR: FAIL" in result.output


def test_lint_reads_from_stdin(fed_hub):
    block = _golden_block(fed_hub)
    text = _build_ticket(block)

    result = runner.invoke(
        app, ["ticket", "lint", "-", "--hub", str(fed_hub)], input=text
    )

    assert result.exit_code == 0, result.output
    assert "DoR: PASS" in result.output


def test_lint_json_output_pass(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_text(_build_ticket(block), encoding="utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub), "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["pass"] is True
    assert data["errors"] == []


def test_lint_json_output_fail(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    text = _broken_ref_ticket(fed_hub, block)
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub), "--json"]
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["pass"] is False
    assert data["errors"]


def test_lint_missing_file_exits_1_with_clear_error(tmp_path):
    missing = tmp_path / "does-not-exist.md"

    result = runner.invoke(app, ["ticket", "lint", str(missing)])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "could not read file" in result.output
    assert str(missing) in result.output
