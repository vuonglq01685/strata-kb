# Tester role — system and integration tests per story (design)

Date: 2026-11-14 · Size: project (several parts, phased) · Version: 1.36.0 → 1.37.0 (phase 1)

## Intent

Today a ticket is `done` the moment the Dev's `-svc` history row for it is
published (`planstatus.py`, `missionnext.done_ids_from_history`). That is
"done in code": nobody has run the story end to end on a real environment.
Testing by hand costs the team too much. The owner wants a fifth role, the
**Tester**, who:

- takes stories that are `done` (or `fix-done`), runs system and integration
  tests against the story's acceptance criteria, through the UI (Playwright
  MCP, then Playwright scripts) and through the API;
- before closing a story, runs the whole regression suite; a regression
  failure is logged as a bug;
- closes the story when nothing fails, or reopens the guilty child ticket so
  the Dev fixes it;
- leaves a test case specification, a reusable regression script set and a
  test report per round, each in a standard template, reviewed by a senior
  tester agent, published to the hub through a PR like a BA publishes tickets.

The owner cares most about **review of what matters**: no test case, script or
report reaches the hub, and no story is reopened, without an independent
review.

## Goals

1. New repo kind `tester` (`kb init --kind tester`), with its own scaffold,
   skills and `kb auto` support, alongside `hub|child|ba|dev`.
2. A guided slash command to declare the test environment (FE, BE/API, DB,
   seed/reset scripts, test accounts, deploy-version check) and verify it.
   The Tester never clones product code.
3. Ticket lifecycle extended: `ready → done → testing → closed`, with
   `testing → reopened → fix-done → testing` on failure. All four new states
   are **derived** from published data and claims, like `done` is today.
4. Test at **parent-story level**: a story is testable only when every child
   ticket is `done`/`fix-done`; a failure reopens only the guilty child.
5. Test case specifications in an industry-standard template (ISO/IEC/IEEE
   29119-3 test case specification + ISTQB design techniques), linted.
6. Exploration with Playwright MCP, then one Playwright/API script per test
   case, kept as a growing regression suite in the `tester` repo.
7. Regression run of the whole suite before a story closes; failures logged
   as bugs.
8. Flaky-test controls so a story is never reopened by a flaky script or a
   broken environment.
9. Two senior-tester agent reviews (Q1 cases + scripts, Q2 report), with the
   Dev convergence rule.
10. Test reports in a standard template; screenshots go to the hub asset
    store, the report keeps the reference. Published by PR as
    `<repo_id>-test`.
11. Hub **Test Report** menu (Q&A-style list) linked both ways with tickets.
12. Dev side: reopened tickets are picked first, the report is the fix's
    input, the fix yields `fix-done`.

## Non-goals

