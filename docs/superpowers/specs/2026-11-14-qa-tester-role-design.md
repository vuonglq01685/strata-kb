# QA / Tester role — system and integration tests per story (design)

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
- closes the story when nothing fails, or reopens the guilty child ticket so
  the Dev fixes it;
- leaves a test case specification, a reusable regression script set and a
  test report per round, each in a standard template, reviewed by a senior
  tester agent, published to the hub through a PR like a BA publishes tickets.

The owner cares most about **review of what matters**: no test case, script or
report reaches the hub, and no story is reopened, without an independent
review.

## Goals

1. New repo kind `qa` (`kb init --kind qa`), with its own scaffold, skills and
   `kb auto` support, alongside `hub|child|ba|dev`.
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
   case, kept as a growing regression suite in the `qa` repo.
7. Flaky-test controls so a story is never reopened by a flaky script or a
   broken environment.
8. Two senior-tester agent reviews (Q1 cases + scripts, Q2 report), with the
   Dev convergence rule.
9. Test reports in a standard template; screenshots go to the hub asset store,
   the report keeps the reference. Published by PR as `<repo_id>-test`.
10. Hub **Test Report** menu (Q&A-style list) linked both ways with tickets.
11. Dev side: reopened tickets are picked first, the report is the fix's
    input, the fix yields `fix-done`.

## Non-goals

