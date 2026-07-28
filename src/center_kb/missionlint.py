"""`kb mission lint` engine — the Definition-of-Ready gate for BA mission
plans.

No CLI dependencies here: `cli.py`'s `kb mission lint` is a thin wrapper
over `lint()`. There is deliberately NO MCP tool (spec §9) — the
traceability checks need filesystem access the shared server does not
have, so an MCP copy would be a strictly degraded gate.

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
                    "missing mission id — add a '> Mission: M-<slug>' line "
                    "directly under the title",
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

    rows = [
        line
        for line in lines[header_at + 1 :]
        if not mission.BACKLOG_SEP_RE.match(line)
    ]
    us_ids: list[str] = []
    issues: list[Issue] = []
    for line in rows:
        m = mission.BACKLOG_ROW_RE.match(line)
        if m is None:
            issues.append(
                Issue("error", f"US backlog row is not a table row: '{line}'")
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
