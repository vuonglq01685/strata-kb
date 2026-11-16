# 1. Who this guide is for

You test. A story reaches you once its Dev tickets are done and its code runs on a shared
test environment. You write test cases from the acceptance criteria, script them in
Playwright, run them, and publish a report that says `PASS` or `FAIL`.

Strata gives you the tickets and the knowledge base the BA grounded them on, a place to
declare the test environment, a lock so two rounds never share it, and a hub page that
shows every round. A `FAIL` reopens the story for the Dev. A regression becomes a bug
candidate for the BA. You never touch product code or tickets.

| A tester repo does | A tester repo does not |
|---|---|
| Read tickets and the published knowledge base | Change tickets, plans or product code |
| Write test cases, Playwright scripts and reports | Ingest documents from outside the repo |
| Publish one document, `<repo_id>-test` (shown as Test Report on the hub) | Publish anything else |
| Open the report PR; merge it by hand (or let auto mode merge it, section 4) | Run `kb publish` itself |

There is **one tester repo per BA repo**. The hub kind and the account role are both
`tester`.

Shared concepts, such as the L0 to L3 layers and `kb-context` citations, are in the
[architecture document](architecture.en.md). The BA's side is in the [BA
guide](guide-ba.en.md), the Dev's in the [Developer guide](guide-dev.en.md).

**Slash commands.** A tester repo has three: `/tester-env-setup`, `/tester-strategy`
and `/tester-test-story`. Each exists for Claude Code, GitHub Copilot and Cursor. A tester
repo has no `/kb-ingest`, `/kb-init` or `/kb-auto`.

---

# 2. First-time setup

## 2.1 Install and scaffold

```bash
pip install strata-kb
kb init --kind tester
```

`kb init --kind tester` writes the config, the MCP wiring (including the `playwright` MCP
server), the three slash commands, `playwright.config.ts`, a login fixture and its smoke spec
under `tests/fixtures/`, the templates (`docs/templates/test-cases.md`,
`test-report.md`, `test-strategy.md`), the review rubric
(`docs/test-review-rubric.md`, with a `.local.md` override), `.kb/test-env.example.yaml`,
`.github/CODEOWNERS` and the workflows (`kb-test-lint.yml`, `kb-test-stale.yml`,
`kb-publish.yml`, `kb-publish-request.yml`). Re-running it is safe: it refreshes the
scaffold and merges `.claude/settings.json`; `*.local.md` files are never touched.

## 2.2 Point at the hub and register the repo

In `.kb/config.yaml` fill:

```yaml
kind: tester
hub: https://github.com/your-org/kb-hub.git   # or a local kb-hub path
repo_id: shop-test                            # must equal this repo's id in the registry
intake: https://kb.internal:8321              # the hub's publish intake
```

**Never put a token in `hub:` or `intake:`.** The file is committed. A URL that needs a
token goes in the `STRATA_KB_HUB` environment variable.

Ask the hub operator to add this repo to `federation/registry.yaml` with `kind: tester`. For
automation (section 4) the entry must also have `auto_merge: true`.

## 2.3 Connect your assistant

`kb mcp-setup` writes `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN` into `.env`
(git-ignored). Load it, then restart your assistant. The tester repo uses the token for
the hub's HTTP API: claims, the environment lock, the known failures.

## 2.4 Describe the test environment: `/tester-env-setup`

Run `/tester-env-setup`. It walks you through the environment and writes
`.kb/test-env.yaml`. `.kb/test-env.example.yaml` shows the shape:

```yaml
name: staging
apps:
  - repo: shop-fe
    url: https://staging.example.test
    version_check: { url: https://staging.example.test/version, field: commit }
db:
  url_env: TEST_DB_URL
  check: tests/seeds/check.sh
  reset: tests/seeds/reset.sh
  seeds: { checkout-basic: tests/seeds/checkout-basic.sh }
accounts:
  buyer: { user_env: TEST_BUYER_USER, password_env: TEST_BUYER_PASSWORD }
retries: 3
```

