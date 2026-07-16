# src/center_kb/web/ui.py
from __future__ import annotations

import hmac
import html
import re
from importlib import resources
from string import Template
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from center_kb.mcp import ServerConfig
from center_kb.query import AmbiguousDocError, get_section, search, tokenize
from center_kb.web import api
from center_kb.web.auth import COOKIE_NAME
from center_kb.web.mdrender import render as md_render

HUB_DOWN_HTML = '<div class="empty-state"><p>Hub unreachable.</p></div>'
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
    doc = _template("base.html").substitute(title=html.escape(title), body=body)
    return HTMLResponse(doc, status_code=status)


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _status_span(status: str) -> str:
    return f'<span class="status-badge status-{_e(status)}">{_e(status)}</span>'


def _chips(tags: list[str]) -> str:
    if not tags:
        return '<span class="chip chip-empty">no tags</span>'
    return "".join(
        f'<a class="chip" href="/ui?tags={quote(t)}">{_e(t)}</a>' for t in tags
    )


def _source_badge(source: str) -> str:
    return f'<span class="source-badge source-remote">{_e(source)}</span>'


def _match_badge(mode: str) -> str:
    return f'<span class="match-badge match-{_e(mode)}">{_e(mode)}</span>'


def _result_blocks(results, terms: set[str] | None = None) -> str:
    if not results:
        return (
            '<div class="empty-state"><p>No matching section found.</p>'
            "<p>Try dropping tags or changing keywords.</p></div>"
        )
    blocks = []
    for r in results:
        href = f"/ui/docs/{quote(r.doc_id)}/{quote(r.section_id)}?repo={quote(r.source)}"
        blocks.append(
            '<article class="result">'
            '<header class="result-head">'
            f'<a class="cite" href="{href}">{_e(r.citation)}</a>'
            f"{_source_badge(r.source)}"
            f"{_match_badge(r.match_mode)}"
            f'<span class="score">~{r.tokens} tk</span>'
            "</header>"
            f'<div class="result-body">{md_render(r.content, terms=terms)}</div>'
            + (
                f'<div class="result-snippet">raw match: {_e(r.snippet)}</div>'
                if r.snippet
                else ""
            )
            + "</article>"
        )
    return "\n".join(blocks)


def _doc_cards(docs: list[dict]) -> str:
    if not docs:
        return (
            '<div class="empty-state"><p>No documents match those tags.</p>'
            "<p>Check the tag spelling or browse all documents.</p></div>"
        )
    cards = []
    for d in docs:
        title = _e(d["title"]) or _e(d["id"])
        href = f"/ui/docs/{quote(d['id'])}?repo={quote(d['repo'])}"
        name = f'<a href="{href}">{title}</a>'
        rev = f'<span class="rev">{_e(d["revision"])}</span>' if d["revision"] else ""
        cards.append(
            '<article class="doc-card">'
            f'<header class="result-head"><span class="doc-name">{name}</span> {rev}'
            f"{_source_badge(d['repo'])}</header>"
            f'<p class="doc-summary">{_e(d["summary"])}</p>'
            f'<p class="chips">{_chips(d["tags"])}</p>'
            "</article>"
        )
    return "\n".join(cards)


def _match_tags(docs: list[dict], tags: list[str]) -> list[dict]:
    tagset = {t.lower() for t in tags}
    return [
        d for d in docs
        if tagset & {t.lower() for t in d["tags"]} or d["id"].lower() in tagset
    ]