- Performance / load, security and accessibility testing.
- Cross-browser or device matrix: Chromium only in phase 1.
- Unit tests (the Dev's plan already makes those test-first).
- Deploying the product to the test environment (the team's CI does that;
  the Tester only checks what is deployed).
- Logins through SSO, MFA or captcha (phase 1: user/password only).
- Manual status overrides on the hub (status is derived; change it with a new
  report).
- Reopening a `closed` story: once closed it stays closed (O15).

## Anti-goals (a failure even if it works)

- A story reopened by a flaky script, a down environment or a not-yet-deployed
  commit.
- A story `closed` while any of its ACs is unverified (flaky).
- A test case, script or report published, or a story reopened, without Q1/Q2
  passing.
- A secret (DB URL, password, token) in git, in a report, in a screenshot
  reference or on the hub.
- A destructive DB reset/seed run against anything but the declared test DB.
- Two Testers testing the same story at once, or two rounds sharing one test
  environment at once.
- A second source of truth for ticket status.

## Decisions made with the owner

| # | Decision |
|---|---|
| O1 | Tester role exists because "done" is code-only and manual testing is costly. |
| O2 | Statuses: Dev `done` → Tester `testing` → `closed` (no bug) or `reopened` (bug) → Dev fixes → `fix-done` → Tester retests. |
| O3 | Test environment is pre-built and declared once by a slash command at init (FE, BE for API tests, DB for setup scripts/data, "everything needed"). No cloning of product code. |
| O4 | Explore with Playwright MCP, then write scripts; scripts are the regression suite. |
| O5 | Hub gets a new **Test Report** menu, Q&A-like, linked to tickets. Reports follow a standard template with clear headings. |
| O6 | Screenshots go to the asset store; the report keeps only the path, like documents. Reports publish when the Tester's PR merges, like BA tickets. |
| O7 | Tester runs unattended (`kb auto`). Every test case is reviewed by a **senior tester, who is an agent**. |
| O8 | Review rounds converge like Dev: at the last round, no BLOCKER and only 1–2 SUGGESTED → pass. |
| O9 | Test at parent-story level. |
| O10 | Test case template follows an industry standard. |
| O11 | Out of scope: performance, security, multi-browser (Chromium only). |
| O12 | Build approach 1 (below). |
| O13 | The test site is deployed automatically by CI on every merge to `main`. |
| O14 | Test accounts log in with user/password; API uses cookie or bearer token. |
| O15 | A `closed` story stays `closed`, even if the BA later amends it; a change after close needs a new ticket. |
| O16 | After every TC of the parent story passes, and before the story closes, the whole regression suite runs; any regression failure is logged as a bug. |

## Approaches

1. **`tester` repo, status derived from published data (chosen).** Reports
   and cases publish as `<repo_id>-test`; `planstatus` derives `testing` from
   hub claims, `closed`/`reopened` from the latest published report,
   `fix-done` from the Dev's history. One source of truth; every reopen traces
   to a reviewed, merged report; same shape as `done` today. Cost: derivation
   reads more sources; no manual override.
2. **`tester` repo, status stored in a hub DB table.** Easy queries and admin
   override, but two sources of truth (PR merged vs status written can
   disagree), plus a write API, a role and drift handling. Works against "merge
   the PR to publish".
3. **Tester inside the BA repo.** Least scaffold, but the BA repo would carry
   the test env, Playwright and scripts; BA and Tester auto loops collide;
   BA CODEOWNERS would review test code. Mixes roles.

Dropped early: Tester inside a Dev repo (owner wants no cloning, and a parent
story spans several Dev repos).

The owner chose **1**.

## Design

### D1. Repo kind `tester`

- Name: `tester`, not `qa`. `qa` already means ticket Q&A in this codebase
  (`.kb-qa/`, `ticketqa`, `web/qaui.py`, `autorun/qa.py`, claim phase
  `waiting-qa`, result `blocked-qa`).
- `initcmd.KINDS` gains `tester`; `kinds._CONFIG_TO_HUB` maps
  `tester → "tester"`; `HUB_KINDS` gains it; `MENU["tester"] = "Test Report"`.
- Exactly **one `tester` repo per BA repo** in phase 1; registry lint refuses
  a second one for the same BA repo.
- Scaffold (mirrors `dev`): `config-tester.yaml`, `QUICKSTART-tester.md`,
  `codeowners-tester`, `.mcp.json` with `strata-kb` **and** a Playwright MCP
  server entry, slash commands for Claude Code / Copilot / Cursor, `.gitignore`
  for `.env`, Playwright output (`test-results/`, `playwright-report/`,
  traces), the local run log and fetched tickets.
- Layout:

```
.kb/config.yaml                  kind: tester
.kb/test-env.yaml                the environment (D2), no secret values
.env                             secret values (git-ignored)
tests/<story-id>/test-cases.md   test case specification (D4)
tests/<story-id>/tc<NN>.spec.ts  one script per test case (D5)
tests/fixtures/, tests/seeds/    shared helpers (login fixture), seed data
reports/<story-id>/R<n>.md       published report of round n (D6)
reports/<story-id>/assets/       screenshots referenced by R<n>.md
docs/test-review-rubric.md       Q1/Q2 criteria (+ .local.md override)
```

- Hub account role `tester` added to `serving/accounts.ROLES` (sees Test
  Report and tickets like `dev`; not Registry). The `accounts` table has a
  `CHECK(role IN ...)`: adding a role needs a table migration.

### D2. Test environment — `/tester-env-setup`

Guided command (skill + `kb test-env` CLI underneath) that asks for each item,
writes `.kb/test-env.yaml`, and verifies it.

```yaml
name: staging
apps:                         # one entry per Dev repo the stories touch
  - repo: shop-fe
    url: https://staging.example.test
    version_check: { url: https://staging.example.test/version, field: commit }
  - repo: shop-api
    api_base: https://api.staging.example.test
    version_check: { url: https://api.staging.example.test/health, field: git_sha }
db:
  url_env: TEST_DB_URL        # name only; value lives in .env / CI secret
  check: tests/seeds/check.sh # exits 0 when the DB answers
  reset: tests/seeds/reset.sh
  seeds: { checkout-basic: tests/seeds/checkout-basic.sh }
accounts:                     # role → env var names, user/password login (O14)
  buyer:  { user_env: TEST_BUYER_USER, password_env: TEST_BUYER_PASSWORD }
  admin:  { user_env: TEST_ADMIN_USER, password_env: TEST_ADMIN_PASSWORD }
api_auth: cookie              # or: bearer (token obtained by the login fixture)
retries: 3                    # D5 flaky control
```

Rules:

- Only env var **names** in the file; the CLI refuses a value that looks like
  a secret (URL with credentials, long token) in any field.
- DB access is through the user's own scripts (any engine: `psql`, `mysql`,
  `mongosh`, …). kb adds no DB driver. kb runs `check`/`reset`/seeds with
  `$<url_env>` exported and nothing else DB-related. kb cannot stop a script
  from connecting elsewhere: the guard below is best-effort, and Q1 reviews
  the seed scripts.