- Performance / load, security and accessibility testing.
- Cross-browser or device matrix: Chromium only in phase 1.
- Unit tests (the Dev's plan already makes those test-first).
- Deploying the product to the test environment (the team's CI does that;
  the Tester only checks what is deployed).
- Manual status overrides on the hub (status is derived; change it with a new
  report).

## Anti-goals (a failure even if it works)

- A story reopened by a flaky script, a down environment or a not-yet-deployed
  commit.
- A test case, script or report published, or a story reopened, without Q1/Q2
  passing.
- A secret (DB URL, password, token) in git, in a report, in a screenshot
  reference or on the hub.
- A destructive DB reset/seed run against anything but the declared test DB.
- Two Testers testing the same story round at once.
- A second source of truth for ticket status.

## Decisions made with the owner

| # | Decision |
|---|---|
| O1 | Tester role exists because "done" is code-only and manual testing is costly. |
| O2 | Statuses: Dev `done` → Tester `testing` → `closed` (no bug) or `reopened` (bug) → Dev fixes → `fix-done` → Tester retests. |
| O3 | Test environment is pre-built and declared once by a slash command at init (FE, BE for API tests, DB for setup scripts/data, "everything needed"). No cloning of product code. |
| O4 | Approach B: explore with Playwright MCP, then write scripts; scripts are the regression suite. |
| O5 | Hub gets a new **Test Report** menu, Q&A-like, linked to tickets. Reports follow a standard template with clear headings. |
| O6 | Screenshots go to the asset store; the report keeps only the path, like documents. Reports publish when the Tester's PR merges, like BA tickets. |
| O7 | Tester runs unattended (`kb auto`). Every test case is reviewed by a **senior tester, who is an agent**. |
| O8 | Review rounds converge like Dev: at the last round, no BLOCKER and only 1–2 SUGGESTED → pass. |
| O9 | Test at parent-story level. |
| O10 | Test case template follows an industry standard. |
| O11 | Out of scope: performance, security, multi-browser (Chromium only). |
| O12 | Build approach 1 (below). |

## Approaches

1. **`qa` repo, status derived from published data (chosen).** Reports and
   cases publish as `<repo_id>-test`; `planstatus` derives `testing` from hub
   claims, `closed`/`reopened` from the latest published report, `fix-done`
   from the Dev's history. One source of truth; every reopen traces to a
   reviewed, merged report; same shape as `done` today. Cost: derivation reads
   more sources; no manual override.
2. **`qa` repo, status stored in a hub DB table.** Easy queries and admin
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

### D1. Repo kind `qa`

- `initcmd.KINDS` gains `qa`; `kinds._CONFIG_TO_HUB` maps `qa → "qa"`;
  `HUB_KINDS` gains `qa`; `MENU["qa"] = "Test Report"`.
- Scaffold (mirrors `dev`): `config-qa.yaml`, `QUICKSTART-qa.md`,
  `codeowners-qa`, `.mcp.json` with `strata-kb` **and** a Playwright MCP
  server entry, slash commands for Claude Code / Copilot / Cursor, `.gitignore`
  for `.env`, Playwright output (`test-results/`, `playwright-report/`,
  traces) and fetched tickets.
- Layout:

```
.kb/config.yaml               kind: qa
.kb/test-env.yaml             the environment (D2), no secret values
.env                          secret values (git-ignored)
tests/<story-id>/test-cases.md   test case specification (D4)
tests/<story-id>/tc<NN>.spec.ts  one script per test case (D5)
tests/fixtures/, tests/seeds/    shared helpers, seed data
reports/<story-id>/R<n>.md       report of round n (D6)
reports/<story-id>/assets/       screenshots referenced by R<n>.md
docs/test-review-rubric.md       Q1/Q2 criteria (+ .local.md override)
```

- Hub account role `qa` added to `serving/accounts.ROLES` (sees Test Report
  and tickets like `dev`; not Registry).

### D2. Test environment — `/qa-env-setup`

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
  reset: tests/seeds/reset.sh
  seeds: { checkout-basic: tests/seeds/checkout-basic.sql }
accounts:                     # role → env var names
  buyer:  { user_env: TEST_BUYER_USER, password_env: TEST_BUYER_PASSWORD }
  admin:  { user_env: TEST_ADMIN_USER, password_env: TEST_ADMIN_PASSWORD }
retries: 3                    # D5 flaky control
```

Rules:

- Only env var **names** in the file; the CLI refuses a value that looks like
  a secret (URL with credentials, long token) in any field.
- `version_check` may be `none`. With `none`, `kb auto` for `qa` refuses to
  start (preflight reason); a manual run asks the Tester to confirm the deploy.
- Verify step: FE URL answers, API base answers, DB connects, `reset` runs,
  each seed loads, each account logs in (through Playwright), each
  `version_check` returns a commit. Each failure is printed with its item.
- Destructive-run guard: `reset`/seeds run only through `kb test-env reset`,
  which connects only to `$<url_env>` and refuses if that URL equals a URL
  listed under `protected_urls` (optional) or if `name` is `production`/`prod`.

### D3. Lifecycle and derived status

```
ready ──Dev──► done ──Tester claim──► testing ──R<n> PASS──► closed
                                         │
                                         └─R<n> FAIL──► reopened (guilty child)
                                                          │ Dev fix
                                         testing ◄── fix-done
```

Derivation in `planstatus` (one place, used by hub UI, `kb mission next`,
pickers):

| Status | Derived when |
|---|---|
| `done` | unchanged (id in the Dev's `-svc` history) and no `-test` report yet |
| `testing` | a `qa` claim on the parent story is held (D7) |
| `closed` | latest published report of the story has verdict `PASS` |
| `reopened` | latest published report has verdict `FAIL`; applies to the children it names as guilty; the parent shows `reopened` too |
| `fix-done` | a reopened child whose Dev history records the fix of that round (below) |

- **Fix round in Dev history.** A `-svc` history row is one row per ticket
  today (no round, no time), so "newer row" cannot be told. The fix handover
  records the round it answers: `kb svc note <ticket> --fixes R<n>`, stored
  in the row's refs as `fix:R<n>`. `fix-done` = latest report `R<n>` reopened
  the child and the child's row carries `fix:R<n>`.
- **Testable story.** The Tester picker offers a parent story (or an
  unsplit story) when every child is `done` or `fix-done` and none is
  `reopened`. `fix-done` stories come before `done` ones.
- `BLOCKED-ENV` and `FLAKY`-only rounds (D5) do not change status: the story
  stays `done`/`fix-done` and is retried later.
- **Deploy check before claim → testing.** For each Dev repo of the story,
  the environment's `version_check` commit must equal or descend from the
  `source_commit` of that repo's latest publish (`publish.py` records it).
  Ancestry is checked through the GitHub compare API with the Tester's `gh`
  login (read access to the Dev repo, no clone). Not deployed yet → skip the
  story this pass.
- Bug tickets (`BUG-<n>`) follow the same flow: steps to reproduce become the
  negative test case, expected result the oracle. (Builder's call, see list.)

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

`kb testcase lint` (new, CI-gated in the `qa` repo):

- every AC of the story has ≥1 positive TC;
- every AC with a value, limit, format or state constraint has ≥1 negative or
  boundary TC;
- every `### Alternate / exception flows` entry of the ticket has ≥1 TC;
- every TC names exactly one existing script; no orphan scripts;
- `Ticket revision` matches the hub's current revision (else re-plan);
- no field left as template placeholder.

### D5. Scripts and flaky-test controls

Script rules (lint + Q1 review): Playwright Test; role/text/testid locators
(no brittle CSS/XPath); no `waitForTimeout`/fixed sleeps; web-first
assertions; every test seeds its own data and does not depend on order; API
checks through Playwright `request`; trace, screenshot and video kept on
failure. Credentials read from env only.

Run pipeline per round, in order; a story is reopened only if all five hold:

1. **Preflight**: env health (FE, API, DB) and deploy check (D3). Fails →
   round verdict `BLOCKED-ENV`, no status change.
2. **Clean retry**: a failing TC is rerun on a reset + reseeded DB up to
   `retries` (default 3). Always fails → real failure. Mixed → `FLAKY`: the
   AC is *unverified* (not pass), the script goes back to the Tester; the Dev
   is not involved.
3. **MCP confirmation**: for each stable failure the agent replays the steps
   by hand through Playwright MCP. Reproduced → bug. Not reproduced → script
   defect, back to the Tester.
4. **Script rules** (above) enforced before any run.
5. **Q2 + merge**: reopen happens only when the report PR passes Q2 and
   merges (D3 derives it from the published report).

Re-test rounds run **all** TCs of the story, not only the failed ones.

### D6. Test report — `reports/<story-id>/R<n>.md`

Based on ISO/IEC/IEEE 29119-3 test completion report + incident report fields
(aligned with `bug-template.md`).

```
# R<n> — <story-id> — <story title>
> Story: <id> · Round: <n> · Verdict: PASS | FAIL | BLOCKED-ENV
> Environment: <name> · <repo> <commit> · … · Date: YYYY-MM-DD
> Test cases: tests/<story-id>/test-cases.md @ <qa commit>

## Summary            <passed>/<total> TCs, <flaky> flaky, <n> defects
## Results by AC
| AC | TC | Result | Script | Evidence |
|---|---|---|---|---|
| AC1 | TC-01 | PASS | tests/…/tc01.spec.ts | ![](assets/tc01.png) |
## Defects            one per failure:
### D1 — <symptom>   Guilty: <child id> · Severity · Priority
  Steps to reproduce · Expected · Actual · Evidence · Environment
## Flaky / unverified TC ids, reruns, next action
## Regression         TCs that passed in an earlier round, rerun now
## Environment & data seeds used, deviations
## Review record
```

- Evidence images live in `reports/<story-id>/assets/` (PNG/WebP, the hub's
  asset convention). At ingest they are hashed and rewritten to
  `assets/<sha256>.<ext>` and uploaded to the asset store, reusing
  `planingest`'s bug-attachment path (`buglint.attachment_images`,
  `rewrite_images`, symlink/outside-folder refusal).
