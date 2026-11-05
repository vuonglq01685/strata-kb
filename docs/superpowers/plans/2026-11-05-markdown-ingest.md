# Markdown Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb ingest <file>.md --id <doc>` writes L3/L2/manifest/spans/L3-check exactly like a PDF ingest, with heading ids normalized by the sectioner rules, and the `/kb-l3-fix` loop verifying AI drafts against the source MD.

**Architecture:** A new `ingest/mdreader.py` turns MD into `DocItem`s by slicing verbatim source lines (markdown-it-py token `.map`), then the existing `sectioner` (new `md_mode`) and `scaffold` run unchanged. A small source-context seam (`l3check/source.py`) gives the L3 check, lint and fix either the PDF text layer or synthetic MD pages; `manifest.ingest.source_kind` picks which.

**Tech Stack:** Python 3, typer, pydantic, markdown-it-py (core dep), pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-markdown-ingest-design.md`

## Global Constraints

- Version 1.34.4 → 1.34.5; CHANGELOG entry `## 1.34.5 — <date>`.
- MD path must not import docling, pypdfium2, Pillow or rapidocr (works without the `ingest` extra).
- PDF ingest output byte-identical: no existing test or fixture under `tests/` or `tests-gate/` changes (`tests/test_ingest_seam.py` stays green untouched).
- Suffixes `.md` / `.markdown`, case-insensitive, select the MD path.
- `IngestConfig.source_kind: Literal["pdf", "md"] = "pdf"` (old manifests load unchanged).
- Only heading lines are rewritten; every other source byte (after CRLF→LF and front-matter removal) reaches L3 unchanged, except rewritten image targets.
- Images copied only for `.png` / `.webp` inside the source file's directory tree, to `.kb/<doc>/assets/<sha256>.<ext>`.
- Refusal messages (exact copy):
  - `'<id>' was ingested from a PDF — ingest the Markdown under a new --id`
  - `'<id>' was ingested from Markdown — ingest the PDF under a new --id`
  - `<file>: fenced code holds a '## ' heading line at line(s) <n>, <m> — move it out of the fence or indent it`
  - `source is Markdown: no page images`
- CI gate: `ruff check .`, `ruff format --check .`, `pyright`, `pytest -q -n auto`.

## Review Focus

1. **BOM + CRLF source** → same L3 as the LF/no-BOM file. Test in Task 2.
2. **Heading id behind inline markup** (`## **1.2** Scope`, `## 1.2 [Scope](x.md)`) → id `1.2`, title kept as written. Test in Task 2.
3. **Image path escaping the source tree** (`![](../../secret.png)`, absolute path, symlink out) → not copied, link kept, warning. Test in Task 3.
4. **MD file with no heading at all** → one unit, nothing in `uncovered`. Test in Task 6.
5. **Non-UTF-8 file** → `ValueError` "`<file>` is not UTF-8", nothing written. Test in Task 6.

---

### Task 1: `source_kind` in the manifest

**Files:**
- Modify: `src/strata_kb/models.py:82-87` (`IngestConfig`)
- Modify: `src/strata_kb/ingest/scaffold.py:270-283, 389-394` (`scaffold_doc`)
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Produces: `IngestConfig.source_kind: Literal["pdf", "md"] = "pdf"`; `scaffold_doc(..., source_kind: Literal["pdf","md"] = "pdf")` writes it.

- [ ] **Step 1: Write failing tests** `test_manifest_records_source_kind_md` (scaffold with `source_kind="md"` → loaded manifest `.ingest.source_kind == "md"`) and `test_manifest_without_source_kind_loads_as_pdf` (a YAML manifest whose `ingest:` lacks the key loads with `source_kind == "pdf"`).
- [ ] **Step 2: Run** `pytest tests/test_scaffold.py -k source_kind -v` → FAIL.
- [ ] **Step 3: Implement** the field and the keyword.
- [ ] **Step 4: Run** same command → PASS; `pytest tests/test_scaffold.py tests/test_ingest_seam.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: record ingest source kind in the manifest`.

