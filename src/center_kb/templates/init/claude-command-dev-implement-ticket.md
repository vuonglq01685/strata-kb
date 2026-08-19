---
description: Implement a BA ticket grounded in the KB — resolve pinned citations, verify %%TODO%% placeholders, then design → plan → execute → handover under TDD
argument-hint: "[ticket id, path, or pasted ticket]"
---

Invoke the `dev-implement-ticket` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the ticket when given; when empty,
ask for it during Intake.

Pipeline: Intake → Resolve → Ground → Placeholders → design → plan → execute
→ handover. This command is also the safe re-entry point: called again on a
ticket already in progress it reports state and offers the next step rather
than redoing finished phases.

*Counterpart in the superpowers plugin: none — this orchestrator is
center-kb specific; the phases it runs map to brainstorming, writing-plans,
and subagent-driven-development.*

## Freshness re-check (run this FIRST, every time)

Before anything else, re-resolve the ticket's `kb-context`: call the MCP tool
`kb_resolve` when available, otherwise `kb resolve <ticket-file>` (or
`kb resolve - < ticket.md`). The hub may have published since the last session,
so a ref that was `ok` yesterday can be `stale` today — checking only at
handover is too late, because the plan may already rest on changed content.

- **broken** → STOP. This is a blocker: report to the BA that the ticket needs
  re-pinning. Never implement around a citation that no longer resolves.
- **stale** → show BOTH versions and let the humans decide: `kb resolve` returns
  the pinned content plus the reason; `kb get <doc-id> <section> [--level l3]`
  returns the CURRENT hub version. Do NOT use `kb diff` — it compares the local
  `.kb/` worktree against a local git rev, and this repo holds no local copy of
  the cited domain document.
- **ok** → continue.

Steps the skill enforces: **Intake** reads the ticket's `## Dependencies`
(`Blocked by:` / `Blocks:`) and, when a `> Parent mission:` line is
present, that mission's `## Sequencing` row, and stops if there is no
`kb-context` block to resolve; **Resolve** triages exactly as in the
Freshness re-check above; **Ground** reads resolved L2, escalating to L3
for any value that will be encoded in code or tests, then reads the actual
code before trusting anything; **Placeholders** verifies every
`%%TODO: verify against codebase%%` against the codebase, reports the list
to the BA, **never edit the ticket**, and anything unverifiable becomes
`OPEN(BA)`; **Run the phases** invokes the `dev-design`, `dev-plan`,
`dev-execute`, then `dev-handover` skills in order, detecting re-entry
state from `docs/impl/<ticket-id>-{design,plan}.md`, the plan's
ticked-checkbox ratio, the current branch, and whether a PR exists, so
finished phases are skipped.

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

    State: design <✅ approved|⬜ not written> · plan <✅ approved|⬜ not written> · tasks <n>/<m> · PR <✅ opened|⬜ not opened>

Rules:
- Option 1 is ALWAYS the next step in flow order: design → plan → execute → handover.
- Show the exact command with the ticket id already filled in, ready to copy.
- The `State:` line always shows all four markers, even the ones not yet reached.
- A blocker takes option 1 instead and says so, e.g.
  `→ 1. Send back to the BA — ref ATM-STD §5.3 is broken, re-pin needed`.
  Flow order never hides a blocker.