- Guard: `reset`/seeds run only through `kb test-env reset|seed`; refused when
  `name` is `production`/`prod` or `$<url_env>` matches an optional
  `protected_urls` list.
- `version_check` is required for `kb auto` (preflight refuses `none`); a
  manual run with `none` asks the Tester to confirm the deploy.
- Login: the scaffold ships a Playwright login fixture for a user/password
  form (`tests/fixtures/login.ts`); `/tester-env-setup` fills its selectors by
  exploring the login page through Playwright MCP.
- Verify step: FE URL answers, API base answers, `check` passes, `reset` runs,
  each seed loads, each account logs in through the fixture, each
  `version_check` returns a commit. Each failure is printed with its item.

### D3. Lifecycle and derived status

```
ready ──Dev──► done ──Tester claim──► testing ──R<n> PASS──► closed (final)
                                         │
                                         └─R<n> FAIL──► reopened (guilty child)
                                                          │ Dev fix
                                         testing ◄── fix-done
```

Derivation in `planstatus` (one place, used by hub UI, `kb mission next`,
pickers):

| Status | Derived when |
|---|---|
| `done` | unchanged (id in the Dev's `-svc` history) and no published report yet |
| `testing` | a Tester claim on the parent story is held (D7) |
| `closed` | latest published report of the story has verdict `PASS`. **Final** (O15): no later revision, child or Dev row changes it |
| `reopened` | latest published report has verdict `FAIL`; applies to the children it names as guilty; the parent shows `reopened` too |
| `fix-done` | a reopened child whose Dev history records the fix of that round (below) |

- **Fix round in Dev history.** A `-svc` history row is one row per ticket
  today (no round, no time), so "newer row" cannot be told. The fix handover
  records the round it answers: `kb svc note <ticket> --fixes R<n>`, stored
  in the row's refs as `fix:R<n>`. `fix-done` = latest report `R<n>` reopened
  the child and the child's row carries `fix:R<n>`.
- **Closed is final.** `kb ticket lint` (BA repo) refuses an amend of a
  ticket whose story is `closed` on the hub, with "story is closed — write a
  new ticket" (hub unreachable → warning, not error).
- **Testable story.** The Tester picker offers a parent story (or an
  unsplit story) when every child is `done` or `fix-done` and none is
  `reopened`. `fix-done` stories come before `done` ones.
- **Only `PASS` and `FAIL` rounds are published** and get a round number.
  A run that ends `BLOCKED-ENV` or `INCOMPLETE` (D5) is kept only in the local
  run log; the story's status does not change and it is retried later.
- **Deploy check before claim → testing.** The site is deployed from `main`
  on every merge (O13). For each Dev repo of the story, the environment's
  `version_check` commit must equal or descend from the `source_commit` of
  that repo's latest publish (`publish.py` records it). Ancestry is checked
  through the GitHub compare API with the Tester's `gh` login (read access to
  the Dev repo, no clone). Not deployed yet → skip the story this pass.
