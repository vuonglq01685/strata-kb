# Hub Mobile / Foldable / iPad UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the hub web UI (`/ui`) fully usable, with every desktop feature, at every width from 320px up: bottom tab bar + bottom sheets below 900px, compact top bar + right-rail sheet below 1280px, desktop at ≥1280px unchanged.

**Architecture:** One markup. The existing `<aside class="rail rail-left">` / `<aside class="rail rail-right">` become bottom sheets through CSS media queries; `base.html` gains a tab-bar partial, a More-sheet partial, a sheet-pill strip and a compact top-bar control set, all outside `<main>`. `static/app.js` gains a small sheet controller and the search-expand toggle. No-JS falls back to in-flow panels through `<noscript><style>`.

**Tech Stack:** Jinja2 templates, plain CSS (`static/style.css`), vanilla JS (`static/app.js`), pytest + Starlette `TestClient`; browser check with the pre-installed Node Playwright (`require('playwright')`, Chromium).

**Spec:** `docs/superpowers/specs/2026-10-31-hub-mobile-ui-design.md`

## Global Constraints

- Breakpoints (CSS px, viewport width): phone layout `max-width: 899px`; compact top bar and right-rail sheet `max-width: 1279px`; ≥1280px must look and behave as today.
- Desktop grid literal stays: `grid-template-columns: 288px minmax(0,1fr) 292px`; `grid-template-columns: 288px` appears exactly twice in `style.css` (`tests/test_web_ui.py::test_left_rail_is_288px`, `::test_static_css_widens_main_and_defines_new_styles`).
- The rail tags must still start with `<aside class="rail rail-left"` and `<aside class="rail rail-right"`. Add attributes only after `class`.
- New shell markup (tab bar, pill strip, sheets, scrim) sits outside `<main class="content">…</main>` and outside `.topbar` (`.topbar` has `backdrop-filter`, which traps `position: fixed` children).
- CSP is `script-src 'self'`: no inline `<script>`, no `on*=` attributes. `<noscript><style>` and `style=` are allowed.
- No new dependencies (Python or JS). No dark theme, no PWA files.
- Every feature works with JS off.
- Touch rules under `@media (pointer: coarse)`: tap targets ≥ 44×44px; `input, select, textarea` font-size ≥ 16px.
- Viewport meta: `width=device-width, initial-scale=1, viewport-fit=cover`; never `user-scalable=no` or `maximum-scale`.
- Sheet: max-height `80dvh` (`80vh` fallback), width capped at 640px and centered at ≥ 600px, ≈200ms slide, no animation under `prefers-reduced-motion: reduce`.
- Tab bar: 5 links in this order: Overview `/ui`, Docs `/ui/docs`, Tickets `/ui/tickets`, Code `/ui/code`, Q&A `/ui/questions`; ≥ 44px tall; `padding-bottom: env(safe-area-inset-bottom)`.
- Right-rail pill labels: overview `Store health`, doc `Coverage`, search `Filters`, section / plan_mission / plan_ticket `On this page`, default `Page info`. Left-rail pill: `Sections · N` (N = section rows in `shell.tree`) when `shell.tree`, else `Tags`.
- Commits: `<type>: <description>` (feat, fix, test, docs, chore…), ending with the session's attribution lines.

## Plan-level calls (not in the spec; flag in review if wrong)

- The pill strip renders **above** the page head (first row of a new `.main-col` wrapper around `<main>`), not inside it, so it stays outside `<main>` per the constraint above. The mockup showed it under the title.
- The More sheet repeats the Sign out `<form>` (3 lines) rather than moving the desktop one; the status chips come from one shared macro.

## Review Focus

