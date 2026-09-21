# L3 fidelity and hub reader — design

Date: 2026-09-21. Branch: `feat/l3-fidelity`.

## Problem

L3 (`*.raw.md`) promises "no content lost", not "pixel identical". Today it
loses content and structure, and the hub reader renders what survives as
flat paragraphs. Verified on the four MyFlix docs (`docling` parse cache
`.kb-work/*/parsed-v2.json`, 16 `code` items, 27 `list_item` items):

1. Text drawn inside a `picture` (children reached via
   `iterate_items(traverse_pictures=True)`) is emitted as one paragraph per
   docling text cell. On §2 of `02-high-level-architecture` that is 26
   paragraphs of box-drawing fragments under an image that already shows
   the diagram correctly.
2. `code` items become plain paragraphs: line breaks are gone (docling joins
   lines with spaces), columns are gone.
3. `list_item` items become plain paragraphs: bullets are gone.
4. Docling separates words with `\t` (`Hệ\tthống\tkhông`). Harmless in
   `<p>` but wrong in L3 as a file, in alt text and in code.
5. In monospace runs the PDF falls back to FreeMono for Vietnamese glyphs,
   so docling yields `g ố c`, `k ế t`. FTS on "gốc" misses.
6. `mdrender.py` supports headings, paragraphs, pipe tables and asset
   images only. No fenced code, no lists.
7. `section.html` shows previous/next only below the article.

pypdfium2 (a docling dependency, already installed) reads the same PDF
regions with correct diacritics and line breaks
(`PdfTextPage.get_text_bounded`), and exposes per-character boxes
(`count_chars`, `get_charbox(i)`, `get_text_range(i, 1)`), which is enough
to rebuild monospace columns.

## Decision

L3 stays markdown. Fix ingest so L3 carries every construct the source
has (code, lists, figure text), then make the hub render it at IDE
markdown-preview quality. No page crops, no shipped PDF, no page numbers
in the manifest (adding a field to `SectionEntry` is a wire break for
older readers of mirrored manifests; nobody needs it yet).

## A. Ingest (`src/strata_kb/ingest/parser.py`, new `ingest/pdftext.py`)

### A1. `pdftext.py` — text from a PDF region

```python
def region_text(pdf_path: Path, page_no: int, bbox_bottomleft, mono: bool) -> str | None
```

