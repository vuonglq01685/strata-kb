# Spec A: Image & Icon Handling in the Ingest Pipeline

**Status:** Approved design — not yet implemented.
**Date:** 2026-07-16
**Scope:** `center-kb` engine ingest core, applied to AERO-KB. First of three specs (A: ingest core — this spec; B: S3 asset delivery; C: init/profile tooling — deferred, see §10).

---

## 1. Problem

Ingest converts PDF → markdown well for text but drops all images and icons. For Annex 4 (chart symbology) and ARINC 424 (object icons, diagrams), figures and icons are core content. Additionally, section order after ingest does not follow the table of contents.

Root causes (verified against the code):

- `ingest/parser.py`: `load_or_parse()` never sets `generate_picture_images`, so docling discards pixels; `doc_to_items()` has no `PictureItem` branch, so images are skipped. Captions are kept but float detached.
- Ordering uses docling's reading order; `scaffold_doc` groups by insertion order, does not anchor to the TOC, and section ids sort as strings.

## 2. Goals

- Keep images/icons and place them at the correct position in the document.
- Images searchable via their description text (search indexes L2 only).
- Every description traceable to the source document — **no fabrication, no VLM**.
- Section order follows the PDF outline (TOC).
- Preserve existing invariants, especially table-integrity (L2 cell == L3 cell).

Non-goals for this spec: cloud storage, hub CI, publish-time rewriting, `kb init` changes, migration tooling (specs B and C).

## 3. Architecture constraints

Four-layer model: L0 `index.yaml` · L1 `_maaml` (TOC) · L2 `<file>.md` (condensed) · L3 `<file>.raw.md` (verbatim).

1. **Search indexes L2 only** (`searchdb`: title + summary + first 500 chars of L2). For an image to be searchable its description text must live in L2. `searchdb` / `embed` / `query` are unchanged by this spec.
2. **The hub is the only read source.** `kb publish` / hashsync copies the whole `.kb/` (including `assets/`) to the hub unchanged. This spec adds no publish logic.

## 4. PoC gate (first implementation task)

Before the main build, run docling with `generate_picture_images=True` on representative real Annex-4 and ARINC 424 pages. Measure:

- large-figure coverage (are diagrams emitted as `PictureItem`s?),
- in-cell icon detection (are small icons inside table cells emitted at all?),
- legend-table detection (does the symbology legend survive as a table with image cells?).

Outcome rules:

- In-cell icons **not** detected → descope the inline-table-icon feature (§7) and legend-grounding (§6, source 3) as an accepted gap; the rest of the spec proceeds unchanged.
- Icons detected → full spec proceeds; PoC also fixes the icon/figure pixel threshold (§5) and validates phash matching on real legend pairs (§6).

PoC produces a short findings note committed alongside the plan. The PoC runs manually on real (copyrighted, uncommitted) PDFs — it is not part of CI.

## 5. Extraction, classification, compression (`ingest/parser.py`)

- Enable `generate_picture_images=True`, `images_scale=2.0` (OCR and perceptual hashing need the pixels; compression happens after). Do **not** enable `do_picture_description`.
- Add a `PictureItem` branch to `doc_to_items()`:
  1. obtain the rendered image bytes;
  2. classify **icon vs figure** by pixel dimensions — default threshold ~64 px at scale 1 (i.e. ~128 px at scale 2), a named constant tuned by the PoC;
  3. compress: icon → lossless optimized PNG (sharp, hash-stable); figure → WebP quality ~80;
  4. compute `sha256` **of the stored (compressed) bytes**; write to `.kb/<doc-id>/assets/<sha>.<ext>`;
  5. emit a `DocItem` of kind `image` carrying page (`prov[0].page_no`), bbox, asset path, and the caption reattached via docling's caption reference.
- Content-addressed naming from birth means no rename/rewrite is ever needed downstream (spec B maps the same sha to S3).
- Determinism: the sha depends on encoder output — pin the Pillow (and WebP encoder) version so re-ingest produces no diff noise.

## 6. Description sources — deterministic, first source wins

For each image, in priority order, stopping at the first source that yields text:

1. **Caption** — already captured by docling; reattach to the image item.
2. **OCR** — RapidOCR (already in the pipeline) on the image crop; accept only above a minimum-character floor.
3. **Legend-grounding** (icons only) — parse the document's own legend table into an icon↔meaning map, then match each in-body icon to its entry:
   - Legend detection heuristic: a table where one column is ≥80% images and an adjacent column is text.
   - Matching: **perceptual hash only** (dhash/phash via the `imagehash` library). Same document + same rasterizer → near-identical pixels. Match accepted at Hamming distance ≤ 5 on a 64-bit hash (named constant, config-tunable). Fully deterministic; no model dependency.

