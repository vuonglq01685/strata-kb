"""The Tester's test strategy (`docs/test-strategy.md`): parse the priority
order and the areas it and a ticket cite. Pure; knows nothing of plans,
the hub or the CLI."""

from __future__ import annotations

import contextlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

from strata_kb import buglint, kbcontext, lintcore, planingest, planrev
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

_PLAN_RE = re.compile(r"^>[ \t]*Plan:[ \t]*(.*?)[ \t\r]*$", re.M)
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


ASSETS_DIR = "assets"  # images live in docs/assets/ (png/webp)


def image_srcs(text: str) -> list[str]:
    return buglint._IMAGE_RE.findall(visible_body(text))


def _ship_issues(text: str, base_dir: Path | None) -> list[Issue]:
    """What `kb report-ingest` would drop the strategy for, so lint-clean
    means it ships. `base_dir` (docs/) turns on the image existence check."""
    out = [
        _err(p, "st-image")
        for src in dict.fromkeys(image_srcs(text))
        for p in buglint.image_problems(src, ASSETS_DIR, base_dir)
    ]
    if base_dir is not None:
        out += [
            _err(f"image '{src}' is a symlink — copy the real file", "st-image")
            for src in dict.fromkeys(image_srcs(text))
            if not buglint.image_problems(src, ASSETS_DIR, base_dir)
            and planingest.via_symlink(base_dir, src)
        ]
    if reason := planingest.fence_reason(text):
        out.append(_err(reason, "st-fence"))
    return out


def lint(text: str, base_dir: Path | None = None) -> LintReport:
    """Offline structure check; hub-backed checks live with the CLI."""
    raw = text
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
    issues += _ship_issues(raw, base_dir)
    return LintReport(issues=issues)


@dataclass(frozen=True)
class StoryInfo:
    us_id: str
    mission_id: str  # "" when unparented
    depends_on: tuple[str, ...]
    retest: bool
    citations: frozenset[Area]
    mission_citations: frozenset[Area]
    plan_pos: int


@dataclass(frozen=True)
class Placement:
    story: str
    row: Row | None
    how: str  # "id" | "mission" | "area" | "outside"
    tier: int  # 0 retest, 1 ranked, 2 unranked/outside, 3 `last`


def _best(rows: list[Row]) -> Row | None:
    return min(rows, key=lambda r: (r.rank is None, r.rank or 0), default=None)


def _match(strategy: Strategy | None, story: StoryInfo) -> tuple[Row | None, str]:
    rows = strategy.rows if strategy else ()
    for target, how in ((story.us_id, "id"), (story.mission_id, "mission")):
        row = next((r for r in rows if target and r.target == target), None)
        if row:
            return row, how
    for cites in (story.citations, story.mission_citations):
        row = _best(
            [r for r in rows if r.area and any(r.area.covers(c) for c in cites)]
        )
        if row:
            return row, "area"
    return None, "outside"


def place(strategy: Strategy | None, story: StoryInfo) -> Placement:
    row, how = _match(strategy, story)
    if story.retest:
        tier = 0
    elif row and row.rank is None:
        tier = 3
    else:
        tier = 1 if row else 2
    return Placement(story.us_id, row, how, tier)


def _sort_group(items: list[tuple[Placement, StoryInfo]]) -> list[Placement]:
    """Plan-order topological pass; a cycle emits the lowest remaining story."""
    left = sorted(items, key=lambda it: (it[1].plan_pos, it[1].us_id))
    ids = {s.us_id for _, s in left}
    out: list[Placement] = []
    while left:
        done = {p.story for p in out}
        pick = next(
            (
                it
                for it in left
                if all(d in done or d not in ids for d in it[1].depends_on)
            ),
            left[0],
        )
        left.remove(pick)
        out.append(pick[0])
    return out


def order(strategy: Strategy | None, stories: list[StoryInfo]) -> list[Placement]:
    """Groups are (tier, rank); `last` and unmatched rank after every number."""
    placed = [(place(strategy, s), s) for s in stories]

    def group(it: tuple[Placement, StoryInfo]) -> tuple[int, float]:
        p = it[0]
        return (p.tier, p.row.rank if p.row and p.row.rank else math.inf)

    return [
        p
        for g in sorted({group(it) for it in placed})
        for p in _sort_group([it for it in placed if group(it) == g])
    ]


def empty_rows(strategy: Strategy, stories: list[StoryInfo]) -> list[Row]:
    hit = {id(p.row) for p in (place(strategy, s) for s in stories) if p.row}
    return [r for r in strategy.rows if id(r) not in hit]
