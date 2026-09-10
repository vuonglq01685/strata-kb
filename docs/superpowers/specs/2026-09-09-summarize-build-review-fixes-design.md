# Summarize/build review fixes — C2 rules in `kb build`, a safe `--redo`, a review signal that means something

**Status:** approved design, ready for an implementation plan
**Source:** reviewer B of the 2026-09-08 full framework review,
`docs/superpowers/reviews/2026-09-08-full-framework-review/B-summarize-build.md`
(findings B-1–B-20), and §5 đợt 1 items 2–7 of
`docs/superpowers/reviews/2026-09-08-full-framework-review.vi.md`.
**Predecessor:** `2026-09-08-ingest-review-fixes-design.md` (reviewer A,
merged as PR #46). That batch made `kb ingest` rename duplicate ids and
keep every section its own row; this batch takes the pipeline from the
scaffold onward.
**Approach:** as approved on 2026-09-09 — put the C2 quality rules into a
new pure module `quality.py` shared by `kb build`, `kb summarize` and
`kb approve` (approach A); make the table check two-way; pass the Copilot
prompt through stdin; make `--redo` opt-in per document and protective of
reviewed work; record provenance, an L3 hash and a review record in the
manifest; gate `kb approve` on a strict build; make the manual
`/kb-summarize` path consume the engine's own prompt. Code, tests and
docs only: the bundled `.kb/` is **not** re-summarized in this batch.

## Goal

Reviewer B proved, on the shipped KB and on synthetic KBs, that the
framework's core content promise (C2: L2 is a faithful 20–30 % condensation
of the prose, tables are never rewritten by AI) is stated in a prompt and
checked almost nowhere:

- On Windows the Copilot runner passes the prompt as an argv element of a
  `.cmd` shim; `cmd.exe` cuts it at the first newline, so the model sees 58
  characters, invents a summary, and `kb build` says OK (B-1, CRITICAL).
- 44 of the 90 table-bearing `arinc-424` sections restate their own table
  in L2 prose, with real errors (§5.7 drops the "except RNAV" clause; §5.99
  invents the codes `IM/MM/OM/BM`), and the table-integrity latch cannot
  see it (B-2, CRITICAL).
- The 300-character floor turns the "hard 35 %" budget into 0.45× in
  aggregate and up to 14× per section; 207/325 sections get a budget larger
  than their source and the model fills it with framing (B-6).
- `kb build` checks tables in one direction only: an invented table, a
  duplicated table, a deleted header-only table, an emptied L2 body, an
  orphan heading and a 40× L2 all pass (B-7, 8 of 24 mutations missed).
- `kb summarize --redo` with no argument resets every document, including
  `reviewed` sections, before the first LLM call; one API outage leaves the
  KB unbuildable with every sign-off gone (B-4). It also deletes `Figure:`
  lines that only a re-ingest can restore (B-5).
- `kb approve` verifies nothing and records nothing; `kb publish` ships
  `summarized` content exactly like `reviewed` content; no manifest field
  says which model or prompt produced a summary, or whether L3 changed
  since (B-9, B-10, B-11). Both shipped manifests are 329/329
  `summarized`, 0 `reviewed`.
- The manual `/kb-summarize` path reads the full L3 (tables included), has
  no integer budget and no length validation — the likeliest origin of the
  transcriptions (B-16).

After this batch:

- every C2 sub-promise except "no invention" in the abstract is a
  deterministic check in `kb build`, warned by default and fatal with
  `--strict`, and measured on the same prose string the engine budgets;
- `kb build` rejects every one of the 24 adversarial mutations that
  reviewer B says it should (a, b, d, h, m, q, s, u become failures) and
  writes nothing when it fails;
- the prompt reaches Copilot intact on every platform, and a test pins
  that no runner ever puts the prompt in argv;
- `--redo` names a document, never touches `reviewed` sections unless told
  to, prints what it will destroy before it writes, and keeps figure
  captions;
- a manifest row says who summarized it with what, what L3 it summarized,
  and who approved which L2; `kb build` fails when either hash drifts;
  `kb publish` says how much of what it ships is unreviewed;
- the manual path and the engine send the model the same prompt.

