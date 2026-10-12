---
name: dev-implement-ticket
description: Implement a BA ticket grounded in the KB — resolve its pinned kb-context, verify %%TODO%% placeholders against the codebase, then design → plan → execute → handover under mandatory TDD. Use when a Dev asks to implement / work on / pick up a ticket, or invokes /dev-implement-ticket.
---

# dev-implement-ticket — implement a BA ticket, grounded and re-entrant

You are the ORCHESTRATOR of the ticket-implementation pipeline: Intake →
Check → Resolve → Ground → Placeholders → design → plan → execute → handover. You
are also the **safe re-entry point** for this pipeline — called again on a
ticket that already has work in progress, you detect how far it got and
offer the next step instead of redoing phases that are already finished.

*Counterpart in the superpowers plugin: none — this orchestrator is
strata-kb specific; the phases it runs map to brainstorming, writing-plans,
and subagent-driven-development.*

## Freshness re-check (run this FIRST, every time)

Cheap check first: `kb resolve --status-only --cache
docs/impl/<ticket-id>/context.md <ticket-file>` (no CLI → `kb_resolve`;
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

- **Intake** — run `kb impl tidy` first (it moves an old flat
  `docs/impl/<id>-*` layout into `docs/impl/<id>/` — commit the renames on
  their own before the first task; no CLI → move them by hand); get the ticket: given only an id, run
  `kb ticket fetch <id>` first — the hub is the source of truth; it writes
  `docs/impl/<id>/ticket.md`, your `<ticket-file>` (no CLI → MCP
  `kb_get_section` `<doc> §<id>` at `l3`, saved to that path with headings
  promoted one level and the provenance line `> Fetched from hub:
  <repo>:<doc> §<id> @ <rev> — do not edit; amend in the BA repo.`); a
  path or a pasted body is the fallback when the hub has no copy or is
  unreachable. A fetched ticket has no `## Definition of Ready`: being on
  the hub means DoR passed, so do not stop on its absence. Confirm
  ticket/US id and branch; read the ticket's `## Dependencies` (`Blocked
  by:` / `Blocks:`) and, when a `> Parent mission:` line is present, that
  mission's `## Sequencing` row (from the local mission file, else `kb get
  <doc> <M-id> --level l3` from the hub); if this story is blocked by something
  unmerged, say so and let the Dev decide. No `kb-context` block → stop,
  the ticket is not Ready.
- **Check the grounding** — if the ticket has a `## Technical grounding`
  section, run `kb ticket check docs/impl/<id>/ticket.md` (your
  `<ticket-file>`). PASS → show every `[warn]` (a diff, or facts that could
  not be verified), the Dev decides, continue. FAIL with `re-run
  /sa-ticket-ground` → STOP, blocker for the BA (the SA re-grounds on the
  current `-code`) — unless the run also printed the local-fallback note
  (`checked against the local -code, not the hub's copy`): your branch's own
  changes may cause it, so re-run once the hub is reachable and holds the
  -code. FAIL without that line
  → report the errors to the BA and STOP. No `## Technical grounding` →
  skip, with a note. No CLI → skip, with a note.
- **Resolve** — triage exactly as in the Freshness re-check above:
  `broken` → stop and report to the BA; `stale` → show both versions and
  let the Dev decide; `ok` → continue. A full resolve is
  `kb resolve --write-cache docs/impl/<ticket-id>/context.md <ticket-file>`:
  the command writes the header and the resolved sections; you never
  edit above the `<!-- kb:placeholder-map -->` marker.
- **Ground** — read resolved L2; escalate to L3 via `kb_get_section … l3`
  (or `kb get <doc> <section> --level l3`) only for a value that will be
  encoded in code or tests, and call `kb_get_section` only for a section
  already chosen; then `kb_search` (`kinds=["dev"]`; CLI: `kb query --kind dev`) both
  own-repo documents, budgeted at 500–800 tokens for broad discovery —
  `<repo_id>-code` for structure and `<repo_id>-svc` for responsibility,
  each restricted with `--tags <repo_id>-code` / `--tags <repo_id>-svc` —
  and then read the actual code. State the rule: *knowledge orients, code
  decides* — skip whichever document is missing and read the code
  directly for that half. A `<repo_id>-code` missing from the hub is not
  yet published — CI publishes it on merge to the default branch; `kb
  doctor` says whether the hub lags. A `<repo_id>-svc` missing from the
  hub is either not yet seeded (`dev-code-seed`) or seeded and not yet
  published — check `.kb/<repo_id>-svc/` locally: present → say "seeded,
  unpublished: run `kb publish --pr`" in one line; absent → "not seeded".
  Reads stay hub-only either way; never report it as a KB gap.
- **Ticket and mission lookup** — one separate query,
  `kb query "<ticket or mission topic>" --kind ba` (MCP:
  `kinds=["ba"]`), for the ticket and its parent mission as published by
  the BA. Cite what you use.
- **Knowledge lookup** — one separate query,
  `kb query "<domain term>" --kind kb` (MCP: `kinds=["kb"]`), for the
  domain knowledge the ticket cites. Never mix it into the `--kind dev`
  query.
- **Placeholders** — for each `%%TODO: verify against codebase%%`, verify
  the real name against the codebase and record `placeholder → verified
  value (file:line or code-knowledge ref)`; report the list to the BA;
  **never edit the ticket**; unverifiable here → `OPEN(BA)`. Record the
  map in the cache file's `## Placeholder map` table below the marker
  (`| placeholder | verified value | evidence (file:line or ref) |`).
- **Run the phases** — invoke the `dev-design` skill, then — after the Dev
  approves it — the `dev-plan` skill, then the `dev-execute` skill, then
  the `dev-handover` skill.
  On re-entry, derive the state — never store it — and name the case:
  - `docs/impl/<ticket-id>/design.md` with `status: draft` and no clean
    round recorded in its `## Review record` table → run `dev-design`'s
    A1 review first; a clean round recorded → `design 📝 draft`, offer
    GATE 1. `status: approved` → `design ✅`.
  - design approved, plan absent, and `git log --oneline <default>..HEAD`
    non-empty → `plan ⚠ missing, N commits on branch`: ask before running
    `dev-plan` — work may already be committed.
  - plan with `status: draft` and no clean round recorded in its
    `## Review record` table → run `dev-plan`'s A2 review first; a clean
    round recorded → `plan 📝 draft`, offer GATE 2. approved → tasks =
    ticked/total checkboxes.
  - `gh pr list --head <branch> --state merged` non-empty → `PR ✅ merged`,
    flow done; `--state closed` non-empty → `PR ❌ closed`, next step is
    re-handover or reopen — never end the flow silently; `gh` absent →
    `PR ? unknown (gh not installed)`.
  - no branch matches `git branch --list "*<ticket-id>*"` and HEAD is the
    default branch → offer `git switch -c <ticket-id>`.
  - the current branch names a *different* `ABC-12` ticket id → STOP:
    "two tickets in flight; switch branches first".
  Then skip finished phases and offer the next one.

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
