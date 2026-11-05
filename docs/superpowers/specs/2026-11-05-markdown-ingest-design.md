# Markdown ingest — `.md` source straight to L3 (design)

Date: 2026-11-05 · Size: project · Version: 1.34.4 → 1.35.0

## Intent

Some source documents already exist as Markdown. Today `kb ingest` takes only
a PDF, so an MD document must be printed to PDF and parsed back — lossy and
pointless. The owner wants `kb ingest <file>.md` to put the document straight
into L3, after checking that its headings follow the L3 section-id format and
fixing them where they do not:

1. **Rules first** (deterministic, at ingest time): headings become
   `## <id> <title>` units with the same id rules as a PDF ingest.
2. **AI second** (the existing `/kb-l3-fix` loop): what the rules could not
   settle (wrong or skipped numbers, a body line that is really a heading,
   broken paragraphs) is repaired by AI drafts that `kb l3 fix apply` checks
   against the **source MD** instead of the PDF. A human still confirms.

## Goals

1. `kb ingest <path>.md --id <doc>` writes the same artifacts a PDF ingest
   writes: `<stem>.raw.md` (L3), `<stem>.md` (L2 placeholders), `_manifest.yaml`,
   `index.yaml` entry, `sections.json` spans, `_l3check.yaml`, fix-record reset.
2. Text and tables of the source reach L3 unchanged. Only heading lines are
   rewritten by the rules.
3. Section ids follow the existing sectioner rules: numbered heading → its
   number (`1.2`, `A.3`, chapter/appendix/attachment patterns); unnumbered
   heading → fallback slug id under its parent; duplicates renamed `-N` with a
   warning; units bounded by the existing token targets.
4. Unnumbered headings nest by their Markdown `#` level (an MD file carries a
   reliable level; a PDF does not). A numbered heading's depth still comes from
   its number.
5. `kb l3 fix apply`, `kb l3 lint` and the ingest-time L3 check accept an MD
   source: the word check aligns drafts to the MD text; PDF-only checks are
   skipped.
6. `/kb-l3-fix` and `/kb-ingest` skills and the guides (en + vi) describe the
   MD path.

## Non-goals

- No other input formats (docx, html, rst).
- No docling for MD: the MD path must work without the `ingest` extra.
- No mechanism to re-apply AI fixes after a re-ingest (see Decisions).
- No change to the `authored` tag semantics, L2/L1 summarize, build, publish.
- No change to PDF ingest behavior or output (byte-identical on the existing
  test corpus).

## Anti-goals (a failure even if it "works")

- Any word, number or table cell in L3 that is not in the source MD at that
  place (rules or AI).
- A content block of the source MD that never reaches L3 (`uncovered` must
  stay empty, as for PDF).
- An MD ingest that silently invents numbered ids (`1`, `1.1`, …) for
  unnumbered headings: invented numbers look authoritative and collide with a
  later real numbering. Unnumbered stays fallback-slug until the AI or the
  author numbers it.

## Constraints (from the code today)

- `ingestcmd._run_ingest` is PDF-shaped: `parser.load_or_parse` (docling),
  `parser.doc_to_items`, `outline_parts`/`bookmark_ids` (PDF outline),
  `pdftext.page_texts`, `parser.furniture_by_page(doc)`.
- `sectioner` consumes `DocItem(kind, text, level, page, bbox)` and decides ids
  from heading **text** (`parse_section_id`, `HeadingConfig`); it ignores
  `DocItem.level` today. Fallback headings nest under whatever node is open.
- L3 format: unit `## <id> <title>` (`mdutils.HEADING_RE`), folded child
  `### <id> <title>`.
- `l3check` checks take `pdf_pages: dict[int, str]` and
  `furniture: dict[int, list[str]]`; `spans` stores page spans per unit;
  `kb l3 fix apply --pdf` preflight checks `sha256(pdf) == manifest.source_sha256`;
  `kb l3 fix pages` renders PDF pages to images.
- `markdown-it-py>=3.0` is a core dependency (used by `web/gfmrender.py`).
- `planingest.demote_headings/promote_headings` already handle fenced code
  when shifting heading levels — reuse rather than re-implement fence logic.

## Approaches considered

**A. MD reader → `DocItem` → existing sectioner/scaffold (chosen).**
`kb ingest` branches on the source suffix. A new reader parses MD with
`markdown-it-py` into `DocItem`s, slicing each block from the **source lines**
(token `.map`) so text is never re-rendered. From there the PDF pipeline runs
unchanged. L3 check / fix get an MD "source text" provider in place of the PDF
text layer. Least new code; MD and PDF docs share id rules and unit sizing.
Cost: the PDF-only checks must be made optional.

**B. MD through docling.** Reuses `doc_to_items` almost as is, but docling
re-renders text and tables (breaks goal 2) and forces the heavy `ingest`
extra. Rejected.

**C. Separate `kb ingest-md` writing `.raw.md` directly.** Self-contained, but
duplicates id rules, token sizing and manifest writing; the two paths drift.
Rejected.

The owner picked **A**.

## Decisions (owner)

- Fixing is two-layer: rules at ingest, then the AI fix loop with human
  confirm (`kb l3 confirm`), same gates as PDF.
- **The source MD is the master**, exactly like a PDF: it lives in `source/`
  (git-ignored), edits go into the MD, and `kb ingest` is re-run. A re-ingest
  re-runs the rules and resets `_l3fix.yaml` for the rewritten files (current
  `_reset_fix_record` behavior), so `/kb-l3-fix` and confirm are re-run. To
  freeze a doc, `kb authored <doc>` still works and makes ingest refuse it.

