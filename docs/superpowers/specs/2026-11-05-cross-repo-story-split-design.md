# Cross-repo stories — parent story + per-repo child tickets (design)

Date: 2026-11-05 · Size: project (phased) · Version: 1.34.5 → 1.35.0

## Intent

A product is often spread over many dev repos (≈10 per folder is a real
setup), each with its own `kb init --kind dev`, its own `<repo>-code` /
`<repo>-svc` on the hub and its own Dev or auto runner. A business need
regularly touches several of them ("pay with MoMo" = API + web + notify).

Today the framework assumes one ticket = one repo, but nothing enforces or
supports the multi-repo case:

- The BA cannot know which repo a story belongs to — and should not have to.
- `/ba-ticket-author` splits only on >10 AC or a second "As a …"; the SA
  grounds on a single `<repo-id>-code` (`Grounded on:` keeps the `-code`
  entry). Work for another repo degrades to `[NEW: …]` / `Open decisions`.
- **Routing gap:** `autorun/picker.dev_candidates` hands every ready ticket on
  the hub to every Dev runner — with 10 dev repos, 10 runners race for the
  same ticket.
- **Dependency gap:** an unparented ticket's `- Blocked by:` is ignored by
  the runner (`picker._dev_tasks` yields every ready unparented ticket).
- **Done gap:** `planstatus._done_ids` reads one `-svc` history per BA plan
  (the first mission's `Grounded on:`), so "done" for tickets of other repos
  is unknown.

The owner wants: the framework detects early that a need touches several
repos, **proposes** a split (how many children, names, which AC where, the
order), and only after the BA agrees writes **one normal ticket per repo**
under a lightweight **parent story**, with the cross-cutting parts (changes,
Q&A, bugs) kept consistent between parent and children.

## Goals

1. **Routing (every ticket):** a Dev runner / `kb ticket fetch` picks only
   tickets whose target repo is its own `repo_id`.
2. **Dependencies without a mission:** `- Blocked by:` between sibling
   tickets (and any unparented ticket) is honored by the runner and shown by
   `kb mission next` / hub.
3. **Done per target repo:** a ticket is `done` when its own target repo's
   `<repo>-svc` history lists it.
4. **Parent story + child tickets:** a new parent-story file (index only) and
   child tickets that are normal tickets plus two header lines; a lint that
   keeps parent and children consistent; `kb plan-ingest` publishes both; hub
   shows the story with its children and rolled-up status.
5. **Detect and propose the split** in `/ba-ticket-author` (right after
   Intake) and in `/ba-mission-plan` (split runs after SA services analysis).
   Nothing is written until the BA accepts.
6. **Change flow:** the BA describes a change at the parent; the SA proposes
   which children to amend / which new children to add; the BA accepts; each
   child goes through the normal amend.
7. **Q&A at the parent:** a business question asked on a child is recorded
   at the parent story; the SA proposes widening `blocks:` to sibling ACs;
   only BA-confirmed blocks block; the BA answers once; the SA proposes the
   amendments.
8. **Bugs:** a bug is assigned to one first-responder repo (SA proposes from
   the symptoms, BA confirms); after root cause, the Dev proposes child bugs
   for other repos; the BA confirms.

## Non-goals

- No automatic ticket writing without BA acceptance (propose only).
- No cross-repo PRs or a "meta" Dev that works in several repos.
- No change to the one-ticket-one-repo rule or to per-repo `kb init`.
- No new mission features; missions keep their own `Depends on`.
- The parent story is not reviewed: no maturity review, no DoR on it.

## Anti-goals (a failure even if it "works")

- Two runners implementing the same ticket.
- A child starting while a sibling it is blocked by is not merged.
- Parent and children disagreeing silently (an AC in two children, an AC in
  no child, a split table that names a child that does not exist, a child's
  `Blocked by` different from the table).
- A question's answer applied to one child while a sibling that shares the
  meaning keeps the old reading, without anyone being told.
- An AI deciding a split, a block or an amendment on its own.
- Breaking existing single-repo setups (tickets/bugs without a target must
  keep working where there is only one dev repo).

## Decisions (owner)

- **Model:** one business US = a **parent story** (index only) + N **child
  tickets**, one per repo. Children are normal tickets and the only thing
  that goes through review and BA approval. No mission is created for it.
- **ACs live only in children.** The parent holds the user story, the split
  table (child, repo, AC ids, blocked by, why) and its change log — no AC
  text. AC ids are unique across the whole story (AC1–3 in one child, AC4–5
  in another).
- **Early detection:** in `/ba-ticket-author` right after Intake; in
  `/ba-mission-plan` the split step runs after the SA services analysis.
- **Propose, never auto-split:** the framework states how many children,
  their names (one per repo) and which AC goes where; the BA accepts first.
- **Changes are described at the parent;** the SA analyses and proposes which
  children to amend or add; the BA accepts; children follow the normal amend.
- **Q&A:** business questions on a child go to the parent; the SA proposes
  widening `blocks:`; **blocks widen only after BA confirmation**.
- **Bugs:** first-responder repo first; split only after root cause.
- **Approach A** (below).

## Approaches considered

**A. Parent-story file in the BA repo + normal child tickets (chosen).**
`tickets/<folder>/US-<n>.md` with `> Kind: parent story`; children carry
`> Parent story:`; lint checks consistency; plan-ingest publishes both;
runner routes by target repo and honors `Blocked by`. Gives the BA a place
to describe changes at the parent and the SA a place to record proposals;
children keep every existing rule. Cost: a new file kind that plan-ingest,
planstatus, hub UI and lint must understand.

**B. No parent file; children only carry `> Parent story: US-12`, hub groups
them.** Less code, but no place for the BA's parent-level change, no record
of the SA split, consistency only pairwise. Works against the agreed change
flow. Rejected.

**C. Auto-created mini mission as the parent.** Reuses Sequencing / D-rows,
but the owner rejected creating a mission for one US, and mission lint
(maturity review, scope split, C4) does not fit. Rejected.

## Design

### 0. Vocabulary and ids

- **Parent story id:** the BA's US id, e.g. `US-12` (or `M-x-US3` inside a
  mission). File `tickets/<folder>/US-12.md`.
