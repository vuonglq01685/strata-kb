# Reviewer A — the ingest step (PDF → sections → L3 / L2 scaffold / L1)

Repo `D:\Projects\AERO-KB` @ `4b47b4c` (main, clean). Criteria in scope: **C2 (L3 completeness)**, **C3 (sectioning)**, C16 (re-ingest / scaffold-preservation parts).

---

## 1. Scope & method

**Code read (line refs used throughout):**
`src/center_kb/ingest/sectioner.py` (561 L), `parser.py` (449 L), `scaffold.py` (139 L), `images.py` (163 L), `tableimages.py` (147 L), `src/center_kb/ingestcmd.py` (106 L), the `ingest` command in `src/center_kb/cli.py:395-480`, `src/center_kb/mdutils.py`, `src/center_kb/query.py:225-302`.

**Specs read:** `docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md` §4, `2026-07-11-bookmark-sectioning-design.md`, `2026-07-16-l3-search-recall-and-section-ids-design.md`, `2026-07-16-image-icon-ingest-design.md`.

**Executed (all foreground, all read-only against the repo; scratch under `…/scratchpad/A/`):**

| # | What | Result |
|---|---|---|
| 1 | `.venv/Scripts/python -m pytest -q tests/test_{sectioner,parser,scaffold,images,tableimages,ingest_cli,ingest_seam,heading_config}.py` | **143 passed in 61 s** |
| 2 | `scratchpad/A/measure.py` — manifest metrics for both bundled docs | see §4 |
| 3 | `scratchpad/A/adversarial.py` — 12 synthetic `build_units()` cases in the tests' `DocItem` style | see §6 |
| 4 | `scratchpad/A/warnvis.py` — warning visibility with **no** `logging.basicConfig` (i.e. exactly the `kb` process) | see F1 |
| 5 | `scratchpad/A/e2e_report.py` — the **real** `kb ingest` CLI end-to-end via `CliRunner`, with `parser.load_or_parse/outline_parts/bookmark_ids` stubbed (docling is not installed) | see F1 |
| 6 | `scratchpad/A/scaffold_test.py` — table/figure/marker byte-fidelity through `scaffold_doc()` | see §5 |
| 7 | `scratchpad/A/reingest_test.py` — `--sections` re-ingest destructiveness | see F6 |
| 8 | Parser item-type matrix over 14 docling labels | see §5 |

`docling` and `pypdfium2` are **not** installed in `.venv` (`ModuleNotFoundError`), so the sectioner/scaffold were exercised through stub `DocItem`/`_StubDoc` fixtures, the same way the repo's own tests do. No source PDFs are in the repo (`git ls-files | grep pdf` → only `AERO-KB_Architecture_v0.4.pdf`), and there is no `.kb-work/` cache, so the ARINC ingest could not be re-run; ARINC findings are read off the committed L3/L2/manifest plus mechanism reproduction on synthetic input.

---

## 2. Verified-good