## Design

### 1. Entry point

`kb ingest <source>`: argument renamed from `pdf` to `source` (help text
"Source PDF or Markdown file"). Suffix `.md`/`.markdown` (case-insensitive)
→ MD path; anything else → PDF path as today. `IngestOptions.pdf` becomes
`source` (all callers updated). `--no-bookmarks` is a no-op for MD (warn if
given). `manifest.source_sha256` = sha256 of the MD bytes.

### 2. MD reader (`ingest/mdreader.py`, new)

`md_to_items(text: str) -> list[DocItem]`:

- Front matter (`---` YAML at line 1) is dropped from items and reported once
  as a warning (it is metadata, not content). *Builder: if keeping it as a
  text item is simpler and harmless, say so.*
- The first `#` H1, when it is the only H1 and is unnumbered, becomes the
  document title (manifest `title`), not a section. Otherwise every heading is
  a section heading.
- Heading → `DocItem("heading", <inline text>, level=<#count>)`.
- Paragraph, list, table, fenced/indented code, blockquote, HTML block →
  `DocItem` of the matching kind whose `text` is the **verbatim source lines**
  of that block (via token `.map`). Tables stay pipe tables byte for byte.
- `page`: a synthetic page number per top-level heading block (see §4);
  `bbox=None`.
- Images (`![alt](src)`) stay as written inside their block. Local relative
  image files are **not** copied into `assets/` in this version (see Open
  questions).

### 3. Rules (sectioner changes)

- Numbered headings: unchanged path (`parse_section_id`, `HeadingConfig`).
- Unnumbered headings from an MD source: nest by `DocItem.level` relative to
  the open stack (pop to the nearest open node with a smaller level) instead
  of "under whatever is open". Gate this on a flag passed by the MD path
  (e.g. `build_units_with_notes(..., use_levels=True)`) so PDF output is
  byte-identical.
- Dedupe, demotion of caption/label/repeated lines, token-bounded units,
  `uncovered`: unchanged. `_reorder_inverted_pages` is a no-op without bbox.
- The rules only rewrite heading lines into `## <id> <title>` / folded
  `### <id> <title>`; nothing else in a block changes.

### 4. Source context for L3 check / fix

Introduce one small seam: a "source context" of
`(pages: dict[int, str], furniture: dict[int, list[str]])`, which is exactly
what `lint.load_pdf_context` returns today.

- PDF: unchanged (`pdftext.page_texts`, `parser.furniture_by_page`).
- MD: pages = the source text split into synthetic pages, one per top-level
  heading block (front matter removed); furniture = `{}`. Synthetic pages keep
  `spans` meaningful (a unit's span is its block, so the "does not copy a
  neighbouring unit's text" check still works) and keep word-check alignment
  local instead of whole-document.
- The context is chosen by the manifest's source kind, recorded at ingest
  (`IngestConfig.source_kind: "pdf" | "md"`, default `"pdf"` so existing
  manifests load unchanged).

### 5. `kb l3 fix apply` / `kb l3 lint` / `kb l3 fix pages`

- `--pdf` gains an alias `--source` (keep `--pdf` working); preflight sha256
  check is the same against either file.
- With an MD source: load the MD context; skip furniture/watermark and
  page-image checks; refuse `--from-image` and `kb l3 fix pages` with a
  one-line message ("source is Markdown: no page images").
- All other checks (replaces, status, tables, contract, words, ids, links)
  run as for PDF.

### 6. Ingest-time L3 check

`ingestcmd.l3_check` takes the source context instead of `doc` + `pdf_pages`;
for MD it runs `detect.check_document` with the MD context. Findings that only
make sense for PDF (furniture, page headers) are naturally empty with
furniture `{}`.

### 7. Skills and docs

- `kb-ingest` skill: accept `.md` files.
- `kb-l3-fix` skill: "the PDF" → "the source file (PDF or MD)"; for MD,
  rule 4 reads "a word may enter L3 only where the source MD has it";
  `--from-image` / page images not available for MD.
- `guide-hub` / `guide-child` (en + vi): short MD-ingest subsection; rebuild
  the guide PDFs.
- CHANGELOG entry; version 1.35.0.

## Testing

- `mdreader`: verbatim block slicing (tables, code fences with `#` lines,
  lists, blockquote, HTML), front matter, H1-as-title, CRLF input, non-ASCII
  headings.
- Sectioner with `use_levels=True`: unnumbered nesting by level, mixed
  numbered/unnumbered, skipped levels, duplicate headings; PDF path unchanged
  (existing tests stay green, no fixture updates).
- End-to-end `run_ingest` on a small MD fixture: files written, `uncovered`
  empty, every source word present in L3, re-ingest resets fix record,
  `authored` refusal.
- `kb l3 fix apply` with MD source: a passing draft, a draft adding a word not
  in the MD (rejected), `--from-image` refused, wrong `--source` file refused.
- Ingest without the `ingest` extra installed works for MD.

## Open questions

1. **Local images** referenced by the MD (`![](img/a.png)`): leave the link as
   written (current proposal, link may break once published to the hub), or
   copy the file into `.kb/<doc>/assets/` and rewrite the link?

## Left to the builder

- Exact module/function names, the shape of the source-context seam, and how
  `IngestOptions` is threaded through.
- How the `use_levels` flag reaches `_TreeBuilder`.
- Synthetic page boundaries when the file has no top-level heading (one page
  is fine).