1. **Long unbroken strings at 320–344px** (slug section ids, `owner/repo` pins, workflow refs, URLs): expected to wrap or ellipsize, never widen the page. Pinned in Task 1's fixture (long ids) + overflow check.
2. **Rotate / unfold while a sheet is open** (viewport 402 → 1366): the sheet closes, scroll lock lifts, the rails return to columns. Pinned in Task 4's harness check `resize-closes-sheet`.
3. **Back button after following a link from a sheet** (bfcache restore): page comes back with no sheet open and the page scrollable. Pinned in Task 4's harness check `bfcache-no-sheet`.
4. **JS disabled on a phone:** tab bar links work, both rails' content is visible in-flow, no overflow. Pinned in Task 4's harness run `nojs`.
5. **Long tag cloud / section tree inside a sheet:** the sheet scrolls internally, never taller than 80% of the viewport, and the page behind does not scroll. Pinned in Task 4's harness check `sheet-scrolls-inside` (fixture with 60 tags and 40 sections).

---

### Task 1: Browser check harness (red baseline)

**Files:**
- Create: `scripts/ui_demo_server.py`
- Create: `scripts/mobile_ui_check.cjs`

**Interfaces:**
- Produces: `python scripts/ui_demo_server.py --port 8765` serves `ui.build_routes(ServerConfig(kb_dir=…, hub=…), token)` (no auth middleware, like `tests/test_web_ui.py::_client`) over uvicorn on a temp hub; prints `READY http://127.0.0.1:8765` once listening.
- Produces: `node scripts/mobile_ui_check.cjs <base_url> <out_dir> [--only <check>] [--baseline]`. Exits 0 when all checks pass, 1 otherwise; prints one line per failure `FAIL <check> <viewport> <path>: <detail>`. `--baseline` writes screenshots to `<out_dir>/baseline/` and runs no assertions.
- Check names later tasks add to: `overflow`, `desktop-unchanged`, `sheets`, `resize-closes-sheet`, `bfcache-no-sheet`, `nojs`, `sheet-scrolls-inside`, `touch-targets`.

- [ ] **Step 1: Write `scripts/ui_demo_server.py`**

Builds the hub in a `tempfile.mkdtemp()` dir the way `tests/conftest.py::fed_hub` does (`git init`, `.kb/index.yaml`, `make_fed_entry(...)`, `write_federation_index`), importing `make_fed_entry` from `tests.conftest` (run from repo root). Fixture content:
- `fed_hub`'s two repos plus `demo-kb:demo-doc` with `DEMO_L2`/`DEMO_L3` from `tests/test_web_ui.py`.
- one doc whose id is `very-long-document-identifier-without-any-breaks-0123456789` with a section id `appendix-b.long-slug-section-identifier-0123456789` (Review Focus 1).
- one doc with 60 tags (`tag-00`…`tag-59`) and 40 sections (`1.1`…`1.40`, append with the `_add_section` approach from `tests/test_web_ui.py`) (Review Focus 5).
- plan fixtures for `/ui/tickets` and one mission + one ticket page, copying the smallest setup `tests/test_web_plans.py` uses, if it needs nothing beyond files on disk; otherwise skip those pages and note it in the commit message.

- [ ] **Step 2: Write `scripts/mobile_ui_check.cjs` with the `overflow` and `desktop-unchanged` checks**

Pages: `/ui`, `/ui?q=airspace`, `/ui/docs`, `/ui/docs/demo-doc?repo=demo-kb`, `/ui/docs/demo-doc/1.1?repo=demo-kb`, the long-id doc + section pages, the 60-tag doc page, `/ui/tickets`, `/ui/code`, `/ui/questions`, `/ui/login`, `/ui/docs/does-not-exist?repo=demo-kb` (error page), plus the plan pages if Task 1 Step 1 made them.
Viewports (w×h): 344×882, 375×667, 402×874, 440×956, 412×915, 600×900, 884×1104, 744×1133, 834×1194, 1024×1366, 1180×820, 1366×1024, 1440×900.
- `overflow`: `document.documentElement.scrollWidth <= window.innerWidth` on every page × viewport; save a screenshot `<out_dir>/<w>x<h>/<slug>.png`.
- `desktop-unchanged`: at 1440×900 and 1366×1024 (mouse, no touch), the screenshot buffer equals `<out_dir>/baseline/<w>x<h>/<slug>.png`; on mismatch write `<slug>.diff-actual.png` and fail.

