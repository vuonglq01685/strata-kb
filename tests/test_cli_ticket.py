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
from tests.conftest import _make_stale
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


def test_lint_non_utf8_file_names_encoding_as_the_problem(fed_hub, tmp_path):
    """Ticket bodies are explicitly UTF-8, so a latin-1/binary file is a
    realistic user error — it must produce a red one-liner naming
    encoding, not a raw traceback (UnicodeDecodeError is a ValueError, not
    an OSError). Mirrors test_missionlint's mission-side equivalent so the
    two error paths stay identical."""
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_bytes(b"caf\xe9 - not valid utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub)]
    )

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "utf-8" in result.output.lower()


def test_explicit_missions_dir_missing_is_a_hard_error(fed_hub, tmp_path):
    """An explicit --missions-dir that doesn't exist is a BA typo, not a
    missing mission — it must error out rather than silently letting
    check_parent_mission's .is_file() probing report 'mission file not
    found' for a mission that actually exists elsewhere."""
    block = _golden_block(fed_hub)
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_text(_build_ticket(block), encoding="utf-8")
    bad_dir = tmp_path / "missons"  # typo, does not exist

    result = runner.invoke(
        app,
        [
            "ticket", "lint", str(ticket_path), "--hub", str(fed_hub),
            "--missions-dir", str(bad_dir),
        ],
    )

    assert result.exit_code == 1
    assert str(bad_dir) in result.output


def test_explicit_missions_dir_overrides_the_sibling(fed_hub, tmp_path):
    """--missions-dir must override the sibling default, not merely
    supplement it. Both directories exist and disagree on the ticket's
    parent mission: the sibling's mission has a backlog that does NOT
    cover this ticket's US id, the explicit dir's does. A refactor to
    `sibling or missions_dir` would report PASS become FAIL here (Path is
    always truthy, so `or` would pick the sibling regardless of what
    --missions-dir was passed) — the assertion below cannot pass under
    both semantics."""
    block = _golden_block(fed_hub)
    (tmp_path / "missions").mkdir()
    (tmp_path / "missions" / "M-airspace-filter.md").write_text(
        "# Mission\n\n"
        "> Mission: M-airspace-filter\n\n"
        "## US backlog\n"
        "| US ID | Title |\n"
        "|---|---|\n"
        # sibling backlog covers a DIFFERENT story — US1 is absent.
        "| M-airspace-filter-US2 | Filter by altitude |\n",
        encoding="utf-8",
    )
    (tmp_path / "tickets").mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "M-airspace-filter.md").write_text(
        "# Mission\n\n"
        "> Mission: M-airspace-filter\n\n"
        "## US backlog\n"
        "| US ID | Title |\n"
        "|---|---|\n"
        # elsewhere's backlog DOES cover this ticket's US id.
        "| M-airspace-filter-US1 | Render polygons |\n",
        encoding="utf-8",
    )
    ticket_path = tmp_path / "tickets" / "M-airspace-filter-US1.md"
    text = _build_ticket(block).replace(
        "\n\n## Summary",
        "\n\n> Parent mission: M-airspace-filter\n\n## Summary",
        1,
    )
    ticket_path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "ticket", "lint", str(ticket_path), "--hub", str(fed_hub),
            "--missions-dir", str(elsewhere),
        ],
    )

    # PASS from --missions-dir (US1 covered there), never FAIL from the
    # sibling's mismatched backlog.
    assert result.exit_code == 0, result.output
    assert "DoR: PASS" in result.output
    assert "not in the backlog" not in result.output


def test_ticket_lint_resolves_sibling_missions_dir(fed_hub, tmp_path):
    """A ticket at tickets/<id>.md finds missions/ next to it, so the
    back-link check runs with no flag."""
    block = _golden_block(fed_hub)
    (tmp_path / "missions").mkdir()
    (tmp_path / "tickets").mkdir()
    (tmp_path / "missions" / "M-airspace-filter.md").write_text(
        "# Mission\n\n"
        "> Mission: M-airspace-filter\n\n"
        "## US backlog\n"
        "| US ID | Title |\n"
        "|---|---|\n"
        "| M-airspace-filter-US1 | Render polygons |\n",
        encoding="utf-8",
    )
    ticket_path = tmp_path / "tickets" / "M-airspace-filter-US1.md"
    text = _build_ticket(block).replace(
        "\n\n## Summary",
        "\n\n> Parent mission: M-airspace-filter\n\n## Summary",
        1,
    )
    ticket_path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub)]
    )

    assert result.exit_code == 0, result.output
    assert "DoR: PASS" in result.output


def test_lint_exits_2_when_only_the_ref_is_stale(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    path = tmp_path / "M-airspace-US1.md"
    path.write_text(_build_ticket(block), encoding="utf-8")
    _make_stale(fed_hub)

    result = runner.invoke(
        app,
        ["ticket", "lint", str(path), "--hub", str(fed_hub),
         "--fail-on-stale"],
    )
    assert result.exit_code == 2


def test_lint_exits_1_when_something_else_also_fails(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    path = tmp_path / "M-airspace-US1.md"
    path.write_text(
        _build_ticket(block).replace("## Use cases", "## Use case"),
        encoding="utf-8",
    )
    _make_stale(fed_hub)

    result = runner.invoke(
        app,
        ["ticket", "lint", str(path), "--hub", str(fed_hub),
         "--fail-on-stale"],
    )
    assert result.exit_code == 1


def test_lint_exits_0_on_a_stale_ref_without_the_flag(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    path = tmp_path / "M-airspace-US1.md"
    path.write_text(_build_ticket(block), encoding="utf-8")
    _make_stale(fed_hub)

    result = runner.invoke(
        app, ["ticket", "lint", str(path), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0
