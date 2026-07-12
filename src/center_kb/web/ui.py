# src/center_kb/web/ui.py
from __future__ import annotations

import hmac
import html
from importlib import resources
from string import Template
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from center_kb.mcp import ServerConfig
from center_kb.query import get_section, search
from center_kb.web import api
from center_kb.web.auth import COOKIE_NAME
from center_kb.web.mdrender import render as md_render


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
    kind = "remote" if source.startswith("remote:") else source
    return f'<span class="source-badge source-{_e(kind)}">{_e(source)}</span>'


def _result_blocks(results) -> str:
    if not results:
        return (
            '<div class="empty-state"><p>No matching section found.</p>'
            "<p>Try dropping tags or changing keywords.</p></div>"
        )
    blocks = []
    for r in results:
        if r.source.startswith("remote:"):
            # federation carries L1 only — link to the doc's TOC page, not a
            # section content page (which does not exist for remote docs)
            href = f"/ui/docs/{quote(r.doc_id)}"
        else:
            href = f"/ui/docs/{quote(r.doc_id)}/{quote(r.section_id)}"
        blocks.append(
            '<article class="result">'
            '<header class="result-head">'
            f'<a class="cite" href="{href}">{_e(r.citation)}</a>'
            f"{_source_badge(r.source)}"
            f'<span class="score">score {r.score:.2f} · ~{r.tokens} tk</span>'
            "</header>"
            f'<div class="result-body">{md_render(r.content)}</div>'
            "</article>"
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
        # remote docs render too: the doc page shows their L1 TOC + repo note
        name = f'<a href="/ui/docs/{quote(d["id"])}">{title}</a>'
        rev = f'<span class="rev">{_e(d["revision"])}</span>' if d["revision"] else ""
        cards.append(
            '<article class="doc-card">'
            f'<header class="result-head"><span class="doc-name">{name}</span> {rev}'
            f"{_source_badge(d['source'])}</header>"
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
        hub = api.hub_handle(config)
        # hub configured → search published knowledge only (hub + federation);
        # no hub → this server *is* the knowledge source, search it directly.
        include_local = hub is None
        results_html = ""
        if q:
            results = search(
                config.kb_dir,
                q,
                tags=tags or None,
                budget=2000,
                hub=hub,
                include_local=include_local,
            )
            results_html = _result_blocks(results)
        elif tags:
            docs = api.list_docs(config, include_local=include_local)
            results_html = _doc_cards(_match_tags(docs, tags))
        scope = (
            "published knowledge · hub + federation"
            if hub is not None
            else "local knowledge base"
        )
        body = _template("search.html").substitute(
            q=_e(q), tags=_e(raw_tags), scope=_e(scope), results=results_html
        )
        return _page("Search", body)

    async def docs_page(request: Request) -> HTMLResponse:
        # same scoping as home(): a hub configured → published knowledge only
        include_local = api.hub_handle(config) is None
        cards = _doc_cards(api.list_docs(config, include_local=include_local))
        body = _template("docs.html").substitute(cards=cards)
        return _page("Documents", body)

    async def doc_page(request: Request) -> HTMLResponse:
        doc_id = request.path_params["doc"]
        found = api.load_manifest(config, doc_id)
        if found is None:
            return _page("Not found", f"<h1>404</h1><p>Unknown doc '{_e(doc_id)}'.</p>", 404)
        manifest, repo = found
        rows = []
        for s in manifest.sections:
            if repo:
                cell = f"§{_e(s.id)}"  # federation: L1 only, no content page
            else:
                href = f"/ui/docs/{quote(doc_id)}/{quote(s.id)}"
                cell = f'<a href="{href}">§{_e(s.id)}</a>'
            rows.append(
                f"<tr><td>{cell}</td><td>{_e(s.title)}</td>"
                f"<td>{_e(s.summary)}</td><td>{_status_span(s.status)}</td></tr>"
            )
        repo_note = (
            f'<p class="meta">[remote] repo \'{_e(repo)}\' — L1 summaries only; '
            "read full content at the source repo.</p>"
            if repo
            else ""
        )
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
        result = get_section(
            config.kb_dir, doc_id, section_id, level=level, hub=api.hub_handle(config)
        )
        if result is None:
            return _page(
                "Not found",
                f"<h1>404</h1><p>{_e(doc_id)} §{_e(section_id)} not found.</p>",
                404,
            )
        other = "l3" if level == "l2" else "l2"
        toggle_href = f"/ui/docs/{quote(doc_id)}/{quote(section_id)}?level={other}"
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

    return [
        Route("/ui", home, methods=["GET"]),
        Route("/ui/login", login_get, methods=["GET"]),
        Route("/ui/login", login_post, methods=["POST"]),
        Route("/ui/docs", docs_page, methods=["GET"]),
        Route("/ui/docs/{doc}", doc_page, methods=["GET"]),
        Route("/ui/docs/{doc}/{section}", section_page, methods=["GET"]),
        Route("/ui/static/style.css", static_css, methods=["GET"]),
    ]
