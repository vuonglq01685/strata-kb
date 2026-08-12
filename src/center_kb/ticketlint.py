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

from center_kb import acquality, lintcore, mission, missionlint, ticket
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


def _check_ac_weasel(ac_items: list[str]) -> list[Issue]:
    """NT2 — an AC that cannot be acceptance-tested does not exist.
    Warning per banned phrase (docs/ac-quality.md); an OPEN(<owner>)
    marker on the same AC suppresses it (declared, owned vagueness)."""
    return [
        Issue(
            "warning",
            f"AC uses banned weasel phrase '{phrase}' without "
            f"OPEN(<owner>): '{item.strip()}' — see docs/ac-quality.md",
        )
        for item in ac_items
        for phrase in acquality.weasel_hits(item)
    ]


def _unknown_count(text: str) -> int:
    """OPEN(...) + %%TODO%% markers, guidance comments stripped so the
    templates' own '<!-- ... OPEN(<owner>) ... -->' examples never count."""
    clean = lintcore.HTML_COMMENT_RE.sub("", text)
    return len(acquality.OPEN_RE.findall(clean)) + clean.count(
        mission.PLACEHOLDER
    )


def _check_owned_unknowns(text: str) -> list[Issue]:
    """NT3 — 'unknown' is valid; 'unknown without an owner' is not. Every
    OPEN(...)/%%TODO%% outside '## Open questions' needs an owned row
    there. Count-based: exact marker-to-row matching is not decidable, so
    the check demands at least as many rows as markers."""
    rows = lintcore.open_question_rows(text) or []
    oq_body = lintcore.section_body(
        text, lintcore.OPEN_QUESTIONS_HEADING
    )
    outside = _unknown_count(text) - _unknown_count(oq_body or "")
    issues: list[Issue] = []
    if outside > len(rows):
        issues.append(
            Issue(
                "warning",
                f"{outside} OPEN(...)/'{mission.PLACEHOLDER}' marker(s) "
                f"but only {len(rows)} row(s) in '## Open questions' — "
                "every unknown needs an owned row",
            )
        )
    issues += lintcore.check_open_question_owners(rows)
    return issues


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
        if ticket.PARENT_MISSION_LINE_RE.search(text) is not None:
            # The line is present but the value after the colon is blank
            # or whitespace-only — a BA started the back-link and never
            # filled it in. Without this check the line simply fails to
            # match PARENT_MISSION_RE and reads as "no parent mission at
            # all", which is a silent PASS on a half-written back-link.
            return [
                Issue(
                    "error",
                    "'> Parent mission:' back-link is present but has no "
                    "mission id — fill in 'M-<slug>' after the colon",
                )
            ], []
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
    try:
        mission_text = mission_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        # Unreachable from the MCP tool (kb_ticket_lint): it never passes
        # `path`/`missions_dir`, so execution already returned at the "no
        # repo paths supplied" branch above, well before this read. Keep
        # the guard anyway — this is the first engine code to read a
        # cross-referenced artifact (missionlint.check_coverage only ever
        # probes with `.is_file()`), so a bad mission file (e.g. saved as
        # cp1252 after a pasted smart quote, or a permission/race error)
        # must produce an [error] line, not a raw traceback.
        return [
            Issue(
                "error",
                f"could not read mission file '{mission_path}': {exc}",
            )
        ], []
    backlog_issues, backlog_ids = missionlint.check_backlog(
        mission_text, mission_id
    )
    if us_id not in backlog_ids:
        return [
            Issue(
                "error",
                f"'{us_id}' is not in the backlog of mission "
                f"'{mission_id}' — add the row, fix the ticket filename, "
                f"or run 'kb mission lint {mission_path}' if the mission's "
                "backlog table is malformed",
            )
        ], []
    if backlog_issues:
        # `check_backlog` found membership (the id string is in the table)
        # but the backlog table itself has OTHER errors — e.g. a
        # zero-padded id like 'M-demo-US01' fails mission lint's
        # `us_id_re` pattern check yet still lands in `backlog_ids`
        # verbatim, so a ticket named 'M-demo-US01.md' would otherwise
        # pass here while `kb mission lint` rejects the same id as
        # malformed. Surface a single warning rather than the mission's
        # own issue list — this check only vouches for "the id string
        # appears in the table", not for the table's own validity, which
        # is mission lint's job.
        return [
            Issue(
                "warning",
                f"parent mission '{mission_id}' backlog has errors; "
                "back-link membership may be unreliable — run "
                f"'kb mission lint {mission_path}'",
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

    issues += _check_ac_weasel(ac_items)
    issues += lintcore.check_recommended_sections(
        text, ticket.RECOMMENDED_HEADINGS
    )
    issues += _check_owned_unknowns(text)

    pm_issues, pm_notes = check_parent_mission(text, path, missions_dir)
    issues += pm_issues
    notes += pm_notes

    return LintReport(issues=issues, notes=notes)
