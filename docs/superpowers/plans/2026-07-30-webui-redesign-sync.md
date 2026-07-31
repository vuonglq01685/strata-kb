# Web UI Redesign Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sync the Jinja web UI with the latest `CENTER-KB Redesign.dc.html` deltas: left-rail section tree, searchable/toggling tag panel, docs filter bar, search tag-filter row + doc count, real semantic toggle, J/C shortcuts, reader "On this page" TOC.

**Architecture:** Server-rendered Starlette + Jinja2 with progressive-enhancement JS. All new controls work without JS (GET links/forms); JS-only affordances (live filters, shortcuts, tag cap) are hidden or inert under `noscript`. Data aggregation lives in `src/center_kb/web/uidata.py`; route handlers in `src/center_kb/web/ui.py`; one shared stylesheet `style.css`; one shared `app.js`.

**Tech Stack:** Python 3.13 (`.venv`), Starlette, Jinja2, pytest, ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-30-webui-redesign-sync-design.md`

## Global Constraints

- Branch: `feat/webui-redesign-sync` (already checked out; spec committed as `544693a`)
- Activate venv first: `source .venv/bin/activate` (Python 3.13)
- Test command: `python -m pytest tests/<file>::<test> -q` — tests must stay hermetic (never invoke real `claude`/LLM; the dev machine has a real `claude` binary)
- Lint: `ruff check src tests` must pass (CI gate T0)
- Commit format: `<type>: <description>` (feat/fix/test/chore…), no attribution footer
- Design tokens: use the existing CSS custom properties in `style.css` (`--accent`, `--warn`, `--ok`, `--field`, `--line`, `--mono`, …). Never hardcode a palette value that already has a token
- Status colors: pending `var(--warn)` #92600a · summarized `var(--accent)` #1349a5 · reviewed `var(--ok)` #1a6e3c
- Templates auto-escape (Jinja `select_autoescape`); never mark user data `| safe`
- Every template change must keep the no-JS path working (GET forms/links); JS-only inputs get a `noscript` hide
- Existing test helpers to reuse (in `tests/test_web_ui.py`): `_client(kb_dir, hub)`, `_main(resp)`, `_topbar(resp)`, fixtures `fed_hub` (2 repos: `icao-kb:icao-annex-2` §1.1, `arinc-kb:arinc-424` §5.3, both status `summarized`) and `demo_doc_hub`

---

### Task 1: `uidata.section_tree()` — tree data for the left rail

**Files:**
- Modify: `src/center_kb/web/uidata.py`
- Test: `tests/test_web_uidata.py`

**Interfaces:**
- Consumes: `models.Manifest`, `models.SectionEntry` (fields: `id`, `title`, `status`, `file`)
- Produces: `TreeNode` frozen dataclass with `kind: str` (`"chapter" | "section"`), `label: str`, `id: str = ""`, `status: str = ""`; function `section_tree(manifest: Manifest) -> list[TreeNode]`. Task 4's template iterates these nodes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_uidata.py` (follow its existing import style):

```python
def test_section_tree_single_file_has_no_chapter_rows():
    m = models.Manifest(id="d", title="D", sections=[
        models.SectionEntry(id="1", title="One", file="ch1-intro.md"),
        models.SectionEntry(id="2", title="Two", file="ch1-intro.md"),
    ])
    tree = uidata.section_tree(m)
    assert [n.kind for n in tree] == ["section", "section"]
    assert [n.id for n in tree] == ["1", "2"]


def test_section_tree_groups_by_file_with_chapter_headers():
    m = models.Manifest(id="d", title="D", sections=[
        models.SectionEntry(id="1", title="One", file="ch1-intro.md",
                            status="reviewed"),
        models.SectionEntry(id="1.2", title="One-two", file="ch1-intro.md"),
        models.SectionEntry(id="2", title="Two", file="ch2-data.md"),
    ])
    tree = uidata.section_tree(m)
    assert [(n.kind, n.label) for n in tree] == [
        ("chapter", "ch1 intro"), ("section", "One"), ("section", "One-two"),
        ("chapter", "ch2 data"), ("section", "Two"),
    ]
    assert tree[1].status == "reviewed"


def test_section_tree_empty_manifest():
    assert uidata.section_tree(models.Manifest(id="d", title="D")) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_uidata.py -q -k section_tree`
Expected: FAIL — `AttributeError: module 'center_kb.web.uidata' has no attribute 'section_tree'`

- [ ] **Step 3: Implement**

In `src/center_kb/web/uidata.py`, after the `Coverage` dataclass add:

```python
@dataclass(frozen=True)
class TreeNode:
    kind: str  # "chapter" | "section"
    label: str
    id: str = ""
    status: str = ""
```

After `doc_coverage()` add:

```python
def section_tree(manifest: Manifest) -> list[TreeNode]:
    """Left-rail tree: section rows, with a chapter header row per source
    file — but only when the doc spans more than one file."""
    files = {s.file for s in manifest.sections}
    out: list[TreeNode] = []
    current: str | None = None
    for s in manifest.sections:
        if len(files) > 1 and s.file != current:
            current = s.file
            stem = s.file.rsplit(".", 1)[0]
            out.append(TreeNode(kind="chapter", label=stem.replace("-", " ")))
        out.append(TreeNode(kind="section", label=s.title, id=s.id, status=s.status))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_uidata.py -q`
Expected: PASS (all, including pre-existing)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/uidata.py tests/test_web_uidata.py
git commit -m "feat: uidata.section_tree for the left-rail section tree"
```

---

### Task 2: `uidata.inject_heading_anchors()` — anchors + TOC for the reader

**Files:**
- Modify: `src/center_kb/web/uidata.py`
- Test: `tests/test_web_uidata.py`

**Interfaces:**
- Consumes: HTML string produced by `center_kb.web.mdrender.render` (headings are `<h1>`–`<h6>` with escaped inner text, no attributes)
- Produces: `TocEntry` frozen dataclass with `anchor: str`, `label: str`; function `inject_heading_anchors(content_html: str) -> tuple[str, list[TocEntry]]`. Task 8 wires it into `section_page` and the template.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_uidata.py`:

```python
def test_inject_heading_anchors_adds_ids_and_toc():
    html_in = "<h2>5.129 Restrictive Airspace</h2><p>x</p><h3>Field notes</h3>"
    out, toc = uidata.inject_heading_anchors(html_in)
    assert '<h2 id="5-129-restrictive-airspace">' in out
    assert '<h3 id="field-notes">' in out
    assert [(t.anchor, t.label) for t in toc] == [
        ("5-129-restrictive-airspace", "5.129 Restrictive Airspace"),
        ("field-notes", "Field notes"),
    ]


def test_inject_heading_anchors_dedupes_slugs():
    out, toc = uidata.inject_heading_anchors("<h2>Same</h2><h2>Same</h2>")
    assert [t.anchor for t in toc] == ["same", "same-2"]
    assert 'id="same-2"' in out


def test_inject_heading_anchors_no_headings():
    out, toc = uidata.inject_heading_anchors("<p>plain</p>")
    assert out == "<p>plain</p>"
    assert toc == []


def test_inject_heading_anchors_unescapes_label():
    out, toc = uidata.inject_heading_anchors("<h2>A &amp; B</h2>")
    assert toc[0].label == "A & B"
    assert toc[0].anchor == "a-b"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_uidata.py -q -k inject_heading`
Expected: FAIL — `AttributeError ... has no attribute 'inject_heading_anchors'`

- [ ] **Step 3: Implement**

In `src/center_kb/web/uidata.py` add to the imports block:

```python
import html
import re
```

Add after `TreeNode`:

```python
@dataclass(frozen=True)
class TocEntry:
    anchor: str
    label: str


_HEADING_TAG_RE = re.compile(r"<h([1-6])>(.*?)</h\1>", re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
```

Add after `section_tree()`:

```python
def inject_heading_anchors(content_html: str) -> tuple[str, list[TocEntry]]:
    """Give every mdrender heading an id and return the matching TOC list.

    mdrender emits attribute-less <hN>escaped text</hN>, so a regex pass is
    safe here — this is not a general-purpose HTML rewriter.
    """
    toc: list[TocEntry] = []
    used: set[str] = set()

    def _sub(m: re.Match[str]) -> str:
        level, inner = m.group(1), m.group(2)
        label = html.unescape(_TAG_STRIP_RE.sub("", inner)).strip()
        slug = _SLUG_RE.sub("-", label.lower()).strip("-") or "section"
        anchor, n = slug, 2
        while anchor in used:
            anchor = f"{slug}-{n}"
            n += 1
        used.add(anchor)
        toc.append(TocEntry(anchor=anchor, label=label))
        return f'<h{level} id="{anchor}">{inner}</h{level}>'

    return _HEADING_TAG_RE.sub(_sub, content_html), toc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_uidata.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/uidata.py tests/test_web_uidata.py
git commit -m "feat: uidata.inject_heading_anchors for the reader TOC"
```

---

### Task 3: Tag panel — toggle links in the shell + rail template

**Files:**
- Modify: `src/center_kb/web/ui.py` (add `_tag_links`, extend `_shell_ctx`)
- Modify: `src/center_kb/templates/web/_partials/left_rail.html`
- Modify: `src/center_kb/templates/web/static/style.css`
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `uidata.all_tags(hub) -> list[str]`
- Produces: `shell.tags` becomes `list[dict]` with keys `label: str`, `href: str`, `on: bool` (was `list[str]`); new `shell.selected_tags: list[str]`. Tasks 5 and 6 render `shell.tags` chips with `t.on` / `t.href`. `_tag_links(all_tags: list[str], selected: list[str], q: str) -> list[dict]` is module-level in `ui.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_ui.py` (a `_rail(resp)` helper mirrors `_main`):

```python
def _left_rail(resp) -> str:
    text = resp.text
    start = text.index('<aside class="rail rail-left"')
    return text[start : text.index("</aside>", start)]


def test_tag_links_toggle_on_and_off():
    from center_kb.web.ui import _tag_links
    links = _tag_links(["airspace", "icao"], ["icao"], q="air")
    by_label = {l["label"]: l for l in links}
    assert by_label["icao"]["on"] is True
    # removing the only selected tag keeps the query
    assert by_label["icao"]["href"] == "/ui?q=air"
    assert by_label["airspace"]["on"] is False
    # adding appends to the current selection
    assert by_label["airspace"]["href"] == "/ui?q=air&tags=icao%2Cairspace"


def test_tag_links_no_query_no_tags_falls_back_to_search_screen():
    from center_kb.web.ui import _tag_links
    links = _tag_links(["icao"], ["icao"], q="")
    assert links[0]["href"] == "/ui?q="


def test_rail_tag_panel_marks_selected_and_searchable(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui?q=air&tags=icao")
    rail = _left_rail(resp)
    assert "Search tags…" in rail
    assert 'class="chip on"' in rail          # selected chip highlighted
    assert "tags=icao%2Cairspace" in rail     # unselected chip adds itself
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_ui.py -q -k "tag_links or tag_panel"`
Expected: FAIL — `ImportError: cannot import name '_tag_links'`

- [ ] **Step 3: Implement `ui.py`**

In `src/center_kb/web/ui.py` change the urllib import to:

```python
from urllib.parse import quote, urlencode
```

Add above `_shell_ctx`:

```python
def _tag_links(all_tags: list[str], selected: list[str], q: str) -> list[dict]:
    """One toggle link per known tag: clicking adds/removes it from `tags=`.

    Falls back to /ui?q= (the search screen) when toggling off the last tag
    with no query — a bare /ui would render the overview instead.
    """
    out: list[dict] = []
    for t in all_tags:
        on = t in selected
        new = [x for x in selected if x != t] if on else [*selected, t]
        params: list[tuple[str, str]] = []
        if q:
            params.append(("q", q))
        if new:
            params.append(("tags", ",".join(new)))
        href = f"/ui?{urlencode(params)}" if params else "/ui?q="
        out.append({"label": t, "href": href, "on": on})
    return out
```