**No source yields text → keep the image, leave the description empty. Never fabricate.** A wrong description is worse than none in an aviation KB.

## 7. Placement rules (`ingest/scaffold.py`)

- **Large figure:** L3 gets `![desc](assets/<sha>.webp)` plus the caption line; L2 gets the description text only (as text, so search sees it). Empty description → nothing added to L2 (accepted search gap).
- **Table icon:** the cell content is **byte-identical** in L2 and L3: `![desc](assets/<sha>.png)` with alt-text = legend meaning (or empty), `|` stripped from alt-text. Table-integrity holds because the cells are identical — the invariant forbids L2 ≠ L3, not images in cells. This is a deliberate, icons-only exception to "L2 has no images".
- Committed references are relative (`assets/<sha>.ext`): local markdown preview works, and the content-addressed name makes later profile switches a resolver-only change.

## 8. Section ordering (`ingest/sectioner.py`)

Full page-range anchoring:

- Build a section → page-range map from the PDF outline (`outline_parts()` already exists; a section's range runs from its bookmark's start page to the next bookmark's start).
- Assign every `DocItem` to a section by `prov[0].page_no` (+ bbox-y for boundary pages).
- Emit sections in TOC order; within a section, sort items by (page, bbox-y), respecting docling's coordinate origin.
- Fallback when the PDF has no bookmarks: current behavior plus natural numeric sort of section ids (2.2 < 2.10).

## 9. Rendering & serving (`web/mdrender.py`, `web/ui.py`)

- `mdrender` renders `![]()` images, including inline inside table cells. At render time it rewrites relative `assets/<sha>.ext` refs to the serving route; committed markdown stays relative.
- New route `GET /assets/<sha>.<ext>`: same auth as `/ui`; resolves the sha via a lookup across `federation/**/assets/` (cached map); strict filename guard `^[0-9a-f]{64}\.(png|webp)$` — no path traversal. Private serving keeps images at the same access level as the (copyrighted) text.

## 10. Deferred to specs B and C

Directions already decided, recorded here so context is not lost:

- **Spec B — S3 delivery:** hub-side GitHub Actions on PR merge uploads asset bytes to a private, content-addressed S3 store (`assets/<sha>.ext`, idempotent by `head_object`); binaries never enter hub git; authenticated hub-proxy serving by default (never commit a signed URL); CI-loop guard; reindex after merge. Open there: byte transport (LFS-as-transport vs staging upload), presigned-redirect offload.
- **Spec C — init/profile tooling:** storage profiles `none` (in-repo + git-LFS, default) / `s3` (OIDC) / `s3-token`; `kb init --assets` scaffolding (config, workflow, Terraform stub, `.gitattributes`); guided `/kb-init`; `kb assets migrate`/`verify`; `doctor` checks. Content-addressed refs (this spec) are what keep migration text-rewrite-free.
- **Licensing:** private access controls who sees excerpts; whether ICAO/ARINC terms permit storing/redistributing images must be confirmed with the subscription owner separately.

## 11. Error handling

- Any single-image failure (decode, compress, save) → log a warning, skip that image, continue the ingest. Never abort a document on asset errors.
- OCR failure → empty description (fall through to the next source or empty).
- Missing asset at render time → broken-image placeholder, page still renders.

## 12. Testing

Hermetic — no live docling, no LLM, no network (existing test pattern; the machine has a real `claude` so ingest tests must not shell out):

- phash matcher: synthetic icon pairs (identical, near-identical, distinct) against the Hamming threshold.
- icon/figure classifier and compression format selection.
- sectioner: synthetic `DocItem`s + fake outline → TOC-ordered output; no-bookmark fallback natural sort.
- scaffold: figure placement (L3 image + L2 text), table-icon cells byte-identical L2 == L3, `|` stripped from alt-text.
- mdrender: image rendering incl. in-cell; asset route auth required; traversal/filename-guard rejection.
- `tests-gate` golden regression updated for the new output shape.

Real-PDF validation stays in the manual PoC (§4).

## 13. Decisions log

| Decision | Choice |
|---|---|
| Scope | Decompose into A (this) → B (S3) → C (init tooling); PoC gate folded into A |
| Legend matcher | Perceptual hash only, Hamming ≤ 5 / 64-bit, tunable |
| Compression | Extract at `images_scale=2.0`; icons lossless PNG, figures WebP q~80; threshold from PoC |
| Ordering | Full page-range anchoring to PDF outline; natural-sort fallback |
| Reference format | Content-addressed filename `assets/<sha>.ext`, relative refs, no rewrite step |
| Descriptions | Caption → OCR → legend-grounding; empty when none; no VLM |
| Search layers | `searchdb` / `embed` / `query` unchanged |
