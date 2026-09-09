---
name: dev-plan
description: Turn an approved technical design into an implementation plan — one task per AC, each with a failing test first and checkboxes for resumable progress. Use as phase 2 of implementing a ticket, or when invoked as /dev-plan.
---

# dev-plan — turn an approved design into a resumable, test-first plan

You are phase 2 of the ticket-implementation pipeline, invoked after the
Dev has approved the design at GATE 1. Your job: turn that design into
`docs/impl/<ticket-id>-plan.md`, a resumable checkbox file that phase 3
(`dev-execute`) reads and ticks task by task.

*Counterpart in the superpowers plugin: `superpowers:writing-plans`.*

## Freshness re-check (run this FIRST, every time)

Cheap check first: when `docs/impl/<ticket-id>-context.md` exists and its
`version:` matches the ticket's block, run `kb resolve --status-only
<ticket-file>` (no CLI → `kb_resolve`, full output). All **ok** → use the
cache; do NOT re-pull pinned content. No cache, version mismatch, or a
non-ok verdict → full `kb resolve <ticket-file>` (else `kb_resolve`), then
rewrite the cache, keeping its `## Placeholder map`.

- **broken** → STOP. Blocker: the BA must re-pin. Never implement around a
  citation that no longer resolves.
- **stale** → show BOTH versions, humans decide: the resolve gives the
  pinned content and the reason, `kb get <doc-id> <section> [--level l3]`
  the current hub version. Do NOT use `kb diff` — it compares the local
  `.kb/` worktree to a local git rev, not this repo to the hub.
- **ok** → continue.

## Steps

- **Read the design** — on the architectural path, read
  `docs/impl/<ticket-id>-design.md`; on the spike or bounded path there is
  no design file, so work from the design as the Dev approved it in chat.
- **Write the plan** — write `docs/impl/<ticket-id>-plan.md` with one
  task per AC, or several tasks for a large AC, and every task names the
  test that proves it. Per task, give exactly three headings: **Files**
  (create / modify / test, by path); **Interfaces** (what this task
  consumes from earlier tasks and what it produces for later ones —
  exact names and types, because a task's implementer sees only their
  own task); and **Steps** as `- [ ]` checkboxes, step 1 always being
  the failing test.
- **A task with no test declares its exemption.** Every task's first
  step is a failing test, with exactly four exceptions — config, CI,
  docs and style changes, defined in `docs/tdd-exemptions.md`. A task
  in one of those classes carries one line instead, and no other shape
  is accepted: `Exempt: <config|ci|docs|style> — verified by <what>`.
  The slug comes from that document; a change that fits none of the
  four is not exempt, and a change that alters behaviour an AC can see
  is never exempt whatever its file extension.
- **Order and close** — order tasks so each one leaves the repo green, and
  end the plan with one closing task for cross-cutting verification (full
  suite + lint) that names the commands it will run — `cmd.test` and
  `cmd.lint` from `-code §cmd.*`.
- **No `-code` document yet** — when `-code §cmd.*` has not been generated
  in this repo (`kb code-ingest` not yet run), ask the Dev once for the
  build/test/lint commands and record them at the top of the plan file, so
  this closing task, `dev-execute`, and `dev-handover` all have something
  to run.
- **No linter in the repo** — when there is no linter at all to record as
  `cmd.lint`, make setting one up the plan's first task, from the
  *Linting* section of `docs/conventions/<lang>.md` (plus
  `docs/conventions/<lang>.local.md` overrides), and record the command
  it establishes as `cmd.lint`. Its red step is running that command and
  watching it fail because no linter is configured. Scope the initial
  config so `cmd.lint` passes on the untouched tree — every later task's
  verify step runs it — and record tightening it to full strength as a
  finding for the PR body.
- **GATE 2** — the Dev approves the plan before any code is written; once
  approved, option 1 in the Next-step block below is
  `/dev-execute <ticket-id>`. The checkbox file is also the resume point,
  so it must be complete enough for a different session to pick up cold.

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