Rules: the file holds **names of environment variables only**. Values live in `.env`
(git-ignored) or CI secrets. Scripts must sit inside the repo, and `reset` refuses
production and protected URLs. The skill then runs `kb test-env check` (names only, no
secret-looking value) and `kb test-env verify` (one `ok` or `FAIL` line per app URL, DB
`check`, `reset`, seed, version endpoint), fills the login fixture by exploring the login
page with Playwright MCP (it never types a credential through MCP), and logs in once per
account with the smoke spec.

Each app carries a `version_check`: an endpoint and the field that holds the deployed
commit. `kb test-env deployed <story>` compares it with the commit the story's Dev PRs
published. Without a `version_check` the Tester has to confirm a deploy by hand, and auto
mode refuses to start.

## 2.5 Turn on the PR gate

The `lint` job of `kb-test-lint.yml` lints test cases, reports and the strategy on every PR.
Make it a required check on the default branch, and replace `@OWNER` in
`.github/CODEOWNERS`. Section 4.1 explains why, and gives a ruleset sample. Do it even
if you never run auto mode.

---

# 3. Daily work

## 3.1 The test strategy: `/tester-strategy`

Run `/tester-strategy` before the first story. It writes `docs/test-strategy.md`: what to
test first, how, and why, in a **Priority order** table (one row per mission, story or KB
area, with a rank, a risk and a reason that cites evidence). It grounds the rows in
the KB and the hub plan, writes a `## KB context` block, lints
(`kb strategy lint docs/test-strategy.md --hub`), has a fresh-context reviewer read it, and
opens a PR. You review and merge it; the merge publishes it as section `strategy`.

It works from documents alone, before any code or environment exists. With no
`.kb/test-env.yaml` it writes the planned environments, marks them "not set up yet" and
reminds you to run `/tester-env-setup`. The strategy **never blocks testing**: a story is
tested whether or not it has a row.