1. **L3 text extraction is a deny-list, and it holds.** `parser.py:18-23` skips only `page_header`/`page_footer`. Measured over 14 docling labels: `text, paragraph, list_item, caption, footnote, formula, code, checkbox_selected, reference` all reach L3; only the two page-furniture labels are dropped. This is the right call for C2 ("L3 = full original, nothing cut") and the comment explains why.
2. **Tables reach L2 byte-for-byte.** `scaffold.py:86-87` writes `unit.tables` (from `extract_tables`) straight into L2. Verified with a table containing escaped pipes and a mixed alignment row (`|:---|---:|:--:|`): the 4-line block is byte-identical in `.md` and `.raw.md`.
3. **`Figure:` lines and the summarize marker are emitted correctly.** `<!-- TODO:summarize <id> -->` sits *above* the copied tables, `Figure: <alt>` below them; `extract_image_descs` correctly skips image refs inside table rows so an in-cell icon is not double-counted.
4. **Image descriptions are never generated.** `parser.py:313` (`ocr_text = "" if caption.strip() else images.ocr_image(img)`) + `images.py:106-114` (`resolve_description`: caption → OCR → `""`). Content-addressed naming over the *encoded* bytes (`images.py:42-49`) with `if not path.exists()` — re-ingest is idempotent per asset. Matches README §"Images and icons".
5. **The `pypdfium2` crop path is properly guarded.** `parser.py:254-257` wraps `_render_page` in `except Exception`, so a missing `pypdfium2` degrades to "no cell crops" with a log line instead of a traceback; `_crop_md` (`parser.py:295-297`) and `_picture_md` (`parser.py:317-319`) do the same per image. Losing an image never aborts an ingest.
6. **Reading-order orphan recovery genuinely works.** `_TreeBuilder.pending_orphans` (`sectioner.py:242`, `317-334`, `378-379`) reattaches a deep clause emitted before its parent; reproduced with the ICAO 3.6.3 case — `3.6.2` stays clean, all four bodies land under `3.6.3`.
7. **Appendix/attachment id namespacing prevents collisions.** `appendix-2.1-1` vs `appendix-2.5-1`, `attachment-1-2.1` vs chapter `2.1` — verified in my own runs, not just the tests.
8. **`uncovered()` + `_warn_uncovered` is a real content-loss latch.** Non-heading items that no unit carries are named with page numbers in the report (`ingestcmd.py:36-46`, `81`).
9. **`tests/test_ingest_seam.py` is a genuine trip-wire**: it regenerates `tests-gate/fixtures/pending-kb/` from `scaffold_doc()` and byte-compares the committed tree. Ingest output cannot drift silently.
10. **`icao-annex-3` is clean**: 4 sections, all 490–1074 tokens (100 % inside the 300–5000 band), 0 fallback ids, 0 caption/label titles, 0 ordering anomalies.
11. **Re-ingest destructiveness is documented** (`README.md:320`, explicitly: "chapters previously ingested but omitted this time are gone, not preserved").

---

## 3. Findings by severity

### F1 — CRITICAL(-ish, rated **HIGH**): non-structural headings become sections, and the ingest report says nothing — C3 breached on both halves

C3: *"running page headers, 'Source/Content:'-style labels and table captions **must not** become sections; unparsed headings fall back to a derived id **WITH a warning in the ingest report**."*

**Mechanism.** `_TreeBuilder.feed` (`sectioner.py:245-269`) has exactly two noise filters:
* `sectioner.py:252-257` — drop a heading with no alphanumeric char (`"_____"`);
* `sectioner.py:258-264` — demote a heading that **ends with** `:`.

Anything else that fails `parse_section_id` goes to `_attach_fallback` (`sectioner.py:336-371`) and becomes a section. There is no caption test, no all-caps/running-header test, no "label with colons in the middle" test. And the only `logger.warning` (`sectioner.py:353-357`) sits in the `x{n}` last-resort branch, which is reached **only when the slug is empty** — the repo's own test admits that is unreachable: *"an alnum char that `\w` drops (to force an empty slug) does not exist"* (`tests/test_sectioner.py`, `test_last_resort_xn_id_logs_warning`, which asserts **no** warning is emitted).

**Repro — real `kb ingest` CLI, docling stubbed** (`scratchpad/A/e2e_report.py`):

```
sectioning: heading patterns
  [warn] bookmark section '5.139' not found in the extracted tree
  [warn] bookmark section '5.15' not found in the extracted tree
Ingested 'demo': 6 sections, 2 files in …\.kb\demo
Summarize skipped. …

section ids: ['5', '5.6', '5.6-commentary',
              '5.6-table-5-6-airport-and-heliport-sid-recor',
              '5.6-used-on-runway-record-length-1-character', '5.7']
```

Three of the six "sections" are a `COMMENTARY` block, a table caption and a `Used On: … Length: … Character Type: Alpha` label line. **Zero warnings.** Missing-bookmark warnings *do* surface correctly (`ingestcmd.py:83-86` → `cli.py:451`), so the plumbing exists — the fallback path just never uses it.

**Logger visibility (question 3).** `cli.py` never calls `logging.basicConfig` (grep: the only one in the package is `mcp.py:265`). So `logger.warning` falls to `logging.lastResort` (`_StderrHandler`, level WARNING) — verified: `synthetic fallback id 'x1' for unparsed heading 'SomeHeadingNoDigits'` reaches stderr as a bare line, **no `[warn]` prefix, no colour, not part of the report**, and it did not appear in `CliRunner`'s captured output. So even the one warning that exists is not "a warning in the ingest report".

**This is F-D's root cause.** All **10** fallback sections in `.kb/arinc-424` are non-structural:

