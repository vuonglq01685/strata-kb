# Web UI + PyPI Packaging + Docker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One process (`python -m aero_kb.mcp --hub . --transport http`) serves MCP + REST JSON + HTML lookup UI; `kb init` scaffolds a ready-to-use KB repo; a single Docker image serves and ingests; release pipeline publishes to PyPI + GHCR.

**Architecture:** A parent Starlette app composes three branches — `/mcp` (existing FastMCP streamable HTTP app, mounted), `/api/*` (REST JSON), `/ui/*` (server-rendered HTML). All three call the existing `query.py`/`models.py` functions. Auth is one middleware accepting bearer header OR cookie. Templates ship inside the wheel via `importlib.resources`.

**Tech Stack:** Python ≥3.11, Starlette + uvicorn (already dependencies — **no new runtime deps**), pytest + Starlette TestClient, hatchling, Docker, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-11-web-ui-packaging-docker-design.md`

## Global Constraints

- **No new runtime dependencies.** Web layer uses only starlette/uvicorn (already in `[project.dependencies]`) + stdlib (`string.Template`, `html`, `hmac`, `http.cookies`, `importlib.resources`).
- **Zero build step for UI** — no Node, no bundler. Templates are files under `src/aero_kb/templates/`, read via `importlib.resources.files("aero_kb")`.
- **Tables verbatim:** markdown table cells render character-for-character (HTML-escaped only). The renderer must never reflow/reformat cell text.
- **All dynamic HTML content is escaped** with `html.escape` before insertion (XSS defense).
- **Token comparison always via `hmac.compare_digest`** — never `==`.
- **Auth-exempt paths, exactly:** `/api/health`, `/ui/login`, and the static asset prefix `/ui/static/` (CSS only — the login page needs it).
- **Circular-import rule:** `aero_kb/web/*` modules MAY import `aero_kb.mcp` at module level (for `ServerConfig`); `aero_kb/mcp.py` imports `aero_kb.web.app` ONLY inside the `create_http_app` function body.
- **CLI flag is `--id`** (not `--doc-id`) for `kb ingest` — templates/docs must use `--id`.
- Commit format `<type>: <description>` (feat/fix/docs/test/chore/ci). No attribution footer.
- Tests: pytest, existing fixtures in `tests/conftest.py` (`fixture_kb` builds a demo KB with doc `demo-doc`, sections `1.1`/`1.2`, revision `Rev 1`, tags `["demo", "airspace"]`, a pipe table `| Code | Meaning |...`). Coverage target ≥80% on new modules.
- Run tests from repo root: `python -m pytest tests/<file> -v` (Windows dev machine; CI is ubuntu).

## File Structure

```
src/aero_kb/
├── web/
│   ├── __init__.py          # empty
│   ├── auth.py              # TokenAuthMiddleware (bearer OR cookie), exempt list
│   ├── mdrender.py          # minimal markdown→HTML (headings, paragraphs, pipe tables)
│   ├── api.py               # /api/* JSON routes
│   ├── ui.py                # /ui/* HTML routes + /ui/static/style.css
│   └── app.py               # create_app(): compose api + ui + mounted MCP app
├── templates/
│   ├── web/                 # base.html, login.html, search.html, docs.html,
│   │                        # doc.html, section.html, style.css
│   └── init/                # index.yaml, federation-README.md, source-gitignore.txt,
│                            # mcp.json, kb-review.yml, docker-compose.yml,
│                            # env.example, QUICKSTART.md
├── initcmd.py               # init_repo(target, force) -> InitReport
├── mcp.py                   # MODIFIED: re-export auth middleware; create_http_app → create_app
└── cli.py                   # MODIFIED: add `kb init`
Dockerfile                   # multi-stage, aero-kb[ingest]
.dockerignore
docker-compose.yml           # dev compose (build: .)
.github/workflows/release.yml
pyproject.toml               # MODIFIED: metadata, version 0.2.0
LICENSE                      # Apache-2.0
README.md                    # MODIFIED: web UI + docker + init section
tests/
├── test_web_mdrender.py
├── test_web_auth.py
├── test_web_api.py
├── test_web_ui.py
├── test_web_app.py
├── test_init.py
└── test_templates.py
```

---

### Task 1: Markdown renderer (`web/mdrender.py`)

**Files:**
- Create: `src/aero_kb/web/__init__.py` (empty file)
- Create: `src/aero_kb/web/mdrender.py`
- Test: `tests/test_web_mdrender.py`

**Interfaces:**
- Consumes: nothing (stdlib only: `html`, `re`).
- Produces: `render(md: str) -> str` — HTML string. Supported subset: `#`–`######` headings, blank-line-separated paragraphs, GitHub pipe tables (first row = header iff second row is a `---` separator). Everything else is treated as paragraph text. All text HTML-escaped.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_mdrender.py
from aero_kb.web.mdrender import render


def test_heading_levels():
    assert render("## 5.3 Restrictive Airspace") == "<h2>5.3 Restrictive Airspace</h2>"
    assert render("### Sub") == "<h3>Sub</h3>"


def test_paragraph_and_escape():
    out = render("Length <1> char & alpha.")
    assert out == "<p>Length &lt;1&gt; char &amp; alpha.</p>"


def test_script_is_escaped_not_executed():
    out = render("<script>alert(1)</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_pipe_table_header_and_cells_verbatim():
    md = "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n| R | Restricted |"
    out = render(md)
    assert "<table>" in out and "</table>" in out
    assert "<th>Code</th><th>Meaning</th>" in out
    assert "<td>P</td><td>Prohibited</td>" in out
    assert "<td>R</td><td>Restricted</td>" in out


def test_table_cell_characters_preserved_exactly():
    # cell content must survive character-for-character (after HTML escaping)
    md = "| Field | Value |\n|---|---|\n| SEC CODE  | 1 alpha <A-Z> |"
    out = render(md)
    assert "<td>SEC CODE</td>" in out          # strip() around cells is allowed
    assert "<td>1 alpha &lt;A-Z&gt;</td>" in out


def test_table_without_separator_has_no_header():
    md = "| a | b |\n| c | d |"
    out = render(md)
    assert "<th>" not in out
    assert "<td>a</td><td>b</td>" in out


def test_mixed_document():
    md = "## 1.1 Airspace\n\nIntro text.\n\n| K | V |\n|---|---|\n| P | Prohibited |\n\nAfter table."
    out = render(md)
    assert out.index("<h2>") < out.index("<p>Intro text.</p>") < out.index("<table>")
    assert "<p>After table.</p>" in out


def test_multiline_paragraph_joined():
    assert render("line one\nline two") == "<p>line one line two</p>"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_mdrender.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.web'`

- [ ] **Step 3: Implement**

Create empty `src/aero_kb/web/__init__.py`, then:

```python
# src/aero_kb/web/mdrender.py
"""Minimal markdown→HTML for the exact subset used in L2/L3 files.

Supported: #..###### headings, blank-line paragraphs, GitHub pipe tables.
Table cells are escaped but never reworded/reflowed — the project's
inviolable rule is that tables render character-for-character.
"""
from __future__ import annotations

import html
import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _is_separator(row: str) -> bool:
    return "-" in row and bool(_SEPARATOR_RE.match(row))


def _render_table(rows: list[str]) -> str:
    has_header = len(rows) > 1 and _is_separator(rows[1])
    out = ["<table>"]
    for i, row in enumerate(rows):
        if has_header and i == 1:
            continue
        tag = "th" if (has_header and i == 0) else "td"
        cells = "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in _cells(row))
        out.append(f"<tr>{cells}</tr>")
    out.append("</table>")
    return "".join(out)


def render(md: str) -> str:
    blocks: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        if para:
            blocks.append(f"<p>{html.escape(' '.join(para))}</p>")
            para.clear()

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|"):
            flush_para()
            table: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                table.append(lines[i])
                i += 1
            blocks.append(_render_table(table))
            continue
        m = _HEADING_RE.match(line)
        if m:
            flush_para()
            level = len(m.group(1))
            blocks.append(f"<h{level}>{html.escape(m.group(2).strip())}</h{level}>")
        elif not line.strip():
            flush_para()
        else:
            para.append(line.strip())
        i += 1
    flush_para()
    return "\n".join(blocks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_mdrender.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/web/__init__.py src/aero_kb/web/mdrender.py tests/test_web_mdrender.py
git commit -m "feat: minimal markdown renderer for web UI (tables verbatim)"
```

---

### Task 2: Auth middleware with cookie support (`web/auth.py`)

**Files:**
- Create: `src/aero_kb/web/auth.py`
- Modify: `src/aero_kb/mcp.py` — delete the `BearerAuthMiddleware` class body (lines 87–113), replace with a re-export.
- Test: `tests/test_web_auth.py`

**Interfaces:**
- Consumes: stdlib (`hmac`, `http.cookies`).
- Produces:
  - `TokenAuthMiddleware(app, token: str)` — ASGI middleware. Accepts `Authorization: Bearer <token>` header OR cookie `aero_kb_token=<token>`. Unauthorized: paths starting `/ui` or exactly `/` → 302 redirect to `/ui/login`; anything else → 401 JSON `{"error": "unauthorized"}`.
  - Constants: `COOKIE_NAME = "aero_kb_token"`, `EXEMPT_PATHS = ("/api/health", "/ui/login")`, `EXEMPT_PREFIXES = ("/ui/static/",)`.
  - `aero_kb.mcp.BearerAuthMiddleware` remains importable (alias) so existing tests keep passing.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_auth.py
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from aero_kb.web.auth import COOKIE_NAME, TokenAuthMiddleware


def _app():
    async def ok(request):
        return PlainTextResponse("ok")

    routes = [
        Route(path, ok, methods=["GET"])
        for path in ["/", "/mcp", "/api/docs", "/api/health", "/ui", "/ui/login", "/ui/static/style.css"]
    ]
    return Starlette(routes=routes)


def _client():
    return TestClient(TokenAuthMiddleware(_app(), "secret-token"))


def test_api_without_token_401_json():
    resp = _client().get("/api/docs")
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


def test_bearer_header_passes():
    resp = _client().get("/api/docs", headers={"Authorization": "Bearer secret-token"})
    assert resp.status_code == 200


def test_cookie_passes():
    c = _client()
    c.cookies.set(COOKIE_NAME, "secret-token")
    assert c.get("/api/docs").status_code == 200


def test_wrong_cookie_401():
    c = _client()
    c.cookies.set(COOKIE_NAME, "wrong")
    assert c.get("/api/docs").status_code == 401


def test_ui_without_token_redirects_to_login():
    resp = _client().get("/ui", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ui/login"


def test_root_without_token_redirects_to_login():
    resp = _client().get("/", follow_redirects=False)
    assert resp.status_code == 302


def test_exempt_paths_pass_without_token():
    c = _client()
    assert c.get("/api/health").status_code == 200
    assert c.get("/ui/login").status_code == 200
    assert c.get("/ui/static/style.css").status_code == 200


def test_mcp_without_token_401():
    assert _client().get("/mcp").status_code == 401


def test_malformed_cookie_header_is_401_not_crash():
    resp = _client().get("/api/docs", headers={"Cookie": ";;=;;garbage"})
    assert resp.status_code == 401


def test_mcp_module_still_exports_bearer_alias():
    from aero_kb.mcp import BearerAuthMiddleware

    assert BearerAuthMiddleware is TokenAuthMiddleware
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.web.auth'`

- [ ] **Step 3: Implement `web/auth.py`**

```python
# src/aero_kb/web/auth.py
from __future__ import annotations

import hmac
from http.cookies import CookieError, SimpleCookie

COOKIE_NAME = "aero_kb_token"
EXEMPT_PATHS = ("/api/health", "/ui/login")
EXEMPT_PREFIXES = ("/ui/static/",)


class TokenAuthMiddleware:
    """Accept 'Authorization: Bearer <token>' OR the aero_kb_token cookie.

    Unauthorized: browser-facing paths (/, /ui*) get a 302 to /ui/login;
    everything else (API, MCP) gets 401 JSON.
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    def _authorized(self, scope) -> bool:
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if hmac.compare_digest(auth, f"Bearer {self.token}"):
            return True
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("cookie", ""))
        except CookieError:
            return False
        morsel = cookie.get(COOKIE_NAME)
        return morsel is not None and hmac.compare_digest(morsel.value, self.token)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if (
            path in EXEMPT_PATHS
            or any(path.startswith(p) for p in EXEMPT_PREFIXES)
            or self._authorized(scope)
        ):
            await self.app(scope, receive, send)
            return
        if path == "/" or path.startswith("/ui"):
            await send(
                {
                    "type": "http.response.start",
                    "status": 302,
                    "headers": [(b"location", b"/ui/login")],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b'{"error": "unauthorized"}'}
        )
```

- [ ] **Step 4: Rewire `mcp.py`**

In `src/aero_kb/mcp.py`: delete the whole `BearerAuthMiddleware` class (the block starting `class BearerAuthMiddleware:` through its final `await self.app(scope, receive, send)`) and the now-unused `import hmac` at the top. Add near the top imports:

```python
from aero_kb.web.auth import TokenAuthMiddleware as BearerAuthMiddleware  # noqa: F401 — re-export
```

(The `# noqa: F401` keeps ruff from flagging the deliberate re-export.)
`create_http_app` keeps working unchanged for now (it still wraps with `BearerAuthMiddleware`, which is now the new class).

- [ ] **Step 5: Run new tests + regression**

Run: `python -m pytest tests/test_web_auth.py tests/test_mcp_http.py -v`
Expected: all PASS (old bearer tests exercise the new middleware via the alias; note `test_missing_token_401` in test_mcp_http.py hits `/mcp` → still 401).

- [ ] **Step 6: Commit**

```bash
git add src/aero_kb/web/auth.py src/aero_kb/mcp.py tests/test_web_auth.py
git commit -m "feat: token auth middleware with cookie support for web UI"
```

---

### Task 3: REST API routes (`web/api.py`)

**Files:**
- Create: `src/aero_kb/web/api.py`
- Test: `tests/test_web_api.py`

**Interfaces:**
- Consumes: `aero_kb.mcp.ServerConfig` (fields: `kb_dir: Path`, `hub: str | None`); `aero_kb.query.search(kb_dir, text, tags=None, budget=2000, hub=None) -> list[QueryResult]`; `aero_kb.query.get_section(kb_dir, doc_id, section_id, level="l2", hub=None) -> QueryResult | None` (`QueryResult` fields: `doc_id, section_id, title, score, citation, content, tokens, source`); `aero_kb.models.load_yaml_model / KBIndex / Manifest`; `aero_kb.hub.resolve_hub(hub) -> HubHandle | None` (`HubHandle.kb_dir`, `.federation_dir`); `aero_kb.federation.load_federation(federation_dir)` → repos with `.meta.repo_id`, `.index.docs`, `.manifests: dict[str, Manifest]`.
- Produces: `build_routes(config: ServerConfig) -> list[Route]` with:
  - `GET /api/health` → `{"status": "ok", "hub_configured": bool}`
  - `GET /api/docs` → `{"docs": [{id,title,revision,tags,summary,source}]}` (source: `"local" | "hub" | "remote:<rid>"`; hub/remote deduped against local ids)
  - `GET /api/docs/{doc}` → `{"id","title","revision","repo","sections":[{id,title,summary,status}]}` (repo `""` for local/hub, `<rid>` for federation) or 404
  - `GET /api/docs/{doc}/sections/{section}?level=l2|l3` → `{"doc_id","section_id","title","citation","tokens","level","content","source"}` or 400/404
  - `GET /api/search?q=&tags=&budget=` → `{"query", "results":[{doc_id,section_id,title,score,citation,tokens,content,source}]}` or 400
  - Errors always `{"error": "<slug>", "detail": "<human text>"}`.
  - Module helper reused by Task 4: `hub_handle(config) -> HubHandle | None` and `MAX_BUDGET = 20000`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_api.py
from starlette.applications import Starlette
from starlette.testclient import TestClient

from aero_kb.mcp import ServerConfig
from aero_kb.web import api


def _client(fixture_kb, hub=None):
    config = ServerConfig(kb_dir=fixture_kb, hub=hub)
    return TestClient(Starlette(routes=api.build_routes(config)))


def test_health_no_auth_needed_shape(fixture_kb):
    resp = _client(fixture_kb).get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "hub_configured": False}


def test_docs_lists_local_index(fixture_kb):
    data = _client(fixture_kb).get("/api/docs").json()
    assert data["docs"][0]["id"] == "demo-doc"
    assert data["docs"][0]["source"] == "local"
    assert data["docs"][0]["tags"] == ["demo", "airspace"]


def test_doc_detail_returns_manifest_sections(fixture_kb):
    data = _client(fixture_kb).get("/api/docs/demo-doc").json()
    assert data["id"] == "demo-doc"
    assert data["revision"] == "Rev 1"
    ids = [s["id"] for s in data["sections"]]
    assert ids == ["1.1", "1.2"]
    assert data["sections"][0]["status"] == "summarized"


def test_doc_detail_404_names_known_docs(fixture_kb):
    resp = _client(fixture_kb).get("/api/docs/nope")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "doc_not_found"
    assert "demo-doc" in body["detail"]


def test_section_l2_and_l3(fixture_kb):
    c = _client(fixture_kb)
    l2 = c.get("/api/docs/demo-doc/sections/1.1").json()
    assert l2["level"] == "l2"
    assert l2["citation"] == "demo-doc §1.1 (Rev 1)"
    assert "Condensed" in l2["content"]
    l3 = c.get("/api/docs/demo-doc/sections/1.1", params={"level": "l3"}).json()
    assert "Full raw text" in l3["content"]


def test_section_bad_level_400(fixture_kb):
    resp = _client(fixture_kb).get("/api/docs/demo-doc/sections/1.1", params={"level": "l9"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_level"


def test_section_404(fixture_kb):
    resp = _client(fixture_kb).get("/api/docs/demo-doc/sections/9.9")
    assert resp.status_code == 404
    assert resp.json()["error"] == "section_not_found"


def test_search_returns_results_with_citation(fixture_kb):
    data = _client(fixture_kb).get("/api/search", params={"q": "airspace designation"}).json()
    assert data["query"] == "airspace designation"
    assert data["results"][0]["doc_id"] == "demo-doc"
    assert data["results"][0]["citation"].startswith("demo-doc §")


def test_search_missing_q_400(fixture_kb):
    resp = _client(fixture_kb).get("/api/search")
    assert resp.status_code == 400
    assert resp.json()["error"] == "missing_query"


def test_search_bad_budget_400(fixture_kb):
    resp = _client(fixture_kb).get("/api/search", params={"q": "x", "budget": "lots"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_budget"


def test_docs_includes_hub_and_federation(fixture_kb, hub_worktree):
    data = _client(fixture_kb, hub=str(hub_worktree)).get("/api/docs").json()
    by_id = {d["id"]: d for d in data["docs"]}
    assert by_id["demo-doc"]["source"] == "local"
    assert by_id["arinc-424"]["source"] == "hub"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'api'`

- [ ] **Step 3: Implement `web/api.py`**

```python
# src/aero_kb/web/api.py
from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from aero_kb import models
from aero_kb.mcp import ServerConfig
from aero_kb.query import get_section, search

MAX_BUDGET = 20000


def hub_handle(config: ServerConfig):
    """'' / None → None; otherwise resolve (None again if unreachable)."""
    if not config.hub:
        return None
    from aero_kb.hub import resolve_hub

    return resolve_hub(config.hub)


def _error(status: int, error: str, detail: str = "") -> JSONResponse:
    return JSONResponse({"error": error, "detail": detail}, status_code=status)


def _index_docs(kb_dir: Path) -> list[models.IndexEntry]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return []
    return models.load_yaml_model(index_path, models.KBIndex).docs


def known_doc_ids(config: ServerConfig) -> list[str]:
    ids = [d.id for d in _index_docs(config.kb_dir)]
    hub = hub_handle(config)
    if hub is not None:
        ids += [d.id for d in _index_docs(hub.kb_dir) if d.id not in set(ids)]
    return ids


def list_docs(config: ServerConfig) -> list[dict]:
    """L0 across local + hub + federation, local wins on id collision."""
    out = [{**d.model_dump(), "source": "local"} for d in _index_docs(config.kb_dir)]
    hub = hub_handle(config)
    if hub is None:
        return out
    seen = {d["id"] for d in out}
    for d in _index_docs(hub.kb_dir):
        if d.id not in seen:
            out.append({**d.model_dump(), "source": "hub"})
            seen.add(d.id)
    from aero_kb.federation import load_federation

    for repo in load_federation(hub.federation_dir):
        rid = repo.meta.repo_id
        for d in repo.index.docs:
            out.append({**d.model_dump(), "source": f"remote:{rid}"})
    return out


def load_manifest(config: ServerConfig, doc_id: str) -> tuple[models.Manifest, str] | None:
    """Find a manifest for doc_id: local → hub → federation. Returns (manifest, repo)."""
    candidates: list[Path] = [config.kb_dir]
    hub = hub_handle(config)
    if hub is not None:
        candidates.append(hub.kb_dir)
    for base in candidates:
        mp = base / doc_id / "_manifest.yaml"
        if mp.exists():
            return models.load_yaml_model(mp, models.Manifest), ""
    if hub is not None:
        from aero_kb.federation import load_federation

        for repo in load_federation(hub.federation_dir):
            m = repo.manifests.get(doc_id)
            if m is not None:
                return m, repo.meta.repo_id
    return None


def build_routes(config: ServerConfig) -> list[Route]:
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "hub_configured": bool(config.hub)})

    async def docs(request: Request) -> JSONResponse:
        return JSONResponse({"docs": list_docs(config)})

    async def doc_detail(request: Request) -> JSONResponse:
        doc_id = request.path_params["doc"]
        found = load_manifest(config, doc_id)
        if found is None:
            known = ", ".join(known_doc_ids(config))
            return _error(404, "doc_not_found", f"unknown doc '{doc_id}'; known docs: {known}")
        manifest, repo = found
        return JSONResponse(
            {
                "id": manifest.id,
                "title": manifest.title,
                "revision": manifest.revision,
                "repo": repo,
                "sections": [
                    {"id": s.id, "title": s.title, "summary": s.summary, "status": s.status}
                    for s in manifest.sections
                ],
            }
        )

    async def section(request: Request) -> JSONResponse:
        doc_id = request.path_params["doc"]
        section_id = request.path_params["section"]
        level = request.query_params.get("level", "l2")
        if level not in ("l2", "l3"):
            return _error(400, "bad_level", f"level '{level}' is invalid — use 'l2' or 'l3'")
        result = get_section(config.kb_dir, doc_id, section_id, level=level, hub=hub_handle(config))
        if result is None:
            known = ", ".join(known_doc_ids(config))
            return _error(
                404, "section_not_found", f"{doc_id} §{section_id} not found; known docs: {known}"
            )
        return JSONResponse(
            {
                "doc_id": result.doc_id,
                "section_id": result.section_id,
                "title": result.title,
                "citation": result.citation,
                "tokens": result.tokens,
                "level": level,
                "content": result.content,
                "source": result.source,
            }
        )

    async def api_search(request: Request) -> JSONResponse:
        q = request.query_params.get("q", "").strip()
        if not q:
            return _error(400, "missing_query", "query parameter 'q' is required")
        raw_tags = request.query_params.get("tags", "")
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()] or None
        try:
            budget = int(request.query_params.get("budget", "2000"))
        except ValueError:
            return _error(400, "bad_budget", "'budget' must be an integer")
        budget = max(1, min(budget, MAX_BUDGET))
        results = search(config.kb_dir, q, tags=tags, budget=budget, hub=hub_handle(config))
        return JSONResponse(
            {
                "query": q,
                "results": [
                    {
                        "doc_id": r.doc_id,
                        "section_id": r.section_id,
                        "title": r.title,
                        "score": r.score,
                        "citation": r.citation,
                        "tokens": r.tokens,
                        "content": r.content,
                        "source": r.source,
                    }
                    for r in results
                ],
            }
        )

    return [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/docs", docs, methods=["GET"]),
        Route("/api/docs/{doc}", doc_detail, methods=["GET"]),
        Route("/api/docs/{doc}/sections/{section}", section, methods=["GET"]),
        Route("/api/search", api_search, methods=["GET"]),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_api.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/web/api.py tests/test_web_api.py
git commit -m "feat: REST JSON routes /api for docs, sections, search, health"
```

---

### Task 4: HTML UI — templates + routes (`web/ui.py`)

**Files:**
- Create: `src/aero_kb/templates/web/base.html`, `login.html`, `search.html`, `docs.html`, `doc.html`, `section.html`, `style.css`
- Create: `src/aero_kb/web/ui.py`
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `api.hub_handle(config)`, `api.list_docs(config)`, `api.load_manifest(config, doc_id)` (Task 3); `mdrender.render` (Task 1); `auth.COOKIE_NAME` (Task 2); `aero_kb.query.search/get_section`; `ServerConfig`.
- Produces: `build_routes(config: ServerConfig, token: str) -> list[Route]` with GET `/ui`, `/ui/docs`, `/ui/docs/{doc}`, `/ui/docs/{doc}/{section}`, `/ui/static/style.css`, GET+POST `/ui/login`. Templates use `string.Template` (`$placeholder`) — NOT `str.format` (CSS braces would break it).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_ui.py
from starlette.applications import Starlette
from starlette.testclient import TestClient

from aero_kb.mcp import ServerConfig
from aero_kb.web import ui
from aero_kb.web.auth import COOKIE_NAME

TOKEN = "secret-token"


def _client(fixture_kb):
    config = ServerConfig(kb_dir=fixture_kb, hub=None)
    return TestClient(Starlette(routes=ui.build_routes(config, TOKEN)))


def test_login_page_renders(fixture_kb):
    resp = _client(fixture_kb).get("/ui/login")
    assert resp.status_code == 200
    assert 'name="token"' in resp.text


def test_login_correct_token_sets_cookie_and_redirects(fixture_kb):
    resp = _client(fixture_kb).post(
        "/ui/login", data={"token": TOKEN}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui"
    assert COOKIE_NAME in resp.headers.get("set-cookie", "")
    assert "httponly" in resp.headers["set-cookie"].lower()


def test_login_wrong_token_shows_error_no_cookie(fixture_kb):
    resp = _client(fixture_kb).post("/ui/login", data={"token": "wrong"})
    assert resp.status_code == 200
    assert "set-cookie" not in resp.headers
    assert "Invalid token" in resp.text


def test_home_shows_search_form(fixture_kb):
    resp = _client(fixture_kb).get("/ui")
    assert resp.status_code == 200
    assert 'name="q"' in resp.text


def test_home_with_query_renders_results(fixture_kb):
    resp = _client(fixture_kb).get("/ui", params={"q": "airspace designation"})
    assert "demo-doc" in resp.text
    assert "§1.1" in resp.text


def test_docs_page_lists_docs(fixture_kb):
    resp = _client(fixture_kb).get("/ui/docs")
    assert "demo-doc" in resp.text
    assert "Demo Document" in resp.text


def test_doc_page_lists_sections_with_status(fixture_kb):
    resp = _client(fixture_kb).get("/ui/docs/demo-doc")
    assert "Airspace Records" in resp.text
    assert "summarized" in resp.text


def test_doc_page_404(fixture_kb):
    assert _client(fixture_kb).get("/ui/docs/nope").status_code == 404


def test_section_page_renders_l2_with_table_and_citation(fixture_kb):
    resp = _client(fixture_kb).get("/ui/docs/demo-doc/1.1")
    assert resp.status_code == 200
    assert "demo-doc §1.1 (Rev 1)" in resp.text
    assert "<td>Prohibited</td>" in resp.text          # table rendered verbatim
    assert 'level=l3' in resp.text                     # toggle link to L3


def test_section_page_l3(fixture_kb):
    resp = _client(fixture_kb).get("/ui/docs/demo-doc/1.1", params={"level": "l3"})
    assert "Full raw text" in resp.text


def test_section_page_404(fixture_kb):
    assert _client(fixture_kb).get("/ui/docs/demo-doc/9.9").status_code == 404


def test_static_css(fixture_kb):
    resp = _client(fixture_kb).get("/ui/static/style.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_ui.py -v`
Expected: FAIL — `ImportError: cannot import name 'ui'`

- [ ] **Step 3: Create the templates**

`src/aero_kb/templates/web/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title — AERO-KB</title>
<link rel="stylesheet" href="/ui/static/style.css">
</head>
<body>
<header class="topbar">
  <a class="brand" href="/ui">AERO-KB</a>
  <nav>
    <a href="/ui">Search</a>
    <a href="/ui/docs">Browse</a>
  </nav>
</header>
<main>
$body
</main>
<footer class="foot">Knowledge Base as Code — L0→L3</footer>
</body>
</html>
```

`src/aero_kb/templates/web/login.html`:

```html
<section class="login">
  <h1>Sign in</h1>
  <p>Paste the access token (<code>AERO_KB_HTTP_TOKEN</code>) to continue.</p>
  $error
  <form method="post" action="/ui/login">
    <input type="password" name="token" placeholder="Access token" autofocus required>
    <button type="submit">Sign in</button>
  </form>
</section>
```

`src/aero_kb/templates/web/search.html`:

```html
<section class="search">
  <form method="get" action="/ui">
    <input type="search" name="q" value="$q" placeholder="Search the knowledge base…" autofocus>
    <input type="text" name="tags" value="$tags" placeholder="tags (comma-separated)">
    <button type="submit">Search</button>
  </form>
</section>
$results
```

`src/aero_kb/templates/web/docs.html`:

```html
<h1>Documents</h1>
<table class="doclist">
  <tr><th>ID</th><th>Title</th><th>Revision</th><th>Tags</th><th>Source</th></tr>
$rows
</table>
```

`src/aero_kb/templates/web/doc.html`:

```html
<p class="crumbs"><a href="/ui/docs">Documents</a> / $doc_id</p>
<h1>$title <span class="rev">$revision</span></h1>
$repo_note
<table class="sections">
  <tr><th>Section</th><th>Title</th><th>Summary</th><th>Status</th></tr>
$rows
</table>
```

`src/aero_kb/templates/web/section.html`:

```html
<p class="crumbs"><a href="/ui/docs">Documents</a> / <a href="/ui/docs/$doc_id">$doc_id</a> / §$section_id</p>
<h1>$title</h1>
<p class="meta">
  <code id="citation">$citation</code>
  <button class="copy" onclick="navigator.clipboard.writeText(document.getElementById('citation').textContent)">Copy citation</button>
  · ~$tokens tokens · level <strong>$level</strong> · $toggle
</p>
<article class="content">
$content
</article>
```

`src/aero_kb/templates/web/style.css`:

```css
:root {
  --bg: #ffffff; --text: #1a1d21; --muted: #5c6570;
  --accent: #0b57d0; --line: #e2e5e9; --surface: #f6f7f9;
}
* { box-sizing: border-box; }
body {
  margin: 0; color: var(--text); background: var(--bg);
  font: 16px/1.6 system-ui, "Segoe UI", sans-serif;
}
.topbar {
  display: flex; gap: 1.5rem; align-items: baseline;
  padding: 0.8rem 1.5rem; border-bottom: 1px solid var(--line);
}
.brand { font-weight: 700; color: var(--text); text-decoration: none; }
.topbar nav a { color: var(--muted); text-decoration: none; margin-right: 1rem; }
.topbar nav a:hover { color: var(--accent); }
main { max-width: 60rem; margin: 0 auto; padding: 1.5rem; }
.foot { color: var(--muted); text-align: center; padding: 2rem 0; font-size: 0.85rem; }
h1 .rev { color: var(--muted); font-size: 0.6em; font-weight: 400; }
.crumbs, .meta { color: var(--muted); font-size: 0.9rem; }
.search form { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; }
.search input[type=search] { flex: 2; }
.search input[type=text] { flex: 1; }
input, button {
  padding: 0.55rem 0.8rem; font: inherit;
  border: 1px solid var(--line); border-radius: 6px;
}
button { background: var(--accent); border-color: var(--accent); color: #fff; cursor: pointer; }
button.copy { background: var(--surface); color: var(--text); border-color: var(--line); padding: 0.15rem 0.5rem; font-size: 0.8rem; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { border: 1px solid var(--line); padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }
th { background: var(--surface); }
.result { border: 1px solid var(--line); border-radius: 8px; padding: 1rem 1.25rem; margin: 1rem 0; }
.result .cite { font-weight: 600; }
.result .score { color: var(--muted); font-size: 0.85rem; }
.status-pending { color: #b45309; }
.status-summarized { color: #0b57d0; }
.status-reviewed { color: #15803d; }
.login { max-width: 24rem; margin: 4rem auto; }
.login form { display: grid; gap: 0.75rem; }
.error { color: #b91c1c; }
article.content { overflow-x: auto; }
```

- [ ] **Step 4: Implement `web/ui.py`**

```python
# src/aero_kb/web/ui.py
from __future__ import annotations

import hmac
import html
from importlib import resources
from string import Template
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from aero_kb.mcp import ServerConfig
from aero_kb.query import get_section, search
from aero_kb.web import api
from aero_kb.web.auth import COOKIE_NAME
from aero_kb.web.mdrender import render as md_render


def _template(name: str) -> Template:
    text = (
        resources.files("aero_kb")
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
            resources.files("aero_kb")
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_ui.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/aero_kb/templates/web src/aero_kb/web/ui.py tests/test_web_ui.py
git commit -m "feat: server-rendered HTML UI — login, search, browse, section view"
```

---

### Task 5: Compose the parent app (`web/app.py`) + rewire `mcp.py`

**Files:**
- Create: `src/aero_kb/web/app.py`
- Modify: `src/aero_kb/mcp.py` — `create_http_app` body
- Test: `tests/test_web_app.py`

**Interfaces:**
- Consumes: `api.build_routes(config)` (Task 3), `ui.build_routes(config, token)` (Task 4), `TokenAuthMiddleware` (Task 2), `aero_kb.mcp.create_server(config) -> FastMCP`. FastMCP v1: `server.streamable_http_app()` returns a Starlette app whose internal route is `/mcp`; `server.session_manager` is available **after** `streamable_http_app()` has been called and exposes `.run()` (async context manager) that MUST be entered for the app's lifetime.
- Produces: `create_app(config: ServerConfig, token: str, mcp_server=None)` → auth-wrapped ASGI app. With `mcp_server=None` (tests) no `/mcp` branch and no lifespan requirement. `aero_kb.mcp.create_http_app(config, token)` now returns `create_app(config, token, mcp_server=create_server(config))`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_app.py
from starlette.testclient import TestClient

from aero_kb.mcp import ServerConfig, create_http_app
from aero_kb.web.app import create_app

TOKEN = "secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_root_redirects_to_ui(fixture_kb):
    client = TestClient(create_app(ServerConfig(kb_dir=fixture_kb), TOKEN))
    resp = client.get("/", headers=AUTH, follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/ui"


def test_api_and_ui_reachable_through_one_app(fixture_kb):
    client = TestClient(create_app(ServerConfig(kb_dir=fixture_kb), TOKEN))
    assert client.get("/api/docs", headers=AUTH).status_code == 200
    assert client.get("/ui", headers=AUTH).status_code == 200


def test_unauthenticated_api_401_ui_redirect(fixture_kb):
    client = TestClient(create_app(ServerConfig(kb_dir=fixture_kb), TOKEN))
    assert client.get("/api/docs").status_code == 401
    resp = client.get("/ui", follow_redirects=False)
    assert resp.status_code == 302


def test_full_http_app_serves_mcp_and_api_together(fixture_kb):
    """create_http_app: MCP handshake still works AND /api works on the same app."""
    app = create_http_app(ServerConfig(kb_dir=fixture_kb), TOKEN)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    headers = {
        **AUTH,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    with TestClient(app, base_url="http://localhost:8321") as client:
        resp = client.post("/mcp", json=payload, headers=headers)
        assert resp.status_code == 200
        assert "serverInfo" in resp.text
        assert client.get("/api/health").status_code == 200
        assert client.get("/ui", headers=AUTH).status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.web.app'`

- [ ] **Step 3: Implement `web/app.py`**

```python
# src/aero_kb/web/app.py
from __future__ import annotations

import contextlib

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route

from aero_kb.mcp import ServerConfig
from aero_kb.web import api, ui
from aero_kb.web.auth import TokenAuthMiddleware


def create_app(config: ServerConfig, token: str, mcp_server=None):
    """One ASGI app: / → /ui redirect, /api/*, /ui/*, and /mcp (mounted FastMCP).

    mcp_server=None (unit tests): no /mcp branch, no lifespan requirement.
    """

    async def root(request: Request) -> RedirectResponse:
        return RedirectResponse("/ui")

    routes: list = [Route("/", root, methods=["GET"])]
    routes += api.build_routes(config)
    routes += ui.build_routes(config, token)

    lifespan = None
    if mcp_server is not None:
        mcp_app = mcp_server.streamable_http_app()

        @contextlib.asynccontextmanager
        async def lifespan(app):
            # FastMCP's session manager must run for the app's lifetime,
            # but Starlette does not run a mounted sub-app's lifespan —
            # so the parent enters it explicitly.
            async with mcp_server.session_manager.run():
                yield

        # Mounted last: /mcp requests fall through to the FastMCP app,
        # which serves them at its internal /mcp path.
        routes.append(Mount("/", app=mcp_app))

    app = Starlette(routes=routes, lifespan=lifespan)
    return TokenAuthMiddleware(app, token)
```

- [ ] **Step 4: Rewire `create_http_app` in `mcp.py`**

Replace the existing `create_http_app` function body:

```python
def create_http_app(config: ServerConfig, token: str):
    """One ASGI app: MCP (streamable HTTP) + REST /api + HTML /ui, token-guarded."""
    from aero_kb.web.app import create_app

    return create_app(config, token, mcp_server=create_server(config))
```

(Import inside the function — the circular-import rule from Global Constraints.)

- [ ] **Step 5: Run new tests + full regression**

Run: `python -m pytest tests/test_web_app.py tests/test_mcp_http.py tests/test_mcp.py -v`
Expected: all PASS (the existing handshake test posts `/mcp` through the new parent app).
Then full suite: `python -m pytest` — expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aero_kb/web/app.py src/aero_kb/mcp.py tests/test_web_app.py
git commit -m "feat: compose MCP + REST + UI into one HTTP app"
```

---

### Task 6: `kb init` scaffold

**Files:**
- Create: `src/aero_kb/templates/init/index.yaml`, `federation-README.md`, `source-gitignore.txt`, `mcp.json`, `kb-review.yml`, `docker-compose.yml`, `env.example`, `QUICKSTART.md`
- Create: `src/aero_kb/initcmd.py`
- Modify: `src/aero_kb/cli.py` — add `init` command
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `importlib.resources`; typer app in `cli.py`.
- Produces: `init_repo(target: Path, force: bool = False) -> InitReport` where `InitReport` is a dataclass with `created: list[str]`, `skipped: list[str]` (relative POSIX paths). CLI: `kb init [PATH] [--force]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_init.py
from pathlib import Path

from typer.testing import CliRunner

from aero_kb.cli import app
from aero_kb.initcmd import EXPECTED_FILES, init_repo

runner = CliRunner()


def test_init_creates_all_files(tmp_path: Path):
    report = init_repo(tmp_path)
    assert sorted(report.created) == sorted(EXPECTED_FILES)
    assert report.skipped == []
    for rel in EXPECTED_FILES:
        assert (tmp_path / rel).is_file(), rel


def test_init_is_idempotent_never_overwrites(tmp_path: Path):
    init_repo(tmp_path)
    marker = tmp_path / ".kb" / "index.yaml"
    marker.write_text("docs: [{id: keep-me, title: X}]\n", encoding="utf-8")
    report = init_repo(tmp_path)
    assert report.created == []
    assert sorted(report.skipped) == sorted(EXPECTED_FILES)
    assert "keep-me" in marker.read_text(encoding="utf-8")


def test_init_force_overwrites(tmp_path: Path):
    init_repo(tmp_path)
    marker = tmp_path / ".kb" / "index.yaml"
    marker.write_text("docs: [{id: gone, title: X}]\n", encoding="utf-8")
    report = init_repo(tmp_path, force=True)
    assert sorted(report.created) == sorted(EXPECTED_FILES)
    assert "gone" not in marker.read_text(encoding="utf-8")


def test_kb_doctor_passes_on_fresh_skeleton(tmp_path: Path):
    init_repo(tmp_path)
    result = runner.invoke(app, ["doctor", "--kb-dir", str(tmp_path / ".kb")])
    assert result.exit_code == 0
    assert "kb doctor: OK" in result.output


def test_cli_init_reports_and_next_steps(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    assert "created" in result.output
    assert "kb ingest" in result.output
    result2 = runner.invoke(app, ["init", str(tmp_path)])
    assert result2.exit_code == 0
    assert "skipped" in result2.output


def test_quickstart_uses_correct_ingest_flag(tmp_path: Path):
    init_repo(tmp_path)
    text = (tmp_path / "QUICKSTART.md").read_text(encoding="utf-8")
    assert "--id" in text
    assert "--doc-id" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_init.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.initcmd'`

- [ ] **Step 3: Create the init templates**

`src/aero_kb/templates/init/index.yaml`:

```yaml
docs: []
```

`src/aero_kb/templates/init/federation-README.md`:

```markdown
# federation/

L0+L1 snapshots published by child repos.

Each child repo runs `kb publish --hub <this-repo-url-or-path>`, which writes
`federation/<repo-id>/` (index + manifests). The hub serves these read-only
through `kb query --hub`, the MCP tools, and the web UI. Content (L2/L3) stays
in the child repo — the hub only holds the child's catalog and summaries.
```

`src/aero_kb/templates/init/source-gitignore.txt` (written to `source/.gitignore`):

```
# Copyrighted source documents — never commit them.
*.pdf
```

`src/aero_kb/templates/init/mcp.json` (written to `.mcp.json`):

```json
{
  "mcpServers": {
    "aero-kb": {
      "command": "python",
      "args": ["-m", "aero_kb.mcp", "--kb", ".kb/"]
    }
  }
}
```

`src/aero_kb/templates/init/kb-review.yml` (written to `.github/workflows/kb-review.yml`) — copy the current file `D:\Projects\AERO-KB\.github\workflows\kb-review.yml` **verbatim** (it is the reference implementation of the auto-review flow; do not retype it — copy it):

```bash
cp .github/workflows/kb-review.yml src/aero_kb/templates/init/kb-review.yml
```

`src/aero_kb/templates/init/docker-compose.yml`:

```yaml
services:
  hub:
    image: ghcr.io/vuonglq01685/aero-kb:latest
    ports: ["8321:8321"]
    env_file: .env
    volumes:
      - ./:/data
      - kb-model-cache:/home/app/.cache
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8321/api/health')"]
      interval: 30s
volumes:
  kb-model-cache:
```

`src/aero_kb/templates/init/env.example` (written to `.env.example`):

```
AERO_KB_HTTP_TOKEN=change-me
```

`src/aero_kb/templates/init/QUICKSTART.md`:

```markdown
# AERO-KB Quickstart

Five steps from empty repo to a searchable knowledge base.

1. **Configure the token** — `cp .env.example .env`, then edit
   `AERO_KB_HTTP_TOKEN` (any long random string).
2. **Ingest the first document** — put the PDF in `source/`, then:
   `kb ingest source/my-doc.pdf --id my-doc --tags "tag1,tag2"`
   (needs the ingest extra: `pip install "aero-kb[ingest]"` — or run it
   inside Docker: `docker compose run --rm hub kb ingest source/my-doc.pdf --id my-doc`)
3. **Summarize** — open Claude Code in this repo and run the `kb-summarize`
   skill for the pending sections, then validate: `kb build`
4. **Serve the hub** — `docker compose up -d` → web UI at
   http://localhost:8321/ui (sign in with the token).
   Without Docker: `python -m aero_kb.mcp --hub . --transport http`
   (requires the `AERO_KB_HTTP_TOKEN` env var).
5. **Query** — `kb query "your question"`, the web UI, or point Claude Code
   at `.mcp.json` (MCP over stdio) / the HTTP endpoint.
```

- [ ] **Step 4: Implement `initcmd.py`**

```python
# src/aero_kb/initcmd.py
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

# target relative path -> template resource name under templates/init/
TEMPLATE_MAP: dict[str, str] = {
    ".kb/index.yaml": "index.yaml",
    "federation/README.md": "federation-README.md",
    "source/.gitignore": "source-gitignore.txt",
    ".mcp.json": "mcp.json",
    ".github/workflows/kb-review.yml": "kb-review.yml",
    "docker-compose.yml": "docker-compose.yml",
    ".env.example": "env.example",
    "QUICKSTART.md": "QUICKSTART.md",
}
EXPECTED_FILES = list(TEMPLATE_MAP)


@dataclass
class InitReport:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def init_repo(target: Path, force: bool = False) -> InitReport:
    """Scaffold a KB repo. Never overwrites existing files unless force=True."""
    base = resources.files("aero_kb").joinpath("templates/init")
    report = InitReport()
    for rel, resource_name in TEMPLATE_MAP.items():
        dest = target / rel
        if dest.exists() and not force:
            report.skipped.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = base.joinpath(resource_name).read_text(encoding="utf-8")
        dest.write_text(text, encoding="utf-8")
        report.created.append(rel)
    return report
```

- [ ] **Step 5: Add the CLI command to `cli.py`**

Insert after the `main()` callback (before `_resolve_hub_option`):

```python
@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Target directory (default: current)"),
    force: bool = typer.Option(False, "--force", help="Overwrite files that already exist"),
) -> None:
    """Scaffold a new KB repo: .kb/, federation/, config templates — ready for `kb ingest`."""
    from aero_kb.initcmd import init_repo

    report = init_repo(path, force=force)
    for rel in report.created:
        typer.echo(f"  created  {rel}")
    for rel in report.skipped:
        typer.secho(
            f"  skipped  {rel} (exists — use --force to overwrite)",
            fg=typer.colors.YELLOW,
        )
    typer.echo(
        f"kb init: {len(report.created)} file(s) created, {len(report.skipped)} skipped."
    )
    typer.echo("Next steps:")
    typer.echo("  1. cp .env.example .env    # then edit AERO_KB_HTTP_TOKEN")
    typer.echo("  2. kb ingest source/<file>.pdf --id <doc-id>")
    typer.echo("  (details: QUICKSTART.md)")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_init.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/aero_kb/templates/init src/aero_kb/initcmd.py src/aero_kb/cli.py tests/test_init.py
git commit -m "feat: kb init — scaffold a ready-to-use KB repo"
```

---

### Task 7: PyPI metadata + template packaging guarantee

**Files:**
- Modify: `pyproject.toml`
- Create: `LICENSE`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: Tasks 4 & 6 template layouts (`templates/web/*`, `templates/init/*`), `initcmd.TEMPLATE_MAP`.
- Produces: distribution metadata for PyPI; guarantee that every template referenced in code exists as a package resource.

- [ ] **Step 1: Check the PyPI name**

Run: `curl -s -o /dev/null -w "%{http_code}" https://pypi.org/pypi/aero-kb/json`
- `404` → name is free, keep `name = "aero-kb"`.
- `200` → name taken: change `[project] name` to `aero-kb-hub` in Step 3 (import path `aero_kb` and CLI `kb` stay unchanged), and note it in the commit message.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_templates.py
from importlib import resources

from aero_kb.initcmd import TEMPLATE_MAP

WEB_TEMPLATES = [
    "base.html", "login.html", "search.html",
    "docs.html", "doc.html", "section.html", "style.css",
]


def test_all_web_templates_exist_as_package_resources():
    base = resources.files("aero_kb").joinpath("templates/web")
    for name in WEB_TEMPLATES:
        assert base.joinpath(name).is_file(), name


def test_all_init_templates_exist_as_package_resources():
    base = resources.files("aero_kb").joinpath("templates/init")
    for resource_name in TEMPLATE_MAP.values():
        assert base.joinpath(resource_name).is_file(), resource_name
```

Run: `python -m pytest tests/test_templates.py -v` — expected: PASS already if Tasks 4/6 done correctly (this test's job is to catch future removals; if it fails, a template file is missing — fix that first).

- [ ] **Step 3: Update `pyproject.toml`**

Replace the `[project]` header block (keep `dependencies`, `optional-dependencies`, `scripts` as-is) and the build-system section:

```toml
[project]
name = "aero-kb"
version = "0.2.0"
description = "Knowledge Base as Code cho tài liệu hàng không — 4 tầng L0-L3, MCP server + web UI"
readme = "README.md"
license = "Apache-2.0"
license-files = ["LICENSE"]
requires-python = ">=3.11"
authors = [{ name = "Lâm Quốc Vương" }]
keywords = ["aviation", "knowledge-base", "mcp", "docs-as-code", "arinc-424", "icao"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Text Processing :: Indexing",
]

[project.urls]
Homepage = "https://github.com/vuonglq01685/AERO-KB"
Issues = "https://github.com/vuonglq01685/AERO-KB/issues"

[build-system]
requires = ["hatchling>=1.26"]
build-backend = "hatchling.build"
```

(`hatchling>=1.26` is needed for the PEP 639 `license = "Apache-2.0"` SPDX string. Hatchling includes non-Python files inside `src/aero_kb` in the wheel by default — no extra include config needed; the release workflow verifies this.)

- [ ] **Step 4: Create LICENSE**

Run: `curl -sL -o LICENSE https://www.apache.org/licenses/LICENSE-2.0.txt`
Verify: `head -3 LICENSE` shows "Apache License".

- [ ] **Step 5: Verify the wheel builds and contains templates**

```bash
pip install build
python -m build --wheel --outdir dist-check
python -c "import zipfile,glob; names=zipfile.ZipFile(glob.glob('dist-check/*.whl')[0]).namelist(); assert any('templates/web/base.html' in n for n in names), names; assert any('templates/init/QUICKSTART.md' in n for n in names); print('wheel OK')"
rm -rf dist-check
```

Expected output: `wheel OK`

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml LICENSE tests/test_templates.py
git commit -m "chore: PyPI metadata v0.2.0, Apache-2.0 license, template resource test"
```

---

### Task 8: Dockerfile + dev compose

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `docker-compose.yml` (repo root — dev variant with `build: .`)

**Interfaces:**
- Consumes: the wheel build from Task 7; server entrypoint `python -m aero_kb.mcp` (existing CLI flags `--kb`, `--hub`, `--transport`, `--host`); env `AERO_KB_HTTP_TOKEN`.
- Produces: image tagged `aero-kb` (locally) that Task 9's workflow pushes as `ghcr.io/vuonglq01685/aero-kb`. Runtime layout: KB repo mounted at `/data`, server on `:8321`, non-root user `app` with home `/home/app` (docling model cache lives under `/home/app/.cache`).

- [ ] **Step 1: Create `.dockerignore`**

```
.git
.github
.kb-work
.pytest_cache
.ruff_cache
.superpowers
.venv
dist
dist-check
docs
source
tests
*.pdf
.coverage
__pycache__
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
# Build stage: build the wheel from source.
FROM python:3.12-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

# Runtime stage: wheel + [ingest] extra (docling). git is required by
# aero_kb.gitio (hub clone/pull, kb-context pinning).
FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home app
COPY --from=build /dist /tmp/dist
RUN pip install --no-cache-dir "$(ls /tmp/dist/*.whl)[ingest]" && rm -rf /tmp/dist
USER app
WORKDIR /data
EXPOSE 8321
# The KB repo is mounted at /data; the hub is the repo itself (--hub /data).
CMD ["python", "-m", "aero_kb.mcp", "--kb", "/data/.kb", "--hub", "/data", "--transport", "http", "--host", "0.0.0.0"]
```

- [ ] **Step 3: Create the dev `docker-compose.yml` (repo root)**

Same as the init template (Task 6) but building locally:

```yaml
services:
  hub:
    build: .
    ports: ["8321:8321"]
    env_file: .env
    volumes:
      - ./:/data
      - kb-model-cache:/home/app/.cache
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8321/api/health')"]
      interval: 30s
volumes:
  kb-model-cache:
```

- [ ] **Step 4: Smoke-test locally (skip if no Docker on this machine)**

```bash
docker build -t aero-kb .
echo "AERO_KB_HTTP_TOKEN=smoke-test-token" > .env
docker compose up -d
sleep 8
curl -sf http://localhost:8321/api/health
curl -s -o /dev/null -w "%{http_code}" http://localhost:8321/api/docs   # expect 401 (no token)
docker compose down
rm .env
```

Expected: health returns `{"status":"ok",...}`; `/api/docs` without token → `401`.
If Docker is unavailable locally, note it — the release workflow (Task 9) runs the same smoke test in CI.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml
git commit -m "feat: docker image (serve + ingest) and dev compose"
```

---

### Task 9: Release pipeline + README

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `README.md` — add a "Web UI, Docker & cài qua PyPI" subsection under section 6 (installation)

**Interfaces:**
- Consumes: Dockerfile (Task 8), pyproject metadata (Task 7), test suite.
- Produces: on tag `v*`: PyPI release (trusted publishing — maintainer must one-time configure the "pending publisher" on pypi.org: project `aero-kb`, owner `vuonglq01685`, repo `AERO-KB`, workflow `release.yml`, environment `pypi`) + GHCR image `ghcr.io/vuonglq01685/aero-kb:{latest,vX.Y.Z}`.

- [ ] **Step 1: Create `.github/workflows/release.yml`**

```yaml
name: release
on:
  push:
    tags: ["v*"]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e .[dev]
      - run: pytest

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install build
      - run: python -m build
      - name: Verify wheel is self-contained (templates + kb init + doctor)
        run: |
          python -m venv /tmp/venv
          /tmp/venv/bin/pip install dist/*.whl
          mkdir /tmp/kbtest && cd /tmp/kbtest
          /tmp/venv/bin/kb init
          /tmp/venv/bin/kb doctor
          /tmp/venv/bin/python -c "from importlib import resources; resources.files('aero_kb').joinpath('templates/web/base.html').read_text(encoding='utf-8')"
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  pypi:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1

  docker:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - name: Build image
        run: docker build -t ghcr.io/vuonglq01685/aero-kb:${GITHUB_REF_NAME} .
      - name: Smoke test — serve an empty KB, health must answer, API must 401
        run: |
          mkdir -p /tmp/data/.kb
          echo "docs: []" > /tmp/data/.kb/index.yaml
          docker run -d --name kb -p 8321:8321 \
            -e AERO_KB_HTTP_TOKEN=smoke-test-token \
            -v /tmp/data:/data \
            ghcr.io/vuonglq01685/aero-kb:${GITHUB_REF_NAME}
          for i in $(seq 1 30); do
            curl -sf http://localhost:8321/api/health && break
            sleep 2
          done
          curl -sf http://localhost:8321/api/health
          code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8321/api/docs)
          test "$code" = "401"
          docker rm -f kb
      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Push tags
        run: |
          docker tag ghcr.io/vuonglq01685/aero-kb:${GITHUB_REF_NAME} ghcr.io/vuonglq01685/aero-kb:latest
          docker push ghcr.io/vuonglq01685/aero-kb:${GITHUB_REF_NAME}
          docker push ghcr.io/vuonglq01685/aero-kb:latest
```

- [ ] **Step 2: Add the README subsection**

In `README.md` section 6 (Cài đặt), append a new subsection (Vietnamese, matching the doc's tone):

```markdown
### 6.x. Cài qua PyPI, web UI và Docker

**Cài package** (khi đã publish): `pip install aero-kb` — có ngay lệnh `kb` và MCP server.
Tạo repo KB mới: `kb init` (sinh sẵn `.kb/`, `federation/`, `.mcp.json`, workflow CI,
`docker-compose.yml`, `QUICKSTART.md` — file nào đã có sẽ không bị ghi đè).

**Web UI cho người tra tay:** cùng một tiến trình HTTP phục vụ cả agent lẫn người:

```bash
AERO_KB_HTTP_TOKEN=bi-mat python -m aero_kb.mcp --hub . --transport http
# → agent:  http://<host>:8321/mcp   (Bearer token)
# → REST:   http://<host>:8321/api/… (Bearer token hoặc cookie)
# → người:  http://<host>:8321/ui    (đăng nhập bằng token, lưu cookie)
```

**Docker:** `docker compose up -d` (image có sẵn cả bộ ingest docling);
ingest ngay trong container: `docker compose run --rm hub kb ingest source/x.pdf --id x`.
Khi release tag `v*`, CI tự publish lên PyPI + đẩy image `ghcr.io/vuonglq01685/aero-kb`.
```

- [ ] **Step 3: Validate workflow syntax + full suite**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml', encoding='utf-8')); print('yaml OK')"
python -m pytest
```

Expected: `yaml OK`, all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml README.md
git commit -m "ci: release pipeline — PyPI trusted publishing + GHCR image; docs"
```

---

## Post-plan verification (before merge)

1. `python -m pytest --cov=src --cov-report=term-missing` — coverage of `aero_kb/web/*`, `initcmd.py` ≥ 80%.
2. Manual run: `set AERO_KB_HTTP_TOKEN=dev && python -m aero_kb.mcp --hub . --transport http` → open http://127.0.0.1:8321/ui, login, search "restrictive airspace", open a section, toggle L3, copy citation.
3. Reminder for the maintainer (manual, one-time): configure PyPI trusted publisher + create the `pypi` environment in GitHub repo settings before pushing the first `v*` tag.
```
