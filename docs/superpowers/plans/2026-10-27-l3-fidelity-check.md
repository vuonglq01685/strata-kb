# L3 fidelity check (v1.31.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After `kb ingest`, compare every L3 section with the PDF text layer, flag suspect sections in `.kb/<doc>/_l3check.yaml` (with a Sonnet verdict on broken-paragraph flags), and block summarize/build/publish until a reviewer confirms; plus two hub UI tweaks and the `sonnet` model default.

**Architecture:** New package `src/strata_kb/l3check/`: `report.py` (file schema, load/save, gate, confirm, merge), `detect.py` (pure checks over strings: no PDF, no I/O), `agent.py` (LLM verdicts on `break` findings). `ingestcmd` gathers the inputs only ingest has (units, notes, page texts via pypdfium2, page furniture from the docling doc) and writes the report. Existing commands consult `report.blocked_docs()`.

**Tech Stack:** Python 3, typer, pydantic v2, PyYAML, pypdfium2 (ingest extra), pytest, ruff, pyright.

**Spec:** `docs/superpowers/specs/2026-10-27-l3-fidelity-check-design.md`

## Global Constraints

- Never write L3 (`*.raw.md`) from any code in this plan. The check, the agent and `kb l3 confirm` only read it.
- Findings never go into `_manifest.yaml` / `index.yaml` (`extra="forbid"`, cross-install wire compat).
- Report file path: `.kb/<doc-id>/_l3check.yaml`. Committed in the child repo; never sent to the hub. `pubgate.is_kb_artifact` already refuses it on both the child and the hub intake side; it must not show in the publish "skipped" warning.
- Section digest = `quality.digest(slice_section(raw_md, id, occurrence))`, the same digest `build._check_hashes` uses.
- A document without `_l3check.yaml` is never gated.
- Agent output: JSON `{"verdict": "spurious"|"intentional"|"unsure", "reason": str}`, reason ≤ 30 words; anything else → `unsure`. Agent failure never fails ingest.
- LLM default model `"sonnet"`; existing `index.yaml` values are not rewritten.
- UI: left rail `288px` (default and ≤ 1279px breakpoints); section page default `level` = `l3`; API default stays `l2`.
- Version `1.31.1`.
- Repo checks before every commit: `ruff check src tests`, `ruff format --check src tests`, `pyright`, `pytest -q -x -n auto`.

## Review Focus

1. Re-ingest of an unchanged PDF must keep existing confirmations (same digest, same findings) — otherwise reviewers re-confirm everything every run. Test in Task 3.
2. A section whose heading is folded (`### x1 …`) or a fallback in front matter must not produce an orphan finding id that `kb l3 confirm --section` cannot address. Test in Task 6.
3. A scanned PDF (no text layer) must give `unverifiable` findings, not a flood of `content` findings. Test in Task 5.
4. `kb ingest` on a PDF with findings must not auto-summarize, and must tell the user the exact `kb l3 report <doc>` command. Test in Task 7.
5. Hand edit of `.raw.md` after confirming must re-block the section (digest mismatch). Test in Task 3.

---

### Task 1: LLM model default `sonnet`

**Files:**
- Modify: `src/strata_kb/models.py:123`
- Modify: `src/strata_kb/templates/init/index.yaml:4`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write the failing test**

```python
def test_llm_config_default_model_is_sonnet_alias():
    assert models.LLMConfig().model == "sonnet"

def test_init_index_template_uses_sonnet_alias():
    text = (TEMPLATES / "init" / "index.yaml").read_text(encoding="utf-8")
    assert "model: sonnet\n" in text and "sonnet-5" not in text
```
(`TEMPLATES` = `Path(strata_kb.__file__).parent / "templates"`.)

