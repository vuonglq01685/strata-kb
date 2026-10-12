"""ui — the server-rendered HTML screens under `/ui/*` and `/assets/*`.

`build_routes` returns the overview/search screen, doc and section pages, the
token login and logout, static files, and content-addressed asset serving.
Pages render through `templating` with `mdrender` for Markdown bodies and read
only the hub's `federation/`, never its unpublished `.kb/`. The login form is
unauthenticated, so it is size-capped and rate-limited before the token
compare.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
import tempfile
from collections import Counter
from importlib import resources
from pathlib import Path
from urllib.parse import quote, urlencode

import yaml
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from strata_kb import assetstore, planstatus, searchdb
from strata_kb import hub as hub_mod
from strata_kb.federation import load_federation
from strata_kb.kinds import (
    BA,
    DEV,
    HUB_KINDS,
    KB,
    MENU,
    UnknownKindError,
    normalize_kinds,
)
from strata_kb.query import AmbiguousDocError, get_section, search, tokenize
from strata_kb.serving.auth import (
    COOKIE_NAME,
    SESSION_MAX_AGE,
    cookie_is_secure,
    make_session,
)
from strata_kb.serving.config import ServerConfig
from strata_kb.serving.ratelimit import (
    LOGIN_MAX_ATTEMPTS,
    LOGIN_WINDOW_SECONDS,
    SlidingWindowLimiter,
    client_key,
    trusted_proxies_from_env,
)
from strata_kb.web import api, bodycap, templating, uidata
from strata_kb.web.mdrender import render as md_render

logger = logging.getLogger("strata_kb.web.ui")

# /ui/login is unauthenticated and auth-exempt, and Starlette applies no size
# limit to a form body -- the same reason intake_routes caps every upload
# (intake_routes.read_capped). A token is tens of bytes; 8 KiB is generous.
#
# A chunked request (no Content-Length) skips the header check in login_post
# and reaches request.form() regardless. Do not rely on "the token field is
# not a file part" to bound it: Starlette's FormParser, not just
# MultiPartParser, enforces its own limits on plain url-encoded fields too.
# Verified against pinned Starlette 1.6.0: FormParser caps each field at
# max_part_size (1 MiB) and the whole form at max_fields (1000), raising
# HTTPException(400) past either -- but up to ~1000 fields x 1 MiB can
# accumulate in FormParser.messages before the field-count check trips. That
# path is reachable only via chunked, and bounded to LOGIN_MAX_ATTEMPTS per
# client per LOGIN_WINDOW_SECONDS because login_post's limiter check runs
# before form(); login_post also reads the body through
# bodycap.capped_receive, which refuses it past LOGIN_MAX_BODY.
LOGIN_MAX_BODY = 8 * 1024


class _LoginBodyTooLarge(RuntimeError):
    """Raised from inside the capped receive channel; never a
    MultiPartException, so the form parser lets it through."""


NO_STORE = {"Cache-Control": "no-store"}


def _tag_links(
    all_tags: list[str],
    selected: list[str],
    q: str,
    budget: int | None = None,
    semantic_on: bool | None = None,
    kind: str | None = None,
) -> list[dict]:
    """One toggle link per known tag: clicking adds/removes it from `tags=`.

    Falls back to /ui?q= (the search screen) when toggling off the last tag
    with no query — a bare /ui would render the overview instead. The
    fallback is decided by intent (q and the new tag list both empty), not
    by whether the assembled params list happens to be empty: budget/
    semantic are echoed onto every href and must not, by themselves, turn
    an empty-intent removal into a non-empty param list that skips the
    fallback (that bug used to route `/ui?budget=2000` to the Overview
    screen instead of Search).

    `budget` is echoed back onto every href (after q/tags) so toggling a tag
    chip doesn't silently drop the caller's token-budget selection — without
    it, clicking a chip on `/ui?q=...&budget=8000` would reset the next
    search to the 2000 default. `semantic_on` mirrors the same pattern for
    the match-mode toggle. Both optional, defaulting to None, for backward
    compatibility with existing callers that don't carry that context.

    Any `selected` tag absent from `all_tags` (unknown to the hub, or the
    hub is down and `all_tags` is empty) still gets a chip so it stays
    visible and removable instead of rendering as a blank row.

    `kind` (a menu's own kind) is echoed onto every href so a tag clicked
    inside Document/Ticket/Code stays in that kind.
    """

    def href_for(new: list[str]) -> str:
        if not q and not new:
            return f"/ui?{urlencode([('q', ''), ('kind', kind)])}" if kind else "/ui?q="
        params: list[tuple[str, str]] = []
        if q:
            params.append(("q", q))
        if new:
            params.append(("tags", ",".join(new)))
        if budget is not None:
            params.append(("budget", str(budget)))
        if semantic_on is not None:
            params.append(("semantic", "1" if semantic_on else "0"))
        if kind:
            params.append(("kind", kind))
        return f"/ui?{urlencode(params)}"

    out: list[dict] = []
    for t in all_tags:
        on = t in selected
        new = [x for x in selected if x != t] if on else [*selected, t]
        out.append({"label": t, "href": href_for(new), "on": on})
    known = set(all_tags)
    for t in selected:
        if t in known:
            continue
        out.append(
            {"label": t, "href": href_for([x for x in selected if x != t]), "on": True}
        )
    return out


# The kind whose tags the left rail shows on each menu screen; every other
# screen (overview, top search, errors) shows the tags of all kinds.
_SCREEN_KIND = {"docs": KB, "plans": BA, "plan": BA, "code": DEV}

# Tag-only browse of one kind renders as that kind's menu: (rail screen, docs.html menu).
_BROWSE_MENU = {KB: ("docs", "docs"), BA: ("plans", "tickets"), DEV: ("code", "code")}

# Where each kind's menu lives, and the reader's back-link wording.
MENU_PATH = {KB: "/ui/docs", BA: "/ui/tickets", DEV: "/ui/code"}
_BACK_LABEL = {KB: "all documents", BA: "all tickets", DEV: "all code"}


def _shell_ctx(
    config: ServerConfig,
    screen: str,
    q: str = "",
    raw_tags: str = "",
    budget: int | None = None,
    semantic_on: bool | None = None,
    href_kind: str | None = None,
) -> dict:
    selected = [t.strip() for t in raw_tags.split(",") if t.strip()]
    scope = _SCREEN_KIND.get(screen)
    # The cloud is scoped by `scope`; hrefs keep the menu's kind, or (on the
    # top-search screen, cloud global) the kind chip that is on.
    href_scope = scope or href_kind
    hub = api.hub_handle(config)
    if hub is None:
        return {
            "screen": screen,
            "menu_kind": scope or "",
            "hub_ok": False,
            "q": q,
            "raw_tags": raw_tags,
            "budget": budget,
            "repo_count": 0,
            "tags": _tag_links(
                [],
                selected,
                q,
                budget=budget,
                semantic_on=semantic_on,
                kind=href_scope,
            ),
            "selected_tags": selected,
        }
    return {
        "screen": screen,
        "menu_kind": scope or "",
        "hub_ok": True,
        "q": q,
        "raw_tags": raw_tags,
        "budget": budget,
        "repo_count": len(load_federation(hub.federation_dir)),
        "tags": _tag_links(
            uidata.all_tags(hub, kinds=[scope] if scope else None),
            selected,
            q,
            budget=budget,
            semantic_on=semantic_on,
            kind=href_scope,
        ),
        "selected_tags": selected,
    }


def _render_page(
    template: str,
    config: ServerConfig,
    screen: str,
    status: int = 200,
    q: str = "",
    raw_tags: str = "",
    budget: int | None = None,
    semantic_on: bool | None = None,
    shell_extra: dict | None = None,
    href_kind: str | None = None,
    **ctx,
) -> HTMLResponse:
    # raw_tags/budget/semantic_on are only ever passed by _search_screen
    # (every other caller keeps the falsy defaults, so their shell carries
    # no topbar hidden fields); re-mirrored into ctx so search.html's own
    # top-level {{ raw_tags }}/{{ budget }}/{{ semantic_on }} references
    # (meta-line, budget rail form, match-mode rail form) keep working
    # exactly as before this shell plumbing was added.
    shell = _shell_ctx(
        config,
        screen,
        q=q,
        raw_tags=raw_tags,
        budget=budget,
        semantic_on=semantic_on,
        href_kind=href_kind,
    )
    if shell_extra:
        shell.update(shell_extra)
    ctx["q"] = q
    ctx["raw_tags"] = raw_tags
    ctx["budget"] = budget
    ctx["semantic_on"] = semantic_on
    return HTMLResponse(
        templating.render(template, shell=shell, **ctx), status_code=status
    )


def render_error_page(
    config: ServerConfig, *, status: int, title: str, detail: str
) -> HTMLResponse:
    """Render the shared error shell (used for the 404 path, and by app.py's
    SnapshotCorruptError handler for a corrupt published snapshot)."""
    return _render_page(
        "error.html",
        config,
        screen="",
        status=status,
        title=title,
        code=str(status),
        heading=title,
        message=detail,
    )


def _match_tags(docs: list[dict], tags: list[str]) -> list[dict]:
    tagset = {t.lower() for t in tags}
    return [
        d
        for d in docs
        if tagset & {t.lower() for t in d["tags"]} or d["id"].lower() in tagset
    ]


STATIC_TYPES = {".css": "text/css", ".js": "text/javascript", ".woff2": "font/woff2"}


async def static_file(request: Request) -> Response:
    name = request.path_params["path"]
    suffix = Path(name).suffix
    media = STATIC_TYPES.get(suffix)
    # ":" and "\" never appear in legit asset names; they cover Windows
    # drive-absolute (C:\...) and backslash traversal, where a bare
    # startswith("/") check does not.
    if (
        media is None
        or ".." in name
        or name.startswith("/")
        or ":" in name
        or "\\" in name
    ):
        return Response("not found", status_code=404)
    target = (
        resources.files("strata_kb").joinpath("templates/web/static").joinpath(name)
    )
    try:
        if not target.is_file():
            return Response("not found", status_code=404)
        data = await run_in_threadpool(target.read_bytes)
    except OSError as exc:
        # e.g. ENAMETOOLONG for pathologically long segments — treat as a
        # miss rather than surfacing a 500 to the (auth-exempt) caller.
        logger.warning("static file lookup failed for %r: %s", name, exc)
        return Response("not found", status_code=404)
    return Response(
        data,
        media_type=media,
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _kind_counts(by_kind: dict[str, int]) -> list[dict]:
    return [
        {"kind": k, "label": MENU[k], "count": by_kind.get(k, 0)} for k in HUB_KINDS
    ]


def _kind_of(config: ServerConfig, rid: str) -> str:
    hub = api.hub_handle(config)
    return uidata.repo_kind(hub, rid) if hub is not None else KB


def _tree_extra(
    manifest, doc_id: str, rid: str, kind: str = KB, active: str = ""
) -> dict:
    meta = f"{len(manifest.sections)} sections"
    if manifest.revision:
        meta = f"{manifest.revision} · {meta}"
    return {
        "tree": uidata.section_tree(manifest),
        "tree_doc": {
            "id": doc_id,
            "repo": rid,
            "name": manifest.title,
            "meta": meta,
            "active": active,
            "kind": kind,
            "back_href": MENU_PATH[kind],
            "back_label": _BACK_LABEL[kind],
        },
    }


def _budget(request: Request) -> int:
    try:
        b = int(request.query_params.get("budget", "2000"))
    except ValueError:
        b = 2000
    return max(200, min(b, 8000))


def _use_semantic(request: Request) -> bool:
    vals = request.query_params.getlist("semantic")
    return ("1" in vals) if vals else True


def _hits(
    request: Request,
    hub,
    q: str,
    tags: list[str],
    kinds: list[str] | None = None,
) -> list:
    """`search()` for a screen: a caller error (too many tags, busy index,
    unknown kind) degrades to no hits -- the templates have no slot for the
    message -- and is logged; a corrupt snapshot is the 503 page."""
    try:
        return search(
            hub,
            q,
            tags=tags or None,
            budget=_budget(request),
            use_semantic=_use_semantic(request),
            kinds=kinds,
        )
    except (
        searchdb.TooManyTagsError,
        searchdb.IndexBusyError,
        UnknownKindError,
    ) as exc:
        logger.warning("search screen: %s", exc)
        return []
    except (yaml.YAMLError, ValidationError, ValueError) as exc:
        # Same as api.py's api_search: search() syncs every federated repo's
        # manifest before searching, so a corrupt manifest anywhere surfaces
        # here with no single doc_id to name.
        raise api.SnapshotCorruptError("", " ".join(str(exc).split())) from exc


def _hit_cards(hub, found: list, terms: set[str]) -> list[dict]:
    """Template rows of search hits; a `ba` hit links to its Ticket page."""
    smap = uidata.status_map(hub)
    plan_paths = planstatus.section_paths(hub) if found else {}
    top = max((r.score for r in found), default=1.0) or 1.0
    return [
        {
            "citation": r.citation,
            "title": r.title,
            "kind": r.kind,
            "kind_label": MENU.get(r.kind, r.kind),
            "status": smap.get((r.source, r.doc_id, r.section_id), "pending"),
            "match_mode": r.match_mode,
            # content_tokens, not tokens: the rendered card shows only
            # r.content (via md_render below), never r.snippet.
            "tokens": r.content_tokens,
            "score_pct": round(100 * r.score / top),
            "body_html": md_render(r.content, terms=terms),
            "file": f"{r.doc_id}/{r.section_id}",
            "href": (planstatus.hit_href(plan_paths, r) if r.kind == BA else None)
            or (
                f"/ui/docs/{quote(r.doc_id)}/{quote(r.section_id)}"
                f"?repo={quote(r.source)}"
            ),
        }
        for r in found
    ]


def menu_search(config: ServerConfig, request: Request, kind: str) -> dict:
    """Template context for a menu's own search box (`?q=` on /ui/docs,
    /ui/tickets, /ui/code): hits of that kind only, rendered inside the menu.
    `menu_q` is "" when the box was not used."""
    q = request.query_params.get("q", "").strip()
    out: dict = {"menu_q": q, "menu_results": [], "menu_label": MENU[kind]}
    hub = api.hub_handle(config) if q else None
    if hub is not None:
        found = _hits(request, hub, q, [], kinds=[kind])
        out["menu_results"] = _hit_cards(hub, found, set(tokenize(q)))
    return out


def _kind_chips(request: Request, q: str, found: list, shown: str | None) -> list[dict]:
    """ "All n" plus one chip per kind. Counts come from the unfiltered hits;
    "All" carries no `kind` param (an empty one is an unknown kind)."""
    counts = Counter(r.kind for r in found)
    base = [("q", q)]
    if raw_tags := request.query_params.get("tags", "").strip():
        base.append(("tags", raw_tags))
    base += [
        ("budget", str(_budget(request))),
        ("semantic", "1" if _use_semantic(request) else "0"),
    ]

    def chip(label: str, count: int, kind: str | None) -> dict:
        params = [*base, ("kind", kind)] if kind else base
        return {
            "label": label,
            "count": count,
            "href": f"/ui?{urlencode(params)}",
            "on": kind == shown,
        }

    return [
        chip("All", len(found), None),
        *(chip(MENU[k], counts[k], k) for k in HUB_KINDS),
    ]


def build_routes(
    config: ServerConfig,
    token: str,
    store_factory=None,
    login_limiter=None,
    trusted_proxies: int | None = None,
) -> list[Route]:
    limiter = login_limiter or SlidingWindowLimiter(
        LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS
    )
    # This route has no IntakeConfig to read (build_routes only gets
    # ServerConfig), so it reads the same env var through ratelimit.py's
    # shared parser rather than duplicating intake.py's parsing -- one
    # authority for STRATA_KB_TRUSTED_PROXIES, covering both limiters.
    # create_app reads it once and passes it in, so the middleware and the
    # login form cannot disagree about the proxy count -- the env fallback
    # stays for direct unit callers (e.g. test_web_ui.py) that build routes
    # without going through create_app.
    if trusted_proxies is None:
        trusted_proxies = trusted_proxies_from_env()

    async def login_get(request: Request) -> HTMLResponse:
        return HTMLResponse(templating.render("login.html", error=""), headers=NO_STORE)

    async def login_post(request: Request) -> Response:
        # Checked first, before the rate limiter and before request.form()
        # touches the body: a fat-fingered paste (an honest mistake) is not
        # an attempt at the shared secret, so it must not spend a lockout
        # attempt the same way a wrong token does (the same rule as auth's
        # _credential_presented -- absence/non-attempt doesn't count). An
        # attacker sending oversized bodies to probe gains nothing either:
        # this is a header-only check, no body is ever read, so it costs the
        # server nothing regardless of whether it is rate-limited.
        if int(request.headers.get("content-length") or 0) > LOGIN_MAX_BODY:
            return HTMLResponse("body too large", status_code=413, headers=NO_STORE)
        client_ip = client_key(request, trusted_proxies)
        # Checked before the token compare: a brute-forcer must not learn of
        # a hit inside the lockout window.
        if not limiter.allow(client_ip):
            logger.warning("login rate-limited for %s", client_ip)
            return HTMLResponse(
                templating.render(
                    "login.html", error="Too many attempts — try again later."
                ),
                status_code=429,
                headers=NO_STORE,
            )
        # The Content-Length check above does not bound a chunked body, and
        # request.form() alone buffers up to 1 MiB per field × 1000 fields:
        # one unauthenticated request could OOM the whole service. The capped
        # receive refuses the bytes off the wire.
        capped = Request(
            request.scope,
            bodycap.capped_receive(request, LOGIN_MAX_BODY, _LoginBodyTooLarge),
        )
        try:
            form = await capped.form(max_files=0, max_fields=4)
        except _LoginBodyTooLarge:
            return HTMLResponse("body too large", status_code=413, headers=NO_STORE)
        submitted = str(form.get("token", ""))
        await capped.close()
        # Bytes, not str: compare_digest raises TypeError on a non-ASCII str,
        # which would be a 500 for any non-ASCII guess.
        if hmac.compare_digest(submitted.encode("utf-8"), token.encode("utf-8")):
            resp = RedirectResponse("/ui", status_code=303, headers=NO_STORE)
            secure = cookie_is_secure(request, trusted_proxies)
            if not secure:
                logger.warning(
                    "session cookie set without Secure — request arrived over "
                    "plain HTTP. Behind a TLS proxy, set "
                    "STRATA_KB_TRUSTED_PROXIES to the number of proxies in "
                    "front so X-Forwarded-Proto is believed."
                )
            resp.set_cookie(
                COOKIE_NAME,
                make_session(token),
                httponly=True,
                samesite="lax",
                secure=secure,
                max_age=SESSION_MAX_AGE,
            )
            # Drop cookies from prior product names so an upgrade does not
            # leave an old session (or the pre-0.25 raw-token cookie) in
            # the jar. Path="/" matches those set_cookie calls.
            resp.delete_cookie("center_kb_token", path="/")
            resp.delete_cookie("center_kb_session", path="/")
            return resp
        # never log the submitted value — it may be a near-miss of the token
        logger.warning("failed login attempt from %s", client_ip)
        return HTMLResponse(
            templating.render(
                "login.html", error="Invalid token — check for trailing spaces."
            ),
            headers=NO_STORE,
        )

    async def logout_post(request: Request) -> Response:
        resp = RedirectResponse("/ui/login", status_code=303, headers=NO_STORE)
        resp.delete_cookie(COOKIE_NAME, path="/")
        resp.delete_cookie("center_kb_token", path="/")
        resp.delete_cookie("center_kb_session", path="/")
        return resp

    def _search_screen(request: Request, q: str, raw_tags: str) -> HTMLResponse:
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        kind = request.query_params.get("kind", "").strip()
        hub = api.hub_handle(config)
        if hub is None:
            return _render_page(
                "search.html",
                config,
                screen="search",
                title="Search",
                q=q,
                results=[],
                kind_chips=[],
                kind=kind,
                budget=_budget(request),
                active_tags=tags,
                raw_tags=raw_tags,
                docs_count=0,
                semantic_on=True,
            )
        if not q and tags:
            docs = api.list_docs(config) or []
            screen, menu = "search", "docs"
            try:
                browse_kind = normalize_kinds([kind])[0] if kind else None
            except UnknownKindError as exc:
                logger.warning("search screen: %s", exc)
                docs, browse_kind = [], None
            if browse_kind:
                docs = [d for d in docs if d["kind"] == browse_kind]
                screen, menu = _BROWSE_MENU[browse_kind]
            matched = _match_tags(docs, tags)
            return _render_page(
                "docs.html",
                config,
                screen=screen,
                title=MENU[browse_kind or KB],
                menu=menu,
                docs=matched,
                browse_tags=tags,
                raw_tags=raw_tags,
                menu_q="",
                menu_results=[],
                total_docs=len(docs),
            )
        budget = _budget(request)
        terms = set(tokenize(q))
        # An empty query with no tags has nothing to search for -- skip the
        # lookup and render the search screen's empty state rather than
        # asking search() to match on "".
        use_semantic = _use_semantic(request)
        # The unfiltered hits feed the chip counts; `kind` only narrows what
        # is listed, so the counts stay put when a chip is chosen.
        shown = None
        found: list = []
        try:
            shown = normalize_kinds([kind])[0] if kind else None
        except UnknownKindError as exc:
            logger.warning("search screen: %s", exc)
        else:
            found = _hits(request, hub, q, tags) if q else []
        listed = [r for r in found if shown in (None, r.kind)]
        return _render_page(
            "search.html",
            config,
            screen="search",
            title="Search",
            q=q,
            href_kind=shown,
            results=_hit_cards(hub, listed, terms),
            kind_chips=_kind_chips(request, q, found, shown) if found else [],
            kind=kind,
            budget=budget,
            active_tags=tags,
            raw_tags=raw_tags,
            docs_count=len({r.doc_id for r in listed}),
            semantic_on=use_semantic,
        )

    def home(request: Request) -> HTMLResponse:
        q = request.query_params.get("q", "").strip()
        raw_tags = request.query_params.get("tags", "").strip()
        # Presence of the `q` param (even empty, as in the nav "Search" link's
        # `/ui?q=`) routes to the search screen; only a bare `/ui` with no
        # query params at all renders the overview.
        if "q" in request.query_params or raw_tags:
            return _search_screen(request, q, raw_tags)
        hub = api.hub_handle(config)
        if hub is None:
            return _render_page(
                "overview.html",
                config,
                screen="overview",
                title="Overview",
                stats=uidata.StoreStats(0, 0, 0, 0),
                kind_counts=_kind_counts({}),
                queue=[],
                pending_total=0,
                awaiting_total=0,
                index_ok=False,
                publish=uidata.PublishInfo(),
            )
        stats = uidata.store_stats(hub)
        queue = uidata.review_queue(hub)
        cat = uidata.catalog(hub)
        pending_total = sum(d.pending for d in cat)
        awaiting_total = sum(d.pending + d.summarized for d in cat)
        return _render_page(
            "overview.html",
            config,
            screen="overview",
            title="Overview",
            stats=stats,
            kind_counts=_kind_counts(stats.by_kind),
            queue=queue,
            pending_total=pending_total,
            awaiting_total=awaiting_total,
            index_ok=(hub.federation_dir / "index.yaml").exists(),
            publish=uidata.last_publish(hub),
        )

    def _menu_docs_page(request: Request, kind: str, menu: str) -> HTMLResponse:
        all_docs = [d for d in api.list_docs(config) or [] if d["kind"] == kind]
        return _render_page(
            "docs.html",
            config,
            screen=menu,
            title=MENU[kind],
            menu=menu,
            docs=all_docs,
            browse_tags=[],
            total_docs=len(all_docs),
            **menu_search(config, request, kind),
        )

    def docs_page(request: Request) -> HTMLResponse:
        return _menu_docs_page(request, KB, "docs")

    def code_page(request: Request) -> HTMLResponse:
        return _menu_docs_page(request, DEV, "code")

    def doc_page(request: Request) -> HTMLResponse:
        doc_id = request.path_params["doc"]
        repo = request.query_params.get("repo") or None
        try:
            found = api.load_manifest(config, doc_id, repo=repo)
        except AmbiguousDocError as exc:
            return render_error_page(
                config, status=400, title="Ambiguous document", detail=str(exc)
            )
        if found is None:
            return render_error_page(
                config,
                status=404,
                title="Not found",
                detail=f"Unknown doc '{doc_id}'.",
            )
        manifest, rid = found
        # filter_raw preserves the caller's original casing for echoing back
        # into the filter input's value= attribute (passed to the template
        # as filter_value); filter_q is the lowered form used for the
        # (case-insensitive) row match below.
        filter_raw = request.query_params.get("filter", "").strip()
        filter_q = filter_raw.lower()
        status_q = request.query_params.get("status", "all")
        if status_q not in ("all", "pending", "summarized", "reviewed"):
            status_q = "all"
        rows = [
            s
            for s in manifest.sections
            if (status_q == "all" or s.status == status_q)
            and (not filter_q or filter_q in f"{s.id} {s.title} {s.summary}".lower())
        ]
        files = sorted({s.file for s in manifest.sections})
        return _render_page(
            "doc.html",
            config,
            screen="doc",
            title=manifest.title,
            doc_id=doc_id,
            manifest=manifest,
            rid=rid,
            rows=rows,
            coverage=uidata.doc_coverage(manifest),
            filter_value=filter_raw,
            status_q=status_q,
            files=files,
            shell_extra=_tree_extra(manifest, doc_id, rid, _kind_of(config, rid)),
        )

    def section_page(request: Request) -> HTMLResponse:
        doc_id = request.path_params["doc"]
        section_id = request.path_params["section"]
        level = request.query_params.get("level", "l2")
        if level not in ("l2", "l3"):
            level = "l2"
        repo = request.query_params.get("repo") or None
        hub = api.hub_handle(config)
        if hub is None:
            return render_error_page(
                config,
                status=503,
                title="Hub unreachable",
                detail="The federation is the only read source.",
            )
        try:
            result = get_section(hub, doc_id, section_id, level=level, repo=repo)
        except AmbiguousDocError as exc:
            return render_error_page(
                config, status=400, title="Ambiguous document", detail=str(exc)
            )
        except (yaml.YAMLError, ValidationError, ValueError) as exc:
            raise api.SnapshotCorruptError(doc_id, " ".join(str(exc).split())) from exc
        if result is None:
            return render_error_page(
                config,
                status=404,
                title="Not found",
                detail=f"{doc_id} §{section_id} not found.",
            )
        prev = nxt = entry = None
        revision = ""
        # repo=result.source is always a concrete repo id here (get_section
        # already resolved it), so this can't raise AmbiguousDocError — that
        # only fires when repo is None and >1 repo holds the same doc_id.
        # found is None only for the theoretical race of the doc vanishing
        # between get_section's and this call's federation reads; the
        # `entry`/`prev`/`next` = None fallback below (and section.html's
        # rail `{% if entry %}` branch) keeps that degrade graceful.
        shell_extra = None
        found = api.load_manifest(config, result.doc_id, repo=result.source)
        if found is not None:
            manifest, _ = found
            revision = manifest.revision
            prev, nxt = uidata.prev_next(manifest, result.section_id)
            entry = next(
                (s for s in manifest.sections if s.id == result.section_id), None
            )
            shell_extra = _tree_extra(
                manifest,
                result.doc_id,
                result.source,
                _kind_of(config, result.source),
                active=result.section_id,
            )
        content_html, toc = uidata.inject_heading_anchors(md_render(result.content))
        return _render_page(
            "section.html",
            config,
            screen="section",
            title=f"{doc_id} §{section_id}",
            doc_id=result.doc_id,
            section_id=result.section_id,
            repo=result.source,
            level=level,
            result=result,
            content_html=content_html,
            toc=toc,
            prev=prev,
            next=nxt,
            entry=entry,
            revision=revision,
            shell_extra=shell_extra,
        )

    asset_name_re = re.compile(r"^[0-9a-f]{64}\.(?:png|webp)$")
    asset_cache: dict[str, Path] = {}

    resolve_store = store_factory or assetstore.store_for_hub
    store_cache: dict[str, object] = {}  # hub root → store (or None), built once

    def _store_for(hub):
        key = str(hub.root)
        if key not in store_cache:
            store_cache[key] = resolve_store(hub)
        return store_cache[key]

    def _disk_cache_dir() -> Path:
        return hub_mod._cache_base() / "asset-cache"

    def _find_asset(hub, name: str) -> Path | None:
        """Resolve a content-addressed asset filename to a path.

        Positive hits only are cached: content-addressed files are immutable
        once written, so a cached hit stays valid for the process lifetime
        (re-verified with is_file() in case the file vanished). Misses are
        never cached — a later publish can add the asset.

        Local dirs miss → fall through to the object store (if configured):
        a store hit is written to the on-disk cache and served from there on
        subsequent requests. A store lookup failure raises AssetStoreError,
        which propagates to the handler for a 503 response.

        A local-tree or disk-cache hit is hash-verified before being served
        or cached; a mismatch is treated as a miss (disk-cache is evicted)
        so a bad object heals on the next request instead of being served
        forever.
        """
        cached = asset_cache.get(name)
        if cached is not None and cached.is_file():
            return cached
        # federation/ only: the hub's own .kb/ is unpublished work and README
        # promises the server never reads it.
        # Content-addressed name → any hit is THE asset (natural dedupe).
        local_hit = None
        if hub.federation_dir.is_dir():
            local_hit = next(hub.federation_dir.glob(f"**/assets/{name}"), None)
        if local_hit is not None:
            if assetstore.verify_bytes(name, local_hit.read_bytes()):
                asset_cache[name] = local_hit
                return local_hit
            logger.warning(
                "local asset %s does not match its name -- ignoring, "
                "falling through to the store",
                local_hit,
            )
        cache_file = _disk_cache_dir() / name
        if cache_file.is_file():
            if assetstore.verify_bytes(name, cache_file.read_bytes()):
                asset_cache[name] = cache_file
                return cache_file
            logger.warning(
                "disk-cached asset %s does not match its name -- evicting, "
                "falling through to the store",
                cache_file,
            )
            try:
                cache_file.unlink()
            except OSError as exc:
                logger.warning("asset disk cache evict failed: %s", exc)
        store = _store_for(hub)
        if store is not None:
            data = assetstore.get_verified(store, name)  # errors propagate to handler
            if data is not None:
                target = cache_file
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                except OSError as exc:
                    logger.warning("asset disk cache write failed: %s", exc)
                    fd, tmp_name = tempfile.mkstemp(suffix=Path(name).suffix)
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(data)
                    target = Path(tmp_name)
                asset_cache[name] = target
                return target
        return None

    async def asset(request: Request) -> Response:
        name = request.path_params["name"]
        if not asset_name_re.match(name):
            return Response("not found", status_code=404)
        # hub_handle can run git (and pull when the TTL expired): off the loop.
        hub = await run_in_threadpool(api.hub_handle, config)
        if hub is None:
            return Response("hub unreachable", status_code=503)
        try:
            path = await run_in_threadpool(_find_asset, hub, name)
        except assetstore.AssetStoreError as exc:
            logger.warning("asset store lookup failed: %s", exc)
            return Response("asset store unavailable", status_code=503)
        if path is None:
            return Response("not found", status_code=404)
        media = "image/png" if name.endswith(".png") else "image/webp"
        data = await run_in_threadpool(path.read_bytes)
        return Response(
            data,
            media_type=media,
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    return [
        Route("/ui", home, methods=["GET"]),
        Route("/ui/login", login_get, methods=["GET"]),
        Route("/ui/login", login_post, methods=["POST"]),
        Route("/ui/logout", logout_post, methods=["POST"]),
        Route("/ui/docs", docs_page, methods=["GET"]),
        Route("/ui/code", code_page, methods=["GET"]),
        Route("/ui/docs/{doc}", doc_page, methods=["GET"]),
        Route("/ui/docs/{doc}/{section}", section_page, methods=["GET"]),
        Route("/ui/static/{path:path}", static_file, methods=["GET"]),
        Route("/assets/{name}", asset, methods=["GET"]),
    ]
