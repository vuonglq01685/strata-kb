# Test strategy — the Tester's plan and test order (design)

Date: 2026-11-15 · Size: project (phased) · Version: 1.37.0 → 1.38.0 (phase 1)

Builds on the tester role (`2026-11-14-tester-role-design.md`, phase 1
shipped in 1.37.0). Terms from there are reused: `tester` repo,
`<repo_id>-test` hub document, Q1 review, testable story (`done` or
`fix-done`), Test Report menu (`/ui/tests`).

## Intent

A Tester today tests one story at a time (`/tester-test-story <story>`) and
the order is whatever the person types. Nothing on the hub says what the
Tester plans to test, in what order, why, or with which tools. The owner
wants a **test strategy / test plan**, written by the Tester:

- what is in scope, which test levels and types, which tools run them
  (Playwright UI, API, DB seed/reset, regression), environments, entry and
  exit criteria, risks;
- the **order** in which US / Missions are tested, with the reason (risk);
- readable by people first (PM, BA, Dev on the hub), then used by the
  machine: `/tester-test-story` and later `kb auto` pick the next story in
  that order.

It must work in two situations the owner named:

1. **Docs only.** No code and possibly no missions or stories yet; only KB
   documents (SRS, business docs). The strategy orders functional areas of
   the documents.
2. **Joining late.** The project is 50–60% built, many stories are `done`
   and untested. The strategy orders that backlog and the rest.

When tickets change later, the strategy must re-link itself where it can and
flag what needs re-grounding, and in auto mode the Tester agent re-grounds
it by itself, including re-ordering (owner choice, see O4).

## Owner answers

| # | Answer |
|---|---|
| O1 | It lives in the Tester's own menu. The Test Report menu already is the `tester` kind's menu (`kinds.MENU["tester"]`, `ui.MENU_PATH[TESTER] = "/ui/tests"`), so it goes there. |
| O2 | Both readers: people first, then the machine uses the order. |
| O3 | Must support both docs-only (no missions/US yet) and missions/US already split; follow how the BA kind works (cites `[doc-id §section]`, revisions, `--amend`). |
| O4 | In auto mode the agent may change priorities, not only re-pin, when it has evidence and a fresh-context reviewer agrees (option b). |
| O5 | Approach A: a new section of the existing `<repo_id>-test` document. |

## Goals

1. A strategy file in the tester repo, from a scaffolded template, with a
   machine-readable **Priority order** table and free-text sections for
   people.
2. A row targets a mission id, a story id, **or** a KB document area
   `[doc-id §section]`, so it can be written before the BA has split work.
3. Stories are matched to rows **at read time** (no stored mapping): by id,
   then by parent mission, then by the `[doc-id §section]` citations the
   story and its mission already carry. New and re-scoped tickets re-link
   with no edit.
4. Rows pin what they were written against; `kb test stale` reports rows and
   test case specs that drifted, on demand and on a schedule.
5. `kb strategy lint`, Q1 review, ingest as section `strategy` of
   `<repo_id>-test`, publish by PR like reports.
6. Hub: Strategy on top of `/ui/tests`, full page `/ui/tests/strategy` with
   computed order, coverage gaps and drift.
7. Machine order: `kb test next` and `/tester-test-story` with no argument.
8. Auto: `pick_tester` re-grounds the strategy before testing, and
   `/tester-strategy --amend` runs unattended.

## Non-goals

- Executing non-functional tests (load, security, cross-browser). The
  strategy may *describe* them in its test-types table; running them stays
  out of scope as in the tester role design.
- Scheduling with dates or effort (no Gantt). The optional rounds/waves
  section is prose for people.
- A strategy per mission or per story. One strategy per tester repo, i.e.
  per BA repo (the tester role allows exactly one tester repo per BA repo).
- Editing BA tickets or missions from the tester side.

## Anti-goals

- The strategy **gates** testing. No strategy, or a stale one, never stops
  `/tester-test-story <story>`; it only warns. A Tester joining late must be
  able to test on day one.
- A stored story→row mapping that someone has to keep in sync.
- Auto re-ordering that people cannot see. Every auto re-order is visible on
  the hub until a person revises the strategy (D8).
- A second publish pipeline next to the one `<repo_id>-test` already has.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | New section `strategy` in the existing `<repo_id>-test` document | Reuses `kb report-ingest`, publish workflows, Q1 and hub read path. Strategy and reports share one publish revision — fine, same owner. | **Chosen** |
| B | Separate document `<repo_id>-strategy` | Own lifecycle, but a second ingest, workflow, hub read path and kind suffix for no user-visible gain. | |
| — | Strategy in the BA repo | Tester cannot write the BA repo, and test order is the Tester's call. | dropped |
| — | Ingest as a plain KB document | The order table is not linted and the machine cannot read it. | dropped |

