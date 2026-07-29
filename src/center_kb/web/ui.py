# src/center_kb/web/ui.py
from __future__ import annotations

import hmac
import html
import logging
import os
import re
import tempfile
from importlib import resources
from string import Template
from urllib.parse import quote

from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from center_kb import assetstore
from center_kb import hub as hub_mod
from center_kb.mcp import ServerConfig
from center_kb.query import AmbiguousDocError, get_section, search, tokenize
from center_kb.web import api, templating, uidata
from center_kb.web.auth import COOKIE_NAME
from center_kb.web.mdrender import render as md_render
from center_kb.web.ratelimit import (
    LOGIN_MAX_ATTEMPTS,
    LOGIN_WINDOW_SECONDS,
    SlidingWindowLimiter,
)

logger = logging.getLogger("center_kb.web.ui")

HUB_DOWN_PAGE = (
    "<h1>503</h1><p>Hub unreachable — the federation is the only read source.</p>"
)


def _template(name: str) -> Template:
    text = (
        resources.files("center_kb")
        .joinpath(f"templates/web/{name}")
        .read_text(encoding="utf-8")
    )
    return Template(text)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    # Screens not yet converted to the Jinja shell (search/docs/doc/section —
    # see Tasks 5-8) render against this frozen copy of the pre-Task-4
    # base.html, since the real base.html is now a Jinja template (`{{ }}` /
    # `{% %}`) that string.Template's `$identifier` substitution can't fill.
    doc = _template("_legacy_base.html").substitute(title=html.escape(title), body=body)
    return HTMLResponse(doc, status_code=status)


def _shell_ctx(config: ServerConfig, screen: str, q: str = "") -> dict:
    hub = api.hub_handle(config)
    if hub is None:
        return {"screen": screen, "hub_ok": False, "q": q,
                "repo_count": 0, "catalog": [], "tags": []}
    return {
        "screen": screen, "hub_ok": True, "q": q,
        "repo_count": uidata.store_stats(hub).repos,
        "catalog": uidata.catalog(hub),
        "tags": uidata.all_tags(hub),
    }


def _render_page(
    template: str, config: ServerConfig, screen: str,
    status: int = 200, q: str = "", **ctx,
) -> HTMLResponse:
    shell = _shell_ctx(config, screen, q=q)
    ctx["q"] = q
    return HTMLResponse(
        templating.render(template, shell=shell, **ctx), status_code=status
    )


def _error_page(
    config: ServerConfig, code: int, heading: str, message: str
) -> HTMLResponse:
    return _render_page(
        "error.html", config, screen="", status=code,
        title=heading, code=str(code), heading=heading, message=message,
    )


def _e(text: str) -> str:
    return html.escape(text, quote=True)


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
    if media is None or ".." in name or name.startswith("/"):
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


