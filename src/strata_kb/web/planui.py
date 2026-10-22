"""planui — the Ticket menu: `/ui/tickets/*` pages for BA missions and tickets.

Status is derived and read-only (`planstatus`). The repo rides in `?repo=`
because a nested federation id (`mid/ba-x`) contains `/`; it is only compared
with federation ids, never joined into a path. Mission and ticket ids are
checked with `planstatus.safe_name` before any lookup. The menu was once
`/ui/plans/*`; those URLs answer 301 to the same path under `/ui/tickets`.
"""

from __future__ import annotations

import logging
import sqlite3
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from strata_kb import planstatus
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle
from strata_kb.kinds import BA
from strata_kb.serving.auth import COOKIE_NAME, SessionAuth, current_user
from strata_kb.serving.config import ServerConfig, hub_serves_own_checkout
from strata_kb.ticketclaim import (
    MAX_REASON,
    WORKING_PHASES,
    Claim,
    ClaimError,
    ClaimStore,
    claims_db_path,
)
from strata_kb.web import api, bodycap, qaui, uidata
from strata_kb.web.claim_api import claim_ttl_from_env
from strata_kb.web.gfmrender import has_mermaid
from strata_kb.web.gfmrender import render as md_render
from strata_kb.web.registry_routes import _csrf_ok, csrf_token
from strata_kb.web.ui import NO_STORE, _render_page, menu_search, render_error_page

logger = logging.getLogger("strata_kb.web.planui")

MAX_BODY = 8192
CLAIMS_UNAVAILABLE = "Claim info is unavailable right now."
_PR_BADGES = {"review": "In review", "publishing": "Publishing"}


def claim_badge(claim: Claim | None) -> str | None:
    """The short status a held claim puts on a ticket; None without a claim."""
    if claim is None:
        return None
    if claim.state == "stopped":
        return f"Stopped: {claim.stop_reason}"
    if claim.phase in WORKING_PHASES:
        return "In progress"
    return _PR_BADGES.get(claim.phase, "In progress")


def claim_closed_line(claim: Claim) -> str:
    """Who closed a claim and why, for the next Dev to read."""
    reason = claim.close_reason or ""
    kind, _, detail = reason.partition(": ")
    if kind in ("admin", "released"):
        line = f"Released by {claim.closed_by}"
        return f"{line} — {detail}" if detail else line
    if reason == "expired":
        return f"Expired — no sign of {claim.holder} for too long"
    if reason == "done":
        return "Done — the ticket is in the Dev repo's history"
    return f"Closed by {claim.closed_by}: {reason}"


def _held_by_ticket(
    hub: HubHandle, repo: str, ttl: int
) -> tuple[dict[str, Claim], str]:
    """(ticket -> held claim, notice) of a repo. A missing store is no claims;
    an unreadable one is a notice, never a failed page."""
    db = claims_db_path(hub.root)
    if not db.exists():  # read-only pages must not create the DB
        return {}, ""
    try:
        return {c.ticket: c for c in ClaimStore(db, ttl=ttl).held(repo)}, ""
    except (sqlite3.Error, KbError, OSError):
        logger.warning("claim store unreadable for %s", repo, exc_info=True)
        return {}, CLAIMS_UNAVAILABLE


def _story_status(hub: HubHandle, repo: str, story: str) -> str:
    """The derived status of a story or unparented ticket; "" when unknown."""
    plans, _notes = planstatus.hub_plans(hub, repo)
    for plan in plans:
        for item in (*(s for m in plan.missions for s in m.stories), *plan.unparented):
            if item.us_id == story:
                return item.status
    return ""