### Task 2: MD reader

**Files:**
- Create: `src/strata_kb/ingest/mdreader.py`
- Test: `tests/test_mdreader.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class MdDoc:
      items: list[DocItem]          # sectioner.DocItem
      title: str | None             # sole unnumbered H1, else None
      warnings: list[str]
  def read_md(text: str, name: str) -> MdDoc        # raises ValueError (fenced heading)
  def md_pages(text: str) -> dict[int, str]          # synthetic pages for checks
  ```
- Rules:
  - Strip a leading U+FEFF; normalize CRLF/CR to LF.
  - Front matter (`---` at line 1 … closing `---`) is dropped, with one warning `front matter dropped (<n> lines)`.
  - Sole unnumbered H1 → `title`, not an item. Otherwise every heading is an item.
  - Heading → `DocItem("heading", text, level=<#count>)`. `text` = source heading text minus `#` markers, with emphasis/link markup removed only **when it wraps the leading id token** (so `parse_section_id` sees `1.2 Scope`). Title words stay as written.
  - Every other top-level block → `DocItem(kind, "\n".join(source_lines[map[0]:map[1]]).rstrip("\n"))`. Do not `strip()`: leading indent of an indented code block survives. Kinds: `paragraph/html/blockquote/hr`→`"text"`, `table`, `fence/code_block`→`"code"`, `bullet_list/ordered_list`→`"list"`, a paragraph that is only an image → `"image"`.
  - `page` = 1 + index of the top-level (lowest-level-present) heading block the item falls in; `bbox=None`.
  - Any fence/code-block line matching `^#{2,3} ` → `ValueError` with the Global Constraints copy, all offending 1-based source line numbers.
  - `md_pages(text)` = `{page: detect.strip_markdown(<page's source text>)}` using the same page boundaries; a file with no heading is the single page 1.
  - Use `markdown_it.MarkdownIt("commonmark").enable("table")`.

- [ ] **Step 1: Write failing tests:**
  - `test_blocks_are_verbatim_source_lines`: table, list with nested items, blockquote, HTML block, ```` ``` ```` fence → each item `.text` equals the exact source slice.
  - `test_indented_code_keeps_first_line_indent`.
  - `test_front_matter_dropped_with_warning`.
  - `test_sole_unnumbered_h1_is_title` / `test_numbered_h1_is_a_heading_item` / `test_two_h1_are_items`.
  - `test_heading_level_from_hashes`.
  - `test_id_behind_bold_or_link_is_parsed` (Review Focus 2): `## **1.2** Scope` and `## 1.2 [Scope](x.md)` → `sectioner.parse_section_id(item.text)[0] == "1.2"`.
  - `test_crlf_and_bom_same_items_as_lf` (Review Focus 1).
  - `test_fenced_heading_line_refused`: source with ```` ```\n## step\n``` ```` at line 5 → `ValueError` whose message ends `at line(s) 6 — move it out of the fence or indent it`.
  - `test_pages_follow_top_level_headings` and `test_md_pages_strip_markdown`.
  - `test_reader_imports_no_docling`: run `read_md` in a subprocess with `sys.modules["docling"] = None`; it must succeed.