When the hub moves under the strategy (a re-pinned ticket, a renamed target, an uncovered
story), `kb test stale` reports it, and `kb-test-stale.yml` keeps one issue labelled
`kb-test-stale` up to date. Run `/tester-strategy --amend` to fix the findings: one change
per finding, each approved by you, written as a row in the strategy's `## Change log`.
`tc-revision` findings (a test case behind its ticket's revision) are not strategy
changes; `/tester-test-story` updates the cases.

## 3.2 Pick the story: `kb test next`

`kb test next` lists the testable stories in strategy order (plan order when there is no
strategy), with tier, rank and how to test; `--json` and `--all` are available. A story is
testable when every one of its tickets is `done` and none is `reopened` or `testing`, and
the story itself is not `closed`. Exit `0` found, `3` nothing testable, `1` error.
`/tester-test-story` with no argument runs it, proposes the first story and asks you to
confirm or name another.

## 3.3 Test a story: `/tester-test-story`

`/tester-test-story <story>` runs one round. In order:

1. Fetch the ticket and check the story is testable (nothing is held yet).
2. Check the deploy (`kb test-env deployed`). Exit `4` means the environment does not run
   the published commits yet: stop, nothing held.
3. Lock the environment (`kb test-env lock`), take the claim on a branch
   `test/<story>-R<n>` (`kb claim take`).
4. Explore the acceptance criteria in the app with Playwright MCP, write
   `tests/<story>/test-cases.md` (one TC per block, at least one positive TC per
   criterion, a negative or boundary TC when it states a value, and every alternate or
   exception flow) and lint it with `kb testcase lint`.
5. Write one Playwright script per TC (role and text locators, no fixed sleeps, each test
   seeds its own data).
6. **Q1 review**: a fresh `test-case-reviewer` reads the cases and scripts before any run.
7. Run the pipeline: preflight, story run, clean retry on a reset DB (`retries` times),
   MCP confirmation of every stable failure, a **regression run** of the closed stories,
   and a post-check of the deployed commits.
8. Write `reports/<story>/R<n>.md` (`kb report lint` until it exits 0), then the **Q2
   review** by a fresh `test-report-reviewer`.
9. Publish: `kb report-ingest`, commit `tests/<story>/` and `reports/<story>/`, push, and
   open the PR with `kb pr open`. By hand you then merge it. The merge publishes the report
   through the `kb-publish-request` workflow. The skill never runs `kb publish`.

The claim and the lock are released on any stop. Credentials come from environment
variables only, through the login fixture; none ever lands in a case, script, report, log
or PR.

**Round outcomes.**

| Outcome | When | Result |
|---|---|---|
| `PASS` | every story TC passed, preflight and post-check clean | report committed |
| `FAIL` | at least one confirmed defect (a story TC, or a story regression) | report committed; the story is reopened for the Dev |
| `INCOMPLETE` | no defect, but a flaky or script-defect TC | run log only (`.kb/runlog/`); retried later |
| `BLOCKED-ENV` | preflight or post-check failed (environment changed or unhealthy) | run log only; retried later |

A flaky TC (it passes on retry) leaves its criterion *unverified*, never `PASS`. A script
is never edited during a round: the fix goes into the next round and back through Q1.

## 3.4 Report rounds

A story is tested in rounds, `R1`, `R2`, and so on. A `FAIL` report names each defect
(`D<k>`) with the guilty child ticket, steps, expected, actual and evidence. The hub marks
that child `reopened`. The Dev reads the report with `kb report fetch`, fixes it, and hands
over; the child becomes `fix-done` and the story is testable again. Each new round reruns
**all** TCs of the story, not only the failed ones. A `PASS` report closes the story, and
a closed story is final: it is never tested again, only run as regression.

## 3.5 Regression and bug candidates

When every story TC passes, the round runs the scripts of the **closed** stories. A
failure there is checked with the hub's known failures first (a key such as
`ST-0/TC-3` already open is listed as known, not logged again).

- A **story regression** is a defect of this story: the TC passed at the last baseline
  (the last `PASS` round on this environment) **and** the failing page, route or service
  maps to a file the story's Dev PRs changed (`kb test-env changed`). It is marked
  `Regression: yes` and reopens the guilty child.
- Anything else is an **outside regression**, written `RD<k>`. It does not stop the story
  closing. It becomes a **bug candidate** on the hub. The BA drafts a bug ticket from it,
  which the Dev then fixes.

A doubt always means outside regression, never a reopen on a guess.

## 3.6 The Test Report menu

The hub's **Test Report** page lists every story with its rounds, verdicts and derived
status (`testing`, `reopened`, `fix-done`, `closed`). Filters: `all`, `testing`, `reopened`,
`closed`, `regression`, and open bug candidates. A reopened ticket with a regression defect
carries a `regression` badge. The **Strategy** panel on the same page shows the revision,
the top ranks and a `needs re-grounding` badge when the strategy has drifted.

## 3.7 Keep the strategy and the cases current

Run `kb test stale` whenever you want to know (it exits `0` none, `2` warnings only, `1`
any error, and never blocks testing). Re-grounding a test case after a ticket revision is
part of the next `/tester-test-story` round.

---

# 4. Automation modes

**Full-auto mode (optional).** A switch on a `tester` repo that lets it test on its own,
on the Tester's machine: pick a story, test it, merge the report, pick the next one, until
nothing is left to test. No step waits for a person: the agent runs its own reviews,
fixes red checks and merges. Nothing changes while the switch is off.

Tester auto mode runs on the Tester's machine, with Chromium. It does **not** run on Claude
Code cloud.

## 4.1 Security: read this first

