"""`kb ticket lint` engine — the Definition-of-Ready gate for BA tickets.

No CLI/MCP dependencies here: `cli.py`'s `kb ticket lint` command and the
`kb_ticket_lint` MCP tool are both thin wrappers over `lint()`. Shared
primitives live in `lintcore`; this module holds only what is specific to
the ticket contract.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from center_kb import lintcore, ticket
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


def lint(text: str, hub: "HubHandle | None") -> LintReport:
    issues: list[Issue] = []
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

    return LintReport(issues=issues)
