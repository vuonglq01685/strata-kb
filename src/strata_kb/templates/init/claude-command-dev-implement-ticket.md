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

Steps the skill enforces: **Intake** reads the ticket's `## Dependencies`
(`Blocked by:` / `Blocks:`) and, when a `> Parent mission:` line is
present, that mission's `## Sequencing` row, and stops if there is no
`kb-context` block to resolve; **Resolve** triages exactly as in the
Freshness re-check above; the full resolve is `kb resolve --write-cache
docs/impl/<ticket-id>-context.md <ticket-file>`, which writes the header
and the resolved sections — you never edit above the
`<!-- kb:placeholder-map -->` marker; **Ground**
reads resolved L2, calling `kb_get_section` only for a section already
chosen and escalating to L3 only for a value that will be encoded in code
or tests, then searches within a 500–800 token budget for broad discovery
— `<repo_id>-code` and `<repo_id>-svc` for structure and responsibility
before reading the actual code, skipping whichever document is missing and
reading the code directly for that half — a document missing from the hub
means either not yet generated (`kb code-ingest` for `<repo_id>-code`,
`dev-code-seed` for `<repo_id>-svc`) or generated and not yet published,
checked via `.kb/<repo_id>-code/` and `.kb/<repo_id>-svc/` locally
(present → say "generated, unpublished: run `kb publish`"; absent → "not
generated"), reads staying hub-only either way and never reported as a KB
gap; **Placeholders** verifies every
`%%TODO: verify against codebase%%` against the codebase, reports the list
to the BA, **never edits the ticket**, and records the map in the cache
file's `## Placeholder map` table below the marker
(`| placeholder | verified value | evidence (file:line or ref) |`); and
anything unverifiable becomes `OPEN(BA)`; **Run the phases** invokes the
`dev-design`, `dev-plan`, `dev-execute`, then `dev-handover` skills in
order, deriving re-entry state — never stored — from
`docs/impl/<ticket-id>-design.md` and `-plan.md` by their own `status:`
header: `status: draft` offers the matching gate, `status: approved` moves
on; design approved with no plan file but `git log --oneline
<default>..HEAD` non-empty is `plan ⚠ missing, N commits on branch` — ask
before running `dev-plan`, work may already be committed; an approved plan
turns tasks into ticked/total checkboxes; `gh pr list --head <branch>
--state merged` non-empty ends the flow, `--state closed` non-empty offers
re-handover or reopen, and `gh` absent leaves the PR state unknown (gh not
installed); no branch matching the ticket id while on the default branch
offers `git switch -c <ticket-id>`; a current branch naming a different
ticket STOPs — two tickets in flight, switch branches first.

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
