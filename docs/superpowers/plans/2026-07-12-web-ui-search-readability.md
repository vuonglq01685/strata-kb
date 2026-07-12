# Web UI Search Readability — Layout, Highlight, Match Badge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen the web UI's data-heavy pages (search, docs list, doc detail table) while keeping the section-detail page at a readable width, highlight matched query keywords inside search results, and show a small badge on each result indicating whether it matched by keyword (BM25) or by semantic fallback.

**Architecture:** All three lois vào (CLI `kb query`, MCP tool `kb_search`, web UI) share one retrieval engine: `center_kb.query.search()`. This plan touches only `query.py` (add a `match_mode` field to `QueryResult`, promote `_tokenize` to public `tokenize`), the hand-rolled markdown renderer `center_kb.web.mdrender` (add keyword highlighting during rendering, not as an HTML post-process), and `center_kb.web.ui` (wire tokenized query terms + badge into the result HTML) plus `style.css`/`section.html` for layout. CLI and MCP output are untouched — `match_mode` has a default so existing callers ignore it silently.

**Tech Stack:** Python 3.13 (`.venv`), Starlette (web routes + `TestClient` in tests), pytest, hand-rolled markdown renderer (no external markdown library), plain CSS (no build step).

**Spec:** `docs/superpowers/specs/2026-07-12-web-ui-search-readability-design.md`

## Global Constraints

