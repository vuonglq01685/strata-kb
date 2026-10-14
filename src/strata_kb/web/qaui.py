"""qaui — the Q&A menu: `/ui/questions*` read-only pages over the ticket Q&A store.

The store is never created here: with no `qa.db` yet the pages render their
empty state. The repo rides in `?repo=` (a nested federation id contains `/`);
it is only compared with stored repo ids, never joined into a path. The ticket
id is checked with `planstatus.safe_name` before any lookup.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

from strata_kb import planstatus, ticketqa
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle
from strata_kb.serving.config import ServerConfig
from strata_kb.ticketqa import QaStore, Question
from strata_kb.web import api
from strata_kb.web.ui import _render_page, render_error_page

logger = logging.getLogger("strata_kb.web.qaui")

Row = tuple[Question, str, int | None]  # (question, derived state, hub revision)


@dataclass(frozen=True)
class TicketSummary:
    ticket: str
    href: str | None  # the existing ticket page; None when the hub dropped it
    qa_href: str
    open: int
    waiting: int
    answered: int
    oldest_open: str  # age of the oldest open question, or "—"


def _qs(repo: str, ticket: str) -> str:
    return f"repo={quote(repo, safe='')}&ticket={quote(ticket, safe='')}"


def _rows(hub: HubHandle, **kwargs: str) -> list[Row]:
    db = ticketqa.qa_db_path(hub.root)
    if not db.exists():  # read-only pages must not create the DB
        return []
    return ticketqa.list_questions(hub, QaStore(db), status="all", **kwargs)


def _groups(hub: HubHandle) -> dict[tuple[str, str], str]:
    """(repo, ticket id) -> the group (mission id or `tickets`) of its page URL."""
    return {
        (fed.meta.repo_id, s.id): s.file
        for fed, manifest in planstatus.plan_docs(hub)
        for s in manifest.sections
        if s.id != s.file and planstatus.safe_name(s.file)
    }


def _ticket_href(
    groups: dict[tuple[str, str], str], repo: str, ticket: str
) -> str | None:
    group = groups.get((repo, ticket))
    if group is None:
        return None
    return f"/ui/tickets/{quote(group)}/{quote(ticket)}?repo={quote(repo, safe='')}"


def _age(asked_at: str) -> str:
    seconds = max(
        0, int((datetime.now(UTC) - datetime.fromisoformat(asked_at)).total_seconds())
    )
    for size, unit in ((86400, "d"), (3600, "h")):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds // 60}m"


def _summaries(
    rows: list[Row], groups: dict[tuple[str, str], str], *, unresolved_only: bool
) -> list[tuple[str, list[TicketSummary]]]:
    by_ticket: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        by_ticket.setdefault((row[0].repo, row[0].ticket), []).append(row)
    repos: dict[str, list[TicketSummary]] = {}
    for (repo, ticket), items in sorted(by_ticket.items()):
        states = [state for _, state, _ in items]
        if unresolved_only and set(states) == {"answered"}:
            continue
        open_asked = [q.asked_at for q, state, _ in items if state == "open"]
        repos.setdefault(repo, []).append(
            TicketSummary(
                ticket=ticket,
                href=_ticket_href(groups, repo, ticket),
                qa_href=f"/ui/questions/ticket?{_qs(repo, ticket)}",
                open=states.count("open"),
                waiting=states.count("waiting"),
                answered=states.count("answered"),
                oldest_open=_age(min(open_asked)) if open_asked else "—",
            )
        )
    return list(repos.items())


def unresolved_count(hub: HubHandle, repo: str, ticket: str) -> int:
    """Open + waiting questions of a ticket, for its page. A broken Q&A store
    must not break the ticket page, so a failure counts as none."""
    try:
        return sum(
            state != "answered"
            for _, state, _ in _rows(hub, ticket_ref=ticket, repo=repo)
        )
    except (sqlite3.Error, KbError):
        logger.warning("Q&A store unreadable for %s:%s", repo, ticket, exc_info=True)
        return 0


def qa_routes(config: ServerConfig) -> list[Route]:
    def _hub_unreachable() -> HTMLResponse:
        return render_error_page(
            config,
            status=503,
            title="Hub unreachable",
            detail="The federation is the only read source.",
        )

    def questions_page(request: Request) -> HTMLResponse:
        show_all = request.query_params.get("all") == "1"
        hub = api.hub_handle(config)
        if hub is None:
            return _hub_unreachable()
        rows = _rows(hub)
        return _render_page(
            "questions.html",
            config,
            screen="questions",
            title="Q&A",
            repos=_summaries(rows, _groups(hub), unresolved_only=not show_all),
            show_all=show_all,
            any_questions=bool(rows),
        )

    def question_ticket_page(request: Request) -> HTMLResponse:
        repo = request.query_params.get("repo") or ""
        ticket = request.query_params.get("ticket") or ""
        if not repo or not ticket:
            return render_error_page(
                config,
                status=400,
                title="Bad request",
                detail="Both ?repo= and ?ticket= are required.",
            )
        if not planstatus.safe_name(ticket):
            return render_error_page(
                config,
                status=400,
                title="Bad request",
                detail=f"'{ticket}' is not a ticket id.",
            )
        hub = api.hub_handle(config)
        if hub is None:
            return _hub_unreachable()
        rows = _rows(hub, ticket_ref=ticket, repo=repo)
        # the hub revision is the same on every row of one ticket
        hub_rev = rows[0][2] if rows else None
        return _render_page(
            "questions_ticket.html",
            config,
            screen="questions-ticket",
            title=f"{ticket} — Q&A",
            repo=repo,
            ticket=ticket,
            href=_ticket_href(_groups(hub), repo, ticket),
            hub_rev=hub_rev,
            rows=rows,
        )

    return [
        Route("/ui/questions", questions_page, methods=["GET"]),
        Route("/ui/questions/ticket", question_ticket_page, methods=["GET"]),
    ]
