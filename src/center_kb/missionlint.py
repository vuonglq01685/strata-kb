"""Structural checks for the BA mission-plan Definition-of-Ready gate.

There is deliberately NO MCP tool (spec §9) — the traceability checks
need filesystem access the shared server does not have, so an MCP copy
would be a strictly degraded gate.

Shared primitives live in `lintcore`; this module holds only what is
specific to the mission contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from center_kb import lintcore, mission
from center_kb.doctor import Issue
from center_kb.lintcore import LintReport

if TYPE_CHECKING:
    from center_kb.hub import HubHandle


def check_mission_id(
    text: str, path: Path | None
) -> tuple[list[Issue], list[str], str | None]:
    """Check 1 (id half). Returns (issues, notes, mission_id).

    The id lives in the document so stdin callers can be checked too. When
    a real file IS supplied, the filename must agree — otherwise every US
    id and ticket path derived from it points somewhere else.
    """
    m = mission.MISSION_LINE_RE.search(text)
    if m is None:
        return (
            [
                Issue(
                    "error",
                    "missing mission id — the document must contain a "
                    "'> Mission: M-<slug>' line (conventionally placed "
                    "directly under the title)",
                )
            ],
            [],
            None,
        )
    mission_id = m.group(1)
    if not mission.MISSION_ID_RE.match(mission_id):
        return (
            [
                Issue(
                    "error",
                    f"malformed mission id '{mission_id}' — expected "
                    "'M-<slug>' in lowercase kebab-case",
                )
            ],
            [],
            None,
        )
    if path is None:
        return (
            [],
            ["filename check skipped — no file path supplied"],
            mission_id,
        )
    if path.stem != mission_id:
        return (
            [
                Issue(
                    "error",
                    f"filename '{path.stem}' does not match mission id "
                    f"'{mission_id}' — every derived US id and ticket path "
                    "would be wrong",
                )
            ],
            [],
            mission_id,
        )
    return [], [], mission_id


def check_backlog(
    text: str, mission_id: str | None
) -> tuple[list[Issue], list[str]]:
    """Checks 6 and 7. Returns (issues, us_ids).

    Numbering gaps are allowed: format and uniqueness are checked, never
    contiguity (see mission.us_id_re).
    """
    body = lintcore.section_body(text, "## US backlog")
    if body is None:
        return [], []  # heading missing — already reported by check_headings

    lines = [line.strip() for line in body.splitlines() if line.strip()]
    header_at = next(
        (
            i
            for i, line in enumerate(lines)
            if mission.BACKLOG_HEADER_RE.match(line)
        ),
        None,
    )
    if header_at is None:
        return [
            Issue(
                "error",
                "'## US backlog' must contain a table with the header row "
                "'| US ID | Title |'",
            )
        ], []

    issues: list[Issue] = []
    for line in lines[:header_at]:
        if mission.BACKLOG_ROW_RE.match(line):
            issues.append(
                Issue(
                    "error",
                    f"backlog row '{line}' appears above the "
                    "'| US ID | Title |' header row — move it below the "
                    "header and separator rows",
                )
            )

    if header_at + 1 >= len(lines) or not mission.BACKLOG_SEP_RE.match(
        lines[header_at + 1]
    ):
        issues.append(
            Issue(
                "error",
                "'## US backlog' header row must be followed by a "
                "separator row (e.g. '|---|---|'), or the table will not "
                "render for the human reviewing the DoR",
            )
        )

    rows = [
        line
        for line in lines[header_at + 1 :]
        if not mission.BACKLOG_SEP_RE.match(line)
    ]
    us_ids: list[str] = []
    for line in rows:
        m = mission.BACKLOG_ROW_RE.match(line)
        if m is None:
            issues.append(
                Issue(
                    "error",
                    f"US backlog row is not a table row: '{line}' — the "
                    "'## US backlog' section must end with the table; put "
                    "trailing notes in another section",
                )
            )
            continue
        us_ids.append(m.group(1))

    if not us_ids:
        issues.append(
            Issue("error", "US backlog must have at least 1 story row")
        )
        return issues, []

    if mission_id is not None:
        pattern = mission.us_id_re(mission_id)
        for us_id in us_ids:
            if not pattern.match(us_id):
                issues.append(
                    Issue(
                        "error",
                        f"US id '{us_id}' does not match "
                        f"'{mission_id}-US<n>'",
                    )
                )

    seen: set[str] = set()
    for us_id in us_ids:
        if us_id in seen:
            issues.append(Issue("error", f"duplicate US id '{us_id}'"))
        seen.add(us_id)

    return issues, us_ids


def check_placeholders(text: str) -> list[Issue]:
    """Check 13. Unresolved code-grounding placeholders are a warning, not
    an error — a mission may legitimately ship with open questions that
    Phase 5 code-knowledge will resolve."""
    count = text.count(mission.PLACEHOLDER)
    if not count:
        return []
    return [
        Issue(
            "warning",
            f"{count} unresolved '{mission.PLACEHOLDER}' placeholder(s) "
            "remain",
        )
    ]


def check_coverage(us_ids: list[str], tickets_dir: Path) -> list[Issue]:
    """Check 12. Coverage is DERIVED from the filesystem, never recorded in
    the backlog table — a hand-maintained status column rots the moment a
    ticket is written and nobody edits the mission.

    Always a warning: a mission is authored before its tickets exist, so
    0/N at creation time is the normal case, not a failure.
    """
    missing = [
        us_id
        for us_id in us_ids
        if not (tickets_dir / f"{us_id}.md").is_file()
    ]
    if not missing:
        return []
    drafted = len(us_ids) - len(missing)
    return [
        Issue(
            "warning",
            f"{drafted}/{len(us_ids)} US drafted — no ticket file yet for: "
            + ", ".join(missing),
        )
    ]


def lint(
    text: str,
    hub: "HubHandle | None",
    *,
    path: Path | None = None,
    tickets_dir: Path | None = None,
) -> LintReport:
    """Run the mission DoR gate. Checks run in spec §5.1 order.

    `path` enables the filename half of check 1; `tickets_dir` enables the
    coverage check. Each omission is recorded as a note rather than
    silently passing.
    """
    issues: list[Issue] = []
    notes: list[str] = []

    issues += lintcore.check_title(text)

    id_issues, id_notes, mission_id = check_mission_id(text, path)
    issues += id_issues
    notes += id_notes

    issues += lintcore.check_headings(text, mission.REQUIRED_MISSION_HEADINGS)

    issues += lintcore.check_diagram(
        text, "## System context (C4 L1)", mission.L1_KEYWORDS
    )
    issues += lintcore.check_diagram(
        text, "## Containers (C4 L2)", mission.L2_KEYWORDS
    )
    if lintcore.section_body(text, mission.COMPONENT_HEADING) is not None:
        issues += lintcore.check_diagram(
            text, mission.COMPONENT_HEADING, mission.L3_KEYWORDS
        )

    backlog_issues, us_ids = check_backlog(text, mission_id)
    issues += backlog_issues

    ctx_issues, _ctx = lintcore.check_context_block(text, hub)
    issues += ctx_issues

    # Coverage is skipped — visibly — when the backlog itself is broken.
    # `check_backlog` returns its id list unfiltered, so a malformed row
    # leaves entries like 'US ID' in `us_ids`; running coverage over that
    # would demand a ticket file for garbage. Filtering to the valid
    # entries instead would be worse: a story with a typo'd id would drop
    # out of the coverage set silently, and coverage would report a clean
    # pass over a subset without saying so. The report already fails on the
    # backlog errors, so nothing is lost by deferring. Gate on the issue
    # list rather than on `us_ids` contents, so the guard stays correct if
    # the set of backlog checks grows later.
    #
    # The final branch runs unconditionally: `check_backlog` only returns
    # an empty `us_ids` alongside an error issue that the `elif
    # backlog_issues` above already caught, and `check_coverage([], ...)`
    # is a no-op, so there is nothing left for an `elif us_ids:` guard to
    # protect against. That guard would only ever matter by masking a
    # future bug — a backlog change that returns an empty `us_ids` with no
    # issue would then skip coverage with no note at all, the one silent
    # skip in an otherwise fully-noted pipeline.
    if tickets_dir is None:
        notes.append(
            "coverage check skipped — no tickets directory supplied"
        )
    elif backlog_issues:
        notes.append(
            "coverage check skipped — the US backlog has errors; "
            "fix those first"
        )
    else:
        issues += check_coverage(us_ids, tickets_dir)

    issues += check_placeholders(text)

    return LintReport(issues=issues, notes=notes)