- Bug tickets (`BUG-<n>`) follow the same flow: steps to reproduce become the
  negative test case, expected result the oracle.

### D4. Test case specification — `tests/<story-id>/test-cases.md`

Based on ISO/IEC/IEEE 29119-3 test case specification; techniques per ISTQB
(equivalence partitioning, boundary value, decision table, state transition,
use case).

```
# Test cases — <story-id> — <story title>
> Story: <id> · Children: <id.repo>, … · Ticket revision: <n>

## Scope & traceability
| AC | Test cases |
|---|---|
| AC1 | TC-01, TC-02 |

## TC-01 — <one-line title>
| Field | Value |
|---|---|
| Objective | Verify AC<k>: … |
| Type | UI · API · UI+API |
| Priority | P1 · P2 · P3 |
| Technique | EP · BVA · decision table · state transition · use case |
| Preconditions | … |
| Test data | seed `<name>`, values … |
| Steps | 1. … 2. … |
| Expected result | observable outcome (UI text, API status/body, DB row) |
| Script | tests/<story-id>/tc01.spec.ts |
| Automation | automated · manual (reason) |

## Change log
## Review record
```

`kb testcase lint` (new, CI-gated in the `tester` repo):

- every AC of the story has ≥1 positive TC;
- every AC with a value, limit, format or state constraint has ≥1 negative or
  boundary TC;
- every `### Alternate / exception flows` entry of the ticket has ≥1 TC;
- every TC names exactly one existing script; no orphan scripts;
- `Ticket revision` matches the hub's current revision (else update the
  cases before the next round);
- no field left as template placeholder.

### D5. Scripts, regression and flaky-test controls

Script rules (lint + Q1 review): Playwright Test; role/text/testid locators
(no brittle CSS/XPath); no `waitForTimeout`/fixed sleeps; web-first
assertions; every test seeds its own data and does not depend on order; API
checks through Playwright `request`; trace, screenshot and video kept on
failure. Credentials read from env only, login through the shared fixture.

**Environment lock.** One round runs on one test environment at a time: the
hub holds a lock per environment `name` next to claims (`claims.db`), taken
before the preflight and released after the regression run. Taken → skip the
story this pass.

Run pipeline per round, in order:

1. **Preflight**: env health (FE, API, `check`) and deploy check (D3); record
   each app's commit. Fails → `BLOCKED-ENV`.
2. **Story run**: every TC of the story (re-test rounds rerun all, not only
   the failed ones).
3. **Clean retry**: a failing TC is rerun on a reset + reseeded DB up to
   `retries` (default 3). Always fails → stable failure. Mixed → flaky: the
   AC is *unverified* (never pass), the script goes back to the Tester; the
   Dev is not involved.
4. **MCP confirmation**: for each stable failure the agent replays the steps
   by hand through Playwright MCP. Reproduced → defect. Not reproduced →
   script defect, back to the Tester.
5. **Regression run** (O16), only when every story TC passed: run the scripts
   of every `closed` story, with the same retry and MCP confirmation. Each
   confirmed regression failure becomes a *regression defect* in the report
   (D6) and is logged as a bug (D6). It does not reopen the old story (closed
   is final) and does not stop this story from closing.
6. **Post-check**: re-read every `version_check`. A commit changed during the
   round (CI deployed) → the round is void, `BLOCKED-ENV`.

Round outcome:

| Outcome | When | Published |
|---|---|---|
| `PASS` | every story TC passed, steps 1 and 6 clean | yes → `closed` |
| `FAIL` | ≥1 confirmed story defect | yes → `reopened` |
| `INCOMPLETE` | no defect, but ≥1 flaky / script-defect TC | no (local run log) |
| `BLOCKED-ENV` | step 1 or 6 failed | no (local run log) |

A `FAIL` round skips the regression run (step 5): the regression runs on the
round that will close the story.

### D6. Test report — `reports/<story-id>/R<n>.md`

Based on ISO/IEC/IEEE 29119-3 test completion report + incident report fields
(aligned with `bug-template.md`).