- **Child id:** `<parent-id>-<repo-id>`, e.g. `US-12-payments-api`. A second
  child for the same repo (added after the first is done) gets `-2`:
  `US-12-payments-api-2`. File `tickets/<folder>/<child-id>.md`.
- **Bug child id:** `BUG-<n>-<repo-id>` (same rule).
- A repo id that contains `/` (nested federation id) is written with `/`
  replaced by `--` in the child id; the header keeps the real id.

### 1. Target repo (phase 1, every ticket)

- **Story/child ticket:** the target repo is the repo of the `-code` entry of
  `Grounded on:` (`missionnext.grounded_doc`). A child also states it in
  `> Target repo: <repo-id>`; lint fails if the two disagree.
- **Bug:** `> Target repo: <repo-id>` header (new, set by the SA quick look in
  `/ba-bug-report`, confirmed by the BA).
- **Missing target (legacy / ungrounded):** the ticket is routed to the only
  dev repo in the hub registry when there is exactly one; otherwise it is not
  picked automatically and `kb mission next` / hub show
  `no target repo — run /sa-ticket-ground or set > Target repo:`.
  (Claude's call: keeps today's single-repo setups working, refuses to guess
  with several.)
- `StoryStatus` gains `target_repo: str | None`.
- `picker.dev_candidates(..., repo_id)` keeps only tasks whose target is
  `repo_id` (or resolves to it by the single-repo rule). Same filter for the
  hub ticket list `?for=<repo>` and `kb mission next --from-hub --for <repo>`.
- `kb ticket fetch <id>` in a dev repo warns (does not refuse) when the
  target is another repo: `US-12-web-app targets web-app, this repo is
  payments-api`. (Claude's call: a human may legitimately read it.)

### 2. Blocked by for unparented tickets (phase 1)

- Unparented tickets and children: `StoryStatus.depends_on` is filled from
  `## Dependencies` → `- Blocked by: <id> — <why>` (ids only; external items
  written as free text with no ticket id are ignored with a note).
- Status `blocked` with reason `blocked by <id> (not done)` until every named
  id is `done`. `picker._dev_tasks` checks `depends_on` for unparented items
  exactly as it does for mission stories.
- A `Blocked by` id that is not published anywhere on the hub: status
  `blocked`, reason `blocked by <id> (unknown)` — never treated as done.
- Cycle (A blocked by B blocked by A): both `blocked`, reason `dependency
  cycle: A → B → A`; `kb ticket lint` on the parent (§4) fails on it too.

### 3. Done per target repo (phase 1)

`planstatus._plan_repo` computes done per ticket: load the `-svc` history of
the ticket's target repo (cache per repo per run); `done: unknown (<svc> not
published)` per target instead of one note for the whole plan. Mission
stories keep the mission's `Grounded on:` unless the story's own ticket has a
target. A parent story's status is rolled up (§5).

### 4. Parent story file and consistency lint (phase 2)

Parent file (`tickets/<folder>/US-12.md`):

```markdown
# US-12 <title>
> Kind: parent story
> Revision: <N>
[> Parent mission: M-x @ rev K]          (when the US is a mission story)

## User Story
As a …, I want …, so that ….

## Split
| Child | Repo | AC | Blocked by | Why |
|---|---|---|---|---|
| US-12-payments-api | payments-api | AC1, AC2, AC3 | — | api.payments POST /payments |
| US-12-web-app | web-app | AC4, AC5 | US-12-payments-api | page.web /checkout |

