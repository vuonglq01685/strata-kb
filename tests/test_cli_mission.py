"""CLI tests for `kb mission lint`. Hermetic — `fed_hub` git fixture as
the hub, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from center_kb import kbcontext
from center_kb.cli import app
from center_kb.hub import HubHandle

runner = CliRunner()

MISSION_ID = "M-airspace-filter"


def _golden_block(fed_hub: Path) -> str:
    block, _warning = kbcontext.build_context_block(
        HubHandle(root=fed_hub),
        ["arinc-kb:arinc-424 §5.3"],
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
            "```",
            "",
            "## Containers (C4 L2)",
            "```mermaid",
            "C4Container",
            '  Container(api, "Airspace API", "Python")',
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
    assert "notes" in data


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