## Decisions taken during brainstorming (2026-09-09)

1. **Scope: đợt 1 items 2–7, code + tests + docs; no re-summarize.**
   B-8 (`kb summarize --redo arinc-424` for real, SME approval, README §10
   number) is a later batch that needs a real runner and a human review of
   325 sections. README §10 keeps `11.1 %` with one added sentence saying
   it predates the quality gate. Rejected: the narrower "gate + runner
   only" cut (leaves `--redo` able to erase every sign-off, and approve
   decorative) and "everything including B-8".
2. **New checks are warnings by default; `kb build --strict` makes them
   errors.** The shipped KB fails 325/325 on the ratio check today, so
   fatal-by-default would redden the repo's own build and every CI journey
   until the re-summarize batch. Pre-existing checks (TODO marker, empty
   L1, table integrity) stay fatal, and so do the new structural checks
   (extra/duplicated/missing table, orphan heading, hash drift, empty L0).
   After the re-summarize batch the default flips to strict. Rejected:
   fatal now; fatal with a `--no-quality-checks` escape (inverts the burden
   on every existing repo).
3. **`kb approve` runs a strict build on the document and refuses on any
   error; `kb publish` warns on `summarized` content, `--require-reviewed`
   makes it fatal.** Approval is the SME gate (C16); approving a section
   that fails the C2 checks would make the gate decorative again. Publish
   stays permissive by default because every existing KB, the bundled one
   included, is 100 % `summarized`. Rejected: approve with the non-strict
   build (an SME could approve a transcribed table); publish fatal by
   default.
4. **Sections with ≤ 200 characters of prose are copied verbatim into L2
   with no LLM call.** 64 % of `arinc-424` sections are `Used On:` /
   `Length:` boilerplate; any summary is longer than the source. L2 becomes
   the prose itself, L1 a fixed label (`Brief section: <title>.`) that
   `kb build` can verify, exactly like `Table-only section:`. Removes ~207
   LLM calls per redo and every ratio > 1.0 by construction. Rejected: keep
   calling the LLM with `min(n, …)` as the cap (still invites framing); copy
   L2 verbatim but let the LLM write L1 (207 calls for one sentence each).
5. **Approach A: a pure `quality.py` shared by build, summarize and
   approve.** `prose_only()` is the single unit of measure for the guard,
   the near-table-only test and the ratio check, so the engine and the gate
   can never disagree on the denominator (the B-6 inflation was exactly
   that disagreement). Rejected: everything in `build.py` (400+ lines and a
   duplicated `prose_only`); validate only after summarize (misses the
   manual path and hand edits).
6. **Copilot gets the prompt on stdin.** The Copilot CLI documents
   `copilot -p < file` / `echo … | copilot -p` (bare `-p` reads stdin);
   `-s` suppresses metadata. No temp file, no argv, no `cmd.exe` parsing.
7. **`--redo` requires a `DOC_ID` or `--all`, skips `reviewed` unless
   `--include-reviewed`, prints its preview before writing, and asks
   `y/N` (or `--yes`) when reviewed work would be reset.** No automatic
   backup: the KB is git-tracked and `kb approve` requires a clean tree, so
   `git checkout -- .kb/<doc>` restores anything. The confirmation text
   says so.
8. **Thresholds are constants, not config.** 120 (floor), 200
   (near-table-only), 0.35 (ratio), 0.45 (lexical overlap), 4 (cells per
   sentence), 25 (L1 words), 30 (L0 words) live at the top of
   `quality.py`. Nothing in the review asked for tuning per KB.

## Scope

**In:**

- `src/center_kb/quality.py` — new: `prose_only`, `Finding`,
  `check_section`, `check_doc`, thresholds.
- `src/center_kb/build.py` — strict mode, quality findings, two-way
  table check with multiplicity and order, orphan headings, hash drift,
  no manifest write on failure, `kb stats` hint.
- `src/center_kb/mdutils.py` — `extract_tables` accepts a one-line block.
- `src/center_kb/summarize.py` — prose-based budget, near-table-only
  short-circuit, row-keyed results, balanced-brace JSON parse, L0 refresh
  and failure accounting, provenance + `l3_sha256`, `--print-prompt`
  support, `Figure:` lines survive `rebuild_l2_scaffold`, scoped
  `redo_reset` with preview.
