# Ingest review fixes — sectioner correctness and an honest `kb ingest` report

**Status:** approved design, ready for an implementation plan
**Source:** reviewer A of the 2026-09-08 full framework review,
`docs/superpowers/reviews/2026-09-08-full-framework-review/A-ingest.md`
(findings F1–F9), and §2.1 / §5 đợt 1 item 1 of
`docs/superpowers/reviews/2026-09-08-full-framework-review.vi.md`.
**Approach:** as approved on 2026-09-08 — fix the sectioner defects that
corrupt or hide content (F2, F3, F1, F7), make every sectioning decision
visible in the `kb ingest` report (F1, F4, F5), give `--sections` merge
semantics (F6), close the section-id contract on the scaffold side (F8), and
take the two cheap F9 items. Code and tests only: the bundled `.kb/` is
**not** re-ingested in this batch. The user has both source PDFs; re-ingest,
`kb summarize --redo` and SME re-approval are a later batch.

## Goal

`kb ingest` is the only step that touches the original document, so every
defect here propagates to L2, to the hub, to citations in tickets and to code
a Dev agent writes. Reviewer A showed, on the shipped `arinc-424`:

- `§5.83` holds `§5.84`'s field definition and `§5.83`'s own definition is
  absent (F2, CRITICAL) — a citation to `arinc-424 §5.83` returns the wrong
  field, undetectable without the PDF.
- `5.15` and `5.139` have no trace in L3 at all (F3, HIGH) — a title-less
  numbered heading collapses onto the chapter id and swallows the text.
- 10 of 10 fallback sections are noise (table captions, `Used On:` label
  lines, a repeated `COMMENTARY` block) and the report says nothing (F1,
  HIGH).
- 58 % of sections are below the spec's own 200-token merge threshold and
  nothing measures it (F4, HIGH); the merge rule is inert by design on any
  large chapter and the spec contradicts itself.
- `crosscheck` reports missing bookmarks only, and a fallback child masks a
  missing parent (F5); `--sections` deletes chapters it was not asked about,
  including reviewed L2 (F6); duplicate ids are still producible and
  `kb get` returns the first silently (F7); a custom chapter pattern can
  emit an id with a space that nothing can slice (F8).

After this batch, `kb ingest`:

- attaches body text to the right heading on pages where docling emitted
  headings out of order, and says so;
- never collapses a title-less numbered heading, never turns a caption, a
  label line or a running header into a section, never emits a duplicate id
  or an id containing whitespace;
- prints every demotion, every fallback id, every page re-order, every
  duplicate rename, every unit not in the PDF outline, and the L3 token
  distribution — through the same `[warn]`/echo channel the report already
  uses, so nothing leaks to bare stderr;
- with `--sections`, rewrites only the named chapters and leaves every other
  chapter's files and manifest entries untouched.

## Decisions taken during brainstorming (2026-09-08)

1. **Scope: code + tests; no re-ingest.** The user has the ARINC 424 and
   ICAO Annex 3 PDFs but re-ingest, `--redo` and re-approval are a separate
   batch (they depend on the B-4/B-5 `--redo` safety fixes). All evidence in
   this batch is synthetic `DocItem` fixtures, the way the repo's own tests
   work. The F2 geometry heuristic is therefore validated on synthetic
   bboxes only until that re-ingest; the accompanying warning makes every
   page it touched visible.
2. **F4: each field stays its own section; measure and report.** The
   phase-1 spec §4.4 rule "merge leaves < 200 tokens" contradicts C3 "each
   field is its own section" on a field-definition chapter (ARINC ch5: 324
   fields, 85 669 tokens). The code's existing all-or-nothing guard is the
   right behaviour and becomes the written rule. 300–5000 tokens is a
   measured target, not a law; `kb ingest` prints the distribution. No
   change to the folding algorithm, so the bundled KB keeps its shape and
   `§5.x` citations stay per-field. Rejected: fold small leaves into the
   preceding sibling (changes KB shape, a long field would carry the deleted
   fields after it); fold greedily until the cap (inconsistent — first
   fields merged, last not).
