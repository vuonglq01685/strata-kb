"""/api/claims: the hub's JSON routes for ticket claims (see `ticketclaim`).

Bearer-authed like the rest of `/api`. A claim is keyed like Q&A: `repo` is
the BA plan repo `ticketfetch.find` names, `ticket` the id. Store calls are
sync SQLite, so each handler runs in the threadpool; only the body read is
async.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sqlite3
from collections.abc import Callable
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from strata_kb import planstatus, ticketclaim, ticketfetch
from strata_kb.hub import HubHandle
from strata_kb.serving.config import ServerConfig, hub_serves_own_checkout
from strata_kb.web import bodycap
from strata_kb.web.api import (
    HUB_DOWN_DETAIL,
    _error,
    hub_handle,
)

logger = logging.getLogger("strata_kb.web.claim_api")

MAX_BODY = 8192
TTL_ENV = "STRATA_KB_CLAIM_TTL"
CLAIMS_NEED_HUB_DETAIL = "claims need the shared hub server"

Handler = Callable[[Request, dict[str, Any], HubHandle], JSONResponse]


def claim_ttl_from_env() -> int:
    raw = os.environ.get(TTL_ENV)
    if raw is None:
        return ticketclaim.DEFAULT_TTL
    try:
        ttl = int(raw)
    except ValueError:
        ttl = 0
    if ttl <= 0:
        logger.warning(
            "%s=%r is not a positive integer; using %d",
            TTL_ENV,
            raw,
            ticketclaim.DEFAULT_TTL,
        )
        return ticketclaim.DEFAULT_TTL
    return ttl


def _bad(detail: str) -> JSONResponse:
    return _error(400, "bad_request", detail)


def _claim_json(claim: ticketclaim.Claim) -> dict:
    return dataclasses.asdict(claim)


def _str_field(body: dict, key: str, *, required: bool = False) -> str | None:
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ticketclaim.ClaimError(f"{key} must be a string")
    return value


def _claim_error(exc: ticketclaim.ClaimError) -> JSONResponse:
    """Map a store error to the wire format. Subclasses first."""
    if isinstance(exc, ticketclaim.ClaimTaken):
        return JSONResponse(
            {"error": "taken", "claim": _claim_json(exc.claim)}, status_code=409
        )
    if isinstance(exc, ticketclaim.ClaimLost):
        return JSONResponse(
            {
                "error": "lost",
                "close_reason": exc.close_reason,
                "closed_by": exc.closed_by,
            },
            status_code=409,
        )
    if isinstance(exc, ticketclaim.BadClaimToken):
        return _error(403, "bad_token", str(exc))
    if isinstance(exc, ticketclaim.UnknownClaim):
        return _error(404, "unknown_claim", str(exc))
    if "pr_mismatch" in str(exc):
        return _error(409, "pr_mismatch", "pr is not the claim's pr")
    return _bad(str(exc))


def build_claim_routes(config: ServerConfig) -> list[Route]:
    ttl = claim_ttl_from_env()

    def store_for(hub: HubHandle) -> ticketclaim.ClaimStore:
        return ticketclaim.ClaimStore(ticketclaim.claims_db_path(hub.root), ttl=ttl)

    def guarded(handler: Handler):
        """Hub checks and error mapping around `handler(request, body, hub)`."""

        def run(request: Request, body: dict[str, Any]) -> JSONResponse:
            if not hub_serves_own_checkout(config):
                return _error(503, "qa_needs_hub_server", CLAIMS_NEED_HUB_DETAIL)
            hub = hub_handle(config)
            if hub is None:
                return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
            try:
                return handler(request, body, hub)
            except ticketclaim.ClaimError as exc:
                return _claim_error(exc)
            except (sqlite3.Error, OSError):
                logger.exception("claim store error")
                return _error(500, "claim_store_error", "see hub log")

        return run

    async def read_body(request: Request) -> dict | JSONResponse:
        too_big = _error(413, "body_too_large", f"max {MAX_BODY} bytes")
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            return too_big
        capped = Request(
            request.scope,
            bodycap.capped_receive(
                request, MAX_BODY, lambda: OverflowError("body too large")
            ),
        )
        try:
            raw = await capped.body()
        except OverflowError:
            return too_big
        try:
            body = json.loads(raw)
        except ValueError:  # includes UnicodeDecodeError
            return _bad("body must be JSON")
        if not isinstance(body, dict):
            return _bad("body must be a JSON object")
        return body

    def endpoint(handler: Handler, *, has_body: bool = True):
        run = guarded(handler)

        async def view(request: Request) -> JSONResponse:
            body: dict = {}
            if has_body:
                got = await read_body(request)
                if isinstance(got, JSONResponse):
                    return got
                body = got
            return await run_in_threadpool(run, request, body)

        return view

    def claim_id(request: Request) -> int:
        try:
            return int(request.path_params["claim_id"])
        except ValueError:
            raise ticketclaim.UnknownClaim("no such claim") from None

    def take(_request: Request, body: dict, hub: HubHandle) -> JSONResponse:
        ref = _str_field(body, "ticket", required=True) or ""
        holder = _str_field(body, "holder", required=True) or ""
        sent = _str_field(body, "token")
        try:
            _, ticket = ticketfetch.split_ref(ref)
            repo, _doc, _l3 = ticketfetch.find(hub, ref)
        except ticketfetch.TicketNotOnHub as exc:
            return _error(404, "unknown_ticket", str(exc))
        except ticketfetch.TicketFetchError as exc:
            # find() raises one type for several holders and for a bad id
            kind = "ambiguous" if "several repos" in str(exc) else "bad_request"
            return _error(400, kind, str(exc))
        claim, token = store_for(hub).take(repo, ticket, holder, sent)
        # An expired claim retried with its old token is a new grant (new token).
        regrant = sent is not None and token == sent
        return JSONResponse(
            {"claim": _claim_json(claim), "token": token},
            status_code=200 if regrant else 201,
        )

    def close_done_tickets(hub: HubHandle, store: ticketclaim.ClaimStore) -> None:
        held = store.held()
        done: set[tuple[str, str]] = set()
        try:
            for repo in sorted({c.repo for c in held}):
                stories, unparented, _notes = planstatus.next_from_hub(hub, repo)
                done |= {
                    (repo, s.us_id)
                    for s in [*stories, *unparented]
                    if s.status == "done"
                }
        except Exception:  # a plan read must never fail the listing
            logger.exception("claims: plan read failed; not closing done tickets")
            return
        store.close_done(done)

    def listing(request: Request, _body: dict, hub: HubHandle) -> JSONResponse:
        store = store_for(hub)
        close_done_tickets(hub, store)
        params = request.query_params
        claims = store.held(params.get("repo", ""), params.get("ticket", ""))
        return JSONResponse({"claims": [_claim_json(c) for c in claims]})

    def update(request: Request, body: dict, hub: HubHandle) -> JSONResponse:
        token = _str_field(body, "token", required=True) or ""
        claim = store_for(hub).update(
            claim_id(request),
            token,
            phase=_str_field(body, "phase"),
            pr=_str_field(body, "pr"),
            state=_str_field(body, "state"),
            stop_reason=_str_field(body, "stop_reason"),
        )
        return JSONResponse({"claim": _claim_json(claim)})

    def release(request: Request, body: dict, hub: HubHandle) -> JSONResponse:
        token = _str_field(body, "token", required=True) or ""
        reason = _str_field(body, "reason") or ""
        store_for(hub).release(claim_id(request), token, reason)
        return JSONResponse({})

    def pr_closed(request: Request, body: dict, hub: HubHandle) -> JSONResponse:
        pr = _str_field(body, "pr", required=True) or ""
        claim = store_for(hub).pr_closed(claim_id(request), pr)
        return JSONResponse({"claim": _claim_json(claim)})

    return [
        Route("/api/claims", endpoint(take), methods=["POST"]),
        Route("/api/claims", endpoint(listing, has_body=False), methods=["GET"]),
        Route("/api/claims/{claim_id}", endpoint(update), methods=["PATCH"]),
        Route("/api/claims/{claim_id}", endpoint(release), methods=["DELETE"]),
        Route(
            "/api/claims/{claim_id}/pr-closed", endpoint(pr_closed), methods=["POST"]
        ),
    ]
