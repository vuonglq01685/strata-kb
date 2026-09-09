# Reviewer E — BA side: do the Definition-of-Ready gates guarantee Dev-ready, KB-grounded tickets?

Area: criterion **C10** (BA gates) plus the BA halves of **C8** (kb-context) and **C16** (docs-as-code / scaffold trip-wires).
Repo: `D:\Projects\AERO-KB` @ `4b47b4c`, read-only. All experiments in
`…/scratchpad/E/`.

---

## Scope & method

**Live environment built from scratch** (mirrors `scripts/demo-federation.sh` 1–3):

1. `…/E/hub` — bare kb-hub (`.kb/index.yaml`, `federation/`), git-init'd.
2. `…/E/aero` — a **copy of the repo's real `.kb/`** (arinc-424 + icao-annex-3) published as repo id `aero`
   → `kb publish` → hub HEAD `272953a`, so real refs such as `arinc-424 §5.129` resolve for real.
3. `…/E/ba` — `kb init --kind ba` (20 files), `.kb/config.yaml` `hub:` pointed at the local hub,
   `CENTER_KB_HUB_CACHE=…/E/cache`, CLI `D:/Projects/AERO-KB/.venv/Scripts/kb`.
4. Pinned block generated for real: `kb context new --refs "arinc-424 §5.129"` →
   `version: "272953a"`, `refs: [aero:arinc-424 §5.129]`, `tags: [airport, airspace, airway, arinc424, navaid, navdata]` (auto-derived).

**Then:** one template-compliant "golden" ticket + one golden mission (both **PASS**), and **41 adversarial
mutations** of them run through the real `kb ticket lint` / `kb mission lint`; upstream amendment + republish to
test staleness; `kb init` re-run to test scaffold preservation; direct probes of `acquality.weasel_hits` and
`lintcore.INLINE_CITE_RE`; reading of `ticket.py, ticketlint.py, missionlint.py, lintcore.py, review.py,
acquality.py, mission.py, kbcontext.py, doctor.py, cli.py`, the 7 BA templates, all 8 BA wrapper variants, and
specs `2026-07-17`, `2026-07-28`, `2026-08-12 ×2`, `2026-08-22`.

**Tests run (foreground):**
`pytest tests/test_ticketlint.py test_missionlint.py test_lintcore.py test_review.py test_acquality.py test_cli_ticket.py test_cli_mission.py test_mission_ticket_traceability.py -q` → **222 passed in 130 s**.
`pytest tests/test_templates.py -q` → **123 passed**. `pytest tests/test_mcp.py -q` → **20 passed**.
The suite is green; every finding below is a gap the suite does not cover, not a broken test.

Two parallel sub-audits contributed the wrapper diff (Q4/Q6) and the CI+MCP audit (Q7/Q8); their claims were
delivered with file:line quotes and are attributed inline.

---

## Verified-good (calibration — this side of the framework is genuinely well built)

| # | Verified | Evidence |
|---|---|---|
| V1 | **The golden path works end-to-end on real data.** A template-compliant ticket citing `arinc-424 §5.129` with a real pinned block → `DoR: PASS`, exit 0. Golden mission → `DoR: PASS`. | `…/E/ba/tickets/M-nav-restrict-US1.md` |
| V2 | **`--json` envelope is exactly C10's contract.** `{"pass": bool, "errors": [...], "warnings": [...], "notes": [...]}` for both ticket and mission, with `notes` populated for skipped checks. | `lintcore.py:78-84`; ran both |
| V3 | **kb-context integrity (C8/A1/A2) is real and strict.** Random hex version → error; empty version → error; commit predating the doc → error; `tags: [ghost-tag]` → **error** with a `did you mean` hint and an explicit "never re-run `kb context new`" instruction; tags auto-derived by `kb context new` with no agent input. | `lintcore.py:393-465`, `kbcontext.py:178-191`; T12/T13a/T13c/T13d |
| V4 | **Citation cross-check (forward) is sound and punctuation-tolerant.** `arinc-424 §5.129.` (sentence end), `(arinc-424 §5.129)`, `…§5.129, and` all match; a citation to a section not in `refs` is a hard error. Citations inside ``` fences correctly do **not** count. | `lintcore.py:50-53, 361-390`; T6/T8/T9a/T9b/T9d |
| V5 | **Required headings hidden in a ``` fence do not count** (the pasted-example attack is closed). | `lintcore.py:132-156`; T19 → 9 heading errors |
| V6 | **Mission↔ticket traceability works in the scaffolded layout.** Ghost parent mission → error; ticket filename not in the mission backlog → error naming both fixes; sibling `missions/` auto-resolution is gated on `path.parent.name == "tickets"`; a typo'd `--missions-dir` is a hard error, not a silent skip. | `ticketlint.py:119-223`, `cli.py:1567-1596`; T10b/T11 |
| V7 | **Mission C4 level keywords are level-specific.** A `C4Context` diagram under `## Containers (C4 L2)` fails; a swapped pair fails both ways. Missing L2 fails. Backlog ids not derived from the mission id fail. Mission filename ≠ mission id fails. | `mission.py:101-103`, `missionlint.py:82-180`; M1/M2/M5/M6 |
| V8 | **Backlog parser is defensive**: rows above the header row, a missing separator row, trailing non-table prose, duplicate ids, and zero rows are each their own error; coverage is *visibly skipped* (a note) when the backlog is broken rather than silently passing. | `missionlint.py:112-180, 337-366` |
| V9 | **`kb resolve` exit codes are 0/1/2 as specified** — ran: stale → 2, broken → 1. | verified |
| V10 | **MCP/CLI parity is honest.** `kb_ticket_lint` runs the same `ticketlint.lint()`; the two filesystem-dependent checks it cannot run are reported as a `[note]` that *reaches the agent* via `render()`; hub-unreachable returns `HUB_DOWN`, never a passing report; `kb_mission_lint` is deliberately absent and pinned by 3 tests + the golden. | `mcp.py:201-217`, `lintcore.py:86-95`; sub-audit ran it |
| V11 | **CI gate change detection is genuinely correct.** No `paths:` filter (the "always start, decide inside" pattern, so a required check can never hang); `fetch-depth: 0` + `origin/${base_ref}...` three-dot; `--diff-filter=ACMR` (deletions excluded); `-z` + `IFS= read -r -d ''` + `core.quotePath=false` (spaces/Unicode safe); renames emit only the destination; **all** failing files are reported (`|| status=1`, loop fed by redirect not pipe); a missing base ref aborts loudly instead of reading as "clean". Behaviourally tested in `tests/test_init.py:1134/1239/1311/1353`. | `templates/init/kb-ticket-lint.yml:20-115`; sub-audit ran each case |
| V12 | **No false green on a fork PR.** Empty `CENTER_KB_HUB` → `require_hub` falls back to `.kb/config.yaml` → either "no hub configured" or "could not reach hub", both `exit 1`. There is no code path where an unresolvable hub yields a passing lint. | `cli.py:368-392`, `config.py:48-54`; sub-audit ran both |
| V13 | **All 8 BA wrappers forbid Jira pushes and forbid agent-chosen tags** (A4), with `no citation, no claim`, `%%TODO: verify against codebase%%`, and `OPEN(<owner>)` fallbacks so the agent has a non-fabricating exit at every point. Pipeline is 8 steps, same order, in all 8. | sub-audit, quotes at `claude-skill-ba-ticket-author.md:78-83, 138-139, 168` etc. |
| V14 | **`kb init` re-run preserves `.kb/config.yaml`** (hub survived; only `kind: ba` appended) and `.claude/settings.json`. | `initcmd.py:156-158`; ran |