3. **F6: `--sections` means merge.** Re-ingesting with `--sections 6`
   rewrites chapter 6 and leaves chapters 5 and 7 (files, manifest entries,
   status, summaries) untouched. Rejected: keep full-replace behind
   `--force` (smaller change, but the flag's name promises the merge and a
   typo would still be one flag away from deleting reviewed work).
4. **F2: geometry re-order, gated by detected inversion, plus a warning
   always.** Docling's in-page reading order stays authoritative on every
   page that shows no heading-order inversion (the code comment is right:
   it is better than a naive bbox sort). Only a page whose numbered headings
   arrive out of id order is re-ordered by layout, and that page is named in
   the report whether or not bboxes were available to fix it. Rejected:
   warning only (leaves the CRITICAL defect in place until a human edits
   L3); unconditional bbox sort (breaks multi-column layouts).
5. **F3: an empty title is legal end to end.** `parse_section_id("5.15")`
   returns `("5.15", "")`; L3/L2 carry `## 5.15` with no trailing space;
   the manifest carries `title: ""`; both heading regexes in `mdutils`
   accept it. No placeholder text — L3 is the original, and inventing
   "(untitled)" would be the LLM-free layer fabricating content.
6. **F7: rename duplicates, never fail.** A duplicate id from a page-range
   stray or a Part-restarted numbering becomes `<id>-2`, `-3`, … with a
   warning. Ugly but reachable by `kb get`, and a document like ICAO Annex 8
   still ingests. Proper per-Part namespacing is a separate feature.
7. **F9: only the two zero-risk items.** Declare `rapidocr-onnxruntime` in
   the `ingest` extra; clean `assets/` with `shutil.rmtree`. The one-row
   table gap in `extract_tables` belongs to the build batch (B-7), heading
   text is not preserved verbatim in L3 by design (ids need the normalised
   form), and the per-table PDF re-render is a perf item.

## Scope

**In:**

- `src/center_kb/ingest/sectioner.py` — F3 regex, F1 noise filter, F2
  inversion detection + gated re-order, F7 duplicate rename, id whitespace
  normalisation, `SectioningNotes`, `build_units_with_notes()`.
- `src/center_kb/ingest/parser.py` — `DocItem.bbox` populated from docling
  provenance, `bookmark_ids` → `None` on an unreadable outline, `crosscheck`
  reverse direction and part-root-only `-` clause, `assets/` cleanup.
- `src/center_kb/ingestcmd.py` — logging bridge, notes → report, outline
  warning, token distribution line.
- `src/center_kb/ingest/scaffold.py` — merge semantics for `chapters`,
  id invariants, empty-title heading line, `token_stats` on
  `ScaffoldReport`.
- `src/center_kb/mdutils.py` — `_HEADING_RE` / `_SUBHEADING_RE` accept an
  empty title.
- `pyproject.toml` + `uv.lock` — `rapidocr-onnxruntime` in the `ingest`
  extra (the lock must be regenerated in the same PR; only CI checks it).
- Specs and README: phase-1 §4.2 / §4.3 / §4.4 / §4.7 rewritten to match;
  README §7.1 re-ingest paragraph and report description.
- Tests: `tests/test_sectioner.py`, `test_parser.py`, `test_scaffold.py`,
  `test_ingest_cli.py`; `test_ingest_seam.py` re-run (fixture regenerated
  only if the demo-doc shape changes — not expected).

**Out (named so nobody re-litigates):**

- Re-ingesting `.kb/arinc-424` and `.kb/icao-annex-3`, `kb summarize
  --redo`, SME re-approve, README §10 numbers — next batch, after B-4/B-5.
- Per-Part id namespacing for documents whose chapters restart numbering
  per Part (Annex 8).
- Reviewed-L2 preservation inside a chapter that *is* being rewritten —
  that is `--redo`'s contract (B-4/B-5), not ingest's.
- Assets derived for the whole document under `--sections` (content-
  addressed, harmless).
- `cli.py` and `logging.basicConfig` — unchanged; the bridge lives in
  `run_ingest`.
- `kb build` duplicate-id check for already-ingested KBs — build batch.

## Evidence this design rests on

