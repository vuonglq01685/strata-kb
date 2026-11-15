"""testui — the Test Report menu: `/ui/tests*` read-only pages over the `-test` docs.

Everything comes from the federation (`testflow`): no store of its own. A
report for a story no BA plan holds is listed as "unknown story". Story and
round come from the URL, so both are checked before any lookup.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

from strata_kb import planrev, planstatus, strategyhub, testflow
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle
from strata_kb.serving.config import ServerConfig
from strata_kb.web import api, qaui
from strata_kb.web.gfmrender import render as md_render
from strata_kb.web.ui import _render_page, render_error_page

FILTERS = ("all", "testing", "reopened", "closed", "regression", "candidates")
_ROUND_RE = re.compile(r"R([1-9]\d{0,5})")
TOP_RANKS = 5
logger = logging.getLogger("strata_kb.web.testui")


@dataclass(frozen=True)
class Row:
    story: str
    round: int  # 0: claimed, no report yet
    verdict: str
    status: str
    date: str
    regression: bool
    ticket_href: str  # "" for a story no BA plan holds
    report_href: str


def _ticket_hrefs(hub: HubHandle) -> dict[str, str]:
    """story id -> its ticket page (the first plan that holds it)."""
    out: dict[str, str] = {}
    for (repo, ticket), group in qaui._groups(hub).items():
        out.setdefault(ticket, planstatus.plan_href(repo, group, ticket))
    return out


def _statuses(hub: HubHandle) -> dict[str, str]:
    repos, _notes = planstatus.hub_plans(hub)
    return {
        s.us_id: s.test_status
        for r in repos
        for s in (*(s for m in r.missions for s in m.stories), *r.unparented)
        if s.test_status
    }


def _rows(hub: HubHandle, facts: testflow.TestFacts) -> list[Row]:
    hrefs, derived = _ticket_hrefs(hub), _statuses(hub)
    rows = []
    for story in sorted({*facts.reports, *(s for s in facts.testing if s in hrefs)}):
        reports = facts.reports.get(story, ())
        latest = reports[-1] if reports else None
        status = derived.get(story) or testflow.story_test_status(story, (), facts).get(
            story, ""
        )
        rows.append(
            Row(
                story=story,
                round=latest.round if latest else 0,
                verdict=latest.verdict if latest else "",
                status=status,
                date=latest.date if latest else "",
                regression=bool(latest and any(d.regression for d in latest.defects)),
                ticket_href=hrefs.get(story, ""),
                report_href=(
                    f"/ui/tests/{quote(story, safe='')}/R{latest.round}"
                    if latest
                    else ""
                ),
            )
        )
    return rows


def _keep(row: Row, status: str) -> bool:
    if status == "all":
        return True
    if status == "regression":
        return row.regression
    if status == "reopened":
        return row.status in ("reopened", "fix-done")
    return row.status == status


def _panel(view: strategyhub.StrategyView) -> dict:
    ranked = sorted(
        ((r, placed) for r, placed in view.rows if r.rank is not None),
        key=lambda item: item[0].rank,
    )
    log = planrev.parse_change_log(view.text)
    return {
        "repo": view.tester_repo,
        "date": log[-1].date if log else "",
        "plan": view.strategy.plan,
        "revision": view.strategy.revision,
        "top": ranked[:TOP_RANKS],
        "regrounding": bool(view.findings),
    }


def test_routes(config: ServerConfig) -> list[Route]:
    def _hub_unreachable() -> HTMLResponse:
        return render_error_page(
            config,
            status=503,
            title="Hub unreachable",
            detail="The federation is the only read source.",
        )

    def _not_found(detail: str) -> HTMLResponse:
        return render_error_page(config, status=404, title="Not found", detail=detail)

    def tests_page(request: Request) -> HTMLResponse:
        status = request.query_params.get("status", "all")
        if status not in FILTERS:
            status = "all"
        hub = api.hub_handle(config)
        if hub is None:
            return _hub_unreachable()
        facts = testflow.load_facts(hub)
        rows = _rows(hub, facts)
        strategies, unreadable = [], []
        try:
            views = strategyhub.views(hub)
            strategies = [_panel(v) for v in views]
            # views() skips a failing strategy; name it instead of hiding it
            seen = {v.tester_repo for v in views}
            unreadable = sorted(set(testflow.strategy_texts(hub)) - seen)
        except (KbError, ValueError, OSError):
            logger.exception("test strategy could not be read")
            unreadable = ["strategy"]
        candidates = (
            list(testflow.known_failures(facts).values())
            if status == "candidates"
            else []
        )
        return _render_page(
            "tests.html",
            config,
            screen="tests",
            title="Test Report",
            filters=FILTERS,
            active=status,
            rows=[r for r in rows if _keep(r, status)]
            if status != "candidates"
            else [],
            candidates=candidates,
            any_reports=bool(rows),
            strategies=strategies,
            unreadable=unreadable,
        )

    def strategy_page(request: Request) -> HTMLResponse:
        hub = api.hub_handle(config)
        if hub is None:
            return _hub_unreachable()
        try:
            views = strategyhub.views(hub)
        except (KbError, ValueError, OSError):
            logger.exception("test strategy could not be read")
            return render_error_page(
                config,
                status=503,
                title="Strategy unreadable",
                detail="The test strategy could not be read.",
            )
        repo = request.query_params.get("repo")
        pool = [v for v in views if v.tester_repo == repo] if repo else views
        if len(pool) != 1:
            return _not_found("Unknown strategy.")
        view = pool[0]
        return _render_page(
            "tests_strategy.html",
            config,
            screen="tests",
            title="Test strategy — Test Report",
            view=view,
            story_status={s: st for _, placed in view.rows for s, st in placed},
            text_html=md_render(view.text),
        )

    def story_page(request: Request) -> HTMLResponse:
        story = request.path_params["story"]
        if not planstatus.safe_name(story):
            return _not_found(f"Unknown story '{story}'.")
        hub = api.hub_handle(config)
        if hub is None:
            return _hub_unreachable()
        facts = testflow.load_facts(hub)
        reports = facts.reports.get(story, ())
        cases = testflow.section_text(hub, f"{story}.cases")
        held = story in facts.testing  # listed as `testing`, so it must open
        if not reports and cases is None and not held:
            return _not_found(f"No test reports for '{story}'.")
        try:
            placement = next(
                (
                    row
                    for v in strategyhub.views(hub)
                    for row, placed in v.rows
                    if any(s == story for s, _ in placed)
                ),
                None,
            )
        except (KbError, ValueError, OSError):
            logger.exception("test strategy could not be read")
            placement = None
        return _render_page(
            "tests_story.html",
            config,
            screen="tests",
            title=f"{story} — Test Report",
            story=story,
            reports=reports,
            cases_html=md_render(cases) if cases else "",
            ticket_href=_ticket_hrefs(hub).get(story, ""),
            placement=placement,
        )

    def report_page(request: Request) -> HTMLResponse:
        story = request.path_params["story"]
        match = _ROUND_RE.fullmatch(request.path_params["rnd"])
        if not planstatus.safe_name(story) or match is None:
            return _not_found("Unknown test report.")
        number = int(match.group(1))
        hub = api.hub_handle(config)
        if hub is None:
            return _hub_unreachable()
        report = next(
            (
                r
                for r in testflow.load_facts(hub).reports.get(story, ())
                if r.round == number
            ),
            None,
        )
        text = testflow.section_text(hub, f"{story}.R{number}") if report else None
        if report is None or text is None:
            return _not_found(f"No report R{number} for '{story}'.")
        hrefs = _ticket_hrefs(hub)
        return _render_page(
            "tests_report.html",
            config,
            screen="tests",
            title=f"{story} R{number} — Test Report",
            story=story,
            report=report,
            content_html=md_render(text),
            ticket_href=hrefs.get(story, ""),
            closed_stories=[
                (d, quote(d.story, safe=""))
                for d in report.regression_defects
                if planstatus.safe_name(d.story)
            ],
        )

    return [
        Route("/ui/tests", tests_page, methods=["GET"]),
        Route("/ui/tests/strategy", strategy_page, methods=["GET"]),
        Route("/ui/tests/{story}", story_page, methods=["GET"]),
        Route("/ui/tests/{story}/{rnd}", report_page, methods=["GET"]),
    ]
