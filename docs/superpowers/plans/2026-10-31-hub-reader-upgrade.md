# Hub Reader Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The hub renders numbered lists, nested lists, bold, italic and inline code in L2/L3 (never inside tables), and the section page shows a one-line document header.

**Architecture:** `web/mdrender.py` stays a single-pass line renderer. A new inline pass (`_inline`) runs on paragraph, list-item and heading text only; table cells keep `_cell_html` untouched. The flat bullet buffer becomes a small list builder that handles `1.`/`1)` items, 2 nesting levels and continuation lines. `section.html` gets a `doc-line` under the `<h1>` fed by `ui.py` from the manifest it already loads.

**Tech Stack:** Python 3.11+, stdlib `html`/`re`, Jinja2, FastAPI test client, pytest, Playwright UI check script.

**Spec:** `docs/superpowers/specs/2026-10-31-l3-ai-fix-design.md` §6, §8 (Part 1 only).

## Global Constraints

- Tables render character for character: no inline parsing inside a table cell, ever (`README` rule, spec §8.1).
- Text is HTML-escaped before any tag is added; no raw HTML passes through.
- No new dependency.
- No change to `SectionEntry`, `Manifest` or any published file (wire-compat, spec §5). No page number in the doc header.
- Nesting: max 2 list levels; deeper indents render at level 2. A tab counts as 4 spaces.
- `uidata.inject_heading_anchors` must keep working: headings stay attribute-less `<hN>…</hN>` from mdrender.
- The hub has one (light) theme today; style new elements with the existing tokens in `style.css` `:root` and check the `< 900px` breakpoint.
- Run tests with `uv run pytest <path> -q`; lint with `uv run ruff check src tests`.
- Commit messages `<type>: <description>`, ending with:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01RknHEUyRwgKfup5an67w4e`.
- Branch: `claude/optimistic-sagan-nfdfd0`.

## Review Focus

1. Literal asterisks/underscores in real prose (`a * b`, `2*3*4`, `snake_case_name`, `file_v2_final`, a lone `**`) must stay literal — Task 1 tests.
2. A search keyword inside `**bold**` text must still get `<mark>` and never break a tag; inside `` `code` `` text stays exact (no mark) — Task 1 tests.
3. A heading with inline formatting must give a plain-text TOC label and a clean anchor — Task 1 test through `inject_heading_anchors`.
4. A numbered list directly followed by a paragraph line (no blank line) must close the list; a blank line between items must not split one list into two — Task 2 tests.
5. An L3 heading-like line `4.2.1 Thủ tục` (no `#`) and a year line `2026 là năm…` must stay paragraphs, not list items — Task 2 test.

---

## File map

| File | Change |
|---|---|
| `src/strata_kb/web/mdrender.py` | `_inline()`, list builder, docstring "Supported:" line |
| `tests/test_web_mdrender.py` | new cases |
| `src/strata_kb/web/ui.py` (~line 978-1012) | pass `doc_title`, `chapter_label` |
| `src/strata_kb/templates/web/section.html` | `doc-line` under `<h1>` |
| `src/strata_kb/templates/web/static/style.css` (~line 279-297) | `ol`, nested lists, `strong`, `em`, inline `code`, `.doc-line` |
| `tests/test_web_ui.py` (~line 830-865) | doc-line test |
| `CHANGELOG.md`, `pyproject.toml` | 1.33.0 entry and version |

---

### Task 1: Inline formatting

**Files:**
- Modify: `src/strata_kb/web/mdrender.py`
- Modify: `src/strata_kb/templates/web/static/style.css`
- Test: `tests/test_web_mdrender.py`, `tests/test_web_uidata.py` (put `test_heading_inline_and_toc_label` here, next to the existing `inject_heading_anchors` tests)

**Interfaces:**
- Produces: `_inline(text: str, terms: set[str]) -> str` in `mdrender.py` — escapes `text`, applies code/strong/em, highlights `terms` outside code spans. Task 2 calls it for list items.

- [ ] **Step 1: Write the failing tests**