- [ ] **Step 2: Run** `pytest tests/test_mdreader.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** `mdreader.py` per the rules above.
- [ ] **Step 4: Run** `pytest tests/test_mdreader.py -v` → PASS.
- [ ] **Step 5: Commit** `feat: Markdown reader for ingest`.

### Task 3: Local image copy

**Files:**
- Modify: `src/strata_kb/ingest/mdreader.py`
- Test: `tests/test_mdreader.py`

**Interfaces:**
- Consumes: `MdDoc` (Task 2).
- Produces: `def copy_images(items: list[DocItem], source: Path, assets_dir: Path) -> tuple[list[DocItem], list[str]]` → new items (never mutate input) + warnings.
- Rules: for each `![alt](target)` in any item: target relative, not a URL, `(source.parent / target).resolve()` is a regular file **and** `is_relative_to(source.parent.resolve())`, suffix `.png`/`.webp` (case-insensitive) → write bytes to `assets_dir/<sha256(bytes)>.<lower ext>`, rewrite target to `assets/<sha>.<ext>`, alt unchanged. Otherwise keep as written, warn `image kept as written: <target> (<reason>)` with reason `not png/webp`, `missing`, `outside the source folder`. `assets_dir` is cleared first (same as `parser.doc_to_items`). Pure hashlib; no Pillow.

- [ ] **Step 1: Write failing tests:** `test_png_copied_and_link_rewritten`, `test_same_image_twice_one_asset`, `test_jpg_kept_with_warning`, `test_missing_image_kept_with_warning`, `test_path_outside_source_tree_not_copied` (Review Focus 3: `../x.png`, absolute path, symlink pointing outside), `test_url_image_untouched`, `test_input_items_not_mutated`.
- [ ] **Step 2: Run** `pytest tests/test_mdreader.py -k image -v` → FAIL.
- [ ] **Step 3: Implement** `copy_images`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: copy local png/webp images of a Markdown source`.

### Task 4: Sectioner `md_mode`

**Files:**
- Modify: `src/strata_kb/ingest/sectioner.py` (`build_units_with_notes`, `_build_tree`, `_TreeBuilder.__init__/feed/_attach_parsed/_attach_fallback`, `_Node`, `_units_from_tree`)
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Produces: `build_units_with_notes(items, ..., parts=None, md_mode: bool = False)`; `build_units` unchanged.
- With `md_mode=True` only:
  - No demotion: `_noise_reason`, the trailing-`:` rule and `_repeated_unparsed_headings` are not applied; every heading opens a node.
  - A repeated id does **not** reopen `self.seen[sid]`: it opens a new node; `_dedupe_ids` then renames it `-N` and records a `Duplicate` note.
  - Unnumbered heading nesting: `_Node` gains `md_level: int = 0`. Before attaching a fallback node of level L, pop the stack while the top node's `md_level >= L` (root has 0). Numbered nodes still place by their number and record their `md_level`.
  - A non-root node with an empty body and no kept children still emits a unit (body `""`), and a note/warning `heading with no text: <id>`.
  - `_reorder_inverted_pages` is skipped (no bbox).
- `md_mode=False`: behavior byte-identical.

- [ ] **Step 1: Write failing tests:** `test_md_mode_repeated_id_renamed` (`2.1`, `2.2`, `2.1` → ids `2.1`, `2.2`, `2.1-2`, a Duplicate note, title "Baz" present in its unit), `test_md_mode_unnumbered_nest_by_level` (`# A`/`## B`/`## C`/`# D` → B and C under A, D sibling of A), `test_md_mode_repeated_unnumbered_subheadings_kept` ("Notes" under three top headings → three units, none demoted), `test_md_mode_colon_and_caption_headings_kept`, `test_md_mode_part_heading_above_numbers` (`# Part I`, `## 1 Intro`, `## 2 Scope` → ids include `1`, `2` flat and a fallback unit whose title is `Part I`), `test_pdf_mode_unchanged` (one existing PDF-shaped item list gives identical units with and without passing `md_mode=False`).
- [ ] **Step 2: Run** `pytest tests/test_sectioner.py -k md_mode -v` → FAIL.
- [ ] **Step 3: Implement** the flag through `_build_tree` → `_TreeBuilder`.
- [ ] **Step 4: Run** `pytest tests/test_sectioner.py tests/test_ingest_seam.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: sectioner md_mode — no PDF furniture rules, level nesting`.

### Task 5: Source context seam + MD-aware lint

