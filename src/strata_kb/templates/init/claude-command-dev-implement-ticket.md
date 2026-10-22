---
description: Implement a BA ticket grounded in the KB — resolve pinned citations, verify %%TODO%% placeholders, then design → plan → execute → handover under TDD
argument-hint: "[ticket id, path, or pasted ticket]"
---

Invoke the `dev-implement-ticket` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the ticket when given; when empty,
ask for it during Intake.

Pipeline: Intake → Questions → Check → Resolve → Ground → Placeholders →
design → plan → execute → handover. This command is also the safe re-entry point: called again on a
ticket already in progress it reports state and offers the next step rather
than redoing finished phases.

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

**A blocked CLI counts as no CLI.** A `kb` command that has a
`strata-kb` MCP tool has no CLI here when it cannot run: `kb` is not
installed, the permission system denies it, it refuses to run in this
environment (as hub-reading commands do on Claude Code cloud), or it
cannot reach the hub. Then run its MCP tool, even where this skill runs
the CLI first, and carry on: that is the fallback, not a failure and not
a denial to report. Stop only when the MCP tool fails too.

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

Steps the skill enforces: **Intake** runs `kb impl tidy` first (it moves an
old flat `docs/impl/<id>-*` layout into `docs/impl/<id>/` — commit the
renames on their own before the first task; no CLI → move them by hand),
then gets the ticket — given only an id, fetches it first (the hub is the
source of truth: MCP `kb_ticket_fetch` `<id>`, its text saved as
`docs/impl/<id>/ticket.md`, your `<ticket-file>`; CLI fallback `kb ticket
fetch <id>` writes that file), a path
or a pasted body being the fallback when the hub has no copy or is
unreachable; a fetched ticket has no `## Definition of Ready` (being on
the hub means DoR passed), so its absence is not a stop — then reads the
ticket's `## Dependencies` (`Blocked by:` / `Blocks:`) and, when a
`> Parent mission:` line is present, that mission's `## Sequencing` row
(from the local mission file, else `kb_get_section` `<doc> <M-id>` at `l3`,
CLI fallback `kb get <doc> <M-id> --level l3`, from the hub), and stops if there is no `kb-context` block to resolve; then **claims** the
ticket with `kb claim take <id>` (needs `STRATA_KB_HUB_URL` and
`STRATA_KB_HTTP_TOKEN`; run again while held, it only refreshes): exit `3`
→ STOP, "`<id>` is taken by `<holder>` (`<phase>`, updated `<x>` ago). Pick
another ticket, or ask a hub admin to release it."; exit `1` → STOP and
show its message (a hub without the route answers `hub server has no
/api/claims — upgrade it to strata-kb 1.31.0 or later`); a new claim on a
ticket whose branch (`auto/<id>` or `<id>`) already exists on `origin` →
`git fetch origin`, switch to that branch, continue there under the
re-entry rules and log whose work was taken over (in Auto mode a STOP ends
`AUTO-RESULT: failed claim-lost <id>` or `failed claim-error <message>`);
**Questions** calls `kb_question_list(ticket=<id>, status=all)` on every entry
and handles each question by state. The tools work only against the shared
hub server: when `kb_question_list` answers `Q&A needs the shared hub server —
point MCP at it (kb mcp-setup)`, or the client does not expose it, read the
local `docs/impl/<id>/design.md` and `plan.md`. If every `Q<id>` line carries
`— answered rev N` (or there are none), continue with
`BA-Q: unknown (Q&A unavailable)` and a one-line note to the Dev; if any
`Q<id>` line lacks it, STOP and tell the Dev, because its state cannot be
known, never treating it as "no questions". **answered**
and not yet marked in the design/plan `## Open questions` → show the answer
with its changed sections, re-fetch the ticket with `kb_ticket_fetch` into
`docs/impl/<id>/ticket.md`, mark the line `— answered rev N — re-draft` (N = the
answer's `answer_rev`, else the hub rev; `— re-draft` tells `dev-design` or
`dev-plan` to re-dispatch its author once for this new answer), and go back to `dev-design` when a
changed section touches an approved design (it goes back to `status: draft`);
**waiting** → show the answer as information only, say which revision it
waits for, do not act on it; **open** and blocking (`blocks:` names an AC) →
say so in the state line (`BA-Q: open Q<ids>`), do not continue past the gate,
and give the Dev the hub Q&A link (`STRATA_KB_HUB_URL` plus
`/ui/questions/ticket?repo=<repo-id>&ticket=<id>`, `<repo-id>` = the BA repo,
as `kb_question_list` prints it in `<repo>:<ticket>`; path only when unset;
never show `STRATA_KB_HTTP_TOKEN`); an open question that blocks no AC does not stop
the flow but still shows in the state line; **Check the
grounding** runs MCP `kb_ticket_check` with your `<ticket-file>`'s text (CLI
fallback `kb ticket check docs/impl/<id>/ticket.md`, which reads the local
`-code` only when the hub holds none) when the ticket has a `## Technical grounding` section: PASS
shows every `[warn]` to the Dev, who decides; FAIL with `re-run /sa-ticket-ground` STOPs as a blocker for
the BA (the SA re-grounds on the current `-code`), unless the run also printed
the local-fallback note `checked against the local -code, not the hub's copy` —
then re-run once the hub is reachable and holds the -code; FAIL without it is reported to the BA and
STOPs; no section, or neither MCP nor CLI, skips with a note; **Resolve** triages exactly as in the
Freshness re-check above; the full resolve is `kb resolve --write-cache
docs/impl/<ticket-id>/context.md <ticket-file>`, which writes the header
and the resolved sections — you never edit above the
`<!-- kb:placeholder-map -->` marker; **Ground**
reads resolved L2, calling `kb_get_section` (CLI fallback `kb get <doc>
<section> --level l3`) only for a section already
chosen and escalating to L3 only for a value that will be encoded in code
or tests, then searches with `kb_search` (`kinds=["dev"]`, `tags=["<repo_id>-code"]` /
`tags=["<repo_id>-svc"]`; CLI fallback `kb query --kind dev --tags
<repo_id>-code` / `--tags <repo_id>-svc`) within a 500–800 token budget for broad discovery
— `<repo_id>-code` and `<repo_id>-svc` for structure and responsibility
before reading the actual code, skipping whichever document is missing and
reading the code directly for that half — a `<repo_id>-code` missing from
the hub is not yet published (a push to the default branch publishes nothing; tell the Dev to run `kb publish` after the merge — it tags `kb-publish/<ts>` and `kb-code.yml`
publishes from the tag; `kb doctor` says whether the hub lags), and a `<repo_id>-svc`
missing from the hub is either not yet seeded (`dev-code-seed`) or seeded
and not yet published, checked via `.kb/<repo_id>-svc/` locally (present →
say "seeded, unpublished: run `kb publish --pr`"; absent → "not seeded"),
reads staying hub-only either way and never reported as a KB
gap; **Placeholders** verifies every
`%%TODO: verify against codebase%%` against the codebase, reports the list
to the BA, **never edits the ticket**, and records the map in the cache
file's `## Placeholder map` table below the marker
(`| placeholder | verified value | evidence (file:line or ref) |`); and
anything unverifiable becomes `OPEN(BA)`; **Run the phases** invokes the
`dev-design`, `dev-plan`, `dev-execute`, then `dev-handover` skills in
order, deriving re-entry state — never stored — from
`docs/impl/<ticket-id>/design.md` and `plan.md` by their own `status:`
header and `## Review record` table: `status: draft` with no clean round
recorded runs that phase's review first (A1 for design, A2 for plan);
`status: draft` with a clean round recorded offers the matching gate;
`status: approved` moves on; design approved with no plan file but `git log
--oneline <default>..HEAD` non-empty is `plan ⚠ missing, N commits on
branch` — ask before running `dev-plan`, work may already be committed; an
approved plan turns tasks into ticked/total checkboxes; `kb pr find --head <branch>
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

`BA-Q:` comes from `kb_question_list`: `none`, `open Q<ids>` or
`waiting Q<ids>`, a mixed state written `open Q1; waiting Q2`, and
`unknown (Q&A unavailable)` when the Q&A tools are refused (see Questions).

## Next step — ALWAYS end your response with this block

Close every response with a state line and an ordered list of next steps.
Include it even when you stopped early or hit an error — especially then.

    ## Next step

    → 1. <next step in flow> — <what it does>   (next in flow)
      2. <revise the current phase> — <how>
      3. <stop/park> — <where the work is saved>

    State: design <✅ approved|📝 draft|⬜ not written> · plan <✅ approved|📝 draft|⬜ not written|⚠ missing, N commits|n/a (spike)> · tasks <n>/<m> · PR <✅ opened|✅ merged|❌ closed|⬜ not opened|? unknown> · BA-Q: none | open Q<ids> | waiting Q<ids>

Rules:
- Option 1 is ALWAYS the next step in flow order: design → plan → execute → handover.
- Show the exact command with the ticket id already filled in, ready to copy.
- The `State:` line always shows all five markers, even the ones not yet reached.
- A blocker takes option 1 instead and says so, e.g.
  `→ 1. Send back to the BA — ref ATM-STD §5.3 is broken, re-pin needed`.
  Flow order never hides a blocker.

## Auto mode

Run `kb auto status --json`. When `enabled` is false, this section does not apply. When true, the rules below replace the human gates named in them.

The runner starts this skill as `/dev-implement-ticket <us-id>`. Nobody answers questions during the run: you run design, plan, execute and handover yourself, in that order, each under its own Auto mode section, and a step above that says "let the Dev decide", "ask before" or "offer" is yours to carry out, under the rules below. Every step and every hard rule not named here stays as written.

**Decisions.** Write each decision as one `**Auto decision:**` line: what you checked, the options, the choice, and why. Append it to `docs/impl/<ticket-id>/auto-decisions.md` (create the file with the heading `# Auto decisions`; it is committed with the ticket's other files). `dev-handover` copies the lines into the PR's `## Notes`.