- [ ] **Step 2: Run** `pytest tests/test_llm.py -q -k sonnet_alias` — expect 2 FAIL.
- [ ] **Step 3: Change** `model: str = "sonnet-5"` → `"sonnet"` and the template line to `model: sonnet`. Grep `tests/` for other `"sonnet-5"` assertions on `LLMConfig` and update them (price tables in `test_usage_prices.py` are model ids, leave them).
- [ ] **Step 4: Run** `pytest tests/test_llm.py tests/test_summarize*.py -q` — PASS.
- [ ] **Step 5: Commit** `fix(llm): default model alias sonnet instead of sonnet-5`

### Task 2: Hub UI — wider left rail, reader opens L3

**Files:**
- Modify: `src/strata_kb/templates/web/static/style.css:115,122`
- Modify: `src/strata_kb/web/ui.py:943-945`
- Test: `tests/test_web_ui.py`

- [ ] **Step 1: Write the failing tests** (reuse `demo_doc_hub`, `_client`, `_main` in that file)

```python
def test_section_page_defaults_to_l3(demo_doc_hub):
    client = _client(demo_doc_hub / ".kb", str(demo_doc_hub))
    main = _main(client.get("/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}))
    assert re.search(r'class="on"[^>]*href="[^"]*level=l3', main)
    assert "Full raw text" in main

def test_section_page_invalid_level_falls_back_to_l3(demo_doc_hub): ...
    # params={"level": "bogus", ...} -> same assertions as above

def test_left_rail_is_288px():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert css.count("grid-template-columns: 288px") == 2
    assert "248px" not in css
```
Update `test_section_page_level_tabs_reflect_active_level`: the no-`level` request now asserts L3 is `on`; add an explicit `level=l2` request asserting L2 is `on`.

- [ ] **Step 2: Run** `pytest tests/test_web_ui.py -q -k "defaults_to_l3 or invalid_level or 288 or level_tabs"` — FAIL.
- [ ] **Step 3: Implement** `level` default and fallback `"l3"` in `section_page`; both `248px` → `288px` in `style.css`. Pager links stay without `level` (so they open L3).
- [ ] **Step 4: Run** `pytest tests/test_web_ui.py tests/test_web_api.py -q` — PASS (API default `l2` unchanged).
- [ ] **Step 5: Commit** `feat(web): wider left rail; reader opens L3 by default`

### Task 3: Report file — schema, gate, confirm, merge

**Files:**
- Create: `src/strata_kb/l3check/__init__.py` (docstring only), `src/strata_kb/l3check/report.py`
- Test: `tests/test_l3check_report.py`

**Interfaces — Produces** (all in `strata_kb.l3check.report`):
```python
FILE_NAME = "_l3check.yaml"
FindingKind = Literal["fallback", "order", "content", "break", "unverifiable"]

class AgentVerdict(BaseModel):   # extra="forbid"
    verdict: Literal["spurious", "intentional", "unsure"]
    reason: str

class Finding(BaseModel):        # extra="forbid"
    kind: FindingKind
    page: int | None = None
    evidence: dict[str, str] = {}   # keys used: l3, next, pdf, heading, other
    agent: AgentVerdict | None = None

class Confirmation(BaseModel):   # extra="forbid"
    by: str; at: str; l3_sha256: str

class SectionCheck(BaseModel):   # extra="forbid"
    id: str; l3_sha256: str
    findings: list[Finding]
    confirmed: Confirmation | None = None

class L3Check(BaseModel):        # extra="forbid"
    checked_at: str; source_sha256: str = ""
    sections: list[SectionCheck] = []

def load(doc_dir: Path) -> L3Check | None
def save(doc_dir: Path, check: L3Check) -> None          # utf-8, newline="\n"; deletes the file when check.sections is empty
def current_digests(kb_dir: Path, doc_id: str) -> dict[str, str]   # section id -> digest of its L3 slice now
def unconfirmed(check: L3Check, digests: dict[str, str]) -> list[SectionCheck]
def blocked_docs(kb_dir: Path) -> list[tuple[str, list[str]]]       # (doc_id, unconfirmed section ids), docs in index order
def merge(previous: L3Check | None, fresh: L3Check, rechecked: set[str]) -> L3Check
def confirm(kb_dir: Path, doc_id: str, section_ids: list[str] | None, by: str) -> list[str]  # None = all; returns ids confirmed
```
Rules: a section is unconfirmed when `confirmed is None` or `confirmed.l3_sha256 != digests.get(id)`. `merge`: keep previous entries whose id is not in `rechecked` and still in `fresh`'s manifest scope (caller passes all current ids via `rechecked` on a full ingest); for a fresh entry, carry the previous `confirmed` when previous `l3_sha256` equals fresh's and the findings equal ignoring `agent`. `confirm` raises `ValueError` for an id with no entry (message lists valid ids) and uses `review._now()`-style UTC `Z` timestamp.