| id | title | class |
|---|---|---|
| `5.6-x74`, `5.42-x81`, `5.223-x92` | `COMMENTARY` (×3) | repeated non-structural heading |
| `5.7-x75`, `5.10-x77`, `5.23-x78` | `Table 5-6 …`, `Table 5-14 …`, `Table 5-18 …` | table captions |
| `5.35-x79`, `5.77-x85`, `5.115-x87` | `NDB Navaid Record …`, `Preferred Route Record (ET)`, `Enroute Airway Records` | **values of a `Used On:` list** |
| `5.319-x95` | `Used On: Runway Record Length: 1 Character Character Type: Alpha` | label line |

10/10 = noise. The `x{n}` ids are the pre-`2debcbc` legacy the 2026-07-16 spec §9 acknowledges; under today's code the same headings become `5.6-commentary`, `5.7-table-5-6-…`, `5.319-used-on-runway-record-…` — **prettier ids for the same wrong sections, and now with no warning at all** (the old code at least logged one). Also note the *running-header dedupe does not cover this*: `seen` is keyed on the **full** id including the parent prefix (`sectioner.py:358, 361`), so one repeated `COMMENTARY` heading yields one section **per parent** — reproduced: a running header repeated on 5 pages produced `5.1-arinc-…-page-header … 5.4-arinc-…-page-header`, four separate noise sections.

---

### F2 — CRITICAL: body content is attributed to the wrong section id, silently — `§5.83` of the shipped KB contains `§5.84`'s field definition

**Mechanism.** Every non-heading item is appended to `self.stack[-1]` (`sectioner.py:248-251`) — i.e. *whatever heading docling emitted last*. There is no geometry, page or ordering check on body attachment. `order_units` (`sectioner.py:402-417`) re-sorts **units** by heading page, but two headings on the same page keep docling's emission order, and the bodies were already misplaced during tree building. `uncovered()` only asks "does this text exist somewhere in the union of bodies" (`sectioner.py:458-479`) — it cannot see misattribution.

**Evidence in the shipped KB** — `.kb/arinc-424/ch5-navigation-data-field-definitions.raw.md:2884-2918`:

```
## 5.84 RUNWAY TRANS
Definition/Description: This field is used to identify the desired runway transition of the
applicable SID or STAR. … depending on the Company Route/Helicopter Operations Company Route

## 5.83 To FIX
record VIA field (Section 5.77) and whether or not the SID/STAR has explicit runway transitions.
Source/Content: … Used On: Company Route … Length: 5 characters … Examples: RW08L, ALL,
```

The sentence is cut mid-clause. `§5.84` = **72** L3 tokens (a stub); `§5.83` = **265** tokens, all of them `§5.84`'s. §5.83's real "To FIX" definition is **absent from the KB entirely**.

It propagated all the way to L2 (`ch5-navigation-data-field-definitions.md`):

```
## 5.83 To FIX
Defines the desired runway transition for a SID/STAR in Company Route … Length: 5 characters.
```

So `kb query`/`kb get arinc-424 5.83` returns the RUNWAY TRANS spec under the citation `arinc-424 §5.83 (Supplement 22)`. This passed ingest, summarize, `kb build` and the SME PR review, and is undetectable without the source PDF because both neighbours describe plausible-looking fields.

**Scale.** 4 id-ordering inversions in the manifest (`5.84→5.83`, `5.263→5.262`, `5.289→5.288`, `5.315→5.312`), and a structural scan of the 325 L3 sections finds **25 with no `Length:` marker** and **21 with no `Definition:` marker** in a chapter whose every field definition has both. Of the 15 that are also < 120 words, I spot-checked all: `5.152/5.153/5.170/5.171/5.191/5.192/5.193/5.320` are legitimately short ("*This section deleted by Supplement 21*"), but **`5.84`, `5.115`, `5.182`, `5.223`, `5.287`, `5.310`, `5.319`** are truncated — each one's tail sits in the adjacent fallback section or the adjacent numbered section. Example, `5.115`:

```
## 5.115 Directional Restriction
… Source/Content: Direction Restrictions should be derived from official government sources.
They will be coded and supplied as follows:
## 5.115-x87 Enroute Airway Records      ← the coding table lives here
```