- `sectioner.py:248-251` — body text goes to `self.stack[-1]`; no page or
  geometry check. `order_units` (`402-417`) re-sorts units by heading page
  only, so intra-page inversions survive (reviewer's adversarial case 9 vs
  9b).
- `sectioner.py:81` — `_NUMBERED_RE = ^(\d+(?:\.\d+)*)[.\s]+(.*\S)\s*$`
  requires a title, so `"5.15"` backtracks to `("5", "15")` and
  `_attach_parsed` (`299-303`) no-ops because `5` is already on the stack.
- `sectioner.py:252-264` — the only noise filters are "no alnum" and "ends
  with `:`". The only `logger.warning` (`353-357`) is in the `x{n}` branch,
  unreachable (`test_last_resort_xn_id_logs_warning` asserts no warning).
- `sectioner.py:217-230, 271-294` — one `_TreeBuilder` per part, own
  `seen`; numeric parts are not namespaced, so `5.3` can appear in two
  parts.
- `sectioner.py:511-522` — all-or-nothing small-leaf fold; on ARINC ch5 the
  branch always takes `is_depth_fold`.
- `parser.py:340-341` — `bookmark_ids` swallows every exception as
  `set()`. `parser.py:428-449` — `crosscheck` is missing-only and
  `uid.startswith(bm + "-")` lets `5.6-commentary` cover bookmark `5.6`.
- `parser.py:133-135` — `assets_dir.iterdir()` + `unlink()` raises on a
  subdirectory. `parser.py:35-58` — `_topleft_box` already normalises
  docling bboxes to TOPLEFT.
- `scaffold.py:56-63` — `chapters` filter, then `glob("*.md").unlink()`
  (matches `.raw.md` too).
- `mdutils.py:10, 52` — `_HEADING_RE` / `_SUBHEADING_RE` require a
  non-empty title; these two regexes and the scaffold writer are the only
  consumers of the `## <id> <title>` line (grep over `src/`).
- `ingestcmd.py:81-86` and `cli.py:451` — the `warn` callback is the
  existing report channel; `cli.py` never calls `logging.basicConfig`, so
  `logger.warning` currently reaches stderr via `logging.lastResort` as a
  bare line outside the report.
- `pyproject.toml:34` — `ingest` extra lacks `rapidocr`; `images.py:126`
  logs once and returns `""`, so captionless images lose their `Figure:`
  line silently.

## Design

### §1 Sectioner — `src/center_kb/ingest/sectioner.py`

**F3 — title-less numbered heading.**

```python
_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:[.\s]+(.*\S))?\s*$")
```

In `parse_section_id`: if the title group is empty and the id has **no**
dot, return `None` (a bare `123` is a page number and keeps today's path:
fallback → `_fallback_slug` rejects digit-only → demoted to body). If the id
has a dot, return `(sid, "")`. The `.0` chapter normalisation is unchanged
(`5.0` → `5`). `_attach_parsed` needs no change: `"5.15"` is a new id, not
an open node.

**F1 — heading-noise filter.** New module-level helpers, called from
`_TreeBuilder.feed` *after* `parse_section_id` returns `None` and *before*
`_attach_fallback` (so `5.149 Figure of Merit`, which parses, is untouched):

```python
_CAPTION_RE = re.compile(r"^(table|figure|fig\.?|diagram|chart|exhibit)\s+\S", re.I)
_LABEL_RE = re.compile(r"\b[\w/]+:\s")          # "Used On: ", "Length: ", "Source/Content: "

def _noise_reason(normalized: str, repeated_pages: int) -> str | None:
    if _CAPTION_RE.match(normalized):
        return "caption"
    if len(_LABEL_RE.findall(normalized)) >= 2:
        return "label line"
    if repeated_pages >= 3:
        return f"repeated on {repeated_pages} pages"
    return None
```

`repeated_pages` comes from a pre-pass in `build_units_with_notes` over
the **whole** item list, before `_split_front_matter` / `split_by_parts`
(a running header must be counted across parts): for every heading item
whose text does not parse, count distinct pages per normalised text; every
builder receives that mapping. A noise heading is
demoted exactly like the existing `:` rule — `**<text>**` appended to the
current node's body — so content is never lost; the demotion is recorded in
`notes.demoted` once per distinct text (with the page list) so a running
header on 47 pages is one note, not 47.

