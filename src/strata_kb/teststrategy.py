"""The Tester's test strategy (`docs/test-strategy.md`): parse the priority
order and the areas it and a ticket cite. Pure; knows nothing of plans,
the hub or the CLI."""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass

from strata_kb import kbcontext, lintcore, planrev

STRATEGY_FILE = "docs/test-strategy.md"
SECTION_ID = "strategy"
ORDER_HEADING = "## Priority order"
ORDER_HEADER = ("Rank", "Target", "Pin", "Risk", "Why", "Types")
RISKS = ("High", "Medium", "Low")
LAST = "last"
TRIGGERS: frozenset[str] = frozenset(
    {"kb-context", "plan", "coverage", "priority", "scope"}
)
HEADINGS: tuple[str, ...] = (
    "## Scope & objectives",
    "## Test levels & types",
    "## Priority order",
    "## Environments & data",
    "## Entry & exit criteria",
    "## Regression policy",
    "## Risks & mitigations",
    "## Open questions",
    "## KB context",
    "## Change log",
    "## Review record",
)

_PLAN_RE = re.compile(r"^>[ \t]*Plan:[ \t]*(.*?)[ \t]*$", re.M)
_PIN_RE = re.compile(r"^rev\s+(\d+)$")


@dataclass(frozen=True)
class Area:
    repo: str | None
    doc: str
    section: str

    def covers(self, other: Area) -> bool:
        """Same document, compatible repos, and `other` is this section or a
        descendant (`4` covers `4.2`, not `40`)."""
        if self.doc != other.doc:
            return False
        if self.repo and other.repo and self.repo != other.repo:
            return False
        return other.section == self.section or other.section.startswith(
            self.section + "."
        )


@dataclass(frozen=True)
class Row:
    rank: int | None  # None = `last`
    target: str
    area: Area | None
    pin: int | None
    risk: str
    why: str
    types: str


@dataclass(frozen=True)
class Strategy:
    plan: str | None
    revision: int
    rows: tuple[Row, ...]


def _area(target: str) -> Area | None:
    m = lintcore.BRACKET_CITE_RE.fullmatch(target)
    return Area(m.group(1), m.group(2), m.group(3)) if m else None


def _rank(cell: str) -> tuple[bool, int | None]:
    """(parseable, rank); `last` parses as rank None."""
    if cell.strip().lower() == LAST:
        return True, None
    if re.fullmatch(r"[0-9]+", cell) and int(cell) > 0:
        return True, int(cell)
    return False, None


def parse(text: str) -> Strategy:
    m = _PLAN_RE.search(text)
    plan = m.group(1) if m and m.group(1) not in ("", "—", "-") else None
    rows = lintcore.table_rows(lintcore.section_body(text, ORDER_HEADING) or "")
    idx = [lintcore.table_column(rows, n) for n in ORDER_HEADER]
    out: list[Row] = []
    if rows and None not in idx:
        for cells in rows[1:]:
            if len(cells) <= max(i for i in idx if i is not None):
                continue
            rank_c, target, pin_c, risk, why, types = (
                cells[i] for i in idx if i is not None
            )
            ok, rank = _rank(rank_c)
            if not ok:
                continue
            pm = _PIN_RE.match(pin_c)
            out.append(
                Row(
                    rank,
                    target,
                    _area(target),
                    int(pm.group(1)) if pm else None,
                    risk,
                    why,
                    types,
                )
            )
    return Strategy(plan, planrev.parse_revision(text) or 1, tuple(out))


def citations(text: str) -> frozenset[Area]:
    found = {
        Area(m.group(1), m.group(2), m.group(3))
        for m in lintcore.BRACKET_CITE_RE.finditer(lintcore.citation_scan_text(text))
    }
    with contextlib.suppress(kbcontext.KBContextError):
        found |= {
            Area(r.repo_id, r.doc_id, r.section_id) for r in kbcontext.parse(text).refs
        }
    return frozenset(found)