**Reproduced synthetically** (`scratchpad/A/adversarial.py`, case 9): headings `5.84` then `5.83` on the same page produce `5.84` = 8 tokens and `5.83` = 220 tokens holding `REST OF 5.84 CONTENT`. Case 9b (different pages) shows `order_units` *does* fix cross-page inversion — so the defect is specifically intra-page.

---

### F3 — HIGH: a numbered heading with **no title** silently collapses onto its chapter id and eats the following text — this is why `5.15` / `5.139` are missing

`_NUMBERED_RE = ^(\d+(?:\.\d+)*)[.\s]+(.*\S)\s*$` (`sectioner.py:81`) requires a non-empty title, so on a bare `"5.15"` the regex backtracks and matches `group(1)="5"`, separator `"."`, `group(2)="15"`:

```
>>> parse_section_id("5.15")
('5', '15')                     # id = the CHAPTER, title = "15"
```

Then `_attach_parsed` (`sectioner.py:299-303`) sees `"5"` already on the stack → **no-op return** → all subsequent body text accumulates into chapter `5`'s own body. Reproduced (case 10):

```
items: 5.0 NAV / body / heading "5.15" / "Orphan body for 5.15. …" / 5.16 Real Field
units: ['5' (429 tok — includes the orphan body), '5.16']      # no 5.15 at all
```

That is exactly the shipped shape: `.kb/arinc-424` is missing ids **5.15, 5.139, 5.155, 5.156, 5.158, 5.159**. 5.155/5.156/5.158/5.159 are benign — the source really says *"5.155 Intentionally Left Blank"* and those lines are preserved as body text in L3 (`…raw.md:4806-4834`) — but **5.15 and 5.139 leave no trace anywhere in L3** (`grep "5\.139" ` → 0 hits), and neither `§5.14` (164 tok) nor `§5.138` (197 tok) shows absorbed content. Their text is either lost or folded invisibly, and nothing warned.

`crosscheck` *would* have caught them — I verified `crosscheck({...}, {"5","5.6","5.7","5.15","5.139","5.320"})` returns the two "not found in the extracted tree" warnings — but the shipped manifests have `ingest: null`, i.e. they were produced by a CLI generation that predates the current pipeline, and `bookmark_ids` swallows *every* exception (`parser.py:340-341: except Exception: return set()`) with no notice, so an unreadable outline silently disables the only cross-check.

---

### F4 — HIGH: the "merge leaves < 200 tokens" and "300–5000 tokens per unit" rules are effectively inert on the flagship document

`_units_from_tree` (`sectioner.py:511-522`) makes small-leaf folding **all-or-nothing per parent**: if folding *every* small leaf would push the parent over `max_unit_tokens`, it folds **none** of them. Chapter 5 of ARINC has 324 children totalling 85 669 tokens, so the branch always takes `fold_predicate = is_depth_fold` — the merge rule never fires.

Measured on `.kb/arinc-424` (`scratchpad/A/measure.py`):

| metric | arinc-424 (325 sec) | icao-annex-3 (4 sec) |
|---|---|---|
| L3 tokens min / median / max | 15 / 177 / 4327 | 490 / 585 / 1074 |
| **< 200 tokens** (the merge threshold) | **189 (58.2 %)** | 0 |
| **< 300 tokens** | **261 (80.3 %)** | 0 |
| **inside the 300–5000 target** | **64 (19.7 %)** | 4 (100 %) |
| > 5000 tokens | 0 | 0 |
| fallback `-x<NN>` ids | 10 | 0 |
| titles with label markers (`Used On:`/`Length:`…) | 1 | 0 |
| titles matching `^(Table\|Figure)\s+\d` | 3 (+`5.149 Figure of Merit`, a false positive) | 0 |
| duplicate ids | 0 | 0 |
| id-ordering inversions | 4 | 0 |
| depth histogram | `{1: 1, 2: 324}` | `{1: 1, 2: 3}` |

Reproduced (`adversarial.py` case 6b): 40 leaves of 140 tokens under chapter 5 → **40 separate units**, all below the threshold. Case 6a (a single small leaf) folds correctly, so the rule works only on small documents.

I do **not** think unconditional folding is the right fix — "each field is its own section" (C3, first clause) directly contradicts "merge < 200 tokens" for a field-definition chapter, and per-field sections are what makes `§5.3`-style citation useful. But as shipped: **80 % of the flagship document's sections miss the framework's own stated size target, the depth cap is the only normalisation rule that ever runs, and nothing measures or reports it.** The spec conflict should be resolved in writing, and `kb ingest` should print the distribution.

