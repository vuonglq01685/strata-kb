
**Hub access — MCP first.** Reach the hub through the `strata-kb` MCP
tools (`kb_search`, `kb_get_section`, `kb_resolve`, `kb_context_new`,
`kb_ticket_lint`, `kb_ticket_check`,
`kb_mission_lint`, `kb_ticket_stale`) whenever your client exposes them; fall back to the
matching CLI command only when it does not, or the MCP server cannot be
reached. Every `kb mission lint` below runs as the MCP tool `kb_mission_lint` (the
mission's text, its file name without `.md` as `mission_id`; it skips the
ticket-coverage warning, which only the CLI reads from `tickets/`), every `kb ticket stale` as `kb_ticket_stale` (the file's text and its
repo-relative path, e.g. `missions/<M-id>.md`),
every `kb ticket check` as `kb_ticket_check` (the ticket's text; the
local parent mission file's text, when there is one, as
`mission_markdown`); the CLI is the
fallback. `kb publish` has no MCP tool and stays CLI. `kb mission next` stays CLI too:
it reads this repo's unpublished `missions/` and `tickets/`, which
`kb_mission_next` (the published plan only) cannot see.

## Workflow

1. **Intake** — collect the business need at epic level: what capability,
   for whom, why it matters, and how success is measured. Agree the
   mission id with the BA: `M-<slug>`, where `<slug>` is lowercase
   kebab-case. The filename stem must equal the id. Ask for target tags
   (e.g. `#arinc424 #airspace`) or an explicit doc-id. Ask, don't guess.
   Ask also for the doc-id of the architecture document on the hub, when
   one exists — the SA cites it for every service the mission will
   create. Never ask whether the repo is greenfield; the SA sees that in
   `-code`.
2. **Ground** — use the MCP tool `kb_search` when it is available;
   otherwise fall back to `kb query "<text>" --tags <tags> --kind kb --kind dev`
   (CLI). Pass `kinds=["kb","dev"]` to `kb_search`: you read knowledge and
   code, never other tickets.
   **Budget the search:** 500–800 tokens for broad discovery — enough
   for the citation plus a summary to choose from; `kb_get_section`
   only for a section already chosen; L3 only for a value that will be
   encoded in code or a test. Present **ALL** returned candidates with their
   citations — never silently drop one. When the ambiguity note fires
   (two close-scoring hits), the BA MUST choose — never auto-pick.
   A hit tagged `code` (`<repo>-code` / `<repo>-svc`) is not a candidate for
   you: note it in the handover and leave it to `/sa-ticket-ground`.
3. **Draft** — start from `docs/missions/TEMPLATE.md` in the repo (the
   file `kb init --kind ba` scaffolds) and fill it in: Summary,
   Business goal, Scope, System context (C4 L1), Containers (C4 L2),
   Technology decisions, Non-functional requirements,
   Constraints & assumptions, US backlog, Sequencing, Open questions,
   KB context, Definition of Ready. Every
   `%%TODO: verify against codebase%%` you place in a C4 diagram gets
   one owned row in `## Technology decisions` at the same moment —
   never leave a placeholder without an owner.
   Keep the template's `> Mission: M-<slug>` id line and mermaid fences —
   do not recreate the document from scratch. Draw L1 and L2 from domain KB
   content plus what the BA states. Where a diagram needs code-level detail
   (service names, DB tables, …), mark it `%%TODO: verify against
   codebase%%` — never invent it, never look it up yourself. Add the
   optional `## Components (C4 L3)` section ONLY when the BA supplies real
   component detail.
   `## Services & order` is SA-owned: leave it exactly as the template
   ships it — `/sa-ticket-ground --mission` fills it after the backlog is
   confirmed.