## Design

### D1. File and template

`docs/test-strategy.md` in the tester repo, scaffolded from a new
`templates/init/test-strategy-template.md` as `docs/templates/test-strategy.md`
(next to `test-cases.md` and `test-report.md` in `TESTER_TEMPLATES`). The
Tester copies it to `docs/test-strategy.md`; the skill does that on first
run.

```
# Test strategy — <product>
> Revision: 1
> Plan: <ba-repo-id>

## Scope & objectives
## Test levels & types
| Type | In scope | Tool | Runs on | Notes |
## Priority order
| Rank | Target | Pin | Risk | Why | Types |
|---|---|---|---|---|---|
| 1 | M-checkout | rev 3 | High | payment path, money | UI, API |
| 1 | [acme:srs §4.2] | — | High | refunds, no mission yet | API |
| 2 | M-checkout-US5 | rev 2 | Low | static page | UI |
## Rounds                      (optional prose: waves of ranks, entry/exit)
## Environments & data         (points at .kb/test-env.yaml, no secrets)
## Entry & exit criteria
## Regression policy
## Risks & mitigations
## Open questions
## KB context                  (kb-context block, as in tickets)
## Change log                  (planrev format)
```

- `> Plan:` names the one BA repo whose missions and stories the ids refer
  to (one tester repo per BA repo, as the tester role enforces). In a
  docs-only project with no BA repo registered yet it is `—`, and lint then
  allows KB-area rows only. *(Call.)*
- `> Revision:` and `## Change log` use `planrev` (same columns `Rev | Date |
  Trigger | What changed | Affected | Review`). Strategy triggers:
  `kb-context`, `plan` (a pinned mission/ticket revision moved), `coverage`
  (stories added to rows), `priority` (ranks changed), `scope`.
- `## KB context` is the same `kb-context:` block tickets use (`kbcontext`):
  `version` pins the hub commit, `refs` lists every `[doc-id §section]` the
  file cites, Priority order targets included. This is what makes doc
  targets drift-checkable with existing code.

### D2. Priority order table

- **Rank**: positive integer, 1 = test first, ties allowed (same tier); or
  `last` = deliberately left to the end (tested after every ranked and
  unranked story, never a `coverage` gap). This is how a Tester keeps a
  story or area out of the order without the finding coming back. *(Call.)*
- **Target**, exactly one of:
  - a mission id `M-<slug>`;
  - a story id `M-<slug>-US<n>` (or a bug id `BUG-<n>`);
  - a KB area `[<repo:doc-id> §<section>]`, qualified like kb-context refs.
- **Pin**: `rev <N>` for a mission/story target (its `> Revision:` when the
  row was written); `—` for a KB area (pinned by the kb-context `version`).
- **Risk**: `High | Medium | Low`. **Why**: one line, cites evidence.
  **Types**: which test types of the types table apply.
- A target appears in at most one row.

### D3. Matching stories to rows (read time)

One pure function (in `testflow` or a new `teststrategy` module; builder's
call), used by the hub, `kb test next`, `kb test stale` and the picker.
Input: parsed strategy, the BA plan as `planstatus` already loads it, and
each story's and mission's cited sections. Output per story: rank (or
none), the matching row, and how it matched.

For each story S, the **most specific** match wins:

1. a row whose target is S's id;
2. else a row whose target is S's mission;
3. else rows whose KB area matches a `[doc-id §section]` S's ticket cites
   (its kb-context refs and inline citations), or, when S's ticket has none
   that match, its mission cites. An area matches a citation of the same
   document when the sections are equal or the area's section is an
   ancestor (`§4` matches `§4.2`). Several matching rows: the best
   (lowest) rank.

Story ordering for the machine:

1. **retests first**: `fix-done` stories and testable bugs (`BUG-<n>`), as the
   tester role already rules (retest before new); among them, by rank, then
   plan order;
2. ranked stories, by rank;
3. unranked stories;
4. `last` stories.

Within a tier (same rank, or the unranked group), the BA plan order
`planstatus` already gives (mission `## Sequencing`, `Depends on`), with a
story never placed before a story it depends on **in the same tier**.
`Depends on` does not pull a story up from a lower tier: the rank means what
the Tester wrote. *(Call.)*

Coverage, computed with the same pass:

- **rows with no story** — normal in docs-only; shown as "no ticket yet";
- **testable stories outside the strategy** — shown, and counted as a
  `coverage` finding by `kb test stale`. Bugs never count: they are retested
  through the retest tier and are not planned in the strategy. *(Call.)*

### D4. Drift — `kb test stale`

New CLI in the tester repo (twin of `kb ticket stale`), text and `--json`
output. Findings:

| Finding | When | Severity |
|---|---|---|
| `broken-target` | a row's mission/story id is not on the hub | error |
| `pin-moved` | a row's `rev N` ≠ the target's current revision | warning |
| `kb-context` | a kb-context ref is stale or broken (reuse `ticketstale._kb_context_refs` / `resolve_refs`) | warning / error |
| `coverage` | a testable story (not a bug) matches no row, `last` rows included | warning |
| `tc-revision` | any `tests/<story>/test-cases.md` `Ticket revision` ≠ the ticket's current revision (the check `testcases.py` already does, run over every spec) | warning |

- Exit codes as `kb ticket stale`: 0 nothing found, 2 warnings only, 1 any error.
- Scaffold `.github/workflows/kb-test-stale.yml`: scheduled, keeps one issue
  up to date the way `kb-doctor.yml` does for `kb ticket stale` (reuse that
  issue-keeping code).
- A finding never blocks testing (anti-goal). The machine still uses the
  last published order; a `broken-target` row is ignored for matching.

### D5. Lint and review

`kb strategy lint [file]` (local, and in `kb-test-lint.yml` when
`docs/test-strategy.md` changes):

- required headings; the Priority order header row verbatim; Rank integer;
  Target one of the three forms; Pin `rev N` for ids, `—` for areas; Risk
  in the vocabulary; no duplicate targets; no template placeholders;
- every KB-area target is in the kb-context `refs`;
- `planrev.check_revision` with the strategy trigger set;
- with the hub reachable: `broken-target` is an error, `pin-moved` a
  warning (same as D4).

Q1: `docs/test-review-rubric.md` gains a **Strategy** axis set — every High
risk area of the scope has a row; each Why cites evidence; Types and Tools
agree with `.kb/test-env.yaml`; nothing in-scope is silently missing; a
reorder in an amend states what evidence changed. The senior-tester review
gates the PR as for test cases.

### D6. Ingest and publish

`kb report-ingest` (`testingest.run`) ships `docs/test-strategy.md` as
section `strategy` (group `strategy`), before the story groups, only when it
is lint-clean; otherwise it is listed as skipped with the reason, and the
stories still ship. Images, if any, follow the report asset path. Publish is
unchanged (`kb-publish-request-tester.yml` → `kb-publish-tester.yml`).

### D7. Hub — Test Report menu