## Change log
| Rev | Date | Trigger | What changed |
```

Child ticket = normal ticket + header lines `> Parent story: US-12 @ rev N`
and `> Target repo: <repo-id>`.

`kb ticket lint` gains parent-story rules (run on the parent file, and on a
child when its parent is in the same repo):

| Rule | Severity |
|---|---|
| every child in `## Split` exists as a file and has `> Parent story: <parent>` | error |
| every file with `> Parent story: X` is listed in X's split | error |
| child's AC ids == the split row's AC ids; no AC id in two children; no gaps in numbering are allowed only if the change log removed them | error |
| child's `- Blocked by:` ids == the split row's `Blocked by` | error |
| child's `> Target repo:` == split row repo == `Grounded on:` repo (once grounded) | error |
| child's `## User Story` == parent's `## User Story` (whitespace-normalised) | error |
| child's `@ rev N` < parent revision | warning (`stale against parent rev M`) |
| dependency cycle in the split | error |
| parent has no AC section and no DoR (they belong to children) | error if present |

The parent skips DoR, maturity review and technical grounding.
`kb plan-ingest`: a parent publishes when it lints (like a mission); a child
publishes when it lints and its DoR is ticked (like any ticket); a child whose
parent fails lint is skipped with `parent US-12 fails lint`.
`planstatus` / hub: parent shows `k/N done` and its children (repo, status,
PR); the hub ticket page of a child links its parent and siblings.

### 5. Status roll-up

Parent status: `done` when every child is `done`; `blocked` when no child is
ready and at least one is blocked; otherwise `in progress`. The parent itself
is never a task for a runner.

### 6. Detect and propose the split (phase 3)

**`/ba-ticket-author`** — new step 1b *Scope by repo*, after Intake, before
Draft:

1. The agent runs an SA quick look (`/sa-ticket-ground --scope`, read-only):
   `kb_search` over the hub with `kinds=["dev"]` for the routes, pages,
   tables, jobs and services the need implies; maps each hit to its repo.
2. One repo → continue exactly as today (the ticket is a normal ticket with
   a target).
3. Several repos → print the proposal and stop for the BA:
   `This need touches 2 repos. Proposed: parent US-12 + 2 child tickets:
   US-12-payments-api (payments-api: AC about payment creation, refunds) ·
   US-12-web-app (web-app: AC about the checkout page) — US-12-web-app is
   blocked by US-12-payments-api. Evidence: …`
4. BA accepts / edits (rename, merge two repos, move an AC) / rejects (→ one
   ticket as today, with a lint warning that it touches several repos).
5. On accept: write the parent; draft the ACs once for the whole need, then
   distribute them into children by the accepted split; run the normal
   pipeline (Lint → Ground → Maturity review → BA review) **per child**.
   Grounding of each child uses its own repo.

**`/ba-mission-plan`** — reorder: *Ground services* (SA) runs before
*Split*; for each backlog story the SA reports its repos; a multi-repo
story gets the same proposal; on accept the backlog row becomes a parent
story (`M-x-US3`) whose children are drafted later by `/ba-ticket-author`.
`## Sequencing` keeps story-level `Depends on`; child-level order lives in
the parent's split.

### 7. Change flow (phase 4)

1. BA runs `/ba-ticket-author --amend US-12` and describes the change in
   business words at the parent.
2. SA analyses against the split and the children's ACs and proposes:
   `amend US-12-web-app (AC5 changes) · add US-12-payments-api-2 (new AC6:
   refund; US-12-payments-api is done) · no change to …`.
3. BA accepts → parent revision N+1 + change-log row; each touched child gets
   the normal amend (revision +1, change-log row with Trigger `parent rev
   N+1`, one maturity review round, DoR re-ticked by the BA); new children
   go through the full pipeline.
4. **A `done` child is never amended**; a change to its scope becomes a new
   child (`-2`), so shipped history stays intact.
5. Lint (§4) must pass on parent and all children before publish.

### 8. Q&A at the parent (phase 4)

- `kb_question_ask(ticket=<child>, …)` on a child of a parent story records
  the question on the **parent** (`ticket = US-12`) with new field
  `asked_from = <child>`; `blocks` = the asker's AC ids. Technical questions
  still go to the repo's `dev-sa`.
- Q&A store (`.kb-qa/qa.db`): add nullable columns `asked_from TEXT` and
  `proposed_blocks TEXT`; migration on open; existing rows unchanged.
- When a parent-level question is recorded, the SA triage (part of
  `/ba-answer-questions`, or the BA auto loop) writes `proposed_blocks`
  (sibling AC ids + reason). It does **not** block.
