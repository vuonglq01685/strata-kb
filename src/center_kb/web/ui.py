# src/center_kb/web/ui.py
from __future__ import annotations

import hmac
import logging
import os
import re
import tempfile
from importlib import resources
from urllib.parse import quote, urlencode

from pathlib import Path

import yaml
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from center_kb import assetstore, searchdb
from center_kb import hub as hub_mod
from center_kb.federation import load_federation
from center_kb.mcp import ServerConfig
from center_kb.query import AmbiguousDocError, get_section, search, tokenize
from center_kb.web import api, templating, uidata
from center_kb.web.auth import (
    COOKIE_NAME,
    SESSION_MAX_AGE,
    cookie_is_secure,
    make_session,
)
from center_kb.web.mdrender import render as md_render
from center_kb.web.ratelimit import (
    LOGIN_MAX_ATTEMPTS,
    LOGIN_WINDOW_SECONDS,
    SlidingWindowLimiter,
    client_key,
    trusted_proxies_from_env,
)

logger = logging.getLogger("center_kb.web.ui")

# /ui/login is unauthenticated and auth-exempt, and Starlette applies no size
# limit to a form body -- the same reason intake_routes caps every upload
# (intake_routes.read_capped). A token is tens of bytes; 8 KiB is generous.
#
# Fix round 1 (Minor C): a chunked request (no Content-Length) skips the
# header check below and reaches request.form() regardless -- still bounded,
# but not because "the token field is not a file part" (that reasoning was
# wrong: Starlette's FormParser, not just MultiPartParser, enforces its own
# limits on plain url-encoded fields too). Verified against pinned Starlette
# 1.6.0: FormParser caps each field at max_part_size (1 MiB) and the whole
# form at max_fields (1000), raising HTTPException(400) past either. Residual
# worth naming: up to ~1000 fields x 1 MiB can accumulate in
# FormParser.messages before the field-count check trips -- reachable only
# via chunked, and bounded to LOGIN_MAX_ATTEMPTS per client per
# LOGIN_WINDOW_SECONDS because login_post's limiter check runs before form().
LOGIN_MAX_BODY = 8 * 1024

NO_STORE = {"Cache-Control": "no-store"}