- `src/center_kb/llm.py` — Copilot via stdin, envelope errors, one-second
  jittered pause before the retry on a `RunnerError`.
- `src/center_kb/models.py` — `Provenance`, `ReviewRecord`,
  `SectionEntry.l3_sha256 / provenance / reviewed`, `LLMConfig.effort`
  as a `Literal`, `save_yaml_model(exclude_none=True)`.
- `src/center_kb/review.py` + `cli.py` `approve` — strict-build gate,
  clean-tree gate, `--by`, review record.
- `src/center_kb/publish.py` + `cli.py` `publish` — unreviewed count,
  `--require-reviewed`.
- `src/center_kb/diff.py` — render the review record.
- `cli.py` — `build --strict`, `summarize --all/--include-reviewed/--yes/
  --dry-run/--section/--print-prompt`, `approve --by`, `publish
  --require-reviewed`, `stats` hint.
- `.claude/skills/kb-summarize/SKILL.md` and the init templates
  `claude-skill-kb-summarize.md`, `claude-command-kb-summarize.md`,
  `copilot-kb-summarize.instructions.md`, `cursor-kb-summarize.md`,
  `cursor-kb-summarize.mdc` — dispatch via `--print-prompt`; the
  `kb-approve` skill/command templates mention the new gate and `--by`.
- Tests: `tests/test_quality.py` (new), `test_build.py`,
  `test_mdutils.py`, `test_summarize*.py`, `test_llm.py`, `cli_stub.py`,
  `test_cli_approve.py`, `test_review.py`, publish tests,
  `test_templates.py`, `test_init.py`, `test_models.py`.
- Docs: README (C1 wording, new flags, approve gate, §10 caveat), spec
  `2026-07-11-summarize-quality-design.md` §3 note, this spec.

**Out (named so nobody re-litigates):**

- B-8: re-summarizing the bundled KB, SME approval, README §10 number.
- B-17 beyond the cheap parts: 429/529-aware backoff, an overall
  deadline, `effort` for Copilot.
- Per-Part section namespacing (still `<id>-2` from the ingest batch).
- Making thresholds configurable.
- Anything in reviewer C–H.

## Design

### 1. `quality.py` — the C2 rules as pure functions

```python
RATIO = 0.35            # L2 prose ≤ RATIO × L3 prose …
FLOOR_CHARS = 120       # … but never required below this many characters
BRIEF_CHARS = 200       # ≤ this much L3 prose: copy verbatim, no LLM
OVERLAP_MIN = 0.45      # share of L2 word-types that occur in the L3 slice
CELLS_PER_SENTENCE = 4  # distinct table cells quoted in one L2 sentence
L1_MAX_WORDS = 25
L0_MAX_WORDS = 30
TABLE_ONLY_LABEL = "Table-only section: {title}."
BRIEF_LABEL = "Brief section: {title}."
```

`prose_only(text) -> str` drops table lines (`lstrip().startswith("|")`),
heading lines (`#`), `[table omitted]`, `Figure: …` lines and standalone
image lines (`![…](assets/…)`), collapses runs of blank lines, strips.
It is applied to both the L2 slice and the L3 slice, and it is the only
length measure anywhere in this batch.

`budget(l3_prose_chars) -> int` = `max(FLOOR_CHARS, int(RATIO * n))`.
`is_brief(n)` = `0 < n <= BRIEF_CHARS`; `is_table_only(n)` = `n == 0`.

`Finding(code: str, ref: str, message: str, level: Literal["error",
"quality"])`. `check_section(ref, sec, l2_slice, l3_slice) ->
list[Finding]` yields, all at level `quality` unless stated:

| code | fires when |
|---|---|
| `ratio` | `n3 > BRIEF_CHARS and len(l2) > budget(n3)` |
| `brief-verbatim` | `is_brief(n3) and l2 != l3_prose` (whitespace-normalised) |
| `l2-empty` | `n3 > BRIEF_CHARS and l2 == ""` |
| `table-transcription` | some L2 sentence (split on `.?!` + newline) contains ≥ `CELLS_PER_SENTENCE` distinct cell values of the section's own L3 tables; cells shorter than 2 characters or purely numeric are ignored |
| `invented-code` | a token matching `\b[A-Z][A-Z0-9/]{1,7}\b` in the L2 prose is not a substring of the full L3 slice (tables included, so codes that live only in a table remain legal) |
| `lexical-overlap` | L2 prose has ≥ 20 words and the share of its distinct lower-cased words present in the L3 slice is `< OVERLAP_MIN` |
| `l1-words` | `len(sec.summary.split()) > L1_MAX_WORDS` |
| `table-only-label` | `is_table_only(n3)` and (`sec.summary != TABLE_ONLY_LABEL` or `l2 != ""`) |
| `brief-label` | `is_brief(n3)` and `sec.summary != BRIEF_LABEL` |

`check_doc(entry) -> list[Finding]`: `l0-empty` at level **error** when
`entry.summary.strip() == ""`; `l0-words` at level `quality` when it has
more than `L0_MAX_WORDS`.

No I/O, no manifest writes, no LLM. Each check is its own small function
so a test can hit it in isolation.

### 2. `kb build`

`build_kb(kb_dir, allow_pending=False, strict=False) -> BuildReport`.
`BuildReport` gains `quality: list[str]`; the CLI prints them as
`[warn] … (quality)` by default and as `[error] … (quality)` under
`--strict`, in which case they count toward `ok`.

Per section, in this order, after the existing "section not found" and
pending checks:

1. **Tables, two-way.** `l2 = [normalize_table(t) for t in
   extract_tables(l2_slice)]`, same for L3. `Counter(l2) != Counter(l3)`
   → one error naming the difference (`missing in L2` / `extra in L2` /
   `duplicated in L2`). If the multisets agree but the lists differ →
   error `tables reordered within the section`. `extract_tables` now
   keeps a one-line block, so a header-only table is checked like any
   other; reviewer B measured 0 one-line blocks in the shipped KB, and the
   plan verifies that `kb build` on `.kb/` reports the same table errors
   (none) before and after.
2. **Orphan headings.** Every `## <id>` in the L2 file and the L3 file
   must be a manifest id → error (`heading '<id>' not in manifest`).
   Checked once per file, not per section.
3. **Hash drift.** If `sec.l3_sha256` is set and differs from the sha256
   of the current L3 slice → error `L3 changed since it was summarized;
   run kb summarize --redo <doc> --section <id>`. If `sec.reviewed` is set
   and its `l2_sha256` differs from the current L2 slice → error `L2
   changed after review; approve again or redo`. Empty/missing fields
   (older manifests) are skipped silently.
4. **Quality findings** from `check_section`.

Per document: `check_doc(entry)`.

**No write on failure.** Token counts are computed into a local dict and
the manifest is saved only when no error was added while processing that
document (compare `len(report.errors)` before and after). Under
`--strict`, quality findings are errors and therefore also suppress the
write.

`kb stats`: when every section's `tokens` is 0, print `run kb build to
refresh token counts` under the table.

### 3. `kb summarize` engine

- `PendingSection` gains `row: int` (index in `manifest.sections`) and
  `prose_chars: int`. `kind` is derived: `table_only` when
  `prose_chars == 0`, `brief` when `is_brief`, else `llm`. The regex-based
  `_is_table_only` is deleted; the definition lives in `quality.py`.
- `collect_pending` returns every pending row; `_summarize_one` handles
  the three kinds: `table_only` → `("", TABLE_ONLY_LABEL)`; `brief` →
  `(prose_only(l3_body), BRIEF_LABEL)`; `llm` → prompt with
  `max_chars = budget(prose_chars)`, guard on `len(reply["l2_summary"]) <=
  max_chars`, one retry as today. The prompt text itself is unchanged
  except that `{max_chars}` is now the prose-based budget.
- Results are keyed `(doc_id, row)`; `_apply_results` walks
  `enumerate(manifest.sections)` so a duplicated id in an older manifest
  or a code-ingest manifest can no longer receive its neighbour's text.
- `parse_json_reply`: try the body of the first ```` ```json ```` fence,
  then every balanced `{…}` span left to right (string-aware brace
  matching), returning the first object that carries every required key
  as a non-empty string; otherwise `ValueError` as today.