- [ ] **Step 3: Capture the desktop baseline before any UI change**

Run (two shells): `.venv/bin/python scripts/ui_demo_server.py --port 8765` then `node scripts/mobile_ui_check.cjs http://127.0.0.1:8765 .ui-check --baseline`
Expected: `.ui-check/baseline/1440x900/*.png` and `1366x1024/*.png` exist. Add `.ui-check/` to `.gitignore`.

- [ ] **Step 4: Run the check to see it fail**

Run: `node scripts/mobile_ui_check.cjs http://127.0.0.1:8765 .ui-check --only overflow`
Expected: exit 1, `FAIL overflow 344x882 /ui/docs/demo-doc?repo=demo-kb: …` (section table 720px) among others. `--only desktop-unchanged` exits 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/ui_demo_server.py scripts/mobile_ui_check.cjs .gitignore
git commit -m "test: add mobile UI browser check harness"
```

---

### Task 2: Shell markup (tab bar, More sheet, pill strip, compact top-bar controls)

**Files:**
- Modify: `src/strata_kb/templates/web/base.html`
- Create: `src/strata_kb/templates/web/_partials/tab_bar.html`
- Create: `src/strata_kb/templates/web/_partials/more_sheet.html`
- Create: `src/strata_kb/templates/web/_partials/status_chips.html`
- Modify: `overview.html`, `doc.html`, `search.html`, `section.html`, `plan_mission.html`, `plan_ticket.html` (add `{% block rail_label %}` only)
- Modify: `src/strata_kb/templates/web/static/style.css` (hide-by-default rules only)
- Test: `tests/test_web_mobile_shell.py`

**Interfaces:**
- Consumes: `shell` context from `web/ui.py::_shell_ctx` (`screen`, `menu_kind`, `tree`, `tree_doc`, `is_admin`, `hub_ok`, `pull{failed,label,title}`, `commit{sha,date,title}`, `repo_count`, `version`). No Python changes.
- Produces (DOM contract Tasks 3–4 style and script):
  - `<nav class="tab-bar" aria-label="Main menus">` with 5 `<a>`; active one has `aria-current="page"` and class `on`.
  - `<div class="main-col">` wrapping `<div class="sheet-pills">` + the existing `<main class="content">`.
  - Pill buttons: `<button type="button" class="sheet-pill" data-sheet-open="rail-left|rail-right" aria-controls="rail-left|rail-right" aria-expanded="false">`. Right pill only when the page's rail block renders non-blank (`{% set rail_html = self.rail() %}` … `rail_html | trim`).
  - Rails gain ids after class: `<aside class="rail rail-left" id="rail-left" …>`, `<aside class="rail rail-right" id="rail-right" …>`; both get `aria-label` unchanged.
  - In the top bar: `<span class="hub-dot …" aria-label="hub online|hub offline">`, `<button type="button" class="topbar-btn" data-search-toggle aria-label="Search">`, `<button type="button" class="topbar-btn" data-sheet-open="more" aria-controls="more" aria-expanded="false" aria-label="More">`, and a Cancel `<button type="button" data-search-toggle>` inside the search form.
  - `<div class="sheet more-sheet" id="more" role="dialog" aria-modal="true" aria-label="More">`: macro `status_chips(shell, verbose=True)` (each chip's `title` text also printed as visible `<span class="chip-detail">`), `<div class="more-nav">` with Registry (`{% if shell.is_admin %}`) and Sign in links, and a Sign out form identical to the desktop one.
  - `<div class="sheet-scrim" id="sheet-scrim" data-sheet-close hidden></div>` once, after `.columns`.
  - `{% block rail_label %}Page info{% endblock %}` in `base.html`; overrides per Global Constraints.
  - One `<noscript><style>` block in `base.html` (Task 4 fills its rules; this task adds the block with the rule hiding `.sheet-pill, .topbar-btn`).
- CSS this task adds: `.tab-bar, .sheet-pills, .topbar-btn, .hub-dot, .more-sheet, .sheet-scrim { display: none; }` so ≥1280 is unchanged; `.main-col { min-width: 0; }`.

- [ ] **Step 1: Write the failing tests in `tests/test_web_mobile_shell.py`**

Reuse `_client`, `demo_doc_hub`, `_main` from `tests/test_web_ui.py` (import them) and `web_client`, `web_client_logged_in` from `tests/conftest.py`.

```python
def test_viewport_meta_allows_cover_and_zoom(demo_doc_hub):
    text = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui").text
    assert 'content="width=device-width, initial-scale=1, viewport-fit=cover"' in text
    assert "user-scalable" not in text and "maximum-scale" not in text