- Web UI only — do NOT modify `cli.py` or `mcp.py` (spec §2, out of scope).
- Table cells must keep rendering **character-for-character** (existing invariant, documented in `mdrender.py`'s module docstring) — highlighting may only wrap already-present characters in `<mark>...</mark>`, never reflow, reorder, or alter cell text.
- Keyword highlight matching is **whole-word, case-insensitive** — no substring matches (e.g. query term `restrict` must NOT highlight `restricted`).
- `QueryResult.match_mode` defaults to `"keyword"`; only `_semantic_fallback()` sets `"semantic"`. `search()`'s signature and return type (`list[QueryResult]`) do not change.
- Test runner: `.venv/bin/python -m pytest` from the repo root.
- Follow existing code style: `from __future__ import annotations`, type hints on all functions, dataclasses for DTOs.

---

### Task 1: Promote `query._tokenize` to a public `tokenize`

**Files:**
- Modify: `src/center_kb/query.py:43-44` (definition), `src/center_kb/query.py:164` and `:166` (call sites)
- Test: `tests/test_query.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `center_kb.query.tokenize(text: str) -> list[str]` — Task 4 imports this in `web/ui.py` to tokenize the `q` query param into highlight terms, using the exact same tokenization BM25 ranking uses.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_query.py`:

```python
from center_kb.query import tokenize


def test_tokenize_lowercases_and_splits_on_non_alnum():
    assert tokenize("Restrictive Airspace, Type-1!") == [
        "restrictive", "airspace", "type", "1",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_query.py::test_tokenize_lowercases_and_splits_on_non_alnum -v`
Expected: FAIL with `ImportError: cannot import name 'tokenize' from 'center_kb.query'`

- [ ] **Step 3: Rename `_tokenize` to `tokenize`**

In `src/center_kb/query.py`, rename the function definition:

```python
def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())
```

And update both internal call sites inside `search()`:

```python
    section_tokens = [tokenize(f"{c.sec.title} {c.sec.summary}") for c in corpus]
    bm25 = BM25Plus(section_tokens)
    query_token_list = tokenize(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_query.py -v`
Expected: PASS (all tests, including the new one and every existing `search()` test — the rename must not change behavior).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/query.py tests/test_query.py
git commit -m "refactor: promote query._tokenize to public tokenize()"
```

---

### Task 2: Add `match_mode` to `QueryResult`

**Files:**
- Modify: `src/center_kb/query.py:21-31` (`QueryResult` dataclass), `src/center_kb/query.py` inside `_semantic_fallback` (the `QueryResult(...)` construction, currently around line 264-269)
- Test: `tests/test_query.py`, `tests/test_query_semantic.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `QueryResult.match_mode: str` (`"keyword"` or `"semantic"`). Task 5 reads `r.match_mode` in `web/ui.py` to render the match badge.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_query.py`:

```python
def test_search_results_default_to_keyword_match_mode(fixture_kb: Path):
    results = search(fixture_kb, "airspace designation type")
    assert results
    assert all(r.match_mode == "keyword" for r in results)
```

Append to `tests/test_query_semantic.py`:

```python
def test_semantic_fallback_results_have_semantic_match_mode(fixture_kb):
    results = search(
        fixture_kb, "airspace controlled zones", semantic=True,
        embedder=FakeEmbedder(),
    )
    assert results
    assert all(r.match_mode == "semantic" for r in results)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_query.py::test_search_results_default_to_keyword_match_mode tests/test_query_semantic.py::test_semantic_fallback_results_have_semantic_match_mode -v`
Expected: FAIL with `AttributeError: 'QueryResult' object has no attribute 'match_mode'`

- [ ] **Step 3: Add the field and set it in the semantic branch**

In `src/center_kb/query.py`, modify the `QueryResult` dataclass:

```python
@dataclass
class QueryResult:
    doc_id: str
    section_id: str
    title: str
    score: float
    citation: str
    content: str
    tokens: int
    source: str = "local"  # "local" | "hub" | "remote:<repo-id>"
    match_mode: str = "keyword"  # "keyword" | "semantic"
```

In `_semantic_fallback()`, add `match_mode="semantic"` to the `QueryResult(...)` construction:

```python
        results.append(
            QueryResult(
                doc_id=doc_id, section_id=sec_id, title=c.sec.title,
                score=float(score), citation=c.citation, content=content,
                tokens=n_tokens, source=c.source, match_mode="semantic",
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_query.py tests/test_query_semantic.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/query.py tests/test_query.py tests/test_query_semantic.py
git commit -m "feat: tag QueryResult with match_mode (keyword | semantic)"
```

---

### Task 3: Keyword highlighting in `mdrender.render()`

**Files:**
- Modify: `src/center_kb/web/mdrender.py` (add `_highlight`, thread `terms` through `render()` and `_render_table()`)
- Test: `tests/test_web_mdrender.py`

**Interfaces:**
- Consumes: nothing new (pure string in, string out).
- Produces: `render(md: str, terms: set[str] | None = None) -> str`. Task 4 calls this from `web/ui.py` with the tokenized query terms.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_mdrender.py`:

```python
def test_highlight_matches_whole_word_case_insensitive_in_paragraph():
    out = render("Restrictive Airspace designation rules.", terms={"airspace"})
    assert out == "<p>Restrictive <mark>Airspace</mark> designation rules.</p>"


def test_highlight_does_not_match_substring():
    out = render("Restricted and restriction apply.", terms={"restrict"})
    assert "<mark>" not in out


def test_highlight_in_heading():
    out = render("## 5.3 Restrictive Airspace", terms={"restrictive"})
    assert out == "<h2>5.3 <mark>Restrictive</mark> Airspace</h2>"


def test_highlight_in_table_cell():
    md = "| Code | Meaning |\n|---|---|\n| P | Prohibited |"
    out = render(md, terms={"prohibited"})
    assert "<td><mark>Prohibited</mark></td>" in out


def test_highlight_preserves_escaping_around_match():
    out = render("Length <1> char & alpha restricted.", terms={"restricted"})
    assert out == "<p>Length &lt;1&gt; char &amp; alpha <mark>restricted</mark>.</p>"


def test_no_terms_behaves_like_before():
    assert render("Plain text.") == "<p>Plain text.</p>"
    assert render("Plain text.", terms=set()) == "<p>Plain text.</p>"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_mdrender.py -k highlight -v`
Expected: FAIL with `TypeError: render() got an unexpected keyword argument 'terms'`

- [ ] **Step 3: Implement highlighting in `mdrender.py`**

Replace the full content of `src/center_kb/web/mdrender.py` with:

```python
# src/center_kb/web/mdrender.py
"""Minimal markdown→HTML for the exact subset used in L2/L3 files.

Supported: #..###### headings, blank-line paragraphs, GitHub pipe tables.
Table cells are escaped but never reworded/reflowed — the project's
inviolable rule is that tables render character-for-character. Optional
keyword highlighting wraps matched whole words in <mark> without altering
any other character.
"""
from __future__ import annotations

import html
import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _is_separator(row: str) -> bool:
    return "-" in row and bool(_SEPARATOR_RE.match(row))


def _highlight(text: str, terms: set[str]) -> str:
    if not terms:
        return html.escape(text)
    out: list[str] = []
    last = 0
    for m in _WORD_RE.finditer(text):
        word = m.group(0)
        if word.lower() in terms:
            out.append(html.escape(text[last:m.start()]))
            out.append(f"<mark>{html.escape(word)}</mark>")
            last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def _render_table(rows: list[str], terms: set[str]) -> str:
    has_header = len(rows) > 1 and _is_separator(rows[1])
    out = ["<table>"]
    for i, row in enumerate(rows):
        if has_header and i == 1:
            continue
        tag = "th" if (has_header and i == 0) else "td"
        cells = "".join(f"<{tag}>{_highlight(c, terms)}</{tag}>" for c in _cells(row))
        out.append(f"<tr>{cells}</tr>")
    out.append("</table>")
    return "".join(out)


def render(md: str, terms: set[str] | None = None) -> str:
    terms = terms or set()
    blocks: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        if para:
            blocks.append(f"<p>{_highlight(' '.join(para), terms)}</p>")
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
            blocks.append(_render_table(table, terms))
            continue
        m = _HEADING_RE.match(line)
        if m:
            flush_para()
            level = len(m.group(1))
            blocks.append(f"<h{level}>{_highlight(m.group(2).strip(), terms)}</h{level}>")
        elif not line.strip():
            flush_para()
        else:
            para.append(line.strip())
        i += 1
    flush_para()
    return "\n".join(blocks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_mdrender.py -v`
Expected: PASS (all tests, including the pre-existing ones — `render(md)` without `terms` must behave exactly as before).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/mdrender.py tests/test_web_mdrender.py
git commit -m "feat: highlight matched keywords when rendering markdown"
```

---

### Task 4: Wire highlight terms through the search route

**Files:**
- Modify: `src/center_kb/web/ui.py:15` (import), `src/center_kb/web/ui.py:56-80` (`_result_blocks`), `src/center_kb/web/ui.py:131-161` (`home`)
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `center_kb.query.tokenize` (Task 1), `center_kb.web.mdrender.render(md, terms=...)` (Task 3).
- Produces: `_result_blocks(results, terms: set[str] | None = None) -> str`. Task 5 extends this same function's signature is unchanged by Task 5 (badge is added inside the loop, not a new parameter).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_ui.py`:

```python
def test_home_query_highlights_matched_keywords(fixture_kb):
    resp = _client(fixture_kb).get("/ui", params={"q": "airspace designation"})
    assert "<mark>Airspace</mark>" in resp.text
    assert "<mark>designation</mark>" in resp.text


def test_tag_only_search_has_no_highlight(fixture_kb):
    resp = _client(fixture_kb).get("/ui", params={"tags": "airspace"})
    assert "<mark>" not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_ui.py::test_home_query_highlights_matched_keywords tests/test_web_ui.py::test_tag_only_search_has_no_highlight -v`
Expected: `test_home_query_highlights_matched_keywords` FAILs (`assert "<mark>Airspace</mark>" in resp.text` — no marks yet); `test_tag_only_search_has_no_highlight` already passes trivially (no regression check yet, still run it to confirm baseline).

- [ ] **Step 3: Wire terms through `home()` and `_result_blocks()`**

In `src/center_kb/web/ui.py`, change the import line:

```python
from center_kb.query import get_section, search, tokenize
```

Change `_result_blocks` to accept and use `terms`:

```python
def _result_blocks(results, terms: set[str] | None = None) -> str:
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
            f'<div class="result-body">{md_render(r.content, terms=terms)}</div>'
            "</article>"
        )
    return "\n".join(blocks)
```

In `home()`, compute `terms` from `q` and pass it through:

```python
    async def home(request: Request) -> HTMLResponse:
        q = request.query_params.get("q", "").strip()
        raw_tags = request.query_params.get("tags", "").strip()
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        terms = set(tokenize(q)) if q else set()
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
            results_html = _result_blocks(results, terms)
        elif tags:
            docs = api.list_docs(config, include_local=include_local)
            results_html = _doc_cards(_match_tags(docs, tags))
```

(The rest of `home()` — the `scope`/`body`/`return` lines — is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_ui.py -v`
Expected: PASS (all tests — including the two new ones and every pre-existing `test_web_ui.py` test, which must keep passing unmodified).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/ui.py tests/test_web_ui.py
git commit -m "feat: highlight matched query keywords in search results"
```

---

### Task 5: Match-mode badge (keyword vs semantic) on each result

**Files:**
- Modify: `src/center_kb/web/ui.py` (add `_match_badge` helper, use it in `_result_blocks`)
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `QueryResult.match_mode` (Task 2).
- Produces: nothing consumed by later tasks — this is the last behavioral task.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_ui.py`:

```python
def test_home_query_shows_keyword_match_badge(fixture_kb):
    resp = _client(fixture_kb).get("/ui", params={"q": "airspace designation"})
    assert 'class="match-badge match-keyword"' in resp.text


def test_home_query_shows_semantic_match_badge_on_fallback(fixture_kb, monkeypatch):
    from center_kb.query import QueryResult
    from center_kb.web import ui as ui_module

    fake_result = QueryResult(
        doc_id="demo-doc", section_id="1.1", title="Airspace Records",
        score=0.42, citation="demo-doc §1.1 (Rev 1)",
        content="## 1.1 Airspace Records\n\nFuzzy semantic match.",
        tokens=5, source="local", match_mode="semantic",
    )
    monkeypatch.setattr(ui_module, "search", lambda *a, **k: [fake_result])
    resp = _client(fixture_kb).get("/ui", params={"q": "airspace designation"})
    assert 'class="match-badge match-semantic"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_ui.py::test_home_query_shows_keyword_match_badge tests/test_web_ui.py::test_home_query_shows_semantic_match_badge_on_fallback -v`
Expected: FAIL with `assert 'class="match-badge match-keyword"' in resp.text` (badge markup doesn't exist yet).

- [ ] **Step 3: Add `_match_badge` and render it in `_result_blocks`**

In `src/center_kb/web/ui.py`, add a helper next to `_source_badge`:

```python
def _match_badge(mode: str) -> str:
    return f'<span class="match-badge match-{_e(mode)}">{_e(mode)}</span>'
```

Insert it into `_result_blocks`'s per-result header, right after `_source_badge`:

```python
        blocks.append(
            '<article class="result">'
            '<header class="result-head">'
            f'<a class="cite" href="{href}">{_e(r.citation)}</a>'
            f"{_source_badge(r.source)}"
            f"{_match_badge(r.match_mode)}"
            f'<span class="score">score {r.score:.2f} · ~{r.tokens} tk</span>'
            "</header>"
            f'<div class="result-body">{md_render(r.content, terms=terms)}</div>'
            "</article>"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_ui.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/ui.py tests/test_web_ui.py
git commit -m "feat: show keyword/semantic match badge on each search result"
```

---

### Task 6: Widen data pages, keep section detail readable, style highlight + badge

**Files:**
- Modify: `src/center_kb/templates/web/style.css`, `src/center_kb/templates/web/section.html`
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: nothing (pure CSS/template — the `<mark>` and `.match-badge` markup already exist from Tasks 3 and 5).
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_ui.py`:

```python
def test_static_css_widens_main_and_defines_new_styles(fixture_kb):
    resp = _client(fixture_kb).get("/ui/static/style.css")
    assert "max-width: 76rem" in resp.text
    assert ".detail" in resp.text
    assert "mark {" in resp.text
    assert ".match-keyword" in resp.text
    assert ".match-semantic" in resp.text


def test_section_page_wraps_content_in_detail_container(fixture_kb):
    resp = _client(fixture_kb).get("/ui/docs/demo-doc/1.1")
    assert 'class="detail"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_ui.py::test_static_css_widens_main_and_defines_new_styles tests/test_web_ui.py::test_section_page_wraps_content_in_detail_container -v`
Expected: FAIL (`max-width: 76rem` not in CSS yet; `class="detail"` not in section page HTML yet).

- [ ] **Step 3: Widen `main`, add `.detail`, `mark`, and `.match-badge` styles**

In `src/center_kb/templates/web/style.css`, change the `main` rule:

```css
main { max-width: 76rem; margin: 0 auto; padding: 2.25rem 1.5rem 3rem; }
```

Add a new rule right after it, for the narrower reading column used by `section.html`:

```css
.detail { max-width: 54rem; margin-inline: auto; }
```

Add highlight styling — place near the `.chips & badges` section:

```css
mark {
  background: var(--amber-soft); color: var(--amber);
  border-radius: 3px; padding: 0 0.15em; font-weight: 600;
}
```

Add match-badge styling right after the existing `.source-badge`/`.status-badge` block
(reusing the same visual pattern and the existing `--muted`/`--violet` tokens):

```css
.match-badge {
  display: inline-block;
  font-family: var(--mono); font-size: 0.68rem; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  border-radius: 4px; padding: 0.08rem 0.45rem;
  border: 1px solid transparent;
}
.match-keyword  { color: var(--muted); background: #f0eee9; border-color: var(--line-strong); }
.match-semantic { color: var(--violet); background: var(--violet-soft); border-color: #d8cdf1; }
```

- [ ] **Step 4: Wrap `section.html`'s body in `.detail`**

Replace the full content of `src/center_kb/templates/web/section.html` with:

```html
<div class="detail">
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
</div>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_ui.py -v`
Expected: PASS (all tests).

- [ ] **Step 6: Run the full test suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS (every test in the repo — this is the final task, confirming no regressions anywhere).

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/templates/web/style.css src/center_kb/templates/web/section.html tests/test_web_ui.py
git commit -m "feat: widen search/docs/doc-table pages, keep section detail readable"
```

---

## Manual verification (not automatable by tests)

After Task 6, run the HTTP server locally and check in a real browser:

```bash
.venv/bin/python -m center_kb.mcp --transport http
```

- Open `/ui`, run a keyword search (e.g. `airspace designation`) — confirm results are
  visibly wider than before, matched words are highlighted amber, and each result shows
  a `KEYWORD` badge.
- Open `/ui/docs/<any-doc>` — confirm the sections table (`Section`/`Title`/`Summary`/`Status`)
  has noticeably fewer wrapped lines than before.
- Open a section detail page (`/ui/docs/<doc>/<section>`) — confirm the prose column is
  not stretched uncomfortably wide, while still sitting inside the wider page.
- Resize the browser to 320, 768, 1024, 1440px — confirm no horizontal overflow at any
  width, and the search form still wraps sensibly on narrow viewports.
