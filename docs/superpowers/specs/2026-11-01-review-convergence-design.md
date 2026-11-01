# A1/A2 review convergence and readable hub Q&A (short design)

Date: 2026-11-01 · Size: small change (skill text, one hub template, one
render helper, tests)

Two independent parts in one release: Part 1 (sections Intent to 4) is the
review loop; Part 2 (section 5) is how Q&A reads on the hub.

## Intent

The design review (A1, `dev-design`) and the plan review (A2, `dev-plan`)
do not converge. Each fresh verification reviewer finds new gaps, so a
ticket runs far past the target of "one review round plus one verification
round" and either ends `AUTO-RESULT: failed design-review` / `plan-review`
or is pushed through by a Dev "beyond cap".

Evidence: the `## Review record` tables of the 27 tickets in
`myflix/docs/impl` (54 design + plan files). All end `approved`, but
`content-ingest-US4` took 11 design and 11 plan rounds,
`content-management-US11` 10 plan rounds, `content-ingest-US2` 8 plan rounds.
Round 1 finds the real risk (B4-13, S7-21). From round 3 on each round
holds 1-2 new SUGGESTED gaps of four kinds:

1. round-1 coverage miss (about 50 rows say so);
2. defects the fix itself made: "regression of the fix", stale wording,
   stale line refs after a re-draft;
3. a ticket revision (BA answers) restarting the cycle;
4. defects only running the step reveals: "verification fails as written"
   (args not reaching Playwright, psql quoting, heredoc env), "expected red
   mis-stated", "line-number pin". TDD and CI catch these at execute anyway.

Kinds 2 and 4 make most of the tail. The review is chasing a perfect paper
document, not the risk.

## Goals

1. A1 and A2 end after at most two rounds: round 1 (exhaustive, unchanged)
   and one verification round. No "beyond cap" path.
2. A verification round blocks only on what round 1 raised, on regressions
   inside the fix diff, and on any BLOCKER.
3. Gaps that execute will catch are handed to `dev-execute` as named checks,
   not fixed on paper.
4. When execute or TDD makes the code differ from the plan or design, the
   plan/design text is updated back, in the same task, without reopening
   A1/A2.
5. Every Q&A question, context and answer on the hub is readable and
   verifiable by a person: rendered, one decision per question, and no
   reference a reader cannot look up.

## Non-goals / anti-goals

- No change to round 1: exhaustive matrix, slices, lead reviewer, class-wide
  fix and sweep stay as written.
- No change to A3/A4/A5 code reviews or their caps.
- No change to how a ticket revision re-draft starts a new cycle (kind 3).
  It now gets the same two-round budget.
- Anti-goal: a BLOCKER passing a gate. Anti-goal: a back-update that
  triggers a full A1/A2 again (the "amendment during execution" rounds in
  myflix US3, US6, platform-operations-US1 are the tail this removes).
- Part 1 needs no Python change. `lintcore.REVIEW_ROUND_CAP` is the BA
  ticket's review record, not the design/plan one; leave it.
- Part 2: no refusal of unformatted Q&A now. `kb_question_ask` and
  `kb_question_answer` accept any text as today, so questions already open
  on the hub stay answerable. No rewrite of stored questions.

## Approaches

- **A. Freeze the gap list after round 1, hard cap 2 rounds, carry
  execute-verifiable gaps (picked).** Cuts kinds 2 and 4, keeps round 1
  where the real defects are found. Trade: some paper-only SUGGESTED gaps
  (stale wording) slip; A3 and later reviews still see the code.
- B. Only BLOCKER blocks a gate. Simplest, but round-1 SUGGESTED gaps are
  mostly real (preconditions, concurrency guards); dropping them lowers
  quality where review works.
- C. Replace A2 with a lint (`kb plan waves`, structure checks), keep A1
  only. Cheapest, but A2 round 1 finds real BLOCKERs (B6-13: missing
  interfaces, unspecified migrations) that are dearer to fix in code.

The Dev picked A.

## Decided