- `/ba-answer-questions` shows the question with the whole story: split table
  + every child's ACs + `proposed_blocks`. The BA confirms or edits the
  widened blocks → `blocks` updated (only now siblings block). Then the BA
  answers once; the SA proposes amendments (→ §7 flow); answer recorded
  when the amendments are published, as today ("waiting for publish").
- Every child's `BA-Q:` line lists the parent's questions; the existing gate
  (`blocks` names one of *this child's* ACs → stop) needs no change because
  AC ids are unique across the story.

### 9. Bugs across repos (phase 5)

- `/ba-bug-report` gains an SA quick look after Intake: from the symptoms it
  proposes the first-responder repo with evidence; BA confirms →
  `> Target repo:`.
- `/dev-fix-bug` root-cause step: if the cause is (partly) in another repo,
  the Dev records it in `rootcause.md` and proposes child bugs
  (`BUG-7-payments-api`) with the root cause and repro steps for that repo;
  the BA confirms (`/ba-bug-report --child-of BUG-7`), which turns `BUG-7`
  into a parent bug (`> Kind: parent bug`, split table) and publishes the
  child.
- The first-responder's own fix, if any, stays in `BUG-7`'s own target work;
  `BUG-7` is done when its own fix (if any) and every child bug are merged.

### 10. Phases (each ships alone)

1. Routing + `Blocked by` for unparented + done per target repo (§1–3).
2. Parent story format, lint, plan-ingest, hub (§4–5).
3. Detect + propose in `/ba-ticket-author` and `/ba-mission-plan` (§6).
4. Change flow + Q&A at the parent (§7–8).
5. Bugs (§9).

## Flow walkthrough (to be reviewed end to end)

1. BA: `/ba-ticket-author` "khách hàng thanh toán bằng ví MoMo".
2. Scope by repo → proposal (2 repos) → BA accepts.
3. Parent `US-12.md` written; ACs drafted once, distributed: AC1–3 →
   `US-12-payments-api.md`, AC4–5 → `US-12-web-app.md` (`Blocked by:
   US-12-payments-api`).
4. Per child: lint → SA ground on its repo → maturity review → BA review,
   DoR tick, commit. Parent lint PASS.
5. `kb plan-ingest` + publish → hub: US-12 `0/2`, `payments-api` ready,
   `web-app` blocked.
6. Runner in payments-api picks `US-12-payments-api` (target match); runner
   in web-app picks nothing for US-12.
7. payments-api PR merged → `-svc` history lists it → done → web-app child
   unblocked → web-app runner picks it.
8. Dev in web-app asks "minimum amount?" `blocks: AC4` → recorded on US-12;
   SA proposes `+AC2`; BA confirms → payments-api child also blocked (it is
   already done → SA proposes a new child `-2` if the answer changes AC2).
9. BA answers; SA proposes amendments; BA accepts; children amended /
   added; publish; questions answered.
10. Both done → US-12 `2/2 done`.

## Failure cases the design must handle

| Case | Expected |
|---|---|
| SA quick look finds no repo (greenfield) | one ticket as today; SA proposes `[NEW: D<n>]`/`[NEW: …]` at grounding |
| Target repo not in the hub registry | lint error on the child; not published |
| Two BA repos publish the same parent/child id | existing `<repo>:<id>` qualification applies; lint warns on a cross-repo duplicate |
| A child is cancelled | removed from the split + change-log row; file deleted; lint passes; hub drops it on next publish |
| A child depends on a sibling that is cancelled | lint error until its `Blocked by` is updated |
| Parent edited by hand inconsistently | lint error; nothing publishes |
| Child DoR unticked after an amend | that child drops off the hub (existing rule); siblings unaffected |
| BA rejects the split | single ticket; lint warning "grounding touches several repos" when SA finds hits outside the target |
| Runner of repo X fetches a child of repo Y by hand | warning, not refusal |
| Q&A DB from an older hub | migration adds nullable columns; old questions have `asked_from = NULL` |
| Hub without the new code (older install) reads a child | header lines are ignored; it is a normal ticket |

## Testing (per phase)

- Phase 1: picker filters by repo; single-repo fallback; unparented `Blocked
  by` blocks/unblocks; unknown and cyclic deps; done read from each target's
  `-svc`.
- Phase 2: every lint rule (one failing fixture each); plan-ingest publish /
  skip; roll-up statuses; hub page shows parent + children.
- Phase 3: skill text tests (templates/mirrors drift checks) for the new step
  and wording; an e2e on a fixture hub with two dev repos.
- Phase 4: Q&A migration; parent-level record; proposed vs confirmed blocks;
  gate stops only on confirmed blocks.
- Phase 5: bug target header; child-bug creation; parent-bug roll-up.

## Left to the builder

- Exact function names/signatures, where routing lives (`picker` vs
  `planstatus`), CLI flag names (`--for`), hub template layout.
- Wording of the agents' proposal messages (must contain: child count, names,
  repo per child, AC per child, blocked-by, evidence).