- `kb report lint`: template headings present, verdict consistent with the
  result table (any FAIL → FAIL; none → PASS), every FAIL has a defect with a
  guilty child that belongs to the story, every image exists, no env var
  value or credential-looking string in the text.

### D7. Claims for the Tester

Reuse `ticketclaim` (`claims.db`, keyed `repo + ticket`). Tester claims the
**parent story id** with `repo = <qa repo id>`. New phases for that kind:
`claimed`, `cases`, `scripts`, `run`, `report`, `review`, `publishing`. A held
`qa` claim is what D3 reads as `testing`. Exit code 3 on taken/lost, as today.

### D8. Reviews Q1 and Q2 (senior tester agent)

| | Where | Looks at |
|---|---|---|
| Q1 | after cases + scripts, before the run | each AC covered; TC matches AC intent; techniques fit; negative/boundary/alternate flows; script rules; data isolation |
| Q2 | after the run, before the PR | verdict follows evidence; every defect reproduced (MCP) and assigned to the right child; flaky handled per D5; no secret leaked |

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
BA plan. Scripts are not published (they stay in the `qa` repo); the report
cites their paths and the `qa` commit.

### D10. Hub UI

- **Test Report** menu (`/ui/tests`), list like `questions.html`: story,
  round, verdict, status, date, filters `all · testing · reopened · closed`.
