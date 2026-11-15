# Tester loop, block 1 — Dev and BA side (design)

Date: 2026-11-15 · Size: project (block 1 of 3, one release 1.37.3) ·
Version: 1.37.2 → 1.37.3 (bumped by this block, tagged after block 3)

Builds on `2026-11-14-tester-role-design.md` (D3 lifecycle, D6 report and bug
candidates, D11 Dev and BA side). That design is approved; this document
fills in what D11 left open. Terms are reused from it: guilty child,
`reopened`, `fix-done`, `closed`, `R<n>`, `RD<k>`, bug candidate.

## Intent

A Tester can now publish a `FAIL` report that reopens the guilty child
ticket, and a regression failure that becomes a bug candidate. Nothing on the
Dev or BA side reacts yet: no Dev picks a reopened ticket, nothing hands the
report to the Dev, nothing records that a fix answers round `R<n>` (the hub
already reads `fix:R<n>`, but no tool writes it), and a bug candidate can only
be logged by hand. The loop "Tester fails → Dev fixes → Tester retests" is
open. Block 1 closes it, by hand and in `kb auto` for BA and Dev. Block 2
(`kb test next`) and block 3 (`kb auto` for tester) build on it.

## Goals

1. `kb report fetch <story> [--round N]` writes a published report and its
   images next to the ticket in a Dev repo.
2. Dev picker: a `reopened` guilty child routed to this Dev repo is picked
   before any `ready` ticket.
3. `/dev-implement-ticket <id>` on a reopened ticket runs a **fix mode**: the
   report's defects are the bug, the `dev-fix-bug` steps apply, no new design.
4. `/dev-handover` in fix mode records `kb svc note … --fixes R<n>` so the
   ticket becomes `fix-done`.
5. `/ba-bug-report --from-report <story> RD<k>` drafts `BUG-<n>` prefilled
   from the regression defect, with `> From report: <story> R<n> RD<k>`.
6. A published bug citing a candidate marks it logged: it leaves the open
   candidates (hub Test Report list, known-failures API, BA picker).
   *(Call: listing candidates in `kb mission next --from-hub` (base D10) is
   not built and stays out of this block.)*
7. BA auto picks open bug candidates (after mission blockers, before drafting).
8. `kb ticket lint` refuses an amend of a ticket whose story is `closed`.

## Non-goals

- Tester auto (block 3), `kb test next` (block 2).
- Cloud-only paths for the Tester (block 3 runs on the Tester's VM).
- Changing how the hub derives statuses (D3 already done in 1.37.0).

## Anti-goals

- A Dev redesigning a story because a test failed: fix mode fixes the named
  defects, nothing else.
- A candidate logged twice: two BA runs must not draft two bugs for one `RD`.
- A `closed` story silently reopened by an amend.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | Fix mode inside `/dev-implement-ticket` (status decides) | One command for picker and Dev; the skill body grows a section | **Chosen** |
| B | New skill `/dev-fix-reopened` | Clean body, but a fourth Dev entry point and a new picker task kind | |
| C | Reuse `/dev-fix-bug` on the child id | `dev-fix-bug` expects a `BUG-<n>` ticket and its template; a story child is not one | dropped |

## Design

### E1. `kb report fetch <story> [--round N] [--out DIR]`

- Reads the published `<story>.R<n>` section from the hub (`testflow`
  `section_text`); default round = latest published; `--round` picks one.
- Writes `docs/impl/<child-id>/report-R<n>.md` when run inside a Dev repo
  with `--child <id>`, else `--out` (default `docs/impl/<story>/`). Image
  refs `assets/<sha>.<ext>` are copied from the `-test` document's `assets/`
  folder next to the file, like `kb ticket fetch` does for plan assets
  (same symlink/outside-folder refusals).
- A provenance line under the title: `> Fetched from hub: <repo>:<doc>
  §<story>.R<n> @ <rev> — do not edit.`
- `docs/impl/*/report-R*.md` and its `assets/` are git-ignored (extend the
  `impl-gitignore.txt` template, as for `ticket.md`).
- MCP tool `kb_report_fetch` mirrors it (as `kb_ticket_fetch` does), so
  cloud Dev sessions can read reports through the hub API. *(Call: the Dev
  auto runs on cloud today; without it fix mode cannot work there.)*
- Errors: unknown story or round → exit 1 with the rounds that exist.

### E2. Dev picker

- `_dev_tasks`: before ready bugs and tickets, yield
  `Task("dev-implement-ticket", <child>)` for every row whose `test_status`
  is `reopened`, routed here (`runnable_here` with reopened instead of
  ready), in plan order. A reopened unsplit story is its own guilty child.
- A reopened row is not blocked by `depends_on` (its deps were done when it
  was built).
- A reopened bug (`BUG-<n>`, or a bug child `BUG-<n>.<repo>`) goes to
  `dev-fix-bug`, which gets the same fix mode (E3) and `--fixes R<n>`
  handover. *(Call: the two ticket shapes differ, so each skill keeps its
  own.)*
- "Reopened is open work" everywhere a Dev ticket is judged finished:
  `autorun/done.all_done`, the runner's `_still_ready_here`, and the hub's
  `web/claim_api.close_done_tickets` (which today closes a Dev claim on any
  row with `status == "done"`, a reopened child included). *(Call: claims
  are not statuses; this is allowed under "no hub status change".)*
- `plan_next` already carries `test_status` (`StoryStatus`); the hub API
  JSON must carry it too (check `HubApi.plan_next` serialises it; add it if
  not).

### E3. Fix mode in `/dev-implement-ticket`

- Trigger: the ticket's hub status (from `kb mission next --from-hub --json`
  or the claim result) is `reopened`. The skill states the mode in its first
  reply.
