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
    return f'<span class="status-{_e(status)}">{_e(status)}</span>'


def _result_blocks(results) -> str:
    if not results:
        return "<p>No matching section found — try dropping tags or changing keywords.</p>"
    blocks = []
    for r in results:
        href = f"/ui/docs/{quote(r.doc_id)}/{quote(r.section_id)}"
        blocks.append(
            '<div class="result">'
            f'<p><a class="cite" href="{href}">[{_e(r.citation)}]</a> '
            f'<span class="score">score={r.score:.2f} · ~{r.tokens}tk · {_e(r.source)}</span></p>'
            f"{md_render(r.content)}"
            "</div>"
        )
    return "\n".join(blocks)


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
        results_html = ""
        if q:
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()] or None
            results = search(
                config.kb_dir, q, tags=tags, budget=2000, hub=api.hub_handle(config)
            )
            results_html = _result_blocks(results)
        body = _template("search.html").substitute(
            q=_e(q), tags=_e(raw_tags), results=results_html
        )
        return _page("Search", body)

    async def docs_page(request: Request) -> HTMLResponse:
        rows = []
        for d in api.list_docs(config):
            href = f"/ui/docs/{quote(d['id'])}"
            link = (
                f'<a href="{href}">{_e(d["id"])}</a>'
                if not d["source"].startswith("remote:")
                else _e(d["id"])
            )
            rows.append(
                f"<tr><td>{link}</td><td>{_e(d['title'])}</td>"
                f"<td>{_e(d['revision'])}</td><td>{_e(', '.join(d['tags']))}</td>"
                f"<td>{_e(d['source'])}</td></tr>"
            )
        body = _template("docs.html").substitute(rows="\n".join(rows))
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