```
# R<n> — <story-id> — <story title>
> Story: <id> · Round: <n> · Verdict: PASS | FAIL
> Environment: <name> · <repo> <commit> · … · Date: YYYY-MM-DD
> Test cases: tests/<story-id>/test-cases.md @ <tester commit>

## Summary            <passed>/<total> TCs, <n> defects, <m> regression defects
## Results by AC
| AC | TC | Result | Script | Evidence |
|---|---|---|---|---|
| AC1 | TC-01 | PASS | tests/…/tc01.spec.ts | ![](assets/tc01.png) |
## Defects            one per confirmed story failure:
### D1 — <symptom>   Guilty: <child id> · Severity · Priority
  Steps to reproduce · Expected · Actual · Evidence · Environment
## Regression         suite size, passed, failed
## Regression defects one per confirmed regression failure:
### RD1 — <symptom>  Story: <closed story id> · TC · Severity · Priority
  Steps to reproduce · Expected · Actual · Evidence · Environment
## Environment & data seeds used, deviations
## Review record
```

- Evidence images live in `reports/<story-id>/assets/` (PNG/WebP, the hub's
  asset convention). At ingest they are hashed and rewritten to
  `assets/<sha256>.<ext>` and uploaded to the asset store, reusing
  `planingest`'s bug-attachment path (`buglint.attachment_images`,
  `rewrite_images`, symlink/outside-folder refusal).
- **Logging a regression defect as a bug.** Bugs are authored in the BA repo
  (`tickets/bugs/BUG-<n>.md`), which the Tester cannot write. Each published
  `RD<k>` shows on the hub as an open bug candidate (Test Report menu, and in
  `kb mission next --from-hub` for the BA). `/ba-bug-report --from-report
  <story> RD<k>` drafts `BUG-<n>` prefilled from it (steps, expected, actual,
  evidence, environment); the BA auto loop picks open candidates like it
  picks Q&A. The candidate shows as logged once a published bug cites it
  (`> From report: <story> R<n> RD<k>`).
- `kb report lint`: template headings present; verdict matches the tables
  (any story FAIL → `FAIL`, else `PASS`; `INCOMPLETE`/`BLOCKED-ENV` never in
  a committed report); every defect has a guilty child that belongs to the
  story; every regression defect names a `closed` story; every image exists;
  no env var value or credential-looking string in the text.

### D7. Claims for the Tester

Reuse `ticketclaim` (`claims.db`). Today `web/claim_api.py` sets `repo` from
the BA repo that holds the ticket and refuses parent stories. For the Tester:

- key stays `(BA repo, story id)`; a new `role` column (`dev` | `tester`)
  keeps Dev claims on child tickets and Tester claims on the parent story
  apart. One open Tester claim per story.
- the take API accepts a parent story when `role = tester`.
- Tester phases: `claimed`, `cases`, `scripts`, `run`, `report`, `review`,
  `publishing`. A held Tester claim is what D3 reads as `testing`.
- the environment lock (D5) is a separate table in the same DB, keyed by env
  `name`, same TTL and lazy-expiry rules.
- exit code 3 on taken/lost, as today.

### D8. Reviews Q1 and Q2 (senior tester agent)

| | Where | Looks at |
|---|---|---|
| Q1 | after cases + scripts, before the run | each AC covered; TC matches AC intent; techniques fit; negative/boundary/alternate flows; script rules; data isolation; seed scripts touch only `$<url_env>` |
| Q2 | after the run, before the PR | verdict follows evidence; every defect reproduced (MCP) and assigned to the right child; regression defects confirmed; flaky handled per D5; no secret leaked |

- Separate subagent context from the author, never the same agent.
- Convergence as `2026-11-01-review-convergence-design.md`: round 1
  exhaustive, round 2 verification only (blocks only on round-1 items,
  regressions of the fix, any BLOCKER). Pass when no BLOCKER and ≤2 SUGGESTED
  remain; carried SUGGESTED rows go to `## Review record`.
- Still a BLOCKER after round 2 → `AUTO-RESULT: failed test-review`, the task
  stops for a human.
- Criteria in `docs/test-review-rubric.md` (+ `.local.md` override).
- In auto mode the report PR auto-merges once Q2 passed and CI (`kb testcase
  lint`, `kb report lint`) is green, under the existing merge policy
  (`ghpolicy`, branch protection required).

### D9. Publish — `<repo_id>-test`

