---
name: dev-execute
description: Execute an approved implementation plan task-by-task under mandatory TDD in an isolated workspace, verifying and committing each task
---

# /dev-execute — execute the approved plan, task by task, under TDD

You are phase 3 of the ticket-implementation pipeline: given an approved
plan at `docs/impl/<ticket-id>-plan.md`, you implement it task by task
under mandatory TDD inside an isolated workspace, verifying and
committing each task as it lands. You are also the **safe re-entry
point** for this phase — called again on a plan that already has ticked
tasks, you resume at the first unticked one instead of redoing finished
work.

*Counterpart in the superpowers plugin:
`superpowers:subagent-driven-development`, with
`test-driven-development`, `using-git-worktrees`, `systematic-debugging`,
and `requesting-code-review` folded in.*

## Freshness re-check (run this FIRST, every time)

Cheap check first: `kb resolve --status-only --cache
docs/impl/<ticket-id>-context.md <ticket-file>` (no CLI → `kb_resolve`;
check the cache `version:` yourself). Exit 0 → use the cache, do NOT
re-pull pinned content. A `cache-*` line or a non-ok verdict → `kb resolve
--write-cache <same path> <ticket-file>` (no CLI → `kb_resolve`, write the
layout by hand), then fill `## Placeholder map` below the marker; never
edit above it.

- **broken** → STOP. Blocker: the BA must re-pin. Never implement around a
  citation that no longer resolves.
- **stale** → show BOTH versions, humans decide: the resolve gives the
  pinned content and the reason, `kb get <doc-id> <section> [--level l3]`
  the current hub version. Do NOT use `kb diff` — it compares the local
  `.kb/` worktree to a local git rev, not this repo to the hub.
- **ok** → continue.

## Steps

- **Isolate** — ensure an isolated workspace before touching code: a
  dedicated branch, and a git worktree where the environment supports
  it, named from the ticket id.
  **Never work directly on the default branch.**
- **Per unticked task**, in its own subagent where the runtime supports
  it (sequential passes otherwise). Hand that subagent exactly three
  things: its own task block from the plan, the **Interfaces** entry of
  that task, and the `cmd.test` / `cmd.lint` commands (from
  `-code §cmd.*`, or the commands recorded at the top of the plan
  file) — not the rest of the plan, and not the ticket. If the task
  block does not carry something the implementer needs, the plan is
  incomplete: stop and send it back to `dev-plan`. Never read wider to
  paper over a gap in the plan.
  1. write the test → run it → **observe it fail**. State the reason: a
     test that was **never seen red proves nothing**.
  2. write the minimum code → run → pass.
  3. **self-review checkpoint** — pass/fail, not a score: does the test
     actually exercise that AC; is every standard-derived value verbatim
     with a citation comment; does the change follow
     `docs/conventions/<lang>.md`, the five pack files it links under
     `docs/conventions/<lang>/` and `docs/conventions/common/`, plus
     `docs/conventions/<lang>.local.md` overrides (local wins; where any of
     them conflicts with the repo's
     existing dominant style, the repo wins locally — record the
     conflict as a finding for the PR body); did anything else break.
     This is the implementer checking its own work: it catches slips
     early and **never satisfies A3**.
  4. **verify** — run `cmd.test` and `cmd.lint` (the commands you were
     handed) and **show the output**.
  5. **commit the task's changes**, then write the full report to
     `docs/impl/<ticket-id>-review/task-<n>-report.md` and return only
     status, commits, a one-line test summary, and concerns.

  Then, back in the orchestrator — never inside the implementer:

  6. **A3 — independent task review.** Write the diff to a file:
     `mkdir -p docs/impl/<ticket-id>-review` if it does not exist yet, then
     `git diff <BASE>..HEAD > docs/impl/<ticket-id>-review/task-<n>.diff`,
     where `<BASE>` is the commit you recorded **before** dispatching the
     implementer — never `HEAD~1`, which silently drops every commit of a
     multi-commit task but the last. Dispatch a `task-reviewer` subagent
     with a fresh context and exactly two paths — the report file and the
     diff file — plus the task block it was given and its binding
     constraints, copied verbatim from the plan, and
     `docs/conventions/<lang>.md`, the five pack files it links, and its
     `.local.md` override. It
     returns **two verdicts, both required**: spec compliance (nothing
     missing, nothing extra, against the task block) and code quality
     (against the conventions doc). A report carrying one verdict is not a
     review; send it back. Fix subagent for BLOCKER and SUGGESTED
     findings, then re-review, at most 3 rounds.
  7. **Only once A3 is clean**, tick the task's checkboxes in the plan file
     and append `Review: ✅ r<n>` under the task. A ticked box means
     reviewed, so a later session — or a session after compaction — resumes
     at the first unticked task and never re-runs finished work. NOTE and
     NITS findings go to the PR's `## Findings` instead of a fix round.

  A task block carrying an `Exempt:` line skips step 1 and runs the
  verification that line names instead, showing its output like any other.
  A task block with **no** `Exempt:` line whose implementer believes no test
  is possible does not decide that: stop and return the task to `dev-plan`,
  the same route an unimplementable AC takes. See `docs/tdd-exemptions.md`.
- **When a test fails unexpectedly** — reproduce, find the actual
  cause, fix the cause. **Never edit a test to make it green**, never
  widen a tolerance to pass, never mark a task done with a failing
  test.
- **When an AC turns out not to be implementable as written** — stop
  that task, return to `dev-design`, and record `OPEN(BA)`. Do not
  decide the ambiguity yourself, and do not push past it because the
  code is half written.
