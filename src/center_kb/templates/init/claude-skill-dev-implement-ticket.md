---
name: dev-implement-ticket
description: Implement a BA ticket grounded in the KB — resolve its pinned kb-context, verify %%TODO%% placeholders against the codebase, then design → plan → execute → handover under mandatory TDD. Use when a Dev asks to implement / work on / pick up a ticket, or invokes /dev-implement-ticket.
---

# dev-implement-ticket — implement a BA ticket, grounded and re-entrant

You are the ORCHESTRATOR of the ticket-implementation pipeline: Intake →
Resolve → Ground → Placeholders → design → plan → execute → handover. You
are also the **safe re-entry point** for this pipeline — called again on a
ticket that already has work in progress, you detect how far it got and
offer the next step instead of redoing phases that are already finished.

*Counterpart in the superpowers plugin: none — this orchestrator is
center-kb specific; the phases it runs map to brainstorming, writing-plans,
and subagent-driven-development.*

## Freshness re-check (run this FIRST, every time)

Re-resolve the ticket's `kb-context` first: `kb_resolve`, else
`kb resolve <ticket-file>`. The hub may have published since last session.

- **broken** → STOP. Blocker: the BA must re-pin. Never implement around a
  citation that no longer resolves.
- **stale** → show BOTH versions, humans decide: `kb resolve` gives the pinned
  content and the reason, `kb get <doc-id> <section> [--level l3]` the current
  hub version. Do NOT use `kb diff` — it compares the local `.kb/` worktree to
  a local git rev, not this repo to the hub.
- **ok** → continue.

## Steps

- **Intake** — accept a pasted ticket body or a path; confirm ticket/US id
  and branch; read the ticket's `## Dependencies` (`Blocked by:` /
  `Blocks:`) and, when a `> Parent mission:` line is present, that
  mission's `## Sequencing` row; if this story is blocked by something
  unmerged, say so and let the Dev decide. No `kb-context` block → stop,
  the ticket is not Ready.
- **Resolve** — triage exactly as in the Freshness re-check above:
  `broken` → stop and report to the BA; `stale` → show both versions and
  let the Dev decide; `ok` → continue.
- **Ground** — read resolved L2; escalate to L3 via `kb_get_section … l3`
  (or `kb get <doc> <section> --level l3`) only for a value that will be
  encoded in code or tests, and call `kb_get_section` only for a section
  already chosen; then `kb_search` both own-repo documents, budgeted at
  500–800 tokens for broad discovery —
  `<repo_id>-code` for structure and `<repo_id>-svc` for responsibility —
  and then read the actual code. State the rule: *knowledge orients, code
  decides* — skip whichever document is missing and read the code
  directly for that half instead: `<repo_id>-code` is missing whenever
  `kb code-ingest` has not run yet in this repo; `<repo_id>-svc` is
  missing whenever this repo has not run `dev-code-seed` (or the seed is
  not yet published). Say so in one line rather than reporting it as a
  KB gap.
- **Placeholders** — for each `%%TODO: verify against codebase%%`, verify
  the real name against the codebase and record `placeholder → verified
  value (file:line or code-knowledge ref)`; report the list to the BA;
  **never edit the ticket**; unverifiable here → `OPEN(BA)`.
- **Run the phases** — invoke the `dev-design` skill, then — after the Dev
  approves it — the `dev-plan` skill, then the `dev-execute` skill, then
  the `dev-handover` skill. On re-entry, detect state from
  `docs/impl/<ticket-id>-design.md`, `docs/impl/<ticket-id>-plan.md`, the
  ticked-checkbox ratio in the plan, the current branch, and whether a PR
  exists — then skip finished phases and offer the next one.

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