**A denied command.** A command the permission system denies ends the run with `AUTO-RESULT: failed command-denied <command>`. Never work around a denial: no other shell, no edit of the settings. The one exception is a denied `kb` command that has a `strata-kb` MCP tool: it counts as no CLI: run the MCP tool and carry on.

**A real blocker is a BA question.** A blocker is something only the BA can settle: a broken citation, a ticket with no `kb-context`, a failed grounding check, a stale citation that changes an AC, or an unmerged dependency this story needs. Call `kb_question_ask(ticket, question, asked_by, context, blocks)`: `asked_by` is `kb-auto`; `blocks` names the AC ids the blocker touches (every AC when it stops the whole ticket). Skip the call when `kb_question_list` already shows the same question. Then end `AUTO-RESULT: blocked-qa Q<id>`, with every other blocking id from `kb_question_list`. When Q&A is unavailable, end `AUTO-RESULT: failed qa-unavailable` instead.

**Already finished.** The runner re-runs a task after a crash, so check first. Run `kb pr find --head auto/<ticket-id> --state merged --json`. A merged PR means the code is in and only the history row or the publish can be missing. Look in `.kb/<repo_id>-svc/` for this ticket id in a `hist.*` row (`kb svc note` wrote it). Row present: run `kb doctor`; when it advises `kb publish`, run `git fetch origin && git merge origin/<default-branch>` (`<default-branch>` is `default_branch` in `kb auto status --json`: the squash merge leaves the ticket branch behind `origin/<default-branch>`, and `kb publish` refuses to run from it with `behind origin/<default-branch> — pull, then kb publish`; the `hist` row is on the default branch after the merge, and a headless run never checks that branch out, so it merges it in here), then `kb publish` once (on a `behind origin/` refusal merge once more and retry once), then end `AUTO-RESULT: done`. Row missing: end `AUTO-RESULT: failed merged-without-history <pr-url>`. With no merged PR, look for an open one (`--state open`). An open PR means a crashed run: `git fetch origin && git switch auto/<ticket-id>`, then `git pull origin auto/<ticket-id>`, check what the branch already holds, and continue at the CI step of `dev-handover`'s branch rule.