- [ ] **Step 1: Write the failing tests** — build a tmp KB with one doc (index.yaml, `_manifest.yaml`, one `.raw.md` holding `## 1 A` / `## 2 B`), then:
  - `test_roundtrip_and_empty_deletes_file`
  - `test_unconfirmed_until_confirmed` — `blocked_docs` returns `[("doc", ["1"])]`, after `confirm(..., ["1"], by="r")` returns `[]`.
  - `test_hand_edit_reblocks` — edit the `## 1` body after confirm → blocked again.
  - `test_merge_keeps_confirmation_when_unchanged` and `test_merge_drops_confirmation_when_findings_change`.
  - `test_merge_partial_reingest_keeps_other_sections`.
  - `test_confirm_unknown_id_raises` (message contains `"1"`).
  - `test_doc_without_file_not_blocked`.
- [ ] **Step 2: Run** `pytest tests/test_l3check_report.py -q` — FAIL (module missing).
- [ ] **Step 3: Implement** `report.py`. Use `models.load_yaml_model`-style loading (`yaml.safe_load` + `model_validate`) and `mdutils.section_map` / `heading_occurrences` for digests.
- [ ] **Step 4: Run** the test file — PASS.
- [ ] **Step 5: Commit** `feat(l3check): findings file, gate and confirm`

### Task 4: Reference text — PDF page text and page furniture

**Files:**
- Modify: `src/strata_kb/ingest/pdftext.py` (add function)
- Modify: `src/strata_kb/ingest/parser.py` (add function)
- Test: `tests/test_pdftext.py`, `tests/test_parser.py`

**Interfaces — Produces:**
```python
# pdftext
def page_texts(pdf_path: Path) -> dict[int, str]   # 1-based page -> full text-layer text ("" for a page with no text); {} when pypdfium2 missing or the PDF is unreadable (logs a warning)
# parser
def furniture_by_page(doc) -> dict[int, list[str]]  # page -> texts of items labelled page_header / page_footer
```

- [ ] **Step 1: Write the failing tests** — `test_page_texts_reads_fixture` (importorskip pypdfium2; `tests/fixtures/mono-diagram.pdf` → page 1 non-empty); `test_page_texts_missing_file_returns_empty`; `test_furniture_by_page` using the fake-doc helpers already in `tests/test_parser.py` (one `page_header`, one `page_footer`, one `text` → only the two furniture strings returned).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** `page_texts` uses `textpage.get_text_range()` per page, normalises `\r\n`/`\r` to `\n`, opens/closes the document once. `furniture_by_page` walks `_iterate(doc)` with `_label_value` / `_page_of`.
- [ ] **Step 4: Run** `pytest tests/test_pdftext.py tests/test_parser.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(ingest): PDF page text and page furniture for the L3 check`

### Task 5: Detection — normalisation, content, unverifiable

**Files:**
- Create: `src/strata_kb/l3check/detect.py`
- Test: `tests/test_l3check_detect.py`

