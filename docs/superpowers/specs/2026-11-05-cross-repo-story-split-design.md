# Cross-repo stories — parent story + per-repo child tickets (design)

Date: 2026-11-05 · Size: project (5 phases) · Version: 1.34.5 → 1.35.0 (phase 1)

## Intent

A product is often spread over many dev repos (≈10 per folder is a real
setup), each with its own `kb init --kind dev`, its own `<repo>-code` /
`<repo>-svc` on the hub and its own Dev or auto runner. A business need
regularly touches several of them ("pay with MoMo" = API + web + notify).

The framework assumes one ticket = one repo but does not enforce or support
the multi-repo case:

- The BA cannot know which repo a story belongs to, and should not have to.
- `/ba-ticket-author` splits only on >10 AC or a second "As a …"; the SA
  grounds on one `<repo-id>-code`. Work for another repo degrades to
  `[NEW: …]` / `Open decisions`.
- **Routing gap:** `autorun/picker.dev_candidates` hands every ready ticket on
  the hub to every Dev runner: with 10 dev repos, 10 runners race for it.
- **Dependency gap:** an unparented ticket's `- Blocked by:` is ignored by the
  runner (`picker._dev_tasks`).
- **Done gap:** `planstatus._done_ids` reads one `-svc` history per BA plan
  (the first mission's `Grounded on:`), so done for other repos is unknown.

The owner wants the framework to detect early that a need touches several
repos, **propose** a split (how many children, their names, which AC where,
the order) and, once accepted, write **one normal ticket per repo** under a
lightweight **parent story**, with changes, Q&A and bugs kept consistent
between parent and children.

## Goals

1. **Routing (every ticket):** a Dev runner picks only tickets whose target
   repo is its own `repo_id`.
2. **Dependencies without a mission:** `- Blocked by:` between sibling
   children is honored by the runner and shown by `kb mission next` / hub.
3. **Done per target repo:** a ticket is `done` when its target repo's
   `<repo>-svc` history lists it.
4. **Parent story + child tickets:** a parent-story file (index only), child
   tickets that are normal tickets plus header lines, a lint that keeps them
   consistent, plan-ingest publishing both, hub showing the story with its
   children and rolled-up status.
5. **Detect and propose the split** in `/ba-ticket-author` (right after
   Intake) and in `/ba-mission-plan` (per backlog story, after Split).
6. **Change flow at the parent**, **Q&A at the parent**, **bugs** routed to a
   first-responder repo and split after root cause.

## Non-goals

- Tracker integration: no change to `kb ticket export`, no mapping from
  child ids to tracker keys (owner: handle later).
- No cross-repo PRs; no Dev that works in several repos.
- No change to the one-ticket-one-repo rule or to per-repo `kb init`.
- The parent is never reviewed (no maturity review, no DoR) and never a task.

## Anti-goals (a failure even if it "works")

- Two runners implementing the same ticket, or a runner implementing a
  ticket of another repo.
- A child starting while a sibling it is blocked by is not merged.
- Parent and children disagreeing silently.
- An answer applied to one child while a sibling that shares the meaning
  keeps the old reading, without anyone being told.
- A whole story disappearing from the hub because of one bad edit.
- A split, a block or an amendment decided without a recorded decision: in
  interactive mode the BA accepts; in auto mode the agent decides **and** a
  fresh-context reviewer checks, and both are recorded (owner decision).
- Breaking existing single-repo setups.

## Decisions (owner)

- **Model:** one business US = **parent story** (index only) + N **child
  tickets**, one per repo. Children are normal tickets and the only thing
  reviewed and approved. No mission is created for it.
- **ACs live only in children.** The parent holds the user story, the split
  table and its change log. AC ids are unique across the story.
- **Early detection:** `/ba-ticket-author` right after Intake;
  `/ba-mission-plan` per backlog story.
- **Propose, never silently split:** child count, names (one per repo), AC per
  child, order, evidence. Interactive: the BA accepts. **Auto mode: the agent
  accepts under the existing decision-plus-fresh-reviewer rule** (owner, 1b).
- **Changes are described at the parent;** the SA proposes which children to
  amend or add; accepted as above; children follow the normal amend.
- **Q&A:** business questions on a child are recorded at the parent; the SA
  proposes widening `blocks:`; widened blocks take effect only once accepted
  (BA, or agent + reviewer in auto mode).
- **Bugs:** first-responder repo first; split only after root cause.
- **Tracker export out of scope** for now.
- **Approach A.**

## Approaches considered

**A. Parent-story file in the BA repo + normal child tickets (chosen).** Gives
the BA a place to describe parent-level changes and the SA a place to record
split proposals; children keep every existing rule. Cost: a new file kind
for plan-ingest, planstatus, hub, lint, picker and claims.

**B. No parent file; children carry `> Parent story:`, hub groups them.**
No place for parent-level changes or split records; consistency only
pairwise. Rejected.

**C. Auto-created mini mission.** Owner rejected a mission for one US;
mission lint (maturity review, scope split, C4) does not fit. Rejected.

## Design

### 0. Ids and header lines

- **Parent id:** the BA's US id (`US-12`, or `M-x-US3` in a mission). File
  `tickets/<folder>/US-12.md`, header `> Kind: parent story`.
- **Child id:** `<parent-id>.<repo-id>` (dot separator), e.g.
  `US-12.payments-api`; a later child for the same repo `US-12.payments-api.2`.
  Bug child: `BUG-7.payments-api`. (Claude's call: a dot cannot appear in a
  dev repo id or a `US<n>`/`BUG-<n>` id, so it never collides with
  `-<digit>` repo ids or the `\b…-US\d+\b` regexes; see Review §C2, M1.)
- **Child headers:** `> Parent story: US-12 @ rev <N>` and
  `> Target repo: <repo-id>`.
- **Bug headers (any bug, phase 1):** `> Target repo: <repo-id>`;
  parent bug: `> Kind: parent bug`.
- **Uniqueness:** a stem must be unique under `tickets/` (lint error, not
  plan-ingest's silent "kept the first"). CI lint (it has the hub) errors on
  an id another BA repo already publishes; planstatus marks such ids
  `blocked: id published by several BA repos`. Dependencies resolve inside
  the same BA plan only. (Review C6, M10.)
- Bug numbering ("highest `BUG-<n>.md` + 1") counts digits-only stems only.

### 1. Target repo and routing (phase 1)

- **Target:** a child's or bug's `> Target repo:` line. A plain (non-split)
  story without the line: the `-code` entry of its first `Grounded on:` must
  be qualified (`<repo>:<repo>-code`); its repo is the target. For a child,
  lint requires the first `Grounded on:` entry to equal
  `<target>:<target>-code`. (Review I8.)
- **Bugs in phase 1:** `/ba-bug-report` asks the BA for the target repo (or
  takes the only dev repo); the SA quick look that proposes it arrives in
  phase 5. (Review I6.)
- **No target:** routed to the only dev repo in the hub registry when there is
  exactly one; otherwise `blocked: no target repo` and not picked. (Claude's
  call: keeps single-repo setups working.)
- **Unknown target** (not a dev repo on the hub): planstatus marks the ticket
  `blocked: target <x> is not a dev repo on the hub` (plan-ingest is offline
  and cannot check it). (Review I9.)
- `StoryStatus` gains `target_repo: str | None`; the hub computes it, so
  routing is server-side on cloud.
- `picker.dev_candidates` keeps only tasks routed to the runner's `repo_id`.
  The Dev runner's `all_done` counts only its routed tickets. (Review M5.)
- The hub plan API takes a new `for_repo=<dev-repo>` parameter, distinct from
  the existing `repo` (BA repo) parameter. (Review M13.)
- **Mixed versions:** the runner reads `target_repo` with `.get`; it refuses to
  start against a hub whose plan API lacks the field (`hub is older than
  1.35 — upgrade the hub first`); plan-ingest warns when publishing to such a
  hub. Pre-1.35 runners do not route; the release note says upgrade every
  Dev runner. (Review I16.)
- `kb ticket fetch <id>` in a dev repo warns when the target is another repo.
- **Stored tasks:** before resuming a stored task the runner re-checks that
  the ticket is still published, still routed to it and not a parent; on
  `unknown_ticket` from claim take it drops the local claim, clears the task,
  logs the reason and picks again (no idle wedge). (Review I14, I15, M14.)

### 2. Blocked by (phase 1)

- **Children:** `- Blocked by:` tokens count only as an exact match against
  the parent's split ids. They are never parsed with `US_ID_IN_CELL_RE` /
  `BARE_US_RE` (`dep_ids('US-12-payments-api')` returns `()` today, and
  `M-x-US3-…` would resolve to the parent). An id not in the split is a lint
  error. (Review C2.)
- **Legacy unparented tickets:** only tokens that equal a ticket id published
  by the same BA plan count; anything else (tracker keys, prose) is a note,
  never a block. (Review I7.)
- A listed dependency that is not `done` → `blocked: blocked by <id> (not
  done)`; picker checks `depends_on` for unparented items as for mission
  stories. Cycles → `blocked: dependency cycle …` and a parent lint error.
- **Consumer → provider references:** a child that uses a route its blocking
  sibling will create writes `[NEW: <sibling-child-id>]`; lint checks the id
  is a sibling this child is blocked by; `kb ticket check` treats it as
  resolved once the sibling is done. (Review M12.)

### 3. Done per target repo (phase 1)

One shared function (used by `planstatus`, the local `kb mission next`, and
the BA picker's local path) computes done per ticket from its target repo's
`-svc` history, cached per repo per run; `done: unknown (<svc> not
published)` per target. Mission stories that are not split keep the
mission's `Grounded on:`. (Review I4.)

### 4. Parent story file, consistency lint, publish (phase 2)

```markdown
# US-12 <title>
> Kind: parent story
> Revision: <N>
[> Parent mission: M-x @ rev K]

## User Story
As a …, I want …, so that ….

## Split
| Child | Repo | AC | Blocked by | Own fix | Why |
|---|---|---|---|---|---|
| US-12.payments-api | payments-api | AC1, AC2, AC3 | — | | api.payments POST /payments |
| US-12.web-app | web-app | AC4, AC5 | US-12.payments-api | | page.web /checkout |

## Change log
| Rev | Date | Trigger | What changed | Affected | Reviewed |
```

- The change log uses the existing 6-column format and triggers (`scope`,
  `question`, …); `Affected` lists the children touched. (Review I1.)
- `Own fix` is used by parent bugs only (§9).
- An AC that replaces a done child's AC is written `AC7 (replaces AC2)` in the
  split; lint accepts the old id staying in the done child. (Review M8.)

**Lint (`kb ticket lint`, CLI and MCP):**

| Rule | Severity |
|---|---|
| every split child exists and has `> Parent story: <parent>` | error |
| every file with `> Parent story: X` is in X's split | error |
| child AC ids == split row AC ids; no AC id in two live children | error |
| child `Blocked by` == split row; ids exist in the split; no cycle | error |
| child `> Target repo:` == split repo == first `Grounded on:` repo | error |
| child `## User Story` == parent's (whitespace-normalised) | error |
| each child has ≥2 ACs (existing rule) — the split proposal must respect it | error |
| parent has no AC section, no DoR | error if present |
| child pinned to an older parent rev and named in a later row's Affected | child reads `draft` (demotion), see below |

- MCP `kb_ticket_lint` gains `parent_markdown`; without it a child's parent
  rules report an **error** (`parent not given`), not a note. (Review I11.)
- BA CI (`kb-ticket-lint.yml`) lints the parent of every added, changed **or
  deleted** child (today `--diff-filter=ACMR` misses deletes). (Review C4.)
- **Demotion:** `planrev.demotions` extends to `> Parent story:` pins: a child
  named in the Affected of a later parent row than its pin reads `draft` (off
  the hub) until re-amended; done children are exempt. (Review I12.)

**Publish (`kb plan-ingest` / `kb publish`):**

- A parent publishes when it lints (no DoR gate); a child when it lints and its
  DoR is ticked.
- **Fail closed:** if any parent story fails lint, plan-ingest exits non-zero
  and publishes nothing, so the hub keeps the last good version — instead of
  silently dropping every child of that story. (Review C4.)
- A ticket id with a live claim or a `hist` row cannot become a parent (CI
  lint, which has the hub). (Review I14.)

**Status and tasks:**

- planstatus and plan-ingest read `> Kind: parent story|parent bug`. A parent
  stays in the status list (mission `Depends on` and the picker's done set
  need it) with a rolled-up status and `is_parent = True`; `_dev_tasks`,
  claim `take` and the hub claim UI refuse it. (Review C1.)
- Roll-up: `done` when every child (and a parent bug's own fix, §9) is done;
  `blocked` when nothing is ready and something is blocked; else
  `in progress`. `in progress` is used for parents only; consumers (planui
  labels, `_next_line`, `all_done`) learn it. A split child with no file yet
  reads `to-draft`. (Review M4.)
- BA picker: a parent is never `draft`; `_ba_tasks` yields
  `ba-ticket-author <child-id>` for each split row with no file. (Review I4.)
- Hub: the parent page shows the split with each child's repo, status, PR;
  each child links its parent and siblings.

### 5. Children of a mission story

A child inherits from its parent (Review C3):

- backlog membership is checked for the **parent** id;
- `depends_on(child)` = the parent's mission `Depends on` + the split row's
  `Blocked by`;
- mission D-row / open-question blockers and demotion of the parent apply to
  every child; `[NEW: D<n>]` in a child resolves against the parent's mission;
- `Blocked by` between siblings lives only in the split, not in the mission's
  `## Sequencing`; `_check_blocked_by_declared` skips sibling ids.

### 6. Detect and propose the split (phase 3)

**`/ba-ticket-author`**, new step 1b *Scope by repo* (after Intake, before
Draft):

1. SA quick look (`/sa-ticket-ground --scope`, read-only): `kb_search` with
   `kinds=["dev"]` for the routes, pages, tables, jobs and services the need
   implies; each hit mapped to its repo.
2. One repo → today's flow; the ticket gets that repo as target.
3. Several repos → proposal: child count, ids, repo, which ACs (by subject;
   ids after Draft), order (`Blocked by`), evidence. Each child must get ≥2
   ACs, otherwise the proposal merges it into a sibling. (Review I10.)
4. Accept / edit / reject. Reject → one ticket, with a lint warning
   `grounding touches several repos` when grounding finds hits elsewhere.
5. Accepted → write the parent; draft the ACs once for the whole need,
   distribute them by the split; run Lint → Ground (own repo) → Maturity
   review → BA review **per child**.

**`/ba-mission-plan`:** order stays Split → Ground services; then a new
per-story repo proposal; an accepted multi-repo story is written as a parent
file at mission time, its children are drafted later by `/ba-ticket-author`
(the BA picker yields them, §4). `## Services & order` may cite several
`<repo>:<repo>-code` docs; `kb ticket check --mission` resolves each id in its
own repo's doc. (Review I13.)

### 7. Change flow (phase 4)

1. `/ba-ticket-author --amend US-12`: the BA describes the change at the
   parent.
2. SA proposes: amend child X (which AC), add child `.2` for a done child,
   no change to Y.
3. Accepted → parent rev N+1 with a change-log row whose Affected lists the
   children; each listed child gets the normal amend (rev +1, trigger
   `scope`/`question`, What changed `parent rev N+1: …`, one maturity round,
   DoR re-ticked). New children go through the full pipeline.
4. A **done** child is never amended; its change becomes a new child. A
   **done parent** (every child done) is frozen: a further change is a new
   US (existing rule, ba-ticket-author "done stories are frozen"). (Review M9.)
5. Until each Affected child is re-published at its new revision it reads
   `draft` (demotion, §4), so no runner works on the old reading.

### 8. Q&A at the parent (phase 4)

- `kb_question_ask(ticket=<child>)` on a child records the question on the
  **parent** (`ticket = US-12`) with `asked_from = <child>`; `blocks` = the
  asker's AC ids. Technical questions go to the repo's `dev-sa` as today.
- `list_questions(ticket=<child>)` also returns its parent's questions, so the
  child sees them and the "already asked" check works. (Review I2.)
- The Dev gate stops only when `blocks` names one of **this ticket's** AC ids;
  ids are compared after normalising `AC-2` → `AC2`. (Review I2.)
- Q&A store: nullable columns `asked_from`, `proposed_blocks`, `confirmed_by`;
  the migration checks columns inside `BEGIN IMMEDIATE`. (Review M6.)
- SA triage writes `proposed_blocks` (sibling ACs + reason); it blocks only
  after acceptance (BA in `/ba-answer-questions`; in auto mode the agent +
  fresh reviewer), recorded in `confirmed_by`. Limit stated in the guide:
  Q&A names are self-declared, so `confirmed_by` is an audit trail, not an
  access control. (Review M7.)
- The BA answers once; the SA proposes amendments (§7).
- **Answered:** a parent question is `answered` only when every child in the
  Affected of the parent's change-log row for `answer_rev` is on the hub with
  `@ rev ≥ answer_rev`; `ticket_sections` = that row's Affected. The DoR stop
  in `/ba-answer-questions` applies to each amended child. (Review C7.)
- **In-flight siblings:** right before merge, `dev-handover` re-runs
  `kb_question_list` and compares the hub revision with the fetched one; a
  newly blocking question or a newer revision stops with `blocked-qa`.
  (Review I3.)

### 9. Bugs across repos (phase 5)

- `/ba-bug-report`: SA quick look after Intake proposes the first-responder
  repo from the symptoms → `> Target repo:` (accepted as above).
- `/dev-fix-bug` root cause: cause (partly) elsewhere → `rootcause.md` + a
  proposal of child bugs (`BUG-7.payments-api`) with the root cause and repro
  steps for that repo. In auto mode the run **ends** after writing the
  proposal (`AUTO-RESULT: blocked-split BUG-7`); it never creates tickets.
- `/ba-bug-report --child-of BUG-7` (BA repo) turns BUG-7 into a parent bug:
  the split carries a row for BUG-7 itself with `Own fix: yes|no` and its
  `Blocked by` (the own fix often needs the child's fix first). The skill
  writes files only; committing/publishing stays the BA's step. (Review M11.)
- Before BUG-7 is edited, the first responder's claim is set to `stopped`
  with reason `split into child bugs`. (Review I5.)
- Done: roll-up only — every child bug done, and BUG-7's own fix done when
  `Own fix: yes`. `close_done_tickets` and `all_done` use the roll-up.

### 10. Auto mode (all phases)

Every new acceptance step ("BA accepts the split / widened blocks /
amendments / child bugs") is, in auto mode, decided by the agent and checked
by a fresh-context reviewer, exactly like existing auto-mode decisions, and
both the decision and the review are written where the BA would have
accepted (parent change log, Q&A `confirmed_by`). Each skill's Auto mode
section names these steps explicitly. (Owner 1b; Review C5.)

### 11. Branch names

Crash-recovery and branch lookups match the exact ticket id or `<id>-r<N>`,
never a prefix glob, so a parent never resumes a child's branch and a child
never resumes its `.2` sibling's. (Review M2.)

### 12. Phases (each ships alone)

1. Routing + target lines for tickets and bugs + `Blocked by` + done per
   target + stored-task recovery (§1–3, §11).
2. Parent story format, lint (CLI/MCP/CI), publish fail-closed, roll-up,
   demotion, hub, mission children (§4–5).
3. Detect + propose (§6).
4. Change flow + Q&A at the parent + pre-merge re-check (§7–8).
5. Bugs (§9).
Auto-mode wording (§10) ships with each phase that adds a step.

## Flow walkthrough

1. BA: `/ba-ticket-author` "khách hàng thanh toán bằng ví MoMo".
2. Scope by repo → 2 repos → proposal → accepted (BA, or agent + reviewer).
3. `US-12.md` written; ACs drafted once: AC1–3 → `US-12.payments-api.md`,
   AC4–5 → `US-12.web-app.md` (`Blocked by: US-12.payments-api`).
4. Per child: lint (with parent) → ground on its repo → maturity review →
   BA review, DoR tick. Parent lint PASS. Commit.
5. plan-ingest + publish (fails closed if the parent is inconsistent) → hub:
   US-12 `in progress 0/2`; payments-api child ready, web-app child blocked.
6. payments-api runner picks its child (routed); web-app runner picks
   nothing; neither picks US-12.
7. payments-api PR merged → its `-svc` history lists it → done → web-app child
   unblocked → web-app runner picks it.
8. web-app Dev asks "minimum amount?" `blocks: AC4` → recorded on US-12;
   SA proposes `+AC2`; accepted → `blocks: AC2, AC4`; AC2's child is done, so
   the SA's amendment proposal will be a new child `US-12.payments-api.2`.
9. BA answers; amendments accepted; parent rev 2 (Affected: web-app,
   payments-api.2); web-app child demoted to draft until re-published; the
   question reads answered once both are on the hub at rev ≥ 2.
10. All children done → US-12 `done`.

## Failure cases

| Case | Expected |
|---|---|
| SA finds no repo (greenfield) | one ticket; target set at grounding |
| Target not a dev repo on the hub | `blocked: target … is not a dev repo` |
| Several dev repos, ticket without target | `blocked: no target repo` |
| Same child id from two BA repos | CI lint error; planstatus `blocked: id published by several BA repos` |
| Child cancelled | removed from split + change-log row; file deleted; CI lints the parent; siblings' `Blocked by` must be updated (lint) |
| Parent edited inconsistently | lint error; publish fails closed; hub keeps last good version |
| Child DoR unticked after amend | that child off the hub; siblings unaffected; its runner re-picks after `unknown_ticket` |
| Ticket already claimed/done made a parent | CI lint error |
| Runner of X fetches a child of Y by hand | warning |
| Older hub, new runner | runner refuses to start with an upgrade message |
| Older runner, new hub | no routing (documented: upgrade runners) |
| Q&A DB from an older hub | migration adds nullable columns |

## Testing (per phase)

- P1: routing per repo; single-repo fallback; no/unknown target; `Blocked by`
  exact-id matching (incl. `M-x-US3.repo`), legacy prose ignored; done per
  target; stored-task recovery on `unknown_ticket`; old-hub refusal.
- P2: one failing fixture per lint rule; MCP `parent_markdown`; CI deleted
  child; plan-ingest fail-closed; roll-up; parent never a task (picker,
  claim take); demotion of Affected children; mission children inherit.
- P3: skill text drift checks; e2e on a fixture hub with two dev repos.
- P4: Q&A migration; parent-level record and listing on children; gate only
  on this ticket's ACs; proposed vs confirmed blocks; answered only after all
  Affected children publish; pre-merge re-check.
- P5: bug target; child-bug proposal ends auto run; parent bug roll-up with
  `Own fix`.

## Left to the builder

- Function names/signatures, module placement of the shared done/roll-up
  function, CLI flag names, hub template layout.
- Wording of proposals (must contain: child count, ids, repo, ACs, order,
  evidence).

## Review record

Builder check and an adversarial flow audit (7 Critical, 16 Important, 14
Minor) were run on the first draft; every finding is closed by a rule above
(tagged `Review <id>`). Owner answered: auto mode accepts with reviewer
(1b); tracker export out of scope.
