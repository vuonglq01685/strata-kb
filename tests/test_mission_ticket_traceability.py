"""End-to-end test that the mission <-> ticket traceability loop actually
closes — this is the whole value proposition of the BA mission-plan
feature (spec §4.4 / §5.2).

`test_ticketlint.py` and `test_missionlint.py` each unit-test one engine
against a STUB of the other artifact: the mission-side tests write ticket
files via `write_text("x")` (never a real, lintable ticket), and the
ticket-side tests build a 7-line mission stub (`_mission_doc()`) that would
itself fail `kb mission lint` (it is missing most required headings and
both C4 diagrams). So no existing test ever runs BOTH engines over a REAL
instance of the other artifact — a regression that broke the loop the two
gates exist to protect could ship with both suites green.

This test writes one real mission document and one real ticket document to
a tmp repo (using the same `fed_hub` git fixture and ref set the two unit
suites already use) and runs both `missionlint.lint` and `ticketlint.lint`
over both, asserting the loop actually closes: the mission lints clean,
the ticket lints clean, the ticket's US id is really in the mission's
backlog, and mission coverage reports the story as drafted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from center_kb import kbcontext, mission, missionlint, ticket, ticketlint
from center_kb.hub import HubHandle

MISSION_ID = "M-traceability-demo"
US_ID = f"{MISSION_ID}-US1"

# Same refs/tags the ticketlint/missionlint unit suites already pin against
# the `fed_hub` fixture (conftest.py) — reused here rather than re-declared
# differently, so this test exercises the same golden data those suites do.
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


def _real_mission_text(block: str) -> str:
    """A real, fully-formed mission document — not a stub — with a
    one-row backlog that names `US_ID`."""
    sections = {
        "## Summary": (
            "Dispatchers need controlled airspace shown on the planning map."
        ),
        "## Business goal": (
            "Cut route-briefing time by showing restrictive airspace "
            "inline. Airspace records follow arinc-kb:arinc-424 §5.3."
        ),
        "## Scope": (
            "**In scope:** map rendering.\n"
            "**Out of scope:** editing airspace data."
        ),
        "## System context (C4 L1)": (
            "```mermaid\n"
            "C4Context\n"
            '  Person(dispatcher, "Dispatcher")\n'
            '  System(planner, "Flight Planner")\n'
            '  Rel(dispatcher, planner, "Plans routes with")\n'
            "```"
        ),
        "## Containers (C4 L2)": (
            "```mermaid\n"
            "C4Container\n"
            '  Container(api, "Airspace API", "Python")\n'
            "```"
        ),
        "## Constraints & assumptions": (
            "ICAO designation rules per icao-kb:icao-annex-2 §1.1 apply."
        ),
        "## US backlog": (
            "| US ID | Title |\n"
            "|---|---|\n"
            f"| {US_ID} | Render restrictive airspace polygons |"
        ),
        "## KB context": f"```yaml\n{block}\n```",
        "## Definition of Ready": "- [ ] Backlog reviewed with the team",
    }
    parts = [f"# {MISSION_ID}", "", f"> Mission: {MISSION_ID}", ""]
    for heading in mission.REQUIRED_MISSION_HEADINGS:
        parts += [heading, sections[heading], ""]
    return "\n".join(parts)


def _real_ticket_text(block: str) -> str:
    """A real, fully-formed ticket document — not a stub — that implements
    `US_ID` and back-links to `MISSION_ID`."""
    sections = {
        "## Summary": "Dispatchers need restrictive airspace details.",
        "## User Story": (
            "As a dispatcher, I want to see restrictive airspace details, "
            "so that I can brief the flight crew accurately."
        ),
        "## Background / Business context": (
            "Restrictive airspace records define designation, type, and "
            "level."
        ),
        "## Acceptance Criteria": (
            "- [ ] AC1: Show airspace type and level per "
            "arinc-kb:arinc-424 §5.3\n"
            "- [ ] AC2: Show ICAO designation per icao-kb:icao-annex-2 §1.1"
        ),
        "## Use cases": (
            "### Main flow\n"
            "Dispatcher opens the map and clicks the airspace polygon.\n\n"
            "### Alternate / exception flows\n"
            "No restrictive airspace nearby: show nothing."
        ),
        "## Sequence diagram": (
            "```mermaid\n"
            "sequenceDiagram\n"
            "  Dispatcher->>System: Request airspace info\n"
            "```"
        ),
        "## Business flow": (
            "```mermaid\n"
            "flowchart TD\n"
            "  A[Start] --> B[Fetch airspace data]\n"
            "```"
        ),
        # Recommended sections (BA upgrade v2) — clean bodies so this real,
        # fully-formed ticket stays warning-free; ticketlint now reports a
        # missing/empty recommended section as a warning, and this test
        # asserts `ticket_report.issues == []`.
        "## Dependencies": "- Blocked by: None\n- Blocks: None",
        "## Non-functional requirements": (
            "| Concern | Target | How to measure | Source |\n"
            "|---|---|---|---|\n"
            "| Detail render | Details visible within 2 s of polygon "
            "click | Stopwatch check on staging | team SLA |"
        ),
        "## UI / presentation spec": (
            "Side panel lists designation, type, and level as labeled "
            "rows; empty state shows 'No restrictive airspace nearby'."
        ),
        "## Out of scope": "Editing airspace records.",
        "## Test data & verification": (
            "Sample record with designation R-2905A: expect type 'R' and "
            "level 'L1' shown in the panel."
        ),
        "## Open questions": (
            "- [ ] Q1 — Confirm the polygon fill color token — "
            "owner: design-team — blocks: UI spec"
        ),
        "## KB context": f"```yaml\n{block}\n```",
        "## Definition of Ready": "- [ ] Every citation resolves",
    }
    parts = [
        f"# {US_ID} — Show restrictive airspace details",
        "",
        f"> Parent mission: {MISSION_ID}",
        "",
    ]
    # Required + recommended sections, recommended ones inserted before
    # '## KB context' — same order as ticket-template.md.
    order = list(ticket.REQUIRED_HEADINGS)
    kb_index = order.index("## KB context")
    order[kb_index:kb_index] = list(ticket.RECOMMENDED_HEADINGS)
    for heading in order:
        parts += [heading, sections[heading], ""]
    return "\n".join(parts)


def test_mission_ticket_loop_closes_end_to_end(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    missions_dir = tmp_path / "missions"
    tickets_dir = tmp_path / "tickets"
    missions_dir.mkdir()
    tickets_dir.mkdir()

    mission_path = missions_dir / f"{MISSION_ID}.md"
    ticket_path = tickets_dir / f"{US_ID}.md"

    mission_text = _real_mission_text(golden_block)
    ticket_text = _real_ticket_text(golden_block)
    mission_path.write_text(mission_text, encoding="utf-8")
    ticket_path.write_text(ticket_text, encoding="utf-8")

    hub = _hub(fed_hub)

    # The mission lints clean, INCLUDING coverage: the one US in the
    # backlog already has a real ticket file, so there is no "undrafted"
    # warning at all.
    mission_report = missionlint.lint(
        mission_text, hub, path=mission_path, tickets_dir=tickets_dir
    )
    assert mission_report.passed is True, mission_report.issues
    assert mission_report.issues == []
    assert not any(
        "US drafted" in issue.message for issue in mission_report.issues
    )

    # The ticket lints clean, including the back-link check (10) against
    # the REAL mission file on disk.
    ticket_report = ticketlint.lint(
        ticket_text, hub, path=ticket_path, missions_dir=missions_dir
    )
    assert ticket_report.passed is True, ticket_report.issues
    assert ticket_report.issues == []

    # The loop actually closes: the ticket's US id is really in the
    # mission's own backlog, not merely assumed to be.
    backlog_issues, backlog_ids = missionlint.check_backlog(
        mission_text, MISSION_ID
    )
    assert backlog_issues == []
    assert US_ID in backlog_ids


def test_mission_ticket_loop_catches_a_break(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    """The positive test above proves the loop PERMITS a correct pair; it
    would also pass if both engines were no-ops. This one proves the loop
    CATCHES a break, which is the property that actually protects the BA.

    The break is the realistic one: the BA renames the ticket file (or
    saves it under a name that does not derive from the mission id), so the
    mission's backlog row no longer has a matching ticket and the ticket's
    own filename stem is no longer in that backlog. Both gates must notice,
    each in its own currency — mission lint as a coverage WARNING (a
    mission is authored before its tickets, so an undrafted story is never
    an error), ticket lint as an ERROR (the ticket is claiming a parent it
    does not belong to).
    """
    missions_dir = tmp_path / "missions"
    tickets_dir = tmp_path / "tickets"
    missions_dir.mkdir()
    tickets_dir.mkdir()

    mission_path = missions_dir / f"{MISSION_ID}.md"
    # The break: saved as -US9, which is NOT the -US1 the backlog lists.
    ticket_path = tickets_dir / f"{MISSION_ID}-US9.md"

    mission_text = _real_mission_text(golden_block)
    ticket_text = _real_ticket_text(golden_block)
    mission_path.write_text(mission_text, encoding="utf-8")
    ticket_path.write_text(ticket_text, encoding="utf-8")

    hub = _hub(fed_hub)

    # Mission side: the backlog's US1 has no ticket file, so coverage fires
    # — as a warning, never an error.
    mission_report = missionlint.lint(
        mission_text, hub, path=mission_path, tickets_dir=tickets_dir
    )
    assert mission_report.passed is True, mission_report.issues
    coverage = [
        i for i in mission_report.issues if "US drafted" in i.message
    ]
    assert len(coverage) == 1, mission_report.issues
    assert coverage[0].level == "warning"
    assert US_ID in coverage[0].message

    # Ticket side: US9 is not in the mission's backlog — an error.
    ticket_report = ticketlint.lint(
        ticket_text, hub, path=ticket_path, missions_dir=missions_dir
    )
    assert ticket_report.passed is False
    assert any(
        "not in the backlog" in i.message and i.level == "error"
        for i in ticket_report.issues
    ), ticket_report.issues