def _tag_links(
    all_tags: list[str], selected: list[str], q: str,
    budget: int | None = None, semantic_on: bool | None = None,
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
    """

    def href_for(new: list[str]) -> str:
        if not q and not new:
            return "/ui?q="
        params: list[tuple[str, str]] = []
        if q:
            params.append(("q", q))
        if new:
            params.append(("tags", ",".join(new)))
        if budget is not None:
            params.append(("budget", str(budget)))
        if semantic_on is not None:
            params.append(("semantic", "1" if semantic_on else "0"))
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
        out.append({"label": t, "href": href_for([x for x in selected if x != t]), "on": True})
    return out


def _shell_ctx(
    config: ServerConfig, screen: str, q: str = "",
    raw_tags: str = "", budget: int | None = None,
    semantic_on: bool | None = None,
) -> dict:
    selected = [t.strip() for t in raw_tags.split(",") if t.strip()]
    hub = api.hub_handle(config)
    if hub is None:
        return {"screen": screen, "hub_ok": False, "q": q,
                "raw_tags": raw_tags, "budget": budget,
                "repo_count": 0,
                "tags": _tag_links([], selected, q, budget=budget,
                                    semantic_on=semantic_on),
                "selected_tags": selected}
    return {
        "screen": screen, "hub_ok": True, "q": q,
        "raw_tags": raw_tags, "budget": budget,
        "repo_count": len(load_federation(hub.federation_dir)),
        "tags": _tag_links(uidata.all_tags(hub), selected, q, budget=budget,
                            semantic_on=semantic_on),
        "selected_tags": selected,
    }


def _render_page(
    template: str, config: ServerConfig, screen: str,
    status: int = 200, q: str = "", raw_tags: str = "",
    budget: int | None = None, semantic_on: bool | None = None,
    shell_extra: dict | None = None, **ctx,
) -> HTMLResponse:
    # raw_tags/budget/semantic_on are only ever passed by _search_screen
    # (every other caller keeps the falsy defaults, so their shell carries
    # no topbar hidden fields); re-mirrored into ctx so search.html's own
    # top-level {{ raw_tags }}/{{ budget }}/{{ semantic_on }} references
    # (meta-line, budget rail form, match-mode rail form) keep working
    # exactly as before this shell plumbing was added.
    shell = _shell_ctx(config, screen, q=q, raw_tags=raw_tags, budget=budget,
                        semantic_on=semantic_on)
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
    SnapshotCorruptError handler for a corrupt published snapshot, M8)."""
    return _render_page(
        "error.html", config, screen="", status=status,
        title=title, code=str(status), heading=title, message=detail,
    )


def _match_tags(docs: list[dict], tags: list[str]) -> list[dict]:
    tagset = {t.lower() for t in tags}
    return [
        d for d in docs
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
    if media is None or ".." in name or name.startswith("/") or ":" in name or "\\" in name:
        return Response("not found", status_code=404)
    target = resources.files("center_kb").joinpath("templates/web/static").joinpath(name)
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
        data, media_type=media,
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _tree_extra(manifest, doc_id: str, rid: str, active: str = "") -> dict:
    meta = f"{len(manifest.sections)} sections"
    if manifest.revision:
        meta = f"{manifest.revision} · {meta}"
    return {
        "tree": uidata.section_tree(manifest),
        "tree_doc": {"id": doc_id, "repo": rid, "name": manifest.title,
                     "meta": meta, "active": active},
    }


def build_routes(
    config: ServerConfig, token: str, store_factory=None, login_limiter=None,
    trusted_proxies: int | None = None,
) -> list[Route]:
    limiter = login_limiter or SlidingWindowLimiter(
        LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS
    )
    # F-D12 item 4: this route has no IntakeConfig to read (build_routes only
    # gets ServerConfig), so it reads the same env var through ratelimit.py's
    # shared parser rather than duplicating intake.py's parsing -- one
    # authority for CENTER_KB_TRUSTED_PROXIES, covering both limiters.
    # Task 11: create_app now reads it once and passes it in, so the
    # middleware and the login form cannot disagree about the proxy count --
    # the env fallback stays for direct unit callers (e.g. test_web_ui.py)
    # that build routes without going through create_app.
    if trusted_proxies is None:
        trusted_proxies = trusted_proxies_from_env()

    async def login_get(request: Request) -> HTMLResponse:
        return HTMLResponse(templating.render("login.html", error=""), headers=NO_STORE)

    async def login_post(request: Request) -> Response:
        # Checked first, before the rate limiter and before request.form()
        # touches the body: a fat-fingered paste (an honest mistake) is not
        # an attempt at the shared secret, so it must not spend a lockout
        # attempt the same way a wrong token does (M6's own rule for
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
        form = await request.form()
        submitted = str(form.get("token", ""))
        if hmac.compare_digest(submitted, token):
            resp = RedirectResponse("/ui", status_code=303, headers=NO_STORE)
            secure = cookie_is_secure(request, trusted_proxies)
            if not secure:
                logger.warning(
                    "session cookie set without Secure — request arrived over "
                    "plain HTTP. Behind a TLS proxy, set "
                    "CENTER_KB_TRUSTED_PROXIES to the number of proxies in "
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
            # Fix (final review item 4): pre-0.25 set center_kb_token = the
            # raw shared secret (no max_age -> a session cookie, but that was
            # luck, not design -- M4's whole point is that a cookie which IS
            # the token is an admin-equivalent credential at rest). The
            # session-cookie switch stopped READING it but never told any
            # existing browser to drop it, so upgrading left that secret
            # sitting in every user's jar indefinitely. Path="/" confirmed
            # against the pre-M4 set_cookie call (no path kwarg -> Starlette
            # default "/").
            resp.delete_cookie("center_kb_token", path="/")
            return resp
        # never log the submitted value — it may be a near-miss of the token
        logger.warning("failed login attempt from %s", client_ip)
        return HTMLResponse(
            templating.render("login.html", error="Invalid token — check for trailing spaces."),
            headers=NO_STORE,
        )

    async def logout_post(request: Request) -> Response:
        resp = RedirectResponse("/ui/login", status_code=303, headers=NO_STORE)
        resp.delete_cookie(COOKIE_NAME, path="/")
        # Fix (final review item 4): same pre-0.25 raw-token cookie as
        # login_post above -- logout must clear it too, not just the current
        # session cookie.
        resp.delete_cookie("center_kb_token", path="/")
        return resp

    def _budget(request: Request) -> int:
        try:
            b = int(request.query_params.get("budget", "2000"))
        except ValueError:
            b = 2000
        return max(200, min(b, 8000))

    async def _search_screen(request: Request, q: str, raw_tags: str) -> HTMLResponse:
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        hub = api.hub_handle(config)
        if hub is None:
            return _render_page(
                "search.html", config, screen="search", title="Search", q=q,
                results=[], budget=_budget(request), active_tags=tags,
                raw_tags=raw_tags, docs_count=0, semantic_on=True,
            )
        if not q and tags:
            docs = api.list_docs(config) or []
            matched = _match_tags(docs, tags)
            return _render_page(
                "docs.html", config, screen="docs", title="Documents",
                docs=matched, browse_tags=tags, raw_tags=raw_tags,
                filter_value="", total_docs=len(docs),
            )
        budget = _budget(request)
        terms = set(tokenize(q))
        # An empty query with no tags (e.g. the nav "Search" link, `/ui?q=`)
        # has nothing to search for — skip the lookup and render the search
        # screen's empty state rather than asking search() to match on "".
        sem_vals = request.query_params.getlist("semantic")
        use_semantic = ("1" in sem_vals) if sem_vals else True
        try:
            found = (
                await run_in_threadpool(
                    search, hub, q, tags=tags or None, budget=budget,
                    use_semantic=use_semantic,
                )
                if q else []
            )
        except (searchdb.TooManyTagsError, searchdb.IndexBusyError) as exc:
            # search.html has no slot for a caller-error message (only the
            # hub_ok / empty-results branches) — degrade to the normal empty
            # state rather than a 500; the reason is still logged server-side.
            logger.warning("search screen: %s", exc)
            found = []
        except (yaml.YAMLError, ValidationError, ValueError) as exc:
            # Same as api.py's api_search: search() syncs every federated
            # repo's manifest before searching, so a corrupt manifest
            # anywhere surfaces here with no single doc_id to name.
            raise api.SnapshotCorruptError("", " ".join(str(exc).split())) from exc
        docs_count = len({r.doc_id for r in found})
        smap = uidata.status_map(hub)
        top = max((r.score for r in found), default=1.0) or 1.0
        results = [
            {
                "citation": r.citation,
                "title": r.title,
                "status": smap.get((r.source, r.doc_id, r.section_id), "pending"),
                "match_mode": r.match_mode,
                # content_tokens, not tokens: the rendered card shows only
                # r.content (via md_render below), never r.snippet (M17).
                "tokens": r.content_tokens,
                "score_pct": round(100 * r.score / top),
                "body_html": md_render(r.content, terms=terms),
                "file": f"{r.doc_id}/{r.section_id}",
                "href": (
                    f"/ui/docs/{quote(r.doc_id)}/{quote(r.section_id)}"
                    f"?repo={quote(r.source)}"
                ),
            }
            for r in found
        ]
        return _render_page(
            "search.html", config, screen="search", title="Search", q=q,
            results=results, budget=budget, active_tags=tags, raw_tags=raw_tags,
            docs_count=docs_count, semantic_on=use_semantic,
        )

    async def home(request: Request) -> HTMLResponse:
        q = request.query_params.get("q", "").strip()
        raw_tags = request.query_params.get("tags", "").strip()
        # Presence of the `q` param (even empty, as in the nav "Search" link's
        # `/ui?q=`) routes to the search screen; only a bare `/ui` with no
        # query params at all renders the overview.
        if "q" in request.query_params or raw_tags:
            return await _search_screen(request, q, raw_tags)  # Task 6
        hub = api.hub_handle(config)
        if hub is None:
            return _render_page(
                "overview.html", config, screen="overview", title="Overview",
                stats=uidata.StoreStats(0, 0, 0, 0), queue=[], pending_total=0,
                awaiting_total=0, index_ok=False, publish=uidata.PublishInfo(),
            )
        stats = uidata.store_stats(hub)
        queue = uidata.review_queue(hub)
        cat = uidata.catalog(hub)
        pending_total = sum(d.pending for d in cat)
        awaiting_total = sum(d.pending + d.summarized for d in cat)
        return _render_page(
            "overview.html", config, screen="overview", title="Overview",
            stats=stats, queue=queue, pending_total=pending_total,
            awaiting_total=awaiting_total,
            index_ok=(hub.federation_dir / "index.yaml").exists(),
            publish=uidata.last_publish(hub),
        )

    async def docs_page(request: Request) -> HTMLResponse:
        all_docs = api.list_docs(config) or []
        filter_raw = request.query_params.get("filter", "").strip()
        fq = filter_raw.lower()
        docs = [
            d for d in all_docs
            if not fq
            or fq in d["id"].lower()
            or fq in (d.get("title") or "").lower()
            or any(fq in t.lower() for t in d["tags"])
        ]
        return _render_page(
            "docs.html", config, screen="docs", title="Documents",
            docs=docs, browse_tags=[], filter_value=filter_raw,
            total_docs=len(all_docs),
        )

    async def doc_page(request: Request) -> HTMLResponse:
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
                config, status=404, title="Not found",
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
            s for s in manifest.sections
            if (status_q == "all" or s.status == status_q)
            and (not filter_q or filter_q in f"{s.id} {s.title} {s.summary}".lower())
        ]
        files = sorted({s.file for s in manifest.sections})
        return _render_page(
            "doc.html", config, screen="doc", title=manifest.title,
            doc_id=doc_id, manifest=manifest, rid=rid, rows=rows,
            coverage=uidata.doc_coverage(manifest),
            filter_value=filter_raw, status_q=status_q, files=files,
            shell_extra=_tree_extra(manifest, doc_id, rid),
        )

    async def section_page(request: Request) -> HTMLResponse:
        doc_id = request.path_params["doc"]
        section_id = request.path_params["section"]
        level = request.query_params.get("level", "l2")
        if level not in ("l2", "l3"):
            level = "l2"
        repo = request.query_params.get("repo") or None
        hub = api.hub_handle(config)
        if hub is None:
            return render_error_page(
                config, status=503, title="Hub unreachable",
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
                config, status=404, title="Not found",
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
                manifest, result.doc_id, result.source, active=result.section_id
            )
        content_html, toc = uidata.inject_heading_anchors(
            md_render(result.content)
        )
        return _render_page(
            "section.html", config, screen="section",
            title=f"{doc_id} §{section_id}",
            doc_id=result.doc_id, section_id=result.section_id, repo=result.source,
            level=level, result=result, content_html=content_html, toc=toc,
            prev=prev, next=nxt, entry=entry, revision=revision,
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
        local_hit = None
        for base in (hub.kb_dir, hub.federation_dir):
            if not base.is_dir():
                continue
            # content-addressed name → any hit is THE asset (natural dedupe)
            for path in base.glob(f"**/assets/{name}"):
                local_hit = path
                break
            if local_hit is not None:
                break
        if local_hit is not None:
            if assetstore.verify_bytes(name, local_hit.read_bytes()):
                asset_cache[name] = local_hit
                return local_hit
            logger.warning(
                "local asset %s does not match its name -- ignoring, "
                "falling through to the store", local_hit,
            )
        cache_file = _disk_cache_dir() / name
        if cache_file.is_file():
            if assetstore.verify_bytes(name, cache_file.read_bytes()):
                asset_cache[name] = cache_file
                return cache_file
            logger.warning(
                "disk-cached asset %s does not match its name -- evicting, "
                "falling through to the store", cache_file,
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
        hub = api.hub_handle(config)
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
        Route("/ui/docs/{doc}", doc_page, methods=["GET"]),
        Route("/ui/docs/{doc}/{section}", section_page, methods=["GET"]),
        Route("/ui/static/{path:path}", static_file, methods=["GET"]),
        Route("/assets/{name}", asset, methods=["GET"]),
    ]
