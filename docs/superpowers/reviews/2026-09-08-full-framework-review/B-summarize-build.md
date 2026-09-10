# Reviewer B — summarize step + `kb build` gate (C1, C2, C4, C5, `kb approve` from C16)

Repo: `D:\Projects\AERO-KB` @ `4b47b4c` (main, clean). Nothing in the repo was modified.

---

## Scope & method

Files read: `src/center_kb/{summarize,llm,build,mdutils,models,review,diff}.py`,
`src/center_kb/cli.py` (`summarize` 555, `status` 606, `build` 632, `stats` 1163,
`approve` 1705, helpers 501–553), `src/center_kb/ingest/scaffold.py:70–105`,
`.claude/skills/kb-summarize/SKILL.md`, the 5 init templates,
`tests/test_{summarize,summarize_cli,summarize_e2e,build,mdutils,llm,cli_approve,review,templates}.py`,
`tests-gate/conftest.py`, specs `2026-07-11-llm-auto-summarize-design.md`,
`2026-07-11-summarize-quality-design.md`, `2026-07-15-kb-approve-restore-design.md`.

Executed (all in `…/scratchpad/B/`, foreground):

1. Full per-section metric extraction over the bundled KB (329 sections) — L2/L3 prose
   chars after `strip_tables` + heading/placeholder removal, table blocks, L1 word counts.
2. `kb summarize --redo arinc-424` on a **copy** of `.kb`, with a fake `claude.cmd` on PATH
   returning a fixed 240-char `l2_summary`; then `kb build` + `kb stats` on the result.
   Prompt sizes logged by the stub (320 logged calls; 5-worker append races lose a few).
3. 24 adversarial `kb build` mutations on a purpose-built 5-section synthetic KB
   (`scratchpad/B/adv/`), each a fresh copy + one mutation + the real `kb build` binary.
4. `normalize_table` equivalence probing (whitespace classes, NFKC, alignment, CRLF).
5. `parse_json_reply` / `_extract_reply` fuzzing with 15 + 6 realistic model/envelope replies.
6. Windows `CreateProcess` / `cmd.exe` argv experiments against a `.cmd` shim, then an
   **end-to-end `kb summarize --llm copilot`** run proving the failure.
7. Duplicate-section-id KB, `--redo`-under-outage blast-radius KB, empty-L0-summary KB.
8. Test run: `pytest tests/test_summarize*.py test_build.py test_mdutils.py test_llm.py
   test_cli_approve.py test_review.py -q` → **102 passed in 63 s**.

---

## Verified-good

* **`--redo` scaffold rebuild is genuinely deterministic and table-safe.** After
  `kb summarize --redo arinc-424` on the real 325-section doc, all **1281 table lines are
  byte-identical** to the originals and **0/325 sections** have a differing table block;
  `kb build` → OK. `rebuild_l2_scaffold` (summarize.py:286) is idempotent
  (`tests/test_summarize.py:358`). C4's `--redo` claim holds.
* **Redo refuses to run without a runner** (cli.py:578–584) — it probes before destroying.
  Good instinct, though see B-4 for what it does not cover.
* **The table-integrity latch does work for the direction it checks.** Every content-level
  mutation I threw at an L3 table was rejected: cell edit, added row, reordered rows,
  reordered columns, deleted table, table split by a blank line, table moved to another
  section, NBSP inserted mid-word, fullwidth digit `１` for `1`, `\|` inserted.
* **`_is_table_only` short-circuit really skips the LLM** (summarize.py:178–182), and the
  ≤ 2-calls-per-section rule is hard-coded (`for _ in range(2)`, summarize.py:186) with a
  retry prompt that states the violated budget. C4's call-budget claim holds.
* **Failure isolation is real**: per-future `except Exception` (summarize.py:232) — the
  5-way `529 overloaded` experiment produced 5 clean `[fail]` lines, exit 1, no partial writes.
* **`kb build` correctly rejects**: a TODO marker anywhere in the slice *including inside a
  fenced code block*, an empty manifest summary, a manifest section absent from L2/L3; and
  it recounts tokens and warns at L0 > 1000 (bundled L0 = 187 tokens).
* **`kb approve` is idempotent and id-safe**: it iterates sections rather than keying on id
  (review.py:33–36, correctly anticipating duplicate ids), skips `pending` with a warning,
  errors on an unknown `--section`, exits 1 in manual mode with nothing to flip.
