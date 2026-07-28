"""Tests for the mission template contract (`mission.py`) and the
`PARENT_MISSION_RE` back-link it adds to `ticket.py` — Task 2 of the BA
mission-plan work.

As shipped here the module under test is pure: plain regex/constant
assertions against literal strings, no fixtures, no filesystem, no
network, no LLM. Later tasks build `missionlint.py` (the DoR lint engine)
on top of these constants and will append hub-backed tests to this file
that exercise the `fed_hub` git fixture (from conftest.py) and a golden
mission pinning/citing published docs — none of that exists yet.
"""

from __future__ import annotations

from center_kb import mission, ticket


def test_required_headings_are_the_agreed_contract():
    assert mission.REQUIRED_MISSION_HEADINGS == (
        "## Summary",
        "## Business goal",
        "## Scope",
        "## System context (C4 L1)",
        "## Containers (C4 L2)",
        "## Constraints & assumptions",
        "## US backlog",
        "## KB context",
        "## Definition of Ready",
    )


def test_component_heading_is_not_required():
    assert mission.COMPONENT_HEADING not in mission.REQUIRED_MISSION_HEADINGS


def test_diagram_keywords_accept_c4_and_flowchart():
    assert mission.L1_KEYWORDS == ("C4Context", "flowchart")
    assert mission.L2_KEYWORDS == ("C4Container", "flowchart")
    assert mission.L3_KEYWORDS == ("C4Component", "flowchart")


def test_mission_id_format():
    assert mission.MISSION_ID_RE.match("M-airspace-filter")
    assert mission.MISSION_ID_RE.match("M-a1")
    assert not mission.MISSION_ID_RE.match("airspace-filter")  # no M- prefix
    assert not mission.MISSION_ID_RE.match("M-Airspace")  # not lowercase
    assert not mission.MISSION_ID_RE.match("M-air_space")  # not kebab


def test_mission_line_extracts_the_id():
    text = "# Title\n\n> Mission: M-airspace-filter\n"
    assert mission.MISSION_LINE_RE.search(text).group(1) == "M-airspace-filter"


def test_mission_line_rejects_missing_marker():
    """Without the leading '>' the line is prose, not the mission marker."""
    text = "# Title\n\nMission: M-airspace-filter\n"
    assert mission.MISSION_LINE_RE.search(text) is None


def test_us_id_is_derived_from_the_mission_id():
    pattern = mission.us_id_re("M-airspace-filter")
    assert pattern.match("M-airspace-filter-US1")
    assert pattern.match("M-airspace-filter-US42")
    assert not pattern.match("M-other-US1")  # wrong mission
    assert not pattern.match("M-airspace-filter-US0")  # 1-based
    assert not pattern.match("M-airspace-filter-1")  # missing 'US'


# The literal '## US backlog' table from the design doc (spec §4.3),
# reused verbatim across the three constants below so a Task 3
# implementer testing against this file sees the same fixture the spec
# shows: header row, separator row, and one data row.
_BACKLOG_HEADER = "| US ID | Title |"
_BACKLOG_SEP = "|---|---|"
_BACKLOG_ROW = "| M-airspace-filter-US1 | Render restrictive airspace polygons |"


def test_backlog_header_re_matches_only_the_exact_header():
    assert mission.BACKLOG_HEADER_RE.match(_BACKLOG_HEADER)
    assert not mission.BACKLOG_HEADER_RE.match(_BACKLOG_ROW)
    assert not mission.BACKLOG_HEADER_RE.match("| Story | Name |")  # wrong column names


def test_backlog_sep_re_matches_only_the_separator_row():
    assert mission.BACKLOG_SEP_RE.match(_BACKLOG_SEP)
    assert not mission.BACKLOG_SEP_RE.match(_BACKLOG_ROW)


def test_backlog_row_re_extracts_id_and_title_from_a_data_row():
    m = mission.BACKLOG_ROW_RE.match(_BACKLOG_ROW)
    assert m.group(1) == "M-airspace-filter-US1"
    assert m.group(2) == "Render restrictive airspace polygons"


def test_backlog_row_re_also_matches_header_and_separator_rows():
    """BACKLOG_ROW_RE is NOT self-discriminating: it happily matches the
    header ('US ID' / 'Title') and the separator ('---' / '---') as if
    they were data rows. A caller that runs this regex over every line of
    the '## US backlog' section without first locating the header row
    positionally, and skipping the separator row that follows it, will
    misreport '---' and 'US ID' as malformed US ids on a perfectly valid
    table. Callers MUST locate the header positionally and skip the
    separator row — never rely on this regex alone to tell a data row
    from a header/separator row."""
    header_match = mission.BACKLOG_ROW_RE.match(_BACKLOG_HEADER)
    assert header_match.group(1) == "US ID"
    assert header_match.group(2) == "Title"

    sep_match = mission.BACKLOG_ROW_RE.match(_BACKLOG_SEP)
    assert sep_match.group(1) == "---"
    assert sep_match.group(2) == "---"