**Interfaces — Produces:**
```python
SHINGLE = 4        # words per shingle
MIN_RUN = 5        # shortest missing/extra run reported
SNIPPET_WORDS = 25 # evidence cap

@dataclass(frozen=True)
class SectionInput:
    id: str
    chapter: str
    page: int | None       # start page (SectionUnit.page)
    end_page: int | None   # last page of the span (next section's start page, or doc's last page)
    l3: str                # the section's L3 slice as written

def normalize_words(text: str) -> list[str]
def strip_markdown(md: str) -> str
def content_findings(sec: SectionInput, l3_neighbours: str, pdf_pages: dict[int, str], furniture: dict[int, list[str]]) -> list[Finding]
def unverifiable(sec: SectionInput, pdf_pages: dict[int, str]) -> Finding | None
```
Normalisation (`normalize_words`): NFKC, casefold, re-join `word-\nword` hyphenation, split on non-word characters (keep digits and Unicode letters, so Vietnamese survives). `strip_markdown` removes `## `/`### ` heading markers, table pipes and separator rows, image links `![..](..)` (keep alt text), code fences, emphasis `*`/`_`. Furniture strings are removed from the page text before tokenising. `content_findings`: a PDF word is covered when any shingle containing it occurs in the shingles of `sec.l3 + l3_neighbours`; each maximal run of ≥ `MIN_RUN` uncovered PDF words is one `content` finding with `evidence={"pdf": ...}` and its page. Reverse direction (L3 words against the span pages' shingles) gives `evidence={"l3": ...}`. `unverifiable` returns a finding when every page in the span has blank text; callers then skip content and break for that section.

- [ ] **Step 1: Write the failing tests**
  - `test_normalize_rejoins_hyphenation_and_keeps_vietnamese` — `"exam-\nple Gốc"` → `["example", "gốc"]`.
  - `test_strip_markdown_table_and_image`.
  - `test_identical_text_gives_no_findings` (L3 = PDF page text with a header line in furniture).
  - `test_missing_run_reported_with_page` — PDF has 8 extra words → 1 finding, kind `content`, `"pdf"` evidence contains them.
  - `test_garbled_l3_reported` — L3 has `"g ố c"`-style split words over a 6-word run → 1 finding with `"l3"` evidence.
  - `test_short_diff_below_min_run_ignored`.
  - `test_scanned_pages_unverifiable`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the functions above.
- [ ] **Step 4: Run** `pytest tests/test_l3check_detect.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(l3check): content and unverifiable detection`

### Task 6: Detection — break, order, fallback, whole-document check

**Files:**
- Modify: `src/strata_kb/l3check/detect.py`
- Test: `tests/test_l3check_detect.py`

**Interfaces — Consumes:** Task 5's `SectionInput`, helpers; `sectioner.Fallback`, `sectioner.Inversion`, `sectioner.SectioningNotes`.
**Produces:**
```python
TERMINAL = ".!?:;…)\"”’]"
JOIN_WORDS = 4

def break_findings(sec: SectionInput, pdf_pages: dict[int, str]) -> list[Finding]
def order_findings(sections: list[SectionInput], titles: dict[str, str], pdf_pages: dict[int, str], notes: SectioningNotes) -> dict[str, list[Finding]]
def fallback_findings(sections: list[SectionInput], notes: SectioningNotes) -> dict[str, list[Finding]]
def enclosing_unit(sections: list[SectionInput]) -> dict[str, str]   # any id incl. folded '### <id>' -> owning unit id
def check_document(sections: list[SectionInput], titles: dict[str, str], pdf_pages: dict[int, str], furniture: dict[int, list[str]], notes: SectioningNotes) -> list[SectionCheck]
```
- `break_findings`: paragraphs = blank-line-separated blocks of `sec.l3`, skipping headings, tables, fences, images and list items (`- `, `* `, `1. `). For consecutive prose blocks P1, P2 where P1's stripped end is not in `TERMINAL`: the normalised last `JOIN_WORDS` words of P1 followed by the first `JOIN_WORDS` of P2 occur contiguously in the normalised word stream of the span pages → finding, `evidence={"l3": tail, "next": head, "pdf": the matched window}`.
- `order_findings`: (a) a section whose `page` is lower than the previous section's `page` → finding on the later one, `evidence={"other": prev_id}`; (b) locate each title (normalised) in the concatenated normalised PDF stream from its start page on; located positions must increase, else finding on the later; (c) every `Inversion` with `reordered=False` → finding on `enclosing_unit[second_id]`.
- `fallback_findings`: every `Fallback` whose enclosing unit's `chapter` is not `"front-matter"` and whose enclosing unit id is not a part root (`sectioner._is_part_root`) → finding on the enclosing unit, `evidence={"heading": fb.heading}`.
- `check_document`: per section, `unverifiable` first; otherwise content (neighbours = previous and next section L3) + break; then order + fallback; return only sections with findings; `l3_sha256 = quality.digest(sec.l3)`.

- [ ] **Step 1: Write the failing tests**
  - `test_break_detected_when_pdf_is_contiguous` and `test_break_not_flagged_after_full_stop` and `test_list_items_not_flagged_as_break`.
  - `test_order_page_regression_flagged`, `test_order_unrepaired_inversion_attached_to_enclosing_unit`.
  - `test_folded_fallback_reported_on_parent_unit` (unit `2` body contains `### x1 Notes`, `Fallback("x1", "Notes", 3)` → finding under `"2"`).
  - `test_front_matter_fallback_not_flagged`.
  - `test_check_document_clean_doc_has_no_sections`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_l3check_detect.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(l3check): break, order and fallback detection`

### Task 7: Wire the check into `kb ingest`

**Files:**
- Modify: `src/strata_kb/ingestcmd.py` (`_run_ingest`, `ScaffoldReport` use)
- Modify: `src/strata_kb/ingest/scaffold.py:262` (`ScaffoldReport` gains `l3_flagged: int = 0`)
- Modify: `src/strata_kb/cli.py:847-944` (`ingest`)
- Test: `tests/test_ingest_seam.py`, `tests/test_ingest_cli.py`

**Interfaces — Consumes:** Tasks 3–6. **Produces:** `ingestcmd.l3_check(opts, doc, units, notes) -> report.L3Check` (pure wiring, no echo) called from `_run_ingest` after `scaffold_doc`; `ScaffoldReport.l3_flagged`.

Behaviour: build `SectionInput`s from `units` (filtered to `chapters` on `--sections`), their L3 slices read back from the written `.raw.md` files via the new manifest, `end_page` from the next unit; `pdf_pages = pdftext.page_texts(opts.pdf)`; when it is `{}`, echo `L3 check skipped: PDF text layer unreadable` and write nothing. Otherwise `report.merge(report.load(doc_dir), fresh, rechecked=<ids of units checked>)`, `report.save`, set `l3_flagged = len(unconfirmed(...))`. Echo `L3 check: N section(s) flagged (fallback a, order b, content c, break d, unverifiable e) — review: kb l3 report <doc-id>` or `L3 check: clean`.
In `cli.ingest`: when `report.l3_flagged`, skip auto-summarize and build and print `Summarize skipped until the L3 review is confirmed: kb l3 report <doc-id>, then kb l3 confirm <doc-id> --section <id> | --all`.

- [ ] **Step 1: Write the failing tests** with the fake-docling seam already used in `tests/test_ingest_seam.py` (monkeypatch `parser.load_or_parse`, `parser.doc_to_items`, `pdftext.page_texts`):
  - `test_ingest_writes_l3check_for_missing_text`, `test_ingest_clean_doc_writes_no_file`,
  - `test_ingest_unreadable_text_layer_skips_check`,
  - `test_ingest_cli_skips_summarize_when_flagged` (CliRunner; fake runner must not be called; output contains `kb l3 report demo`).
  - `test_reingest_unchanged_keeps_confirmation`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_ingest_seam.py tests/test_ingest_cli.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(ingest): run the L3 fidelity check after scaffolding`

### Task 8: Agent verdicts on `break` findings

**Files:**
- Create: `src/strata_kb/l3check/agent.py`
- Modify: `src/strata_kb/cli.py` (`ingest`: `--no-llm-review` option, call after the check)
- Test: `tests/test_l3check_agent.py`, `tests/test_ingest_cli.py`

**Interfaces — Produces:**
```python
REASON_MAX_WORDS = 30
def build_prompt(f: Finding) -> str
def parse_verdict(reply: str) -> AgentVerdict          # never raises; bad input -> unsure
def annotate(kb_dir: Path, doc_id: str, runner, max_workers: int, on_progress: Callable[[str], None] | None = None) -> int   # number of verdicts written
```
`annotate` loads the file, sends every `break` finding with `agent is None` to `runner.run(build_prompt(f))` in a `ThreadPoolExecutor`, writes results on the main thread, saves once. A `RunnerError` or any exception for one finding stores `AgentVerdict("unsure", "agent error: <first 100 chars>")`. The prompt shows L3 tail, L3 head and the PDF window, asks for the JSON object only, and says: judge only — do not rewrite, correct or summarise the text. `parse_verdict` accepts the JSON optionally wrapped in a ```json fence, truncates `reason` to `REASON_MAX_WORDS` words. The CLI resolves the runner with `_resolve_runner(kb_dir, llm, 0)`; skipped silently when `--no-llm-review`, `--llm none`, or no runner (echo `L3 agent review skipped: no LLM CLI`).

- [ ] **Step 1: Write the failing tests**
  - `test_parse_verdict_valid`, `test_parse_verdict_fenced`, `test_parse_verdict_garbage_is_unsure`, `test_parse_verdict_long_reason_truncated`.
  - `test_prompt_forbids_rewrite` (prompt contains `"do not rewrite"`).
  - `test_annotate_only_break_findings_and_never_touches_raw_md` (fake runner records calls; `.raw.md` bytes unchanged; non-break findings keep `agent=None`).
  - `test_annotate_runner_error_stores_unsure`.
  - `test_annotate_does_not_confirm` (`confirmed` stays `None`).
  - `test_ingest_no_llm_review_flag_skips_agent` (CLI).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_l3check_agent.py tests/test_ingest_cli.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(l3check): Sonnet verdicts on broken-paragraph findings`

### Task 9: `kb l3 report` / `kb l3 confirm`, `kb status` line

**Files:**
- Modify: `src/strata_kb/cli.py` (new `l3_app = typer.Typer(help="L3 fidelity review: findings and reviewer confirmation.")`, `app.add_typer(l3_app, name="l3")`, `status`)
- Test: `tests/test_l3check_cli.py`

**Interfaces — Consumes:** `report.blocked_docs`, `report.load`, `report.confirm`, `review.resolve_reviewer`.

- `kb l3 report [DOC_ID] [--kb-dir]`: per unconfirmed section, print `§<id>` then one line per finding: `  [<kind>] p.<page> <evidence…>` and `    agent: <verdict> — <reason>` when present. Ends `N section(s) awaiting review.`; exit `1` if N > 0, else prints `L3 check: nothing awaiting review.` and exit `0`.
- `kb l3 confirm DOC_ID (--section ID ... | --all) [--by NAME] [--yes]`: `--all` without `--yes` asks `typer.confirm("Confirm all N flagged section(s) of <doc>?")`. Neither flag, or both → exit `2` with usage message. Unknown id → exit `1` with the `ValueError` message. Prints `confirmed: §a, §b`.
- `kb status`: after each doc's pending line, `  L3 check: N section(s) awaiting review` when N > 0.

- [ ] **Step 1: Write the failing tests** — `test_report_lists_findings_and_exits_1`, `test_report_clean_exits_0`, `test_confirm_section_then_report_clean`, `test_confirm_all_requires_yes_or_prompt`, `test_confirm_requires_section_or_all`, `test_confirm_unknown_section_exit_1`, `test_status_shows_l3_line`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_l3check_cli.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(cli): kb l3 report / confirm and status line`

### Task 10: Gates in summarize, build, publish, ci-publish

**Files:**
- Modify: `src/strata_kb/summarize.py` (`SummarizeReport.blocked: list[str]`, `summarize_kb`)
- Modify: `src/strata_kb/cli.py` (summarize output; exit non-zero when `report.blocked`)
- Modify: `src/strata_kb/build.py` (`_build_doc`)
- Modify: `src/strata_kb/publish.py` (new `l3_gate(kb_dir) -> UnreviewedGate`, called where `unreviewed_gate` is), `src/strata_kb/cipublish.py` (`_check_unreviewed_gate` neighbour)
- Modify: `src/strata_kb/pubgate.py` (`split_allowlist` leaves `_l3check.yaml` out of `skipped`)
- Test: `tests/test_summarize.py`, `tests/test_build.py`, `tests/test_publish_require_reviewed.py`, `tests/test_pubgate.py`

Messages (exact):
- summarize skip: `[skip] <doc>: L3 review pending (N section(s)) — kb l3 report <doc>`
- build error: `<doc>: L3 review pending for §a, §b — kb l3 report <doc>` (always an error, any `--strict`)
- publish/ci-publish: `[error] L3 review pending in N doc(s): <doc>, … — kb l3 report` with `blocked=True`.

- [ ] **Step 1: Write the failing tests** — `test_summarize_skips_blocked_doc` (runner not called for it; other doc summarized; `report.blocked == ["doc"]`), `test_build_errors_on_blocked_doc`, `test_build_ok_after_confirm`, `test_publish_refuses_when_l3_blocked`, `test_ci_publish_refuses_when_l3_blocked` (no HTTP call made), `test_l3check_file_not_published_and_not_warned` (`split_allowlist` → not in kept, not in skipped), `test_doc_without_l3check_not_gated`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_summarize*.py tests/test_build.py tests/test_publish*.py tests/test_pubgate.py tests/test_cli_ci_publish_summary.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: gate summarize, build and publish on the L3 review`

### Task 11: Release 1.31.1 — version, changelog, docs

**Files:**
- Modify: `pyproject.toml:3` → `1.31.1`; `uv.lock` (`uv lock` if the project entry carries the version)
- Modify: `CHANGELOG.md` (new `## 1.31.1 — <date>` on top, same style as 1.31.0: one-line summary, bullets **L3 check**, **Agent**, **Review gate**, **Reader**, **Model**, **Upgrade**)
- Modify: `src/strata_kb/templates/init/claude-skill-kb-ingest.md`, `copilot-kb-ingest.prompt.md`, `cursor-kb-ingest.md`, `claude-skill-kb-summarize.md`, `QUICKSTART-child.md`, `QUICKSTART-dev.md`, `QUICKSTART-hub.md`, `README.md` (command table): add the review step `kb l3 report <doc>` → `kb l3 confirm <doc> --section <id> | --all` between ingest and summarize.
- Test: existing version/template tests (`grep -rn "1.31.0" tests scripts`).

Upgrade bullet content: upgrade the CLI; bump the CI pin to `strata-kb==1.31.1` (an older CI has no gate; the hub never receives `_l3check.yaml` either way, its intake allowlist drops it); documents ingested before 1.31.1 are not gated until re-ingested; Copilot users set `llm.model` explicitly.

- [ ] **Step 1: Run** `grep -rn "1\.31\.0" pyproject.toml tests scripts src | grep -v CHANGELOG` and update what pins the current version.
- [ ] **Step 2: Edit** files above.
- [ ] **Step 3: Run** the full gate: `ruff check src tests && ruff format --check src tests && pyright && pytest -q -n auto` — all PASS.
- [ ] **Step 4: Commit** `chore: release 1.31.1`
