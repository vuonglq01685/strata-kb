"""`kb ticket lint` engine — the Definition-of-Ready gate for BA tickets.

No CLI/MCP dependencies here: `cli.py`'s `kb ticket lint` command and the
`kb_ticket_lint` MCP tool are both thin wrappers over `lint()`. Shared
primitives live in `lintcore`; this module holds only what is specific to
the ticket contract.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from center_kb import lintcore, mission, missionlint, ticket
from center_kb.doctor import Issue
from center_kb.lintcore import LintReport

if TYPE_CHECKING:
    from center_kb.hub import HubHandle

# A '- [ ]' / '- [x]' checkbox list item.
_AC_ITEM_RE = re.compile(r"^-\s*\[[ xX]\]\s*(.+)$")


def _check_story(text: str) -> list[Issue]:
    body = lintcore.section_body(text, "## User Story")
    if body is None:
        return []  # heading missing — already reported by check_headings
    if not ticket.STORY_RE.search(body):
        return [
            Issue(
                "error",
                "User Story does not match 'As a <role>, I want "
                "<capability>, so that <value>.'",
            )
        ]
    return []


def _check_ac_present(text: str) -> tuple[list[Issue], list[str]]:
    body = lintcore.section_body(text, "## Acceptance Criteria")
    if body is None:
        return [], []
    items = [
        m.group(1)
        for line in body.splitlines()
        if (m := _AC_ITEM_RE.match(line.strip()))
    ]
    if not items:
        return [
            Issue(
                "error",
                "Acceptance Criteria must have at least 1 '- [ ]' item",
            )
        ], []
    return [], items


def _check_ac_citations(ac_items: list[str]) -> list[Issue]:
    return [
        Issue(
            "warning",
            f"Acceptance Criterion has no citation: '{item.strip()}'",
        )
        for item in ac_items
        if not lintcore.INLINE_CITE_RE.search(item)
    ]


def check_parent_mission(
    text: str, path: Path | None, missions_dir: Path | None
) -> tuple[list[Issue], list[str]]:
    """Check 10. Only fires when the OPTIONAL '> Parent mission:' line is
    present — pre-existing tickets carry no such line and are unaffected.

    Traceability is enforced here rather than at mission lint because this
    is the point where both artifacts exist: a mission is authored before
    its tickets, so a mission-side existence check would fail every
    freshly written mission (spec §5.2).
    """
    m = ticket.PARENT_MISSION_RE.search(text)
    if m is None:
        return [], []

    mission_id = m.group(1)
    if not mission.MISSION_ID_RE.match(mission_id):
        return [
            Issue(
                "error",
                f"malformed parent mission id '{mission_id}' — expected "
                "'M-<slug>' in lowercase kebab-case",
            )
        ], []

    if path is None or missions_dir is None:
        return [], [
            "parent-mission existence and backlog checks skipped — no repo "
            "paths supplied"
        ]

    mission_path = missions_dir / f"{mission_id}.md"
    if not mission_path.is_file():
        return [
            Issue(
                "error",
                f"mission file not found: '{mission_path}' — the ticket "
                f"declares parent mission '{mission_id}'",
            )
        ], []

    us_id = path.stem
    mission_text = mission_path.read_text(encoding="utf-8")
    _issues, backlog_ids = missionlint.check_backlog(mission_text, mission_id)
    if us_id not in backlog_ids:
        return [
            Issue(
                "error",
                f"'{us_id}' is not in the backlog of mission "
                f"'{mission_id}' — add the row or fix the ticket filename",
            )
        ], []
    return [], []


def lint(
    text: str,
    hub: "HubHandle | None",
    *,
    path: Path | None = None,
    missions_dir: Path | None = None,
) -> LintReport:
    issues: list[Issue] = []
    notes: list[str] = []
    issues += lintcore.check_title(text)
    issues += lintcore.check_headings(text, ticket.REQUIRED_HEADINGS)
    issues += _check_story(text)

    ac_issues, ac_items = _check_ac_present(text)
    issues += ac_issues

    issues += lintcore.check_diagram(
        text, "## Sequence diagram", ("sequenceDiagram",)
    )
    issues += lintcore.check_diagram(text, "## Business flow", ("flowchart",))

    ctx_issues, _ctx = lintcore.check_context_block(text, hub)
    issues += ctx_issues

    issues += _check_ac_citations(ac_items)

    pm_issues, pm_notes = check_parent_mission(text, path, missions_dir)
    issues += pm_issues
    notes += pm_notes

    return LintReport(issues=issues, notes=notes)