def test_tab_bar_lists_five_main_menus_in_order(demo_doc_hub):
    hrefs = re.findall(r'href="([^"]+)"', _slice(get("/ui"), '<nav class="tab-bar"', "</nav>"))
    assert hrefs == ["/ui", "/ui/docs", "/ui/tickets", "/ui/code", "/ui/questions"]

@pytest.mark.parametrize("path,active", [
    ("/ui", "/ui"), ("/ui/docs", "/ui/docs"), ("/ui/tickets", "/ui/tickets"),
    ("/ui/code", "/ui/code"), ("/ui/questions", "/ui/questions"),
    ("/ui/docs/demo-doc/1.1?repo=demo-kb", "/ui/docs"),
])
def test_tab_bar_marks_active_menu(demo_doc_hub, path, active):
    bar = _slice(get(path), '<nav class="tab-bar"', "</nav>")
    assert re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', bar) == [active]

def test_new_shell_markup_sits_outside_main(demo_doc_hub):
    text = get("/ui/docs/demo-doc/1.1?repo=demo-kb")
    main = _main_span(text)  # (start, end) of <main class="content">…</main>
    for marker in ['<nav class="tab-bar"', 'class="sheet-pills"', 'id="more"', 'id="sheet-scrim"']:
        assert not (main[0] <= text.index(marker) < main[1])

@pytest.mark.parametrize("path,label", [
    ("/ui", "Store health"), ("/ui?q=airspace", "Filters"),
    ("/ui/docs/demo-doc?repo=demo-kb", "Coverage"),
    ("/ui/docs/demo-doc/1.1?repo=demo-kb", "On this page"),
])
def test_right_rail_pill_label_per_page(demo_doc_hub, path, label):
    assert re.search(rf'data-sheet-open="rail-right"[^>]*>\s*{re.escape(label)}\s*<', get(path))

def test_no_right_rail_pill_when_rail_block_is_empty(demo_doc_hub):
    assert 'data-sheet-open="rail-right"' not in get("/ui/docs")

def test_left_rail_pill_is_sections_on_reader_and_tags_elsewhere(demo_doc_hub):
    assert re.search(r'data-sheet-open="rail-left"[^>]*>\s*Sections · 1\s*<', get("/ui/docs/demo-doc/1.1?repo=demo-kb"))
    assert re.search(r'data-sheet-open="rail-left"[^>]*>\s*Tags\s*<', get("/ui/docs"))

def test_sheet_triggers_are_buttons_bound_to_existing_ids(demo_doc_hub):
    text = get("/ui/docs/demo-doc/1.1?repo=demo-kb")
    triggers = re.findall(r"<button[^>]*data-sheet-open=\"([^\"]+)\"[^>]*>", text)
    assert set(triggers) == {"rail-left", "rail-right", "more"}
    for tag in re.findall(r"<button[^>]*data-sheet-open=[^>]*>", text):
        assert 'type="button"' in tag and 'aria-expanded="false"' in tag
        target = re.search(r'aria-controls="([^"]+)"', tag).group(1)
        assert f'id="{target}"' in text