4. **Split** — propose the US backlog table with the header
   `| US ID | Title |` exactly (the lint parser matches this string, not
   a paraphrase) and one row per story below it, ids numbered
   `<mission-id>-US1`, `-US2`, … — numbers start at 1 and are never
   zero-padded (`-US01` fails lint's id pattern). The BA edits and
   confirms the split. Numbering gaps are fine if a story is dropped —
   never renumber, as ticket filenames may already use those ids. Each
   story's eventual ticket is saved as `tickets/<mission-id>/<us-id>.md`
   (e.g. `tickets/<mission-id>/<mission-id>-US1.md`) — that exact path
   is what the coverage check (and `kb ticket lint`'s back-link check)
   looks for; coverage also reads the flat `tickets/<us-id>.md`, but a
   differently-named file will never show as draft or ready.

   **Story-size heuristic** — a story must be split further if it hits
   ANY of these:
   - more than 8 coded-value variants where each needs its own
     algorithm or business rule
   - touches more than 6 source entities (tables, APIs, documents)
   - mixes data construction/transformation with presentation for a
     complex domain
   - contains both the happy path and multiple heavy exception branches

   When a threshold is hit, present the BA the split alternative with
   the reasoning — never just a single title row. After the BA confirms
   the backlog, fill `## Sequencing` (US ID / Depends on / Size /
   Notes) — Devs never infer ordering.

   **Greenfield:** when the BA says the repo is a skeleton, or step 5
   comes back with no existing `svc.*` (revisit the split then), the
   first story is the **foundation slice** — what the architecture
   document says must exist before any feature story (services,
   database, API skeleton), cited `[<arch-doc> §<section>]`, outcome-level ACs,
   still at most 10; every other story `Depends on` it in `## Sequencing`.
   The story-size heuristic applies: the foundation may be two stories.
   `Depends on` may name a story of another mission (`M-<other>-US<n>`)
   — that is how cross-mission order is written.
5. **Ground services** — once the BA has confirmed the backlog and
   `## Sequencing` is filled, invoke `sa-ticket-ground --mission` on the
   draft. It fills the SA-owned `## Services & order` section from the
   hub's `<repo>-code` document and appends a `## Technology decisions`
   row (status `OPEN`, a human owner) for every service the mission will
   create, referenced from the service table as `[NEW: D<n>]`. Its gate
   then reports FAIL on exactly those rows until a human flips them to
   `DECIDED` — that is the expected result, not a defect; flipping is
   the BA's call, in step 5b.
   `kb mission lint` already warns on an ownerless D-row — that warning
   is the BA's to close, never the SA's.
5b. **Decide** — present the whole `## Technology decisions` table to
   the BA once. The BA flips to `DECIDED` the rows whose citation they
   confirm; a row with no citation keeps `OPEN` and a named owner. You
   never flip a status. A story whose blocking rows are all `DECIDED`
   and whose dependencies are done is what `kb mission next` reports as
   `ready` — the Definition of Ready's decided-rows item is this step.
6. **Pin** — once the BA confirms which sections actually apply, call the
   MCP tool `kb_context_new` when available; otherwise fall back to
   `kb context new --refs "<refs>"` (CLI), passing exactly those
   confirmed refs. Include every architecture section a
   `## Technology decisions` row or the foundation-slice story cites — a
   bracketed citation the block does not pin is a lint error. Embed the
   block it returns verbatim under
   `## KB context`. **Tags are NOT yours to set:** the engine derives
   them from the pinned sections' own tags. Leave the tool's `tags`
   argument unset and the CLI's `--tags` off — a tag passed by hand is
   validated against the hub vocabulary and an unknown one is an error.
   The tags the BA gave at intake are search keywords for
   `kb query --tags`, nothing more.
7. **Lint** — run `kb_mission_lint` (CLI: `kb mission lint <file>`)
   against the draft. Fix every
   error and re-run until it reports `DoR: PASS`. A coverage warning of
   `0/N US drafted` is EXPECTED at creation time — the tickets do not
   exist yet. Report remaining warnings to the BA; they are the BA's
   judgment call.
8. **Maturity review** — once lint reports `DoR: PASS`, read
   `docs/review-rubric.md`, then `docs/review-rubric.local.md` if it
   exists — the local file overrides the base one (same for
   `docs/ac-quality.md` and `docs/ac-quality.local.md`). Run TWO
   independent reviews of the draft — when your runtime can dispatch
   subagents, run them as TWO subagents IN PARALLEL; otherwise run TWO
   sequential passes, one role per pass. Never blend the two
   perspectives in one pass:
   - *Business-coverage reviewer* — acts as PO/stakeholder; scores the
     "Business coverage" axis of the rubric.
   - *Dev-implementability reviewer* — acts as the tech lead who will
     slice this mission into tickets; scores the "Dev implementability"
     axis. Give it `## Services & order` as input — the service order is
     what makes the backlog sliceable.
   Each reviewer returns: a 1–5 score (the LOWEST maturity level fully
   satisfied — never averaged), the checklist with pass/fail per item,
   and a gap list where every gap names the section it lives in and a
   proposed fix.

   Apply the fixes, re-run `kb_mission_lint`, then review again — at
   most 3 rounds total; stop early when both axes score ≥ 4.

   **Rounds 2 and 3 are not a re-read.** When your runtime can
   dispatch subagents, dispatch ONE `gap-verifier` subagent; otherwise
   run this pass yourself, acting as `gap-verifier`. Either way, it
   reads only three things: the gaps still open, the current text of
   the sections that changed in response, and the rubric items those
   gaps map to — never the whole draft. It returns pass/fail per gap
   with a one-line reason. Do **not** re-read the rest of the draft
   and do **not** re-score an axis in this pass: an axis's score
   rises only when every gap of that axis passes — re-derive it as
   the LOWEST maturity level fully satisfied, using round 1's
   checklist updated with the verifier's pass/fail; otherwise carry
   the previous round's score forward unchanged.

   A gap you cannot close yourself (a missing business decision,
   missing input) is NEVER invented: write `OPEN(<owner>)` at the spot
   and add an `## Open questions` row.

   Record the result in `## Review record`: on the first round replace
   the `Not yet reviewed.` placeholder; append one table row per round
   (`| Date | Round | Business | Dev | Reviewer |`) — the `Reviewer`
   cell reads `gap-verifier` for rounds 2 and 3 — and list the
   still-open gaps on the `Open gaps:` line. Report both scores and the
   remaining owned gaps to the BA in the handover summary.
9. **Review → save** — write the final Markdown to
   `missions/<mission-id>.md`. Hand it to the BA to review and commit.

## Amend mode — `--amend <M-id>`

`/ba-mission-plan --amend M-<slug>` changes a mission that already exists
(committed, perhaps already published). It does NOT run the workflow above
from Intake: the mission keeps its id and filename, and every change is
recorded in `## Change log`. A new mission is never created by `--amend`.

1. **Read** `missions/<M-id>.md`, then run `kb_ticket_stale` on it (CLI:
   `kb ticket stale --md missions/<M-id>.md`) and read the findings for it (kind: the
   `Kind` column, `kb-context` or `architecture`). Run `kb mission next` as well, to see
   which stories are `done`.
2. **Ask** the BA for the trigger(s) — one or more of `kb-context`,
   `architecture`, `scope`, `delivery` — and what changed. The drift
   findings pre-fill the answer; ask, don't guess.
3. **`kb-context` trigger** — re-pin `## KB context` with the MCP tool
   `kb_context_new` when available, otherwise `kb context new --refs
   "<refs>"` (CLI), with the FULL ref list (kept + moved + new) — the tool
   renders one block with one `version:`, so a partial list drops the
   unchanged refs — and replace the whole block. Only the moved or new refs
   need the BA's re-confirmation, and only the claims citing them need
   re-checking. The `tags`
   rule of step 6 still holds: never pass tags.
4. **`architecture` trigger only** — hand off to `sa-ticket-ground
   --mission` on the mission. It refreshes `## Services & order` and the
   `Grounded on:` revision, then runs `kb ticket check`. For any other
   trigger, skip the SA and `kb ticket check`: a mission's own stories
   change the svc.* sections it cites while it is being delivered. You
   still never read `<repo>-code` or `<repo>-svc` yourself.
5. **Apply the change rules** below.
6. **Bump `> Revision:` and append the change-log row** `| Rev | Date |
   Trigger | What changed | Affected | Review |`. In `Affected` write FULL
   story ids (`M-<slug>-US<n>`), comma-separated, or `-` — a bare `US<n>`
   is not matched by `kb mission next`, so a ticket would never be flagged.
7. **Lint** — `kb_mission_lint` (CLI: `kb mission lint <file>`) until it
   reports `DoR: PASS`.
8. **Maturity review of the changed sections only** — one round, the same
   rubric and the same two perspectives as step 8 of the workflow. Write
   the scores into the new row's `Review` cell (e.g. `B4 D4 (agent)`) —
   never into `## Review record`.
9. **Hand the diff to the BA.** The agent ticks only the DoR boxes the
   evidence map proves; it never commits or pushes. The BA's next `kb publish` ships the amended mission.

Change rules:

- **Done stories are frozen.** A story `kb mission next` reports `done`
  keeps its backlog row unchanged. New or changed work becomes a new row
  with the next free US number — numbers are never reused or renumbered.
- Stories not yet done may be edited; list each in the row's `Affected`.
- **A `DECIDED` row is superseded, never edited.** Add a row `D<n>` with
  `Supersedes D<k>` in its Decision cell, and set `D<k>`'s status to
  `SUPERSEDED`. Later `[NEW: D<k>]` citations must name `D<n>`. If any
  `[NEW: D<k>]` (this mission's `## Services & order`, or a ticket) still
  cites the superseded row, the amendment MUST include the `architecture`
  trigger so `sa-ticket-ground` re-points it to `D<n>`: list the citing
  files to the BA (`grep -rn "D<k>" missions tickets`).
- Tickets already written against this mission keep their `@ rev` pin; the
  BA re-authors a flagged story with `/ba-ticket-author --amend`.

## Hard rules

- Citations are mandatory for every claim that touches a standard — no
  citation, no claim.
- Present ALL `kb_search` candidates and let the BA choose; this is
  mandatory when the ambiguity note fires — never auto-pick.
- Never fabricate codes, record/field names, numeric values, service
  names, or table names — the same verbatim-preservation rules as
  `kb-summarize` apply. Unsure → `%%TODO: verify against codebase%%`.
- **Code-level detail is not yours to ground.** Write
  `%%TODO: verify against codebase%%` where a service or container name
  is needed, add the owned `## Technology decisions` row, and let step 5
  (Ground services) invoke `/sa-ticket-ground --mission` once the BA
  confirms the backlog — it fills the SA-owned `## Services & order`
  section from the hub's `<repo>-code` document (`svc.*` and its
  `Depends on` cell) and the architecture document, and appends an
  `OPEN` decision row for every service the mission will create. Never
  read `<repo>-code` or `<repo>-svc` yourself.
- **The mission lint failing to RUN is not a PASS.** If neither
  `kb_mission_lint` nor the `kb` command can run, tell the BA to connect
  the `strata-kb` MCP server (`kb mcp-setup`) or install `strata-kb` —
  never skip the lint step, and never hand over a mission you could not
  lint.
- Lint must report `DoR: PASS` before handover; report remaining warnings
  to the BA — do not hand over a failing mission silently.
- **Never auto-generate ticket files from the backlog.** Each story goes
  through `/ba-ticket-author` with its own grounding pass — a backlog row
  is a title, not a drafted ticket.
- Close the `## Definition of Ready` boxes a tool proves, yourself, just
  before handover and on the final text: tick a box only when its
  evidence below holds after your last edit — a tool run in this session,
  or the count or tick check the row names. Never tick a box on your own
  judgement, never tick one the map
  leaves to the BA, and never tick an open-question checkbox — its owner
  closes it. List each box you ticked, with its evidence, in the handover.
  The mission DoR does not gate publishing; it tells the team how ready
  the mission is.

  | DoR box | Tick it when |
  |---|---|
  | Business goal, scope, L1 + L2 diagrams, backlog present | `kb_mission_lint` (CLI `kb mission lint`) reports `DoR: PASS` |
  | Every citation resolves at the pinned version | that PASS ran against the hub, not with the hub check skipped |
  | Backlog reviewed with the team; no known missing slice | never — the BA's judgement |
  | Every `%%TODO%%` has an owned row in Technology decisions | lint PASS with no placeholder or ownerless-decision warning |
  | Sequencing covers the whole backlog | lint PASS with no sequencing-coverage warning |
  | Every D-row blocking a story with no dependency is DECIDED | `kb_mission_next` (CLI `kb mission next`) shows each such story `to-draft`, not `blocked` by a D-row |
  | Architecture-impacting open questions closed | every `## Open questions` row with `impact: architecture` is ticked |
- The agent's output is a draft; the BA publishes it. Never push to Jira.
- English template headings are never localized; write the mission body in
  the BA's working language.
- Every C4 `%%TODO: verify against codebase%%` generates one owned row
  in `## Technology decisions`. A mission with an ownerless placeholder
  is not ready, even when lint passes.
- A mission touching large data volumes, concurrency, or timing
  constraints carries at least one quantified row in
  `## Non-functional requirements`.
- Fill `## Sequencing` once the BA confirms the backlog — Devs never
  infer execution order.
- An open question that changes architecture (infrastructure,
  deployment scope, data model) is flagged in `## Open questions` as a
  prerequisite of the foundational stories and closed before they
  start.
- Never alter the `| US ID | Title |` backlog header in any way — lint
  matches the string verbatim; extra columns FAIL. Dependency and size
  live in `## Sequencing`.
- The maturity review never edits business intent on its own authority —
  it closes gaps with facts already confirmed by the BA or the KB, and
  everything else becomes an owned `OPEN(...)`. Scores below 4 after
  3 rounds are reported, not hidden.
- A `[NEW: D<n>]` proposal that cites an architecture section on the
  hub is a recorded decision: the BA flips it at mission time, in step
  5b, not ticket by ticket. A proposal without a citation stays `OPEN`
  with a human owner.

## Auto mode

Run `kb auto status --json`. When `enabled` is false, this section does not apply. When true, the rules below replace the human gates named in them.

The runner starts this skill only as `/ba-mission-plan --amend <mission-id>`, for a mission that holds a story back: an `OPEN` row in `## Technology decisions`, or an unticked row in `## Open questions` with `blocks:`. It never starts a new mission. Nobody answers questions during the run: a step above that says "ask the BA" or "hand it to the BA" is yours to carry out, under the rules below. Every step and every hard rule not named here stays as written.

**Decisions.** Write each decision as one `**Auto decision:**` line: what you checked, the options, the choice, and why. Put the line directly under the `## Change log` table, outside any table row, so the one-row-per-revision check is unaffected. Each D-row and each open question you settle gets its own line.

**Blockers to settle.** Run `kb mission next --json` and take the blockers named in the `reasons` of this mission's stories (`D<n> OPEN`, `Q<n> open`). Settle those rows and no others.

**Already finished.** The runner re-runs a task after a crash, so check first: `kb pr find --head auto/<mission-id> --state all --json`. When no blocker is named and a merged PR exists (`kb pr find --state merged --head auto/<mission-id>`), the work is already finished: change nothing and end `AUTO-RESULT: done`. With no blocker and no such PR ever, end `AUTO-RESULT: failed no-blocker <mission-id>`. An open PR means a crashed run: `git fetch origin && git switch auto/<mission-id>` and continue at the CI step of the branch rule.

- **Amend step 2, "Ask the BA for the trigger(s)"** → the trigger comes from the runner's task. Settling a blocker is trigger `scope`, with `Affected` listing the full ids of the stories it unblocks. When the settlement supersedes a `DECIDED` row, the trigger is `architecture`, as the change rules require. Add `kb-context` when the `kb_ticket_stale` findings call for it.
- **Ground: "the BA MUST choose — never auto-pick"** (also the Hard rule "let the BA choose") → pick the best-matching refs yourself by the ref rule in ba-ticket-author's Auto mode, and write the choice and the reason in an Auto decision line.
- **Step 5b, a `Technology decisions` row stays `OPEN` — "You never flip a status"** → decide the row, then flip it to `DECIDED`. Read the row, the architecture section it cites (`kb_get_section`) and the evidence `kb_search` finds (`kinds=["kb","dev"]`). List the options: those the row names, or those the architecture document allows. Pick the one the evidence supports best; when the evidence does not separate them, pick the smallest and most reversible. Give a fresh-context reviewer (a subagent when your runtime can dispatch one, otherwise a separate pass that reads nothing but these inputs) the row, the options, the evidence and your pick; it answers agree or object with a reason. On an objection, decide again once, then go with that decision. Write the decision into the row's Decision cell with its citation, set the status to `DECIDED`, keep the owner, and log the Auto decision line.
- **Open question with `blocks:` — "never tick an open-question checkbox"** → answer it and tick it. Answer from the mission, the KB and the decided rows, with the same fresh-context check as a D-row. Put the answer, its source and the reason in an Auto decision line and in the change-log row's `What changed` (`Q<n>: <answer>`), then tick the box. An open question without `blocks:` stays as written.
- **The mission DoR box "Backlog reviewed with the team; no known missing slice" — "never — the BA's judgement"** stays unticked. The mission DoR does not gate publishing.
- **"it never commits or pushes", "The BA's next `kb publish` ships the amended mission" and "The agent's output is a draft; the BA publishes it"** → the branch rule in ba-ticket-author's Auto mode, on branch `auto/<mission-id>`. The merge publishes through `kb-publish-request.yml`; follow that rule's last step and do not run `kb publish` by hand otherwise.

### Result line

End the reply with exactly one line, and make it the last line. Nothing follows it: no code fence, no markdown, no closing remark. It has one of three forms:

- `AUTO-RESULT: done` — the blockers are settled, the PR is merged, or the work was already finished. Write no text after `done`; always give a reason after `failed`.
- `AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]` — never ends this skill, which does not wait on Dev questions.
- `AUTO-RESULT: failed <reason>` — anything else: `ci-red <pr-url>` after 2 fix rounds, `mission-lint <mission-id>` when `kb_mission_lint` will not reach `DoR: PASS`, or `no-blocker <mission-id>` when `kb mission next --json` names no blocker for this mission and no merged `auto/<mission-id>` PR exists. The reason goes on the same line.
