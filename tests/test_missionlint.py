"""Tests for the mission DoR lint engine (`mission.py` + `missionlint.py`).

Hermetic: uses the `fed_hub` git fixture (from conftest.py) as the hub —
no network, no live hub, no LLM. `fed_hub` publishes two docs:
arinc-kb:arinc-424 §5.3 and icao-kb:icao-annex-2 §1.1 — the golden
mission pins and cites both.
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


def test_us_id_is_derived_from_the_mission_id():
    pattern = mission.us_id_re("M-airspace-filter")
    assert pattern.match("M-airspace-filter-US1")
    assert pattern.match("M-airspace-filter-US42")
    assert not pattern.match("M-other-US1")  # wrong mission
    assert not pattern.match("M-airspace-filter-US0")  # 1-based
    assert not pattern.match("M-airspace-filter-1")  # missing 'US'


def test_parent_mission_line_extracts_the_id():
    text = "# Ticket title\n\n> Parent mission: M-airspace-filter\n"
    assert (
        ticket.PARENT_MISSION_RE.search(text).group(1) == "M-airspace-filter"
    )


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
