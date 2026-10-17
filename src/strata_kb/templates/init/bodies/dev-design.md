
You are turning an approved ticket into a technical design for THIS
codebase. The ticket **is** the specification: the BA already wrote it,
cited it, and pinned it. This phase does not re-brainstorm the business
need — it decides **how to implement it here**: classify the work, then
design just enough to build it right.

*Counterpart in the superpowers plugin: `superpowers:brainstorming` — if it
is installed it is the newer source for the three-path method.*

**Hub access — MCP first.** Reach the hub through the `strata-kb` MCP
tools (`kb_search`, `kb_get_section`, `kb_resolve`, `kb_context_new`,
`kb_ticket_lint`, `kb_ticket_fetch`) whenever your client exposes them; fall back to the
matching CLI command only when it does not, or the MCP server cannot be
reached. `kb ticket fetch` runs as `kb_ticket_fetch`: save the text it returns
as `docs/impl/<ticket-id>/ticket.md`, the file the CLI would write. `kb svc note` and the cache-writing `kb resolve --status-only --cache` /
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

`<ticket-file>` may be `docs/impl/<ticket-id>/ticket.md`, the file
`kb_ticket_fetch` (CLI: `kb ticket fetch <ticket-id>`) fetched from the
hub.

## Path classification — say it out loud so the Dev can override it

- **spike** — a feasibility question the ticket itself raises; the
  output is an answer plus a recommendation, and anything built to get
  there is labelled throwaway.
- **bounded** — changes a flow that already exists in this repo; the
  design is a few sentences to a few short paragraphs.
- **architectural** — a new service, a new table, a new interface, or a
  change to how components fit; the design covers every item under
  *Design content* below.

Classification measures **the repo, not your familiarity** with it — no
existing flow to change means the ticket is not bounded. Between two
paths, **take the heavier one**. The ratchet is **one-way**: hidden
complexity found later upgrades the path, and you say so; nothing
downgrades mid-ticket.

Every path writes `docs/impl/<ticket-id>/design.md` — one paragraph on
the bounded path is not ceremony, it is the resume point the orchestrator
reads. The file opens with two header lines under its title:
`path: <spike|bounded|architectural>` and `status: draft`. A spike's
body is the question, what was tried, the recommendation, and the
sentence "anything built for this is throwaway"; a spike ends here — no
plan, no execute — and its next step is `dev-handover`, which puts the
recommendation under `## Notes`.

## Design content

Cover modules touched, interfaces added or changed, data changes, and the
placeholder resolutions carried over from the orchestrator's Placeholders
step. Quote every standard-derived value verbatim with its `doc-id
§section`. Any AC that cannot be implemented as written becomes
`OPEN(BA)`, raised as a `business` question (below) — reinterpreting an AC
is forbidden, and so is deciding the ambiguity yourself.

## Questions the design cannot settle

The `design-author` subagent never calls the hub, and it cannot dispatch
subagents. What it could not decide goes into a `## Questions raised`
section of its draft: one item per question, tagged `business` or
`technical`, each with `blocks: <AC ids|none>` — the ACs the answer would
change. You, the orchestrator, handle every raised question; the author
does not:

- **technical** → dispatch `dev-sa` as a subagent (fresh context; the
  question, `docs/impl/<ticket-id>/ticket.md` and the draft passed as file
  paths; model named — the standard tier, as for authors), write its
  decision into the draft's `## Technical decisions` as
  `- SA-<n>: <decision> — why — evidence`, then re-dispatch the author (or
  the fix round) with those decisions.
- **business** → call `kb_question_ask(ticket, question, asked_by, context,
  blocks)` (`asked_by` = `git config user.name`, and when that is empty ask
  the Dev for a name once and reuse it; `context` = where in the
  design it came up; `blocks` = the AC ids, or empty) and move the item to
  the draft's `## Open questions` as
  `- Q<id> — <question> — blocks: <AC ids|none>`. When `dev-sa` returns
  `business question:`, treat the item as business and handle it the same
  way.

**Preservation rule.** Remove each handled item from `## Questions raised`.
Every author and fix round keeps `## Technical decisions` and
`## Open questions` verbatim and never re-raises a question already listed
there. Before `kb_question_ask`, skip any item already in
`## Open questions`.