Replace `_shell_ctx` with:

```python
def _shell_ctx(
    config: ServerConfig, screen: str, q: str = "",
    raw_tags: str = "", budget: int | None = None,
) -> dict:
    selected = [t.strip() for t in raw_tags.split(",") if t.strip()]
    hub = api.hub_handle(config)
    if hub is None:
        return {"screen": screen, "hub_ok": False, "q": q,
                "raw_tags": raw_tags, "budget": budget,
                "repo_count": 0, "catalog": [], "tags": [],
                "selected_tags": selected}
    return {
        "screen": screen, "hub_ok": True, "q": q,
        "raw_tags": raw_tags, "budget": budget,
        "repo_count": len(load_federation(hub.federation_dir)),
        "catalog": uidata.catalog(hub),
        "tags": _tag_links(uidata.all_tags(hub), selected, q),
        "selected_tags": selected,
    }
```

(`catalog` stays in the shell until Task 4 removes the rail cards.)

- [ ] **Step 4: Implement the rail tag panel**

In `src/center_kb/templates/web/_partials/left_rail.html` replace the existing Tags `rail-group` (`<p class="kicker">Tags</p>` + `tag-cloud` block) with:

```html
  <div class="rail-group">
    <div class="tag-head">
      <p class="kicker">Tags</p>
      <span class="tag-count">{{ shell.tags | length }}</span>
    </div>
    <input type="search" class="rail-input" placeholder="Search tags…"
           aria-label="Search tags" data-filter-list="[data-tag-chip]">
    <div class="tag-cloud">
      {% for t in shell.tags %}<a class="chip {{ 'on' if t.on else '' }}"
         data-tag-chip data-text="{{ t.label }}" href="{{ t.href }}">{{ t.label }}</a>{% endfor %}
    </div>
    <p class="tag-hint" data-tag-hint>click to add or remove a tag filter</p>
  </div>
```

At the top of `left_rail.html` (first line inside the `<aside>`) add the shared no-JS hide for all live-filter inputs:

```html
  <noscript><style>[data-filter-list] { display: none }</style></noscript>
```

- [ ] **Step 5: CSS**

In `style.css`, next to the existing `.chip` rules add:

```css
.chip.on { color: #fff; background: var(--accent); border-color: var(--accent); }
.tag-head { display: flex; align-items: baseline; gap: 6px; padding: 0 8px; }
.tag-head .tag-count { margin-left: auto; font: 400 10px/1.4 var(--mono); color: var(--faint); }
.rail-input { width: 100%; height: 28px; padding: 0 10px; font: 12.5px/1 var(--sans);
  color: var(--ink); background: var(--field); border: 1px solid var(--line);
  border-radius: var(--r-sm); }
.rail-input:focus { background: #fff; border-color: var(--accent); outline: none;
  box-shadow: 0 0 0 3px var(--focus-ring); }
.tag-hint { margin: 0; padding: 0 9px; font: 400 10px/1.5 var(--mono);
  color: var(--faint); letter-spacing: .04em; }
.tag-cloud { max-height: 104px; overflow-y: auto; }
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_web_ui.py -q`
Expected: the 4 new tests PASS. If any pre-existing test fails because `shell.tags` is now dicts (e.g. a template or assertion using bare tag strings), fix that usage to `t.label`/`t.href` — `left_rail.html` was the only consumer before this task.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/web/ui.py src/center_kb/templates/web/_partials/left_rail.html src/center_kb/templates/web/static/style.css tests/test_web_ui.py
git commit -m "feat: searchable toggling tag panel in the left rail"
```

---

### Task 4: Left rail — section tree, Sign in nav, compact legend, drop catalog cards

**Files:**
- Modify: `src/center_kb/web/ui.py` (`_render_page` shell_extra, `doc_page`, `section_page`)
- Modify: `src/center_kb/templates/web/_partials/left_rail.html`
- Modify: `src/center_kb/templates/web/static/style.css`
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `uidata.section_tree(manifest) -> list[TreeNode]` (Task 1); `_left_rail(resp)` test helper (Task 3)
- Produces: `_render_page(..., shell_extra: dict | None = None)` — merged into the shell dict. Shell gains optional keys `tree: list[TreeNode]` and `tree_doc: dict` (`id`, `repo`, `name`, `meta`, `active`). Template shows the tree instead of the tag panel when `shell.tree` is set.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_ui.py`:

```python
def test_doc_screen_rail_shows_section_tree_not_catalog(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/arinc-424?repo=arinc-kb")
    rail = _left_rail(resp)
    assert "← all documents" in rail
    assert "§5.3" in rail and "Restrictive Airspace" in rail
    assert "Filter sections…" in rail
    assert "catalog-card" not in rail


def test_section_screen_tree_marks_active_row(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/arinc-424/5.3?repo=arinc-kb")
    rail = _left_rail(resp)
    assert "tree-row active" in rail


def test_overview_rail_has_tags_not_tree_and_signin(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui")
    rail = _left_rail(resp)
    assert "Search tags…" in rail
    assert "tree-row" not in rail
    assert "/ui/login" in rail          # Sign in nav entry
    assert "catalog-card" not in rail


def test_rail_legend_is_compact(fed_hub):
    rail = _left_rail(_client(fed_hub / ".kb", str(fed_hub)).get("/ui"))
    assert ">pending<" in rail and ">summarized<" in rail and ">reviewed<" in rail
    assert "awaiting SME" not in rail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_ui.py -q -k "rail_shows_section_tree or active_row or tags_not_tree or legend_is_compact"`
Expected: FAIL (tree markup absent, catalog-card present)

- [ ] **Step 3: Implement `ui.py`**

Change `_render_page`'s signature and shell handling:

```python
def _render_page(
    template: str, config: ServerConfig, screen: str,
    status: int = 200, q: str = "", raw_tags: str = "",
    budget: int | None = None, shell_extra: dict | None = None, **ctx,
) -> HTMLResponse:
    # (keep the existing comment about raw_tags/budget mirroring)
    shell = _shell_ctx(config, screen, q=q, raw_tags=raw_tags, budget=budget)
    if shell_extra:
        shell.update(shell_extra)
    ctx["q"] = q
    ctx["raw_tags"] = raw_tags
    ctx["budget"] = budget
    return HTMLResponse(
        templating.render(template, shell=shell, **ctx), status_code=status
    )
```

In `_shell_ctx`, delete the `"catalog": uidata.catalog(hub),` line and the `"catalog": [],` entry in the hub-down branch (the rail no longer renders catalog cards; `overview`'s stats use `uidata.catalog` directly in `home`).

Add a small helper above `build_routes`:

```python
def _tree_extra(manifest, doc_id: str, rid: str, active: str = "") -> dict:
    meta = f"{len(manifest.sections)} sections"
    if manifest.revision:
        meta = f"{manifest.revision} · {meta}"
    return {
        "tree": uidata.section_tree(manifest),
        "tree_doc": {"id": doc_id, "repo": rid, "name": manifest.title,
                     "meta": meta, "active": active},
    }
```

In `doc_page`, pass it to `_render_page`:

```python
        return _render_page(
            "doc.html", config, screen="doc", title=manifest.title,
            doc_id=doc_id, manifest=manifest, rid=rid, rows=rows,
            coverage=uidata.doc_coverage(manifest),
            filter_value=filter_raw, status_q=status_q, files=files,
            shell_extra=_tree_extra(manifest, doc_id, rid),
        )
```

In `section_page`, inside the `if found is not None:` branch capture the extra, and pass it (manifest unavailable → no tree → rail degrades to nav+tags):

```python
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
        return _render_page(
            "section.html", config, screen="section",
            title=f"{doc_id} §{section_id}",
            doc_id=result.doc_id, section_id=result.section_id, repo=result.source,
            level=level, result=result, content_html=md_render(result.content),
            prev=prev, next=nxt, entry=entry, revision=revision,
            shell_extra=shell_extra,
        )
```

- [ ] **Step 4: Rewrite `left_rail.html`**

Replace the whole file with (tag panel block comes from Task 3 — keep it verbatim):

```html
<aside class="rail rail-left" aria-label="Navigation and catalog">
  <noscript><style>[data-filter-list] { display: none }</style></noscript>
  <nav class="nav" aria-label="Main navigation">
    <a href="/ui" class="{{ 'active' if shell.screen == 'overview' else '' }}">Overview</a>
    <a href="/ui?q=" class="{{ 'active' if shell.screen == 'search' else '' }}">Search</a>
    <a href="/ui/docs" class="{{ 'active' if shell.screen in ('docs', 'doc') else '' }}">Documents</a>
    {% if shell.screen == 'section' %}<a href="#" class="active">Reader</a>{% endif %}
    <a href="/ui/login">Sign in</a>
  </nav>

  {% if shell.tree %}
  <div class="rail-group">
    <a class="tree-back" href="/ui/docs">← all documents</a>
    <a class="tree-doc" href="/ui/docs/{{ shell.tree_doc.id | urlencode }}?repo={{ shell.tree_doc.repo | urlencode }}">
      <span class="name">{{ shell.tree_doc.name }}</span>
      <span class="meta">{{ shell.tree_doc.meta }}</span>
    </a>
    <input type="search" class="rail-input" placeholder="Filter sections…"
           aria-label="Filter sections" data-filter-list="[data-tree-row]">
    <div class="tree-list">
      {% for n in shell.tree %}
      {% if n.kind == 'chapter' %}
      <span class="tree-chapter">{{ n.label }}</span>
      {% else %}
      <a class="tree-row {{ 'active' if n.id == shell.tree_doc.active else '' }}"
         data-tree-row data-text="{{ (n.id ~ ' ' ~ n.label) | lower }}"
         href="/ui/docs/{{ shell.tree_doc.id | urlencode }}/{{ n.id | urlencode }}?repo={{ shell.tree_doc.repo | urlencode }}">
        <span class="dot dot-{{ n.status }}"></span>
        <span class="num">§{{ n.id }}</span>
        <span class="label">{{ n.label }}</span>
      </a>
      {% endif %}
      {% endfor %}
    </div>
  </div>
  {% else %}
  <div class="rail-group">
    <div class="tag-head">
      <p class="kicker">Tags</p>
      <span class="tag-count">{{ shell.tags | length }}</span>
    </div>
    <input type="search" class="rail-input" placeholder="Search tags…"
           aria-label="Search tags" data-filter-list="[data-tag-chip]">
    <div class="tag-cloud">
      {% for t in shell.tags %}<a class="chip {{ 'on' if t.on else '' }}"
         data-tag-chip data-text="{{ t.label }}" href="{{ t.href }}">{{ t.label }}</a>{% endfor %}
    </div>
    <p class="tag-hint" data-tag-hint>click to add or remove a tag filter</p>
  </div>
  {% endif %}

  <div class="legend">
    <span class="item"><span class="sw" style="background:#92600a"></span>pending</span>
    <span class="item"><span class="sw" style="background:#1349a5"></span>summarized</span>
    <span class="item"><span class="sw" style="background:#1a6e3c"></span>reviewed</span>
  </div>
</aside>
```

(Note: "Sign in" is unconditional — the token middleware makes every rendered
/ui page an authenticated one, so there is no in-template "signed out" state;
the link simply opens `/ui/login`, which is auth-exempt.)

- [ ] **Step 5: CSS**

In `style.css`: delete the `.catalog-card` rule block (5 rules, lines starting `.catalog-card`). Replace the `.legend` rules with:

```css
.legend { margin-top: auto; display: flex; flex-wrap: wrap; gap: 4px 12px;
  padding: 10px 12px; border-radius: var(--r-md); background: var(--field);
  border: 1px solid var(--line); }
.legend .item { display: flex; align-items: center; gap: 6px;
  font: 400 10.5px/1.5 var(--mono); color: var(--muted); letter-spacing: .04em; }
.legend .sw { width: 7px; height: 7px; border-radius: 2px; }
```

Add tree styles next to the `.nav` rules:

```css
.tree-back { padding: 0 8px; font: 600 10px/1.5 var(--mono); letter-spacing: .14em;
  text-transform: uppercase; color: var(--faint); }
.tree-back:hover { color: var(--accent); }
.tree-doc { display: flex; flex-direction: column; gap: 1px; padding: 0 8px 3px; }
.tree-doc .name { font: 600 13.5px/1.4 var(--sans); color: var(--ink); }
.tree-doc .meta { font: 400 10px/1.5 var(--mono); color: var(--faint); letter-spacing: .04em; }
.tree-list { display: flex; flex-direction: column; gap: 1px; max-height: 64vh; overflow-y: auto; }
.tree-chapter { margin: 2px 0 0; padding: 5px 9px; font: 600 10.5px/1.4 var(--mono);
  letter-spacing: .1em; text-transform: uppercase; color: var(--faint); }
.tree-row { display: flex; align-items: baseline; gap: 7px; margin-left: 9px;
  padding: 5px 9px; border-radius: var(--r-sm); font-size: 12.5px; line-height: 1.45; }
.tree-row .dot { flex: none; width: 6px; height: 6px; border-radius: 2px;
  align-self: center; }
.dot-pending { background: var(--warn); }
.dot-summarized { background: var(--accent); }
.dot-reviewed { background: var(--ok); }
.tree-row .num { flex: none; font: 600 11px/1.4 var(--mono); color: var(--faint); }
.tree-row .label { min-width: 0; color: var(--body-c); }
.tree-row.active { background: var(--accent-bg); box-shadow: inset 2px 0 0 var(--accent); }
.tree-row.active .num, .tree-row.active .label { color: var(--accent); font-weight: 600; }
```

- [ ] **Step 6: Run the file's full suite and repair stale assertions**

Run: `python -m pytest tests/test_web_ui.py -q`
Expected: new tests PASS; these known pre-existing spots reference the old rail and must be updated (comments and assertions only — do not change handler behavior to satisfy them):
- `_main` docstring (line ~18): rewrite the rail description (tags + legend + tree, no catalog cards)
- line ~325, ~449, ~676 comments mentioning the rail catalog — update wording
- line ~487 legend test asserting `"summarized — awaiting SME"` — assert `"summarized"` inside the rail instead
- line ~1198 `assert "Demo Document" in resp.text  # catalog card in left rail` — the doc title no longer appears via the rail; point the assertion at `_main(resp)` content or the page it actually tests
- lines ~1201–1217 `_shell_ctx` tests asserting `ctx["catalog"]` — the key is gone; assert `ctx["tags"] == []`/hub-down shape instead

Then run the neighbouring template suites: `python -m pytest tests/test_web_app.py tests/test_web_templating.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/web/ui.py src/center_kb/templates/web/_partials/left_rail.html src/center_kb/templates/web/static/style.css tests/test_web_ui.py
git commit -m "feat: left-rail section tree, Sign in nav, compact legend"
```

---

### Task 5: Docs screen — filter bar + card polish

**Files:**
- Modify: `src/center_kb/web/ui.py` (`docs_page`)
- Modify: `src/center_kb/templates/web/docs.html`
- Modify: `src/center_kb/templates/web/_partials/cards.html`
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `api.list_docs(config) -> list[dict] | None` (dict keys: `id`, `repo`, `title`, `revision`, `summary`, `tags`); `shell.tags` toggle links (Task 3)
- Produces: `docs.html` context gains `filter_value: str`, `total_docs: int`. `doc_card(d)` macro emits `data-doc-card data-text="…"` for the client filter.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_ui.py`:

```python
def test_docs_filter_param_filters_server_side(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs?filter=arinc")
    main = _main(resp)
    assert "arinc-424" in main
    assert "icao-annex-2" not in main
    assert "1 of 2 documents" in main


def test_docs_filter_matches_tags_too(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs?filter=airspace")
    main = _main(resp)
    assert "icao-annex-2" in main
    assert "arinc-424" not in main


def test_docs_cards_have_open_sections_link_and_filter_text(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs")
    main = _main(resp)
    assert "open sections →" in main
    assert "data-doc-card" in main
    assert "2 of 2 documents" in main
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_ui.py -q -k docs_filter or docs_cards`
(quote the -k expression: `-k "docs_filter or docs_cards"`)
Expected: FAIL — filter param ignored, no count label

- [ ] **Step 3: Implement `docs_page`**

Replace `docs_page` in `ui.py`:

```python
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
```

Also in `_search_screen`'s docs branch (`if not q and tags:`), add the two new context keys so the template renders from both paths:

```python
            matched = _match_tags(docs, tags)
            return _render_page(
                "docs.html", config, screen="docs", title="Documents",
                docs=matched, browse_tags=tags, raw_tags=raw_tags,
                filter_value="", total_docs=len(docs),
            )
```

- [ ] **Step 4: Templates**

`docs.html` — replace the `{% if browse_tags %}` meta-line in the page head with nothing (chips move to the filter bar), and insert the filter bar between the page head and the card list:

```html
  <form class="filter-bar" method="get" action="/ui/docs">
    <input type="search" name="filter" value="{{ filter_value }}"
           placeholder="Filter documents by name, id or tag…"
           aria-label="Filter documents" data-filter-list="[data-doc-card]">
    {% for t in shell.tags if t.on %}
    <a class="chip on" href="{{ t.href }}">{{ t.label }} <span class="x">✕</span></a>
    {% endfor %}
    <span class="shown" data-filter-count data-total="{{ total_docs }}"
          data-noun="documents">{{ docs | length }} of {{ total_docs }} documents</span>
    <noscript><button type="submit" class="seg">Apply</button></noscript>
  </form>
```

`_partials/cards.html` — replace the macro with:

```html
{% macro doc_card(d) %}
<article class="doc-card" data-doc-card
         data-text="{{ (d.id ~ ' ' ~ (d.title or '') ~ ' ' ~ d.tags | join(' ')) | lower }}">
  <header>
    <a class="name" href="/ui/docs/{{ d.id | urlencode }}?repo={{ d.repo | urlencode }}">{{ d.title or d.id }}</a>
    {% if d.revision %}<span class="badge badge-summarized">{{ d.revision }}</span>{% endif %}
    <span class="badge badge-mode">{{ d.repo }}</span>
  </header>
  {% if d.summary %}<p class="summary">{{ d.summary }}</p>{% endif %}
  <p class="chips">
    {% for t in d.tags %}<a class="chip" href="/ui?tags={{ t | urlencode }}">{{ t }}</a>
    {% else %}<span class="chip" style="opacity:.6">no tags</span>{% endfor %}
    <a class="open-doc" href="/ui/docs/{{ d.id | urlencode }}?repo={{ d.repo | urlencode }}">open sections →</a>
  </p>
</article>
{% endmacro %}
```

Add to `style.css` next to `.doc-card`:

```css
.doc-card .open-doc { margin-left: auto; font: 400 11px/1.7 var(--mono); letter-spacing: .04em; }
.chip .x { color: rgba(255,255,255,.75); }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_ui.py -q`
Expected: PASS (fix any docs-screen assertion that referenced the removed head meta-line)

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/web/ui.py src/center_kb/templates/web/docs.html src/center_kb/templates/web/_partials/cards.html src/center_kb/templates/web/static/style.css tests/test_web_ui.py
git commit -m "feat: docs catalog filter bar with tag chips and doc count"
```

---

### Task 6: Search screen — removable tag-filter row + doc count

**Files:**
- Modify: `src/center_kb/web/ui.py` (`_search_screen`)
- Modify: `src/center_kb/templates/web/search.html`
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `shell.tags` toggle links (Task 3)
- Produces: `search.html` context gains `docs_count: int`. Task 7 extends the same template's rail.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_ui.py`:

```python
def test_search_meta_line_counts_docs(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui?q=airspace")
    main = _main(resp)
    assert "docs · budget" in main   # "<N> sections · <M> docs · budget …"


def test_search_tag_row_offers_removal_or_none_label(fed_hub):
    c = _client(fed_hub / ".kb", str(fed_hub))
    with_tag = _main(c.get("/ui?q=airspace&tags=icao"))
    assert "✕" in with_tag           # removable chip
    without = _main(c.get("/ui?q=airspace"))
    assert "none — searching the whole store" in without
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_ui.py -q -k "meta_line_counts or tag_row_offers"`
Expected: FAIL

- [ ] **Step 3: Implement**

In `_search_screen`, after `found = search(...)` compute and thread the count; both `search.html` renders get it:

```python
        docs_count = len({r.doc_id for r in found})
```

Pass `docs_count=docs_count` in the final `_render_page("search.html", ...)` call, and `docs_count=0` in the early hub-down `search.html` render.

In `search.html`:
- Change the meta line to:
```html
    <p class="meta-line">{{ results | length }} sections · {{ docs_count }} docs · budget {{ budget }} tk · scope hub federation</p>
```
- Replace the `{% if active_tags %}` block with an always-rendered row:
```html
  <div class="meta-line">
    <span class="kicker">Tag filter</span>
    {% for t in shell.tags if t.on %}
    <a class="chip on" href="{{ t.href }}">{{ t.label }} <span class="x">✕</span></a>
    {% endfor %}
    {% if not active_tags %}<span>none — searching the whole store</span>{% endif %}
  </div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_ui.py -q`
Expected: PASS (update any old assertion on the previous meta-line format: it read `"{{ results|length }} sections · budget …"`)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/ui.py src/center_kb/templates/web/search.html tests/test_web_ui.py
git commit -m "feat: search tag-filter row with removable chips and doc count"
```

---

### Task 7: Real semantic toggle

**Files:**
- Modify: `src/center_kb/query.py` (`search` honors a new `use_semantic` kwarg)
- Modify: `src/center_kb/web/ui.py` (`_search_screen`)
- Modify: `src/center_kb/templates/web/search.html` (match-mode form + budget-form plumbing)
- Test: `tests/test_query.py`, `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `query.search(hub, text, tags=None, budget=2000, semantic=False, embedder=None)`
- Produces: `query.search(..., use_semantic: bool = True, ...)` — when False the semantic leg is skipped by passing `embedder=None` into `_search_index`. The existing `semantic` warn-flag keeps its current meaning (CLI `--semantic` help says "Warn when embeddings are unavailable (hybrid runs both legs automatically)"), so CLI/MCP behavior is unchanged. `search.html` gains `semantic_on: bool` context.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_query.py` — hermetic: `_search_index` is stubbed out, so no
hub, DB, or embedder is touched (with an empty `fused` list, `search()` never
dereferences the hub argument):

```python
def test_search_use_semantic_false_skips_embedder(monkeypatch):
    import center_kb.query as query_mod
    seen = {}

    def spy(hub, embedder, text, tags):
        seen["embedder"] = embedder
        return [], {}

    monkeypatch.setattr(query_mod, "_search_index", spy)
    sentinel = object()
    assert query_mod.search(
        object(), "airspace", use_semantic=False, embedder=sentinel
    ) == []
    assert seen["embedder"] is None


def test_search_use_semantic_default_passes_embedder(monkeypatch):
    import center_kb.query as query_mod
    seen = {}

    def spy(hub, embedder, text, tags):
        seen["embedder"] = embedder
        return [], {}

    monkeypatch.setattr(query_mod, "_search_index", spy)
    sentinel = object()
    query_mod.search(object(), "airspace", embedder=sentinel)
    assert seen["embedder"] is sentinel
```

Append to `tests/test_web_ui.py`:

```python
def test_search_semantic_param_controls_flag(fed_hub, monkeypatch):
    calls = {}

    def fake_search(hub, text, tags=None, budget=2000, use_semantic=True, **kw):
        calls["use_semantic"] = use_semantic
        return []

    monkeypatch.setattr("center_kb.web.ui.search", fake_search)
    c = _client(fed_hub / ".kb", str(fed_hub))
    c.get("/ui?q=airspace&semantic=0")
    assert calls["use_semantic"] is False
    c.get("/ui?q=airspace")            # no param → default on
    assert calls["use_semantic"] is True
    c.get("/ui?q=airspace&semantic=0&semantic=1")  # hidden 0 + checked box
    assert calls["use_semantic"] is True


def test_search_rail_renders_match_mode_form(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui?q=airspace")
    assert "keyword (FTS5)" in resp.text
    assert "semantic (KNN)" in resp.text
    assert 'name="semantic" value="1"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_query.py -q -k use_semantic; python -m pytest tests/test_web_ui.py -q -k "semantic_param or match_mode_form"`
Expected: FAIL — `TypeError: search() got an unexpected keyword argument 'use_semantic'`

- [ ] **Step 3: Implement `query.py`**

Change `search`'s signature and the `_search_index` call:

```python
def search(
    hub: "HubHandle",
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    semantic: bool = False,
    use_semantic: bool = True,
    embedder=None,  # center_kb.embed.Embedder | None — injectable for tests
) -> list[QueryResult]:
```

and

```python
    fused, rows = _search_index(
        hub, embedder if use_semantic else None, text, tags
    )
```

- [ ] **Step 4: Implement `ui.py` + template**

In `_search_screen`, before the `found = search(...)` line:

```python
        sem_vals = request.query_params.getlist("semantic")
        use_semantic = ("1" in sem_vals) if sem_vals else True
        found = (
            search(hub, q, tags=tags or None, budget=budget,
                   use_semantic=use_semantic)
            if q else []
        )
```

Thread `semantic_on=use_semantic` into both `search.html` `_render_page` calls (hub-down render: `semantic_on=True`).

In `search.html`, replace the "Match modes" rail block with:

```html
<div class="rail-block">
  <p class="kicker">Match mode</p>
  <form method="get" action="/ui">
    <input type="hidden" name="q" value="{{ q }}">
    {% if raw_tags %}<input type="hidden" name="tags" value="{{ raw_tags }}">{% endif %}
    <input type="hidden" name="budget" value="{{ budget }}">
    <label class="check"><input type="checkbox" checked disabled>keyword (FTS5)</label>
    <input type="hidden" name="semantic" value="0">
    <label class="check"><input type="checkbox" name="semantic" value="1"
           {{ 'checked' if semantic_on }} onchange="this.form.submit()">semantic (KNN)</label>
    <noscript><button type="submit" class="seg" style="margin-top:6px">Apply</button></noscript>
  </form>
  <p style="margin:2px 0 0; font-size:11.5px; color:#98a0aa; line-height:1.5">
    Both are fused with RRF when the embedder is installed. No model call
    happens at lookup time.</p>
</div>
```

In the existing budget form (same file), add one hidden field so budget changes keep the mode:

```html
    <input type="hidden" name="semantic" value="{{ '1' if semantic_on else '0' }}">
```

Add to `style.css`:

```css
.check { display: flex; align-items: center; gap: 8px; font-size: 12.5px;
  color: var(--body-c); }
.check input { accent-color: var(--accent); }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_query.py tests/test_web_ui.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/query.py src/center_kb/web/ui.py src/center_kb/templates/web/search.html src/center_kb/templates/web/static/style.css tests/test_query.py tests/test_web_ui.py
git commit -m "feat: functional semantic toggle on the search screen"
```

---

### Task 8: Reader "On this page" TOC

**Files:**
- Modify: `src/center_kb/web/ui.py` (`section_page`)
- Modify: `src/center_kb/templates/web/section.html`
- Modify: `src/center_kb/templates/web/static/style.css`
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `uidata.inject_heading_anchors(content_html) -> tuple[str, list[TocEntry]]` (Task 2)
- Produces: `section.html` context gains `toc: list[TocEntry]` (`.anchor`, `.label`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_ui.py`:

```python
def test_section_rail_shows_on_this_page_toc(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/arinc-424/5.3?repo=arinc-kb")
    assert "On this page" in resp.text
    # fed_hub L2 body starts "## 5.3 Restrictive Airspace"
    assert 'id="5-3-restrictive-airspace"' in resp.text
    assert 'href="#5-3-restrictive-airspace"' in resp.text


def test_section_toc_hidden_without_headings(fed_hub):
    _append_section_body(
        fed_hub, "arinc-kb", "arinc-424", "ch5-nav", "5.9", "No Heading",
        "Plain paragraph only.\n")
    _add_section(fed_hub, "arinc-kb", "arinc-424", models.SectionEntry(
        id="5.9", title="No Heading", file="ch5-nav.md", status="pending"))
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/arinc-424/5.9?repo=arinc-kb")
    assert "On this page" not in resp.text
```

(Check `_append_section_body`/`_add_section` signatures at the top of the file and match their argument order exactly; `_append_section_body` writes the L2/L3 files, `_add_section` extends the manifest.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_ui.py -q -k "on_this_page or toc_hidden"`
Expected: FAIL — "On this page" absent

- [ ] **Step 3: Implement**

In `section_page`, replace `content_html=md_render(result.content)` wiring:

```python
        content_html, toc = uidata.inject_heading_anchors(
            md_render(result.content)
        )
```

and pass `content_html=content_html, toc=toc` to `_render_page`.

In `section.html`'s `{% block rail %}`, add as the first block:

```html
{% if toc %}
<div class="rail-block">
  <p class="kicker">On this page</p>
  {% for t in toc %}
  <a class="toc-link" href="#{{ t.anchor }}">{{ t.label }}</a>
  {% endfor %}
</div>
{% endif %}
```

Add to `style.css`:

```css
.toc-link { display: block; padding: 3px 9px; font-size: 12.5px;
  border-left: 2px solid var(--line); color: var(--muted); }
.toc-link:hover { border-left-color: var(--accent); color: var(--accent); }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_ui.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/ui.py src/center_kb/templates/web/section.html src/center_kb/templates/web/static/style.css tests/test_web_ui.py
git commit -m "feat: reader 'On this page' TOC with heading anchors"
```

---

### Task 9: app.js — generic live filter, tag cap, J/C shortcuts

**Files:**
- Modify: `src/center_kb/templates/web/static/app.js`
- Modify: `src/center_kb/templates/web/static/style.css`
- Modify: `src/center_kb/templates/web/search.html` (shortcuts rail box)

**Interfaces:**
- Consumes: DOM contracts from Tasks 3–5: inputs with `data-filter-list="<selector>"`, items with `data-text`, optional `[data-filter-count]` (`data-total`, `data-noun`), `[data-tag-chip]`, `[data-tag-hint]`, `.result-card` with a `[data-copy-text]` button
- Produces: nothing consumed by later tasks

This is progressive enhancement — no unit tests; the no-JS path is covered by the template tests above. Verify manually in Step 3.

- [ ] **Step 1: Implement `app.js`**

Append to `static/app.js`:

```js
// Generic live filter: an input with data-filter-list="<selector>" hides
// non-matching elements (matched against each element's data-text).
const TAG_CAP = 8;

function capTagChips() {
  const hint = document.querySelector("[data-tag-hint]");
  const visible = [...document.querySelectorAll("[data-tag-chip]")]
    .filter((el) => el.style.display !== "none");
  visible.forEach((el, i) => { if (i >= TAG_CAP) el.style.display = "none"; });
  if (hint) {
    hint.textContent = visible.length > TAG_CAP
      ? `+${visible.length - TAG_CAP} more — keep typing to narrow`
      : "click to add or remove a tag filter";
  }
}

document.querySelectorAll("[data-filter-list]").forEach((box) => {
  const sel = box.getAttribute("data-filter-list");
  box.addEventListener("input", () => {
    const q = box.value.trim().toLowerCase();
    let shown = 0;
    document.querySelectorAll(sel).forEach((el) => {
      const on = !q || (el.dataset.text || "").includes(q);
      el.style.display = on ? "" : "none";
      if (on) shown += 1;
    });
    const count = document.querySelector("[data-filter-count]");
    if (count) {
      const total = parseInt(count.dataset.total, 10) || shown;
      count.textContent = `${shown} of ${total} ${count.dataset.noun || "shown"}`;
    }
    if (sel === "[data-tag-chip]") capTagChips();
  });
});
capTagChips();

// J = focus next search result, C = copy the focused result's citation.
document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
  const key = typeof e.key === "string" ? e.key.toLowerCase() : "";
  if (key === "j") {
    const cards = [...document.querySelectorAll(".result-card")];
    if (!cards.length) return;
    const current = document.activeElement && document.activeElement.closest
      ? document.activeElement.closest(".result-card") : null;
    const next = cards[Math.min(cards.length - 1, cards.indexOf(current) + 1)];
    next.setAttribute("tabindex", "-1");
    next.focus();
    e.preventDefault();
  } else if (key === "c") {
    const current = document.activeElement && document.activeElement.closest
      ? document.activeElement.closest(".result-card") : null;
    const card = current || document.querySelector(".result-card");
    const btn = card && card.querySelector("[data-copy-text]");
    if (btn) { btn.click(); e.preventDefault(); }
  }
});
```

Add to `style.css`:

```css
.result-card:focus { outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring); }
```

In `search.html`, extend the shortcuts rail card with the two new rows:

```html
<div class="rail-card">
  <p class="kicker">Shortcuts</p>
  <span class="rail-kv"><span>Focus search</span><span class="kbd">⌘K</span></span>
  <span class="rail-kv"><span>Next result</span><span class="kbd">J</span></span>
  <span class="rail-kv"><span>Copy citation</span><span class="kbd">C</span></span>
</div>
```

- [ ] **Step 2: Run the template suites (regression only)**

Run: `python -m pytest tests/test_web_ui.py tests/test_web_app.py -q`
Expected: PASS (this task adds no server behavior)

- [ ] **Step 3: Manual smoke check**

Run the server against a scratch hub (or reuse a dev hub):
`python -m center_kb.cli serve --help` to confirm the serve entry point, then start it and open `/ui?q=<anything>`:
- typing in "Search tags…" narrows chips, caps at 8, hint updates
- doc screen: "Filter sections…" narrows the tree
- docs screen: filter input narrows cards and updates "N of M documents"
- search screen: J walks result cards (visible focus ring), C flips the copy button label to "copied ✓"
- disable JS (or curl): pages still render; filter inputs hidden; Apply buttons submit

- [ ] **Step 4: Commit**

```bash
git add src/center_kb/templates/web/static/app.js src/center_kb/templates/web/static/style.css src/center_kb/templates/web/search.html
git commit -m "feat: live filters, tag cap, and J/C shortcuts in app.js"
```

---

### Task 10: Full verification + branch finish

**Files:**
- Possibly modify: any test/template with stale assertions

- [ ] **Step 1: Full test suite**

Run: `python -m pytest -q`
Expected: PASS — fix any remaining stale assertion (most likely spots were enumerated in Task 4 Step 6). Never weaken a behavioral test to pass; only update wording/selectors that referenced the old rail markup.

- [ ] **Step 2: Lint**

Run: `ruff check src tests`
Expected: clean. Fix any finding (unused import, line length) without behavior change.

- [ ] **Step 3: Commit any test/lint fixes**

```bash
git add -A
git commit -m "test: update web UI assertions for the redesigned rail"
```
(skip if nothing changed)

- [ ] **Step 4: Finish**

Use the superpowers:finishing-a-development-branch skill — the expected outcome is a PR from `feat/webui-redesign-sync` to `main` (repo convention: PRs, CI gate must pass).