**Files:**
- Create: `src/strata_kb/l3check/source.py`
- Modify: `src/strata_kb/l3check/lint.py` (`UnitContext`, `_r6`, `lint_unit`, `lint_file`, `lint_doc`, remove `load_pdf_context` → re-export from `source`)
- Modify: `src/strata_kb/l3check/fixchecks.py:166-183` (`_check_contract`)
- Test: `tests/test_l3fix_lint.py`, `tests/test_l3check_source.py` (new)

**Interfaces:**
- Produces:
  ```python
  # l3check/source.py
  SourceKind = Literal["pdf", "md"]
  def source_kind(kb_dir: Path, doc_id: str) -> SourceKind      # from manifest.ingest, default "pdf"
  def load_context(source: Path, work_dir: Path, doc_id: str, kind: SourceKind
                   ) -> tuple[dict[int, str], dict[int, list[str]]]
  ```
  PDF → current `load_pdf_context` body. MD → `(mdreader.md_pages(text), {})`.
- `UnitContext` gains `md: bool = False`. `lint_file(raw_md, contexts, md: bool = False)` and `lint_doc(..., md: bool = False)` pass it to the neutral context too.
- `_r6` with `md=True`: no `_QUOTE`, `~~~` or `DEEP_LIST` issues. All other rules unchanged.
- `_check_contract` sets `md = t.manifest.ingest is not None and t.manifest.ingest.source_kind == "md"`.

- [ ] **Step 1: Write failing tests:** `test_md_lint_allows_blockquote_html_tilde_deep_list` (each flagged with `md=False`, clean with `md=True`), `test_md_lint_keeps_r3_r4_r9`, `test_load_context_md_pages_no_furniture`, `test_source_kind_defaults_to_pdf`.
- [ ] **Step 2: Run** `pytest tests/test_l3fix_lint.py tests/test_l3check_source.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_l3fix_lint.py tests/test_l3check_source.py tests/test_l3fix_apply.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: L3 source context seam; lint relaxes R6 for Markdown sources`.

### Task 6: `run_ingest` MD path

**Files:**
- Modify: `src/strata_kb/ingestcmd.py` (`IngestOptions`, `_run_ingest`, `l3_check`)
- Modify: `src/strata_kb/cli.py:854-911` (`ingest` builds `IngestOptions(source=...)`)
- Test: `tests/test_ingest_md.py` (new)

**Interfaces:**
- Consumes: `read_md`, `copy_images` (Tasks 2–3), `md_mode` (Task 4), `scaffold_doc(source_kind=)` (Task 1), `source.load_context` (Task 5).
- Produces: `IngestOptions.source: Path` (renamed from `pdf`; update every caller); `def is_md(path: Path) -> bool`; `l3_check(opts, units, notes, slices, pages: dict[int,str], furniture: dict[int,list[str]])`.
- `_run_ingest` order for MD: validate id → authored refusal → kind-switch refusal (previous manifest `source_kind` ≠ new kind, both directions, Global Constraints copy) → decode UTF-8 strictly (`ValueError: <file> is not UTF-8`) → `read_md` → `copy_images` → warn `--no-bookmarks has no effect on Markdown` when set → `build_units_with_notes(items, config=heading_config, md_mode=True)` → same warnings/uncovered → skip bookmark cross-check → `scaffold_doc(title=md.title or doc_id, source_kind="md", used_bookmarks=False)` → spans with `last_page=max(md_pages)` → `l3_check` with MD context → `_reset_fix_record`. PDF branch: same calls as today, `doc` only used inside it.

- [ ] **Step 1: Write failing tests** (MD fixture written in `tmp_path`, includes table, list, code fence, png image, numbered + unnumbered headings):
  - `test_md_ingest_writes_l3_l2_manifest_spans` (files exist, `source_kind == "md"`, `source_sha256` = sha256 of the file bytes, title from H1).
  - `test_md_ingest_every_source_word_in_l3` (strip_markdown words of source ⊆ L3 words, same order).
  - `test_md_ingest_headingless_file_one_unit` (Review Focus 4).
  - `test_md_ingest_non_utf8_refused_nothing_written` (Review Focus 5).
  - `test_md_into_pdf_doc_refused` / `test_pdf_into_md_doc_refused` (exact copy).
  - `test_md_reingest_resets_fix_record`.
  - `test_md_ingest_authored_refused`.
  - `test_md_ingest_without_docling` (subprocess, `sys.modules["docling"] = None`).