`kb report-ingest` (twin of `kb plan-ingest`): pure function of the working
tree, no LLM, no hub. One group per story: its `test-cases.md` and every
`R<n>.md` (latest last). Only lint-clean cases and reports with a Q2-passed
review record ship. Published with `kb publish` / `kb ci-publish` like the
BA plan. Scripts are not published (they stay in the `tester` repo); the
report cites their paths and the `tester` commit.

### D10. Hub UI

- **Test Report** menu (`/ui/tests`), list like `questions.html`: story,
  round, verdict, status, date, filters `all · testing · reopened · closed ·
  bug candidates`.
- Report page renders `R<n>.md` with asset images; links to the ticket page,
  the test case spec and, per regression defect, the closed story and the
  logged bug.
- Ticket page (`plan_ticket.html`) shows the derived status and links to every
  report round; mission/plan pages show the new statuses.
- `kb mission next --from-hub` shows the new statuses and open bug candidates.

### D11. Dev and BA side

- Dev picker (`autorun/picker.py`): `reopened` children before `ready`.
- `/dev-implement-ticket` on a reopened child: fetches the latest report
  (`kb report fetch <story>`, writes `docs/impl/<id>/report-R<n>.md`,
  git-ignored like `ticket.md`) and starts from its defects (bug-fix path,
  `dev-fix-bug` style), not from a fresh design.
- `/dev-handover` writes `kb svc note <ticket> --fixes R<n>` → `fix-done`.
- BA: `/ba-bug-report --from-report`, closed-story amend refusal in
  `kb ticket lint` (D3), BA auto loop picks open bug candidates.

### D12. `kb auto` for `tester`

- `autorun` accepts kind `tester` (`runner.py` checks `ba`/`dev` today).
- Preflight adds: `test-env.yaml` present and verified, every
  `version_check` set, Playwright + Chromium available, merge policy.
- Loop: pick testable story → env lock → deploy check → claim → cases (new
  story) or update (retest) → Q1 → run (D5) → report → Q2 → PR → merge →
  publish → release claim and lock. New `AUTO-RESULT` kinds: `blocked-env`,
  `incomplete`, `failed test-review`.

## Phases

1. `tester` kind, scaffold, `/tester-env-setup` + `kb test-env`, test case
   template + `kb testcase lint`, report template + `kb report lint`,
   `kb report-ingest`, publish, claims `role` + env lock, derived statuses,
   Test Report menu, Q1/Q2 skills, regression run — run by hand.
2. Dev and BA side: reopened picking, `kb report fetch`, `--fixes R<n>`,
   `fix-done`, `/ba-bug-report --from-report`, closed-amend refusal.
3. `kb auto` for `tester` (preflight, loop, results), BA loop picks bug
   candidates, guides EN + VI, PDFs.

## Left to the builder

- Exact CLI names (`kb test-env`, `kb testcase lint`, `kb report lint|fetch`,
  `kb report-ingest`) and module split.
- Playwright MCP server package and pin in the scaffold `.mcp.json`.
- How the GitHub compare call is made (reuse `ghrest`).
- Hub template layout of the Test Report pages (follow `questions.html`).
- Exact rubric wording for Q1/Q2.
- The local run log format for `INCOMPLETE`/`BLOCKED-ENV` runs (reuse the
  `autorun/runlog.py` record where it fits).
- Running the regression suite in parallel Playwright workers.

## Calls made in this document (owner to check)

- Kind and role named `tester` (not `qa`, which already means Q&A); menu
  label "Test Report"; document `<repo_id>-test`.
- One `tester` repo per BA repo in phase 1.
- Only `PASS`/`FAIL` rounds are published; `INCOMPLETE` (flaky only) and
  `BLOCKED-ENV` stay local and do not change status.
- One round per test environment at a time (hub lock); a deploy during the
  round voids it.
- DB through the user's own scripts, any engine, no new driver; the reset
  guard is best-effort.
- A regression failure does not reopen the old story and does not block the
  current story from closing; it becomes a bug candidate the BA turns into
  `BUG-<n>`.
- Bug tickets (`BUG-<n>`) go through the same test flow.
- `retries` default 3; a flaky AC counts as unverified, never as pass.
- Scripts stay in the `tester` repo and are not published to the hub.
- Fix round recorded as `fix:R<n>` in the Dev history row refs.
- `kb ticket lint` refuses amending a ticket whose story is `closed`.