---

### F5 — MEDIUM: `crosscheck` reports missing bookmarks but never *extra* sections, and a fallback child can mask a missing parent

Phase-1 §4.3 says *"Section thiếu/thừa → in cảnh báo"* (missing **or extra** → warn). Only "missing" is implemented (`parser.py:428-449`). Verified:

```
units = {5, 5.6, 5.6-commentary, 5.7, 5.7-table-5-6-airport, 5.319-used-on-runway-record}
bms   = {5, 5.6, 5.7, 5.15, 5.139, 5.320}
crosscheck(...) -> ["bookmark section '5.139' …", "bookmark section '5.15' …", "bookmark section '5.320' …"]
units not backed by any bookmark: ['5.319-used-on-runway-record', '5.6-commentary', '5.7-table-5-6-airport']   # never reported
```

An "extra" check against the outline is precisely the signal that would have caught every F1/F-D noise section on the ARINC ingest, for free.

Two further false negatives in the same function:
* `crosscheck({"5.6-commentary"}, {"5.6"}) → []` — the `uid.startswith(bm + "-")` clause (`parser.py:442-443`) lets a *fallback child* satisfy its parent's bookmark, so a genuinely lost section whose noise child survived is reported as covered.
* `crosscheck({"5"}, {"5.1.2.3"}) → []` — bookmarks deeper than `max_depth` are skipped outright (`parser.py:433-434`), which is defensible (they fold) but means a whole missing sub-tree is invisible when its parent unit exists.

---

### F6 — MEDIUM: `kb ingest --sections` deletes chapters it was not asked about, with no confirmation, no dry-run, and no backup — and it destroys human-approved L2 summaries

`scaffold.py:56-57` filters `units` to the named chapters; `scaffold.py:62-63` then does `for stale in doc_dir.glob("*.md"): stale.unlink()` — and `*.md` matches `*.raw.md` too. Reproduced (`scratchpad/A/reingest_test.py`):

```
after full ingest:           _manifest.yaml, ch5-nav.{md,raw.md}, ch6-proc.{md,raw.md}, ch7-comms.{md,raw.md}
  manifest sections: ['5','6','7']
# a reviewer's approved L2 text is written into ch5-nav.md, then:
after re-ingest --sections 6: _manifest.yaml, ch6-proc.{md,raw.md}
  manifest sections: ['6']
  ch5 file still there? False
  human summary survived?  False
```

This is documented (`README.md:320`) and `.kb/` is in git, so it is recoverable — but a typo in `--sections` silently deletes the only copy of every reviewed summary in the omitted chapters, and the CLI prints nothing about the deletion (`cli.py:456-459` only reports what was written). C16 promises `kb init` preserves user state; the same care is absent here. A one-line "removing N chapter(s) not in --sections: 5, 7 — continue? [y/N]" (or `--dry-run`/`--force`) would close it.

Two related notes: `doc_to_items` unlinks every entry of `assets/` before re-deriving (`parser.py:133-135`) and will raise on a subdirectory (`Path.unlink()` on a dir); and with `--sections`, assets are derived for the *whole* document, so assets belonging to unwritten chapters are left orphaned.

---

### F7 — MEDIUM: duplicate section ids are still producible by ingest, and `kb get`/`slice_section` silently return only the first