```python
def test_inline_strong_em_code():
    assert render("A **Bảng 4-1** và *HRM* và `5 ngày`.") == (
        "<p>A <strong>Bảng 4-1</strong> và <em>HRM</em> và <code>5 ngày</code>.</p>"
    )
    assert render("_nghiêng_ ok") == "<p><em>nghiêng</em> ok</p>"

def test_inline_literal_cases_stay_literal():
    for text in ["a * b * c", "2*3*4 = 24", "snake_case_name", "file_v2_final.pdf", "lone ** here"]:
        assert render(text) == f"<p>{html.escape(text)}</p>"

def test_inline_code_is_not_parsed_further_and_escaped():
    assert render("`**x** <b>`") == "<p><code>**x** &lt;b&gt;</code></p>"

def test_inline_escape_before_tags():
    assert render("**<script>**") == "<p><strong>&lt;script&gt;</strong></p>"

def test_highlight_inside_strong_not_inside_code():
    out = render("**leave rules** and `leave`", terms={"leave"})
    assert "<strong><mark>leave</mark> rules</strong>" in out
    assert "<code>leave</code>" in out

def test_heading_inline_and_toc_label():
    content, toc = inject_heading_anchors(render("## 4.2 **NGHỈ** PHÉP"))
    assert "<strong>NGHỈ</strong>" in content
    assert toc[0].label == "4.2 NGHỈ PHÉP"

def test_table_cells_never_inline_parsed():
    out = render("| a | b |\n|---|---|\n| **x** | `y` |")
    assert "<td>**x**</td><td>`y`</td>" in out
```

(`import html` and `from strata_kb.web.uidata import inject_heading_anchors` at the top.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_web_mdrender.py -q`
Expected: the new tests FAIL (raw `**`, `` ` `` in output), old ones PASS.

- [ ] **Step 3: Implement `_inline(text, terms)` and use it for paragraphs and headings**

Order: split on `` `…` `` spans first (content → `html.escape`, no highlight); on the remaining pieces apply `**x**` then `*x*`/`_x_`. Every delimiter must hug non-space text and sit at a word boundary on its outer side, for `*` as well as `_` (shape: `(?<![\w*])\*(\S|\S.*?\S)\*(?![\w*])`), so `2*3*4`, `snake_case_name` and `a * b` stay literal; escape and highlight the text parts via the existing `_highlight`. Unmatched delimiters stay literal. Replace `_highlight(...)` with `_inline(...)` in `flush_para` and the heading branch only; `_cell_html` is unchanged. Update the module docstring's "Supported:" sentence.

- [ ] **Step 4: Add CSS**

In `style.css` after `.reader-body li + li`: `.reader-body code` (mono font, `var(--field)` background, 1px 5px padding, small radius; not applied to `pre code`, which keeps `font: inherit`), `.reader-body strong { font-weight: 600; color: var(--ink) }`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_web_mdrender.py tests/test_web_uidata.py tests/test_web_ui.py -q && uv run ruff check src tests`
Expected: all PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/web/mdrender.py src/strata_kb/templates/web/static/style.css tests/test_web_mdrender.py tests/test_web_uidata.py
git commit -m "feat: render bold, italic and inline code in hub reader"
```

---

### Task 2: Numbered and nested lists

**Files:**
- Modify: `src/strata_kb/web/mdrender.py`
- Modify: `src/strata_kb/templates/web/static/style.css`
- Test: `tests/test_web_mdrender.py`

**Interfaces:**
- Consumes: `_inline(text, terms)` from Task 1 for item text.
- Produces: nothing new outside the module; `render()` signature unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_ordered_list():
    assert render("1. Gửi đơn\n2) Duyệt") == "<ol><li>Gửi đơn</li><li>Duyệt</li></ol>"

def test_nested_mixed_list():
    md = "1. Gửi đơn\n2. Duyệt\n   - Vắng mặt\n   - Quá hạn\n3. Cập nhật"
    assert render(md) == (
        "<ol><li>Gửi đơn</li><li>Duyệt<ul><li>Vắng mặt</li><li>Quá hạn</li></ul></li>"
        "<li>Cập nhật</li></ol>"
    )

def test_deeper_indent_clamps_to_level_two():
    out = render("- a\n  - b\n    - c")
    assert out == "<ul><li>a<ul><li>b</li><li>c</li></ul></li></ul>"

def test_tab_indent_counts_as_four_spaces():
    assert render("- a\n\t- b") == "<ul><li>a<ul><li>b</li></ul></li></ul>"

def test_continuation_line_joins_item():
    assert render("1. Gửi đơn trên\n   hệ thống HRM") == "<ol><li>Gửi đơn trên hệ thống HRM</li></ol>"

def test_paragraph_line_closes_list_blank_line_does_not():
    assert render("1. a\n\n2. b\nĐoạn văn") == "<ol><li>a</li><li>b</li></ol>\n<p>Đoạn văn</p>"

def test_numbered_headings_and_years_are_not_list_items():
    assert render("4.2.1 Thủ tục") == "<p>4.2.1 Thủ tục</p>"
    assert render("2026 là năm") == "<p>2026 là năm</p>"

def test_list_item_inline_formatting():
    assert render("- **x** và `y`") == "<ul><li><strong>x</strong> và <code>y</code></li></ul>"
```

Keep the existing bullet tests green; if one asserts the old flat output for an indented line, update it and say so in the commit body.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_web_mdrender.py -q`
Expected: new list tests FAIL.

- [ ] **Step 3: Implement the list builder in `render()`**

