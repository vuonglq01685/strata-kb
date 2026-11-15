"""The test strategy against the hub: the plan as the strategy sees it,
published strategies, and drift (`kb test stale`, the hub's Test Report)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb import (
    kbcontext,
    planrev,
    planstatus,
    testcases,
    testflow,
    teststrategy,
    ticketstale,
)
from strata_kb.lintcore import Issue
from strata_kb.teststrategy import Placement, Row, StoryInfo, Strategy

if TYPE_CHECKING:
    from strata_kb.hub import HubHandle
    from strata_kb.missionnext import StoryStatus

logger = logging.getLogger("strata_kb.strategyhub")

_NOT_TESTABLE = ("testing", "closed", "reopened")


@dataclass(frozen=True)
class PlanView:
    stories: list[StoryInfo]
    status: dict[str, str]
    testable: frozenset[str]
    texts: dict[str, str]  # mission and ticket id -> restored markdown
    missions: frozenset[str]


@dataclass(frozen=True)
class Finding:
    code: str
    level: str
    subject: str
    message: str


@dataclass(frozen=True)
class StrategyView:
    tester_repo: str
    text: str
    strategy: Strategy
    order: list[Placement]  # testable stories only
    rows: list[tuple[Row, list[tuple[str, str]]]]  # row -> (story, status), all stories
    empty_rows: list[Row]
    outside: list[str]
    findings: list[Finding]


def testable(row: StoryStatus, kids: list[StoryStatus]) -> bool:
    if row.test_status in _NOT_TESTABLE:
        return False
    if kids:
        return all(k.status == "done" and k.test_status != "reopened" for k in kids)
    return row.status == "done"


def _texts(hub: HubHandle, ba_repo: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for fed, manifest in planstatus.plan_docs(hub, ba_repo):
        for s in manifest.sections:
            section = planstatus._l3_section(fed, manifest.id, s)
            if section is not None:
                out[s.id] = planstatus._restore(s.title, section)
    return out


def _cites(texts: dict[str, str], key: str) -> frozenset[teststrategy.Area]:
    return teststrategy.citations(texts[key]) if key in texts else frozenset()


def plan_view(
    hub: HubHandle, ba_repo: str | None, *, all_plans: bool = False
) -> PlanView:
    """`all_plans`: no BA repo named, read every plan on the hub (what
    `kb test stale` does when there is no strategy to name one)."""
    if ba_repo is None and not all_plans:
        return PlanView([], {}, frozenset(), {}, frozenset())
    repos, _ = planstatus.hub_plans(hub, ba_repo)
    texts = _texts(hub, ba_repo)
    groups = [m.stories for r in repos for m in r.missions] + [
        r.unparented for r in repos
    ]
    rows = [s for g in groups for s in g]
    stories: list[StoryInfo] = []
    ok: set[str] = set()
    for s in (s for s in rows if not s.parent):
        kids = [k for k in rows if k.parent == s.us_id]
        if testable(s, kids):
            ok.add(s.us_id)
        stories.append(
            StoryInfo(
                s.us_id,
                s.mission_id,
                s.depends_on,
                s.test_status == "fix-done"
                or any(k.test_status == "fix-done" for k in kids)
                or s.us_id.startswith("BUG-"),
                _cites(texts, s.us_id),
                _cites(texts, s.mission_id),
                len(stories),
            )
        )
    return PlanView(
        stories,
        {s.us_id: s.test_status or s.status for s in rows},
        frozenset(ok),
        texts,
        frozenset(m.mission_id for r in repos for m in r.missions),
    )


def _revision(plan: PlanView, target: str) -> int | None:
    return (
        (planrev.parse_revision(plan.texts[target]) or 1)
        if target in plan.texts
        else None
    )


def _known(plan: PlanView, target: str) -> bool:
    return target in plan.missions or target in plan.texts or target in plan.status


def _id_findings(strategy: Strategy, plan: PlanView) -> list[Finding]:
    out: list[Finding] = []
    for row in (r for r in strategy.rows if r.area is None):
        if not _known(plan, row.target):
            out.append(
                Finding(
                    "broken-target",
                    "error",
                    row.target,
                    f"{row.target} is not on the hub",
                )
            )
            continue
        rev = _revision(plan, row.target)
        if row.pin is not None and rev is not None and row.pin != rev:
            out.append(
                Finding(
                    "pin-moved",
                    "warning",
                    row.target,
                    f"{row.target} pinned at rev {row.pin}, hub is at rev {rev}",
                )
            )
    return out


def _context_finding(r: ticketstale.StaleRef, text: str) -> Finding:
    # a failed hub read is reported with the version as its citation; the
    # web must not show the raw git error, so it gets its own code
    if r.citation == kbcontext.parse(text).version:
        logger.warning("kb-context hub read failed: %s", r.reason)
        return Finding("hub-read", "error", r.citation, r.reason)
    return Finding(
        "kb-context",
        "error" if r.status == "broken" else "warning",
        r.citation,
        r.reason,
    )


def strategy_findings(
    text: str, strategy: Strategy, plan: PlanView, hub: HubHandle
) -> list[Finding]:
    out = _id_findings(strategy, plan)
    for r in ticketstale._kb_context_refs(text, hub):
        out.append(_context_finding(r, text))
    out += [
        Finding("coverage", "warning", u, f"{u} is testable but matches no row")
        for u in _outside(strategy, plan)
    ]
    return out


def _outside(strategy: Strategy, plan: PlanView) -> list[str]:
    """Testable stories (bugs never count) that no row matches."""
    return [
        s.us_id
        for s in plan.stories
        if s.us_id in plan.testable
        and not s.us_id.startswith("BUG-")
        and teststrategy.place(strategy, s).how == "outside"
    ]


def case_findings(tests_dir: Path, plan: PlanView) -> list[Finding]:
    out: list[Finding] = []
    for path in sorted(tests_dir.glob("*/test-cases.md")):
        try:
            spec = testcases.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        story = spec.story or path.parent.name
        want = (
            planrev.parse_revision(plan.texts[story]) if story in plan.texts else None
        )
        if want is not None and spec.revision != want:
            out.append(
                Finding(
                    "tc-revision",
                    "warning",
                    story,
                    f"{path.as_posix()}: Ticket revision {spec.revision}, ticket is at {want}",
                )
            )
    return out


def render_markdown(findings: list[Finding]) -> str:
    """The issue body `kb-test-stale.yml` keeps up to date."""
    if not findings:
        return "The test strategy and the test cases match the hub.\n"
    lines = [
        f"{len(findings)} finding(s): the test strategy or the test cases no "
        "longer match the hub. Testing is not blocked.",
        "",
        "| Code | Subject | Message |",
        "| --- | --- | --- |",
    ]
    for f in findings:
        message = f.message.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {f.code} | {f.subject} | {message} |")
    return "\n".join(lines) + "\n"


def lint_against_hub(text: str, hub: HubHandle) -> list[Issue]:
    st = teststrategy.parse(text)
    plan = plan_view(hub, st.plan)
    return [
        Issue(
            level="error" if f.level == "error" else "warning",
            message=f.message,
            code=f"st-{f.code}",
        )
        for f in _id_findings(st, plan)
    ]


def views(hub: HubHandle) -> list[StrategyView]:
    out: list[StrategyView] = []
    for repo, text in sorted(testflow.strategy_texts(hub).items()):
        try:
            out.append(_view(hub, repo, text))
        except Exception:  # noqa: BLE001 - one bad strategy must not hide the others
            logger.warning("skipping unreadable strategy of %s", repo, exc_info=True)
    return out


def _view(hub: HubHandle, repo: str, text: str) -> StrategyView:
    st = teststrategy.parse(text)
    plan = plan_view(hub, st.plan)
    placed = {s.us_id: teststrategy.place(st, s) for s in plan.stories}
    return StrategyView(
        repo,
        text,
        st,
        teststrategy.order(st, [s for s in plan.stories if s.us_id in plan.testable]),
        [
            (r, [(u, plan.status[u]) for u, p in placed.items() if p.row is r])
            for r in st.rows
        ],
        teststrategy.empty_rows(st, plan.stories),
        _outside(st, plan),
        strategy_findings(text, st, plan, hub),
    )