def test_placeholder_matches_the_design_docs_convention():
    assert mission.PLACEHOLDER == "%%TODO: verify against codebase%%"


def test_parent_mission_line_extracts_the_id():
    text = "# Ticket title\n\n> Parent mission: M-airspace-filter\n"
    assert (
        ticket.PARENT_MISSION_RE.search(text).group(1) == "M-airspace-filter"
    )


def test_parent_mission_line_rejects_missing_marker():
    """Without the leading '>' the line is prose, not the back-link."""
    text = "# Ticket title\n\nParent mission: M-airspace-filter\n"
    assert ticket.PARENT_MISSION_RE.search(text) is None


def test_parent_mission_line_rejects_capitalized_mission():
    """The regex is case-sensitive on 'mission' (lowercase 'm'). A BA who
    writes '> Parent Mission:' with a capital M gets no match — and
    because the back-link check is opt-in on the line's presence, that
    typo silently disables check 10 for this ticket instead of raising a
    lint error. This test pins that sharp edge rather than papering over
    it with re.I."""
    text = "# Ticket title\n\n> Parent Mission: M-airspace-filter\n"
    assert ticket.PARENT_MISSION_RE.search(text) is None


def test_required_ticket_headings_are_unchanged():
    """REQUIRED_HEADINGS is a compatibility contract across the BA's local
    install, the shared MCP server, and CI — Phase 4.1 must not touch it,
    or every provisioned BA repo needs a migration."""
    assert ticket.REQUIRED_HEADINGS == (
        "## Summary",
        "## User Story",
        "## Background / Business context",
        "## Acceptance Criteria",
        "## Use cases",
        "## Sequence diagram",
        "## Business flow",
        "## KB context",
        "## Definition of Ready",
    )


from pathlib import Path

import pytest

from center_kb import kbcontext, missionlint
from center_kb.hub import HubHandle

MISSION_ID = "M-airspace-filter"
DEFAULT_TITLE = "# Filter and display controlled airspace"
MISSION_LINE = f"> Mission: {MISSION_ID}"

REFS = ["arinc-kb:arinc-424 §5.3", "icao-kb:icao-annex-2 §1.1"]


def _hub(fed_hub: Path) -> HubHandle:
    return HubHandle(root=fed_hub)


@pytest.fixture
def golden_block(fed_hub: Path) -> str:
    block, warning = kbcontext.build_context_block(
        _hub(fed_hub), REFS, tags=["airspace"]
    )
    assert warning is None
    return block


def _default_sections(block: str) -> dict[str, str]:
    return {
        "## Summary": (
            "Dispatchers need controlled airspace shown on the planning map."
        ),
        "## Business goal": (
            "Cut route-briefing time by showing restrictive airspace inline. "
            "Airspace records follow arinc-kb:arinc-424 §5.3."
        ),
        "## Scope": (
            "**In scope:** map rendering, filtering by airspace class.\n"
            "**Out of scope:** editing airspace data, NOTAM ingestion."
        ),
        "## System context (C4 L1)": (
            "```mermaid\n"
            "C4Context\n"
            "  Person(dispatcher, \"Dispatcher\")\n"
            "  System(planner, \"Flight Planner\")\n"
            "  Rel(dispatcher, planner, \"Plans routes with\")\n"
            "```"
        ),
        "## Containers (C4 L2)": (
            "```mermaid\n"
            "C4Container\n"
            "  Container(spa, \"Map UI\", \"TypeScript\")\n"
            "  Container(api, \"Airspace API\", \"Python\")\n"
            "  Rel(spa, api, \"Reads airspace from\", \"HTTPS\")\n"
            "```"
        ),
        "## Constraints & assumptions": (
            "ICAO designation rules per icao-kb:icao-annex-2 §1.1 apply."
        ),
        "## US backlog": (
            "| US ID | Title |\n"
            "|---|---|\n"
            f"| {MISSION_ID}-US1 | Render restrictive airspace polygons |\n"
            f"| {MISSION_ID}-US2 | Filter airspace by class |"
        ),
        "## KB context": f"```yaml\n{block}\n```",
        "## Definition of Ready": (
            "- [ ] Business goal, scope, L1 + L2 diagrams, backlog present\n"
            "- [ ] Every citation resolves at the pinned version\n"
            "- [ ] Backlog reviewed with the team"
        ),
    }