Commit `83f6c86` ("approve reaches sections whose ids repeat", #22) states the reality: *"ICAO Annex 8: 325 sections, 103 unique ids"*. `approve` was fixed; the read path was not.

* Ingest still produces duplicates in bookmark/parts mode — each part gets its **own** `_TreeBuilder` with its own `seen` (`sectioner.py:217-230`), and numeric parts are **not** namespaced (`_namespace`, `sectioner.py:271-294`). Reproduced: parts `[5, 6]` with a `5.3` heading physically inside chapter 6's page range →
  `[('5','5'), ('5.3','5'), ('6','6'), ('5.3','6')]`, i.e. `5.3` twice, in two different files.
* `_get_section_in` takes `next((s for s in manifest.sections if s.id == section_id), None)` (`query.py:256`) and `slice_section` returns the first `## <id>` in the file (`mdutils.py:36-49`). Verified: on `"## 5.3 A … ## 5.4 B … ## 5.3 A"`, `slice_section(md,"5.3")` returns only `'## 5.3 A\n\nFIRST BODY'`.

Consequence for a doc like Annex 8: ~2/3 of sections are unreachable by `kb get`/`kb resolve`, and the citation format `<doc> §<id>` cannot name them. Ingest should either namespace numeric parts too, or the manifest should carry a unique key (`<file>#<id>`).

---

### F8 — MEDIUM: a custom `--chapter-pattern` whose identifier group contains a space produces sections that can never be sliced

`_compile_heading` (`sectioner.py:84-91`) validates only "compiles" and "≥ 2 groups". `_HEADING_RE` in mdutils is `^## (?P<sid>\S+)[ \t]+(?P<title>.+?)\s*$` (`mdutils.py:10`) — the id must be whitespace-free. Reproduced:

```
--chapter-pattern '^(part\s+[A-Z])\s*[-–—.:]\s*(.*)$'  on "Part A - Definitions"
units: [('Part A','Definitions'), ('Part B','Rules')]
slice_section('Part A') -> None      # kb get / kb resolve / build all fail
slice_section('Part B') -> None
```

The scaffold, the manifest and `kb build` all succeed; only retrieval is dead. Same class: an **empty** title makes `slice_section` return `None` (`## 5.15 ` → `None`) — the sectioner cannot currently emit one (every branch of `parse_section_id` returns a non-empty title, and fallbacks use the normalised heading), but there is no invariant guarding it. Regex-special characters in ids are safe (comparison is exact string, and `slugify_id` strips them): `5.6-c-net-notes` slices fine.

---

### F9 — LOW: silent drops the report cannot see

* `parser.py:163-166`: a `table` item whose `export_to_markdown()` returns empty/whitespace is skipped **before** it becomes a `DocItem`, so `uncovered()` structurally cannot detect it. One log-free lost table.
* `mdutils.py:74-84` `extract_tables` requires `len(current) >= 2`, so a one-line pipe table reaches L3 but **not** L2. Reproduced: `| only one row |` present in `.raw.md`, absent from `.md`. (Same root as lead finding F-B, seen from the ingest side.)
* `images.py:117-127`: `rapidocr` is **not declared** in the `ingest` extra (`pyproject.toml:34` = `docling, imagehash, Pillow, pypdfium2`). Without it, `ocr_image` logs once and returns `""` → captionless images get an empty alt → `extract_image_descs` drops blanks → **no `Figure:` line in L2 at all**, silently.
* `tableimages.py:145`: `f" {current} {text} ".replace("  ", " ")` rewrites whitespace inside the cell it injects into, so the L3 table is not byte-identical to docling's own export (L2 and L3 stay consistent with each other, so C1 is unaffected).
* Heading text is not preserved verbatim in L3: `CHAPTER 2. GENERAL` → `## 2 GENERAL`, `5.0 NAV` → `## 5 NAV`. Fine for ids, but "L3 = full original" is approximate at heading lines.
* `_recover_missed_glyphs` re-opens and re-renders the PDF once per table with missing glyph cells (`parser.py:268-275`) and re-logs the same failure each time.
* The bundled `.kb/*/assets` directories do not exist — the whole image/icon path is unexercised by the shipped data.

---

## 4. Answers to the specific questions

**Q1 — which phase-1 §4 rules are actually implemented?**

| §4 rule | Status | Where |
|---|---|---|
| §4.2 heading → standard id (`5.3`, `ch2`, appendix/attachment) | **Implemented** | `parse_section_id` `sectioner.py:135-155` |
| §4.2 unparsed heading → derived id **+ warning in the ingest report** | **Half**: id yes (`_attach_fallback` 336-371); **warning effectively never fires** (only the unreachable `x{n}` branch, 351-357), and it bypasses the report (stderr via `logging.lastResort`) | F1 |
| §4.3 bookmark cross-check, missing **and extra** | **Half**: missing only; extra never reported; silent when `bookmark_ids` throws | F5 |
| §4.4-1 depth ≤ 3 | **Implemented and effective** — the only normalisation rule that fires on ARINC (`is_depth_fold`, `sectioner.py:492-493`) | verified cases 5, appendix variant |
| §4.4-2 merge leaves < 200 tokens into parent | **Implemented but all-or-nothing per parent** → inert on any large chapter; 58 % of ARINC sections are below the threshold | F4 |
| §4.4-3 target 300–5000 tokens | **Not implemented as a check**: `max_unit_tokens` only gates the fold decision; nothing measures, warns, or reports. 19.7 % of ARINC sections comply | F4 |
| §4.5 tables verbatim in L3 **and** L2, copied by code | **Implemented** | §2.2 |
| §4.6 one L2 + one L3 per top-level part, `## <id> <title>` anchors | **Implemented** | `scaffold.py:71-105` |
| §4.7 `--sections` scaffolds only chosen chapters | **Implemented, destructively** | F6 |
| Running headers / labels / captions must not become sections (C3) | **Not implemented** except "ends with `:`" and "no alnum char" | F1 |

**Q3 — what the user sees.** `sectioning: <mode>` · `[warn] content never reached L3 (page N): …` (capped at 10, `ingestcmd.py:33,42-46`) · `[warn] bookmark section 'X' not found …` · `Ingested '<id>': N sections, M files in <dir>`. **Not shown:** how many sections are fallback ids, which headings were demoted, that a bookmark cross-check was skipped, the token distribution, or that chapters were deleted. The sectioner's own `logger.warning` reaches stderr (Python's `lastResort` handler is active because nothing calls `basicConfig`) but as an unprefixed, uncoloured line outside the report.