The `x{n}` branch and its `logger.warning` stay (still the last resort);
every fallback that *does* open a node is recorded in `notes.fallbacks`
(`id`, `heading`, `page`).

**F2 — intra-page heading inversion.** `DocItem` gains
`bbox: tuple[float, float, float, float] | None = None` (`l, t, r, b`,
TOPLEFT origin; default `None` keeps every existing stub fixture valid).

Pre-pass in `build_units_with_notes`, per page (items grouped by
forward-filled page, same rule as `split_by_parts`):

1. Collect the page's heading items that parse to a **numeric** id (chapter/
   appendix/attachment/fallback headings do not participate).
2. Group by parent id (`sid.rsplit(".", 1)[0]`); within a group compare
   consecutive ids as integer tuples. Any descending pair (`5.84` then
   `5.83`) marks the page as inverted; record
   `notes.inversions.append(Inversion(page, first_id, second_id, reordered))`.
3. If inverted **and** every item on the page has a bbox: re-order the
   page's items by layout. Page span = `[min left, max right]` over the
   page's items, `mid` its midpoint. An item whose width ≥ 60 % of the span
   is **spanning** (a chapter title or a full-width table); spanning items
   cut the page into vertical bands at their `top`. Within a band, items
   sort by `(column, top)` with `column = 0` when the bbox centre x < mid
   else `1`; a spanning item sorts first in the band it opens. Ties keep
   docling order (stable sort). `reordered = True`.
4. If inverted and any bbox is missing: leave the page alone,
   `reordered = False` — the warning still names the page.

The re-ordered item list then flows into the existing tree builder
unchanged. Pages with no inversion are never touched, so the existing 143
tests and the seam fixture see identical input.

**F7 — duplicate ids across parts.** After `order_units`, in both modes
(parts and heading-pattern — the invariant is unconditional even though
only the parts mode can produce a duplicate today), walk the units in
order keeping a `seen` set; a
repeated id becomes `f"{id}-{n}"` with the smallest `n ≥ 2` not yet taken,
`title` unchanged, `notes.duplicates.append(Duplicate(original, renamed,
chapter))`. Fallback slugs are never digit-only (`_fallback_slug`), so the
suffix cannot collide with a fallback child; `_depth_of` counts dots only,
so depth is unaffected.

**Id whitespace (F8, sectioner side).** `parse_section_id` applies
`re.sub(r"\s+", "-", id)` to the identifier group of the chapter, appendix
and attachment patterns (case preserved: `Part A` → `Part-A`). Default
patterns capture `\d+`/`[0-9A-Za-z.]+`, so existing ids are unchanged.

**API.**

```python
@dataclass
class SectioningNotes:
    demoted: list[Demotion]        # heading, reason, pages
    fallbacks: list[Fallback]      # id, heading, page
    inversions: list[Inversion]    # page, first_id, second_id, reordered
    duplicates: list[Duplicate]    # original, renamed, chapter

def build_units_with_notes(items, *, max_depth=3, min_tokens=200,
                           max_unit_tokens=5000, config=None, parts=None
                           ) -> tuple[list[SectionUnit], SectioningNotes]: ...

def build_units(items, ...) -> list[SectionUnit]:
    return build_units_with_notes(items, ...)[0]
```

`build_units` keeps its signature so every existing test and caller is
untouched; `ingestcmd` switches to the `_with_notes` form.

### §2 Parser — `src/center_kb/ingest/parser.py`

- `doc_to_items` passes `bbox=_topleft_box(prov.bbox, page, doc)` into every
  `DocItem` it creates (headings, text, tables, images); `None` when docling
  has no provenance or the page height is unknown.
- `bookmark_ids` returns `None` when `PdfReader`/outline walking raises
  (today: `set()`), and `set()` when the outline is readable but yields no
  parseable id. `outline_parts` is unchanged.
