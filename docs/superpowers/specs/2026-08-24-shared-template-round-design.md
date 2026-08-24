# Shared template round — A4 + B4 + C2 + C3 + C4 + C5

**Status:** approved design, ready for an implementation plan
**Roadmap item:** batch 3 ("ĐỢT TEMPLATE CHUNG") of
`docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md`, plus C5 pulled
forward into the same round by decision on 2026-08-24.
**Supersedes nothing.** Edits skill text only; no CLI, no MCP, no schema change.

## Goal

Pay the cost of a template edit **once**. Every skill-text change costs the same
four wrappers (`claude-skill`, `claude-command`, `copilot`, `cursor`) plus a
canon update in `tests/test_templates.py`, so six deferred text items ship as one
PR, one canon bump, one review.

The six items and what each buys:

| Item | Buys |
|---|---|
| A4 | Skill text stops contradicting the engine: tags are derived, not authored. |
| B4 | Every PR carries its own token cost; the BA sees the ticket's cost at handover. |
| C2 | Review rounds 2–3 read a gap list instead of the whole draft. |
| C3 | A task's implementer sees only its own task. |
| C4 | Search budget becomes a number instead of the phrase "the token budget". |
| C5 | The freshness block repeated in 20 dev wrappers gets 36% shorter, losing no rule. |

## Scope

**In:** `src/center_kb/templates/init/` — 8 BA wrappers and 20 dev-workflow
wrappers — and the assertions in `tests/test_templates.py` that pin them.

**Out, and deliberately so:**

- **D4** (pointing the `dev-execute` review checkpoint at a conventions file).
  The conventions content it would point at does not exist yet; D1–D3 are batch
  5. The roadmap already makes D4 conditional on that content being ready.
- **`ba-mission-plan` reporting usage.** The roadmap names only
  `ba-ticket-author` for B4. A mission plan is not cheaper than a ticket, so this
  is a real gap — recorded here as a follow-up rather than widened silently.
- **`dev-code-seed`** (4 wrappers). It carries no SHARED-* block; its canon is a
  separate whole-`## Steps` comparison (`test_templates.py:988`). C5 does not
  reach it.
- **SHARED-NEXT-STEP**, and — after the measurement in evidence 8 —
  **SHARED-HARD-RULES**. C5 as written in the roadmap names both the freshness
  block and the hard rules; only the freshness half survives contact with the
  numbers. Both of these blocks are left byte-identical.
- Everything else in roadmap sections C, D, E.

## Evidence this design rests on

Read from the tree at `e60aa97`, 2026-08-24. Each fact below decided something.

**1. A4 is still real, and the Pin command survives in 7 files, not 8.**
`kb context new --refs "<refs>" --tags "<tags>"` plus "(+ tags)" survives in
`claude-skill-ba-ticket-author.md:73`, `claude-skill-ba-mission-plan.md:86`,
`claude-command-ba-mission-plan.md:80`, `copilot-ba-mission-plan.prompt.md:83`,
`cursor-ba-mission-plan.md:83`, and — with "(+ tags)" already dropped but
`--tags` still in the command — `copilot-ba-ticket-author.prompt.md:66` and
`cursor-ba-ticket-author.md:66`. `claude-command-ba-ticket-author.md:20` is the
compressed variant and mentions no tags at all; it gets the new rule as a clause
so all 8 wrappers can be asserted uniformly.
`QUICKSTART-ba.md:182` was already corrected by batch 1 and is not touched.

**2. The MCP tool still accepts tags, so the rule has to be textual.**
`mcp.py:160`: `def kb_context_new(refs: list[str], tags: list[str] | None = None)`.
Batch 1 deliberately kept the signature and docstring byte-identical to protect
the golden `mcp_tools.json`. Nothing stops an agent from passing a tag — only the
skill text and the engine's vocabulary validation do.

**3. B4 needs no new CLI.** `kb usage report --ticket <id> --md` exists
(`cli.py:1041`–`1044`). One caveat the skill text must handle: on an empty
ledger the command prints a prose line beginning `no usage recorded yet`
(`cli.py:1075`), not Markdown. A wrapper that pastes output blindly would put
that sentence under a `## Usage` heading.

**4. C2 cannot break lint.** `lintcore.check_review_record` (`lintcore.py:271`)
only warns when `## Review record` is missing, empty, or still holds
`Not yet reviewed.`. It never parses the table, so what rounds 2–3 write in the
score columns is a question of honesty, not of passing lint.