- L0: `summarize_kb` no longer returns early on an empty pending list. It
  calls `_fill_doc_summaries` for every in-scope doc that has no pending
  sections **and** either had a section summarized in this run or has an
  empty `entry.summary`. A failed doc summary is appended to
  `report.failed` as `<doc>/<doc-summary>` so the command exits 1.
- After a successful `llm` or `brief` or `table_only` result,
  `_apply_results` sets `sec.l3_sha256` (sha256 hex of the L3 slice that
  was summarized) and `sec.provenance = Provenance(runner, model, effort,
  prompt_sha, at)` where `prompt_sha` is the first 12 hex of
  `sha256(SECTION_PROMPT)` and `at` is UTC ISO-8601 to the second. Rows
  that made no LLM call record `runner="none"`, `model=""`, `effort=""`.
- Retry pause: when the first attempt raised `RunnerError` (not the length
  guard), sleep `1.0 + random() * 0.5` seconds before the retry. Nothing
  more from B-17.

### 4. Runner

```python
if self.name == "claude":
    cmd = [exe, "-p", "--model", model, "--output-format", "json"]
else:  # copilot: bare -p reads the prompt from stdin; -s drops metadata
    cmd = [exe, "-p", "--model", model, "-s"]
proc = subprocess.run(cmd, input=prompt, …)
```

`Runner.run` asserts `prompt not in cmd` before spawning, so a future
runner cannot reintroduce B-1 without a failing test.

`_extract_reply("claude", stdout)`: if the envelope has `is_error: true`
or a `subtype` starting with `error`, raise `RunnerError(result or
subtype)`; if `result` is missing or not a string, raise
`RunnerError("no result in claude envelope")`. Non-JSON stdout is still
returned as-is (older CLI versions).

`LLMConfig.effort: Literal["low", "medium", "high"] = "high"` — a typo in
`index.yaml` becomes a validation error at load time instead of a silent
"no thinking budget".

### 5. `kb summarize --redo`

New surface: `kb summarize [DOC_ID] --redo [--all] [--include-reviewed]
[--yes] [--dry-run] [--section ID …]`.

1. Reject `--redo` with neither `DOC_ID` nor `--all`:
   `--redo resets every summary; name a document, or pass --all to reset
   the whole KB.` Reject `--all` together with a `DOC_ID`, and `--section`
   without a `DOC_ID`.
2. Resolve the runner (unchanged: no runner → nothing reset).
3. `plan_redo(kb_dir, doc_id, sections, include_reviewed) -> RedoPlan`
   lists the rows that would be reset and, separately, the `reviewed`
   rows that would be reset (empty unless `--include-reviewed`) and the
   reviewed rows being skipped. Pure — no writes.
4. Print the plan: `redo: N section(s) in <doc> will be reset (M reviewed
   skipped)`; with `--include-reviewed`, also list every reviewed row as
   `<doc>/<id> reviewed by <by> at <at>`. `--dry-run` stops here, exit 0.
5. If reviewed rows would be reset and `--yes` is absent, prompt
   `Reset these reviewed sections? Their L2 text and sign-off will be
   removed (recoverable with git checkout). [y/N]`; non-interactive stdin
   or anything but `y` → exit 1, nothing written.
6. `redo_reset(plan)` writes: status `pending`, `summary=""`,
   `reviewed=None`, `provenance=None`, `l3_sha256=""`, and restores the
   marker only in the planned rows — a new `reset_section_prose(l2_text,
   sid)` replaces that one section's prose (keeping its heading, tables
   and `Figure:` lines) with its `<!-- TODO:summarize -->` marker; other
   sections in the same file are untouched. `rebuild_l2_scaffold` stays
   as the whole-file form and is what a whole-doc redo applies.
7. `rebuild_l2_scaffold` keeps `Figure: ` lines in place, like table lines.
   A round-trip test proves scaffold → filled → rebuilt is byte-identical
   to the scaffold for a section with a figure and a table.