def test_rail_tags_keep_their_opening(demo_doc_hub):
    text = get("/ui/docs/demo-doc/1.1?repo=demo-kb")
    assert '<aside class="rail rail-left" id="rail-left"' in text
    assert '<aside class="rail rail-right" id="rail-right"' in text

def test_more_sheet_prints_chip_titles_as_text(demo_doc_hub):
    # fed_hub is a git repo, so the commit chip renders with title "hub HEAD <sha> · <date>"
    more = _slice(get("/ui"), 'id="more"', "</form>")
    assert re.search(r'class="chip-detail">\s*hub HEAD ', more)
    assert 'action="/ui/logout"' in more

def test_more_sheet_registry_link_only_for_admin(web_client, web_client_logged_in):
    more = _slice(web_client_logged_in.get("/ui").text, 'id="more"', "</form>")
    assert 'href="/ui/registry"' in more

def test_noscript_fallback_hides_sheet_controls(demo_doc_hub):
    text = get("/ui")
    block = _slice(text, "<noscript><style>", "</style></noscript>")
    assert ".sheet-pill" in block and ".topbar-btn" in block
```

(`get(path)` = `_client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(path).text`; `_slice(text, start, end)` = text from the first `start` to the next `end`, as `_left_rail` does.)

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest tests/test_web_mobile_shell.py -q`
Expected: FAIL (no `tab-bar`, no `viewport-fit`, …).

- [ ] **Step 3: Implement the markup and the hide-by-default CSS per the Interfaces block**