- `crosscheck(unit_ids, bm_ids, max_depth=3)` returns the existing missing
  warnings **plus** extra warnings:
  - the `uid.startswith(bm + "-")` coverage clause applies only when
    `_is_part_root(bm)` (appendix/attachment namespacing); a numeric
    bookmark is no longer covered by a fallback child.
  - reverse direction: a unit id that is numeric (`id[0].isdigit()`), not in
    `bm_ids`, **and** whose parent (`id.rsplit(".", 1)[0]`) is the parent of
    at least one bookmark → `section '<id>' not in the PDF outline`. The
    sibling rule is what makes the check meaningful: the outline enumerates
    that level under that parent, so an id it lacks is a real discrepancy.
    An outline that stops at chapters has no bookmark with parent `5`, so
    no `5.x` unit is ever reported; ARINC's 639-entry outline has many, so a
    collapsed `5.15`, a stray `5.3-2` or a hallucinated `5.6` all surface.
    A bookmark ancestor does **not** cover a unit (bookmark `5` says nothing
    about `5.6`). Fallback ids are excluded (they have their own warning).
- `assets_dir` cleanup: `shutil.rmtree(assets_dir, ignore_errors=False)`
  then `mkdir(parents=True)` — a subdirectory no longer raises.

### §3 Ingest report — `src/center_kb/ingestcmd.py`

**Logging bridge.** A small `logging.Handler` subclass holding the `warn`
callback is attached to `logging.getLogger("center_kb.ingest")` at level
`WARNING` for the duration of `run_ingest` and removed in `finally`. Parser,
images and tableimages warnings arrive in the report as
`[warn] <message>`. `cli.py` and global logging config are untouched;
`kb mcp`'s own `basicConfig` is unaffected.

**Notes → report.** After `build_units_with_notes`, format each group
through `warn`, capped at `_MAX_NOTES_SHOWN = 20` per group with a trailing
`N more <group> not shown` line (same idiom as `_warn_uncovered`):

```
[warn] heading demoted to text (caption, page 129): 'Table 5-6 Airport and Heliport SID Record'
[warn] heading demoted to text (repeated on 3 pages: 61, 88, 104): 'COMMENTARY'
[warn] fallback id '5.35-ndb-navaid-record' for unparsed heading 'NDB Navaid Record' (page 140)
[warn] heading order inverted on page 212: 5.84 before 5.83 — page re-ordered by layout, check both sections
[warn] heading order inverted on page 212: 5.84 before 5.83 — no layout data, body attribution may be wrong
[warn] duplicate section id '5.3' in part 6 renamed to '5.3-2'
[warn] PDF outline unreadable — bookmark cross-check skipped
[warn] section '5.3-2' not in the PDF outline
```

**Token distribution (F4).** `scaffold_doc` already computes
`count_tokens(unit.body_md)` per section; it returns them on
`ScaffoldReport.token_stats` (`n`, `min`, `median`, `max`, `below_300`,
`above_5000`, `n_fallback`). `run_ingest` echoes one line after the scaffold
call, as plain `echo` (expected on field-definition documents per decision
2):

```
sections: 325 · L3 tokens min/median/max 15/177/4327 · 261 below 300, 0 above 5000 · 0 fallback ids
```

`token_stats` carries `n`, `min`, `median`, `max`, `below_300`,
`above_5000` from the units scaffold wrote; the fallback count is
`len(notes.fallbacks)` from the sectioner, appended by `run_ingest` (a
`--sections` run may count fallbacks in chapters it did not write — the
number describes the sectioning pass, which is what it is for).

### §4 Scaffold — `src/center_kb/ingest/scaffold.py`

**Merge semantics for `chapters` (F6).**

```
if chapters is None:            # full ingest — unchanged: delete every *.md, write all
if chapters and no previous manifest:   # unchanged: write the named chapters only
if chapters and previous manifest:      # NEW: merge
```

Merge path:

1. `rewritten = {chapter_stem prefix for each chapter in chapters}` where the
   prefix is `f"ch{c}"` for numeric chapters and `c` otherwise (mirrors
   `chapter_stem`). A previous file/entry belongs to a rewritten chapter when
   its stem `== prefix` or `startswith(prefix + "-")`.
