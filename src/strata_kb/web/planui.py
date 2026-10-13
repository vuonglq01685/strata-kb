"""planui — the Ticket menu: `/ui/tickets/*` pages for BA missions and tickets.

Status is derived and read-only (`planstatus`). The repo rides in `?repo=`
because a nested federation id (`mid/ba-x`) contains `/`; it is only compared
with federation ids, never joined into a path. Mission and ticket ids are
checked with `planstatus.safe_name` before any lookup. The menu was once
`/ui/plans/*`; those URLs answer 301 to the same path under `/ui/tickets`.
"""

from __future__ import annotations

from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

from strata_kb import planstatus
from strata_kb.kinds import BA
from strata_kb.serving.config import ServerConfig
from strata_kb.web import api, uidata
from strata_kb.web.gfmrender import has_mermaid
from strata_kb.web.gfmrender import render as md_render
from strata_kb.web.ui import _render_page, menu_search, render_error_page


def plan_routes(config: ServerConfig) -> list[Route]:
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
        )

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
        content_html, toc = uidata.inject_heading_anchors(md_render(ticket.markdown))
        return _render_page(
            "plan_ticket.html",
            config,
            screen="plan",
            title=f"{story} — Tickets",
            repo=found_repo,
            group=group,
            mission_linked=group != planstatus.TICKETS_GROUP,
            ticket_id=story,
            ticket=ticket,
            content_html=content_html,
            toc=toc,
            mermaid=has_mermaid(content_html),
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
        Route("/ui/plans", plans_moved, methods=["GET"]),
        Route("/ui/plans/{rest:path}", plans_moved, methods=["GET"]),
    ]