The tab bar's active rule copies `left_rail.html`: `menu = shell.tree_doc.kind if shell.tree_doc else shell.menu_kind`; Overview active when `shell.screen == 'overview'`, Q&A when `shell.screen.startswith('questions')`, Docs/Tickets/Code when `menu` is `kb`/`ba`/`dev`. Each tab: inline SVG icon (`aria-hidden="true"`) + text label. The desktop top bar's chips switch to `status_chips(shell)` (non-verbose output must equal today's chip markup byte for byte).

- [ ] **Step 4: Run the new and the existing web tests**

Run: `.venv/bin/pytest tests/test_web_mobile_shell.py tests/test_web_ui.py tests/test_web_accounts_login.py tests/test_web_registry.py tests/test_web_plans.py tests/test_web_questions.py -q`
Expected: all PASS. Then `node scripts/mobile_ui_check.cjs http://127.0.0.1:8765 .ui-check --only desktop-unchanged` (restart the demo server first): exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/web tests/test_web_mobile_shell.py
git commit -m "feat: add mobile shell markup (tab bar, sheets, pills)"
```

---

### Task 3: Compact top bar and bottom tab bar

**Files:**
- Modify: `src/strata_kb/templates/web/static/style.css`
- Modify: `src/strata_kb/templates/web/static/app.js`
- Modify: `scripts/mobile_ui_check.cjs` (add assertions to `overflow` run)

**Interfaces:**
- Consumes: Task 2 DOM contract (`.topbar-btn`, `[data-search-toggle]`, `.hub-dot`, `.tab-bar`, `.topbar-status`, `.nav-logout`).
- Produces: `.topbar[data-searching]` state set/cleared by `app.js`; CSS var `--tabbar-h: 56px` used by Task 4 for sheet bottom offset.

- [ ] **Step 1: Add failing harness assertions**

In the `overflow` run, for widths < 1280: `.topbar-status` and `.nav-logout` not visible, `[data-sheet-open="more"]` visible, `.topbar-search input` ≥ 160px wide (900–1279) ; for widths < 900: `.tab-bar` visible with 5 links each ≥ 44px tall, `.topbar-search` hidden until `[data-search-toggle]` click, then visible, focused (`document.activeElement` is the input) and ≥ 80% of the viewport wide; the last element of `main` is not covered by `.tab-bar` after scrolling to the bottom (its bottom ≤ tab bar top).

- [ ] **Step 2: Run to see it fail**

Run: `node scripts/mobile_ui_check.cjs http://127.0.0.1:8765 .ui-check --only overflow`
Expected: FAIL lines for the new assertions.

- [ ] **Step 3: Implement**

CSS under `max-width: 1279px`: hide `.topbar-status`, `.nav-logout`; show `.topbar-btn[data-sheet-open="more"]`, `.hub-dot`; top bar gap/padding tightened. Under `min-width: 900px`: hide `.more-nav` (the visible left rail already has Registry and Sign in). Under `max-width: 899px`: show `.tab-bar` (`position: fixed; inset: auto 0 0; height: calc(var(--tabbar-h) + env(safe-area-inset-bottom))`), `main.content` `padding-bottom: calc(var(--tabbar-h) + env(safe-area-inset-bottom) + 24px)`, hide `.topbar-search` unless `.topbar[data-searching]` (then brand and buttons hidden, form full width with Cancel). Top bar `padding-top: env(safe-area-inset-top)` and side padding `max(16px, env(safe-area-inset-left|right))`.
JS: click on `[data-search-toggle]` toggles `data-searching` on `.topbar`; when set, focus `#global-search`; Esc clears it. The `⌘K` handler keeps working and also sets `data-searching` below 900px.

- [ ] **Step 4: Verify**

Run: `node scripts/mobile_ui_check.cjs http://127.0.0.1:8765 .ui-check --only overflow` → the top-bar / tab-bar assertions pass (table overflow FAILs from Task 1 may remain until Task 5). `--only desktop-unchanged` → exit 0. `.venv/bin/pytest tests/test_web_mobile_shell.py tests/test_web_ui.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/web/static scripts/mobile_ui_check.cjs
git commit -m "feat: compact top bar and bottom tab bar on small screens"
```

---

### Task 4: Bottom sheets (rails, More) and no-JS fallback

**Files:**
- Modify: `src/strata_kb/templates/web/static/style.css`
- Modify: `src/strata_kb/templates/web/static/app.js`
- Modify: `src/strata_kb/templates/web/base.html` (fill the `<noscript><style>` block)
- Modify: `scripts/mobile_ui_check.cjs` (checks `sheets`, `resize-closes-sheet`, `bfcache-no-sheet`, `nojs`, `sheet-scrolls-inside`)

**Interfaces:**
- Consumes: Task 2 DOM contract; Task 3 `--tabbar-h`.
- Produces: `app.js` functions `openSheet(id, trigger)` and `closeSheet()`; open state = `data-open` on the sheet element, `aria-expanded="true"` on the trigger, `html.sheet-locked` (overflow hidden), `#sheet-scrim` un-hidden.

- [ ] **Step 1: Add the failing harness checks**

- `sheets` (402×874 and 1180×820): for each visible `[data-sheet-open]`: click → target has `data-open`, trigger `aria-expanded="true"`, focus inside target, `html` has `sheet-locked`, target height ≤ 0.8 × innerHeight; then close via each of scrim click, Esc, the sheet's `[data-sheet-close]` button → closed, focus back on trigger. On the section page, clicking a TOC link inside the right-rail sheet closes it and `location.hash` changes. At 402: `.rail-left .nav` is not visible inside the open left sheet (tabs + More replace it).
- `resize-closes-sheet`: at 402×874 open the left sheet, `setViewportSize(1366×1024)` → no `[data-open]`, no `sheet-locked`, `.rail-left` and `.rail-right` visible as columns.
- `bfcache-no-sheet`: at 402×874 open the left sheet on the section page, click a tree row, `goBack()` → no `[data-open]`, no `sheet-locked`.
- `nojs` (new context `javaScriptEnabled: false`, 402×874): `.tab-bar` links visible; `.rail-left .tree-list` (section page) and `.rail-right` content visible in normal flow (not fixed); `.sheet-pill` and `.topbar-btn` hidden; topbar search input visible; no horizontal overflow.
- `sheet-scrolls-inside` (402×874, 60-tag / 40-section doc): open left sheet; sheet `scrollHeight > clientHeight`; `window.scrollY` unchanged after `mouse.wheel` over the sheet.

- [ ] **Step 2: Run to see them fail**

Run: `node scripts/mobile_ui_check.cjs http://127.0.0.1:8765 .ui-check --only sheets` (and each other new check)
Expected: FAIL.

- [ ] **Step 3: Implement CSS**

One `.sheet` look for `.rail-left` (< 900), `.rail-right` (< 1280) and `.more-sheet` (< 1280): `position: fixed; left: 0; right: 0; bottom: 0; max-height: 80vh; max-height: 80dvh; overflow-y: auto; overscroll-behavior: contain; border-radius: 18px 18px 0 0; transform: translateY(102%); transition: transform .2s ease; z-index: 40`; `[data-open]` → `transform: none`; at `min-width: 600px` `max-width: 640px; margin-inline: auto`. Grab handle via `::before`; a close `<button data-sheet-close>` is added by JS at open time if absent (keeps the rail markup untouched). `.sheet-scrim` fixed full-screen, `z-index: 35`. Hide `.rail-left .nav` and `.rail-left .legend`'s top margin auto in sheet mode. Show `.sheet-pill[data-sheet-open="rail-left"]` only < 900, `…="rail-right"` only < 1280. Remove the two old `display: none` rules for the rails. `prefers-reduced-motion: reduce` → `transition: none`. Keep both `grid-template-columns: 288px…` literals.

- [ ] **Step 4: Implement JS in `app.js`**

`openSheet(id, trigger)`: closes any open sheet, sets state per Interfaces, remembers trigger, moves focus to the sheet's first focusable, traps Tab inside. `closeSheet()`: reverses it, restores focus. Wire: click `[data-sheet-open]`, click `[data-sheet-close]` / `#sheet-scrim`, `keydown` Esc, click on any `a[href^="#"]` inside an open sheet (close, then let the browser scroll), swipe-down on the sheet top 32px (pointer events; close when dy > 80px), `matchMedia("(min-width: 900px)")` and `("(min-width: 1280px)")` `change` → `closeSheet()`, `pageshow` → `closeSheet()`. Existing `data-filter-list` and tree-chapter code stays as is.

- [ ] **Step 5: Implement the no-JS `<noscript><style>` rules**

At < 1280px: `.rail-left, .rail-right, .more-sheet` become `position: static; transform: none; max-height: none; display: flex` in normal flow (left rail above `.main-col` content in DOM order already; right rail after); `.sheet-pill, .topbar-btn, .sheet-scrim { display: none }`; `.topbar-search { display: block }`.

- [ ] **Step 6: Verify**

Run each new harness check → exit 0; `--only desktop-unchanged` → exit 0; `.venv/bin/pytest tests/test_web_mobile_shell.py tests/test_web_ui.py -q` → PASS.

- [ ] **Step 7: Commit**

```bash
git add src/strata_kb/templates/web scripts/mobile_ui_check.cjs
git commit -m "feat: rails and More menu as bottom sheets on small screens"
```

---

### Task 5: Tables to cards, forms and per-page fixes

**Files:**
- Modify: `src/strata_kb/templates/web/doc.html`, `plan_mission.html`, `registry.html` (add `data-cards="sections|stories|registry"` on each `.sec-table` wrapper, and per-cell classes where a cell has none)
- Modify: `src/strata_kb/templates/web/static/style.css`
- Modify: `scripts/mobile_ui_check.cjs` (registry page via admin login, if the demo server can seed an admin; else assert on a static render)
- Test: `tests/test_web_mobile_shell.py`

**Interfaces:**
- Consumes: Task 4's sheet CSS (no conflict: only `main` content changes here).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing pytest + harness checks**

```python
def test_tables_carry_card_markers(demo_doc_hub):
    assert 'class="panel sec-table" data-cards="sections"' in get("/ui/docs/demo-doc?repo=demo-kb")
```
Plus one each for `data-cards="stories"` (reuse a `tests/test_web_plans.py` mission fixture) and `data-cards="registry"` (reuse `tests/test_web_registry.py`'s admin client). Harness `overflow` must now pass on every page × viewport.

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/pytest tests/test_web_mobile_shell.py -q -k cards` → FAIL; harness `--only overflow` → FAIL on doc / mission / registry pages.

- [ ] **Step 3: Implement**

Under `max-width: 899px`: `[data-cards] .sec-grid.head, [data-cards] .reg-grid.head { display: none }`; rows drop `min-width` and use `grid-template-areas`:
- sections: `"sid status tk" "title title title" "sum sum sum"`;
- stories: `"sid status" "title title" "reason reason" "ticket ticket"`;
- registry: `"repo repo" "kind pin" "auto remove"`.
`.reg-add-grid` → one column; `.reg-confirm` stacks; `.stat-grid` 1 column below 360px; `.reader-body` padding 16px; `.login-card` full width with the 16px gutter (`margin: 4vh 16px 0`); long strings: `overflow-wrap: anywhere` on `.sid`, `.reg-pin`, `.tree-row .label`, `.cite-box code`, `.crumbs`.

- [ ] **Step 4: Verify**

Run: `.venv/bin/pytest tests/test_web_mobile_shell.py tests/test_web_ui.py tests/test_web_registry.py tests/test_web_plans.py -q` → PASS; harness `--only overflow` → exit 0; `--only desktop-unchanged` → exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/web tests/test_web_mobile_shell.py scripts/mobile_ui_check.cjs
git commit -m "feat: stack tables as cards and fit forms on phones"
```

---

### Task 6: Touch sizes, safe areas, viewport height

**Files:**
- Modify: `src/strata_kb/templates/web/static/style.css`
- Modify: `scripts/mobile_ui_check.cjs` (check `touch-targets`)

**Interfaces:**
- Consumes: everything above.
- Produces: final CSS.

- [ ] **Step 1: Add the failing `touch-targets` check**

Contexts with `hasTouch: true, isMobile: true` at 402×874 and `hasTouch: true` at 1366×1024: every visible `.nav a, .tree-row, .chip, .seg, .btn, .level-tabs a, .switch, .pager a, .result-card footer button, .result-card footer a, .tab-bar a, .sheet-pill, .topbar-btn, .toc-link` has a bounding box ≥ 44×44 (`.chip` and `.toc-link`: height ≥ 44, any width); every visible `input, select, textarea` has computed `font-size` ≥ 16px. At 1366×1024 touch, the layout still has three columns (`.rail-right` visible).

- [ ] **Step 2: Run to see it fail**

Run: `node scripts/mobile_ui_check.cjs http://127.0.0.1:8765 .ui-check --only touch-targets` → FAIL.

- [ ] **Step 3: Implement**

`@media (pointer: coarse)`: raise `min-height: 44px` (and `min-width: 44px` where the element is an icon/switch) with padding, not font size; `input, select, textarea { font-size: 16px }`. `.rail { height: calc(100vh - 56px); height: calc(100dvh - 56px) }`. Side gutters on `main.content` below 900px: `padding-left: max(16px, env(safe-area-inset-left))`, `padding-right: max(16px, env(safe-area-inset-right))`.

- [ ] **Step 4: Full verification**

Run: `.venv/bin/pytest -q` → all PASS. `.venv/bin/ruff check scripts/ui_demo_server.py tests/test_web_mobile_shell.py` → clean. `node scripts/mobile_ui_check.cjs http://127.0.0.1:8765 .ui-check` (all checks) → exit 0. Send the owner the screenshots for 344×882, 402×874, 884×1104, 834×1194, 1180×820 of `/ui`, the section page and `/ui?q=airspace`, with one sheet open.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/web/static/style.css scripts/mobile_ui_check.cjs
git commit -m "feat: touch-size targets and safe-area padding"
```