**Q4 — adversarial results** (full transcript in `scratchpad/A/adversarial.py`):

| case | outcome |
|---|---|
| running header on every page (unparsed) | **one fallback section per parent** (`5.1-arinc-…`, `5.2-arinc-…`, …), no warning |
| table caption as `SectionHeaderItem` | **own section** `5.7-table-5-6-airport-and-heliport-sid-recor`, no warning |
| `Source/Content:` (ends with `:`) | correctly demoted to `**Source/Content:**` body text, no section |
| `Used On: … Length: … Character Type: Alpha` (colons mid-string) | **own section**, no warning |
| `Appendix A` then `A.1` | `appendix-a` + `appendix-a-a-1-sub-of-appendix` — `A.1` is *not* recognised as a dotted number (only `\d+`), so it is slugified into the title. Content preserved, id ugly |
| nesting deeper than 3 | correct: `1.1.1.1` and `1.1.1.1.1` folded into `1.1.1` as `###` |
| tiny leaf < 200 tok, alone | correctly merged into parent (`### 5.1 Tiny Field`) |
| 40 tiny leaves | **none merged** (all-or-nothing cap) → 40 undersized units |
| two consecutive identical headings | correct: one unit, contents merged |
| heading with trailing page number (`ARINC SPEC 424 - Page 129`) | **own fallback section**; a *pure* digit heading (`1234567890123`) is correctly demoted to body |
| `5.84` then `5.83`, same page | both sections created **in that order**, 5.84 truncated to 8 tokens, its body under 5.83. Different pages → `order_units` fixes it |
| `5.15` with no title | **no `5.15` section at all**; id collapses to `5`, body silently appended to the chapter |

**Q5 — L3 completeness / scaffold.** Covered in §2 (items 1-3) and F9. Nothing in the label matrix is dropped except page furniture; list-item bullets and list nesting are flattened to plain paragraphs (`item.text` only), and a picture's caption appears twice (once as the `caption` text item, once as the image's alt text).

**Q6 — images.** Content-addressed over encoded bytes; icon(≤128 px)→optimised PNG, figure→WebP q80 (`images.py:27-49`). Description = caption → OCR → `""`, never generated (`images.py:106-114`, `parser.py:313`). Duplicates: deduped **within** a doc (`if not path.exists()`), stored once per doc dir across docs (assets dirs are per-doc) — matches the README claim. `pypdfium2` crop path guarded correctly (§2.5). Caveats in F9: undeclared `rapidocr`, per-table page re-render, `_PIPE`/whitespace rewrite in `inject`. Note the hash is only as deterministic as the installed Pillow/libwebp encoder — fine for a KB, but it is not a byte-reproducibility guarantee across environments.

**Q7 — section-id contract.** Empty title → `slice_section` returns `None` (unreachable section, manifest still lists it) — currently unreachable from the sectioner but unguarded. Ids with spaces → same failure, and **are** reachable via a custom `--chapter-pattern` (F8). Regex-special chars → safe. Repetition → still producible (F7) and only `approve` handles it; `get`/`slice_section`/`build` take the first occurrence silently.