def build_routes(config: ServerConfig, token: str) -> list[Route]:
    async def login_get(request: Request) -> HTMLResponse:
        body = _template("login.html").substitute(error="")
        return _page("Sign in", body)

    async def login_post(request: Request) -> Response:
        form = await request.form()
        submitted = str(form.get("token", ""))
        if hmac.compare_digest(submitted, token):
            resp = RedirectResponse("/ui", status_code=303)
            resp.set_cookie(COOKIE_NAME, submitted, httponly=True, samesite="lax")
            return resp
        body = _template("login.html").substitute(
            error='<p class="error">Invalid token.</p>'
        )
        return _page("Sign in", body)

    async def home(request: Request) -> HTMLResponse:
        q = request.query_params.get("q", "").strip()
        raw_tags = request.query_params.get("tags", "").strip()
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        terms = set(tokenize(q)) if q else set()
        hub = api.hub_handle(config)
        results_html = ""
        if hub is None:
            results_html = HUB_DOWN_HTML
        elif q:
            results = search(hub, q, tags=tags or None, budget=2000)
            results_html = _result_blocks(results, terms)
        elif tags:
            docs = api.list_docs(config) or []
            results_html = _doc_cards(_match_tags(docs, tags))
        scope = "hub federation"
        body = _template("search.html").substitute(
            q=_e(q), tags=_e(raw_tags), scope=_e(scope), results=results_html
        )
        return _page("Search", body)

    async def docs_page(request: Request) -> HTMLResponse:
        cards = _doc_cards(api.list_docs(config) or [])
        body = _template("docs.html").substitute(cards=cards)
        return _page("Documents", body)

    async def doc_page(request: Request) -> HTMLResponse:
        doc_id = request.path_params["doc"]
        repo = request.query_params.get("repo") or None
        try:
            found = api.load_manifest(config, doc_id, repo=repo)
        except AmbiguousDocError as exc:
            return _page("Ambiguous document", f"<h1>400</h1><p>{_e(str(exc))}</p>", 400)
        if found is None:
            return _page("Not found", f"<h1>404</h1><p>Unknown doc '{_e(doc_id)}'.</p>", 404)
        manifest, rid = found
        rows = []
        for s in manifest.sections:
            href = f"/ui/docs/{quote(doc_id)}/{quote(s.id)}?repo={quote(rid)}"
            cell = f'<a href="{href}">§{_e(s.id)}</a>'
            rows.append(
                f"<tr><td>{cell}</td><td>{_e(s.title)}</td>"
                f"<td>{_e(s.summary)}</td><td>{_status_span(s.status)}</td></tr>"
            )
        repo_note = f'<p class="meta">repo: {_e(rid)}</p>'
        body = _template("doc.html").substitute(
            doc_id=_e(doc_id),
            title=_e(manifest.title),
            revision=_e(manifest.revision),
            repo_note=repo_note,
            rows="\n".join(rows),
        )
        return _page(manifest.title, body)

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

    async def static_css(request: Request) -> Response:
        css = (
            resources.files("center_kb")
            .joinpath("templates/web/style.css")
            .read_text(encoding="utf-8")
        )
        return Response(css, media_type="text/css")

    asset_name_re = re.compile(r"^[0-9a-f]{64}\.(?:png|webp)$")

    async def asset(request: Request) -> Response:
        name = request.path_params["name"]
        if not asset_name_re.match(name):
            return Response("not found", status_code=404)
        hub = api.hub_handle(config)
        if hub is None:
            return Response("hub unreachable", status_code=503)
        for base in (hub.kb_dir, hub.federation_dir):
            if not base.is_dir():
                continue
            # content-addressed name → any hit is THE asset (natural dedupe)
            for path in base.glob(f"**/assets/{name}"):
                media = "image/png" if name.endswith(".png") else "image/webp"
                return Response(
                    path.read_bytes(),
                    media_type=media,
                    headers={"Cache-Control": "private, max-age=31536000, immutable"},
                )
        return Response("not found", status_code=404)

    return [
        Route("/ui", home, methods=["GET"]),
        Route("/ui/login", login_get, methods=["GET"]),
        Route("/ui/login", login_post, methods=["POST"]),
        Route("/ui/docs", docs_page, methods=["GET"]),
        Route("/ui/docs/{doc}", doc_page, methods=["GET"]),
        Route("/ui/docs/{doc}/{section}", section_page, methods=["GET"]),
        Route("/ui/static/style.css", static_css, methods=["GET"]),
        Route("/assets/{name}", asset, methods=["GET"]),
    ]