- [ ] **Step 2: Run** `pytest tests/test_ingest_md.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_ingest_md.py tests/test_ingest_cli.py tests/test_ingest_seam.py tests/test_l3check_cli.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: kb ingest accepts a Markdown source`.

### Task 7: CLI — `--source` and MD refusals

**Files:**
- Modify: `src/strata_kb/cli.py` (`ingest` argument `source` + help "Source PDF or Markdown file"; `_l3_fix_preflight`; `l3_fix_apply`; `l3_lint`; `l3_fix_pages`)
- Test: `tests/test_l3check_cli.py`, `tests/test_ingest_cli.py`

**Interfaces:**
- Consumes: `source.source_kind`, `source.load_context` (Task 5).
- `l3 fix apply`, `l3 lint`, `l3 fix pages`: option `--source` with `--pdf` kept as alias (`typer.Option(..., "--source", "--pdf")`). Preflight message becomes `<file> is not the source <id> was ingested from`.
- MD doc: `l3 fix pages` and any `--from-image` → `_l3_fix_refuse("source is Markdown: no page images")`. `l3 lint` / `fix apply` pass `md=True` through.

- [ ] **Step 1: Write failing tests:** `test_fix_apply_md_passing_draft_applied`, `test_fix_apply_md_draft_adding_word_rejected` (reason starts `words:`), `test_fix_apply_md_from_image_refused`, `test_fix_pages_md_refused`, `test_fix_apply_wrong_source_refused`, `test_pdf_alias_still_works`, `test_l3_lint_md_clean_with_blockquote`.
- [ ] **Step 2: Run** `pytest tests/test_l3check_cli.py -k "md or alias or wrong_source" -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_l3check_cli.py tests/test_ingest_cli.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: kb l3 commands take --source; refuse page images for Markdown`.

### Task 8: Skills, guides, release

**Files:**
- Modify: `.claude/skills/kb-ingest/SKILL.md`, `.claude/skills/kb-l3-fix/SKILL.md`, and every template copy under `src/strata_kb/templates/init/` named `*kb-ingest*` / `*kb-l3-fix*` (claude-skill, claude-command, cursor, copilot)
- Modify: `docs/src/guide-hub.{en,vi}.md`, `docs/src/guide-child.{en,vi}.md`; rebuild `docs/strata-guide-*.pdf` with `python docs/src/build_pdf.py`
- Modify: `CHANGELOG.md`, `pyproject.toml` (`version = "1.34.5"`), `uv.lock` if it pins the project version

- [ ] **Step 1: Edit skills:** kb-ingest accepts `.md`; kb-l3-fix says "source file (PDF or Markdown)", hard rule 4 for MD = "a word may enter L3 only where the source Markdown has it", `--source` in commands, no `--from-image` / `kb l3 fix pages` for MD.
- [ ] **Step 2: Guides:** one short "Ingest a Markdown file" subsection (en + vi, same facts): command, rules applied, refusals (kind switch, fenced `## `), images (png/webp copied), MD is the master — edit and re-ingest.
- [ ] **Step 3: Run** `pytest -q -n auto` (catches template/skill drift tests and guide fact tests) → PASS; `python docs/src/build_pdf.py` → PDFs regenerated.
- [ ] **Step 4: CHANGELOG + version**, then full gate: `ruff check . && ruff format --check . && pyright && pytest -q -n auto` → all pass.
- [ ] **Step 5: Commit** `docs: Markdown ingest in skills and guides — 1.34.5`.