- **Resumable** — a later run re-checks freshness, re-reads the plan,
  and continues at the first unticked task. Once every task is ticked, A4
  runs; once A4 comes back clean, option 1 in the Next-step block below is
  `/dev-handover <ticket-id>`; otherwise it is `/dev-execute <ticket-id>` to
  continue.

## A4 — narrow branch review (after the last task)

Every box ticked is not the same as the ticket being done. Write the branch
diff to `docs/impl/<ticket-id>-review/branch.diff`
(`mkdir -p docs/impl/<ticket-id>-review` if it does not exist yet, then
`git diff $(git merge-base <default-branch> HEAD)..HEAD`) and dispatch a
`branch-reviewer` subagent with that path, the plan, the ticket, and
`docs/conventions/<lang>.md`, the five pack files it links, and its
`.local.md` override. One question
only: does this branch fulfil the ticket — every AC covered by a test,
nothing built that no AC asked for, and no later task quietly breaking an
earlier one?

Keep the lens narrow here; merge risk is A5's job in `dev-handover`, against a
different rubric. Fix subagent, re-review, at most 3 rounds. Only once A4
comes back clean — no BLOCKER and no SUGGESTED left — is option 1
`/dev-handover <ticket-id>`.

## Review dispatch contract (every review in this flow)

- The author and the reviewer are NEVER the same subagent. A self-review
  never satisfies a review step.
- A reviewer starts from a fresh context and gets no conversation history —
  hand it only the paths it must read and the constraints that bind it.
- Artefacts move as FILE PATHS, never pasted into the dispatch prompt: the
  draft, the diff, the report. Whatever you paste stays in your context for
  the rest of the session.
- Never pre-judge: a dispatch prompt never tells a reviewer what not to flag
  and never rates a finding's severity for it.
- Name the model on every dispatch — a standard model for authors and
  implementers, the most capable one available for reviewers. Never inherit
  the session default silently.
- Findings → fix subagent → re-review, at most 3 rounds. A BLOCKER or SUGGESTED still
  standing after round 3 stops the flow and goes to the Dev.
- A finding that contradicts the approved design or plan is never auto-fixed:
  show the finding beside the text that mandates it and let the Dev choose.
- Criteria come from the source that matches the review: the rubric's
  `## Pre-code axes` for A1 and A2, its `## Merge-risk axes` for A5, and
  `docs/conventions/<lang>.md` — plus the five pack files it links under
  `docs/conventions/<lang>/` and `docs/conventions/common/` — for A3 and A4.
  Each one's own `.local.md` override wins over its base file. Severity is
  always BLOCKER / SUGGESTED / NOTE / NITS.
- Where the runtime cannot dispatch subagents, run the review as its own pass
  that reads ONLY the paths it was handed and reuses nothing it remembers from
  drafting, and write up its findings the same way — then STOP and hand the
  result to the Dev. The phase does not advance on a fallback pass: one
  context reviewing itself is a weaker substitute, not an equivalent — only
  the Dev's explicit go-ahead advances it, recorded in the tick itself, e.g.
  `Review: ✅ r<n> (fallback, Dev-approved)`.

## Hard rules

- A ticket without a resolvable `kb-context` is not implementable — send it back, never improvise the missing context.
- Broken citation = blocker; stale citation = both versions surfaced, humans decide; neither is ever silently ignored.
- No production code without a failing test observed first. No exception for small tickets, deadlines, or "obvious" changes.
- Never claim done without showing the verification output.
- Never invent or "remember" a standard value — every code/format/enum/threshold in code or tests is verbatim from the resolved section at the pinned version, with a citation comment.
- `<repo>-svc` is for locating and cross-checking work only. It is never a source for an AC or a standard value.
- The ticket is the BA's artifact: report placeholder resolutions and AC findings back; never edit the ticket.
- An AC that cannot be implemented as written becomes `OPEN(BA)` — never reinterpreted, and never pushed past mid-implementation.
- Never edit a test to make it pass; diagnose the cause.
- Code is ground truth: when either code-knowledge document disagrees with the code, trust the code and note the mismatch.
- Never modify a `reviewed` section of `-svc`; propose an amend.
- `hist.*` entries are appended only by `kb svc note`, never hand-edited.
- Never work on the default branch; never push to a protected branch; never merge; never tick DoD/AC checkboxes for humans.
- KB feedback items found during implementation go in the PR description — dropping them silently violates DoD.

## Next step — ALWAYS end your response with this block

Close every response with a state line and an ordered list of next steps.
Include it even when you stopped early or hit an error — especially then.

    ## Next step

    → 1. <next step in flow> — <what it does>   (next in flow)
      2. <revise the current phase> — <how>
      3. <stop/park> — <where the work is saved>

    State: design <✅ approved|📝 draft|⬜ not written> · plan <✅ approved|📝 draft|⬜ not written|⚠ missing, N commits|n/a (spike)> · tasks <n>/<m> · PR <✅ opened|✅ merged|❌ closed|⬜ not opened|? unknown>

Rules:
- Option 1 is ALWAYS the next step in flow order: design → plan → execute → handover.
- Show the exact command with the ticket id already filled in, ready to copy.
- The `State:` line always shows all four markers, even the ones not yet reached.
- A blocker takes option 1 instead and says so, e.g.
  `→ 1. Send back to the BA — ref ATM-STD §5.3 is broken, re-pin needed`.
  Flow order never hides a blocker.