def build_routes(
    config: ServerConfig, token: str, store_factory=None, login_limiter=None
) -> list[Route]:
    limiter = login_limiter or SlidingWindowLimiter(
        LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS
    )

    async def login_get(request: Request) -> HTMLResponse:
        return HTMLResponse(templating.render("login.html", error=""))

    async def login_post(request: Request) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        # Checked before the token compare: a brute-forcer must not learn of
        # a hit inside the lockout window.
        if not limiter.allow(client_ip):
            logger.warning("login rate-limited for %s", client_ip)
            return HTMLResponse(
                templating.render(
                    "login.html", error="Too many attempts — try again later."
                ),
                status_code=429,
            )
        form = await request.form()
        submitted = str(form.get("token", ""))
        if hmac.compare_digest(submitted, token):
            resp = RedirectResponse("/ui", status_code=303)
            resp.set_cookie(COOKIE_NAME, submitted, httponly=True, samesite="lax")
            return resp
        # never log the submitted value — it may be a near-miss of the token
        logger.warning("failed login attempt from %s", client_ip)
        return HTMLResponse(
            templating.render("login.html", error="Invalid token — check for trailing spaces.")
        )

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
                raw_tags=raw_tags, hub_ok=False,
            )
        if not q and tags:
            docs = api.list_docs(config) or []
            return _render_page(
                "docs.html", config, screen="docs", title="Documents",
                docs=_match_tags(docs, tags), browse_tags=tags,
            )
        budget = _budget(request)
        terms = set(tokenize(q))
        found = search(hub, q, tags=tags or None, budget=budget)
        smap = uidata.status_map(hub)
        top = max((r.score for r in found), default=1.0) or 1.0
        results = [
            {
                "citation": r.citation,
                "title": r.title,
                "status": smap.get((r.source, r.doc_id, r.section_id), "pending"),
                "match_mode": r.match_mode,
                "tokens": r.tokens,
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
            hub_ok=True,
        )

    async def home(request: Request) -> HTMLResponse:
        q = request.query_params.get("q", "").strip()
        raw_tags = request.query_params.get("tags", "").strip()
        if q or raw_tags:
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
        docs = api.list_docs(config) or []
        return _render_page(
            "docs.html", config, screen="docs", title="Documents",
            docs=docs, browse_tags=[],
        )

    async def doc_page(request: Request) -> HTMLResponse:
        doc_id = request.path_params["doc"]
        repo = request.query_params.get("repo") or None
        try:
            found = api.load_manifest(config, doc_id, repo=repo)
        except AmbiguousDocError as exc:
            return _error_page(config, 400, "Ambiguous document", str(exc))
        if found is None:
            return _error_page(config, 404, "Not found", f"Unknown doc '{doc_id}'.")
        manifest, rid = found
        # filter_raw preserves the caller's original casing for echoing back
        # into the filter input's value= attribute; filter_q is the lowered
        # form used for the (case-insensitive) row match below.
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
            filter_q=filter_raw, status_q=status_q, files=files,
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
            return _page("Hub unreachable", HUB_DOWN_PAGE, 503)
        try:
            result = get_section(hub, doc_id, section_id, level=level, repo=repo)
        except AmbiguousDocError as exc:
            return _page("Ambiguous document", f"<h1>400</h1><p>{_e(str(exc))}</p>", 400)
        if result is None:
            return _page(
                "Not found",
                f"<h1>404</h1><p>{_e(doc_id)} §{_e(section_id)} not found.</p>",
                404,
            )
        other = "l3" if level == "l2" else "l2"
        toggle_href = (
            f"/ui/docs/{quote(doc_id)}/{quote(section_id)}"
            f"?level={other}&repo={quote(result.source)}"
        )
        toggle = f'<a href="{toggle_href}">view {other.upper()}</a>'
        body = _template("section.html").substitute(
            doc_id=_e(doc_id),
            section_id=_e(section_id),
            title=_e(result.title),
            citation=_e(result.citation),
            tokens=str(result.tokens),
            level=level,
            toggle=toggle,
            content=md_render(result.content),
        )
        return _page(f"{doc_id} §{section_id}", body)

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
        """
        cached = asset_cache.get(name)
        if cached is not None and cached.is_file():
            return cached
        for base in (hub.kb_dir, hub.federation_dir):
            if not base.is_dir():
                continue
            # content-addressed name → any hit is THE asset (natural dedupe)
            for path in base.glob(f"**/assets/{name}"):
                asset_cache[name] = path
                return path
        cache_file = _disk_cache_dir() / name
        if cache_file.is_file():
            asset_cache[name] = cache_file
            return cache_file
        store = _store_for(hub)
        if store is not None:
            data = store.get(name)  # AssetStoreError propagates to the handler
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
        Route("/ui/docs", docs_page, methods=["GET"]),
        Route("/ui/docs/{doc}", doc_page, methods=["GET"]),
        Route("/ui/docs/{doc}/{section}", section_page, methods=["GET"]),
        Route("/ui/static/{path:path}", static_file, methods=["GET"]),
        Route("/assets/{name}", asset, methods=["GET"]),
    ]