### 6. Manifest schema, `kb approve`, `kb publish`

```python
class Provenance(BaseModel):
    runner: str; model: str = ""; effort: str = ""; prompt_sha: str = ""; at: str = ""

class ReviewRecord(BaseModel):
    by: str; at: str; l2_sha256: str

class SectionEntry(BaseModel):
    …
    l3_sha256: str = ""
    provenance: Provenance | None = None
    reviewed: ReviewRecord | None = None
```

`save_yaml_model` dumps with `exclude_none=True` so older-shaped
manifests stay byte-identical after a load/save round trip (a test pins
this on the bundled manifests). Readers that predate the fields ignore
them (pydantic default `extra="ignore"`); the hub mirrors files and never
parses them for this.

`kb approve DOC_ID [--section …] [--by "name <email>"]` and
`--all-changed --against REV`:

1. `gitio.is_dirty(root, kb_dir / doc_id)` → exit 1: `commit .kb/<doc>
   before approving; approval signs the committed content`.
2. `build_kb(kb_dir, strict=True)` filtered to `<doc> §` prefixed messages
   → any error → print them, exit 1, nothing written.
3. `by` = `--by`, else `git config user.name` + `<user.email>`; neither →
   exit 1.
4. Flip `summarized → reviewed`, set `reviewed = ReviewRecord(by, at,
   sha256(l2_slice))`. `pending` rows are still skipped with a warning;
   `reviewed` rows are untouched.

`kb build` enforces `reviewed.l2_sha256` (design §2 step 3). `kb diff`
appends `reviewed by <by> at <at>` to a changed/added section line when
the record exists.

`kb publish [--require-reviewed]`: after the snapshot is built, count
sections whose status is not `reviewed` across the docs being published.
`> 0` → `[warn] N section(s) in M doc(s) are published without SME
review`; with `--require-reviewed` → error and exit 1 before any commit,
push or PR.

### 7. Manual path

`kb summarize DOC_ID --print-prompt [--section ID …]` prints, for each
pending (or named) row:

```
=== <doc>/<id> ===
<exact output of build_section_prompt>
```

Rows of kind `brief` / `table_only` print `=== <doc>/<id> === [no LLM
needed: brief|table-only — run kb summarize to fill it]` instead. Exit 0
even when nothing is pending (prints `nothing pending`).

The skill and the summarize templates change together:

- Dispatch: sub-agents receive the printed prompts verbatim, not a
  `kb get … --level l3` command; the "Writing rules" block is deleted
  (the prompt carries the rules and the integer `max_chars`).
- Output contract: `[{"section_id", "l2_summary", "l1_summary"}]` —
  `table_only` is gone; the engine decides that.
- Validate: every assigned section present; `l1_summary` ≤ 25 words;
  `len(l2_summary)` ≤ the `max_chars` printed in that section's prompt.
- Verify wave: `kb build --allow-pending --strict`. Finalize: `kb build
  --strict`; doc summary "one sentence, max 30 words".
- `tests/test_templates.py` pins the summarize wrappers' content the way
  the dev-code-seed canon is pinned, and asserts the repo's
  `.claude/skills/kb-summarize/SKILL.md` equals the shipped template.

### 8. Docs

- README C1: "fails on one character of difference" → "fails on any
  difference after whitespace/alignment normalization (NBSP, tabs,
  trailing spaces, `:--` alignment and extra separator rows are folded;
  everything else is byte-compared)".
- README command table: `kb build --strict`, `kb approve` gate and
  record, `kb publish --require-reviewed`, `kb summarize --redo` flags,
  `--print-prompt`.
- README §10: keep `11.1 %`, add "measured before the 2026-09 quality gate;
  the re-summarize batch replaces this number".
- `2026-07-11-summarize-quality-design.md` §3: a dated note that the
  budget is now `max(120, 0.35 × prose)` measured on prose only, that
  sections ≤ 200 prose characters are copied verbatim, and that decision #6
  (re-run the shipped KB) is still outstanding.

## Error handling

- Every new CLI refusal exits 1 with one sentence naming the fix; no
  tracebacks (`ValueError` / `GitError` are caught at the command).