---

## 5. Criteria scorecard

| Criterion | Verdict | One-line why |
|---|---|---|
| **C2 — L3 = full original, nothing cut** | **Partially met** | Deny-list extraction keeps footnotes/captions/formulas/list items, and `uncovered()` catches unplaced text — but content is attributed to the **wrong** section id (F2: §5.83 holds §5.84's spec), `5.15`/`5.139` have no trace at all (F3), and a table docling fails to export vanishes unobserved (F9). |
| **C2 — L1 `_manifest.yaml`, one line per section** | **Met** | `scaffold.py:90-97` writes id/title/file/tokens per unit; `test_ingest_seam.py` pins the shape. |
| **C3 — sectioning** | **Not met** | ✗ noise headings become sections (F1); ✗ no warning for fallback ids (F1); ✗ extra-section cross-check absent (F5); ✗ 300–5000 target met by 19.7 % with no measurement (F4); ✗ < 200-token merge inert on the flagship doc (F4); ✓ standard ids; ✓ depth ≤ 3. |
| **C16 — re-ingest preserves user state** | **Partially met** | Documented as a full replace (README:320) and git-recoverable, but `--sections` silently deletes unnamed chapters and every approved L2 summary in them, with no confirmation or dry-run (F6). Scaffold trip-wire tests (`test_ingest_seam`) are a genuine strength. |
| C1 (tables) — ingest side only | **Met (ingest side)** | Tables copied byte-for-byte into L2 by code (§2.2); the one-row-table gap is `extract_tables`, reported to reviewer covering C1/F-B. |

---

## 6. Top 3 recommendations

1. **Make the ingest report tell the truth about sectioning quality.** Extend `ScaffoldReport`/`run_ingest` to emit, through the existing `warn`/`echo` callbacks (`ingestcmd.py:81-86`): every fallback id with its heading text; every unit outside 300–5000 tokens (counts, not a list); and **extra** sections not backed by a bookmark (`crosscheck` already has both sets — add the reverse direction). Add `logging.basicConfig` in `cli.py` so `sectioner`/`parser` warnings are formatted like the rest of the CLI instead of leaking as bare stderr lines. This alone converts F1, F4 and F5 from silent to visible.
2. **Fix the two id defects that corrupt content, then re-ingest the bundled KB.** (a) Anchor `_NUMBERED_RE` so a title-less `"5.15"` yields `("5.15", "")` (or is demoted to body) instead of collapsing onto the chapter id — F3, verified one-liner. (b) Add a heading-noise filter before `_attach_fallback`: reject headings matching `^(Table|Figure|Fig\.|Diagram)\s+\S+`, headings containing two or more `Label:` groups, and headings that repeat verbatim across ≥ 3 pages — F1/F-D, 10/10 of ARINC's fallback sections are in those three classes. Then re-ingest `arinc-424` (F-A's stale `--redo` and F-C's template table would go with it) and diff `§5.83`/`§5.84` against the PDF; today the shipped KB cites the wrong field definition.
3. **Close the retrieval-side id contract.** Namespace numeric parts the way appendices are namespaced (or key manifest sections on `<file>#<id>`) so ingest cannot emit duplicate ids (F7); validate at `_compile_heading` that a chapter/appendix/attachment pattern cannot yield an id containing whitespace, and assert a non-empty title in `scaffold_doc` (F8). Add a `--dry-run`/confirmation to `kb ingest --sections` listing the chapters it is about to delete (F6).

---

## 7. Incidental (cross-area, for the lead)

During this review the shared checkout went dirty with:

```
 M .kb/arinc-424/_manifest.yaml     +ingest: null
 M .kb/icao-annex-3/_manifest.yaml  +ingest: null
```

Bisected against every ingest test file individually — all clean — so this is not a test side effect. `build.py:77` (`models.save_yaml_model(manifest_path, manifest)`, the C5 token recount) re-serialises the committed manifest and materialises the pydantic default `ingest: null` that the shipped file omits. i.e. **`kb build` mutates git-tracked files as a side effect of a read-style command**, producing a spurious one-line diff on every run — a docs-as-code (C16) noise issue for whoever owns C5. I restored both files with `git checkout --` and removed my own stray `kbtest/`, `kbtest2/` scratch dirs; the tree is clean again. If another reviewer was mid-experiment on `.kb/`, that revert was mine.
