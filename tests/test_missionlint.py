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
