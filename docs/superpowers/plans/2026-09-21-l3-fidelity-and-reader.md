# L3 Fidelity and Hub Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** L3 markdown keeps code blocks, bullet lists and figure text from the source PDF with correct line breaks and Vietnamese diacritics, and the hub renders it at IDE markdown-preview quality with a pager above and below the article.

**Architecture:** A new `ingest/pdftext.py` reads a PDF region's text layer with pypdfium2 (already a direct dependency) and, for monospace regions, rebuilds a character grid from per-character boxes. `ingest/parser.py` routes docling `code` and `list_item` labels through it into fenced/bulleted markdown, and folds text drawn inside a `picture` into that picture's alt text instead of emitting loose paragraphs. `web/mdrender.py` learns fences and lists; `section.html` and `style.css` get the reader styling and a second pager.

**Tech Stack:** Python 3.11+, pypdfium2 (`get_textpage`, `get_text_bounded`, `get_charbox(i, loose=True)`), docling item labels, Jinja2 templates, pytest. Spec: `docs/superpowers/specs/2026-09-21-l3-fidelity-and-reader-design.md`.

## Global Constraints

- No new runtime dependency. pypdfium2 is pinned in `pyproject.toml` as `pypdfium2>=4.30,<6`.
- L3 is markdown; no page crops, no shipped PDF, no new `SectionEntry` field.
- Tables keep rendering character-for-character in `mdrender`.
- Every PDF-text failure logs one `logger.warning` and falls back; ingest never aborts.
- Run tests with `uv run pytest <path> -q`. Repo uses `uv sync --all-extras`.
- Commit messages: `<type>: <description>`, ending with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Work on branch `feat/l3-fidelity` (already created, spec committed on it).

---

## File map

| File | Responsibility |
|---|---|
| Create `src/strata_kb/ingest/pdftext.py` | `region_text(pdf_path, page_no, box, mono)`: text layer of one PDF region, flow or monospace grid. |
| Create `tests/fixtures/mono-diagram.pdf` | One-page monospace fixture with Vietnamese diacritics (generated once, committed). |
| Create `tests/test_pdftext.py` | Grid and flow assertions on the fixture, failure fallbacks. |
| Modify `src/strata_kb/ingest/parser.py` | Tab normalisation, `code` → fence, `list_item` → bullet, picture children → alt. |
| Modify `src/strata_kb/ingest/sectioner.py:15` | `DocItem.kind` comment lists the two new kinds. |
| Modify `tests/test_parser.py` | New cases; one existing case updated. |
| Modify `src/strata_kb/web/mdrender.py` | Fenced code and list rendering. |
| Modify `tests/test_web_mdrender.py` | Fence and list cases. |
| Create `src/strata_kb/templates/web/_partials/pager.html` | Pager macro. |
| Modify `src/strata_kb/templates/web/section.html` | Pager above tabs and below article. |
| Modify `src/strata_kb/templates/web/static/style.css` | Reader `pre`, `ul`, headings, `img`. |
| Modify `tests/test_web_ui.py` | Pager appears twice. |
| Modify `CHANGELOG.md` | Unreleased entry. |

---

### Task 1: `pdftext.region_text` with fixture

**Files:**
- Create: `src/strata_kb/ingest/pdftext.py`
- Create: `tests/fixtures/mono-diagram.pdf`
- Test: `tests/test_pdftext.py`

**Interfaces:**
- Produces: `region_text(pdf_path: Path | None, page_no: int | None, box: tuple[float, float, float, float] | None, mono: bool) -> str | None`. `box` is `(left, top, right, bottom)` in PDF points, BOTTOMLEFT origin (docling `prov[0].bbox` fields `l, t, r, b` as-is). Returns `None` on any failure or when nothing is found.

- [ ] **Step 1: Generate the fixture PDF once**

Run from the repo root (xhtml2pdf comes from the `docs` extra):

```bash
mkdir -p tests/fixtures
uv run --extra docs python - <<'EOF'
from xhtml2pdf import pisa
font = "/System/Library/Fonts/Supplemental/Courier New.ttf"
html = f"""<html><head><style>
@font-face {{ font-family: Mono; src: url("{font}"); }}
@page {{ size: a4 portrait; margin: 20mm; }}
pre {{ font-family: Mono; font-size: 10pt; }}
</style></head><body>
<pre>+------+    +------+
| Nền  |    | gốc  |
+------+    +------+</pre>
</body></html>"""
with open("tests/fixtures/mono-diagram.pdf", "wb") as f:
    pisa.CreatePDF(html, dest=f)
EOF
uv run python - <<'EOF'
import pypdfium2
page = pypdfium2.PdfDocument("tests/fixtures/mono-diagram.pdf")[0]
print(page.get_size())
print(page.get_textpage().get_text_bounded())
EOF
```

