---
description: Turn an approved technical design into an implementation plan — one task per AC, each with a failing test first and checkboxes for resumable progress
argument-hint: "[ticket id]"
---

Invoke the `dev-plan` skill with the Skill tool and follow its workflow
exactly. Pass "$ARGUMENTS" as the ticket id when given; when empty, ask
for it before continuing.

This is phase 2 of the ticket-implementation pipeline, invoked after the
Dev has approved the design at GATE 1.

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

Steps the skill enforces: read the design —
`docs/impl/<ticket-id>-design.md` on the architectural path, the
approved in-chat design otherwise — then write
`docs/impl/<ticket-id>-plan.md` with one task per AC, or several tasks
for a large AC; every task names the test that proves it and carries
three headings — **Files** (create/modify/test), **Interfaces** (what it
consumes from earlier tasks and produces for later ones, exact names and
types, since a task's implementer sees only their own task), and
**Steps** as `- [ ]` checkboxes, step 1 always being the failing test.
A task with no test declares its exemption instead, with exactly four
exception classes — config, CI, docs and style changes, defined in
`docs/tdd-exemptions.md` — carrying one line, and no other shape
accepted: `Exempt: <config|ci|docs|style> — verified by <what>`; the
slug comes from that document, a change fitting none of the four is
not exempt, and a change that alters behaviour an AC can see is never
exempt whatever its file extension. Tasks are ordered so each one
leaves the repo green, and the plan closes
with one cross-cutting verification task (full suite + lint) that names
the commands it will run — `cmd.test` and `cmd.lint` from
`-code §cmd.*`; when that document has not been
generated yet in this repo (`kb code-ingest` not yet run), the skill
asks the Dev once for the build/test/lint commands and records them at
the top of the plan file so this closing task, `dev-execute`, and
`dev-handover` all have something to run; and when the repo has no
linter at all to record as `cmd.lint`, the plan's first task sets one
up from the *Linting* section of `docs/conventions/<lang>.md` (plus
`docs/conventions/<lang>.local.md` overrides) and records the command
it establishes as `cmd.lint` — its red step is running that command
and watching it fail because no linter is configured, and the initial
config is scoped so `cmd.lint` passes on the untouched tree, with
tightening it to full strength recorded as a finding for the PR body.
Ends at **GATE 2**: the Dev approves the plan before any code is
written, and once approved, option 1 in the Next-step block below is
`/dev-execute <ticket-id>`; because the checkbox file is also the
resume point, it must be complete enough for a different session to
pick up cold.

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