- Report page renders `R<n>.md` with asset images; links to the ticket page
  and to the test case spec.
- Ticket page (`plan_ticket.html`) shows the derived status and links to every
  report round; mission/plan pages show the new statuses.
- `kb mission next --from-hub` shows the new statuses.

### D11. Dev side

- Dev picker (`autorun/picker.py`): `reopened` children before `ready`.
- `/dev-implement-ticket` on a reopened child: fetches the latest report
  (`kb report fetch <story>`, writes `docs/impl/<id>/report-R<n>.md`,
  git-ignored like `ticket.md`) and starts from its defects (bug-fix path,
  `dev-fix-bug` style), not from a fresh design.
- `/dev-handover` writes `kb svc note <ticket> --fixes R<n>` → `fix-done`.

### D12. `kb auto` for `qa`

- `autorun` accepts kind `qa` (`runner.py` checks `ba`/`dev` today).
- Preflight adds: `test-env.yaml` present and verified, every
  `version_check` not `none`, Playwright + browser available, merge policy.
- Loop: pick testable story → deploy check → claim → cases (new story) or
  reuse (retest) → Q1 → run (D5) → report → Q2 → PR → merge → publish →
  release claim. New `AUTO-RESULT` kinds: `blocked-env`, `flaky`,
  `failed test-review`.

## Phases

1. `qa` kind, scaffold, `/qa-env-setup` + `kb test-env`, test case template +
   `kb testcase lint`, report template + `kb report lint`, `kb report-ingest`,
   publish, derived statuses, Test Report menu, Q1/Q2 skills — run by hand.
2. Dev side: reopened picking, `kb report fetch`, `--fixes R<n>`, `fix-done`.
3. `kb auto` for `qa` (preflight, loop, results), guides EN + VI, PDFs.

## Left to the builder

- Exact CLI names (`kb test-env`, `kb testcase lint`, `kb report lint|fetch`,
  `kb report-ingest`) and module split.
- Playwright MCP server package and pin in the scaffold `.mcp.json`.
- How the GitHub compare call is made (reuse `ghrest`).
- Hub template layout of the Test Report pages (follow `questions.html`).
- Exact rubric wording for Q1/Q2.

## Builder's calls made in this document (owner to check)

- Kind name `qa`, hub role `qa`, menu label "Test Report".
- Bug tickets (`BUG-<n>`) go through the same test flow.
- `version_check: none` blocks auto mode; manual mode asks the Tester.
- `retries` default 3; flaky AC counts as unverified, never as pass.
- Scripts stay in the `qa` repo and are not published to the hub.
- Fix round recorded as `fix:R<n>` in the Dev history row refs.
