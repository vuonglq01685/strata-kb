"""Revision, change log and parent-mission pin shared by missions and tickets.

A mission or ticket carries `> Revision: <N>` under its title and, from
revision 2 on, one `## Change log` row per amendment. A ticket pins the
mission revision it was written against as `> Parent mission: M-x @ rev N`.
`missionlint` and `ticketlint` both call `check_revision`; nothing here
knows either heading contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from strata_kb import lintcore, ticket

TRIGGERS: frozenset[str] = frozenset(
    {"kb-context", "architecture", "scope", "delivery"}
)
CHANGE_LOG_HEADING = "## Change log"

_REVISION_RE = re.compile(r"^>\s*Revision:\s*(\d+)\s*$", re.M)
_COLUMNS = ("Rev", "Date", "Trigger", "What changed", "Affected", "Review")


@dataclass(frozen=True)
class ChangeRow:
    rev: int
    date: str
    triggers: tuple[str, ...]
    what: str
    affected: tuple[str, ...]
    review: str


def parse_revision(text: str) -> int | None:
    m = _REVISION_RE.search(text)
    return int(m.group(1)) if m else None


def _split(cell: str) -> tuple[str, ...]:
    return tuple(p for p in (s.strip() for s in cell.split(",")) if p and p != "-")


def parse_change_log(text: str) -> list[ChangeRow]:
    """Data rows of the change-log table, in file order. Columns are found by
    header name. Rows without an integer Rev (the template's empty row) are
    skipped; a table missing any column yields no rows."""
    body = lintcore.section_body(text, CHANGE_LOG_HEADING)
    rows = lintcore.table_rows(lintcore.visible_body(body)) if body else []
    cols = [lintcore.table_column(rows, name) for name in _COLUMNS]
    if not rows or None in cols:
        return []
    out: list[ChangeRow] = []
    for cells in rows[1:]:
        if len(cells) < len(rows[0]):
            continue
        rev, date, trig, what, affected, review = (
            cells[c] for c in cols if c is not None
        )
        if not rev.isdigit():
            continue
        out.append(
            ChangeRow(int(rev), date, _split(trig), what, _split(affected), review)
        )
    return out


def check_revision(text: str) -> list[lintcore.Issue]:
    """Absent `Revision` is a warning (read as 1). Otherwise the change log
    must hold exactly one row per revision 2..N, in order, and every Trigger
    must be one of `TRIGGERS`."""
    issues: list[lintcore.Issue] = []
    revision = parse_revision(text)
    if revision is None:
        issues.append(
            lintcore.Issue("warning", "'> Revision: <N>' line missing — read as 1")
        )
        revision = 1
    rows = parse_change_log(text)
    got = [r.rev for r in rows]
    want = list(range(2, revision + 1))
    if got != want:
        issues.append(
            lintcore.Issue(
                "error",
                f"Revision {revision}: '{CHANGE_LOG_HEADING}' needs exactly one "
                f"row per revision 2..{revision} in order, found {got}",
            )
        )
    for r in rows:
        if not r.triggers:
            issues.append(
                lintcore.Issue("error", f"change log rev {r.rev}: Trigger is empty")
            )
        issues += [
            lintcore.Issue(
                "error",
                f"change log rev {r.rev}: unknown Trigger '{t}' "
                f"(allowed: {', '.join(sorted(TRIGGERS))})",
            )
            for t in r.triggers
            if t not in TRIGGERS
        ]
    return issues


def parent_pin(text: str) -> tuple[str, int] | None:
    """`(mission_id, rev)` from `> Parent mission: M-x [@ rev N]`; rev is 1
    when the suffix is absent. `None` without a parent-mission line."""
    m = ticket.PARENT_MISSION_RE.search(text)
    if m is None:
        return None
    return m.group(1), int(m.group(2)) if m.group(2) else 1