- **Intake: "if this story is blocked by something unmerged, say so and let the Dev decide"** → decide. Read the blocker's status (`kb mission next --from-hub --json`) and look for its deliverable in the codebase. Proceed when the blocker is `done`, when its code is already here, or when this story does not touch it, and log an Auto decision line. A blocker whose code this story needs and the codebase lacks is a real blocker.
- **Intake: no `kb-context` block — "No `kb-context` block" means stop, the ticket is not Ready** → a real blocker: ask the BA.
- **Questions: an `open` blocking question — "do not continue past the gate" and give the Dev the hub Q&A link** → stop. End `AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]` with every blocking question that is `open` or `waiting`, written as `Q<id>` and comma-separated. The runner re-runs this task once they are all `answered`. Run no phase and leave the working tree as it is; the hub link is not needed. A question that blocks no AC does not stop you; it shows in the state line.
- **Questions: "STOP and tell the Dev" when Q&A is unavailable and a `Q<id>` line lacks `— answered rev N`** → end `AUTO-RESULT: failed qa-unavailable`; the state of that question cannot be known.
- **Check the grounding: `[warn]` lines — "the Dev decides"** → read each `[warn]` (a diff, or facts that could not be verified) against the code, decide whether it touches an AC, and continue. Log the decision.
- **Check the grounding: FAIL with "re-run /sa-ticket-ground", or any other FAIL — a blocker for the BA** → a real blocker: ask the BA, and put the errors in `context`.
- **Freshness and Resolve: `broken` is a STOP; `stale` shows both versions and "humans decide"** → `broken` is a real blocker. For `stale`, read the pinned text and the hub's current text. When the difference changes no AC this story implements, continue on the pinned version and log both sides in an Auto decision line. Otherwise it is a real blocker.
- **Run the phases: "after the Dev approves it"** → each phase approves itself under its own Auto mode. Run `dev-design`, `dev-plan`, `dev-execute`, `dev-handover` in order; a phase that stops tells you why, and you end with the result line below.
- **Re-entry: `plan ⚠ missing, N commits on branch` — "ask before running `dev-plan`"** → read `git log --oneline <default>..HEAD`. When the commits belong to this ticket, run `dev-plan` for the work still missing and tick the tasks the commits already complete, after checking each against its test. Log the decision.
- **Re-entry: `PR ❌ closed` — "re-handover or reopen"** → re-handover: `dev-handover` opens a new PR.
- **Re-entry: no branch, on the default branch — "offer `git switch -c <ticket-id>`"** → branch at once with `git fetch origin main && git switch -c auto/<ticket-id> FETCH_HEAD`; never check out `main`. Do this before the first phase.
- **Re-entry: the current branch names a different ticket — "two tickets in flight; switch branches first"** → when `git status` is clean, create this ticket's branch the same way and leave the other branch alone. A dirty tree ends `AUTO-RESULT: failed two-tickets-in-flight`.
- **Hard rule "Never work on the default branch; never push to a protected branch; never merge; never tick DoD/AC checkboxes for humans"** → `dev-handover` opens the PR and merges it under its own Auto mode. The rest of the rule stands: no work on `main`, no push to `main`, no DoD or AC box ticked.

### Result line

End the reply with exactly one line, and make it the last line. Nothing follows it: no code fence, no markdown, no closing remark. The `## Next step` block comes first. It has one of three forms:

- `AUTO-RESULT: done` — the PR is merged and `kb publish` has run, or the work was already finished. Write no text after `done`; always give a reason after `failed`.
- `AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]` — a BA question blocks an AC; the runner re-runs this task once the questions are answered.
- `AUTO-RESULT: failed <reason>` — anything else: `ci-red <pr-url>` after 2 fix rounds, `design-review`, `plan-review`, `tests-red task <n>`, `plan-defect task <n>`, `qa-unavailable`, `merged-without-history <pr-url>`, `two-tickets-in-flight`, `claim-lost <ticket-id>`, `claim-error <message>`, or `command-denied <command>`. The reason goes on the same line.