- `build_kb` never raises on content; a corrupt manifest is already an
  error entry. It never writes when it has errors.
- `redo_reset` is only ever called with a `RedoPlan` that was printed;
  the prompt is the last thing before the first write.
- `approve` writes only after both gates pass and after `by` resolved.
- `_summarize_one` keeps its "one section never aborts the batch" contract;
  the doc-summary failure is now counted, not swallowed.

## Testing

TDD, no mocks, real files in `tmp_path`, stubs via `tests/cli_stub.py`.

- `tests/test_quality.py`: `prose_only` on a slice with heading, table,
  placeholder, `Figure:`, image; one positive and one negative case per
  check code; §5.7 and §5.99 reduced to five-line fixtures for
  `table-transcription` and `invented-code`; `budget`/`is_brief`
  boundaries at 0, 200, 201.
- `tests/test_build.py`: the 24-mutation matrix from the review as
  parametrised cases; a, b, d, h, m, q, s, u must now fail and c, e4, e4b,
  e5, f, g, k, l, p, r, t must still fail; e1–e3, i, j pass (j passes only
  when `l3_sha256` is empty — a second case with the hash set must fail);
  quality findings are warnings by default and errors under `strict`;
  manifest untouched on failure (mtime + content); orphan heading; L0 empty.
- `tests/test_mdutils.py`: one-line table block extracted.
- `tests/test_summarize*.py`: brief section fills verbatim without a
  runner call (stub counts invocations); table-only unchanged; budget uses
  prose chars (fixture where headings inflate `l3_body`); duplicate-id
  manifest gets each row its own text; `parse_json_reply` on the nine
  fuzz replies from B-12; L0 refreshed when nothing is pending and summary
  empty; doc-summary failure exits 1; provenance and `l3_sha256` written;
  `--print-prompt` output equals `build_section_prompt`; `redo` refusal
  matrix, `--dry-run` writes nothing, `--include-reviewed` without `--yes`
  on non-tty exits 1 and writes nothing, `Figure:` round trip,
  `--section` resets only that row.
- `tests/test_llm.py`: both stubs switch to `echo_after_stdin`; a test
  pushes a real formatted `SECTION_PROMPT` (multi-line, ~3.5 kB, containing
  `%PATH%`, `& | > ^ !`) through each stub — on Windows through the `.cmd`
  wrapper — and asserts the stub received every byte; `is_error` and
  `error_max_turns` envelopes raise `RunnerError`; `prompt not in cmd`
  assertion; `effort="hgih"` fails model validation.
- `tests/test_cli_approve.py` / `test_review.py`: dirty tree refused;
  strict-build error refused (fixture: the extra-table KB from case a);
  record written with `--by` and with git config; `kb build` fails after
  an L2 edit post-approval; `kb diff` shows the record.
- Publish tests: warning text with counts; `--require-reviewed` exits 1
  before any hub write (hub tree unchanged).
- `tests/test_templates.py` / `test_init.py`: content pins; repo skill ==
  template.
- `tests/test_models.py`: bundled manifests round-trip byte-identical;
  new fields load and dump; `exclude_none`.
- Baseline, measured in Task 14 on the bundled `.kb/`: `kb build --kb-dir
  .kb` exits 0 with 415 `(quality)` warnings — `ratio` 314, `table-transcription`
  37, `invented-code` 36, `brief-label` 15, `brief-verbatim` 12,
  `lexical-overlap` 1 (`table-only-label`, `l1-words`, `l0-words`,
  `l2-empty` all 0) — and `kb build --strict --kb-dir .kb` exits 1. The
  gate journey in `tests-gate/e2e` keeps using the non-strict build.

## Acceptance

- All existing tests pass; new tests cover every bullet above.
- `kb build` on `.kb/`: exit 0, no new `[error]`, quality warnings only.
- `kb build --strict` on `.kb/`: exit 1.
- On Windows, `kb summarize --llm copilot` against the counting stub
  receives the full prompt.
- `kb summarize --redo` with no argument exits 1 and changes nothing.
- `kb approve` on the extra-table fixture exits 1 and changes nothing.