**5. C4 replaces a phrase that carries no number.** "within the token budget"
appears at `claude-skill-ba-ticket-author.md:31`,
`claude-skill-ba-mission-plan.md:27`, `claude-command-ba-mission-plan.md:21`,
`copilot-ba-mission-plan.prompt.md:24`, `cursor-ba-mission-plan.md:24`.
`dev-implement-ticket` already states the L3 half of the rule
(`claude-skill-dev-implement-ticket.md:46`: escalate to L3 "for any value that
will be encoded in code or tests") but gives no search budget.

**6. C5's blast radius is fixed at 20 files by a test that counts them.**
`test_dev_wrappers_carry_byte_identical_shared_blocks` asserts
`len(names) == 20` and compares every copy against `SHARED_BLOCK_TEXT`
(`test_templates.py:307`), a dict holding the block text verbatim. The comment at
line 303 says the canon was extracted with `repr()` from a landed wrapper and
must never be hand-retyped; this round keeps that rule.

**7. Needle tests are bound to hard-rule wording in places.** `kb svc note`
(`test_templates.py:1055`) is asserted against `_dev_wrapper_body`, i.e. with the
shared blocks stripped — so it survives a hard-rules rewrite. The comment at
line 1044 records that this needle *used* to pass through the SHARED-HARD-RULES
bullet, which is exactly the failure mode a rewrite can re-introduce elsewhere.
Every needle that still matches raw wrapper text gets re-checked in this round.

**8. Grouping the hard rules saves almost nothing, so C5 keeps them.** Measured
on 2026-08-24 against the canon: `SHARED-FRESHNESS` is 952 characters and a
lossless rewrite brings it to 598 (**−37%**) — 605 as shipped, once the final
review restored the "Do NOT use" imperative (**−36%**). `SHARED-HARD-RULES` is
1531 characters; regrouping its 14 bullets into 8 while keeping every constraint gives
1449 (**−5%**), and the most aggressive rewording that still carries all 14 gives
1291 (**−16%**). Bullet count is not what costs tokens — the words are, and the
words are the guardrails. Even the aggressive pair would save ~594 characters
(~150 tokens) per wrapper load, roughly 750 tokens per orchestrator session,
against a measured baseline of $28.88 over 239 API calls. The roadmap's "14 dòng
còn ~8 dòng" counted lines, not tokens. C5 therefore ships the freshness trim
only; the hard rules stay verbatim, which also removes the review burden of
tracing 14 constraints into 8 bullets.

## Design

### A4 — tags are derived, never authored

Two edits per BA wrapper, both in prose the wrapper already has:

- **Ground / Intake.** Tags the BA offers stay what they are: search keywords for
  `kb query "<text>" --tags <tags>`. That command is unchanged — it filters a
  search, it does not write a block.
- **Pin.** Drop `--tags "<tags>"` from the CLI fallback, leaving
  `kb context new --refs "<refs>"`. Drop "(+ tags)". Add one sentence, adapted to
  each wrapper's voice: the block's tags are derived by the engine from the
  pinned sections' own tags; a tag passed explicitly is validated against the hub
  vocabulary and an unknown one is an error; never invent one. The same sentence
  covers the MCP path, where `tags` is an optional argument that must be left
  unset.

`claude-command-ba-ticket-author.md` has no Pin command to strip; it receives the
sentence as a clause on its existing "pin only BA-confirmed refs via
`kb_context_new`" line.

### B4 — every handover carries its cost

**`dev-handover`** — one bullet added to the "Assemble the PR description" step:
run `kb usage report --ticket <id> --md` and paste the table under a `## Usage`
heading in the PR body. If the command answers with the "no usage recorded yet"
line instead of a table, keep the heading and write one line saying the ledger is
empty for this ticket and why (hook not wired, or no transcript ingested) — an
empty measurement is a finding, not a reason to delete the section.

**`ba-ticket-author`** — the handover summary (already required to report both
maturity scores and the remaining owned gaps) also reports the ticket's usage
from the same command. The BA repo's ledger covers the authoring side only; the
wrapper says so in the same breath, so nobody reads it as the ticket's full
lifetime cost.

### C2 — rounds 2–3 verify gaps, they do not re-read the draft

Round 1 is unchanged: two reviewers in parallel, each reading the full draft and
`docs/review-rubric.md`, each scoring one axis.

Rounds 2 and 3 dispatch **one** subagent in a role named `gap-verifier`. Its
input is exactly three things:

1. the gap list still open after the previous round, each gap naming its section
   and the fix that was proposed;
2. the current text of **only** the sections that changed in response;
3. the rubric checklist items those gaps map to.

Not the full draft. Its output is pass/fail per gap with a one-line reason — it
does not score an axis, because it has not read enough of the ticket to score
one.

Scoring stays honest by carrying forward: an axis's score rises only when every
gap belonging to that axis passes; otherwise the previous round's score is
repeated unchanged in the new row. The `Reviewer` column reads `gap-verifier`.
The stop condition is unchanged — both axes ≥ 4, or 3 rounds total — and a gap
the agent cannot close itself is still `OPEN(<owner>)` plus an
`## Open questions` row, never invented.

The identical change lands in `ba-mission-plan`, whose maturity-review step
(`claude-skill-ba-mission-plan.md:94`) is the same two-reviewer, three-round
shape.

### C3 — a task's implementer sees only its own task

The "Per unticked task" bullet in `dev-execute` gains an explicit context
statement: the subagent receives its own task block from the plan, the plan's
`Interfaces` section, and the `cmd.test` / `cmd.lint` commands — not the whole
plan, not the whole ticket. The plan format was designed for this — the
per-task **Interfaces** field (`claude-skill-dev-plan.md:40`) exists precisely so
an implementer needs nothing outside its own task — but `dev-execute` never names
it today; only the instruction was missing.

The failure mode gets a rule of its own: if the task block does not contain
something the implementer needs, the **plan** is incomplete — stop and report it
back to `dev-plan`. Reading more of the repo to fill the hole silently is what
this change exists to prevent.

### C4 — the budget is a number

Three sentences replace the phrase "within the token budget" at the Ground step
of `ba-ticket-author`, `ba-mission-plan`, and `dev-implement-ticket`:

- broad discovery calls `kb_search` with a budget of **500–800 tokens** — enough
  for the citation plus a summary to choose from;
- `kb_get_section` is called **only** for a section already chosen;
- **L3 only** for a value that will be encoded in code or in a test.

`dev-implement-ticket` already carries the third sentence; it gains the first two
and keeps its existing wording for L3.

### C5 — a shorter freshness block, and the hard rules left alone

**The hard rules are not touched.** Evidence 8 measured the regrouping the
roadmap asked for: 14 bullets into 8 saves 5% of the block, and even the most
aggressive rewording that preserves all 14 constraints saves 16%. That is not
worth a diff in which a rewritten rule and a deleted rule look identical. The
block stays byte-identical, and roadmap C5 is recorded as delivered in part, with
this measurement as the reason.

**Freshness: cut the explanation, keep the trap.** 952 characters → 605 as
shipped (598 from the rewrite, plus the 7 the final review spent restoring the
"Do NOT use" imperative). The
three verdicts stay
(`broken` → stop and report; `stale` → show both versions, `kb resolve` for the
pinned content and `kb get <doc-id> <section> [--level l3]` for the current hub
version, humans decide; `ok` → continue), and so does the warning not to reach
for `kb diff`, which compares the local `.kb/` worktree against a local git rev
and answers the wrong question here. What goes is the long paragraph explaining
why checking only at handover would be too late; one clause — the hub may have
published since the last session — carries that.

**Mechanics.** A throwaway script rewrites the block in all 20 files in one pass,
so byte-identity is produced rather than hand-maintained; the script lives in the
scratchpad and is not committed. The canon entry is then regenerated with
`repr()` from one rewritten wrapper — never retyped — as `test_templates.py:303`
requires. `SHARED_BLOCKS`' first and last line keys for the freshness block are
unchanged, because the rewrite keeps both boundary lines.

## Testing

TDD applies: the new needles are written and seen red before the wrappers are
edited.

**New assertions in `tests/test_templates.py`:**

- every BA wrapper: the string `--tags "<tags>"` is absent, and the derived-tags
  sentence is present (matched on normalised text, so re-wrapping is free);
- every BA wrapper: `gap-verifier` present;
- the 12 Ground wrappers (8 BA + 4 `dev-implement-ticket`): `500` and `800`
  present, and the phrase "within the token budget" absent;
- the 4 `dev-handover` wrappers: `kb usage report` present, matched against
  `_dev_wrapper_body`;
- the 4 `dev-execute` wrappers: the own-task-block needle, matched against
  `_dev_wrapper_body` — a raw-text match would be satisfiable by a shared block
  and would assert nothing, the exact trap recorded at `test_templates.py:1044`.

**Trip-wires expected to go red, then be updated deliberately:**

- `test_dev_wrappers_carry_byte_identical_shared_blocks`, until
  `SHARED_BLOCK_TEXT['SHARED-FRESHNESS']` is regenerated. The hard-rules and
  next-step entries stay untouched, so a diff against either of them in this
  round is a mistake, not a bump.

`tests/test_init.py`'s pinned scaffold-file count is **not** affected: this round
adds no file.

**Running:** targeted per task —
`pytest tests/test_templates.py tests/test_init.py tests/test_ticketlint.py` —
and the full suite exactly once before handover, because it takes 10–19 minutes.

## Risks

**The four dialects.** `claude-command` wrappers are compressed procedure prose;
`copilot` and `cursor` carry their own frontmatter and their own wrapping. Except
for the SHARED-* blocks, which must stay byte-identical, no sentence may be
pasted across wrappers unedited. This is the likeliest way for the round to go
wrong, and the reason the six items ship together: the dialect tax is paid once.

**C5 is now worth little, and that is the honest reading.** The freshness trim
saves ~354 characters (~90 tokens) per wrapper load. Loaded roughly five times
per orchestrator session, that is a few hundred tokens against a baseline of
$28.88 over 239 API calls — real, cheap, and nowhere near the roadmap's
expectation for section C. It rides along because the round is already opening
these 20 files and bumping the canon; it would not justify a round of its own.
The item that the batch-2 numbers still point at is **C1** (`kb resolve`
returning full pinned content four to five times per ticket), which stays in
batch 4.

**No dev-side data exists yet.** The batch-2 baseline covers `KS-BA` only
(6 transcripts, 239 API calls, $28.88, dominated by `ba-ticket-author`); no Dev
repo has produced a ledger row. Everything this round does to dev wrappers —
C3, C4's dev half, C5 — rests on static reading, not measurement. The trade is
accepted knowingly: none of the three removes a rule, so a wrong guess costs
effort, not a guardrail.