Expected: a size like `(595.27..., 841.88...)` and three lines containing `Nền` and `gốc`. If the diacritics print as `?` or separate marks, the font lacks the glyphs: switch `font` to `/System/Library/Fonts/Supplemental/Andale Mono.ttf` and regenerate. If the three lines print on one line, xhtml2pdf collapsed the `<pre>`: replace the inner newlines with `<br/>` and the runs of spaces with `&nbsp;`, regenerate, and re-run the print. Do not change the test expectation in Step 2 to match a broken fixture.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_pdftext.py
from pathlib import Path

import pytest

from strata_kb.ingest import pdftext

FIXTURE = Path(__file__).parent / "fixtures" / "mono-diagram.pdf"


def _page_box() -> tuple[float, float, float, float]:
    pypdfium2 = pytest.importorskip("pypdfium2")
    pdf = pypdfium2.PdfDocument(str(FIXTURE))
    try:
        width, height = pdf[0].get_size()
    finally:
        pdf.close()
    return (0.0, height, width, 0.0)


def test_mono_grid_keeps_columns_and_diacritics():
    out = pdftext.region_text(FIXTURE, 1, _page_box(), mono=True)
    assert out == (
        "+------+    +------+\n"
        "| Nền  |    | gốc  |\n"
        "+------+    +------+"
    )


def test_flow_text_keeps_diacritics_and_lines():
    out = pdftext.region_text(FIXTURE, 1, _page_box(), mono=False)
    assert out is not None
    lines = out.split("\n")
    assert len(lines) == 3
    assert "Nền" in lines[1] and "gốc" in lines[1]


def test_region_without_text_returns_none():
    # a 1pt sliver in the page corner holds no glyph centres
    assert pdftext.region_text(FIXTURE, 1, (0.0, 1.0, 1.0, 0.0), mono=True) is None
    assert pdftext.region_text(FIXTURE, 1, (0.0, 1.0, 1.0, 0.0), mono=False) is None


def test_missing_inputs_return_none():
    assert pdftext.region_text(None, 1, (0, 10, 10, 0), mono=True) is None
    assert pdftext.region_text(FIXTURE, None, (0, 10, 10, 0), mono=True) is None
    assert pdftext.region_text(FIXTURE, 1, None, mono=True) is None


def test_unreadable_pdf_returns_none_and_warns(tmp_path, caplog):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with caplog.at_level("WARNING", logger="strata_kb.ingest.pdftext"):
        assert pdftext.region_text(bad, 1, (0, 10, 10, 0), mono=True) is None
    assert "pdf text for page 1 skipped" in caplog.text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_pdftext.py -q`
Expected: `ImportError` / `ModuleNotFoundError: No module named 'strata_kb.ingest.pdftext'`.

- [ ] **Step 4: Implement `pdftext.py`**

```python
# src/strata_kb/ingest/pdftext.py
"""Text of one PDF region from its text layer, via pypdfium2.

docling flattens `code` items (line breaks become spaces, words joined by
tabs) and splits Vietnamese glyphs drawn with a fallback monospace font
into separate cells (`g ố c`). The PDF text layer has both right; this
module reads it back for a docling-provided bbox.

`mono=True` rebuilds a character grid from per-character advance boxes so
box-drawing diagrams keep their columns. Two monospace fonts on one line
(DejaVu Sans Mono + FreeMono fallback) differ by ~3 % in advance width,
so columns are placed by rounding each char's delta from its predecessor
rather than its absolute offset: no accumulated drift, no two glyphs in
one cell.
"""
from __future__ import annotations

import logging
import statistics
from pathlib import Path

logger = logging.getLogger("strata_kb.ingest.pdftext")

Box = tuple[float, float, float, float]  # (left, top, right, bottom), BOTTOMLEFT, points


def region_text(
    pdf_path: Path | None, page_no: int | None, box: Box | None, mono: bool
) -> str | None:
    """Text inside `box` on page `page_no` (1-based); None when unavailable."""
    if pdf_path is None or page_no is None or box is None:
        return None
    try:
        import pypdfium2

        # ponytail: reopens the document per region; cache the PdfDocument
        # per ingest if a code-heavy PDF makes this measurably slow.
        pdf = pypdfium2.PdfDocument(str(pdf_path))
        try:
            textpage = pdf[page_no - 1].get_textpage()
            try:
                text = _mono_grid(textpage, box) if mono else _flow(textpage, box)
            finally:
                textpage.close()
        finally:
            pdf.close()
    except Exception as exc:  # noqa: BLE001 -- text layer is best-effort; caller keeps docling's text
        logger.warning("pdf text for page %s skipped: %s", page_no, exc)
        return None
    return text or None


def _flow(textpage, box: Box) -> str:
    left, top, right, bottom = box
    raw = textpage.get_text_bounded(left=left, bottom=bottom, right=right, top=top)
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = (" ".join(line.split()) for line in raw.split("\n"))
    return "\n".join(line for line in lines if line)