def _build_mission(
    block: str,
    *,
    skip: str | None = None,
    title: str = DEFAULT_TITLE,
    mission_line: str = MISSION_LINE,
    overrides: dict[str, str] | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    sections = _default_sections(block)
    if overrides:
        sections.update(overrides)
    parts = [title, "", mission_line, ""]
    for heading in mission.REQUIRED_MISSION_HEADINGS:
        if heading == skip:
            continue
        parts.append(heading)
        parts.append(sections[heading])
        parts.append("")
    for heading, body in (extra or {}).items():
        parts.append(heading)
        parts.append(body)
        parts.append("")
    return "\n".join(parts)


def _errors(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "error"]


def _warnings(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "warning"]


# --- check 1: title + mission id ---


def test_mission_id_extracted_from_body(golden_block: str):
    issues, notes, mission_id = missionlint.check_mission_id(
        _build_mission(golden_block), None
    )
    assert issues == []
    assert mission_id == MISSION_ID
    assert any("filename" in n for n in notes)


def test_missing_mission_line_errors(golden_block: str):
    text = _build_mission(golden_block, mission_line="")
    issues, _notes, mission_id = missionlint.check_mission_id(text, None)
    assert mission_id is None
    assert any("> Mission:" in i.message for i in issues)


def test_malformed_mission_id_errors(golden_block: str):
    text = _build_mission(golden_block, mission_line="> Mission: airspace")
    issues, _notes, mission_id = missionlint.check_mission_id(text, None)
    assert mission_id is None
    assert any("M-<slug>" in i.message for i in issues)


def test_filename_mismatch_errors(golden_block: str, tmp_path: Path):
    path = tmp_path / "M-wrong-name.md"
    issues, notes, mission_id = missionlint.check_mission_id(
        _build_mission(golden_block), path
    )
    assert mission_id == MISSION_ID
    assert notes == []
    assert any("M-wrong-name" in i.message for i in issues)


def test_filename_match_is_clean(golden_block: str, tmp_path: Path):
    path = tmp_path / f"{MISSION_ID}.md"
    issues, notes, mission_id = missionlint.check_mission_id(
        _build_mission(golden_block), path
    )
    assert issues == []
    assert notes == []
    assert mission_id == MISSION_ID


# --- check 6/7: backlog table ---


def test_backlog_parses(golden_block: str):
    issues, us_ids = missionlint.check_backlog(
        _build_mission(golden_block), MISSION_ID
    )
    assert issues == []
    assert us_ids == [f"{MISSION_ID}-US1", f"{MISSION_ID}-US2"]


def test_backlog_missing_header_errors(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                "| Story | Name |\n"
                "|---|---|\n"
                f"| {MISSION_ID}-US1 | Render polygons |"
            )
        },
    )
    issues, us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert us_ids == []
    assert any("| US ID | Title |" in i.message for i in issues)


def test_backlog_with_no_rows_errors(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={"## US backlog": "| US ID | Title |\n|---|---|"},
    )
    issues, us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert us_ids == []
    assert any("at least 1" in i.message for i in issues)


def test_backlog_bad_us_id_errors(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                "| US ID | Title |\n"
                "|---|---|\n"
                "| M-other-mission-US1 | Wrong mission |"
            )
        },
    )
    issues, _us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert any("M-other-mission-US1" in i.message for i in issues)


def test_backlog_duplicate_us_id_errors(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                "| US ID | Title |\n"
                "|---|---|\n"
                f"| {MISSION_ID}-US1 | First |\n"
                f"| {MISSION_ID}-US1 | Duplicate |"
            )
        },
    )
    issues, _us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert any("duplicate" in i.message.lower() for i in issues)


def test_backlog_numbering_gaps_are_allowed(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                "| US ID | Title |\n"
                "|---|---|\n"
                f"| {MISSION_ID}-US1 | First |\n"
                f"| {MISSION_ID}-US7 | Seventh, after US2-US6 were dropped |"
            )
        },
    )
    issues, us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert issues == []
    assert us_ids == [f"{MISSION_ID}-US1", f"{MISSION_ID}-US7"]


# --- check 13: placeholders ---


def test_placeholder_warns(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## Constraints & assumptions": (
                "Service name %%TODO: verify against codebase%% unknown."
            )
        },
    )
    issues = missionlint.check_placeholders(text)
    assert len(issues) == 1
    assert issues[0].level == "warning"


def test_no_placeholder_is_silent(golden_block: str):
    assert missionlint.check_placeholders(_build_mission(golden_block)) == []