def plan_routes(
    config: ServerConfig, session: SessionAuth | None = None
) -> list[Route]:
    ttl = claim_ttl_from_env()

    def claim_ctx(hub: HubHandle, repo: str) -> dict:
        claims, notice = _held_by_ticket(hub, repo, ttl)
        return {
            "claims": claims,
            "claim_badges": {t: claim_badge(c) for t, c in claims.items()},
            "claim_notice": notice,
        }

    def _not_found(detail: str) -> HTMLResponse:
        return render_error_page(config, status=404, title="Not found", detail=detail)

    def _ambiguous(what: str, repos: list[str]) -> HTMLResponse:
        names = ", ".join(sorted(repos))
        return _not_found(
            f"{what} is published by several repos ({names}) — add ?repo="
        )

    def _hub_unreachable() -> HTMLResponse:
        return render_error_page(
            config,
            status=503,
            title="Hub unreachable",
            detail="The federation is the only read source.",
        )

    def plans_page(request: Request) -> HTMLResponse:
        """All repos, or one repo's page with `?repo=<id>`."""
        repo = request.query_params.get("repo") or None
        hub = api.hub_handle(config)
        if hub is None:
            return _hub_unreachable()
        if repo is None:
            search_ctx = menu_search(config, request, BA)
            if search_ctx["menu_q"]:
                return _render_page(
                    "plans.html",
                    config,
                    screen="plans",
                    title="Tickets",
                    repos=[],
                    notes=[],
                    **search_ctx,
                )
        plans, notes = planstatus.hub_plans(hub, repo)
        if repo is None:
            # no `q` here (handled above): the menu search context is empty
            return _render_page(
                "plans.html",
                config,
                screen="plans",
                title="Tickets",
                repos=plans,
                notes=notes,
                menu_q="",
                menu_results=[],
            )
        if not plans:
            return _not_found(f"Unknown plan '{repo}'.")
        return _render_page(
            "plan_repo.html",
            config,
            screen="plan",
            title=f"Tickets · {repo}",
            plan=plans[0],
            notes=notes,
            group=planstatus.TICKETS_GROUP,
            **claim_ctx(hub, plans[0].repo),
        )

    def plan_mission_page(request: Request) -> HTMLResponse:
        mission_id = request.path_params["mission"]
        repo = request.query_params.get("repo") or None
        hub = api.hub_handle(config)
        if hub is None:
            return _hub_unreachable()
        holders = planstatus.mission_holders(hub, mission_id, repo)
        if not holders:
            return _not_found(f"Unknown mission '{mission_id}'.")
        if len(holders) > 1:
            return _ambiguous(mission_id, [m.repo for m in holders])
        mission = holders[0]
        # the page head already shows the title: drop the restored `# <title>` line
        body = mission.markdown.removeprefix(f"# {mission.title}\n")
        content_html, toc = uidata.inject_heading_anchors(md_render(body))
        return _render_page(
            "plan_mission.html",
            config,
            screen="plan",
            title=f"{mission_id} — Tickets",
            mission=mission,
            content_html=content_html,
            toc=toc,
            mermaid=has_mermaid(content_html),
            **claim_ctx(hub, mission.repo),
        )

    def _ticket_page(
        request: Request,
        hub: HubHandle,
        *,
        group: str,
        story: str,
        found_repo: str,
        ticket: planstatus.PlanTicket,
        status: int = 200,
        error: str = "",
    ) -> HTMLResponse:
        content_html, toc = uidata.inject_heading_anchors(md_render(ticket.markdown))
        db = claims_db_path(hub.root)
        ticket_status = _story_status(hub, found_repo, story)
        if ticket_status == "done" and db.exists():  # never create the DB on GET
            try:
                ClaimStore(db, ttl=ttl).close_done({(found_repo, story)})
            except (sqlite3.Error, KbError, OSError):
                logger.warning("claim store unwritable for %s", story, exc_info=True)
        ctx = claim_ctx(hub, found_repo)
        # a draft or blocked ticket shows its status, not a claim
        shows_claim = ticket_status not in ("draft", "blocked")
        claim = ctx["claims"].get(story) if shows_claim else None
        last_closed = None
        if shows_claim and claim is None and db.exists() and not ctx["claim_notice"]:
            try:  # after `held`: that call already closed any expired claim
                last_closed = ClaimStore(db, ttl=ttl).last_closed(found_repo, story)
            except (sqlite3.Error, KbError, OSError):
                ctx["claim_notice"] = CLAIMS_UNAVAILABLE
        user = current_user(request)
        can_release = bool(claim and user and user.role == "admin" and session)
        resp = _render_page(
            "plan_ticket.html",
            config,
            screen="plan",
            status=status,
            title=f"{story} — Tickets",
            repo=found_repo,
            group=group,
            mission_linked=group != planstatus.TICKETS_GROUP,
            ticket_id=story,
            ticket=ticket,
            unresolved=qaui.unresolved_count(hub, found_repo, story),
            content_html=content_html,
            toc=toc,
            mermaid=has_mermaid(content_html),
            claim=claim,
            claim_badge=claim_badge(claim),
            claim_age=qaui._age(claim.last_seen) if claim else "",
            pr_url=claim.pr if claim and claim.pr.startswith("https://") else "",
            last_closed=last_closed,
            last_closed_line=claim_closed_line(last_closed) if last_closed else "",
            can_release=can_release,
            csrf=(
                csrf_token(session.key, request.cookies.get(COOKIE_NAME, ""))
                if can_release and session
                else ""
            ),
            error=error,
            claim_notice=ctx["claim_notice"],
        )
        if can_release:
            resp.headers.update(NO_STORE)
        return resp

    def plan_ticket_page(request: Request) -> HTMLResponse:
        group, story = request.path_params["mission"], request.path_params["story"]
        repo = request.query_params.get("repo") or None
        hub = api.hub_handle(config)
        if hub is None:
            return _hub_unreachable()
        holders = planstatus.ticket_holders(hub, group, story, repo)
        if not holders:
            return _not_found(f"Unknown ticket '{story}'.")
        if len(holders) > 1:
            return _ambiguous(story, [r for r, _ in holders])
        found_repo, ticket = holders[0]
        return _ticket_page(
            request, hub, group=group, story=story, found_repo=found_repo, ticket=ticket
        )

    def _forbidden(detail: str) -> Response:
        resp = render_error_page(config, status=403, title="Forbidden", detail=detail)
        resp.headers.update(NO_STORE)
        return resp

    def _release(
        request: Request, hub: HubHandle, group: str, story: str, form
    ) -> Response:
        repo = request.query_params.get("repo") or None
        holders = planstatus.ticket_holders(hub, group, story, repo)
        if not holders:
            return _not_found(f"Unknown ticket '{story}'.")
        if len(holders) > 1:
            return _ambiguous(story, [r for r, _ in holders])
        found_repo, ticket = holders[0]
        user = current_user(request)
        reason = str(form.get("reason", "")).strip()

        def again(status: int, error: str) -> Response:
            return _ticket_page(
                request,
                hub,
                group=group,
                story=story,
                found_repo=found_repo,
                ticket=ticket,
                status=status,
                error=error,
            )

        if not reason or len(reason) > MAX_REASON:
            return again(400, f"Give a reason of 1 to {MAX_REASON} characters.")
        try:
            store = ClaimStore(claims_db_path(hub.root), ttl=ttl)
            # only the claim the admin saw, and only on this ticket
            seen = str(form.get("claim_id", ""))
            claim = next(
                (c for c in store.held(found_repo, story) if str(c.id) == seen), None
            )
            if claim is None:
                return again(409, "That claim is no longer held. Reload the page.")
            store.admin_release(claim.id, user.username if user else "", reason)
        except ClaimError as exc:
            return again(409, str(exc))
        except (sqlite3.Error, KbError, OSError):
            logger.warning(
                "claim release failed for %s:%s", found_repo, story, exc_info=True
            )
            return again(503, CLAIMS_UNAVAILABLE)
        target = planstatus.plan_href(found_repo, group, story)
        return RedirectResponse(target, status_code=303, headers=NO_STORE)

    async def release_post(request: Request) -> Response:
        user = current_user(request)
        if session is None or user is None or user.role != "admin":
            return _forbidden("Releasing a claim is for hub administrators.")
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            return Response("body too large", status_code=413, headers=NO_STORE)
        capped = Request(
            request.scope,
            bodycap.capped_receive(
                request, MAX_BODY, lambda: OverflowError("body too large")
            ),
        )
        try:
            form = await capped.form(max_files=0, max_fields=6)
        except OverflowError:
            return Response("body too large", status_code=413, headers=NO_STORE)
        await capped.close()
        if not _csrf_ok(session, request, form.get("csrf", "")):
            return _forbidden("Form expired. Reload and try again.")
        hub = api.hub_handle(config)
        if hub is None:
            return _hub_unreachable()
        if not hub_serves_own_checkout(config):
            return render_error_page(
                config,
                status=409,
                title="Not the hub server",
                detail="Claims live on the hub server; release from there.",
            )
        return await run_in_threadpool(
            _release,
            request,
            hub,
            request.path_params["mission"],
            request.path_params["story"],
            form,
        )

    def plans_moved(request: Request) -> RedirectResponse:
        """/ui/plans… -> /ui/tickets…, keeping the rest of the path and the query."""
        raw = request.scope.get("raw_path") or b""
        # a percent-encoded prefix falls back to the decoded path
        if not raw.startswith(b"/ui/plans"):
            raw = quote(request.url.path).encode()
        target = "/ui/tickets" + raw.decode("latin-1")[len("/ui/plans") :]
        if request.url.query:
            target += "?" + request.url.query
        return RedirectResponse(target, status_code=301)

    return [
        Route("/ui/tickets", plans_page, methods=["GET"]),
        Route("/ui/tickets/{mission}", plan_mission_page, methods=["GET"]),
        Route("/ui/tickets/{mission}/{story}", plan_ticket_page, methods=["GET"]),
        Route("/ui/tickets/{mission}/{story}/release", release_post, methods=["POST"]),
        Route("/ui/plans", plans_moved, methods=["GET"]),
        Route("/ui/plans/{rest:path}", plans_moved, methods=["GET"]),
    ]