def _mono_grid(textpage, box: Box) -> str:
    left, top, right, bottom = box
    chars: list[tuple[float, float, float, float, str]] = []  # (cy, left, width, height, ch)
    for i in range(textpage.count_chars()):
        ch = textpage.get_text_range(i, 1)
        if not ch or ch.isspace():
            continue
        l, b, r, t = textpage.get_charbox(i, loose=True)  # noqa: E741 -- pypdfium2 order
        cx, cy = (l + r) / 2, (b + t) / 2
        if left <= cx <= right and bottom <= cy <= top:
            chars.append((cy, l, r - l, t - b, ch))
    if not chars:
        return ""
    cell = statistics.median(c[2] for c in chars)
    if cell <= 0:
        return ""
    row_tol = statistics.median(c[3] for c in chars) / 2
    min_left = min(c[1] for c in chars)

    rows: list[tuple[float, list]] = []
    for c in sorted(chars, key=lambda c: -c[0]):  # PDF y grows upward: top row first
        if rows and abs(rows[-1][0] - c[0]) <= row_tol:
            rows[-1][1].append(c)
        else:
            rows.append((c[0], [c]))

    out: list[str] = []
    for _cy, row in rows:
        line: list[str] = []
        col = -1
        prev_left = None
        for _cy2, l, _w, _h, ch in sorted(row, key=lambda c: c[1]):  # noqa: E741
            if prev_left is None:
                col = round((l - min_left) / cell)
            else:
                col += max(1, round((l - prev_left) / cell))
            prev_left = l
            line.extend(" " * (col - len(line)))
            line.append(ch)
        out.append("".join(line).rstrip())
    return "\n".join(out)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_pdftext.py -q`
Expected: `5 passed`.

If `test_mono_grid_keeps_columns_and_diacritics` fails only on the count of spaces between the two boxes, print the actual output; if it is off by exactly one column, the fixture's `<pre>` rendered with a proportional gap. Regenerate the fixture per Step 1's `&nbsp;` note. The algorithm is validated on real docling output (see spec); do not loosen the assertion.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/ingest/pdftext.py tests/test_pdftext.py tests/fixtures/mono-diagram.pdf
git commit -m "feat(ingest): read PDF region text via pypdfium2 with monospace grid rebuild

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Parser emits code fences, bullets, and space-separated text

**Files:**
- Modify: `src/strata_kb/ingest/parser.py:135-180` (`doc_to_items`) and add helpers after `_prov_box`
- Modify: `src/strata_kb/ingest/sectioner.py:15`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: `pdftext.region_text` (Task 1).
- Produces: `DocItem(kind="code", text="```\n...\n```")` and `DocItem(kind="list", text="- ...")`; `parser._clean(text) -> str`; `parser._bottomleft_box(item, doc) -> tuple[int | None, pdftext.Box | None]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_parser.py`)

```python
def test_doc_to_items_collapses_tabs_between_words():
    doc = _StubDoc(items=[_StubItem(_StubLabel("text"), text="Hệ\tthống\tkhông\tcó")])
    items = parser.doc_to_items(doc)
    assert items[0].text == "Hệ thống không có"


def test_doc_to_items_code_uses_pdf_text_layer(monkeypatch, tmp_path):
    seen = {}

    def fake_region_text(pdf_path, page_no, box, mono):
        seen.update(pdf_path=pdf_path, page_no=page_no, box=box, mono=mono)
        return "line one\n  line two"

    monkeypatch.setattr(parser.pdftext, "region_text", fake_region_text)
    doc = _StubDoc(
        items=[
            _StubItem(
                _StubLabel("code"),
                text="line\tone line\ttwo",
                prov=[_StubProv(page_no=3, bbox=_StubBBox(l=10, t=100, r=200, b=50))],
            )
        ],
        pages={3: _StubPage()},
    )
    items = parser.doc_to_items(doc, pdf_path=tmp_path / "doc.pdf")
    assert [i.kind for i in items] == ["code"]
    assert items[0].text == "```\nline one\n  line two\n```"
    assert items[0].page == 3
    assert seen == {
        "pdf_path": tmp_path / "doc.pdf", "page_no": 3, "box": (10, 100, 200, 50), "mono": True,
    }


def test_doc_to_items_code_falls_back_to_docling_text(monkeypatch):
    monkeypatch.setattr(parser.pdftext, "region_text", lambda *a, **k: None)
    doc = _StubDoc(items=[_StubItem(_StubLabel("code"), text="SELECT\t1;\tCOMMIT;")])
    items = parser.doc_to_items(doc)
    assert items[0].kind == "code"
    assert items[0].text == "```\nSELECT 1; COMMIT;\n```"


def test_doc_to_items_empty_code_is_dropped(monkeypatch):
    monkeypatch.setattr(parser.pdftext, "region_text", lambda *a, **k: None)
    doc = _StubDoc(items=[_StubItem(_StubLabel("code"), text="  \t ")])
    assert parser.doc_to_items(doc) == []