Read this section before you turn the switch on. An unattended run **merges its own report
and strategy pull requests** once the `lint` check is green, under merge policy C: the
`lint` check is required, a code-owner review is required, and CODEOWNERS covers the
sensitive paths. Nobody reads a report before it merges. A defect the agent misjudged goes
straight to the hub, reopens a ticket for a Dev, or closes a story.

- **`Bash(kb pr merge*)` is no longer denied in tester settings.** Auto mode needs it, so a
  **manual** session could also run `kb pr merge`. Only the skill text ("never merge it; a
  human does") stops it there. GitHub is the real gate: set up branch protection **even if
  you never run auto mode**. The `--admin` forms of `kb pr merge` and `gh pr merge` stay
  denied, and `gh pr merge*` stays denied.
- **`kb publish` stays denied.** The merge publishes: the `kb-publish-request` workflow
  tags the merged commit and publishes it through the hub's intake.
- The deny list is defence in depth, not a boundary. The runner never uses
  `--dangerously-skip-permissions` or `bypassPermissions`.
- The working tree must never sit on the default branch with commits on it. The skills
  branch first; the runner does not guard it.

### Merge policy

`kb auto run` starts only when GitHub would not let the agent merge without the required
check and a code-owner review, and would not let it bypass that protection. It reads the
settings through the GitHub REST API with the agent's own login. Each refusal ends with
`see "Merge policy" in the Tester guide`, which points here.

**What must hold on the default branch.**

- The check `lint` (the job of `kb-test-lint.yml`) is a required status check.
- Code-owner review is required. Approving reviews are not: `required_approving_review_count`
  is `0`, so a PR that touches no code-owned path merges when `lint` is green. A test
  report PR touches `tests/` and `reports/`, and a strategy PR touches
  `docs/test-strategy.md`: neither is code-owned.
- Stale approvals are dismissed when new commits are pushed (ruleset
  `dismiss_stale_reviews_on_push`; classic `dismiss_stale_reviews`).
- `.github/CODEOWNERS` exists and no `@OWNER` placeholder is left.
- Force pushes and deletions are blocked (recommended; `kb` does not check it).

**Identity rule.** Only protection the login cannot bypass counts. A **ruleset** counts only
if `current_user_can_bypass` is `never` (when GitHub omits the field: `bypass_actors`
present and empty). **Classic** branch protection counts only for an admin login, with
`enforce_admins` on and no pull-request-review bypass allowance. A non-admin login on
classic-only protection is refused, so a non-admin bot needs a **ruleset**. Any GitHub read
error refuses too (fail closed).

**Ruleset sample.** Settings, Rules, Rulesets, New branch ruleset (or
`POST /repos/<owner>/<repo>/rulesets` as the owner):

```json
{
  "name": "main: merge policy",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "bypass_actors": [],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "require_code_owner_review": true,
        "dismiss_stale_reviews_on_push": true,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [ { "context": "lint" } ]
      }
    }
  ]
}
```

**Owner step: CODEOWNERS.** `kb init` writes `.github/CODEOWNERS` once and never rewrites
it. Replace every `@OWNER` with a real GitHub user or team, commit it to the default
branch, and let that person or team review. GitHub ignores a rule whose owner does not
exist, so an unreplaced placeholder protects nothing and the run refuses. **The owner must
not be the agent's login**: GitHub never lets the author of a PR approve it.

**PRs that wait for a human.** CODEOWNERS covers `.github/CODEOWNERS`, `.github/workflows/`,
`.claude/settings.json`, `.claude/agents/`, `.claude/skills/`, `.claude/commands/`,
`docs/test-review-rubric.md` and `docs/test-review-rubric.local.md`. A PR that touches one
of them cannot merge without the owner's review, so the task ends
`AUTO-RESULT: blocked-review <pr-url>`. For a report, the claim stays held in phase
`review` with the PR, so no other Tester takes the story; the runner frees it once a human
merges or closes the PR.

**Residual risk.** An admin token can still edit the ruleset. Only the permission
allowlist (it does not allow `gh api`) stops the agent from doing so. The hardening is a
**non-admin bot identity** with a ruleset it cannot bypass.

## 4.2 Set up once

1. The BA's plan and the Dev tickets are on the hub, and `docs/test-strategy.md` exists if
   you want a strategy order. With no strategy, auto tests in plan order. Auto **never
   writes a new strategy**, it only amends an existing one.
2. `intake:` is set in `.kb/config.yaml`, and the hub's Registry page has **auto-merge on**
   for this repo, so the merged report publishes.
3. **Chromium.** Playwright and Chromium must be usable from the repo: `npx playwright
   install chromium`. The runner launches headless Chromium once as a probe.
4. **`version_check`** on every app in `.kb/test-env.yaml`, and `/tester-env-setup` green
   (`kb test-env verify` exits `0`). Auto cannot confirm a deploy without it.
5. **Refresh the settings** (see below).
6. Export `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN`, and have the `claude` CLI on the
   `PATH`, **logged in with a Claude subscription**. The runner never uses an API key. The
   runner reads other Testers' claims through the hub API, so it must be reachable.
7. Keep `main` as the default branch; the skills run `git fetch origin`.
8. Set up the merge policy in 4.1.

**Settings refresh.** A tester repo scaffolded earlier still denies `Bash(kb pr merge*)`.
`kb auto run` refuses while that entry is there (`run kb init --kind tester to refresh the
auto-mode settings`). Run `kb upgrade` in the repo: it re-runs the scaffold, drops that
retired deny, adds the new allows (`git switch --detach origin/*`, `git ls-remote --heads
origin *`), and opens a PR on a new branch; it never merges, and a human runs it (an auto
task may not). `.claude/settings.json` is code-owned, so that PR needs the owner's review.
`kb init --kind tester` does the same refresh in place; commit the result to the default
branch. Either way the retired entry is the only one a refresh removes.

## 4.3 Run and stop

| Task | Command | Result |
|---|---|---|
| Turn the switch on | add `auto:` with `enabled: true` to `.kb/config.yaml` | `kb auto on` refuses a tester repo, so the switch is flipped by hand |
| Commit it | commit and push `.kb/config.yaml` and `.claude/settings.json` to the default branch | `kb auto run` refuses until you do |
| Start the loop | `kb auto run` (`--once`, `--model`, `--effort`) | logs to the terminal; run it in a session that stays open |
| See where it is | `kb auto status [--json]` | switch, task, attempts, stop reason |
| Stop it | `kb auto off` | stops after the current task |

```yaml
auto:
  enabled: true
  idle_interval: 600   # seconds to wait when nothing can start now
```

`kb auto run` refuses, and prints every reason, when:

- the switch is off, `.kb/config.yaml` or `.claude/settings.json` is untracked or dirty,
  or `auto.enabled: true` is missing from the default branch's copy;
- `intake:` is empty, the hub registry cannot be read, does not list this repo, or lacks
  `auto_merge: true` for it;
- the merge policy is not enforced on GitHub (4.1);
- it is on cloud;
- the test environment is not verified (`run /tester-env-setup`), an app has no
  `version_check`, or Playwright with Chromium is not usable;
- the settings still deny `Bash(kb pr merge*)`;
- the hub claim API is not set.

Exit codes: `0` done, `2` stopped, `1` refused or error, `130` interrupted.

## 4.4 What it does and when it stops

One fresh `claude -p` process per task. The runner picks, in order:

1. **A claim this machine already holds** that is still working (a crash left a story
   mid-round): the same story again. The skill's crash check picks up from there.
2. **A strategy amend** (`/tester-strategy --amend`), when `docs/test-strategy.md` exists on
   the default branch and `kb test stale` reports a `broken-target`, `pin-moved`,
   `kb-context` or `coverage` finding. `tc-revision` is not a strategy task.
3. **The first story of `kb test next`** that no other Tester holds (read through the hub
   claim API), that is not cooling, and whose deploy check passes (`/tester-test-story
   <story>`). A story whose deploy check exits `4` is set aside for one idle interval with
   no LLM run.

**`/tester-test-story` in auto mode.** The same steps as 3.3, with the human gates
replaced:

- **Crash check first.** Already `closed`, or `reopened` with the latest round published:
  `done`. A merged report PR: release the claim and `done`. An open PR from a crashed run:
  continue at the checks. A pushed branch with no PR: continue at the PR. A PR a human
  closed unmerged is final (`failed report-pr-closed`).
- Both reviews run as subagents. When none can be dispatched, the task ends
  `failed test-review no-subagents`.
- **Merge rule.** Open the PR, watch `kb pr checks --watch`; on red, read the failure, fix
  it and push, up to 2 rounds (still red: `failed ci-red`). On green,
  `kb pr merge --squash --delete-branch`. When the merge is refused for want of a review,
  the claim stays in `review` with `--pr` and the task ends `blocked-review`. After a
  merge, the `kb-publish-request` workflow publishes the report and the claim is released.

**`/tester-strategy --amend` in auto mode.** Re-pin a row, re-point a renamed or split
target, add a row (or a `last` row) for an uncovered story, refresh `## KB context`, align
`.kb/test-env.yaml`, or change a rank, only with cited evidence and an agreeing reviewer.
Auto never drops a row: for a broken target it cannot re-point, it ends `failed
broken-target <target>` and the Tester decides. Each change is one `**Auto decision:**`
line under `## Change log`, checked by a fresh-context reviewer; a rank change objected to
twice is dropped and only recorded. The change-log row's Review cell starts with `auto`.
The branch is `auto/strategy` (`auto/strategy-r2`, ... once spent). After an auto rank
change the hub shows the badge `auto-reordered (rev N)` on the Strategy panel and page
until a person's revision clears it.

**The result line.** Each task ends its reply with one line, and nothing after it:

| Line | Meaning |
|---|---|
| `AUTO-RESULT: done` | the report PR merged, or the work was already finished |
| `AUTO-RESULT: blocked-review <pr-url>` | the merge needs a human review; the loop parks it and goes on |
| `AUTO-RESULT: blocked-env <story> <reason>` | `env-locked`, `not-deployed`, `env-unhealthy` or `claim-taken`; not a failure |
| `AUTO-RESULT: incomplete <story>` | the round ended `INCOMPLETE`; not a failure |
| `AUTO-RESULT: failed <reason>` | anything else; always with a reason |

A missing or malformed line counts as a failed attempt.

**When it waits, and when it stops.**

| Situation | Outcome |
|---|---|
| no strategy amend due and nothing testable | done, exit `0`, "nothing testable". It does not wait for Dev fixes: run `kb auto run` again later |
| candidates exist, but all are held by another Tester, cooling, or not deployed | idle: sleep `idle_interval`, then pick again |
| `blocked-env ... env-locked` (another round holds the environment) | idle for `idle_interval`, no story is tried meanwhile |
| any other `blocked-env` | that story waits one `idle_interval`; the next story is tried at once. No attempt is counted |
| `incomplete` | one attempt counts; the story waits one interval so its scripts get the next round. At `MAX_ATTEMPTS` (2) the story is set aside with a warning, and the loop goes on |
| every candidate was set aside | stop, naming them |
| `failed test-review ...` | stop at once: a BLOCKER stood after round 2 and needs a human |
| `failed ci-red ...`, or a task that fails `MAX_ATTEMPTS` times | stop |
| `blocked-review` | the story is parked while a human reviews; the loop carries on |

A flaky story never stops the loop. After a stop, fix the cause and run `kb auto run`
again: it clears the set-aside stories. A command outside the allowlist ends the task
`failed command-denied <command>`; add it to `permissions.allow` in
`.claude/settings.json` by hand. A usage-limit wait is not a failure. A task process
carries `STRATA_KB_AUTO_TASK=1`, under which `kb auto on`, `off` and `run` refuse
(`status` still works).

Every task run appends one line to `.kb/auto/runs.jsonl` (git-ignored). A Stop hook nudges
a task once when its reply does not end with a valid `AUTO-RESULT:` line.

## 4.5 Claude Code cloud

Not supported. `kb auto run` in a tester repo refuses on cloud: the Tester's machine has
the browser and the test environment.

---

# 5. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `kb test next` exits `3` | nothing is testable: a story needs every ticket `done`, none `reopened` or `testing`, and the story not `closed` |
| `kb test next` exits `1` | no hub, or the strategy's plan is not on the hub; check `hub:` and the `> Plan:` line |
| `kb test-env deployed` exits `4` | the environment does not run the published commits yet; wait for the deploy, or fix the `version_check` |
| `kb test-env lock` exits `3` | another round holds the environment; the lock has a TTL |
| `kb claim take` exits `3` | another Tester holds the story |
| `kb strategy lint` prints `pin-moved` | the ticket moved; re-pin the row (`/tester-strategy --amend`) |
| A round ends `BLOCKED-ENV` | the environment was unhealthy or a commit changed during the round; check it and run the story again |
| A round ends `INCOMPLETE` | a flaky or script-defect TC; fix the script in the next round |
| `kb auto run` refuses with `see "Merge policy" in the Tester guide` | set up branch protection (4.1) |
| `kb auto run` refuses about the auto-mode settings | run `kb upgrade` (4.2) |
| `kb auto on` says it works in ba or dev repos only | set `auto.enabled: true` in `.kb/config.yaml` by hand (4.3) |

---

# 6. Appendix

## 6.1 Config keys and environment variables

| Key or variable | Meaning |
|---|---|
| `kind`, `hub`, `repo_id`, `intake` | see 2.2. Never put a token in `hub:` or `intake:` |
| `auto.enabled`, `auto.idle_interval`, `auto.claim_heartbeat` | auto mode; `idle_interval` is the seconds to wait when nothing can start now (default `600`); `claim_heartbeat` is seconds between claim refreshes (default `900`) |
| `.kb/test-env.yaml` | `name`, `apps` (`repo`, `url`, `api_base`, `version_check`), `db` (`url_env`, `check`, `reset`, `seeds`), `accounts`, `api_auth`, `retries`; names of env vars only |
| `kb init` re-run | creates missing files and refreshes scaffold files; `.kb/config.yaml` and `.claude/settings.json` are protected (`--force` replaces them; `.claude/settings.json` is merged otherwise); `*.local.md` files are never touched |
| `STRATA_KB_HUB` | overrides `hub:`; carries a credentialed URL in CI |
| `STRATA_KB_HUB_URL`, `STRATA_KB_HTTP_TOKEN` | the hub's HTTP base URL and bearer token: MCP, claims, the environment lock, known failures |
| `STRATA_KB_CLAIM_AS` | claim holder name |
| `STRATA_KB_AUTO_TASK` | set by the runner on task processes; `kb auto on`, `off` and `run` refuse under it |
| Test-account variables | the names in `accounts:` and `db.url_env`; values only in `.env` or CI secrets |

Exit codes: `0` ok, `1` error, `2` stale citation (or a usage error), `3` claim taken or
lost (or the environment locked, or nothing testable for `kb test next`), `4` not deployed
yet (`kb test-env deployed`), `8` `kb pr checks` still pending.

## 6.2 Work folders and what is git-ignored

| Path | Holds | Committed |
|---|---|---|
| `tests/<story>/test-cases.md`, `tc<NN>.spec.ts` | the cases and one script per case | yes |
| `tests/fixtures/` | the login fixture and its smoke spec | yes |
| `reports/<story>/R<n>.md`, `assets/` | the report of round n and its evidence (PNG or WebP) | yes |
| `docs/test-strategy.md` | priority order, from `/tester-strategy` | yes |
| `tests/<story>/ticket.md` | the ticket fetched from the hub | no, never edit |
| `.kb/runlog/` | the run log of each round, including `INCOMPLETE` and `BLOCKED-ENV` | no |
| `.kb/auto/`, `.kb/*-test/`, `.env` | the auto runner's state, the generated `-test` index, the credentials | no |
| `test-results/`, `playwright-report/` | Playwright output | no |

## 6.3 What is enforced, and what is only asked

| Rule | Enforced by |
|---|---|
| A report has a verdict `PASS` or `FAIL`, defects with evidence, no secrets | `kb report lint` (CI `lint` job) |
| Cases cover every criterion and alternate flow | `kb testcase lint` (CI `lint` job) |
| The strategy has an order, a KB context and a passing review | `kb strategy lint` (CI `lint` job) |
| One Tester per story; one round per environment | the claim and the environment lock on the hub (exit `3`) |
| A closed story is never tested again | `/tester-test-story` step 1 and the hub status |
| A reviewer is a fresh subagent, never the author | the skill text only |
| A manual session does not merge | the skill text only; GitHub's merge policy is the real gate |
| An auto merge needs green `lint` and a code-owner review on sensitive paths | GitHub branch protection, checked by `kb auto run` |
| No credential in a case, script, report, log or PR | the login fixture, `kb report lint` and the reviewers |

## 6.4 Auto-mode permissions

`kb init --kind tester` merges its permissions into your `.claude/settings.json`.
**Allowed:** everyday `git` (add, commit, status, diff, log, fetch, pull, `switch -c`,
`switch test/*`, `checkout -b`, branch, worktree, merge, `push -u origin HEAD`), the
read-only `git switch --detach origin/*`, `git ls-tree *origin/*`, `git show origin/*`,
`git ls-remote --heads origin *` and `git remote show origin`, `gh pr` and `gh run`,
`Read`/`Edit`/`Write`, the `strata-kb` and `playwright` MCP tools, `npx playwright test*`,
and the `kb` subcommands the skills use: `kb test-env`, `kb testcase`, `kb strategy lint`,
`kb test stale`, `kb test next`, `kb report`, `kb report-ingest`, `kb pr`, `kb claim`,
`kb ticket`, `kb mission`, `kb context`, `kb auto`. One `curl` is allowed in exactly this
form: the hub's `/api/tests/known-failures` read with the bearer token.

**Denied:** `kb publish`; `gh pr merge*`; the `--admin` forms of `kb pr merge` and
`gh pr merge`; `kb init` and `kb upgrade` (a human runs them); any `git push` that names
`main` or `master`, force-push, `+` and `:` refspecs and `--delete`; `git switch`,
`checkout` and `branch` forms that move onto, create, rename or delete `main` or `master`;
`git switch` with `--discard-changes`, `--force` or `-f`; `git reset --hard`;
`gh repo delete`, `gh run delete`; `rm -rf /*`; editing `.claude/settings.json`,
`.claude/settings.local.json` and `.git/**`. `Bash(kb pr merge*)` is **not** denied (auto
mode merges with it); a refresh of an older tester's settings removes it from the deny list.

## 6.5 Hub rules that touch you

Statuses are derived by the hub from published reports and claims, never typed: `testing`
while a Tester holds the story, `reopened` after a `FAIL`, `fix-done` once the Dev hands
over, `closed` after a `PASS`. Claims have a heartbeat (`claim_heartbeat`); a claim parked
in `review` or `publishing` is held without a TTL. The environment lock has a TTL, and
`kb test-env lock` re-run refreshes it. The tools your skills call: `kb_search`,
`kb_get_section`, `kb_context_new`, `kb_resolve`, `kb_ticket_fetch`, `kb_report_fetch`.