---

## Findings by severity

### HIGH-1 — "Dev-ready by construction" is not delivered: the gate accepts an empty ticket

The 2026-08-12 upgrade spec's stated goal (`2026-08-12-ba-template-skill-upgrade-design.md:9-10`) is *"Make BA
missions/tickets Dev-ready **by construction**: verifiable ACs, owned placeholders, NFR / UI / sequencing
sections."* The gate checks **presence**, never **substance**, for every required section.

Repro (`…/E/t/variants/T1-empty-bodies.md`, `T3-no-gwt.md`, `G1-gamed.md`):

```
$ kb ticket lint T1-empty-bodies.md        # every required heading, every body "TBD"
… 9 warnings … DoR: PASS      (exit 0)

$ kb ticket lint T3-no-gwt.md              # ACs = "Store the designator (arinc-424 §5.129)."
DoR: PASS   with ZERO warnings             (exit 0)

$ kb ticket lint G1-gamed.md               # capstone, below
… 3 warnings … DoR: PASS      (exit 0)
```

`G1-gamed.md` passes with: ACs *"The system shall behave correctly and handle all edge cases gracefully"* /
*"Performance is acceptable and the data is validated properly"*; an NFR table reading `| Speed | fast | eyeball
| n/a |`; UI spec *"Looks nice."*; test data *"Use production data."*; every Definition-of-Ready checkbox
unticked; and a self-declared `| 2026-09-08 | 1 | 5 | 5 | me |` review row.

Why nothing fires:
- `check_headings` (`lintcore.py:132-156`) is set-membership on heading lines only — **no body check for
  `REQUIRED_HEADINGS`** (`ticket.py:17-27`). Body emptiness is checked *only* for `RECOMMENDED_HEADINGS`
  (`lintcore.py:234-261`) and only as a **warning**.
- `_check_ac_present` (`ticketlint.py:41-57`) requires **≥ 1 `- [ ]` row**, nothing more. No Given/When/Then, no
  measurable-value, no id-uniqueness (T15: two ACs both labelled `AC1` → PASS), no minimum count.
- `STORY_RE` (`ticket.py:45`) is `as an?\s+.+?i want\s+.+?so that\s+` — `"As a x, I want y, so that z"` passes
  (T22).
- `check_diagram` (`lintcore.py:159-193`) only needs the type keyword at a line start: a fence containing
  `sequenceDiagram` followed by `zzzz !!! not a diagram at all` passes (T4); an **empty** fence with just the
  keyword passes (T1, G1).
- The `## Definition of Ready` checklist itself is never read — neither its content nor its checkbox state,
  despite the skill's hard rule *"Never tick a Definition of Ready checkbox yourself"*
  (`claude-skill-ba-ticket-author.md:171-174`).