### 1. Verification round (A1 and A2, `bodies/dev-design.md`, `bodies/dev-plan.md`)

Round 2 gets the same inputs as today (round-1 inputs, gap list with
classes, sweep list, `review/a<k>-r<n>.diff`). It checks:

- every round-1 gap is closed;
- the diff has no regression;
- spot-checks of each class outside the sweep list.

A new gap outside the diff is recorded as `round-1 coverage miss` and
**does not block**, unless it is a BLOCKER. Remove "it still reports any
other defect it sees" as a blocking source: it still reports them, as
carried gaps (section 3).

### 2. Stop rule and gate

- Cap: round 1 + one verification round. Remove the "cap of 3 rounds", the
  trend rule (moot at two rounds) and any "Dev-approved beyond cap" path.
- NOTE and NITS stay recorded, not fixed, as today.
- **Gate (GATE 1 / GATE 2) is offered when no BLOCKER is open and every open
  SUGGESTED gap is in the carried-gaps table with a target task.**
- A BLOCKER open after round 2 stops the flow and goes to the Dev. Auto mode:
  `AUTO-RESULT: failed design-review` / `plan-review`, open classes in the
  reply. Auto mode's "at most 2 fix rounds (not 3)" becomes the same
  two-round rule; the Auto override lines for the stop rule and the
  "round 3" contract are rewritten to match.
- The shared **Review dispatch contract** bullet "at most 3 rounds" stays for
  A3/A4/A5 and gets an exception line for A1/A2 pointing at this rule.

### 3. Carried gaps

- Rubric (`pr-review-rubric.md`, Pre-code axes): add a short list of
  **execute-verifiable** defect classes: a verification command that fails
  as written, an expected red mis-stated, a line-number pin, an e2e timeout
  or margin unmeasured, a fixture assumption a run checks. Reviewers tag a
  gap of these classes `execute-verifiable`; any reviewer round may raise it,
  it never blocks a gate, and it is never fixed on paper.
- Both `design.md` and `plan.md` get a `## Carried gaps` table below
  `## Review record`:

      | Gap | Class | Severity | Raised in | Target task | Status |
      |---|---|---|---|---|---|

  Rows: execute-verifiable gaps (any round), and SUGGESTED gaps raised in
  round 2 outside the diff.