def test_doc_to_items_list_item_becomes_bullet():
    doc = _StubDoc(
        items=[
            _StubItem(_StubLabel("list_item"), text="•\tXác\tthực\tuser"),
            _StubItem(_StubLabel("list_item"), text=" Kiểm tra asset"),
            _StubItem(_StubLabel("list_item"), text="- đã có gạch"),
        ]
    )
    items = parser.doc_to_items(doc)
    assert [i.kind for i in items] == ["list", "list", "list"]
    assert [i.text for i in items] == ["- Xác thực user", "- Kiểm tra asset", "- đã có gạch"]


def test_bottomleft_box_flips_topleft_provenance():
    item = _StubItem(
        _StubLabel("text"),
        prov=[_StubProv(page_no=1, bbox=_StubBBox(l=10, t=100, r=200, b=120, coord_origin="TOPLEFT"))],
    )
    doc = _StubDoc(pages={1: _StubPage()})  # height 792
    assert parser._bottomleft_box(item, doc) == (1, (10, 692, 200, 672))


def test_bottomleft_box_passes_bottomleft_through():
    item = _StubItem(
        _StubLabel("text"),
        prov=[_StubProv(page_no=2, bbox=_StubBBox(l=1, t=9, r=5, b=3))],
    )
    assert parser._bottomleft_box(item, _StubDoc()) == (2, (1, 9, 5, 3))
    assert parser._bottomleft_box(_StubItem(_StubLabel("text")), _StubDoc()) == (None, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_parser.py -q -k "tabs or code or list_item or bottomleft"`
Expected: 7 failures (`AttributeError: module ... has no attribute 'pdftext'`, `kind == 'text'`, `_bottomleft_box` missing).

- [ ] **Step 3: Implement in `parser.py`**

Add the import next to `tableimages`:

```python
from strata_kb.ingest import pdftext, tableimages
```

Add after `_prov_box`:

```python
def _clean(text: str) -> str:
    """docling separates words with tabs; L3 wants single spaces."""
    return " ".join(text.split())


def _bottomleft_box(item, doc) -> tuple[int | None, pdftext.Box | None]:
    """(page, bbox) in the BOTTOMLEFT frame pypdfium2 uses — docling's own
    PDF provenance frame, so normally a pass-through."""
    prov = getattr(item, "prov", None)
    if not prov:
        return None, None
    page = getattr(prov[0], "page_no", None)
    bbox = getattr(prov[0], "bbox", None)
    if bbox is None:
        return page, None
    origin = getattr(bbox, "coord_origin", "")
    origin = str(getattr(origin, "value", origin)).upper()
    if "TOP" in origin:
        height = _page_height(doc, page)
        if height is None:
            return page, None
        return page, (bbox.l, height - bbox.t, bbox.r, height - bbox.b)
    return page, (bbox.l, bbox.t, bbox.r, bbox.b)


_BULLET_CHARS = "-•*·"


def _code_item(item, doc, pdf_path: Path | None, page, bbox) -> DocItem | None:
    # ponytail: a code line that starts with "## " would end the section in
    # mdutils.slice_section; none in the corpus. Indent fence bodies if it appears.
    raw_page, raw_box = _bottomleft_box(item, doc)
    body = pdftext.region_text(pdf_path, raw_page, raw_box, mono=True) or _clean(item.text)
    if not body.strip():
        return None
    return DocItem("code", f"```\n{body}\n```", page=page, bbox=bbox)


def _list_item(item, page, bbox) -> DocItem | None:
    text = _clean(item.text).lstrip(_BULLET_CHARS).strip()
    if not text:
        return None
    return DocItem("list", f"- {text}", page=page, bbox=bbox)
```

In `doc_to_items`, replace the `elif getattr(item, "text", "") ...` tail of the loop with:

```python
        elif label == "code":
            code = _code_item(item, doc, pdf_path, page, bbox)
            if code:
                items.append(code)
        elif label == "list_item":
            bullet = _list_item(item, page, bbox)
            if bullet:
                items.append(bullet)
        elif getattr(item, "text", "") and item.text.strip():
            items.append(DocItem("text", _clean(item.text), page=page, bbox=bbox))
```

Update `sectioner.py:15`:

```python
    kind: str  # "heading" | "text" | "table" | "image" | "code" | "list"
```

- [ ] **Step 4: Run the whole parser and sectioner suites**

Run: `uv run pytest tests/test_parser.py tests/test_sectioner.py tests/test_scaffold.py tests/test_ingest_seam.py -q`
Expected: all pass. `test_doc_to_items_keeps_text_under_an_unlisted_label` and `test_doc_to_items_keeps_footnotes` still pass because unlisted labels still reach the `text` branch.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/ingest/parser.py src/strata_kb/ingest/sectioner.py tests/test_parser.py
git commit -m "feat(ingest): keep code blocks and bullet lists in L3, single-space words

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Text drawn inside a picture becomes its alt text

**Files:**
- Modify: `src/strata_kb/ingest/parser.py` (`doc_to_items`, `_place_glyphs`, `_picture_md`)
- Test: `tests/test_parser.py` (update `test_doc_to_items_extracts_text_drawn_inside_a_picture`, add two)

**Interfaces:**
- Consumes: `pdftext.region_text(..., mono=False)`, `_bottomleft_box`, `_clean` (Tasks 1–2).
- Produces: `_picture_md(item, doc, assets_dir, pdf_path=None, child_text="")`.

- [ ] **Step 1: Update and add tests**

Replace `test_doc_to_items_extracts_text_drawn_inside_a_picture` with:

```python
def test_doc_to_items_folds_text_drawn_inside_a_picture_into_alt(tmp_path, monkeypatch):
    # Docling nests figure labels (axis titles, box-drawing diagrams) under
    # the picture node. They must stay searchable (L3 alt text) but never
    # become loose paragraphs beside the image that already shows them.
    monkeypatch.setattr(parser.pdftext, "region_text", lambda *a, **k: None)
    monkeypatch.setattr(parser.images, "ocr_image", lambda img: "")
    nested = [
        _StubItem(_StubLabel("text"), text="│\t\tViewer\t\t│"),
        _StubItem(_StubLabel("code"), text="10 m minimum"),
    ]
    doc = _StubDoc(
        items=[
            _StubItem(
                _StubLabel("picture"),
                prov=[_StubProv(page_no=9)],
                image=Image.new("RGB", (32, 32), (0, 0, 0)),
                children=nested,
            ),
            _StubItem(_StubLabel("text"), text="After the figure."),
        ]
    )
    items = parser.doc_to_items(doc, assets_dir=tmp_path)
    assert [i.kind for i in items] == ["image", "text"]
    assert items[0].text.startswith("![│ Viewer │ 10 m minimum](assets/")


def test_doc_to_items_picture_alt_prefers_pdf_text_layer(tmp_path, monkeypatch):
    monkeypatch.setattr(parser.pdftext, "region_text", lambda *a, **k: "Nền tảng\nstreaming VOD")
    nested = [_StubItem(_StubLabel("text"), text="N"), _StubItem(_StubLabel("text"), text="ề")]
    doc = _StubDoc(
        items=[
            _StubItem(
                _StubLabel("picture"),
                prov=[_StubProv(page_no=1, bbox=_StubBBox(l=44, t=487, r=549, b=340))],
                image=Image.new("RGB", (32, 32), (0, 0, 0)),
                children=nested,
            )
        ]
    )
    items = parser.doc_to_items(doc, assets_dir=tmp_path, pdf_path=tmp_path / "d.pdf")
    assert len(items) == 1
    assert items[0].text.startswith("![Nền tảng streaming VOD](assets/")


def test_doc_to_items_picture_caption_still_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(parser.pdftext, "region_text", lambda *a, **k: "text layer")
    doc = _StubDoc(
        items=[
            _StubItem(
                _StubLabel("picture"),
                prov=[_StubProv(page_no=1)],
                image=Image.new("RGB", (32, 32), (0, 0, 0)),
                caption="Figure 2. Context",
                children=[_StubItem(_StubLabel("text"), text="ignored")],
            )
        ]
    )
    items = parser.doc_to_items(doc, assets_dir=tmp_path, pdf_path=tmp_path / "d.pdf")
    assert items[0].text.startswith("![Figure 2. Context](assets/")


def test_doc_to_items_without_assets_dir_keeps_picture_text_as_paragraphs():
    # No assets dir means no image is written, so the nested text is the
    # only trace of the figure: keep the old loose-paragraph behaviour.
    nested = _StubItem(_StubLabel("text"), text="10 m minimum distance.")
    doc = _StubDoc(items=[_StubItem(_StubLabel("picture"), prov=[_StubProv(page_no=9)], children=[nested])])
    assert [i.text for i in parser.doc_to_items(doc)] == ["10 m minimum distance."]
```

`parser.images` must be importable as a module attribute for the monkeypatch: add `from strata_kb.ingest import images` at module level in `parser.py` (it is currently imported inside functions) and drop the in-function imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_parser.py -q -k picture`
Expected: the three new tests fail (`kind` list shows extra `text` items; alt is empty); the no-assets test passes already.

- [ ] **Step 3: Implement**

In `doc_to_items`, after `entries = [...]` and before `tables = ...`:

```python
    nested_ids: set[int] = set()
    child_text: dict[int, str] = {}
    if assets_dir is not None:
        for item, label in entries:
            if label != "picture":
                continue
            kids = [_resolve(c, doc) for c in (getattr(item, "children", None) or [])]
            nested_ids.update(id(k) for k in kids)
            child_text[id(item)] = " ".join(
                t for t in (_clean(getattr(k, "text", "") or "") for k in kids) if t
            )
```

Add the helper after `_iterate`:

```python
def _resolve(ref, doc):
    """docling children are RefItems; the stubs in tests hold the node itself."""
    resolve = getattr(ref, "resolve", None)
    return resolve(doc) if callable(resolve) else ref
```

In the main loop, right after `if label in _SKIP_LABELS: continue`:

```python
        if id(item) in nested_ids:
            continue
```

Change the picture branch to pass the new arguments:

```python
        elif label == "picture":
            if assets_dir is None or id(item) in consumed:
                continue
            md = _picture_md(item, doc, assets_dir, pdf_path, child_text.get(id(item), ""))
```

`_place_glyphs` keeps calling `_picture_md(item, doc, assets_dir)`: glyphs are table icons with no text layer, and opening the PDF per icon would be slow.

Replace `_picture_md`:

```python
def _picture_md(
    item, doc, assets_dir: Path, pdf_path: Path | None = None, child_text: str = ""
) -> str | None:
    """One picture → saved asset + markdown ref, or None on any failure.
    A lost image must never abort the ingest.

    Alt text, first source that yields anything: the document's own
    caption; the PDF text layer under the picture (correct diacritics and
    order); the text cells docling nested under the picture (tabs and split
    glyphs, but still searchable); OCR of the crop.
    """
    try:
        img = item.get_image(doc)
        if img is None:
            return None
        try:
            caption = item.caption_text(doc) or ""
        except Exception:  # noqa: BLE001 -- caption best-effort, image itself is still saved
            caption = ""
        desc = images.resolve_description(caption, "")
        if not desc:
            page, box = _bottomleft_box(item, doc)
            desc = _clean(pdftext.region_text(pdf_path, page, box, mono=False) or "")
        if not desc:
            desc = child_text
        if not desc:
            desc = images.resolve_description("", images.ocr_image(img))
        filename = images.save_asset(img, assets_dir)
        return images.image_ref(desc, filename)
    except Exception as exc:  # noqa: BLE001 — skip the image, keep the text
        logger.warning("picture on page %s skipped: %s", _page_of(item), exc)
        return None
```

Update the `traverse_pictures` comment above `entries` in `doc_to_items` to say the children are folded into the picture's alt text (was: emitted as items).

- [ ] **Step 4: Run the ingest suites**

Run: `uv run pytest tests/test_parser.py tests/test_images.py tests/test_sectioner.py tests/test_scaffold.py tests/test_ingest_seam.py tests/test_ingest_cli.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/ingest/parser.py tests/test_parser.py
git commit -m "fix(ingest): fold text drawn inside a picture into its alt text

Text cells docling nests under a picture used to land in L3 as one
paragraph per cell (26 box-drawing fragments under a diagram that already
shows them). They now become the image's alt, read from the PDF text
layer when available, so search keeps them and the reader does not.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `mdrender` renders fenced code and bullet lists

**Files:**
- Modify: `src/strata_kb/web/mdrender.py`
- Test: `tests/test_web_mdrender.py`

**Interfaces:**
- Produces: `render(md, terms)` emits `<pre><code>…</code></pre>` for fences (escaped, verbatim, no `<mark>`) and `<ul><li>…</li></ul>` for `- `/`* ` lines, merging items across single blank lines.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_fenced_code_is_verbatim_and_escaped():
    md = "```\n│\tViewer <A> | x\n  indented\n```"
    out = render(md)
    assert out == "<pre><code>│\tViewer &lt;A&gt; | x\n  indented</code></pre>"


def test_fenced_code_language_tag_is_ignored():
    assert render("```sql\nSELECT 1;\n```") == "<pre><code>SELECT 1;</code></pre>"


def test_fenced_code_is_not_highlighted():
    assert render("```\nairspace\n```", terms={"airspace"}) == "<pre><code>airspace</code></pre>"


def test_unclosed_fence_runs_to_end():
    assert render("```\none\ntwo") == "<pre><code>one\ntwo</code></pre>"


def test_fence_lines_starting_with_pipe_or_hash_stay_code():
    out = render("```\n| a | b |\n## not a heading\n```")
    assert out == "<pre><code>| a | b |\n## not a heading</code></pre>"


def test_list_items_merge_across_single_blank_line():
    md = "- one\n\n- two\n* three\n\nAfter."
    out = render(md)
    assert out == "<ul><li>one</li><li>two</li><li>three</li></ul>\n<p>After.</p>"


def test_list_item_is_highlighted_and_escaped():
    out = render("- Restrictive <Airspace>", terms={"airspace"})
    assert out == "<ul><li>Restrictive &lt;<mark>Airspace</mark>&gt;</li></ul>"


def test_list_closes_before_heading_and_table():
    md = "- a\n## H\n- b\n| x |"
    out = render(md)
    assert out == "<ul><li>a</li></ul>\n<h2>H</h2>\n<ul><li>b</li></ul>\n<table><tr><td>x</td></tr></table>"


def test_dash_inside_paragraph_is_not_a_list():
    assert render("value - not a list") == "<p>value - not a list</p>"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web_mdrender.py -q`
Expected: the 9 new tests fail (output wrapped in `<p>`).

- [ ] **Step 3: Implement**

Add regexes after `_IMG_LINE_RE`:

```python
_FENCE_RE = re.compile(r"^```[\w-]*\s*$")
_LIST_RE = re.compile(r"^[-*] (.*)$")
```

Update the module docstring's "Supported:" sentence to add "fenced code blocks (verbatim, never highlighted) and `- `/`* ` bullet lists".

Rewrite `render`:

```python
def render(md: str, terms: set[str] | None = None) -> str:
    terms = terms or set()
    blocks: list[str] = []
    para: list[str] = []
    bullets: list[str] = []

    def flush_para() -> None:
        if para:
            blocks.append(f"<p>{_highlight(' '.join(para), terms)}</p>")
            para.clear()

    def flush_list() -> None:
        if bullets:
            blocks.append("<ul>" + "".join(bullets) + "</ul>")
            bullets.clear()

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE_RE.match(line):
            flush_para()
            flush_list()
            i += 1
            code: list[str] = []
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1  # closing fence, or one past the end
            blocks.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
            continue
        if line.lstrip().startswith("|"):
            flush_para()
            flush_list()
            table: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                table.append(lines[i])
                i += 1
            blocks.append(_render_table(table, terms))
            continue
        m_img = _IMG_LINE_RE.match(line.strip())
        if m_img:
            flush_para()
            flush_list()
            blocks.append(_img_tag(m_img))
            i += 1
            continue
        m = _HEADING_RE.match(line)
        m_li = _LIST_RE.match(line)
        if m:
            flush_para()
            flush_list()
            level = len(m.group(1))
            blocks.append(f"<h{level}>{_highlight(m.group(2).strip(), terms)}</h{level}>")
        elif m_li:
            flush_para()
            bullets.append(f"<li>{_highlight(m_li.group(1).strip(), terms)}</li>")
        elif not line.strip():
            flush_para()  # a blank line does not end a list
        else:
            flush_list()
            para.append(line.strip())
        i += 1
    flush_para()
    flush_list()
    return "\n".join(blocks)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_web_mdrender.py tests/test_web_ui.py tests/test_web_uidata.py -q`
Expected: all pass (existing paragraph/table/image behaviour unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/web/mdrender.py tests/test_web_mdrender.py
git commit -m "feat(web): render fenced code and bullet lists in L2/L3

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Reader styling and pager above and below

**Files:**
- Create: `src/strata_kb/templates/web/_partials/pager.html`
- Modify: `src/strata_kb/templates/web/section.html`
- Modify: `src/strata_kb/templates/web/static/style.css:258-274`
- Modify: `CHANGELOG.md`
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Produces: Jinja macro `pager(doc_id, repo, prev, next)` rendering the existing `.pager` markup or nothing.

- [ ] **Step 1: Write the failing test** (append to `tests/test_web_ui.py`, next to `test_section_page_prev_next_pager_links_to_siblings`)

```python
def test_section_page_pager_appears_above_and_below_article(demo_doc_hub):
    _add_section(
        demo_doc_hub, "demo-kb", "demo-doc",
        models.SectionEntry(id="1.2", title="Next Section", status="pending", file="ch1"),
    )
    main = _main(
        _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
            "/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}
        )
    )
    assert main.count('<div class="pager">') == 2
    assert main.index('<div class="pager">') < main.index('class="level-tabs"')
    assert main.rindex('<div class="pager">') > main.index('class="reader-body"')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_ui.py -q -k pager`
Expected: the new test fails on `count == 2` (currently 1); `test_section_page_no_siblings_hides_pager` passes.

- [ ] **Step 3: Implement the partial and template**

`src/strata_kb/templates/web/_partials/pager.html`:

```jinja
{% macro pager(doc_id, repo, prev, next) %}
{% if prev or next %}
<div class="pager">
  {% if prev %}
  <a href="/ui/docs/{{ doc_id | urlencode }}/{{ prev.id | urlencode }}?repo={{ repo | urlencode }}">
    <span class="dir">← previous</span><span class="label">§{{ prev.id }} {{ prev.title }}</span></a>
  {% else %}<span></span>{% endif %}
  {% if next %}
  <a class="next" href="/ui/docs/{{ doc_id | urlencode }}/{{ next.id | urlencode }}?repo={{ repo | urlencode }}">
    <span class="dir">next →</span><span class="label">§{{ next.id }} {{ next.title }}</span></a>
  {% endif %}