- Steps: freshness check as today → `kb report fetch <story> --child <id>`
  (latest round `R<n>`) → for each defect whose `Guilty:` is this ticket:
  reproduce (a failing test from the defect's steps/expected/actual) → root
  cause → fix → full suite → `/dev-handover` in fix mode. Defects of other
  children are listed and left alone. A `Regression: yes` defect gets the
  same treatment; its overlap line names the files to look at first.
- Branch `fix/<id>-R<n>`; PR title `fix(<id>): R<n> defects D1, D2`.
- No design/plan stage (anti-goal); the ticket's ACs stay the oracle.
- Auto mode: same steps; `AUTO-RESULT: done` after merge + publish, as today.
- The "Already finished" crash check (in `dev-implement-ticket` and
  `dev-handover`) looks for a history row carrying `fix:R<n>` in fix mode,
  not just any row for the ticket (the original build's row exists).

### E4. `--fixes R<n>` in `kb svc note` and `/dev-handover`

- `kb svc note <svc> --ticket <id> --title … [--refs …] --fixes R<n>`:
  appends `fix:R<n>` to the row's refs (comma-joined, de-duplicated).
  `svcnote.add_note` replaces the whole row today, so `--fixes` (and any
  re-run) must merge the existing row's refs first, keeping earlier
  `fix:R<m>` and domain refs.
- `R<n>` validated: `R[1-9][0-9]*`.
- `/dev-handover` in fix mode passes `--fixes R<n>` (the round from the
  fetched report's file name).
- Hub effect is already built: `missionnext.fix_rounds_from_history` →
  `testflow.story_test_status` → `fix-done`.

### E5. `/ba-bug-report --from-report <story> R<n> RD<k>`

- The round is part of the argument: `RD<k>` is numbered per report, so
  `<story> RD<k>` alone is ambiguous across rounds. *(Call: changes the base
  design's `<story> RD<k>` syntax.)*
- Reads the report (`kb report fetch <story> --round <n> --out <tmp>`),
  takes the RD block: symptom → title,
  steps/expected/actual, evidence images (copied as bug attachments, the
  existing bug image path), environment line, the closed story it broke
  (`Story:`) as the related ticket.
- Adds `> From report: <story> R<n> RD<k>` under the title (new optional
  header line in `bug-template.md`; `buglint` accepts it and checks its
  shape).
- Before drafting: if a published or local bug already cites the same
  `<story> R<n> RD<k>` (or the same failure key `<closed-story>/TC-<k>`),
  stop and name it (anti-goal: no double log).

### E6. Candidate "logged"

- `testflow.known_failures` (or a wrapper) drops a key whose candidate is
  cited by a published bug: scan published bug tickets on the hub for
  `> From report:` lines, map `<story> R<n> RD<k>` → its failure key.
- Affects: Test Report "bug candidates" filter, `/api/tests/known-failures`
  (the Tester's known-failure guard stays as is: a logged-but-unfixed key is
  still a known failure for regression runs — so the API returns both lists
  or a `logged` flag; *call: add `logged: bool` per entry, the hub list
  shows open ones only*), BA picker.

### E7. BA auto picks candidates

- `pick_ba`: after mission blockers, before draft amends, yield
  `Task("ba-bug-report", "--from-report <story> R<n> RD<k>")` (from `KnownFailure.story/round/rd_id`) for each open
  (not logged) candidate whose closed story belongs to this BA repo's plan.
- Source: local hub → `testflow.known_failures`; cloud → the hub API
  `/api/tests/known-failures` (exists; gains `logged`).
- `ba-bug-report` gains an Auto mode section like `ba-ticket-author`'s
  (branch `auto/BUG-<n>`, lint, PR, the merge publishes); the BA merge policy
  is unchanged.

### E8. Closed-story amend refusal

- `kb ticket lint` (BA repo, with hub reachable): an **amend** is a local
  `> Revision:` higher than the revision published on the hub. An amend of a
  ticket whose story (the ticket itself, or its parent story) is `closed` on
  the hub → error `story is closed — write a new story`. A ticket already at
  its published revision is not an amend and passes (CI lints unchanged
  parents too). Hub unreachable → warning.
- A **new child** under a closed parent story is refused the same way: once
  any round passed, every child of the story is `closed`
  (`testflow.story_test_status`), so a new child could never be tested.
  *(Calls: amend = above published revision; the replacement is a new
  story.)*
- Mission amends are not blocked (a mission may add stories).

## Release

- This block bumps 1.37.2 → 1.37.3 and opens the CHANGELOG entry; blocks 2
  and 3 add bullets. Tag `v1.37.3` only after block 3 merges.

## Constraints

- No hub status change; everything reads the existing derivation.
- Cloud Dev auto must work: report fetch through MCP / hub API.
- Every new CLI path validated (`safe_name` for story/child ids, `R<n>`).

## Left to the builder

- Module for report fetch (`ticketfetch`-style new `reportfetch.py` or in
  `testflow`), MCP tool wiring, exact help texts.
- How `bug-template.md` places the new header line.
- Test fixtures (reuse `plan_hub`, `publish_tests`).

## Calls made in this document (owner to check)

- Fix mode lives in `/dev-implement-ticket` (approach A).
- `kb report fetch` has an MCP twin for cloud Dev sessions.
- Reopened tickets ignore `depends_on`.
- Known-failures API gains `logged`; logged keys still guard regression runs.
- BA picks candidates after mission blockers, before ticket drafting.
- Closed-story refusal only for tickets, not missions; amend = local revision
  above the published one; a new child under a closed story is refused too.
- Reopened bugs use `dev-fix-bug`'s own fix mode.
- `--from-report` takes `<story> R<n> RD<k>`.
- Candidates are not added to `kb mission next` in this block.
- Claims treat reopened as open work (hub claim close included).