**Consequence:** the *only* thing standing between this and a Dev is the LLM maturity review, which has no code
behind it at all (HIGH-4). Criterion violated: **C10** (and the spec's own §Goals).

### HIGH-2 — `check_headings` is HTML-comment-blind: four required sections can be commented out and the gate says PASS

`lintcore.py:149-151` strips ``` fences but not `<!-- … -->`, while `check_recommended_sections`
(`lintcore.py:253`) and `check_review_record` (`lintcore.py:285`) both **do** strip them via
`HTML_COMMENT_RE`. The templates ship guidance in HTML comments, so this is not a theoretical input shape.

Repro (`…/E/t/variants/G5-four-sections-commented.md` — the golden ticket with `## Summary`,
`## Background / Business context`, `## Use cases` and `## Definition of Ready` each wrapped in `<!-- … -->`):

```
$ kb ticket lint G5-four-sections-commented.md
[warn] Acceptance Criterion has no citation: 'AC3 …'
DoR: PASS
```

Those four sections have **no second-order check** (unlike story/AC/diagrams/kb-context, which caught the
all-in-a-fence case T19 and the all-in-a-comment case G2). So four of the nine required sections can be
invisible in the rendered ticket and the gate still passes. The fence hole was found and fixed with a test
(`tests/test_lintcore.py:54`); the comment hole was never considered — `grep '<!--' tests/test_lintcore.py`
returns only the three recommended-section/review-record tests. Criterion: **C10** (*"required headings present
(fences ignored)"* — the intent is clearly "actually present").

### HIGH-3 — `section_body` is not fence-aware: a `#` line inside a code fence produces a false DoR FAIL

`section_body` (`lintcore.py:98-113`) terminates a section at the first line starting with `"## "` **or `"# "`**,
scanning raw text. A markdown/bash comment inside a fenced block truncates the section.

Repro (`…/E/t/variants/G3-fence-hash-in-ac.md` — golden ticket, one fenced example added at the top of
`## Acceptance Criteria`):

````markdown
## Acceptance Criteria
```bash
# example invocation
importer --file feed.dat
```
- [ ] AC1 — Given a Restrictive Airspace record, …
````

```
$ kb ticket lint G3-fence-hash-in-ac.md
[error] Acceptance Criteria must have at least 1 '- [ ]' item
DoR: FAIL      (exit 1)
```

Same root cause, second symptom (`G4-extra-fence.md`): a `# not a diagram` line in a `text` fence placed above
the mermaid fence in `## Sequence diagram` →
`[error] '## Sequence diagram' must contain a ```mermaid fence with 'sequenceDiagram' at the start of a line`.
Both tickets are perfectly valid markdown. `section_body` feeds **every** body-level check (story, ACs,
diagrams, recommended-section emptiness, open questions, backlog, sequencing, tech decisions), so the blast
radius is the whole gate. Criterion: **C10** (the gate rejects conforming artifacts).

### HIGH-4 — `INLINE_CITE_RE` false-positives on natural prose, at error level

`INLINE_CITE_RE` (`lintcore.py:50-53`) takes the last whitespace-delimited token before `§` as the doc-id, and
`cite_matches_ref` (`lintcore.py:353-358`) compares case-sensitively. Verified end-to-end:

| Prose a BA would actually write | Parsed doc-id | Verdict |
|---|---|---|
| `per ARINC 424 §5.129` | `424` | `[error] citation '424 §5.129' in the body is not in kb-context refs` → **FAIL** |
| `(ARINC-424 §5.129)` | `ARINC-424` | **FAIL** (case mismatch vs `arinc-424`) |
| `ICAO Annex 3 §4.2.1` | `3` | would FAIL |
| `Refer to section §5.129 of arinc-424.` | `section` | would FAIL |
| `arinc-424 § 5.129` (space after §) | *no match* | **silently invisible** — neither a citation nor an error; only the `ref never cited` warning surfaces |

Files: `…/E/t/variants/F1-natural-prose.md`, `F2-case-mismatch.md`, `T9c-space-after-sect.md`.
The error message ("citation '424 §5.129'") gives the BA no clue what to fix. In a regulated-aviation repo where
prose *should* name the standard the way the standard names itself, an error-level gate that rejects
`ARINC 424 §5.129` teaches BAs to stop writing `§` in prose — which defeats the grounding story the gate exists
to enforce. Criterion: **C10**.

### MEDIUM-1 — A second `## KB context` block is never parsed, so anything in it is invisible

`kbcontext._extract_block` (`kbcontext.py:157-175`) returns *"the first kb-context block"*; nothing counts blocks
or flags a duplicate.

Repro (`T14-two-blocks.md` — golden block, then a second `## KB context` with `version: "0000000"`,
`refs: [aero:arinc-424 §9.999]`, `tags: [ghost-tag]`): **`DoR: PASS`**, no warning.
Control (`T20-bogus-block-first.md`, same two blocks in reverse order): 3 errors, FAIL.

So the verdict depends on block order and the second, unvalidated pin sits in the ticket looking authoritative to
a human and to the Dev-side intake. Criterion: **C8/C10**.

### MEDIUM-2 — Documentation contract is wrong about what CI enforces (stale refs; reverse citation)

`templates/init/QUICKSTART-ba.md:111-129`, under the heading **"DoR rules (what CI enforces)"**:

> - Every `## KB context` ref resolves at its pinned hub commit — **no broken, malformed, or stale refs**.
> - Every inline `doc-id §section` citation is backed by a pinned ref **(and vice versa)** — citations and pins must agree.

Both halves in bold are false, and the adjacent *"What lint does **not** enforce"* list does not mention them.
Verified by amending §5.129 in the `aero` copy, re-publishing to the hub, and re-linting the untouched golden
ticket:

```
$ kb ticket lint tickets/M-nav-restrict-US1.md
[warn] aero:arinc-424 §5.129: L2 content has changed since the pinned version (amendment after the BA wrote it)
DoR: PASS      (exit 0)         ← the CI step's exact command; CI is GREEN
$ kb resolve tickets/M-nav-restrict-US1.md --status-only   → status=stale, exit 2
```

And `T17b-zero-citations.md` (intact pin, zero body citations) → `DoR: PASS` with one warning.
Stale-as-warning **is** the spec (`2026-07-17-ba-agent-design.md:89-110`, check 6/8), so the code is right and
the BA-facing contract doc is wrong. But the operational consequence is real: **an amendment to a cited aviation
standard does not turn any BA gate red**, and the ticket template's own DoR line "- [ ] No stale refs" is a
human checkbox with no machine backing. `kb ticket lint` collapses `kb resolve`'s 0/1/2 to 0/1; nothing in the
CI template runs `kb resolve`. Criteria: **C10, C8, C16**.

### MEDIUM-3 — The maturity review has zero code behind it; the `## Review record` is unvalidated

`review.py` is `kb approve` (`summarized→reviewed` in `_manifest.yaml`) — **unrelated to the maturity review**.
`grep -rn maturity src/center_kb/*.py` returns only `lintcore.py:267-303`. Scoring is done entirely by an LLM
following `docs/review-rubric.md`; the only check is `check_review_record`
(`lintcore.py:271-303`) = *present, non-empty, not the literal `Not yet reviewed.`* — **warning-level**.

Not checked: the table's columns, that a row exists at all, the scores, the ≥ 4 threshold, the round count ≤ 3,
that the `Reviewer` cell reads `gap-verifier` for rounds 2–3 (which the skill mandates,
`claude-skill-ba-ticket-author.md:120-124`), or that `Open gaps:` ids have owned Open-questions rows.

Repro (`T18-fake-review.md`): `| 2026-09-08 | 1 | 5 | 5 |  |` (empty reviewer, self-declared 5/5) →
`DoR: PASS`, **no warning at all**. `Not yet reviewed.` → deleted and replaced with any single character also
passes.

Warnings-only is the spec's explicit choice (`2026-08-12-ba-review-agents-design.md:25, 113`). The finding is not
"the spec is unimplemented" but **the composition**: given HIGH-1, the maturity review is the only thing actually
judging quality, and it is a free-text self-report. C10's *"maturity review two axes ≥ 4"* is a prompt, not a
gate. Criterion: **C10** (partially met).

**The C2 process change (round 1 = two reviewers, rounds 2–3 = one gap-verifier) IS present** — in **7 of 8**
wrappers, correctly worded, with correct no-subagent fallbacks (sub-audit, quotes below). Divergences:

| Divergence | Where |
|---|---|
| `claude-command-ba-ticket-author.md:34-35` states only the rounds-2/3 half; **never** mentions the two reviewer roles, the **3-round cap**, `score ≥ 4`, `docs/review-rubric.md`, or `## Review record`. It is a pure delegating pointer, deliberately per `tests/test_templates.py:1341-1346` — but it is the one file where a reader gets no bound on the loop. | ticket, claude-command |
| Two incompatible dialects: **ticket** forks per harness (skill = *"dispatch TWO review subagents IN PARALLEL"*; copilot/cursor = *"run TWO sequential review passes yourself"*, pinned apart by `tests/test_templates.py:244-252`). **Mission** uses one conditional text in all four (*"when your runtime can dispatch subagents … otherwise run TWO sequential passes"*). Both are correct; the fork is a maintenance liability. | ticket vs mission |
| The mission dialect asks the model to self-assess *"when your runtime can dispatch subagents"* — Copilot/Cursor models may answer wrongly. | mission ×4 |

**No variant says "two reviewers every round" or a wrong reviewer count.** The parallel-review fallback is
correctly given in all four subagent-less variants.

**Canon-test coverage is asymmetric and thin** (sub-audit, `tests/test_init.py`, `tests/test_templates.py`):
- Mission: `tests/test_init.py:963 test_mission_wrapper_workflow_bodies_are_byte_identical` — exact slice
  comparison from `## Workflow` to EOF across all four. Strong.
- **Ticket: no parity test of any kind.** `test_copilot_and_cursor_wrappers_differ_only_in_their_frontmatter_name`
  (`tests/test_templates.py:767`) iterates `DEV_WORKFLOW_SKILLS` only. Every BA-review test is a bare substring
  presence check.
- **The 3-round cap is asserted nowhere, for any of the 8 files.** These edits all pass the full suite: cap →
  `5 rounds`; cap deleted; rounds 2–3 → `dispatch TWO gap-verifier subagents` (only the substring
  `"gap-verifier"` is asserted, `:1331`); round 1 → `THREE review subagents` (only the two role *names* are
  asserted, `:1337`); copilot ticket body forking from cursor ticket body.
- `BA_TICKET_AUTHOR_PIPELINE_STEPS` (`tests/test_templates.py:21-23`) is a stale 7-tuple missing
  `"Maturity review"`; the substring `"Review"` matches inside it. No mission pipeline-step test exists.
- `expected_files("ba")` is compared to itself (`tests/test_init.py:680`) with **no numeric count pin** — exactly
  the hole `dev`'s own `== 45` pin (`:1434`) has a comment warning about.

Criterion: **C16** (trip-wires exist but are load-bearing only on the mission side).

### MEDIUM-4 — The AC quality bar is a 23-word deny-list with a one-token universal mute

`acquality.py` is the *entire* implementation of the spec's "verifiable ACs". It checks nothing else — no
Given/When/Then, no numeric-value requirement, no NFR/UI/sequencing content. It is wired into
`kb ticket lint` (`ticketlint.py:71-83`, **warning**) and **not** into `kb mission lint` at all.

1. **Trivially evaded.** 23 fixed phrases (`acquality.py:168-192`). Direct probe of `weasel_hits` — all clean:
   *"The system shall behave correctly"*, *"fast and stable under load"*, *"only the relevant fields"*,
   *"sensible defaults"*, *"handles all edge cases gracefully"*, *"Performance is acceptable"*,
   *"Data is validated properly"*.
2. **`OPEN(...)` anywhere on the line mutes every hit on that line** (`acquality.py:228-229`). Probe:
   `"Values are configured OPEN(x) and appropriate and a subset and responsive."` → `[]` — four banned phrases,
   zero warnings. `OPEN(TBD)` and `OPEN(?)` both count as owned unknowns (`OPEN_RE`, `acquality.py:165`).
3. **The owned-unknown counterpart is count-only.** `_check_owned_unknowns` (`ticketlint.py:95-116`) just needs
   `#rows ≥ #markers` in `## Open questions`, and a row is "owned" if it contains the substring `owner:`
   (`lintcore.py:221-231`). `- [ ] Q1 — what? — owner: TBD` satisfies it (G1).
4. **Scope is AC checkbox rows only** — the NFR table, UI spec and prose are never scanned, so
   `| Speed | fast | eyeball |` is invisible, contradicting the rubric's *"No weasel words anywhere in the body"*
   (`review-rubric.md:47`).
5. **`docs/ac-quality.md` is documentation only.** No code reads it; the list is hardcoded
   (`acquality.py:19` "kept in sync with"). A BA adding a domain-specific banned phrase to the doc changes
   nothing.

Net: an agent optimising for `DoR: PASS` needs one `OPEN(x)` per AC, or a thesaurus. Criterion: **C10**.

### MEDIUM-5 — `kb init` re-run overwrites the review rubric the framework tells the BA to tune

`PROTECTED_FILES` (`initcmd.py:156-158`) = `{.kb/index.yaml, .kb/config.yaml, .claude/settings.json}`. Ran a
re-init on the scratch BA repo after editing two files:

```
$ kb init --kind ba .
  updated  docs/tickets/TEMPLATE.md      ← local edit gone
  updated  docs/review-rubric.md         ← local edit gone
  updated  .kb/config.yaml (kind recorded)   ← hub preserved, only `kind:` appended
  skipped  .claude/settings.json (protected data)
```

`review-rubric.md:7-8` says: *"**Edit this file to tune the criteria for your domain**; the skills read it at
review time."* There is no `.local.md` escape for BA repos, unlike the dev side's
`docs/conventions/<lang>.local.md` (C11), which is never overwritten. Same exposure for `docs/ac-quality.md`.
Criterion: **C16** (inconsistent with the dev-side guarantee).

### MEDIUM-6 — CI gate quality: unpinned install, no concurrency, failures hidden in collapsed groups

(sub-audit, `templates/init/kb-ticket-lint.yml`)
- `:40` `pip install center-kb` — **unpinned**. The gate self-upgrades from PyPI on every PR: a new release can
  turn every open BA PR red with no repo change. `_gate.yml:26-33` argues at length against exactly this for
  ruff (*"A lint gate that upgrades itself is not a gate"*).
- **No `concurrency:` block**, while this repo's own `ci.yml:7-10` has one for the stated reason.
- **Readability is the weakest part.** No `$GITHUB_STEP_SUMMARY`, no use of the CLI's `--json`, no annotations.
  Real failures print `[error] …` **inside a `::group::`**, and Actions renders groups collapsed — reviewer sees
  a red X and must expand to learn why. The one `::error::` (`:98`) sits on an arm the file itself calls
  unreachable.
- `QUICKSTART-ba.md` never documents `vars.CENTER_KB_HUB` / `secrets.KB_HUB_TOKEN`; the gate works in practice
  only via the `.kb/config.yaml` fallback. On a fork PR it fails with a *network*-flavoured message, so an
  external contributor will misdiagnose it.
- `:44` `${CENTER_KB_HUB#https://}` mangles a non-`https://` hub when a token is set.
- The gate is **not installed in this repo's own `.github/workflows/`** — scaffold artifact only.

### MEDIUM-7 — The "500–800 token" search budget is unactionable in all 8 wrappers

(sub-audit) Every variant says *"**Budget the search:** 500–800 tokens for broad discovery"*
(`claude-skill-ba-ticket-author.md:33-36`, mission `:29-32`) but the CLI fallback they hand the agent is
`kb query "<text>" --tags <tags>` with **no `--budget`**, and the MCP call is never shown with a `budget`
argument. Both default to **2000** (`mcp.py:106`, `cli.py:1101`). An agent following the literal command gets
2.5× the stated budget and never knows. `tests/test_templates.py:1250` pins only that the string `"500–800"`
exists. Two clauses later the same step says *"Present **ALL** returned candidates … never silently drop one"* —
the budget line is the weakest instruction in the step. The **C4 budget discipline in the mission Draft step is
otherwise coherent** (L1+L2 mandatory, `## Components (C4 L3)` optional and gated on *"ONLY when the BA supplies
real component detail"*, matching `mission.py:89-93`), though the two unrelated "L3"s in one file (KB level vs C4
level) are a readability hazard.

### LOW findings

| # | Finding | Evidence |
|---|---|---|
| L1 | **Citations inside HTML comments count as body citations, both ways.** `citation_scan_text` (`lintcore.py:346-350`) strips fences and bare kb-context blocks but not `<!-- -->`. `G6`: the reverse-consistency check is satisfied by a citation that exists only in `<!-- grounded in arinc-424 §5.129 -->` → PASS. `G7`: `<!-- TODO check arinc-424 §9.999 later -->` → hard **FAIL**. A BA's own TODO note blocks the gate. | ran both |
| L2 | **A ticket with no `> Parent mission:` line has no traceability check at all** and passes (`T11b`). Documented compatibility choice (`ticket.py:47-50`), but combined with L3 it means mission↔ticket traceability is entirely opt-in. | ran |
| L3 | **Mission coverage counts any file with the right name.** `check_coverage` (`missionlint.py:279-283`) only calls `.is_file()`. A `tickets/M-nav-restrict-US7.md` containing the single word `garbage` flipped `0/2 US drafted` → `1/2`. | ran |
| L4 | **`kb ticket lint` never reports stale as an exit code** (0/1 only) whereas `kb resolve` uses 0/1/2, and the CI template never runs `kb resolve`. See MEDIUM-2. | ran |
| L5 | **Duplicate AC ids pass** (`T15`: two `AC1` rows). No AC id parsing at all. | ran |
| L6 | **`check_placeholders` counts `%%TODO%%` inside HTML comments** (`missionlint.py:183-196`, raw `text.count`) while `ticketlint._unknown_count` strips them (`ticketlint.py:89`). The **shipped `mission-template.md` warns about its own guidance comments**: `kb mission lint docs/missions/TEMPLATE.md` → `[warn] 2 unresolved '%%TODO: verify against codebase%%' placeholder(s) remain`. | ran |
| L7 | **`arinc-424 § 5.129` (space after §) is silently invisible** to the scanner — see HIGH-4 row 5. | ran |
| L8 | The **`N/A — <reason>` escape hatch is missing from all four mission wrappers** (string `N/A` count = 0) although `lintcore.py:249/259` names it in the warning the mission agent will see. Ticket wrappers have it. | sub-audit |
| L9 | **Dead cross-domain rule in all four mission wrappers**: *"never substitutes for a domain citation in an **Acceptance Criterion**"* (`claude-skill-ba-mission-plan.md:173-176`) — missions have no `## Acceptance Criteria` section. Pinned in place by `tests/test_templates.py:1138`. | sub-audit |
| L10 | **`## Review record` is in neither `REQUIRED_HEADINGS` nor `RECOMMENDED_HEADINGS`** — it has a bespoke check. Consistent behaviour, but the heading contract does not know about a section both templates ship. | `ticket.py:17-41`, `lintcore.py:264` |

---

## PASS/FAIL matrix — adversarial tickets

Baseline: golden ticket `…/E/ba/tickets/M-nav-restrict-US1.md` → **PASS**. Hub reachable, `272953a` pinned, refs
valid. ✅ = the gate behaved as a DoR gate should; ❌ = it did not.

| # | Adversarial ticket | Verdict | Level fired | ✅/❌ |
|---|---|---|---|---|
| T1 | All 9 required headings present, every body `TBD`/empty | **PASS** | warnings only | ❌ |
| T2 | ACs as vague prose ("the system shall behave correctly") | **PASS** | citation warn only | ❌ |
| T3 | ACs with no Given/When/Then and no measurable value | **PASS** | **no output at all** | ❌ |
| T4 | Mermaid fence: `sequenceDiagram` + garbage lines | **PASS** | — | ❌ (documented) |
| T5 | Two mermaid fences of the same type (no business-flow one) | **FAIL** | error | ✅ |
| T6 | Inline citation `§5.126`, pinned block has only `§5.129` | **FAIL** | error | ✅ |
| T7 | Pinned ref never cited in the body | **PASS** | warning | ⚠️ spec'd |
| T8 | Citation only inside a ``` fence | **PASS** | warning (`ref never cited`) | ⚠️ correct + weak |
| T9a | `… per arinc-424 §5.129.` (sentence-final period) | **PASS**, matched | — | ✅ |
| T9b | `(arinc-424 §5.129)` in parentheses | **PASS**, matched | — | ✅ |
| T9d | `arinc-424 §5.129, and` (comma) | **PASS**, matched | — | ✅ |
| T9c | `arinc-424 § 5.129` (space after §) | **PASS**, **not matched** | warning only | ❌ |
| T10 | `> Parent mission:` → mission that does not exist (in `tickets/`) | **FAIL** | error | ✅ |
| T10b | same, linted outside a `tickets/` dir (or via MCP) | **PASS** | note | ⚠️ noted |
| T11 | Filename ≠ `<mission-id>-US<n>.md`, mission exists | **FAIL** | error | ✅ |
| T11b | No `> Parent mission:` line at all | **PASS** | — | ⚠️ opt-in |
| T12 | `tags: [ghost-tag]` | **FAIL** | error + suggestion | ✅ |
| T13a | `version: "deadbee"` (random hex) | **FAIL** | error | ✅ |
| T13b | Older but valid hub commit, content unchanged | **PASS** | — | ✅ correct |
| T13c | `version: ""` | **FAIL** | error | ✅ |
| T13d | Commit predating the doc on the hub | **FAIL** | error | ✅ |
| T14 | Two `## KB context` blocks (valid first, bogus second) | **PASS** | — | ❌ |
| T20 | Two blocks, bogus **first** | **FAIL** | 3 errors | ✅ (order-dependent) |
| T15 | Duplicate AC ids (`AC1` twice) | **PASS** | — | ❌ |
| T16 | AC contradicting the cited section (20 chars, numeric-only) | **PASS** | — | ⚠️ by design (LLM's job) |
| T17b | Zero body citations, pinned block intact | **PASS** | warning | ❌ |
| T18 | `## Review record` claiming 5/5 with an empty reviewer cell | **PASS** | **no warning** | ❌ |
| T19 | All required headings only inside a ``` fence | **FAIL** | 9 errors | ✅ |
| T21 | `## Acceptance Criteria` as prose, no `- [ ]` rows | **FAIL** | error | ✅ |
| T22 | `As a x, I want y, so that z` | **PASS** | — | ❌ |
| G1 | **Capstone gamed ticket** (vague ACs + `OPEN(TBD)` mute + unquantified NFR + "Looks nice." + 5/5 self-review) | **PASS** | 3 warnings | ❌ |
| G2 | All required headings only inside `<!-- -->` | **FAIL** | but **zero** "missing heading" errors | ❌ (heading check blind) |
| G5 | Summary + Background + Use cases + DoR wholly inside `<!-- -->` | **PASS** | — | ❌ |
| G6 | Only citation lives inside `<!-- -->` | **PASS** | — | ❌ |
| G7 | Bogus citation inside `<!-- TODO … -->` | **FAIL** | error | ❌ false positive |
| G3 | `# comment` in a fenced block inside `## Acceptance Criteria` | **FAIL** | error | ❌ false positive |
| G4 | Non-mermaid fence with a `# ` line before the mermaid fence | **FAIL** | error | ❌ false positive |
| F1 | `per ARINC 424 §5.129` (natural prose) | **FAIL** | `citation '424 §5.129' …` | ❌ false positive |
| F2 | `(ARINC-424 §5.129)` (case) | **FAIL** | error | ❌ false positive |
| S1 | Upstream amendment to the cited section, then re-lint | **PASS** | warning; CI green | ❌ vs docs |

## PASS/FAIL matrix — adversarial missions

Baseline: golden mission → **PASS** (with the expected `1/2 US drafted` warning).

| # | Adversarial mission | Verdict | ✅/❌ |
|---|---|---|---|
| M0 | Template-compliant | **PASS** | ✅ |
| M1 | Backlog ids `STORY-1/2`, not derived from the mission id | **FAIL** (2 errors) + coverage visibly skipped | ✅ |
| M2 | C4 L1 present, L2 fence replaced by prose | **FAIL** | ✅ |
| M3 | Plain `flowchart LR` under `## Containers (C4 L2)` | **PASS** | ⚠️ keyword-only, documented (`mission.py:95-100`) |
| M4 | Both L1 and L2 plain `flowchart` (no C4 syntax anywhere) | **PASS** | ⚠️ same |
| M5 | `C4Context` diagram under the L2 heading | **FAIL** | ✅ level keywords are level-specific |
| M6 | L1 heading carrying a `C4Container` diagram | **FAIL** | ✅ |
| M7 | No tickets drafted → `0/2 US drafted` | **PASS** + warning | ✅ intended (`missionlint.py:276-278`) |
| M7b | A `tickets/<us-id>.md` containing only `garbage` | counted as drafted (`1/2`) | ❌ existence-only |
| M8 | Structure intact, every body `TBD` | **PASS** | ❌ (mirrors HIGH-1) |
| — | Mission filename ≠ `> Mission:` id | **FAIL** | ✅ |
| — | Ticket names the mission but the backlog lacks that US (ticket side) | **FAIL** (T11) | ✅ |
| — | `--json` envelope | `{pass, errors, warnings, notes}` exactly | ✅ |

---

## Criteria scorecard

| Criterion | Verdict | One line |
|---|---|---|
| **C10 — required headings present (fences ignored)** | **partially met** | Fences handled (T19 ✅); **HTML comments are not** — four required sections can be commented out and the gate passes (G5). |
| **C10 — story / AC / diagram structure** | **partially met** | Structural presence only: `As a x, I want y, so that z` passes, `- [ ]` count ≥ 1 is the whole AC contract, an empty mermaid fence passes. |
| **C10 — Mermaid type keyword at line start** | **met** | Correctly anchored; wrong type → error (T5); init directives allowed. |
| **C10 — every `## KB context` ref resolves at the pinned commit** | **met** | Broken/malformed/missing version/absent doc all error (T13a/c/d). Stale = warning per spec; **the BA-facing doc claims otherwise** (MEDIUM-2). |
| **C10 — inline citation ⇄ pinned ref, both directions** | **partially met** | Forward = error and works (T6); reverse = warning only (T7/T17b); error-level false positives on natural prose (HIGH-4); a second block is never parsed (MEDIUM-1). |
| **C10 — tags in vocabulary (error)** | **met** | Ghost tag → error with suggestion and the right remediation (T12). |
| **C10 — parent-mission back-link check** | **met (CLI, scaffolded layout)** | Ghost mission and non-backlog filename both error; skipped-with-note over MCP/stdin/other dirs; entirely opt-in if the line is omitted. |
| **C10 — `kb mission lint`: structure + C4 L1&L2 + derived backlog ids + citations** | **met, with a soft C4** | All fire correctly; C4 is keyword-detected and `flowchart` is an accepted substitute at every level (documented tradeoff). |
| **C10 — `--json` envelope** | **met** | Exactly `{pass, errors, warnings, notes}`, both commands. |
| **C10 — maturity review, two axes ≥ 4, round 1 two reviewers / rounds 2–3 one verifier** | **partially met** | The C2 wording is correct in 7/8 wrappers with proper no-subagent fallbacks; **no code implements or verifies any of it** — `review.py` is `kb approve`; a fabricated 5/5 with an empty reviewer passes silently. |
| **C10 — agent never pushes to Jira** | **met** | Explicit in all 8 wrappers; no tracker tool anywhere. |
| **C10 overall** | **partially met** | The *grounding* half (pins, refs, tags, traceability) is strong and I could not break it. The *Dev-readiness* half is presence-only: a ticket of pure `TBD` passes (HIGH-1). |
| **C8 (BA part) — pin one hub commit; refs validated; tags auto-derived & validated; resolve at pinned version + freshness; exit 0/1/2** | **met** | Verified live: auto-derived tags, ghost tag rejected, stale detected after a real upstream amendment, `kb resolve` exits 0/1/2. Caveat: `kb ticket lint` collapses stale to exit 0. |
| **C16 (BA part) — everything YAML/MD in git; `kb init` re-run refreshes scaffold but preserves config; trip-wire tests** | **partially met** | `.kb/config.yaml` and `.claude/settings.json` preserved ✅; **`docs/review-rubric.md` (which invites tuning) and `docs/ac-quality.md` are silently overwritten** with no `.local` escape ❌; trip-wires are strong for mission wrappers (byte-identity) and absent for ticket wrappers, with no BA scaffold-count pin. |

---

## Top 3 recommendations

**1. Make the required sections carry weight — turn presence into substance.**
Cheapest high-value change: extend the existing `check_recommended_sections` emptiness logic
(`lintcore.py:234-261`) to `REQUIRED_HEADINGS` at **error** level, add a placeholder deny-list
(`TBD`, `…`, `<…>`, `N/A` where N/A is not allowed), require ≥ 2 ACs, and require each AC to contain either a
Given/When/Then triple **or** a digit/comparison/identifier (a "measurable token") **or** `OPEN(<owner>)` — with
everything but the emptiness check landing as warnings first, then errors one minor release later. Also make
`## Non-functional requirements` rows require a digit or `OPEN(` in the *Target* column, matching the skill's
own hard rule (`claude-skill-ba-ticket-author.md:189-191`) which lint currently ignores. This is the single
change that moves C10 from "structure gate" to "DoR gate".

**2. Fix the four text-scanning bugs; they are small and each is either a silent pass or a false red.**
(a) strip `HTML_COMMENT_RE` in `check_headings` (`lintcore.py:149`) and in `citation_scan_text`
(`lintcore.py:350`) — the helper already exists and two sibling checks already use it (HIGH-2, L1);
(b) make `section_body` fence-aware — blank out ``` fences before scanning for the terminating `# `/`## ` line,
or track fence state (HIGH-3, two false FAILs on valid markdown);
(c) anchor `INLINE_CITE_RE` so the doc-id must contain a `-` or match a known doc-id from the parsed
`kb-context.refs`/hub index, compare doc-ids case-insensitively, and tolerate `§ <space>` — then downgrade an
*unrecognised* doc-id to a warning and keep error-level only for a recognised doc-id with an unpinned section
(HIGH-4, L7);
(d) error on a **second** `kb-context:` block in `kbcontext.parse` (MEDIUM-1) — six lines.
Add the corresponding negative tests; the current suite has none of these shapes.

**3. Close the honesty gap on the review and on staleness.**
(a) Correct `QUICKSTART-ba.md:111-129` — move "stale refs" and the "(and vice versa)" clause out of *"what CI
enforces"* into *"what lint does not enforce"*, and give the CI template an opt-in `kb resolve --status-only`
step (or a `--fail-on-stale` flag on `kb ticket lint`) so a repo that wants amendment safety can have it
(MEDIUM-2, L4).
(b) Give `## Review record` a real format check — table header, at least one data row, all five cells non-empty,
both scores parseable integers 1–5, round numbers 1…3 monotonic, `Reviewer` = `gap-verifier` for rounds ≥ 2 —
still warning-level as the spec requires, but *specific* enough that a fabricated row is visible (MEDIUM-3).
(c) Add the ticket-wrapper parity test the mission side already has
(`tests/test_init.py:963`), assert the 3-round cap and `≥ 4` threshold strings across all 8 wrappers, pin
`len(expected_files("ba"))`, fix the stale `BA_TICKET_AUTHOR_PIPELINE_STEPS` 7-tuple, and add
`docs/review-rubric.md` + `docs/ac-quality.md` to `PROTECTED_FILES` or give them `.local.md` siblings
(MEDIUM-3, MEDIUM-5, C16).
