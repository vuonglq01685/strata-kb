"""The Tester's test strategy (`docs/test-strategy.md`): parse the priority
order and the areas it and a ticket cite. Pure; knows nothing of plans,
the hub or the CLI."""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass

from strata_kb import kbcontext, lintcore, planrev
from strata_kb.lintcore import Issue, LintReport
from strata_kb.mdmask import visible_body

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
_STRICT_PIN_RE = re.compile(r"rev [0-9]+")
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # as planstatus; not imported
_PLACEHOLDER_RE = re.compile(r"<(?!br\b)[a-z][\w .-]*>|(?<!\w)…(?!\w)")
_NO_PIN = ("—", "-")


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


def _err(msg: str, code: str) -> Issue:
    return Issue(level="error", message=msg, code=code)


def _row_issues(cells: list[str], seen: set[str]) -> list[Issue]:
    rank, target, pin, risk, why, _types = cells
    out: list[Issue] = []
    if not _rank(rank)[0]:
        out.append(
            _err(f"{target}: Rank must be a positive integer or `last`", "st-row")
        )
    is_area = _area(target) is not None
    if not is_area and not _NAME_RE.fullmatch(target):
        out.append(_err(f"bad Target: {target!r}", "st-row"))
    elif is_area and pin not in _NO_PIN:
        out.append(_err(f"{target}: a KB area takes Pin `—`", "st-row"))
    elif not is_area and not _STRICT_PIN_RE.fullmatch(pin):
        out.append(_err(f"{target}: Pin must be `rev <N>`", "st-row"))
    if risk not in RISKS:
        out.append(_err(f"{target}: Risk must be one of {', '.join(RISKS)}", "st-row"))
    if not why.strip():
        out.append(_err(f"{target}: Why is empty", "st-row"))
    if target in seen:
        out.append(_err(f"{target} appears in more than one row", "st-duplicate"))
    seen.add(target)
    return out


def _order_issues(text: str) -> list[Issue]:
    rows = lintcore.table_rows(lintcore.section_body(text, ORDER_HEADING) or "")
    if tuple(c.strip() for c in rows[0]) != ORDER_HEADER if rows else True:
        return [
            _err(
                f"{ORDER_HEADING}: header must be {' | '.join(ORDER_HEADER)}",
                "st-heading",
            )
        ]
    out: list[Issue] = []
    seen: set[str] = set()
    for cells in rows[1:]:
        if len(cells) != len(ORDER_HEADER):
            out.append(
                _err(f"row {cells[0]!r}: expected {len(ORDER_HEADER)} cells", "st-row")
            )
            continue
        out += _row_issues(cells, seen)
    return out


def _plan_issues(text: str, st: Strategy) -> list[Issue]:
    if _PLAN_RE.search(text) is None:
        return [_err("missing `> Plan:` line (`—` when no plan)", "st-plan")]
    if st.plan is None and any(r.area is None for r in st.rows):
        return [_err("`> Plan: —` but rows name missions/stories", "st-plan")]
    return []


def _context_issues(text: str, st: Strategy) -> list[Issue]:
    try:
        refs = kbcontext.parse(text).refs
    except kbcontext.KBContextError as exc:
        return [_err(f"kb-context: {exc}", "st-kb-context")]
    return [
        _err(f"{r.target} is not among the kb-context refs", "st-kb-context")
        for r in st.rows
        if r.area
        and not any(
            lintcore.cite_matches_ref(ref, r.area.repo, r.area.doc, r.area.section)
            for ref in refs
        )
    ]


def lint(text: str) -> LintReport:
    """Offline structure check; hub-backed checks live with the CLI."""
    text = visible_body(text) + "\n"
    st = parse(text)
    issues = lintcore.check_title(text) + lintcore.check_headings(text, HEADINGS)
    issues += _order_issues(text)
    issues += _plan_issues(text, st)
    if _PLACEHOLDER_RE.search(text):
        issues.append(_err("placeholder left in the document", "st-placeholder"))
    issues += _context_issues(text, st)
    if not lintcore.review_passed(text):
        issues.append(_err("Q1 has not passed", "st-review"))
    issues += planrev.check_revision(text, TRIGGERS)
    return LintReport(issues=issues)
