"""CLI tests for `kb mission lint`. Hermetic — `fed_hub` git fixture as
the hub, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb import kbcontext
from strata_kb.cli import app
from strata_kb.hub import HubHandle
from tests.conftest import make_stale

runner = CliRunner()

MISSION_ID = "M-airspace-filter"


def _golden_block(fed_hub: Path) -> str:
    block, _warning = kbcontext.build_context_block(
        HubHandle(root=fed_hub),
        ["arinc-kb:arinc-424 §5.3"],
        tags=["airspace"],
    )
    return block


def _golden_block_with_icao(fed_hub: Path) -> str:
    """Pins icao-kb:icao-annex-2 §1.1 alongside the usual arinc-kb ref, so
    `make_stale` (which edits the icao-kb entry) has a pinned ref of this
    mission's own context to act on. The body still only inline-cites the
    arinc-kb ref, same as `_golden_block` — the extra pin is uncited, which
    is only ever a warning (never a failure), so it cannot affect any of
    the exit-code assertions below."""
    block, _warning = kbcontext.build_context_block(
        HubHandle(root=fed_hub),
        ["arinc-kb:arinc-424 §5.3", "icao-kb:icao-annex-2 §1.1"],
        tags=["airspace"],
    )
    return block


def _mission_text(block: str) -> str:
    return "\n".join(
        [
            "# Filter and display controlled airspace",
            "",
            f"> Mission: {MISSION_ID}",
            "",
            "## Summary",
            "Show controlled airspace on the planning map.",
            "",
            "## Business goal",
            "Cut briefing time. Records per arinc-kb:arinc-424 §5.3.",
            "",
            "## Scope",
            "**In scope:** rendering. **Out of scope:** editing.",
            "",
            "## System context (C4 L1)",
            "```mermaid",
            "C4Context",
            '  Person(d, "Dispatcher")',
            '  System(kb, "Knowledge Base")',
            '  Rel(d, kb, "queries")',
            "```",
            "",
            "## Containers (C4 L2)",
            "```mermaid",
            "C4Container",
            '  Container(api, "Airspace API", "Python")',
            '  Container(db, "Airspace DB", "Postgres")',
            '  Rel(api, db, "reads from")',
            "```",
            "",
            "## Constraints & assumptions",
            "None recorded.",
            "",
            "## US backlog",
            "| US ID | Title |",
            "|---|---|",
            f"| {MISSION_ID}-US1 | Render polygons |",
            "",
            "## KB context",
            f"```yaml\n{block}\n```",
            "",
            "## Definition of Ready",
            "- [ ] Backlog reviewed",
            "",
        ]
    )


@pytest.fixture
def mission_file(fed_hub: Path, tmp_path: Path) -> Path:
    path = tmp_path / f"{MISSION_ID}.md"
    path.write_text(_mission_text(_golden_block(fed_hub)), encoding="utf-8")
    return path


def test_lint_passing_mission_exits_0(fed_hub: Path, mission_file: Path):
    result = runner.invoke(
        app, ["mission", "lint", str(mission_file), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0, result.output
    assert "DoR: PASS" in result.output
    # mission_file has no missions/tickets sibling layout, so coverage is
    # skipped — assert the note actually appears rather than trusting a
    # bare PASS, which a silently-skipped check would also produce.
    assert "[note] coverage check skipped — no tickets directory supplied" in (
        result.output
    )


def test_lint_failing_mission_exits_1(fed_hub: Path, tmp_path: Path):
    path = tmp_path / f"{MISSION_ID}.md"
    text = _mission_text(_golden_block(fed_hub)).replace("## US backlog", "")
    path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app, ["mission", "lint", str(path), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 1
    assert "DoR: FAIL" in result.output


def test_lint_reads_stdin_and_notes_the_skipped_checks(
    fed_hub: Path, mission_file: Path
):
    result = runner.invoke(
        app,
        ["mission", "lint", "-", "--hub", str(fed_hub)],
        input=mission_file.read_text(encoding="utf-8"),
    )
    assert result.exit_code == 0, result.output
    assert "[note] filename check skipped" in result.output
    assert "[note] coverage check skipped" in result.output


def test_lint_json_output(fed_hub: Path, mission_file: Path):
    result = runner.invoke(
        app,
        ["mission", "lint", str(mission_file), "--hub", str(fed_hub), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["pass"] is True
    assert data["errors"] == []
    # Pin the actual note content on the JSON surface too: `data["notes"]`
    # being non-empty here is what proves this "pass" reflects a skipped
    # coverage check, not a real one — an empty/omitted notes list would
    # let a skip masquerade as a full pass through --json.
    assert data["notes"] == [
        "coverage check skipped — no tickets directory supplied"
    ]


def test_lint_uses_sibling_tickets_dir_by_default(
    fed_hub: Path, tmp_path: Path
):
    """A mission at missions/<id>.md resolves tickets/ as its sibling, so
    the coverage check runs without the BA passing a flag."""
    (tmp_path / "missions").mkdir()
    (tmp_path / "tickets").mkdir()
    path = tmp_path / "missions" / f"{MISSION_ID}.md"
    path.write_text(_mission_text(_golden_block(fed_hub)), encoding="utf-8")

    result = runner.invoke(
        app, ["mission", "lint", str(path), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0, result.output
    assert "0/1 US drafted" in result.output
    assert "coverage check skipped" not in result.output


def test_lint_missing_file_exits_1_with_clear_error(fed_hub: Path, tmp_path: Path):
    result = runner.invoke(
        app,
        ["mission", "lint", str(tmp_path / "nope.md"), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 1
    assert "could not read file" in result.output


def test_explicit_tickets_dir_overrides_the_sibling(fed_hub: Path, tmp_path: Path):
    """--tickets-dir must override the sibling default, not merely
    supplement it. Both directories exist and disagree on coverage: the
    sibling has neither story drafted, the explicit dir has one of two.
    (With a single-story backlog, full coverage prints nothing at all —
    see test_missionlint.py — so two stories are needed for a visible,
    discriminating fraction.) A refactor to `sibling or tickets_dir` would
    report 0/2 here, since a Path is always truthy and `or` would pick the
    sibling regardless of what --tickets-dir was passed."""
    (tmp_path / "missions").mkdir()
    (tmp_path / "tickets").mkdir()  # sibling: empty, both stories missing
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / f"{MISSION_ID}-US1.md").write_text("x", encoding="utf-8")

    text = _mission_text(_golden_block(fed_hub)).replace(
        f"| {MISSION_ID}-US1 | Render polygons |",
        f"| {MISSION_ID}-US1 | Render polygons |\n"
        f"| {MISSION_ID}-US2 | Filter by altitude |",
    )
    path = tmp_path / "missions" / f"{MISSION_ID}.md"
    path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "mission", "lint", str(path), "--hub", str(fed_hub),
            "--tickets-dir", str(elsewhere),
        ],
    )

    # 1/2 from --tickets-dir (US1 drafted there), never 0/2 from the sibling.
    assert "1/2 US drafted" in result.output, result.output
    assert "0/2 US drafted" not in result.output


def test_explicit_tickets_dir_missing_is_a_hard_error(fed_hub: Path, tmp_path: Path):
    """An explicit --tickets-dir that doesn't exist is a BA typo, not
    missing tickets — it must error out rather than silently reporting
    '0/N US drafted' via check_coverage's per-file .is_file() probing."""
    path = tmp_path / f"{MISSION_ID}.md"
    path.write_text(_mission_text(_golden_block(fed_hub)), encoding="utf-8")
    bad_dir = tmp_path / "tikcets"  # typo, does not exist

    result = runner.invoke(
        app,
        [
            "mission", "lint", str(path), "--hub", str(fed_hub),
            "--tickets-dir", str(bad_dir),
        ],
    )

    assert result.exit_code == 1
    assert str(bad_dir) in result.output