- The plan author reads the design's carried gaps and names a target task
  for each (copying the row into the plan's table). An open plan row names
  its task directly.
- `dev-execute` (`bodies/dev-execute.md`): the implementer of a task gets
  the carried rows that name it with its task block. A3 checks each row is
  resolved by the code or test, and the orchestrator sets `Status: closed
  task <n>` when it ticks the task. An open row at handover is listed in
  the PR's `## Notes`.

### 4. Back-update during execute (`bodies/dev-execute.md`)

- When the code of a task differs from its plan task or a design section,
  the implementer edits that plan/design text in the **same task commit**
  and adds a row to `## Execution deviations` in `plan.md`:

      | Task | Doc + section | What changed | Why |
      |---|---|---|---|

- A3 adds one check to the spec-compliance verdict: the plan/design text
  matches the code of this task, and every difference has a deviation row.
  A miss is a SUGGESTED A3 finding, fixed in A3's own fix rounds.
- Only a deviation that **changes the meaning of an AC or a public
  contract/interface** triggers one **delta review**: a fresh
  `design-reviewer` (design text) or `plan-reviewer` (plan text) on the doc
  diff of that commit only, one round, no loop. BLOCKER → Dev (Auto: end
  `AUTO-RESULT: failed design-review` / `plan-review`). SUGGESTED → carried
  gap. A changed AC meaning still goes to the BA as today ("AC not
  implementable as written" route); the delta review does not replace that.
- Lane implementers never edit `plan.md` today. In a lane the implementer
  writes its deviation rows and doc edits into its task report; the
  orchestrator applies them to `plan.md` / `design.md` at merge-back, before
  A3. Design-only edits in a lane follow the same route.

### 5. Readable hub Q&A (Part 2)

Evidence: hub Q37 (myflix, `content-ingest-US2`, screenshot from the Dev).
Markdown shows raw (`` `S3_ENDPOINT` `` with its backticks), the whole
question is one paragraph, one question bundles two decisions (accept a test
approach; open a new story), its context is only internal codes
(`design A1 r1 R1-13 — SA-1, DD12, §9.3 T4`), and the answer mixes the
decision, ticket changes, follow-ups and auto assumptions in one paragraph.

**5a. Render.** `templates/web/questions_ticket.html` shows `question`,
`context` and `answer` as plain text under `white-space:pre-wrap`. Render the
three through `web/gfmrender.py` instead, with line breaks kept: today
`gfmrender.render` turns a single newline into a space (checked:
`"line one\nline two"` renders as one line) and only a literal `<br>` into a
break. Old Q&A is plain text whose layout lives in single newlines, so the
Q&A path needs markdown-it's `breaks` behaviour. Raw HTML stays off, as
for mission and ticket pages. The `kb_question_list` text output
(`ticketqa.format_questions`) is unchanged.

**5b. Format for new questions** (skills that call `kb_question_ask`:
`dev-design`, `dev-plan`, `dev-implement-ticket`, `dev-fix-bug`; the
`dev-execute` and `dev-sa` routes that reach it inherit it). `question`:

    **Decision needed:** <one sentence>

    **Background:**
    - <2-4 bullets in plain words>

    **Options:**
    1. <option> — <consequence>
    2. <option> — <consequence>

    **Dev recommends:** <option>, because <reason>
    **AC impact:** <which ACs change, which do not>

Rules: one decision per question (two decisions → two questions); no
internal id (DD12, SA-1, R1-13, G-3) unless the same text says what it is;
`context` names a place a reader can open, e.g. `design.md §9.3 — test T4`,
not a review-round code. Labels are fixed English (they match the hub UI
and a later check can parse them); the content is in the ticket's language.

**5c. Format for answers** (`ba-answer-questions`). `answer`:

    **Decision:** <what the BA chose>
    **Ticket changes (rev N):**
    - <section>: <what changed>

    **Follow-ups:** <new question or story, and its owner>
    **Assumptions:** <only if any>

The BA's own words go in **Decision**; the skill structures, it does not
reword.

**5d. Questions already open.** When `ba-answer-questions` shows the BA an
open question not in the 5b format, it restates it in that format in chat
only, so the BA can read it. The stored question is never edited. The
answer is written in the 5c format.

**Later (not this change).** `kb_question_ask` warns on a question missing
the 5b labels; it refuses only once the hub has no open question in the old
format.

## Builder's calls (marked as mine)

- Table names `## Carried gaps` and `## Execution deviations`, and their
  columns.
- The execute-verifiable class list above (taken from the myflix records);
  the builder may merge near-duplicates.
- Lane deviations applied by the orchestrator at merge-back.
- Delta review uses the existing `design-reviewer` / `plan-reviewer` roles,
  no new role.
- Q&A labels in English, content in the ticket's language.
- Restating old questions in chat (5d) instead of migrating stored text.

## Left to the builder

- Exact wording in both bodies and their mirrored
  `claude-command-dev-design.md` / `claude-command-dev-plan.md` copies;
  the `dev-execute` command copy too.
- `tests/test_templates.py` pins A1/A2 section text (the section snapshot
  near line 2317 and the phrase checks near line 3684): update them to the
  new wording; leave `tests/fixtures/bodies-pre-auto/` untouched unless a
  test compares against it for this change.
- Guide text in `docs/src` that describes the 3-round cap, if any, and the
  guide PDFs rebuilt the way the repo already does.
- How 5a keeps line breaks: a second `MarkdownIt` with `breaks` on, or an
  option on `render`; mission/ticket page rendering must not change. A test
  renders an old-style plain-text question (single newlines, backticks) and
  a 5b-format question.
- Whether the `/ui/questions` list page needs the same render (it shows no
  question text today).
- CHANGELOG entry and version bump at the next release.