* **JSON parsing survives the two most common wrappers** (```` ```json ```` fences, prose
  before the object) and `JSONDecodeError` is a `ValueError` subclass, so every parse
  failure is caught by `_summarize_one` — there is no crash path.
* All 102 tests in the area pass.

---

## Findings

### CRITICAL

#### B-1 — On Windows the Copilot runner silently truncates the prompt to its first line; the pipeline accepts the resulting hallucination and `kb build` says OK

`src/center_kb/llm.py:36-37`

```python
# copilot CLI takes the prompt as an argument, not stdin
cmd = [self.executable, "-p", prompt, "--model", self.model]
```

`shutil.which("copilot")` on Windows resolves the npm shim `copilot.CMD` (verified:
`which('copilot') -> …\copilot.CMD` even with an extensionless sibling present; Python
3.11, PATHEXT contains `.CMD`). Running a `.cmd` goes through `cmd.exe`, which **cuts the
argument at the first newline** and **expands `%VAR%`**.

Repro (end-to-end, real `kb` binary, stub `copilot.cmd` that echoes `len(argv[2])`):

```
$ kb summarize --llm copilot --kb-dir <scratch> --redo
redo: 5 section(s) reset to pending
Summarizing with copilot (sonnet-5), 5 workers…
  [ok] testdoc/5.3 … 5 summarized, 0 failed.
$ head -3 <scratch>/testdoc/doc.md
## 5.3 Alpha Field
[stub saw 58 prompt chars; last 30: ' for a knowledge-base section.']
$ kb build --kb-dir <scratch>
kb build: OK
```

58 chars = `"You are filling in summaries for a knowledge-base section."` — the model never
sees the section id, the title, the source text, the char budget, or the JSON contract.
Whatever it invents is written into L2, flipped to `status: summarized`, and passes the
gate. Additional probe: `-p "a & b | c > d ^ e %PATH% !x!"` arrived as **1852 chars** —
`%PATH%` was expanded, i.e. host environment values can be injected into an LLM prompt.

Also measured on the same shim: >8100 chars → `The command line is too long.` (rc 1);
~8000 chars → corrupted invocation, rc 255; ≥ 32767 → `WinError 206`. 2 of the 320 real
arinc-424 prompts exceed 8100 chars, so even without the newline bug the copilot path
cannot summarize the largest sections on Windows.

Why the suite misses it: `tests/test_llm.py:61` calls `runner.run("prompt")` — one word,
no newline. The spec itself (`2026-07-11-llm-auto-summarize-design.md:59`) wrote the design
as `copilot -p "<prompt>"`.

Violates **C4** (prose-only prompt actually delivered), **C2** (no invention), **C15**
("Windows fully supported"). Fix: pass the prompt via a file or stdin; at minimum refuse a
prompt containing `\n` when `os.name == "nt"`.

#### B-2 — L2 prose transcribes table content and materially misstates it; the "most important safety latch" cannot see it (confirms and hardens F-A)

The verbatim-table check protects the *copy* of the table. It says nothing about prose that
**re-encodes** the same table above it. Measured on the shipped KB: of the 90 arinc-424
sections that contain an L3 table, **44 (49%)** have an L2 prose sentence containing ≥ 4
tokens that are cells of that section's own tables.

Worst case, `arinc-424 §5.7 Route Type` (L3 prose 1803 chars → L2 prose **2006 chars, 1.11×**):
the L2 paragraph restates Tables 5-2/5-3/5-4/5-5 in full, and it is **wrong**:

| L3 table cell (verbatim, sitting 3 lines below in the same L2 file) | L2 prose |
|---|---|
| `Officially Designated Airways, except RNAV, RNP or Helicopter Airways` → `O` | "Officially Designated Airways **O**" — the exception clause is dropped, so `O` reads as covering RNAV/RNP |
| `North American Routes for North Atlantic Traffic` / `Common Portion` → `C` | "North American Routes for North Atlantic Traffic **C**" — "Common Portion" dropped, making `C` and `N` (Non-common) indistinguishable |
| `Airline Airway (Tailored Data)` → `A` | "Airline Airway **A**" |
| Note 1: "coded with Route Type R but includes **non PBN** segments" | "code N marks a **non-RNAV/RNP** segment" |

`arinc-424 §5.99 Marker Type` is the same failure in miniature: the L3 table encodes the
marker type across **columns 18/19/20** (`I`+`M`, `M`+`M`, `O`+`M`, `B`+`M`); the L2 prose
synthesizes the codes **`IM`, `MM`, `OM`, `BM`** — strings that occur nowhere in the L3
section. A deterministic check for "uppercase token in L2 prose that is not a substring of
the L3 section" finds **5/325** sections (`§5.35-x79 CLASS/NAVAID`, `§5.99 IM/MM/OM/BM`,
`§5.101 CTAF`, `§5.104 UHF`, `§5.229 GPS/WAAS`) — 1.5% hit rate, 4 of 5 real violations.

`kb build` on the shipped KB: **OK**. Violates **C1** ("tables are never rewritten by AI" —
they are, into prose) and **C2** ("tables never described or transcribed into prose";
"no invention").

---

### HIGH

#### B-3 — Duplicate section ids: the second section is given the first section's summary; `kb build` passes

`summarize.py:224` keys results on `(doc_id, section_id)`; `mdutils.slice_section` returns
only the first match; `_apply_results` (summarize.py:258) looks up `pairs.get(sec.id)` for
every manifest row. `review.py:33-36` explicitly documents that duplicate ids occur
("regulatory docs restart §-numbering inside each part").

Repro (`scratchpad/B/dup`, stub echoes back the `<source>` it received):

```
## 1.1 Part A Section 1.1
SUMMARY-OF[## 1.1 Part A Section 1.1  AAAA this is the body of PART A. ]
## 1.1 Part B Section 1.1
SUMMARY-OF[## 1.1 Part A Section 1.1  AAAA this is the body of PART A. ]   <-- Part A's text
```

Both manifest rows also get `L1-OF[…PART A…]`, and after `kb build` both carry the first
slice's token counts (`l2: 60, l3: 46`), so `kb stats` double-counts one section and never
counts the other. `kb build` → **OK**.

Latent in the shipped data (0 duplicate ids in either manifest), but it is silent
misinformation the moment a doc with restarted numbering is ingested.
Violates **C2** (a summary must describe *its* section) and **C5**.

#### B-4 — `kb summarize --redo` is an unconfirmed, whole-KB destructive operation; one transient API outage leaves the KB unbuildable with every SME approval gone

`cli.py:576-591` + `summarize.py:314-343`. `redo_reset(kb_dir, doc_id or None)` — omitting
`DOC_ID` resets **every document in the KB**. It resets `pending`, `summarized` **and**
`reviewed`, blanks `sec.summary`, and rewrites every L2 file, *before* any LLM call. The
`[warn] N reviewed section(s) were reset` line is printed **after** the write. There is no
`--yes`, no `--dry-run`, no backup. The pre-flight probe only checks that a runner binary
exists on PATH, not that it works.

Repro (`scratchpad/B/blast`, stub exits 1 with `529 overloaded`):

```
kb approve testdoc          -> 5 section(s) → reviewed
kb summarize --redo         -> redo: 5 reset ; [warn] 5 reviewed section(s) were reset
                               0 summarized, 5 failed.
kb build                    -> 5 × "[error] still has a TODO marker or an empty summary" (exit 1)
```

Every L2 paragraph and every sign-off is gone; recovery is git-only. The docs-as-code design
mitigates this, which is why it is HIGH not CRITICAL. Violates **C16** (SME sign-off is the
review gate).

#### B-5 — `rebuild_l2_scaffold` permanently deletes `Figure:` lines from L2

`summarize.py:286-305` keeps only `## ` headings, table lines, and the blank that closes a
table block; "anything else is prose/old summary/old marker -> dropped". But
`ingest/scaffold.py:88-89` writes `Figure: <alt>` lines into the L2 scaffold — content
derived from the source document, not from the LLM, and **absent from L3** (L3 carries the
`![alt](assets/<sha>.png)` markdown, not the `Figure:` line).

```
in : "Figure: Holding pattern entry sectors"  +  "![Holding pattern](assets/….png)"
out: (both gone)
```

So `kb summarize --redo` silently discards figure captions; only a full re-ingest restores
them, and nothing (build, doctor, diff) notices. Latent in the bundled KB (0 figures), but
`tests/test_scaffold.py:194` proves the framework emits them, and no test asserts `--redo`
preserves them. Violates **C4** ("`--redo` rebuilds scaffold deterministically" — it also
destroys).

#### B-6 — The length guard's 300-char floor makes the "hard 35%" limit a ~45% limit in aggregate and up to 14× per section

`summarize.py:126-127`: `return max(300, int(0.35 * len(prose)))`.

Measured on arinc-424 (325 sections):

| | value |
|---|---|
| sections where the **300 floor wins** | **207 / 325 (64%)** |
| Σ per-section budget ÷ Σ true L3 prose | **0.45** (spec says 0.35) |
| median budget ÷ true prose | **0.46** |
| sections whose budget **exceeds 100%** of their own prose | **24** |
| worst | `§5.320` — 21 chars of prose, **300-char budget = 14.3×** (`§5.191/2/3`: 25 chars → 12×) |

**Is the guard measured on the same string the prompt shows?** Yes —
`build_section_prompt` (summarize.py:130-136) and `_max_chars` are both fed
`section.l3_body`, so prompt and guard agree with each other. But `l3_body` is
`strip_tables(slice)`, which still contains the `## `/`### ` heading lines and the
`[table omitted]` placeholders, while the thing being measured
(`len(reply["l2_summary"])`, summarize.py:194) is prose only. Measured inflation on
arinc-424: headings 13 503 chars + placeholders 1 824 chars = **+5.7%** on the denominator
(`§5.319-x95`: 35 chars of prose, 507-char `l3_body`).

Structural cause of the worst offenders: `_is_table_only` (summarize.py:81-83) requires
*every* line to be a heading/placeholder/blank. An ARINC field section that is
`Used On: … / Length: … / Character Type: …` and nothing else has ~20–40 chars of
boilerplate "prose", is therefore **not** table-only, and gets a 300-char budget — so the
model writes 300 chars of invented framing. `§5.263 HAL`'s L2 literally reads *"This section
header (HAL) contains only field usage metadata in the extracted source text, with no
accompanying definition or source/content notes."* — meta-commentary about the PDF
extraction, in a navigation-data standard.

**Proposed fix** (all three parts needed):

```python
def _prose_only(l3_body: str) -> str:          # NEW — exclude what the model must not echo
    return "\n".join(
        l for l in l3_body.splitlines()
        if not l.lstrip().startswith("#") and l.strip() != TABLE_PLACEHOLDER
    ).strip()

def _max_chars(l3_body: str) -> int:
    n = len(_prose_only(l3_body))
    if n <= MIN_PROSE_FOR_SUMMARY:             # 200: too small to be worth an LLM call
        return n                               # verbatim-or-shorter; see below
    return max(120, int(0.35 * n))             # floor 120, measured on the same prose
```

plus: treat `n <= 200` as *near-table-only* — copy the L3 prose verbatim into L2 (it is
already shorter than any summary would be) and derive L1 deterministically, no LLM call.
On arinc-424 that removes ~207 LLM calls and every ratio > 1.0. Keep the guard, and **also
enforce it in `kb build`** (B-15) so the manual path is covered.

#### B-7 — `kb build` table integrity is one-directional, multiplicity-blind, order-blind inside a section, and ignores single-row tables (confirms and extends F-B)

`build.py:148-155` builds a *set* of normalized L2 tables and only asks whether each L3
table is a member. Full matrix (each row = fresh copy + one mutation + real `kb build`):

| # | Mutation | `kb build` |
|---|---|---|
| a | fabricated extra table added to an L2 section | **PASS — not caught** |
| b | an existing table duplicated in L2 | **PASS — not caught** |
| c | table moved from §5.4 to §5.5 (both have tables) | FAIL (rejected, 2 errors) |
| d | single-row (header-only) table deleted from L2 | **PASS — not caught** |
| e1 | alignment row `---` → `:--` / `--:` | **PASS** (by design, `normalize_table`) |
| e2 | trailing spaces on a row | **PASS** (by design) |
| e3 | double spaces inside a cell | **PASS** (by design) |
| e4 | space → NBSP mid-word (`Al\u00a0pha`) | FAIL (rejected) |
| e4b | `1` → fullwidth `１` (NFKC-equal) | FAIL (rejected) |
| e5 | `\|` escape inserted into a cell | FAIL (rejected) |
| f | two ROWS reordered | FAIL (rejected) |
| g | two COLUMNS reordered | FAIL (rejected) |
| h | section body deleted, heading + tables kept | **PASS — not caught** |
| i | a number changed inside L2 prose | **PASS — not caught** (SME's job; confirmed) |
| j | L3 prose edited after summarization | **PASS — not caught** |
| k | `<!-- TODO:summarize` inside a fenced code block | FAIL (rejected) |
| l | manifest section absent from L2/L3 | FAIL (rejected: "section not found") |
| m | orphan `## 5.8` heading + fabricated table in L2, not in manifest | **PASS — not caught** |
| p | fabricated ROW appended to a real table | FAIL (rejected) |
| q | two tables inside ONE section, order swapped in L2 | **PASS — not caught** |
| r | real table split by a blank line | FAIL (rejected) |
| s | single-row table's contents entirely rewritten in L2 | **PASS — not caught** |
| t | manifest `summary: ''` | FAIL (rejected) |
| u | L2 prose = 40× the L3 prose (zero compression) | **PASS — not caught** |

`extract_tables` (mdutils.py:295) requires `len(current) >= 2`, so a one-line pipe block is
invisible in **both** directions — case (s) is the sharp edge: a header-only table can be
replaced with arbitrary content and the gate is silent. The bundled data is currently clean
(0 single-row blocks among 114 L3 blocks; 0 extra L2 tables), so these are latent.
15 sections have ≥ 2 tables, i.e. case (q) is live today.

Additionally: **`build_kb` writes `_manifest.yaml` unconditionally** (build.py:161), even
when it is about to return errors — a "validate" command that mutates state; and sections
that hit the `continue` at build.py:138 keep stale token counts.

**What C1/C5 promise vs. what build enforces**

| Promise | Reality |
|---|---|
| C1 "Every L3 table appears verbatim in L2" | Enforced (modulo the deliberate `normalize_table` folding) |
| C1 "`kb build` … fails on one character of difference" | False as stated: NBSP/TAB/thin-space/alignment colons/CRLF/extra separator rows are folded (harmless, but not "one character"); U+200B and fullwidth digits *are* caught |
| C1 "Tables are NEVER rewritten by AI" | Enforced for the copy; **not** for prose that restates the table (B-2) |
| — (unstated) | No check that L2 has **no extra** tables, no multiplicity check, no intra-section order check, single-row tables unguarded |
| C5 "fails on any pending/TODO marker/empty summary" | Enforced — but "empty summary" means the **manifest L1**, not the L2 body: a section whose L2 prose is entirely gone passes (case h) |
| C5 "fails on table integrity" | One-directional only |
| C5 "recounts tokens" | Yes — and persists them even on failure |
| C5 "warns L0 > 1000 tokens" | Yes (bundled: 187) |
| — (unstated) | No orphan-heading check, no L3-hash/staleness check, no length/ratio check, no L0-summary check |

#### B-8 — The shipped KB was never re-summarized after the fix that exists to fix it, and README presents the resulting number as proof of success

`docs/superpowers/specs/2026-07-11-summarize-quality-design.md` decision **#6** reads:
"Sau khi merge: chạy `kb summarize --redo arinc-424` + `kb build` … Người dùng đã duyệt
re-run toàn bộ 449 section." Git says it never happened: `.kb/arinc-424` has exactly one
commit, `efc5582` (2026-07-10); the four quality commits (`a95698f`, `fa6078b`, `6e03f27`,
`893a4f2`) are all 2026-07-11.

Measured today (all headings, tables and placeholders excluded from both sides):

| doc | L2 prose / L3 prose | target | > 0.35 | L2 prose ≥ L3 prose |
|---|---|---|---|---|
| arinc-424 | 216 003 / 275 299 = **0.785** | 0.20–0.30 | **325 / 325** | **52** |
| icao-annex-3 | 9 285 / 12 418 = **0.748** | 0.20–0.30 | 4 / 4 | 0 |

Worst: `§5.319-x95` 456/35 = **13.03×**, `§5.115-x87` 531/98 = 5.42×, `§5.23-x78` 874/258 =
3.39×, `§5.263 HAL` 244/98 = 2.49×, `§5.283` 968/413 = 2.34×, `§5.106` 1141/528 = 2.16×.

`README.md:414` prints `arinc-424 … 76126 … 11.1%` inside **§10 "Proof it works (real PoC
numbers)"**, and `README.md:418` explains the low number away as an artefact of measuring a
whole document. It is not — it is ~3× the specified prose budget. Note also that the spec's
own architectural excuse ("tables are ~80% of a table-dense doc, so the saving ceiling is
~20–25%") does **not** apply to the shipped chapter: tables are **27%** of arinc-424 L3
tokens (23 170 / 85 669), so the ceiling is ~68%, not 25%.

---

### MEDIUM

#### B-9 — `kb approve` verifies nothing, records nothing, and `reviewed` is not load-bearing

`review.py:18-57`, `cli.py:1705-1783`. It flips `summarized → reviewed` and saves. It does
**not** run `kb build`, does not check table integrity, does not check that the git tree is
clean, does not require that a diff was viewed. Proven on the KB from case (a) — which
contains a **fabricated table**:

```
$ kb approve testdoc --kb-dir <kb_a_extra_table>
testdoc: 5 section(s) → reviewed: §5.3, §5.4, §5.5, §5.6, §5.7   (exit 0)
```

`--restore` is not a flag — the spec `2026-07-15-kb-approve-restore-design.md` is titled
"*Restore* `kb approve`" (re-adding a command deleted in `6116566`); the surface is
`[DOC_ID] [--section …] [--all-changed --against <rev>]`, and `kb approve <doc>` with no
`--section` flips the whole document (325 sections for arinc-424) in one keystroke.

Downstream consumers of `reviewed`: `web/uidata.py:110/138/175` and `web/ui.py:353` (dashboard
counts + filter), `codeingest/core.py:620,1145` and `svcnote.py` (refuse to overwrite
human-edited `-code`/`-svc` text). **Not** consulted by `build.py`, `publish.py`, `query.py`,
`resolve.py`, `ticketlint.py`, or `doctor.py` — `kb publish` mirrors `summarized` content to
the hub exactly like `reviewed` content. The manifest stores no reviewer identity, no
timestamp, and no hash of what was approved, and `--redo` erases the flag (B-4).

Dogfood check: **both shipped manifests total 329 sections, all `summarized`, zero
`reviewed`.** The SME gate has never been exercised on the project's own flagship KB.
Against **C16**, the signal is decorative for the L0–L3 flow.

#### B-10 — No provenance: nothing records which model or prompt produced a summary

`models.SectionEntry` = `{id, title, summary, status, file, tokens}`; `Manifest` adds
`{revision, ingested, source_sha256, ingest}`. There is **no** `model`, `effort`,
`prompt_version`, `summarized_at`, `runner`, or `reviewed_by`. `index.yaml` carries an
`llm:` block, but that is *current config*, not what ran — and the shipped `index.yaml` has
no `llm:` block at all, so the 329 summaries in the repo have literally zero recorded
provenance. In a regulated domain this makes L2 non-reproducible and non-auditable: you
cannot answer "which model wrote this sentence, under which prompt revision, and was it
re-checked after the 2026-07-11 rule change?". Cheapest fix: one
`provenance: {runner, model, effort, prompt_sha, at}` per section, written by
`_apply_results`.

#### B-11 — No L3 hash: editing the source after summarization is undetectable

Case (j): I rewrote an L3 paragraph after the section was `summarized`; `kb build` → OK,
status unchanged. `kb diff` does report `content_changed` against a git rev
(`diff.py:15-18`), but nothing demotes the section, and `kb approve --all-changed` would
report "nothing to approve" because the section is already `reviewed`. Storing
`l3_sha256` per section and failing on mismatch is a ~10-line build check.

#### B-12 — `parse_json_reply`'s brace-span heuristic breaks on realistic model output

`summarize.py:145`: `start, end = text.find("{"), text.rfind("}")`. Fuzzing results:

| reply | result |
|---|---|
| ```` ```json {…} ``` ```` | OK |
| `Sure! Here is the JSON:\n{…}` | OK |
| `{…}\nHope that helps!` | OK |
| `{…}\nNote: use {curly} braces carefully.` | **JSONDecodeError** |
| `Analysis {of the section}\n{…}` | **JSONDecodeError** |
| two JSON objects on two lines | **JSONDecodeError** |
| trailing comma / single quotes / raw newline inside a value | **JSONDecodeError** |
| nested `{5.3}` *inside* a value; escaped `\"` | OK |
| `[{…}]` array wrapper | OK |

All are caught (`JSONDecodeError` ⊂ `ValueError`), so nothing crashes — but each costs the
full 2-call budget and leaves the section `pending`. A brace-balanced scan (or: try each
` ```json ` fence, then each balanced `{…}` span left-to-right) removes the whole class.

#### B-13 — `_extract_reply` ignores `is_error` / `subtype`, so the real API error is discarded

`llm.py:57-67`. `{"type":"result","subtype":"error_during_execution","is_error":true,
"result":"API Error: 500"}` returns `"API Error: 500"` as if it were the model's reply; the
operator then sees `[fail] doc/§x: no JSON object in reply` instead of the actual error.
`subtype: error_max_turns` with an empty `result` degrades the same way (and a *partial*
`result` that happens to contain a JSON object would be accepted as a summary). Two lines
fix it: `if envelope.get("is_error"): raise RunnerError(envelope.get("result") or subtype)`.

#### B-14 — The L0 doc summary is never refreshed once nothing is pending, and an empty one passes `kb build`

`summarize.py:221-222` returns early when `collect_pending` is empty, *before*
`_fill_doc_summaries`. So a doc whose sections are all `summarized` but whose `index.yaml`
summary is blank can never be repaired by `kb summarize`:

```
$ kb summarize --llm claude --kb-dir <kb with summary: '' and 0 pending>
0 summarized, 0 failed.            # index.yaml summary still ''
$ kb build --kb-dir <same>
kb build: OK
```

And when `_fill_doc_summaries` *does* run and the call fails, it only emits
`[warn] doc summary failed for <id>` (summarize.py:363-364) without touching
`report.failed`, so `kb summarize` still exits 0. `kb build` never checks that an
`index.yaml` entry has a summary. C2 makes L0 the tag pre-filter for every query (C6), so a
silently empty L0 entry costs recall. Fix: run `_fill_doc_summaries` for any doc with a
blank `entry.summary`, count its failure in the report, and error in `build_kb`.

#### B-15 — Everything C2 promises besides table verbatimness is unchecked; cheap deterministic checks exist for all of it

Measured against the shipped KB so the false-positive cost is known:

| C2 promise | Machine-checked today | Cheapest deterministic check for `kb build` | Result on the shipped KB |
|---|---|---|---|
| L1 ≤ 25 words | **No** | `len(sec.summary.split()) > 25` → error | 0/329 violations (max exactly 25) — free to add |
| L2 ≤ 35% of L3 prose | **No** (only at generation time) | `len(l2_prose) > 0.35*len(l3_prose)` → **error** when `l3_prose > 400`, else warn | 325/325 arinc + 4/4 icao fire today; 322 exceed even 0.50 |
| L2 prose not silently deleted | No (case h) | `l3_prose > 200 and l2_prose == 0` → error | 0 today |
| source-language match | **No** | lexical overlap: share of L2 prose word-types present in the L3 slice — a translated or hallucinated summary collapses | median 0.86, p05 0.75, min 0.28 (arinc); `< 0.45` error + `< 0.65` warn fires on exactly 1 section (`§5.263 HAL` — a true positive) |
| codes/units verbatim, no invention | **No** | every `\b[A-Z]{2,8}\b` in L2 prose must be a substring of the L3 slice → error | **5/325**, 4 of them real (§5.99 `IM/MM/OM/BM`, §5.101 `CTAF`, §5.104 `UHF`, §5.229 `GPS/WAAS`) |
| no table transcription | **No** | any L2 prose sentence containing ≥ 4 distinct cell values of that section's own L3 tables → error | **44/90** table-bearing sections, incl. §5.7 (B-2) |
| "Table-only section: `<title>`." label consistency | **No** | if `_is_table_only(l3_body)`: require `sec.summary == f"Table-only section: {sec.title}."` **and** empty L2 prose | 0 table-only sections shipped, so free |
| L0 summary present | **No** | `not entry.summary.strip()` → error (B-14) | 0 today |
| no invented tables / no orphan sections | **No** | symmetric set compare + multiplicity (`Counter`) + `## ` headings ⊆ manifest ids | 0 today (B-7) |

Every one is O(text) with no new dependency and no LLM. They belong in `build_kb` because
that is the only place the engine path and the manual path converge.

#### B-16 — The manual `/kb-summarize` path does not follow the same rules as the engine, and nothing pins it

C4 requires "manual `/kb-summarize` path follows the same rules". Diffing
`.claude/skills/kb-summarize/SKILL.md` and the 3 assistant templates against
`SECTION_PROMPT` (summarize.py:14-43):

| Rule | Engine | Manual paths |
|---|---|---|
| what the model sees | tables **physically removed**, replaced by `[table omitted]` (kills the transcription failure mode at the root — spec RC2) | the sub-agent runs `kb get <doc> <sec> --level l3`, i.e. **reads the tables**, and is merely *told* not to use them. Biggest divergence, and the most likely origin of the 44/90 transcriptions in B-2 |
| length budget | explicit integer: "at most **{max_chars} characters**", enforced after parse with 1 retry | SKILL.md:84 "under ~**35%** of the original prose length" **and** :86 "~**20–30%** of the original length" — two numbers, no integer, **units unstated** (chars? words?), no floor. Nothing measures it |
| denominator | `l3_body` = prose after `strip_tables` | "the original prose length" — undefined; a model reading the full L3 plausibly measures against a section that is 27% tables, inflating the allowance |
| table-only detection | deterministic `_is_table_only`, LLM never called | the **model** returns `"table_only": true/false` — non-deterministic; can disagree with the engine on the identical section |
| validation step | char guard + strict retry | SKILL.md:43-44 validates "every assigned section present; `l1_summary` ≤ 25 words; `l2_summary` non-empty" — the **length rule is absent from the validation list**. The Copilot/Cursor variants have no validation step at all beyond `kb build`, which does not check length |
| doc summary | DOC_PROMPT: "ONE sentence (max **30 words**)" | "fill the doc's one-sentence `summary`" — no word cap |
| `Table-only section:` label | written by code, always exact | asked of the model, unverified |
| table-only L2 result | marker replaced by `""` (blank line remains) | "delete the marker line (leave nothing)" — different whitespace, harmless |

`tests/test_templates.py` does **not** pin the summarize wrappers — its only mention of
`summarize` is line 922, inside the *dev-code-seed* canon suite. `tests/test_init.py` pins
their **paths and existence** only (lines 613–664, 686). Compare `dev-code-seed`, which has
~8 content-canon tests. The drift is already real: `.claude/skills/kb-summarize/SKILL.md:95`
says "so **BM25** matches technical keywords" while the shipped template
`src/center_kb/templates/init/claude-skill-kb-summarize.md:95` says "so **keyword search**
matches" — the repo's dogfood copy and the artefact it ships differ, and `kb init` would
silently rewrite the repo's own file.

#### B-17 — Concurrency and runner-config hardening gaps

* `max_workers: 5` (models.py:385) drives 5 concurrent `claude -p` sessions against one
  binary and one credential. There is **no** backoff, no jitter, and no 429/529-aware retry:
  the single retry in `_summarize_one` fires immediately with the same prompt. On the
  325-section doc that is 325+ sessions; my `529 overloaded` run shows the whole batch fails
  together and every section stays `pending` — recoverable, but the operator must re-run.
* `timeout: 300` is **per call**, with no overall budget. Worst case for arinc-424 is
  ⌈325/5⌉ × 2 × 300 s ≈ 10.8 h with no progress deadline.
* `LLMConfig.effort` is a bare `str`, not a `Literal` (contrast `runner`), so `effort: "hgih"`
  silently means "no thinking budget", indistinguishable from a deliberate `effort: "medium"`.
  It is also a complete no-op for `copilot` (`llm.py:40` checks `self.name == "claude"`).
* `env=None` for every call except claude+high is correct (the child inherits), and
  `os.environ | {…}` on Windows preserves `SYSTEMROOT` etc. — no defect found here.
* Prompt sizes on the real doc (320 logged calls): min 1 364 / median 2 017 / p95 3 354 /
  **max 13 308** chars, 715 656 chars total ≈ 180 k input tokens for one `--redo`.

---

### LOW

* **B-18** C1's line "fails on one character of difference" is inaccurate.
  `normalize_table` (mdutils.py:321-329) deliberately folds NBSP / TAB / thin space →
  space, `---` vs `:--` vs `--:`, trailing spaces, collapsed inner runs, CRLF, and any
  number of extra separator rows. All harmless; the *claim* should read "byte-identical
  after whitespace/alignment normalization".
* **B-19** Orphan `## ` headings in L2 that are absent from the manifest are invisible to
  build (case m) — an assistant that invents a whole section is not caught.
* **B-20** `kb stats`' `saving` column reads the manifest's cached `tokens`, which only
  `kb build` refreshes; before the first build it prints 0 %.

---

## Measured estimate: what would re-summarizing the bundled KB today actually achieve?

`kb summarize --redo arinc-424` **run for real** on a copy of `.kb` with a stub returning a
fixed 240-char summary (i.e. an idealised, always-compliant model):

```
before: arinc-424  325 sections  L1 28491  L2 76126  L3 85669   saving 11.1%
after : arinc-424  325 sections  L1 20502  L2 43566  L3 85669   saving 49.1%     kb build: OK
```

Decomposition of the post-redo L2 (43 566 tokens): **23 170 tokens of verbatim tables +
4 145 tokens of headings = 27 315 tokens that no summarizer can remove** — the hard ceiling
for this document is **68.1% saving**, not the ~20–25% the spec assumed (tables are 27% of
L3 tokens here, not 80%).

Projecting the *current engine's* behaviour with a real model (floor + guard applied per
section):

| model behaviour | resulting L2 | saving | sections still > 35% of true prose | sections still ≥ 100% |
|---|---|---|---|---|
| obeys "~25% of prose" | ~44 500 tok | **48.0%** | 0 | 0 |
| realistic (25%, but ≥ ~120 chars/section) | ~45 300 tok | **47.1%** | 27 | 12 |
| uses the full budget it is given | ~58 400 tok | **31.8%** | **325** | 24 |
| *shipped today* | 76 126 tok | 11.1% | 325 | 52 |

So: **expect roughly 45–50% document-level saving, ~4× better than today** — a real
improvement that would land inside the guard for the large sections. **What would still
slip through, by construction:**

1. **Table transcription (B-2).** `strip_tables` stops the model *seeing* the tables, so
   large-scale transcription should collapse — but nothing verifies it, and the manual
   `/kb-summarize` path (which still reads the tables) reintroduces it.
2. **The 207 short sections (64%).** With a 300-char floor against 21–40 chars of source,
   the engine still licenses ~300 chars of model-written framing per section; the 24
   sections whose budget exceeds their own prose stay legal. `§5.263 HAL`-style
   meta-commentary is exactly what the floor invites.
3. **Invented codes.** Nothing checks that an uppercase token in L2 prose exists in L3 — the
   5 current hits would survive a redo unless the model happens to behave.
4. **Docling noise (F-C) and fallback-id sections (F-D)** are inputs; a redo re-summarizes
   the noise faithfully rather than removing it.
5. **L1 quality, source language, L0 summaries** — unmeasured before and after.
6. **Nothing about the redo would be recorded** — same manifest shape, no model, no date, no
   prompt version (B-10) — so a reviewer in six months cannot tell which sections are post-fix.
7. **If the operator's runner is Copilot on Windows**, the redo produces 325 pure
   hallucinations and `kb build` still says OK (B-1).

---

## Criteria scorecard

| Criterion | Verdict | One-line reason |
|---|---|---|
| **C1** Tables never rewritten by AI; build fails on any difference | **Partially met** | The verbatim copy is well protected (every content mutation rejected), but the check is one-directional / multiplicity-blind / single-row-blind (B-7), and it does not stop the AI from *re-encoding the same table into prose above it* — with real errors (B-2). "One character" is also inaccurate (B-18). |
| **C2** L2 = 20–30% of prose (guard 35%), source language, verbatim codes, no invention, no table transcription, table-only ⇒ no LLM prose | **Not met** | Shipped ratio 0.785 / 0.748, 325/325 over the guard, 52 sections longer than their source (B-8); 44/90 table-bearing sections transcribe tables; 5 sections contain invented codes; and of the eight sub-promises exactly one (table verbatimness) is machine-checked (B-15). |
| **C4** Prose-only prompt, explicit char budget, ≤ 2 calls, over-length ⇒ retry once ⇒ pending, manual path same rules, `--redo` deterministic | **Partially met** | Prose-only prompt ✔, explicit budget ✔, ≤ 2 calls ✔, retry-then-pending ✔, `--redo` byte-identical on 1281 table lines ✔ — but the 300-char floor makes the budget a 0.45× guard in aggregate (B-6), the manual path materially differs (B-16), `--redo` destroys `Figure:` lines (B-5) and the whole KB on a bare flag (B-4), and on Windows+Copilot the prompt never reaches the model at all (B-1). |
| **C5** Build fails on pending/TODO/empty summary, fails on table integrity, recounts tokens, warns L0 > 1000 | **Partially met** | All four stated behaviours verified working (incl. TODO inside a code fence). But "empty summary" only means the manifest L1 — an emptied L2 body passes; table integrity is one-directional; the gate misses 8 of 24 adversarial mutations (B-7); and it writes the manifest while failing. |
| **C16** (`kb approve` slice only) SME flips `summarized → reviewed` | **Partially met** | The command works, is idempotent and duplicate-id-safe — but it validates nothing (it approved a KB containing a fabricated table), records no reviewer/time/hash, is erased by `--redo`, gates nothing downstream (publish ships `summarized` content), and has never been run on the repo's own KB (329/329 `summarized`). |

---

## Top 3 recommendations

1. **Fix the Copilot runner before anything else, and prove it with a realistic prompt
   (B-1).** Stop passing the prompt as an argv element — pass a prompt file or stdin; if the
   CLI truly requires argv, refuse when `"\n" in prompt or len(prompt) > 7000` on Windows.
   Change `tests/test_llm.py:61` to push the actual `SECTION_PROMPT` (multi-line, ~3.5 kB)
   through the stub and assert the stub received all of it — that one-line test change turns
   a silent hallucination generator into a red build.

2. **Move the quality rules from the prompt into `kb build`, then re-summarize and re-approve
   the shipped KB (B-2, B-6, B-8, B-15).** Add the nine O(text) checks from B-15 — ratio
   guard measured on prose with a 120-char floor, near-table-only sections (< 200 chars of
   prose) copied verbatim instead of summarized, and the table-transcription and
   invented-code detectors. Ship them as warnings for one release, then as errors. Then
   finally execute spec decision #6 —
   `kb summarize --redo arinc-424 && kb build && kb approve arinc-424` — and replace the
   `11.1%` in README §7.7 / §10 with the measured post-fix number (expect ~45–50%). Anything
   the new checks flag on the real doc is a genuine defect, as §5.7 and §5.99 demonstrate.

3. **Make the review signal and the provenance real (B-3, B-4, B-9, B-10, B-11).** Per
   section store `l3_sha256` and `provenance: {runner, model, effort, prompt_sha, at}`; on
   approve store `reviewed: {by, at, l2_sha256}`. Then `kb build` errors when a `reviewed`
   section's `l2_sha256`/`l3_sha256` no longer matches, `kb publish` refuses (or loudly
   warns) on `summarized` content, and `kb summarize --redo` requires `--yes` when it would
   reset `reviewed` sections, defaults to one doc, and prints its warning *before* it writes.
   Close B-3 in the same pass by keying summarize results on the manifest row index rather
   than `(doc_id, section_id)` — five lines, and today's behaviour silently attributes one
   section's text to another.