- Opens the page with pypdfium2, takes chars whose charbox centre lies in
  `bbox` (docling BOTTOMLEFT coordinates, same origin as pypdfium2, so no
  conversion; pass the raw `prov.bbox`, not `_prov_box`'s TOPLEFT box).
- `mono=False`: returns `get_text_bounded(...)` with `\r\n` normalised and
  runs of whitespace collapsed to one space per line. Used for picture alt.
- `mono=True`: rebuilds a character grid. Row = chars grouped by baseline
  (charbox bottom rounded to 1pt); column = `round((left - min_left) /
  cell_w)` where `cell_w` is the median width of non-space charboxes in the
  region. Gaps become spaces, trailing spaces stripped. Used for code.
- Any exception, empty result, or `pdf_path is None` returns `None`; the
  caller keeps docling's text. One `logger.warning` per failure, ingest
  never aborts. Page handles are closed per call (ponytail: reopen the
  document per region; cache the `PdfDocument` if ingest time matters).

### A2. `parser.doc_to_items` label handling

| docling label | today | after |
|---|---|---|
| `code` | `DocItem("text", …)` | `DocItem("code", fence)` where body = `region_text(mono=True)` or docling text with `\t`→space, wrapped in ```` ``` ```` fences. `code_language` ignored (docling never sets it here). |
| `list_item` | `DocItem("text", …)` | `DocItem("list", "- " + text)` with `\t`→space and the leading marker docling sometimes keeps (` `, `•`, `-`) stripped. |
| `text` and other text-bearing | as is | `\t`→space (`" ".join(text.split())`). |
| children of a `picture` (any label) | emitted as separate items | skipped; their text becomes the picture's alt (A3). |

Picture children are found by walking `item.children` of every picture
(refs resolved through `doc`), collected into a `set` of ids before the
main loop, and skipped in it.

`DocItem.kind` gains `"code"` and `"list"`. `sectioner.feed` already
appends any non-heading item's stripped text to the current body, so
fence and bullet text flow through unchanged. `_missing_items` compares
`item.text` against the rendered body, so it stays consistent because the
item text *is* the fence/bullet markdown.

Consecutive `list` items are separated by a blank line in L3 like every
other body item. The renderer merges them (B1); no sectioner change.

### A3. Picture alt text

`_picture_md` today: caption, else RapidOCR of the crop (which returned
nothing for §2). After:

1. caption, if any;
2. else `region_text(mono=False)` over the picture bbox (text layer);
3. else OCR as today.

Alt is passed through the existing `_sanitize_alt` (single line, no `|[]`).
`scaffold` already copies alt into L2 as `Figure: …`; a diagram alt is
long but it is the same class of content OCR produces today, so no cap.

### A4. Known limits (accepted)

- A code line beginning with `## ` would end a section in
  `mdutils.slice_section`. Not seen in the corpus; marked with a
  `ponytail:` comment in `pdftext.py`, fix by indenting fence bodies if it
  ever happens.
- Column rebuild assumes one monospace size per code block. Proportional
  fonts inside a `code` item degrade to docling's text with tabs replaced.
- Existing KBs keep their current L3 until re-ingested. `kb ingest` on the
  same source rewrites `*.raw.md`; L2 and review status handling is the
  existing re-ingest path (`scaffold._merge_sections`), unchanged.

## B. Hub reader (`src/strata_kb/web/mdrender.py`, `style.css`)

### B1. `mdrender.render`

Add, in this order of precedence inside the line loop:

- Fenced code: a line that is exactly ```` ``` ```` (optionally followed by a
  language word) opens a block; every line until the closing fence is
  emitted verbatim inside `<pre><code>…</code></pre>`, HTML-escaped, no
  highlighting, no trimming. Unclosed fence runs to end of input.
- List items: a line starting with `- ` or `* ` becomes `<li>`; consecutive
  items, including ones separated by a single blank line, share one
  `<ul>`. Highlighting applies to item text like paragraphs.
- Everything else unchanged. Tables remain character-exact.

Tests in `tests/test_web_mdrender.py`: fence verbatim (tabs, `<`, `|`,
box-drawing kept), fence with language tag, unclosed fence, list merge
across blank line, list item highlight, list followed by paragraph.

### B2. Reader styling ("IDE preview")

Scoped to `.reader-body`, both L2 and L3 tabs:

- `pre`: monospace stack already in `--mono`, 13px, `overflow-x: auto`,
  `white-space: pre`, soft surface background, 1px line border, radius
  `--r-lg`, 14px padding. Box-drawing glyphs need a font with those
  code points; `--mono` stays as is and the browser falls back per glyph,
  which is what IDE previews do.
- `ul`: 1.4em indent, 4px between items.
- `h2`/`h3` scale contrast (26/20px), 32px top margin on `h2`, 22px on
  `h3`; paragraphs 15px/1.7 as today.
- `img`: `max-width: 100%`, 1px `--line-soft` border, 4px radius, 12px
  vertical margin.

No new fonts, no JS.

### B3. Pager top and bottom

Move the `.pager` markup into `_partials/pager.html` as a macro and call
it above `.level-tabs` and below `.reader-body` in `section.html`. Same
links, same CSS.

## C. Verification

- Unit: `tests/test_parser.py` gains cases for `code`, `list_item`,
  picture children skipped, tab normalisation, alt from text layer, using
  the `_Stub*` docling doubles the file already has; `region_text` is
  monkeypatched there. `tests/test_pdftext.py` reads a checked-in
  one-page fixture `tests/fixtures/mono-diagram.pdf` (a monospace
  box-drawing block containing `gốc` and `Nền tảng`, generated once with
  xhtml2pdf, the `docs/src/build_pdf.py` toolchain, not a runtime dep) and
  asserts the rebuilt grid matches an expected string and that
  `mono=False` returns the diacritics intact.
- Manual: re-ingest `02-high-level-architecture.pdf` and
  `03-system-design.pdf` in the MyFlix KB, open §2 and §3 on the hub:
  image with no fragment paragraphs below, code blocks with line breaks
  and `gốc` intact, bullets rendered, pager visible at top.

## Out of scope

Page-crop facsimiles, shipping PDFs, page numbers in citations, syntax
highlighting, changing L2 summarisation.