</div>
{% endif %}
{% endmacro %}
```

In `section.html`: add `{% from "_partials/pager.html" import pager %}` under the existing `status` import; insert `{{ pager(doc_id, repo, prev, next) }}` between the `.page-head` div and the `.level-tabs` div; replace the whole `{% if prev or next %} … {% endif %}` block after the article with `{{ pager(doc_id, repo, prev, next) }}`.

- [ ] **Step 4: Reader CSS**

In `style.css`, after `.reader-body img { max-width: 100%; }` replace that line and add:

```css
.reader-body img { max-width: 100%; margin: 12px 0; border: 1px solid var(--line-soft);
  border-radius: 4px; }
.reader-body h2 { font-size: 26px; margin: 32px 0 12px; }
.reader-body h3 { font-size: 20px; margin: 22px 0 8px; }
.reader-body pre { margin: 14px 0; padding: 14px 16px; overflow-x: auto; white-space: pre;
  font: 400 13px/1.5 var(--mono); background: var(--surface-alt); border: 1px solid var(--line);
  border-radius: var(--r-lg); }
.reader-body pre code { font: inherit; }
.reader-body ul { margin: 10px 0; padding-left: 1.4em; }
.reader-body li + li { margin-top: 4px; }
```

- [ ] **Step 5: Run the web suites**

Run: `uv run pytest tests/test_web_ui.py tests/test_web_templating.py tests/test_web_app.py -q`
Expected: all pass, including the three existing pager tests.

- [ ] **Step 6: Visual check**

The web UI is the HTTP MCP server. Run it against any hub clone (a repo with `federation/<repo>/<doc>/`; the test fixtures in `tests/conftest.py::fed_hub` show the layout, and the MyFlix hub clone, if present locally, is the real one):

```bash
STRATA_KB_HTTP_TOKEN=dev uv run python -m strata_kb.mcp --hub <hub-clone-path> --transport http
```

Open `http://127.0.0.1:8321/ui`, sign in with `dev`, open any section on L3. Confirm: pager above the tabs and below the article, image bordered, code blocks in a scrollable mono box (any doc with a fence; otherwise temporarily paste a fenced block into a federation `.raw.md` and reload). If no hub clone exists locally, skip this step; Task 6 and the UI tests cover the behaviour.

