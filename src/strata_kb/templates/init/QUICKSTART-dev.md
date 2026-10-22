# Strata Quickstart (dev repo)

This repo is a **product code** repo: it consumes the shared knowledge base
while implementing BA tickets, and it publishes two knowledge documents
about its OWN source code back to the hub. Generated structure
(`<repo_id>-code`) is generated, never written by hand — `kb publish`
tags the commit `kb-publish/<ts>` and `.github/workflows/kb-code.yml`
runs `kb code-ingest` → `kb build` → `kb ci-publish` on that tag; locally, `kb svc note`, `kb build` and `kb publish` regenerate it
from your working tree — it is never committed (`.gitignore`:
`.kb/*-code/`). Curated responsibility knowledge (`<repo_id>-svc`) is bootstrapped
once via `/dev-code-seed` (see "Onboarding an existing project (once)"
below) and then accrues automatically per ticket via `kb svc note` (see
"Keeping it current" below). This repo never ingests documents from
outside itself — that happens in `child` repos, reviewed on the `hub`.

## Setup once

1. **Install** — `pip install "strata-kb[code]"` (or clone this repo if
   someone already scaffolded it; otherwise `kb init --kind dev` in an empty
   folder creates it). The `code` extra adds the parsers that read routes,
   pages, jobs and exported symbols; without it those sections are all
   `not scanned`, the SA cannot prove a route or page absent, and
   `kb doctor` warns. CI (`kb-code.yml`) installs the extra for you.
2. **Point at the hub** — fill `hub:` in `.kb/config.yaml` with the main
   hub's git URL or path. This is the only read source for `kb query` /
   `kb resolve` / `kb get` / MCP.
3. **Point at the intake for publishing** — fill `intake:` in
   `.kb/config.yaml` with the hub's intake service URL, then ask the hub
   maintainer to add this repo under `repos:` in the hub's
   `federation/registry.yaml`. **Publishing is `kb publish`**, run from
   the default branch after a merge: it tags the commit `kb-publish/<ts>`
   and pushes the tag, and `kb-code.yml` publishes `<repo_id>-code` from
   that tag. A push to `main` publishes nothing — the intake accepts a
   publish only from a `kb-publish/*` tag. The same `kb ci-publish` step
   republishes committed `<repo_id>-svc` content too: it diffs the whole
   `.kb/` tree, not `-code` alone, so a merged `-svc` amend rides the
   next `kb publish` out to the hub with no separate command. What CI
   never does is *create* `-svc` content — `--scaffold-svc` is never
   passed there. The one-time seed below runs `kb publish --pr`, which
   opens the hub PR directly instead of going through the tag.
   Whether the hub PR `kb ci-publish` opens is merged for you is a
   **per-repo switch** on the hub's Registry page (an admin turns
   *auto-merge* on for this repo). Ask the hub maintainer whether it is on.
   When it is on, the hub merges the **whole** publish PR right after
   opening it — including any `<repo_id>-svc` content riding along: the
   intake keys the publish branch by repo id and reuses it while a PR is
   pending, so one PR can carry a regenerated `-code` and a merged `-svc`
   amend, and the switch cannot tell them apart. The `-svc` review
   therefore happens **locally**, in `/dev-code-seed` step 4, before the
   section reaches `reviewed` — never at the hub. If the merge fails, the
   PR stays open for the hub maintainer and the publish still counts as
   done. `kb publish` and `kb ci-publish` print "merged" when it merged (the CI step summary still shows `hub PR: <url>`).
   With the switch off, a hub BA or architect merges the PR as before.
4. **Connect the shared MCP server** — run `kb mcp-setup` (in your assistant:
   `/kb-mcp-setup`). It asks for the hub's HTTP base URL and token, writes
   both into `.env`, makes sure git ignores that file, and then verifies them
   against the hub so a wrong URL and a rejected token give you different
   errors.
   - `STRATA_KB_HUB_URL` — e.g. `http://kb-hub.example.com:8321`
   - `STRATA_KB_HTTP_TOKEN` — the hub token (ask the hub maintainer)

   `.mcp.json` (Claude Code) and `.cursor/mcp.json` (Cursor) already read
   those two variables from your environment, so load `.env` into your shell
   (`set -a; source .env; set +a`, or use direnv) and restart your assistant —
   MCP reads the environment only at startup.

   This is a *different* value from `hub:` in `.kb/config.yaml`, which is the
   git/path federation hub used by `kb query` and the lint gates.
5. **Open this repo** in Claude Code, GitHub Copilot Chat, or Cursor — the
   `dev-implement-ticket`, `dev-design`, `dev-plan`, `dev-execute`, and
   `dev-handover` skills/commands/prompts are scaffolded for all three.

## Onboarding an existing project (once)

An existing product repo already has services doing real work — adopting
strata-kb should not mean documenting the system from a blank page. Run
`/dev-code-seed` (the `dev-code-seed` skill/command/prompt) once per repo,
and it walks seven steps:

1. **Preflight** — confirms `.kb/config.yaml` has `hub:`, `repo_id:`, and
   `intake:`; confirms this repo is allowlisted in the hub's
   `federation/registry.yaml` (ask the hub maintainer if it isn't yet);
   warns if the working tree is dirty.
2. **Extract** — runs `kb code-ingest --scaffold-svc`, which regenerates
   `<repo_id>-code` and creates a `pending` `svc.<name>` scaffold in
   `<repo_id>-svc` for every service the extractors found, backed by
   deterministic code evidence in each section's L3.
3. **Draft** — runs `kb summarize <repo_id>-svc`, asking an LLM to write
   an L2 responsibility paragraph for every scaffolded section from that
   L3 evidence.
4. **Review — the actual work, and it is yours.** Walk every drafted
   `svc.*` section, L2 next to its L3 evidence, and correct it.
   **The LLM draft is a draft, not a fact.** It can name the wrong flow,
   miss a responsibility, or over-claim one — approving a section you
   have not read defeats the entire point of the gate. Where a
   responsibility touches a domain standard, cite `doc-id §section` from
   the hub instead of restating the rule in your own words.
5. **Approve** — `kb approve <repo_id>-svc` (or `--section <id>` for a
   subset) flips the sections you just corrected from `summarized` to
   `reviewed`.
6. **Flows (optional)** — add `flow.<name>` sections for business flows
   that cross several services, if you can describe them. Skip freely —
   a missing flow beats a guessed one.
7. **Validate and publish** — `kb build` **without** `--allow-pending`
   must pass before you publish; resolve or remove anything still
   `pending` (`--allow-pending` is only for the middle of a seed, never
   for what you publish). Then commit and run `kb publish --pr` to open
   a PR on the hub — plain `kb publish` also works, through the tag and
   `kb-code.yml`, but `--pr` opens the review PR straight away.
   **That hub PR is reviewed by a BA or architect**, the same
   as any other hub content — unless the hub has auto-merge switched on
   for this repo: then the hub merges it on the repo's next intake publish,
   and the `-svc` review you did in step 4 is the only one (see the
   auto-merge note in step 3 of "Setup once" above). `kb publish --pr` does
   not go through intake, so it does not merge the PR by itself.

Budget **10–15 min per service** for step 4 — that is the honest cost of
a seed, and it is a one-time cost. Everything after the seed publishes is
either regenerated automatically (`<repo_id>-code`) or accrued a few
lines at a time (`<repo_id>-svc §hist.*`, see "Keeping it current" below)
— no per-ticket documentation discipline required.

## Implement a ticket

Pick the entry point that matches where the work already stands — every
phase is resumable, because state lives in `docs/impl/`, the branch, and
the PR, not in the assistant's memory:

| Situation | Run |
| --- | --- |
| New ticket, nothing started | `/dev-implement-ticket <ticket>` |
| Small ticket, the whole change is obvious | `/dev-implement-ticket <ticket>` — the flow collapses itself; the design is still written to `docs/impl/<ticket-id>/design.md`, just a bounded one (a paragraph, `path: bounded`) instead of the full template |
| Design approved, no plan yet | `/dev-plan <id>` |
| Plan approved, or execution already in progress | `/dev-execute <id>` |
| Code hand-implemented, needs a PR write-up | `/dev-handover <id>` |
| Lost track of where a ticket stands | `/dev-implement-ticket <id>` |
| A technical question you want answered with evidence | `/dev-sa <question>` |
| Just want to check a citation, no implementation | `kb resolve <file>` |

`/dev-implement-ticket` is also the orchestrator: given a ticket fresh, it
runs Intake → Check → Resolve → Ground → Placeholders, then invokes `dev-design`,
`dev-plan`, `dev-execute`, and `dev-handover` in order, detecting how far a
ticket already got so it never redoes finished work.

**A ticket id is enough.** Given only an id (`M-<slug>-US<n>`), Intake runs
`kb ticket fetch <id>`, which reads the ticket from the hub and writes it to
`docs/impl/<id>/ticket.md`. The hub is the source of truth; that copy is
regenerated on every fetch and gitignored, so never edit it — amend the ticket
in the BA repo. A path or a pasted body still works when the hub has no copy or
is unreachable. If several repos publish the same id, qualify it: `<repo>:<id>`.

**The ticket's grounding is checked next.** Right after Intake the flow runs
`kb ticket check docs/impl/<id>/ticket.md` (skipped, with a note, when the
ticket has no `## Technical grounding`). A `-code` that moved since the SA
grounded the ticket is not a failure: PASS with a `[warn]` means the cited
names still hold, so read the diff and decide. A FAIL carrying `re-run
/sa-ticket-ground` means a cited fact is gone: STOP and send it back to the BA,
who has the SA re-ground it. If the run also prints `checked against the local
-code, not the hub's copy`, your own branch may be the cause: re-run once the
hub is reachable and holds the -code.

## Questions while you design and plan

`dev-design` and `dev-plan` never decide a question they cannot settle by
guessing. Their author subagents list each one under `## Questions raised` in
the draft, tagged `business` or `technical`, with the ACs it blocks. The
orchestrating skill then sorts them:

- **Technical** (how to build it, where it goes, which component to reuse) →
  `dev-sa`, the Dev-repo solution architect. It reads this repo's source and
  the hub's `-code`, `-svc` and domain documents, and returns a decision with
  `path:line` and `doc §section` evidence. The skill writes it into the
  draft's `## Technical decisions` as `- SA-<n>: <decision> — why — evidence`
  and re-dispatches the author. Nothing goes to the hub. You can also call it
  yourself: `/dev-sa <question>` for the ticket in flight; it returns the line
  for you to record.
- **Business** (anything that changes what an AC means) → asked of the BA with
  MCP `kb_question_ask`, which stores it on the hub. The draft's `## Open
  questions` gets `- Q<id> — <question> — blocks: <AC ids|none>`. A technical
  question that `dev-sa` returns as `business question:` goes the same way.
  The BA answers it with `/ba-answer-questions`.
- **A blocking question stops the gate.** A design or plan with an open
  question that blocks an AC cannot pass GATE 1 or GATE 2: the skill stops and
  gives you the hub's Q&A link to paste in chat. A question that blocks no AC
  does not stop the gate; the A1 and A2 reviewers treat it as a known open
  item, not a defect.
- **The `BA-Q` marker.** The `State:` line of the Next-step block in
  `/dev-implement-ticket`, `dev-design`, `dev-plan`, `dev-execute` and
  `dev-handover` ends with a fifth marker: `BA-Q: none | open Q<ids> | waiting Q<ids>`.
- **Resuming.** On every entry `/dev-implement-ticket` calls
  `kb_question_list` for the ticket. An **answered** question you have not
  marked yet is shown with its changed sections; the flow re-fetches the
  ticket into `docs/impl/<id>/ticket.md`, marks the `## Open questions` line
  `— answered rev N — re-draft` (the phase re-dispatches its author once for
  it, then drops `— re-draft`), and sends you back to `dev-design` if a changed section
  touches an approved design (it returns to `draft`). A **waiting** question
  (answered, but the BA's new ticket revision is not on the hub yet) is shown
  as information only: do not act on it. An **open** blocking one stops the
  flow.
- **Only on the shared hub server.** `kb_question_ask`, `kb_question_list` and
  `kb_question_answer` work only when MCP points at the hub's HTTP server
  (`kb mcp-setup`); a hub URL read through a local cache clone, or any other
  target, answers `Q&A needs the shared hub server — point MCP at it (kb
  mcp-setup)`. Any authenticated caller may write, and
  the names are self-declared (`git config user.name`): they track who asked,
  nothing more. At most 50 questions per ticket can be open. When Q&A is
  unavailable and every `Q<id>` line in the design or plan carries `— answered
  rev N` (or there are none), `/dev-implement-ticket` continues with `BA-Q:
  unknown (Q&A unavailable)` and a note; if any `Q<id>` line lacks it, it
  stops, because it cannot know the state. In `dev-design` and `dev-plan` a
  business question with `blocks: none` then falls back to `OPEN(BA)`; only a
  blocking one stops.
- **Review.** The pre-code axis of `docs/pr-review-rubric.md` accepts a `Q<id>`
  asked through hub Q&A as the escalation of an ambiguous AC.

## Fix a bug

A bug the BA published is `BUG-<n>` (`> Type: bug` or `hotfix`,
`> Severity: S1`–`S4`). It has no user story and no acceptance criteria: it is
done when its steps no longer reproduce the wrong result. Run
`/dev-fix-bug BUG-<n>` (installed by `kb init --kind dev`):

1. **Intake** — fetch the bug. `kb ticket fetch BUG-<n>` also copies its
   screenshots to `docs/impl/<id>/assets/` and warns once per image missing
   from the hub clone (open `<hub>/assets/<name>`); MCP `kb_ticket_fetch`
   returns text only. Branch `fix/<BUG-id>`, or `hotfix/<BUG-id>` from the
   production line you name.
2. **Reproduce** — a failing test that shows the Actual result. No fix
   without it.
3. **Root cause** — written hypotheses in `docs/impl/<id>/rootcause.md`;
   three failed ones stop the flow for an architecture talk with you.
4. **Fix** — one change at the root cause, full suite green.
5. **Handover** — `/dev-handover` with bug rules: no design or plan, the
   reproduction test and the root cause replace them.

## Several Devs on one repo

Two Devs who pick the same hub ticket would build it twice. A **ticket claim** on
the hub prevents that. `/dev-implement-ticket` and `/dev-fix-bug` run
`kb claim take <id>` in Intake, and every later phase refreshes the claim.

- **One holder per ticket.** The claim names its holder (`<git user.name>@<hostname>`,
  or `STRATA_KB_CLAIM_AS` / `--as`) and its phase: `claimed`, `design`, `plan`,
  `execute`, `handover`, `review`, `publishing`, `waiting-qa`. A second Dev who runs
  the same ticket gets `taken by <holder> (<phase>, updated <x> ago)` (exit `3`)
  and the skill stops: pick another ticket, or ask a hub admin to release it.
  A BA repo has no claims, and `dev-test-workflow` carries none.
- **It expires after 4 hours without an update.** The hub env `STRATA_KB_CLAIM_TTL`
  (seconds, default `14400`) sets it. `dev-design`, `dev-plan`, `dev-execute` and
  `dev-handover` update the claim on entry, `dev-execute` after each task commit,
  and `kb auto run` sends a heartbeat every `auto.claim_heartbeat` seconds
  (default `900`, in `.kb/config.yaml`).
- **Held through review and publishing.** Once you have opened the PR, tell
  `dev-handover` (or re-run `/dev-handover <id>`): it finds the PR and sets `review`
  with its URL; until then the claim expires after 4 hours. A claim in `review` or `publishing` with a PR never
  expires, so the ticket stays yours while the PR waits. A claim the auto runner
  marked `stopped` (the run stopped with a reason) never expires either, and
  resumes when you run it again.
- **Taking over.** After an expiry or a release, the next Dev who claims the ticket
  and finds its branch on `origin` (`auto/<id>`, `<id>`, `fix/<BUG-id>`,
  `hotfix/<BUG-id>`) continues on that branch and logs whose work it took over.
  If your claim was released while you work, the next update exits `3` (`lost:
  <reason> by <who>`) and the skill stops without pushing.
- **Look and release.** `kb claim list [--json]` shows what is held;
  `kb claim release <ticket> [--reason TEXT]` gives yours back. A hub admin can
  release anyone's claim with the **Release** button (and a reason) on the ticket
  page of the Ticket menu. The menu shows the claim as *In progress*, *In review*,
  *Publishing* or *Stopped: <reason>*.
- **Hub first.** The commands need `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN`
  and a hub that is 1.31.0 or later. An older hub has no `/api/claims`: `kb claim`
  exits `1` with `hub server has no /api/claims — upgrade it to strata-kb 1.31.0 or
  later`, and `kb auto run` stops. Upgrade the hub, then the CLI, then re-run
  `kb init --kind dev`.
- **The publish guard.** In a dev repo `kb publish` refuses to run from a checkout
  that is behind `origin/<default>` (`behind origin/<default> — pull, then kb
  publish`; also `no origin remote — …` and `could not fetch origin/<default>: …`),
  because the snapshot would drop another machine's newer `hist` row. A squash merge
  leaves the ticket branch behind, so after the merge switch to the default branch,
  pull, then publish: `git fetch origin && git switch <default> && git pull --ff-only
  origin <default>`, then `kb publish`. `dev-handover` says the same.

## Where work lives

- `docs/impl/<ticket-id>/design.md` — the design produced by `dev-design`.
- `docs/impl/<ticket-id>/plan.md` — the checkbox task plan produced by
  `dev-plan`, and the resume point `dev-execute` reads from.
- `docs/impl/<ticket-id>/context.md` — the resolved-context cache written
  by `dev-implement-ticket`; gitignored, regenerated by any full
  re-resolve. Not a state marker — it may legitimately be absent.
- `docs/impl/<ticket-id>/review/` — per-task diffs, reviewer reports, the
  branch diff and the merge-risk report; gitignored.

State is derived from those first two files plus the current git branch and
whether a PR is open — never from conversation history — so any phase can
resume cold in a brand-new session. `kb init` never edits your
`docs/impl/` content: it adds `docs/impl/.gitkeep` (so the directory exists
before your first ticket does) and `docs/impl/.gitignore` (so the context
cache, fetched tickets and review artefacts never land in a PR), and moves an old flat
layout (`<id>-design.md`, `<id>-plan.md`, `<id>-context.md`, `<id>-review/`)
into `<id>/` — never overwriting. `kb impl tidy` does the same move on
demand. Commit the renames.

### Waves and lanes

Every task in `docs/impl/<ticket-id>/plan.md` carries a `Depends on:` line
under its `### Task <n>:` heading — `none`, or the tasks whose Interfaces it
consumes or whose files it shares. `dev-plan` derives it; the A2 reviewer
checks it. `kb plan waves docs/impl/<ticket-id>/plan.md` turns those lines
into waves (wave n = tasks whose dependencies all sit in earlier waves) and
fails when two tasks share a file without a dependency between them, when
there is a cycle, or when a line is missing — a plan like that has no safe
parallel order; a plan where every task lacks the line predates waves and
runs sequentially. `dev-execute` runs it after isolating the branch: a wave of
one task runs as before; a wave of several runs each task in its own git
worktree lane cut from the ticket branch, at most 3 lanes at a time, merged
back in task order with `--no-ff`, the full suite run once per wave. A merge
conflict means the plan was wrong and goes back to `dev-plan`. A task that
drives a shared running environment (an e2e stack, fixed host ports) carries
`Serial resource: <name>`; `kb plan waves` prints it after `serial:` in its
wave, and `dev-execute` runs those tasks one at a time in the ticket worktree,
never in a lane.

## The four gates, five agent review rounds

Nothing in this pipeline merges or ships without a human:

1. **Design approved** — the Dev signs off on `dev-design`'s output before
   any plan is written.
2. **Plan approved** — the Dev signs off on `dev-plan`'s task breakdown
   before any code is written.
3. **PR opened** — `dev-handover` writes up the PR body; a human opens it.
4. **Merged** — a human reviews and merges. The agent does neither of the
   last two itself.

Before each of the first three gates, a different agent has already read
the work back in a context of its own — never the same agent that
produced it:

| | Where | What it looks at |
|---|---|---|
| A1 | `dev-design`, before GATE 1 | whether the design matches the ticket |
| A2 | `dev-plan`, before GATE 2 | whether the plan is test-first and runnable |
| A3 | `dev-execute`, per task | whether this task's diff meets its spec, and whether the code is good |
| A4 | `dev-execute`, after the last task | whether the finished branch rounds out the ticket |
| A5 | `dev-handover`, before GATE 3 | whether merging into the default branch is safe |

Criteria live in `docs/pr-review-rubric.md`, overridden by
`docs/pr-review-rubric.local.md`. Each round allows at most 3 fix/review
passes; a round only counts as clean once no BLOCKER and no SUGGESTED
finding is left open — NOTE and NITS get recorded, not fixed.

A1 and A2 aim for one review round plus one verification round. The author
self-checks before review; round 1 returns a coverage matrix and tags each
gap with a defect class; the fix sweeps the whole artefact for each class;
later rounds verify the fix against the diff. A design over 8 ACs or 600
lines, or a plan over 12 tasks or 600 lines, is reviewed in parallel slices
plus a lead reviewer that re-checks the slice findings and checks drift from
the ticket and the design. A round that finds no fewer BLOCKER plus
SUGGESTED gaps than the one before stops the loop and hands you the trend.

Where your assistant's runtime cannot dispatch subagents — the default
for the Copilot and Cursor wrappers — the review still runs, but as a
single pass reading only what it was handed, and it is a **report, not a
gate**: the phase stops there and hands the result to you instead of
advancing on its own say-so.

## What is enforced

### Machine-enforced

- **The PR carries its evidence** — `.github/workflows/kb-pr-lint.yml`
  checks out the branch read-only and runs `kb pr lint` on every pull
  request. It fails when Ticket, Changes or Testing is missing or still
  holds the template's comment, when Testing has no fenced output, when
  no fence holds the plan's `cmd.test:` command, or when Testing carries
  no `Blocking: No` line. Add **`pr-lint` to the branch's
  required checks** once: `kb init` writes the workflow but cannot turn
  on branch protection for you. Unlike `kb-ticket-lint`, this gate never self-skips — once
  required, it blocks **every** PR without the required sections, bot PRs
  (a Dependabot bump, a revert) included, so make that required-check
  decision knowingly.
- **Unreviewed knowledge cannot reach the hub** — `kb build` (run by
  `kb-code.yml` on a publish tag and on PRs) exits 1 while any `<repo_id>-svc`
  section is `pending`.
- **The context cache is CLI-owned** — `kb resolve --status-only --cache`
  refuses a cache whose version, ref set or resolved block differs from
  the ticket's.
- **The merge-risk review has run and no BLOCKER remains** — `kb pr lint`
  requires the PR's `## Testing` section to carry a `Blocking: No` line.

### Prompt-only — stated in every wrapper, measured by nothing

A recommendation the skills repeat as a rule; nothing in `kb` enforces or
measures compliance with it. The only check is the human at the gate.

- **TDD** — no production code without a failing test observed first, at
  every step of `dev-execute`; exempt classes are named in
  `docs/tdd-exemptions.md` and declared in the plan.
- **Shown verification** — a completion claim without the real command
  output; `kb pr lint` checks the PR body, not the session.
- **Pinned values, verbatim** — every standard-derived value comes from
  the resolved section at its pinned hub version with a citation comment.
- **The ticket is read-only** — findings go back to the BA; the agent
  never edits the ticket.
- **GATE 1 and GATE 2** — design and plan approved before the next phase;
  the `status:` header records it, a human grants it.
- **`OPEN(BA)`** — an ambiguous AC is escalated, never reinterpreted. During
  design and plan the escalation is a hub question (`Q<id>`); `OPEN(BA)` stays
  for the case `dev-execute` meets mid-implementation, which returns to
  `dev-design`.
- **A1–A4** — the four agent reviews before GATE 3 are prompt discipline;
  nothing in `kb` measures whether they ran. Only A5 has teeth: `kb pr
  lint` reads the `Blocking:` line in the PR's `## Testing` section. An
  agent that skips A1–A4 and writes an honest `Blocking: No` still passes — the gate sits where the
  merge actually happens, not at every step before it.

## Keeping it current

The two code-knowledge documents stay current in two different ways —
neither needs new per-ticket discipline from you:

- **`<repo_id>-code`** needs one command from you: `kb publish` after a
  merge. `kb-code.yml` then runs `kb code-ingest` → `kb build` →
  `kb ci-publish` on the `kb-publish/*` tag, so the hub reflects the
  tagged commit's structure;
  locally, `kb svc note`, `kb build` and `kb publish` regenerate it from
  your working tree — it is never committed (`.gitignore`: `.kb/*-code/`).
  Since 1.3.0 each `svc.*` record also carries its
  named volumes, the healthcheck command and device reservations
  from compose, so the SA grounds those instead of deciding them —
  run `kb publish` once after upgrading before the BA re-grounds.
- **`<repo_id>-svc`** accrues automatically at handover: `dev-handover`
  runs `kb svc note <service> --ticket <id> --title "<title>" --refs
  "<refs>"` for every service a ticket touched, appending one row to
  that service's `hist.<service>` section. You never hand-edit `hist.*`
  — it is an append-only log written only by `kb svc note`.

**Responsibility text can still drift, and it self-reports rather than
self-heals.** When `kb code-ingest --scaffold-svc` refreshes a service's
L3 code evidence, and that section's L2 is already `reviewed`, it
compares the old and new rendered evidence as a **whole-body,
whitespace-trimmed** string — not a semantic diff over specific fields.
**Any** change other than to leading/trailing whitespace flags
`stale-risk: svc.<name>` in the ingest report: a real change (a file
or table added or removed) will trip it, but so will a change in
nothing but *how* the evidence is rendered, with zero code changed
underneath (see the upgrade note just below for exactly that case).
That is not an error and it never touches L2 — it is a flag that a
human-reviewed sentence may no longer match the code, for a human to
resolve. **Amend that section's L2 prose by hand and
leave it `reviewed`** — the person correcting it is the reviewer; no
further approval step is needed.

**Do not reach for `kb summarize --redo` to fix one service.**
`redo_reset` has no per-section scope: it resets **every** section of the
document to `pending` and blanks every `summary`, including sections
that were already `reviewed`, and rebuilds every L2 file from its
scaffold — `services.md` included, not just `history.md`. It is not the
data-loss event it sounds like **for the accrued ticket history**: the
scaffold rebuild keeps every `|`-prefixed line, so the `hist.*` ticket
rows in L2 survive, and `redo_reset` never rewrites `history.raw.md` at
all, so the L3 record survives too. **It genuinely is a data-loss event
for a service's responsibility prose, though**: a human's corrected
`svc.*` text is wiped from both `services.md` (L2) and the manifest's
`summary` field. `services.raw.md`'s code evidence survives, so the
section can always be re-drafted from scratch — but the human's
corrections themselves come back only from git, not from
`kb summarize`. `kb summarize --redo` does not stop at the reset,
either: it re-summarizes in the same command right away. That includes
`hist.*` — its ticket rows survive as described above, but the
machine-authored summary `kb svc note` wrote for that section is
replaced by LLM prose — and every section that was `reviewed` before the
redo loses that status and is re-summarized from scratch along with
everything else. Use the hand-amend path above instead — `--redo` is for
re-seeding a whole document from scratch, never for correcting one
entry.

**The first `kb code-ingest --scaffold-svc` run after upgrading past this
release will likely report `stale-risk` for every already-`reviewed`
`svc.*` section, even though nothing in your code changed.** This release
relabels two L3 evidence lines in the `services` extractor — `tables:`
and `files:` become explicit name-match heuristics, stated as such
because their absence proves nothing — which changes the rendered L3
bytes those sections compare against, not the code they describe. Expect
the one-time `stale-risk` batch, open each flagged section, confirm the
responsibility prose still holds, and amend by hand only where it does
not; there is nothing to fix in the code itself.

**A note on the `kb-summarize` wrapper's wording.** The `kb-summarize`
skill/command/prompt scaffolded on this repo is the identical resource a
`child` repo gets, and its own text says "after `kb ingest`" and
"`kb ingest` generated the scaffold." Both are literally true on a
`child` repo and **false here** — a `dev` repo never runs `kb ingest`
at all. On this repo, read every `kb ingest` mention in that wrapper as
`kb code-ingest --scaffold-svc`: that is the command that actually
created the scaffold `kb-summarize` fills, in the Onboarding step above.

## Full-auto mode (optional)

`kb auto on` lets this repo run on its own beside a BA repo, until every ticket on
the hub is done; `kb auto run` starts the loop in a terminal, or `/kb-auto run` from
your editor commits the switch, pushes it and starts the loop detached (log in
`.kb/auto/run.log`; `/kb-auto status` and `/kb-auto off` go with it). The agent approves
GATE 1 and GATE 2 after the independent review, merges with **admin rights** and
publishes with no human review, so read this before you turn it on.

**Security.** The deny list in `.claude/settings.json` is defence in depth only.
A ticket the agent misreads goes straight to `main` and the hub. The repo owner
must enable GitHub branch protection on `main` (block force pushes and deletions,
include administrators) and keep `kb-test.yml` (or the workflow with the
`kb-test` marker) as a required check (branch protection picks it by job
name: `test-<lang>`). Do **not** require approving reviews on `main`: the agent
cannot approve its own PR, and `kb pr merge --admin` is refused when
administrators are included. If you do require reviews, exclude administrators
from that rule and accept that the agent can then bypass it.

- After `kb auto on`, commit and push `.kb/config.yaml` and `.claude/settings.json` to the
  default branch; `kb auto run` refuses until you do (`kb publish` refuses a
  dirty `.kb/`, so no ticket would reach `done`).
- `intake:` must be set in `.kb/config.yaml`, and the hub's Registry page must
  have auto-merge **on** for this repo. The hub must be 1.29.0 or later (the
  runner polls Q&A over `GET /api/questions`).
- Export `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN` (as in `.mcp.json`) and log
  the `claude` CLI in with your subscription.
- First task: `/dev-test-workflow`, if no workflow runs the repo's tests. Then bugs
  first, then a `ready` ticket with no mission, then `ready` stories in mission order whose dependencies are `done`, one
  ticket at a time. A blocking business question makes the Dev wait for the BA's
  answer, then resume.
- `kb auto status` shows the current task and why it stopped; after two failed
  attempts it stops, and `kb auto run` resumes the same task once you fixed the
  cause. A tool outside the allowlist ends the task `failed command-denied`: add
  the command to `permissions.allow` in `.claude/settings.json` by hand. A blocked
  `kb` command that has a `strata-kb` MCP tool is not a failure: the skill counts
  it as no CLI and runs the MCP tool.
- Re-run `kb init --kind dev` to get the permission allowlist (with the commands
  of your `langs:`), the Auto mode sections and the `dev-test-workflow` skill. The
  full reference is the README's "Full-auto mode" section.

**On Claude Code cloud.** `/kb-auto run` works in a cloud session too. Set
`STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN` in the cloud environment; the hub must
be 1.30.0 or later. The loop reads the hub live through its API (nothing is copied),
`kb pr` replaces `gh pr` (REST; GraphQL is blocked), and the skill stays on the
session's `claude/...` branch: if the default branch's switch is off it opens an
`auto/switch` PR that flips only `auto.enabled`, waits for green checks, admin
squash-merges it after telling you, then starts the loop and keeps `kb auto wait`
armed. Keep the session open. Details and known limits: README, "On Claude Code cloud".

## Upgrading

Re-run `kb init --kind dev` to pick up new templates. This only ever
touches **scaffold files** — the skill/command/prompt wrappers,
`QUICKSTART-DEV.md`, `.github/workflows/kb-code.yml`, and the
`docs/impl/.gitkeep` marker — and only overwrites one when its content
differs from the new template; `.kb/config.yaml` and `.kb/index.yaml` are
never touched by a plain `kb init`, and `.claude/settings.json` is only merged
into (the usage hooks, the auto-mode permission lists and the test commands of
your languages are added; every entry of yours stays) — but
`--force` replaces all three outright: your hand-edited `.kb/config.yaml`
(`kind`, `repo_id`, `asset_store` included), `.kb/index.yaml`, and your whole
`.claude/settings.json` (hooks, permissions and model included), none of it
merged. Anything you authored under `docs/impl/` is not scaffolding:
`kb init` only moves an old flat `<id>-*` layout into `docs/impl/<id>/`
(the same as `kb impl tidy`) and never edits or overwrites it — commit the
renames.
**If you hand-edited a wrapper, `kb-code.yml`, or QUICKSTART-DEV.md, back it
up first: your edits are lost** — ingest configuration belongs in
`code_ingest:` in `.kb/config.yaml`, which `kb init` never overwrites.

## Token and cost measurement

`kb init` wrote `.claude/settings.json` with two hooks, `Stop` and
`SubagentStop`, that both call `kb usage ingest-transcript --hook-stdin` —
after each turn and after each subagent. It reads Claude
Code's own transcript — the numbers are the assistant's real usage, not an
estimate — and appends them to `.kb/usage/<ticket>.jsonl`, which is committed,
so a ticket's cost travels with the ticket. `.claude/settings.json` itself is
committed too — a teammate who pulls the repo without `kb` on their `PATH`
otherwise sees this hook fail on every turn.

It **adds about 0.6s per turn** (the cost of starting the `kb` CLI; parsing the
transcript itself is ~60ms), and the same again each time a subagent
finishes. That is the price of the data.

- `kb usage report` — writes `.kb/usage/report.html`; open it in a browser. Per
  ticket, per phase, per model, plus a `_unattributed` bucket.
- `kb usage report --ticket <id> --md` — a Markdown table.
- `kb usage ingest-transcript <path>` — backfill. Every transcript under
  `~/.claude/projects/<this-repo>/` can be ingested now; re-ingesting is safe,
  rows are de-duplicated by the transcript's own row ids. A main transcript
  brings its subagents with it; a `subagents/agent-*.jsonl` path finds its
  parent for attribution. A backfill holds nothing back, so run it only on a
  session that has ended — a call still streaming would be stored with a
  partial output count, and a stored row never changes.
- Subagent cost is recorded too, as `sidechain`. A `SubagentStop` hook ingests
  each subagent when it finishes, and the `Stop` hook sweeps any it missed.
  The report's "Main thread vs subagents" table shows where the tokens went.
  Claude Code writes a subagent's output count from the start of each
  streamed reply, never the final one, so subagent output tokens are a lower
  bound; input and cache tokens, most of the cost, are complete.
- `kb usage note --ticket <id> --phase <p> --model <m> --tokens-in N --tokens-out N --assistant <name>`
  — record a row by hand. Rows entered this way are estimates unless
  `--measured` is given. It always **appends** a new row, so it is never
  the way to fix one the automatic attribution got wrong — using it that way
  double-counts the tokens. The real repair is editing the stored row
  directly in `.kb/usage/<ticket>.jsonl`, then re-running `kb usage report`.
  If you already re-ingested the transcript, `--ticket` on
  `kb usage ingest-transcript` cannot help either: every row's uuid is
  already recorded, so there is nothing left for it to move.

A row is attributed to whichever ticket file the session mentioned most
recently (`docs/impl/<id>/{design,plan}.md`, `tickets/<id>.md`,
`missions/<id>.md`). Work done before any ticket file is mentioned lands in
`_unattributed.jsonl` — a large bucket there means attribution is missing
work, not that the work was free.

If `.kb/usage/*.jsonl` isn't growing, check `.kb/usage/ingest-errors.log` —
the hook fails silently by design (a `Stop` hook cannot block a turn from
ending), so this file is the only place a failure — a mistyped `kind:`, a
missing transcript, a corrupt ledger line — is ever visible.

**The `kb` on your `PATH` must be 0.19.0 or newer.** An older `kb` has no
`usage` command, so the hook exits 2 — and a `Stop` hook exiting 2 blocks the
turn from ending instead of failing quietly. Nothing reaches
`ingest-errors.log` either, because the failure happens before `kb usage` runs
at all. Run `kb --version` if a session starts refusing to finish, and upgrade
rather than deleting the hook. Subagent cost needs 1.9.0: an older `kb` reads a
`SubagentStop` payload as another `Stop` and records no subagent call.

**Re-ingesting is always safe**, because a call already in the ledger is
recognised and skipped. So if you ever have reason to distrust a ledger file,
the repair is to delete it and re-ingest the transcripts. Ingesting a main
transcript also ingests its subagents (`<session-id>/subagents/`), so the loop
below needs no second glob:

```bash
rm .kb/usage/<ticket>.jsonl
for f in ~/.claude/projects/<this-repo-slug>/*.jsonl; do
  kb usage ingest-transcript "$f"
done
```

If this repo already had a `.claude/settings.json`, `kb init` merged the hooks
into it and kept your own entries. To do the same by hand (for example when
`kb init` printed a note that the file is not valid JSON), add:

```json
{"hooks": {
  "Stop": [{"hooks": [
    {
      "type": "command",
      "command": "kb usage ingest-transcript --hook-stdin",
      "timeout": 30,
      "statusMessage": "Recording token usage..."
    }
  ]}],
  "SubagentStop": [{"hooks": [
    {
      "type": "command",
      "command": "kb usage ingest-transcript --hook-stdin",
      "timeout": 30,
      "statusMessage": "Recording token usage..."
    }
  ]}]
}}
```

`kb doctor` warns when `Stop` is there and `SubagentStop` is not. Until you add
it, the `Stop` sweep still records subagents, minus each one's last call (it
may still be streaming when `Stop` runs).

`--force` does not merge: it replaces the whole file with the scaffolded one,
so a repo with its own `.claude/settings.json` loses its entries. Leave
`--force` off to keep them.

`.kb/usage/report.html` is generated, not a record — the committed `.jsonl`
ledgers are. Regenerate it whenever you want with `kb usage report`; commit it
only if you want it browsable on GitHub.

Each append holds a lock on `.kb/usage/.lock`, so two hooks finishing at the
same moment cannot both store a call. The `.kb/usage/.gitignore` written next
to it keeps the lock out of git; commit that `.gitignore`.

Prices come from a table shipped with the package; override it per model in
`.kb/usage-prices.yaml`. The report prints the table's `effective_date` and
warns when it is over 90 days old. A model with no rates is reported as
`unpriced` with its token counts — never as free. That includes a model id
with no row of its own: add a row to `.kb/usage-prices.yaml`; it is never
priced as its family.

The report states the unattributed share of cost (of tokens when nothing is
priced). US-only inference (`inference_geo: us`, ×1.1) and web searches are
priced. A fast-mode call is priced at the standard rate and flagged: a total
that contains one is a lower bound. Any other geo, speed or service tier
(`batch`, `priority`) is priced as standard and flagged as an unrecognised
modifier.

## Model tiering

A recommendation, not a rule — nothing in `kb` enforces or measures compliance
with it. Some steps in this pipeline are judgment and some are mechanical;
running both on the same model pays the judgment price for the mechanical half.

| Tier | Steps |
| --- | --- |
| Strong | `dev-design`, `dev-plan`, the review subagents (A1–A5, including the `task-reviewer`), and assembling the PR body |
| Cheap | the lint/format fix loop, re-running the suite until green, ticking plan checkboxes, the self-review checkpoint inside each `dev-execute` task (it never satisfies A3), and the `kb svc note` calls at handover |

Which model belongs to which tier follows the price table in force —
`usage-prices.yaml` shipped with the package, overridable per model at
`.kb/usage-prices.yaml`. That table carries an `effective_date` and is the only
list of models in this project; this page deliberately keeps no second copy to
rot.

**Switch at phase boundaries, never inside a phase.** Changing model mid-session
discards the prompt cache and pays a fresh cache write at the new model:
`cache_write` costs 1.25x input at 5m and 2x at 1h, and every write measured
here so far has been 1h. Three cheap-model turns in the middle of a
strong-model session can cost **more** than not tiering at all.

Check the result instead of trusting it: `kb usage report` already breaks
spending down by model, and subagent cost is separated as `sidechain`, so a
tiering change shows up in the report the next ticket generates.

## CLI reference

- `kb init --kind dev` — scaffold or refresh this repo
- `kb resolve <file> [--hub <url>]` — resolve a ticket's `kb-context`
  block and report freshness (ok/stale/broken)
- `kb get <doc-id> <section> [--level l3]` — fetch one section at a given
  level, escalating past the summary when a value must be encoded exactly
- `kb query "<text>"` — hybrid search over the hub's summaries
- `kb code-ingest [--scaffold-svc]` — (re)generate `<repo_id>-code`; add
  `--scaffold-svc` to also upsert the `<repo_id>-svc` scaffold (seed/amend)
- `kb svc note <service> --ticket <id> --title "<title>" [--refs "..."]`
  — append this ticket to `<repo_id>-svc §hist.<service>` (run by
  `dev-handover`; idempotent per ticket)
- `kb plan waves <plan-file> [--json]` — dependency waves of a dev plan;
  exit 1 on a shared file without a dependency, a cycle, or a missing
  `Depends on:` line
- `kb doctor` — check `.kb/`, `<repo_id>-code` and what the hub has of
  this repo (published snapshot, hub lag, registry kind). With `kb
  mcp-setup` done it asks the hub over MCP and needs no hub clone;
  otherwise it clones the git hub from `hub:` / `--hub <url>`
- `kb auto on|off|status|run` — full-auto mode: the `auto:` switch in
  `.kb/config.yaml`, the runner's state, and the loop (`run [--once]`)
- `kb claim take|update|release|list` — ticket claims on the hub (see
  "Several Devs on one repo")
- `kb usage report [--ticket <id>] [--md]` — token and cost totals for this
  repo's tickets
- `kb usage ingest-transcript <path>` — backfill usage from a Claude Code
  transcript, its subagents included
- `kb mcp-setup [--hub-url URL] [--token T] [--no-verify]` — write the hub's
  HTTP MCP credentials into `.env` and verify them. Re-run it bare to verify
  again without retyping anything.
  (in your assistant: `/kb-mcp-setup`; prefer the hidden prompt or
  `STRATA_KB_HTTP_TOKEN` over `--token` — it puts the token in your shell
  history)