2. Delete only `doc_dir/*.md` whose stem belongs to a rewritten chapter.
3. New manifest sections = previous sections with every rewritten-chapter
   entry removed, and the new entries inserted at the index of the first
   removed entry (appended at the end if the chapter is new). Kept entries
   are copied verbatim — `status`, `summary`, `tokens` survive.
4. `ingested`, `source_sha256`, `ingest` config and `index.yaml` entry are
   refreshed from this run, as today.

**Id contract (F8).** Before writing anything, `scaffold_doc` validates
every unit: `id` non-empty and `re.search(r"\s", id) is None`; otherwise
`ValueError(f"section id {id!r} contains whitespace — adjust the chapter/
appendix/attachment pattern so its identifier group has no spaces")`. Title
may be empty.

**Heading line.** `f"## {unit.id} {unit.title}".rstrip()` in both L3 and
L2 so an empty title yields `## 5.15`.

### §5 `mdutils.py`

```python
_HEADING_RE    = re.compile(r"^## (?P<sid>\S+)(?:[ \t]+(?P<title>.*?))?\s*$")
_SUBHEADING_RE = re.compile(r"^### (?P<sid>\S+)(?:[ \t]+(?P<title>.*?))?\s*$")
```

`slice_section(md, "5.15")` on `## 5.15` returns the block. Callers that
read `group("title")` treat `None` as `""`.

### §6 Packaging

`pyproject.toml` `ingest` extra gains `rapidocr-onnxruntime>=1.3`; `uv.lock`
regenerated in the same commit (`uv lock`), verified by `uv lock --check`.

### §7 Specs and README

- `docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md`
  - §4.2: add the three noise rules (caption, ≥ 2 labels, repeated on ≥ 3
    pages) and the title-less numbered heading rule; "+ cảnh báo trong báo
    cáo ingest" now names the exact warning line.
  - §4.3: "thiếu/thừa" — both directions, plus the outline-unreadable
    warning; note the part-root-only `-` clause.
  - §4.4: rule 2 becomes "gộp lá < 200 token vào cha **chỉ khi** cha sau gộp
    ≤ 5000 token; nếu không, không gộp lá nào (all-or-nothing)"; rule 3
    becomes a measured target printed by `kb ingest`, with the explicit
    exemption for field-definition chapters (mỗi field một section để cite).
  - §4.7: `--sections` = merge; full ingest = full replace.
- `README.md` §7.1: replace the "Re-ingest is a full replace" paragraph with
  the two cases; add the report lines and the `sections:` summary to the
  ingest description.

## Error handling

- A page with an inversion but incomplete bboxes is reported, never
  guessed.
- `ValueError` from the id contract surfaces through the existing
  `except (ValueError, RuntimeError)` in `cli.py` as a red line + exit 1,
  before any file is written.
- The logging bridge is removed in `finally`, so a failed ingest never
  leaves a handler attached for a later command in the same process
  (tests run many CLI invocations in one interpreter).
- `bookmark_ids is None` is the only new tri-state; `run_ingest` treats
  `None` as "warn and skip", `set()` as "no bookmarks, skip silently".
- Merge with a previous manifest whose `file` stems do not match the
  current `chapter_stem` convention (a doc ingested by an older CLI) still
  works: unmatched entries are simply kept, and the new chapter's files are
  written alongside — nothing is deleted that the prefix rule cannot claim.

## Tests and trip-wires

All new behaviour is TDD, on synthetic `DocItem`/`_StubDoc` fixtures (docling
is not installed in `.venv`).