def test_lint_non_utf8_file_names_encoding_as_the_problem(
    fed_hub: Path, tmp_path: Path
):
    """Mission/ticket bodies are explicitly UTF-8 with Vietnamese text and
    '§' characters, so a latin-1/binary file is a realistic user error —
    it must produce a red one-liner naming encoding, not a raw traceback
    (UnicodeDecodeError is a ValueError, not an OSError)."""
    path = tmp_path / f"{MISSION_ID}.md"
    path.write_bytes(b"caf\xe9 - not valid utf-8")

    result = runner.invoke(
        app, ["mission", "lint", str(path), "--hub", str(fed_hub)]
    )

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "utf-8" in result.output.lower()


def test_mission_lint_exits_2_when_only_the_ref_is_stale(fed_hub, tmp_path):
    block = _golden_block_with_icao(fed_hub)
    path = tmp_path / f"{MISSION_ID}.md"
    path.write_text(_mission_text(block), encoding="utf-8")
    make_stale(fed_hub)

    result = runner.invoke(
        app,
        ["mission", "lint", str(path), "--hub", str(fed_hub),
         "--fail-on-stale"],
    )
    assert result.exit_code == 2, result.output
    # Click also exits 2 for a usage error (e.g. an unrecognised option) —
    # pin that this 2 came from the lint report, not from `--fail-on-stale`
    # failing to parse.
    assert "DoR: FAIL" in result.output


def test_mission_lint_exits_1_when_something_else_also_fails(fed_hub, tmp_path):
    block = _golden_block_with_icao(fed_hub)
    path = tmp_path / f"{MISSION_ID}.md"
    text = _mission_text(block).replace("## US backlog", "")
    path.write_text(text, encoding="utf-8")
    make_stale(fed_hub)

    result = runner.invoke(
        app,
        ["mission", "lint", str(path), "--hub", str(fed_hub),
         "--fail-on-stale"],
    )
    assert result.exit_code == 1


def test_mission_lint_exits_0_on_a_stale_ref_without_the_flag(fed_hub, tmp_path):
    block = _golden_block_with_icao(fed_hub)
    path = tmp_path / f"{MISSION_ID}.md"
    path.write_text(_mission_text(block), encoding="utf-8")
    make_stale(fed_hub)

    result = runner.invoke(
        app, ["mission", "lint", str(path), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0
