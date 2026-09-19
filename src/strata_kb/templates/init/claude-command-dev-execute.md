---
description: Execute an approved implementation plan task-by-task under mandatory TDD in an isolated workspace, verifying and committing each task
argument-hint: "[ticket id]"
---

Invoke the `dev-execute` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the ticket id when given; when
empty, ask for it before continuing.

This command is also the safe re-entry point for phase 3 — called again
on a plan with tasks already ticked, it picks up where the last run
left off instead of redoing finished work.

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

Steps the skill enforces: **Isolate** the work onto a dedicated branch
and, where the environment supports it, a git worktree named from the
ticket id. Never work directly on the default branch. Then, per
unticked task, in its own subagent where the runtime supports it
(sequential passes otherwise), handed exactly its own task block from
the plan, that task's **Interfaces** entry, and the `cmd.test` /
`cmd.lint` commands (from `-code §cmd.*`, or the commands recorded at
the top of the plan file) — not the rest of the plan and not the
ticket; when the task block does not carry something the implementer
needs, the plan is incomplete, so stop and send it back to `dev-plan`
rather than reading wider: write the test, run it, and observe it
fail — a test that was never seen red proves nothing; write the
minimum code and get it passing; hold a **review checkpoint**
(pass/fail, not a score) confirming the test actually exercises that
AC, every standard-derived value is verbatim with a citation comment,
the change follows `docs/conventions/<lang>.md` plus
`docs/conventions/<lang>.local.md` overrides (local wins; where either
conflicts with the repo's existing dominant style, the repo wins
locally — the conflict is recorded as a finding for the PR body), and
nothing else broke; then **verify** by running `cmd.test` and `cmd.lint` (the
commands it was handed) and show the output; then commit the task's
changes — ticking its checkboxes in the plan file happens next, back
in the orchestrator, since the plan file itself is never handed to
the subagent. A task block carrying an `Exempt:` line skips step 1
and runs the verification that line names instead, showing its
output like any other; a task block with no `Exempt:` line whose
implementer believes no test is possible does not decide that alone
— stop and return the task to `dev-plan`, the same route an
unimplementable AC takes (see `docs/tdd-exemptions.md`). When a test
fails unexpectedly, reproduce it, find the actual cause, and fix the
cause. Never edit a test to make it green,
never widen a tolerance to pass, and never mark a task done with a
failing test. When an AC turns out not to be implementable as
written, stop that task, return to `dev-design`, and record
`OPEN(BA)` — never decide the ambiguity yourself, and never push past
it because the code is half written. The skill is resumable: a later
run re-checks freshness, re-reads the plan, and continues at the
first unticked task. Once every task is ticked, option 1 in the
Next-step block below is `/dev-handover <ticket-id>`; otherwise it is
`/dev-execute <ticket-id>` to continue.

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