- `tests/test_sectioner.py`
  - F3: `parse_section_id("5.15") == ("5.15", "")`; `"123"` → `None`;
    `"5.0 NAV"` still `("5", "NAV")`; reviewer case 10 now yields units
    `['5', '5.15', '5.16']` with the orphan body under `5.15`.
  - F1: caption, label line, repeated-on-3-pages each demoted with the
    right reason; `Source/Content:` keeps the `:` path; `5.149 Figure of
    Merit` stays a section; a heading repeated on 2 pages is **not**
    demoted; content of every demoted heading is present in the body.
  - F2: case 9 with bboxes (two-column page: `5.83` and its body in the
    left column, `5.84` and both of its paragraphs in the right column,
    docling order `5.84, para-a, 5.83, para-b`) → `5.84` holds both
    paragraphs, `5.83` its own body;
    `inversions == [Inversion(page, "5.84", "5.83", reordered=True)]`. Same
    items without bboxes → bodies as today, `reordered=False`. A spanning
    chapter title above both columns stays first. Case 9b (different pages)
    → no inversion note, `order_units` result unchanged. A page with no
    inversion and bboxes present → item order identical to input.
  - F7: parts `[5, 6]` with `5.3` inside chapter 6's range →
    `['5', '5.3', '6', '5.3-2']` and one `Duplicate` note.
  - F8: chapter pattern `^(part\s+[A-Z])\s*[-–—.:]\s*(.*)$` → id `Part-A`.
  - `test_last_resort_xn_id_logs_warning` updated to assert the note, not
    the absence of a warning.
- `tests/test_parser.py`
  - `crosscheck({"5.6-commentary"}, {"5.6"})` → missing `5.6`;
    `crosscheck({"appendix-3-2.1"}, {"appendix-3"})` → covered;
    reverse: `crosscheck({"5", "5.6", "5.6.1"}, {"5", "5.7"})` → missing
    `5.7`, extra `5.6` (bookmark `5.7` shares parent `5`); `5.6.1` is not
    reported (no bookmark has parent `5.6`); `crosscheck({"5", "5.6"},
    {"5"})` → no extras (outline stops at chapters).
  - `bookmark_ids` on an unreadable path → `None`; on a stub with no
    parseable titles → `set()`.
  - `doc_to_items` with a subdirectory under `assets/` → no raise, dir
    recreated empty.
  - `DocItem.bbox` populated from a `_StubProv` bbox, TOPLEFT and
    BOTTOMLEFT variants.
- `tests/test_scaffold.py`
  - merge: full ingest of chapters 5/6/7, mark a ch5 section `reviewed`
    with a summary, re-scaffold with `chapters={"6"}` → ch5/ch7 files and
    entries byte-identical, ch6 rewritten, manifest order `5, 6, 7`.
  - no previous manifest + `chapters={"6"}` → only ch6 written (unchanged).
  - `chapters=None` → every `*.md` replaced (unchanged).
  - `ValueError` on id `"Part A"`; message names the id.
  - empty title → L3 line `## 5.15`, `slice_section(raw, "5.15")` returns
    the block, manifest `title: ""`.
  - `ScaffoldReport.token_stats` values on a 3-unit fixture.
- `tests/test_ingest_cli.py`
  - CliRunner e2e with `parser.load_or_parse/outline_parts/bookmark_ids`
    stubbed (the reviewer's `e2e_report.py` shape): asserts each `[warn]`
    line class, the `sections:` line, and that a `logger.warning` emitted
    from `center_kb.ingest.parser` during the run appears as `[warn]` in
    captured output; after the run the logger has no bridge handler left.
  - `bookmark_ids` stub returning `None` → the outline warning.
- `tests/test_ingest_seam.py` — must stay green without touching the
  fixture; if the demo-doc shape changes, regenerate via
  `scripts/gen_e2e_fixture.py`, read the diff, and update
  `tests-gate/e2e/test_journey.py` if it depends on the changed lines.
- Gate: `uv lock --check`, `ruff`, full `pytest`.

## Sequencing

1. `mdutils` regexes + scaffold heading line + F3 regex (small, unlocks the
   empty-title contract everywhere).
2. `SectioningNotes` + `build_units_with_notes` scaffold (no behaviour
   change yet), then F1 filter, F7 rename, F8 id normalisation on top.
3. `DocItem.bbox` + parser provenance, then F2 pre-pass.
4. Parser `bookmark_ids`/`crosscheck`/assets cleanup.
5. `ingestcmd` bridge + notes formatting + `token_stats`.
6. Scaffold merge semantics + id validation.
7. `pyproject` extra + `uv lock`.
8. Spec §4 and README edits.
9. Whole-branch review; `test_ingest_seam` last.