Item regex `^(?P<indent>[ \t]*)(?P<marker>[-*]|\d+[.)])[ \t]+(?P<text>.*)$` (tabs expanded to 4 spaces before measuring). Level = 1 at the first item's indent, 2 when indent ≥ parent indent + 2, anything deeper stays 2. A non-blank, non-item line indented ≥ 2 spaces while a list is open joins the last item's text with one space; an unindented one closes the list and starts a paragraph. Build nested `<ul>`/`<ol>` inside the parent `<li>` as in the tests; a level-2 marker type change opens a new nested list. Replace `bullets`/`flush_list` with this builder; fences, tables, images and headings still close the list first.

- [ ] **Step 4: Add CSS**

`.reader-body ol` same margins/padding as `ul`; `.reader-body li > ul, .reader-body li > ol { margin: 4px 0 0 }`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_web_mdrender.py tests/test_web_ui.py -q && uv run ruff check src tests`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/web/mdrender.py src/strata_kb/templates/web/static/style.css tests/test_web_mdrender.py
git commit -m "feat: render numbered and nested lists in hub reader"
```

---

### Task 3: Document header line, UI check, release

**Files:**
- Modify: `src/strata_kb/web/ui.py` (section route, ~line 978-1012)
- Modify: `src/strata_kb/templates/web/section.html`
- Modify: `src/strata_kb/templates/web/static/style.css`
- Modify: `CHANGELOG.md`, `pyproject.toml`
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `manifest` already loaded in the section route via `api.load_manifest`.
- Produces: template vars `doc_title: str` (manifest title, `""` when manifest missing) and `chapter_label: str` (`entry.file.replace("-", " ")`, same label the left-rail tree uses in `uidata.py:238`; `""` when no entry). Separator is ` · ` (space, U+00B7, space).

- [ ] **Step 1: Write the failing test** (next to `test_section_page_l3`)

```python
def test_section_page_shows_doc_line(demo_doc_hub):
    manifest_path = demo_doc_hub / "federation" / "demo-kb" / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.revision = "Rev 7"
    models.save_yaml_model(manifest_path, manifest)
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"level": "l3", "repo": "demo-kb"}
    )
    assert '<p class="doc-line">Demo Document · Rev 7 · ch1</p>' in resp.text

def test_section_page_doc_line_without_revision(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}
    )
    assert '<p class="doc-line">Demo Document · ch1</p>' in resp.text
```

(Same pattern as `test_section_page_rail_shows_revision_when_set`; the fixture writes `file="ch1"`, revision `""`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_web_ui.py -q -k doc_line`
Expected: FAIL.

- [ ] **Step 3: Implement**

`ui.py`: set `doc_title = manifest.title` and `chapter_label` in the `found is not None` branch, defaults `""`; pass both to `_render_page`. `section.html`: right after the `<h1>`, `{% if doc_title %}<p class="doc-line">{{ doc_title }}{% if revision %} · {{ revision }}{% endif %}{% if chapter_label %} · {{ chapter_label }}{% endif %}</p>{% endif %}` (Jinja autoescape stays on). CSS: `.doc-line { margin: 0; font: 400 12px/1.5 var(--mono); color: var(--muted); }` with `overflow-wrap: anywhere` in the `< 900px` block next to `.crumbs`.

- [ ] **Step 4: Run the full web suite**

Run: `uv run pytest tests/test_web_mdrender.py tests/test_web_ui.py tests/test_web_uidata.py -q && uv run ruff check src tests`
Expected: all PASS.

- [ ] **Step 5: UI check**

Run `uv run python scripts/ui_demo_server.py` (background; read its `--help` for the port), then `node scripts/mobile_ui_check.cjs <base_url> .ui-check` (add `--login user:password` if the demo server prints one).
Expected: no overflow failures. If only the desktop pixel-compare differs on section pages because of the doc line or new list/inline rendering, re-run with `--baseline`, and list the regenerated baselines in the commit body. Any other failure: stop and fix.

- [ ] **Step 6: Release notes and version**

`pyproject.toml` version `1.33.0`; `CHANGELOG.md` new top entry `## 1.33.0 — <date>`: hub reader renders numbered and nested lists, bold, italic and inline code in L2/L3 (tables unchanged, character for character); section page shows document title · revision · chapter; **Upgrade.** hub only, no config, CLI or `kb init` change. Run `uv lock` only if the repo's release commits update `uv.lock` for the version (check `git log -p -1 8335bb4 -- uv.lock`).

- [ ] **Step 7: Commit**

```bash
git add src/strata_kb/web/ui.py src/strata_kb/templates/web/section.html src/strata_kb/templates/web/static/style.css tests/test_web_ui.py CHANGELOG.md pyproject.toml
git commit -m "feat: section page doc line; release 1.33.0"
```
