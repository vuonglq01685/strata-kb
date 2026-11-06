"""Ticket-lint glue for parent stories and their children.

`ticketlint.lint` sends a parent story to `lint_parent` and adds
`child_checks` to the ordinary lint of a child ticket. The format rules
live in `storylint`; this module adds what needs the other tickets, the
mission and the hub.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from strata_kb import storylint, ticket
from strata_kb.doctor import Issue
from strata_kb.lintcore import LintReport

_LoadText = Callable[[str], str | None]
# ticketlint.check_parent_mission, passed in: this module cannot import ticketlint
_CheckMission = Callable[..., tuple[list[Issue], list[str]]]


def _err(message: str) -> Issue:
    return Issue("error", message)


def dedupe(issues: list[Issue]) -> list[Issue]:
    """Drop repeated (level, message) pairs, keeping the first."""
    seen: set[tuple[str, str]] = set()
    out: list[Issue] = []
    for i in issues:
        if (i.level, i.message) not in seen:
            seen.add((i.level, i.message))
            out.append(i)
    return out


def lint_parent(
    text: str,
    *,
    path: Path | None,
    missions_dir: Path | None,
    ticket_id: str | None,
    load_mission: _LoadText | None,
    load_ticket: _LoadText | None,
    check_mission: _CheckMission,
) -> LintReport:
    pid = ticket_id or (path.stem if path else None)
    if pid is None:
        return LintReport([_err("parent id unknown — pass the ticket id")])
    children = {
        r.child: load_ticket(r.child) if load_ticket else None
        for r in storylint.parse_split(text)
    }
    report = storylint.lint_parent(text, children, parent_id=pid)
    pm_issues, notes = check_mission(
        text,
        path,
        missions_dir,
        ticket_id=pid,
        load_mission=load_mission,
        blockers_as="warning",
    )
    return LintReport(report.issues + pm_issues, notes)


def child_checks(
    text: str,
    *,
    path: Path | None,
    missions_dir: Path | None,
    ticket_id: str | None,
    load_mission: _LoadText | None,
    load_ticket: _LoadText | None,
    check_mission: _CheckMission,
) -> tuple[list[Issue], list[str]]:
    """Checks for a ticket with '> Parent story:' beyond the ordinary lint:
    the parent's split row, the mission inherited from the parent, the hub."""
    pin = ticket.parent_story_pin(text)
    child_id = ticket_id or (path.stem if path else None)
    issues: list[Issue] = []
    if ticket.PARENT_MISSION_LINE_RE.search(text) is not None:
        issues.append(
            _err(
                "a child ticket inherits its parent's mission — remove "
                "'> Parent mission:'"
            )
        )
    if pin is None or child_id is None:
        return issues, ["parent-story checks skipped — no ticket id supplied"]
    parent_id = pin[0]
    parent_text = load_ticket(parent_id) if load_ticket else None
    issues += storylint.lint_child_against_parent(
        text, child_id, parent_text, parent_id
    )
    notes: list[str] = []
    if parent_text is not None:
        pm_issues, notes = check_mission(
            text,
            path,
            missions_dir,
            ticket_id=child_id,
            load_mission=load_mission,
            parent=(parent_id, parent_text),
        )
        issues += pm_issues
    return issues, notes