`kb_question_ask` has no CLI twin and works only against the shared hub
server. Any other MCP target answers `Q&A needs the shared hub server —
point MCP at it (kb mcp-setup)`; the hub can also answer
`hub unreachable — queries need the hub federation` (the `HUB_DOWN` text) or
`Q&A store error — see hub log`; treat each as Q&A unavailable, and so is a
client that does not expose the tool. When Q&A is unavailable, a `business`
item with `blocks: none` falls back to the pre-1.27 behaviour —
`OPEN(BA)` in the draft and a note in the PR description — and the work
continues; only a blocking one stops. For that one, stop and tell the Dev;
this is a stop, never "no questions". The hub link for the Dev to share with the BA is
`STRATA_KB_HUB_URL` (from the process env, or the `.env` that `kb mcp-setup`
wrote; read only that line and never show `STRATA_KB_HTTP_TOKEN`) followed
by the path `kb_question_ask` returned; if it is unset, give the path only.

**Gate.** A blocking open BA question stops the gate: a design whose
`## Open questions` holds a question line without `— answered rev N`
whose `blocks:` names an AC cannot pass GATE 1. Stop and give the Dev the
hub Q&A link. A non-blocking open BA question does not stop the gate
(`blocks: none`); it stays listed, and the A1 reviewer reads it as a known
open item, not a defect (the rubric's Pre-code axis says so). The answer is
picked up by `dev-implement-ticket` on its next entry, which marks a newly
answered line `— answered rev N — re-draft`: once per `Q<id>` line carrying
`— re-draft`, re-dispatch the `design-author` with the re-fetched ticket, then strip
that suffix (the line keeps `— answered rev N`). A line with
`— answered rev N` and no `— re-draft` is already handled.

## A1 — independent design review (before GATE 1)

Write the design in its own context: dispatch a `design-author` subagent with
the resolved context cache path, the ticket's acceptance criteria, the
conventions paths, and this phase's own authoring rules above — what the
design must cover, how placeholders and standard values are cited, and the
author self-check below —
and the Questions rule and preservation rule above: it lists what it could
not decide under `## Questions raised`, tags each item `business` or
`technical` with `blocks: <AC ids|none>`, never calls the hub or asks the BA
itself, and keeps `## Technical decisions` and `## Open questions` verbatim —
and let it write `docs/impl/<ticket-id>/design.md` with `status: draft`.
After each author or fix round returns, handle its `## Questions raised`
before the reviewer is dispatched. You orchestrate; you do not draft and
then judge your own draft.

**Author self-check.** Before any reviewer sees a draft, the author — and
every fix round after it — runs this checklist and fixes what it finds: every
AC is answered by a named design section; every placeholder and standard
value cites a section of the resolved context cache; every precondition an
AC's test needs is set up by something the design names; every
cross-reference points at a section that exists; every block a formatter
re-wrapped is re-read. It returns the checklist result with the draft.

That design is a draft until a reviewer that never saw it being written
says otherwise. Dispatch a `design-reviewer` subagent — or slice reviewers, as
**Size check** below decides — and hand each exactly these things: the path
`docs/impl/<ticket-id>/design.md`, the resolved context cache path, the
ticket's
acceptance criteria, and the `## Pre-code axes` of `docs/pr-review-rubric.md`
plus `docs/pr-review-rubric.local.md`. Not your reasoning, not this
conversation.

**Round 1 is exhaustive.** The reviewer writes its report to
`docs/impl/<ticket-id>/review/a1-r<n>.md` (`mkdir -p` the folder first):
pass/fail per axis; a coverage matrix — every AC against the design section
that answers it, and every Pre-code axis item not marked (A2) against every
design section, each cell PASS, FAIL or not-checked; and a gap list in which
every gap names the section it lives in,
its severity, a defect class (a short name such as `uncited literal` or
`precondition not set up`) and a proposed fix. A not-checked cell sends a
fresh reviewer back to exactly those cells, appending to the same report,
before anything is fixed: round 1 finds
every gap, not the first few.

**Size check.** Before round 1, count the ticket's ACs and the design's
lines. Up to 8 ACs and 600 lines, one `design-reviewer` reviews the whole
design. Above either, split the review into slices of at most 4 ACs, each
with the design sections that answer them (every section in at least one
slice), and dispatch one `design-reviewer` per slice in parallel, each handed
the inputs above plus its slice's ACs and sections and filling the matrix for
those only (report `a1-r<n>-<slice>.md`). Then
dispatch one `design-lead-reviewer` with a fresh context, handing it the
design, the ticket's acceptance criteria, the context cache path and every
slice report. It writes the consolidated report `a1-r<n>.md`:

- what no slice can see — components, data and interfaces shared across
  slices, and every AC traced to a section across the whole design;
- every slice finding re-checked against the design text: a finding that
  does not hold is dropped with the reason, duplicates are merged, and one
  defect class gets one severity across slices;
- drift — scope no AC asks for, an AC weakened or left out, a standard value
  not taken from the context cache — in the design or in a proposed fix;
- the slices' coverage matrices together cover every cell.

A design that needed slices adds a NOTE suggesting the BA split tickets of
this size.

**Class-wide fix.** Copy the design to
`docs/impl/<ticket-id>/review/design-r<n>.md`, then apply BLOCKER and
SUGGESTED gaps through a fix subagent. For every gap it fixes the cited
instance, sweeps the whole design for the same defect class, and writes each
further instance it fixed to `review/a1-r<n>-sweep.md`; then it re-runs the
author self-check. The fix
subagent gets the same Questions rule and preservation rule as the
author.

**Verification rounds.** Round 2 and later are not a fresh full review. A
`design-reviewer` with a fresh context gets the round-1 inputs, the previous
gap list with its
classes, the fix subagent's sweep list, and `diff -u` of the copy taken before the
fix against the design, written to `review/a1-r<n>.diff`. It checks that every
previous gap is closed, spot-checks instances of each class outside the
sweep list, and checks the diff for regressions; it still reports any other
defect it sees. A full review runs again only for not-checked cells or a
slice the diff mostly rewrote.

**Stop.** Record every round in the design file's `## Review record` table,
creating it below the design body on round 1:

    | Date | Round | Verdict | Reviewer | Coverage | Classes | Open gaps |
    |---|---|---|---|---|---|---|
    | <date> | 1 | BLOCKER x1 | design-reviewer | 38/40 | precondition not set up | AC3 not addressed |

Coverage is checked cells over all cells. A gap a verification round finds
outside the diff is recorded as `round-1 coverage miss`. The target is one
review round plus one verification round. When a round's BLOCKER plus
SUGGESTED count is not lower than the round before, stop at once and hand the
Dev the trend and the open classes instead of spending the rounds left;
otherwise the cap of 3 rounds holds.

GATE 1 is offered only after A1 comes back clean — clean means no BLOCKER and
no SUGGESTED gap left open; NOTE and NITS are recorded, not fixed.

## GATE 1 — Dev approval before any plan is written

The Dev approves the design before the plan is started. Presenting the
design and starting the plan in the same turn is skipping the gate.
When the Dev approves, flip the header to `status: approved` before
anything else — `dev-plan` refuses a `draft` design. A file's existence
is not approval; its `status:` line is. A spike's design is flipped to
`status: approved` here too — approving the recommendation, not a plan —
so `design ✅` reads correctly if the ticket is re-opened.

## Review dispatch contract (every review in this flow)

- The author and the reviewer are NEVER the same subagent. A self-review
  never satisfies a review step.
- A reviewer starts from a fresh context and gets no conversation history —
  hand it only the paths it must read and the constraints that bind it.
- Artefacts move as FILE PATHS, never pasted into the dispatch prompt: the
  draft, the diff, the report. Whatever you paste stays in your context for
  the rest of the session.
- Never pre-judge: a dispatch prompt never tells a reviewer what not to flag
  and never rates a finding's severity for it.
- Name the model on every dispatch — a standard model for authors and
  implementers, the most capable one available for reviewers. Never inherit
  the session default silently.
- Findings → fix subagent → re-review, at most 3 rounds. A BLOCKER or SUGGESTED still
  standing after round 3 stops the flow and goes to the Dev.
- A finding that contradicts the approved design or plan is never auto-fixed:
  show the finding beside the text that mandates it and let the Dev choose.
- Criteria come from the source that matches the review: the rubric's
  `## Pre-code axes` for A1 and A2, its `## Merge-risk axes` for A5, and
  `docs/conventions/<lang>.md` — plus the five pack files it links under
  `docs/conventions/<lang>/` and `docs/conventions/common/` — for A3 and A4.
  Each one's own `.local.md` override wins over its base file. Severity is
  always BLOCKER / SUGGESTED / NOTE / NITS.
- Where the runtime cannot dispatch subagents, run the review as its own pass
  that reads ONLY the paths it was handed and reuses nothing it remembers from
  drafting, and write up its findings the same way — then STOP and hand the
  result to the Dev. The phase does not advance on a fallback pass: one
  context reviewing itself is a weaker substitute, not an equivalent — only
  the Dev's explicit go-ahead advances it, recorded in the tick itself, e.g.
  `Review: ✅ r<n> (fallback, Dev-approved)`.

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

For `dev-design`, option 1 below is always `/dev-plan <ticket-id>` once
GATE 1 passes — unless `path: spike`, where option 1 is `/dev-handover
<ticket-id>`; a blocker takes its place instead.

`BA-Q:` comes from the local `## Open questions` lines of `design.md` /
`plan.md`, not from the hub: `none` when no `Q<id>` line lacks
`— answered rev N`, otherwise `open Q<ids>`; `dev-implement-ticket` refines
open and waiting from `kb_question_list`. A mixed state is written
`open Q1; waiting Q2`, and `unknown (Q&A unavailable)` is
`dev-implement-ticket`'s when the Q&A tools are refused.

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

`/dev-implement-ticket <us-id>` runs this skill as phase 1, on the ticket branch it created. Nobody answers questions during the run: a step above that says "the Dev approves", "tell the Dev" or "let the Dev choose" is yours to carry out, under the rules below. Every step and every hard rule not named here stays as written.

**Decisions.** Write each decision as one `**Auto decision:**` line: what you checked, the options, the choice, and why. Append it to `docs/impl/<ticket-id>/auto-decisions.md` (create the file with the heading `# Auto decisions` when it is missing). `dev-handover` copies the lines into the PR's `## Notes`.

**A denied command.** A command the permission system denies ends the run: report `command-denied <command>` to the orchestrator, which ends `AUTO-RESULT: failed command-denied <command>`. Never work around a denial: no other shell, no edit of the settings. The one exception is a denied `kb` command that has a `strata-kb` MCP tool: it counts as no CLI: run the MCP tool and carry on.

- **GATE 1 — Dev approval before any plan is written** → the A1 review, run by a `design-reviewer` subagent in a fresh context, is the approval, and you flip the header yourself. When A1 comes back clean (no BLOCKER and no SUGGESTED gap open), set `status: approved` at once, log an Auto decision line (the rounds, the verdict counts, what the reviewer read), and carry on to `dev-plan` in the same turn; the "same turn" ban belongs to the Dev. A spike's design is flipped the same way. Otherwise send the gaps through the fix subagent and re-review, at most 2 fix rounds (not 3). A design that is still not clean after that stays `draft`: end `AUTO-RESULT: failed design-review`, and name the open classes in the reply.
- **Questions: "ask the Dev for a name once"** → `asked_by` is `kb-auto`. Never ask.
- **Gate: a blocking open BA question — "stop and tell the Dev", and give the Dev the hub Q&A link** → stop without flipping the status. Report the blocking `Q<id>` lines to `dev-implement-ticket`, which ends `AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]`. When Q&A is unavailable and the item blocks an AC, report `failed qa-unavailable`. A business question with `blocks: none` still falls back to `OPEN(BA)` and a PR note, and the work continues.
- **Stop rule: "stop at once and hand the Dev the trend"** → a round whose BLOCKER plus SUGGESTED count is not lower than the round before is treated as not clean: stop spending rounds and end `AUTO-RESULT: failed design-review`, with the trend and the open classes in the reply.
- **Review contract: "round 3 stops the flow and goes to the Dev"** → the cap is 2 fix rounds here, and what is left ends `AUTO-RESULT: failed design-review`.
- **Review contract: a finding that contradicts the approved design or plan — "let the Dev choose"** → choose the reading closer to the ticket's ACs and the cited standards, fix on that reading, and log both texts and the choice in an Auto decision line.
- **Review contract: "STOP and hand the result to the Dev" on a fallback pass, advanced only by "the Dev's explicit go-ahead"** → where the runtime cannot dispatch subagents, the separate pass stands in. Record the tick as `Review: ✅ r<n> (fallback, auto)` and go on.

### Result line

You run as a phase of `/dev-implement-ticket`, which ends the task: report your outcome to it in plain words, with the reason when you stopped. When the runner started you directly as `/dev-design <us-id>`, end the reply with exactly one line, and make it the last line. Nothing follows it: no code fence, no markdown, no closing remark. The `## Next step` block comes first. It has one of three forms:

- `AUTO-RESULT: done` — the design is `status: approved`. Write no text after `done`; always give a reason after `failed`.
- `AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]` — a BA question blocks an AC; the runner re-runs the task once the questions are answered.
- `AUTO-RESULT: failed <reason>` — anything else: `design-review`, or `qa-unavailable`. The reason goes on the same line.