- [ ] **Step 7: Changelog and commit**

Add under a new `## Unreleased` heading at the top of `CHANGELOG.md` (above `## 1.0.2`):

```markdown
## Unreleased

- Ingest keeps code blocks (fenced, line breaks and Vietnamese diacritics read back from the PDF text layer), bullet lists, and single-spaced words in L3; text drawn inside a figure becomes the image's alt text instead of loose paragraphs. Re-ingest to pick this up.
- Hub reader renders fenced code and bullet lists, styles headings/figures/code like a markdown preview, and shows the previous/next pager above the article as well as below.
```

```bash
git add src/strata_kb/templates/web/_partials/pager.html src/strata_kb/templates/web/section.html src/strata_kb/templates/web/static/style.css tests/test_web_ui.py CHANGELOG.md
git commit -m "feat(web): pager above and below the section, markdown-preview reader styling

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end check on the MyFlix KB

**Files:** none in this repo.

- [ ] **Step 1: Re-ingest two documents**

From `/Users/vuonglq01685/Documents/Projects/MyFlix/code/myflix-center-kb`, using this branch's checkout (`kb ingest <pdf> --id <doc-id>`; doc ids are the existing manifest ids, so the sections merge in place and `.kb-work/<id>/parsed-v2.json` is reused, no docling re-run):

```bash
uv run --project /Users/vuonglq01685/Documents/Projects/AERO-KB kb ingest source/02-high-level-architecture.pdf --id high-level-architecture
uv run --project /Users/vuonglq01685/Documents/Projects/AERO-KB kb ingest source/03-system-design.pdf --id system-design
```

Do not commit anything in the MyFlix repo; this is a read-out. `git -C . checkout -- .kb` afterwards if the user has not asked to keep the re-ingest.

- [ ] **Step 2: Inspect L3**

```bash
grep -c '^```' .kb/high-level-architecture/*.raw.md .kb/system-design/*.raw.md
grep -n 'g ố c\|k ế t' -r .kb/system-design/*.raw.md || echo "no split diacritics"
sed -n '1,12p' .kb/high-level-architecture/ch2-so-o-ngu-canh-he-thong-c4-level-1.raw.md
```

Expected: fence counts > 0 in system-design files; `no split diacritics`; §2 is the heading, one `![…](assets/…webp)` line whose alt starts with `┌──────────────┐`, and the closing paragraph. No box-drawing paragraphs.

- [ ] **Step 3: Run the full test suite once**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 4: Report**

State what was verified with the actual grep output. If anything in Step 2 differs, do not adjust expectations; open the mismatch as a finding for review.
