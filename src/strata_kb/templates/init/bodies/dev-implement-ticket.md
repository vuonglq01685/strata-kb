
# /dev-implement-ticket — implement a BA ticket, grounded and re-entrant

You are the ORCHESTRATOR of the ticket-implementation pipeline: Intake →
Check → Resolve → Ground → Placeholders → design → plan → execute → handover. You
are also the **safe re-entry point** for this pipeline — called again on a
ticket that already has work in progress, you detect how far it got and
offer the next step instead of redoing phases that are already finished.

*Counterpart in the superpowers plugin: none — this orchestrator is
strata-kb specific; the phases it runs map to brainstorming, writing-plans,
and subagent-driven-development.*

**Hub access — MCP first.** Reach the hub through the `strata-kb` MCP
tools (`kb_search`, `kb_get_section`, `kb_resolve`, `kb_context_new`,
`kb_ticket_lint`, `kb_ticket_fetch`,
`kb_ticket_check`) whenever your client exposes them; fall back to the
matching CLI command only when it does not, or the MCP server cannot be
reached. `kb ticket fetch` runs as `kb_ticket_fetch`: save the text it returns
as `docs/impl/<ticket-id>/ticket.md`, the file the CLI would write. `kb ticket check` runs as `kb_ticket_check` (the ticket's text), the CLI as
the fallback. `kb impl tidy`, `kb svc note` and the cache-writing `kb resolve --status-only --cache` /
`--write-cache` stay CLI-first; where a step below names an MCP path for
one, it is only the no-CLI fallback.

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
  pinned content and the reason, `kb_get_section` (else `kb get …
  --level l3`) the hub's version. Do NOT use `kb diff` — it compares
  the local `.kb/` worktree to a local git rev, not this repo to the hub.
- **ok** → continue.

## Steps

- **Intake** — run `kb impl tidy` first (it moves an old flat
  `docs/impl/<id>-*` layout into `docs/impl/<id>/` — commit the renames on
  their own before the first task; no CLI → move them by hand); get the ticket: given only an id, fetch
  it first — the hub is the source of truth: MCP `kb_ticket_fetch` `<id>`,
  its text saved as `docs/impl/<id>/ticket.md`, your `<ticket-file>` (CLI
  fallback: `kb ticket fetch <id>` writes that file); a
  path or a pasted body is the fallback when the hub has no copy or is
  unreachable. A fetched ticket has no `## Definition of Ready`: being on
  the hub means DoR passed, so do not stop on its absence. Confirm
  ticket/US id and branch; read the ticket's `## Dependencies` (`Blocked
  by:` / `Blocks:`) and, when a `> Parent mission:` line is present, that
  mission's `## Sequencing` row (from the local mission file, else `kb_get_section` `<doc> <M-id>` at `l3`, CLI fallback `kb get
  <doc> <M-id> --level l3`, from the hub); if this story is blocked by something
  unmerged, say so and let the Dev decide. No `kb-context` block → stop,
  the ticket is not Ready.
- **Check the grounding** — if the ticket has a `## Technical grounding`
  section, run MCP `kb_ticket_check` with your `<ticket-file>`'s text (CLI
  fallback: `kb ticket check docs/impl/<id>/ticket.md`, which reads the
  local `-code` only when the hub holds none). PASS → show every `[warn]` (a diff, or facts that could
  not be verified), the Dev decides, continue. FAIL with `re-run
  /sa-ticket-ground` → STOP, blocker for the BA (the SA re-grounds on the
  current `-code`) — unless the run also printed the local-fallback note
  (`checked against the local -code, not the hub's copy`): your branch's own
  changes may cause it, so re-run once the hub is reachable and holds the
  -code. FAIL without that line
  → report the errors to the BA and STOP. No `## Technical grounding` →
  skip, with a note. Neither MCP nor CLI → skip, with a note.
- **Resolve** — triage exactly as in the Freshness re-check above:
  `broken` → stop and report to the BA; `stale` → show both versions and
  let the Dev decide; `ok` → continue. A full resolve is
  `kb resolve --write-cache docs/impl/<ticket-id>/context.md <ticket-file>`:
  the command writes the header and the resolved sections; you never
  edit above the `<!-- kb:placeholder-map -->` marker.
- **Ground** — read resolved L2; escalate to L3 via the `kb_get_section`
  MCP tool (CLI fallback: `kb get <doc> <section> --level l3`) only for a
  value that will be encoded in code or tests, and only for a section
  already chosen; then `kb_search` with `kinds=["dev"]` over both own-repo
  documents, budgeted at 500–800 tokens for broad discovery —
  `<repo_id>-code` for structure and `<repo_id>-svc` for responsibility,
  each restricted with `tags=["<repo_id>-code"]` /
  `tags=["<repo_id>-svc"]` — (CLI fallback: `kb query --kind dev` with
  `--tags <repo_id>-code` / `--tags <repo_id>-svc`) and then read the
  actual code. State the rule:
  *knowledge orients, code decides* — skip whichever document is missing
  and read the code directly for that half.
  A `<repo_id>-code` missing from the hub is not yet published — a
  push to the default branch publishes nothing; tell the Dev to run `kb publish` after the
  merge (it tags `kb-publish/<ts>` and `kb-code.yml` publishes from the
  tag); `kb doctor` says whether the hub lags. A `<repo_id>-svc` missing from the hub is either not yet
  seeded (`dev-code-seed`) or seeded and not yet published — check
  `.kb/<repo_id>-svc/` locally: present → say "seeded, unpublished: run
  `kb publish --pr`" in one line; absent → "not seeded". Reads stay
  hub-only either way; never report it as a KB gap.
- **Ticket and mission lookup** — one separate query,
  `kb_search` for `"<ticket or mission topic>"` with `kinds=["ba"]`
  (CLI fallback: `kb query … --kind ba`), for the ticket and its parent mission as published by
  the BA. Cite what you use.
- **Knowledge lookup** — one separate query,
  `kb_search` for `"<domain term>"` with `kinds=["kb"]` (CLI fallback:
  `kb query … --kind kb`), for the
  domain knowledge the ticket cites. Never mix it into the `--kind dev`
  query.
- **Placeholders** — for each `%%TODO: verify against codebase%%`, verify
  the real name against the codebase and record `placeholder → verified
  value (file:line or code-knowledge ref)`; report the list to the BA;
  **never edit the ticket**; unverifiable here → `OPEN(BA)`. Record the
  map in the cache file's `## Placeholder map` table below the marker
  (`| placeholder | verified value | evidence (file:line or ref) |`).
- **Run the phases** — run the `/dev-design` prompt (or follow
  `docs/impl/` conventions inline if prompts are unavailable), then —
  after the Dev approves it — the `/dev-plan` prompt, then the
  `/dev-execute` prompt, then the `/dev-handover` prompt.
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