The menu label stays **Test Report** (the owner's term); `/ui/tests` gets:

- a **Strategy** panel on top: revision, date, top ranks with their target,
  matched-story count and test status, plus badges `needs re-grounding`
  (any D4 finding on a row) and `auto-reordered (rev N)` (D8). No strategy
  published: a one-line empty state, the story list below unchanged.
- `/ui/tests/strategy`: the rendered document, then the computed tables —
  order (rank → target → matched stories with status, how each matched),
  rows with no story, testable stories outside the strategy, drift
  findings. Read-only, built from the federation like the other test pages.
- the story page shows the story's rank and matching row.
- several BA repos on one hub → one Strategy panel per published strategy,
  each labelled by its `> Plan:`; `/ui/tests/strategy?repo=<tester-repo-id>`.

### D8. Machine order and auto

**Phase 2 — `kb test next`.** JSON/text list of testable stories in D3
order, each with rank, row and match kind (`id | mission | area |
outside`). `/tester-test-story` with no argument proposes the first one and
asks; with an argument it behaves as today. No strategy: plan order, with a
warning.

**Phase 3 — auto** (lands with tester `kb auto`, tester role phase 3).
`pick_tester`, mirroring `pick_ba` (fix what blocks before new work):

1. `kb test stale` has strategy findings (`broken-target`, `pin-moved`,
   `kb-context`, `coverage`) → task `tester-strategy:--amend`;
2. else the first story of `kb test next` → `tester-test-story:<story>`
   (its existing update step handles that story's `tc-revision`);
3. keys in `skip` are passed over, as in `pick_ba`, so a failing amend does
   not loop.

`/tester-strategy --amend` in Auto mode (written like `ba-mission-plan`'s):

- may re-pin, re-point a row whose id was renamed or split (by the
  citations), add rows for uncovered stories, **and change ranks** when the
  evidence supports it **and** the reviewer agrees (O4);
- each change is one `**Auto decision:**` line under `## Change log`; a
  fresh-context reviewer gets the rows, the evidence and the pick and
  answers agree/object; on an objection decide once more. A re-pin,
  re-point or added row then goes ahead (as in `ba-mission-plan`); a **rank
  change** objected to twice is dropped, the rank stays, and the Auto
  decision line records the proposal for the Tester;
- an uncovered story the agent judges not worth a rank is added as a
  `last` row, so the `coverage` finding clears and the loop stops;
- the change-log row's Review cell starts with `auto`; a rank change adds
  the `priority` trigger;
- lint, Q1, PR on `auto/strategy`, merge publishes;
- hub badge `auto-reordered (rev N)` shows while any change-log row since
  the last row whose Review does not start with `auto` has trigger
  `priority`. A person's revision clears it.

### D9. Skill `/tester-strategy`

New skill (Claude Code, Copilot, Cursor, like the other tester skills;
body in `templates/init/bodies/tester-strategy.md`):

- **New**: asks scope and `> Plan:`; grounds with `kb_search`
  (`kinds=["kb","ba"]`) the way `ba-mission-plan` grounds; reads hub status
  (`planstatus`): missions/stories that exist, which are `done` and
  untested. Docs-only → rows are KB areas; plan exists → mission/story
  rows, KB areas for scope no mission covers yet; joining late → proposes
  the untested `done` backlog by risk first. Builds the kb-context block
  (`kb context new`). Runs lint, Q1, opens the PR.
- **`--amend`**: reads `kb test stale --json`, proposes one change per
  finding, the Tester approves (or Auto mode decides), bumps revision,
  change log, lint, Q1, PR.

## Phases

1. **People (1.38.0)**: template, `kb strategy lint`, Q1 axes, ingest
   section, hub panel + `/ui/tests/strategy` + story rank, D3 matching,
   `kb test stale` + scheduled workflow, `/tester-strategy` (new and
   `--amend`, attended).
2. **Machine order**: `kb test next`, `/tester-test-story` with no argument.
3. **Auto**: `pick_tester` steps, Auto mode of `/tester-strategy --amend`,
   `auto-reordered` badge. Ships with tester `kb auto`.

The first implementation plan covers **phase 1 only**. Phases 2 and 3 must
work on cloud like BA/Dev auto does; there the hub is reached through
`HubApi`, which today serves `plan_next`, `registry_entry` and `resolve`
only. Those phases add the hub API routes they need (strategy order and
drift for a tester repo) with an older-hub fallback, planned with them.
*(Call.)*

## Constraints

- Pure parsing and matching (text in, results out), like `missionnext` and
  `testcases`; hub access at the edges.
- Section and route names checked like the existing test pages
  (`planstatus.safe_name`); `strategy` cannot clash with story ids.
- Never cut: lint before publish, Q1 before PR, no secrets in the file
  (environments point at `.kb/test-env.yaml`).

## Left to the builder

- Module split (`testflow` vs new `teststrategy`), exact CLI names.
- How a ticket's inline citations are read on the hub (reuse what
  `ticketstale` / `ticketcheck` already parse).
- Hub template layout (follow `tests.html` / `plan_mission.html`).
- Exact rubric wording of the Strategy axes.
- Whether `kb-test-stale.yml` reuses `kb-doctor.yml`'s job or is its own file.

## Calls made in this document (owner to check)

- **Most specific match wins** (story id > mission > KB area), not "highest
  rank wins" as discussed in chat: otherwise a Tester could never rank one
  low-risk story below its high-risk mission. Among several KB areas, the
  best rank wins.
- Ancestor sections match (`§4` covers `§4.2`).
- Ties in rank are allowed; ties fall back to BA plan order.
- Menu label stays "Test Report".
- File path `docs/test-strategy.md`; `> Plan:` names the BA repo.
- A stale strategy keeps being used by the machine; only `broken-target`
  rows are ignored.
- `coverage` (story outside the strategy) is a drift finding, so auto
  re-grounds when new stories become testable.
- The `auto-reordered` badge clears only on a human revision.
- Builder-check calls: rank `last` (deliberate exclusion, clears `coverage`,
  stops the auto loop); bugs not in `coverage`, retested first; retests
  (`fix-done`, bugs) before ranks, as the tester role rules; `Depends on`
  orders inside a tier only; a twice-objected auto rank change is dropped
  (O4 says "reviewer agrees"); `> Plan:` is one BA repo or `—`; one panel
  per strategy on a multi-BA hub; first plan = phase 1, phases 2–3 add hub
  API routes for cloud.
