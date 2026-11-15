# Tester loop, block 3 — `kb auto` for the Tester (design)

Date: 2026-11-15 · Size: project (block 3 of 3, release 1.37.3) ·
Version: stays 1.37.3; tag `v1.37.3` after this block merges.

Builds on `2026-11-14-tester-role-design.md` (D12 `kb auto` for `tester`,
phase 3) and `2026-11-15-test-strategy-design.md` (D8 phase 3 auto). Blocks 1
(Dev/BA side, #155) and 2 (`kb test next`, #156) are merged first. Terms are
reused: testable, `testing`, `reopened`, `fix-done`, `closed`, `R<n>`, `RD<k>`,
env lock, Q1/Q2.

## Intent

Today the Tester can run `/tester-test-story` only by hand, and `kb auto run`
refuses a `tester` repo. With blocks 1 and 2 in place, the rest of the loop
already runs unattended. A Dev fixes a reopened ticket, the BA logs a bug from a
regression candidate, and `kb test next` names the next story to test. Block 3
lets the Tester's VM run the same loop with nobody at the keyboard:
pick a story, test it, publish the report (merge), and pick the next one. It
also keeps the test strategy grounded while doing so.

## Goals

1. `kb auto run` accepts a `tester` repo, with a tester preflight (E1).
2. `pick_tester`: a strategy amend when `kb test stale` has strategy
   findings, else the first story of `kb test next` that no other Tester
   holds and whose deploy check passes (E2).
3. The runner handles the new results `blocked-env`, `incomplete` and
   `failed test-review` (E3).
4. `/tester-test-story` gets an Auto mode section. It covers merge after green
   CI, the crash check and no human gates (E4).
5. `/tester-strategy --amend` gets an Auto mode section (strategy D8 phase 3).
   The hub shows the badge `auto-reordered (rev N)` (E5).
6. The runner stops only when nothing is left to test. A story that cannot
   start now (another Tester holds it, not deployed, environment locked) is
   waited on, never counted as a failure (E6).
7. A Tester guide, EN and VI, with PDFs (E7).

## Non-goals

- Tester auto on Claude Code cloud. It runs on the Tester's VM, which has
  Chromium (owner answer).
- Writing a new strategy in auto. Auto only amends an existing
  `docs/test-strategy.md`. With no file, it tests in plan order.
- Parallel stories on one VM. One task at a time, as for BA and Dev.
- Changing how the hub derives test statuses.

## Anti-goals

- A flaky story that stops the whole loop: it is set aside, and the other
  stories go on.
- Burning an LLM run on a story the runner could have known it cannot start:
  not deployed, or held by another Tester.
- A report merged without its required `lint` check, or a sensitive path
  merged without a code-owner review.
- Manual mode quietly merging: outside auto, the Tester still merges by hand.

## Owner answers (carried)

| # | Answer |
|---|---|
| A1 | Tester auto runs on the Tester's VM with Chromium, not on cloud. |
| B1 | `kb auto` exits when there is nothing to do; a later run picks up new work. |
| B3 | A story defect reopens the child for the Dev; a regression defect goes through the BA. Unchanged here. |

## Design

### E1. Preflight for `tester`

`autorun/runner.preflight` accepts kind `tester` (message: "auto mode needs
'ba', 'dev' or 'tester'"). For a tester repo, it adds these refusals:

- On cloud (`cloud.is_cloud()`): "tester auto runs on the Tester's machine,
  not on cloud".
- `.kb/test-env.yaml` is missing or does not load. `kb test-env verify` (the
  `testenv.verify` function) exits non-zero: "test environment not verified —
  run `/tester-env-setup`".
- An app in `test-env.yaml` has no `version_check`: "app `<repo>` has no
  version_check: auto cannot confirm a deploy".
- Playwright or Chromium is not usable from the repo. Run
  `npx --no-install playwright --version`, then launch headless Chromium
  through the repo's Playwright and close it. *(Builder: one small node
  snippet through `subprocess`, with a timeout.)*
- `.claude/settings.json` still denies `Bash(kb pr merge*)` (see E4):
  "run `kb init --kind tester` to refresh the auto-mode settings".
- The hub claim API is not reachable (`claimclient.from_env()` raises): the
  runner needs it to see other Testers' claims (E2).
- Merge policy C: `ghpolicy.REQUIRED_JOBS["tester"] = ("lint",)` (the
  `kb-test-lint` job), plus code-owner review and CODEOWNERS, as for BA. The
  refusal text points to the Tester guide's "Merge policy" section.
- The existing checks also apply to tester repos: `intake:`, the registry
  entry and `auto_merge`.

### E2. `pick_tester`

`autorun/picker.pick_tester(root, kb_dir, hub, *, skip, held, waiting)`
returns a `Task` or a reason why none is picked:

1. **Strategy amend.** Read `docs/test-strategy.md` from `origin/<default>`
   after a fetch, as `pick_ba` reads the plan, because the working tree may
   be stale. When the file exists and `kb test stale` would report a finding
   with code `broken-target`, `pin-moved`, `kb-context` or `coverage`
   (in-process `strategyhub` drift, the function behind `kb test stale`),
   yield `Task("tester-strategy", "--amend")`. A `tc-revision` finding is not
   a strategy task (`/tester-test-story` updates the cases). No file: skip
   this step.
2. **Next story.** `strategyhub.next_stories(hub, strategy)` (block 2), in
   order. Pass over a story that:
   - has a task key in `skip`;
   - is in `held`: another Tester's tester-role claim, read through the hub
     claim API (`ClaimClient.held(role="tester")`). The local hub clone's
     claim store is git-ignored and stays empty on the VM, so `testing` from
     the clone is not enough;
   - is in `waiting` (E3 cooldown);
   - fails `kb test-env deployed <story>`: exit 4 puts the story in
     `waiting` for one idle interval, with no LLM run; exit 1 is a hub error,
     and the pick is idle.
   The first story left → `Task("tester-test-story", <story>)`.
3. **Resume first.** Before 1 and 2, check for a Tester claim this machine
   holds (its token is in `LocalClaims`) that is still working (phase not
   `publishing` and not stopped). If one exists, that story is picked again,
   because a crash left it mid-round. The skill's crash check picks up from
   there (E4).

Result shape: the task, or `None` with a cause, one of:

- `nothing`: no amend and `next_stories` is empty. The runner ends `done`.
- `waiting`: every candidate is held, cooling or not deployed. The runner is
  idle.

*(Call: `kb test next` exit 3 maps to `nothing`; the runner exits 0 there,
following B1.)*

### E3. Results and runner state

`claude.RESULT_FORMS` gains two forms. The Stop-hook guard reuses them.

- `AUTO-RESULT: blocked-env <story> <reason>`. `<reason>` is one of:
  - `env-locked`: another round holds the environment;
  - `not-deployed`: the deploy check exit 4 at run time;
  - `env-unhealthy`: preflight, health or post-check failed, so the round
    ended `BLOCKED-ENV`;
  - `claim-taken`: `kb claim take` exit 3.
- `AUTO-RESULT: incomplete <story>`: the round ended `INCOMPLETE`, with a
  flaky or script-defect TC.

`parse_result` gains the kinds `blocked-env` (ids `(story, reason)`) and
`incomplete` (ids `(story,)`). `prompt_for` prints the tester forms only for
kind `tester`. The BA and Dev prompts are unchanged.

`_settle`, tester only:

- `blocked-env`: no attempt is counted, and the task is cleared.
  - `env-locked` puts every story on hold: `state.env_wait_until = now +
    idle_interval`, and the outcome is `idle`.
  - Any other reason puts this story in `state.waiting` (`"<story>
    <until-epoch>"`) for one idle interval, and the outcome is `ran`, so the
    next story is tried right away.
- `incomplete`: counts one attempt on the task. Below `MAX_ATTEMPTS`, the
  task is cleared and the story goes into `waiting` for one interval, so its
  scripts get the next round. At `MAX_ATTEMPTS`, the key goes into
  `state.skipped` with a warning (anti-goal: no full stop). `resume` already
  clears `skipped`.
- `failed test-review …`: stops at once, like `ci-red`. A BLOCKER that
  stands after round 2 needs a human.
- `done`, `blocked-review` and other `failed` results: as for BA.

`AutoState` gains `waiting: tuple[str, ...]` and `env_wait_until: float |
None`, both defaulting to empty. An old state file loads. Expired entries
are dropped on load.

`_check_done` is not used for a tester repo: the plan-wide `all_done` is a
BA/Dev rule. The tester's stop rule is E2's `nothing`. `run_loop` starts
no Q&A thread and no `RunnerClaims` for a tester repo. The skill takes,
updates and releases its own claim, as it does by hand.

### E4. `/tester-test-story` Auto mode

The section is written like `ba-ticket-author`'s. It opens with: "Run `kb auto
status --json`; when `enabled` is false this section does not apply". The
runner starts `/tester-test-story <story>`.

- **Already finished (crash check), first.**
  - Fetch, then read the story row (`kb mission next --from-hub --json`).
  - If its `test_status` is `closed`, or `reopened` with a report on
    `origin/<default>` whose round matches the latest published round, end
    `AUTO-RESULT: done`.
  - If an open PR exists for `test/<story>-R<n>` (`kb pr find --head …
    --state open --json`), switch to it and continue at the CI step of the
    merge rule below.
  - If a branch `test/<story>-R<n>` exists with no PR, the run crashed after
    its push: continue at Publish.
- **Step 2 deploy check**: the manual-confirm exception does not apply.
  Preflight requires every `version_check`, and any exit 4 ends
  `AUTO-RESULT: blocked-env <story> not-deployed`.
- **Step 3 lock**, exit 3 → `blocked-env <story> env-locked`.
  **Step 4 claim**, exit 3 → `blocked-env <story> claim-taken`. On every
  stop, the hold-and-release rules apply first.
- **Reviews**: subagent dispatch is required. The fallback pass with "PAUSE
  and hand to the Tester" does not apply. If dispatch is not possible, end
  `AUTO-RESULT: failed test-review no-subagents`. A BLOCKER that stands after
  round 2 ends `AUTO-RESULT: failed test-review <TC or D id>` (the text was
  reserved in phase 1).
- **Round outcome**: `INCOMPLETE` → write the run log, release, then end
  `AUTO-RESULT: incomplete <story>`. `BLOCKED-ENV` → release, then end
  `AUTO-RESULT: blocked-env <story> env-unhealthy`.
- **Step 12 Publish, the merge rule**, replaces "Never merge it":
  1. Commit and push as written.
  2. `kb pr open`, then `kb pr checks --watch`.
  3. If a check is red, read it, fix it (a lint finding in the report or
     cases), push, and watch again, for up to 2 rounds. Still red: release,
     then `failed ci-red <pr-url>`.
  4. Green: `kb pr merge --squash --delete-branch`. If the merge is refused
     for want of a review: release the lock, keep the claim in `review`, and
     end `blocked-review <pr-url>`.
  5. Merged: the `kb-publish-request` workflow publishes. Run `kb claim
     release <story>`, then end `AUTO-RESULT: done`.
  `kb publish` stays denied.
- **Branch names stay `test/<story>-R<n>`.**
- **Result line block**: the six forms, the last line, nothing after it.

Settings: remove `Bash(kb pr merge*)` from `TESTER_DENY`. Keep
`Bash(gh pr merge*)`, and keep the template's `Bash(kb pr merge*--admin*)`
deny. On refresh of a tester `.claude/settings.json`, drop the retired entry
`Bash(kb pr merge*)` from `deny`. This is the only removal `merge_settings`
does, as a named retired list for kind tester. The manual-mode text stays
"Never merge it; a human does". *(Call: the deny guarded phase 1; the merge
rule is now written per mode, and merge policy C enforces it on GitHub.)*

### E5. `/tester-strategy --amend` Auto mode and the badge

The section follows strategy design D8 phase 3. It replaces "Auto mode is
not available yet".

- Allowed changes:
  - re-pin, re-point a renamed or split target, and add a row for an
    uncovered story;
  - a `last` row for a story the agent judges not worth a rank, so the
    `coverage` finding clears;
  - a rank change, only with evidence and a reviewer who agrees.
- Each change is one `**Auto decision:**` line under `## Change log`. A
  fresh-context reviewer gets the rows, the evidence and the pick, and
  answers agree or object. On an objection, the agent decides once more:
  - a re-pin, re-point or added row then goes ahead;
  - a rank change that is objected to twice is dropped, and its Auto
    decision line records the proposal for the Tester.
- The change-log row's Review cell starts with `auto`. A rank change adds
  the trigger `priority`. A `.kb/test-env.yaml` alignment is allowed, with
  trigger `scope`.
- Then lint and Q1, on branch `auto/strategy` (`-r2`, … when spent, as in
  the BA branch rule). Merge, which publishes. The result lines are `done`,
  `blocked-review`, and `failed <reason>`, with reason `lint`, `ci-red` or
  `test-review`.

The hub badge `auto-reordered (rev N)` shows on the Strategy panel and the
strategy page while any change-log row has trigger `priority` and a Review
cell starting with `auto`, counted after the last row whose Review does not
start with `auto`. `N` is the newest such row's revision. A person's revision
clears it. Read in `teststrategy` from the parsed change log, so no new hub
store is needed.

### E6. Stopping

| Situation | Outcome |
|---|---|
| no amend, `next_stories` empty | `done`, exit 0, "nothing testable" |
| candidates exist, all held, cooling or not deployed | `idle`, sleep `idle_interval` |
| `env_wait_until` in the future | `idle` |
| every candidate skipped (`incomplete` `MAX_ATTEMPTS` times) | stop, naming them, as the existing "every task left was skipped" |
| `failed test-review`, `ci-red`, `MAX_ATTEMPTS` failures | stop, as for BA |

### E7. Tester guide

`docs/src/guide-tester.en.md` and `.vi.md` cover:

- install, `kb init --kind tester`, and hub and registry setup;
- `/tester-env-setup`, `/tester-strategy` and `/tester-test-story`;
- reports and publishing;
- the Test Report menu, and auto mode: security, merge policy, run and
  stop, what it does and when it stops;
- reference: config keys and env vars, git-ignored folders, auto-mode
  permissions.

Built to `docs/strata-guide-tester.{en,vi}.pdf` by `docs/src/build_pdf.py`,
which gains the two titles. The VI headings mirror the EN ones
(`test_vi_guides_mirror_en_headings`). The guide names only real commands
(`test_doc_lint`). README and `QUICKSTART-tester.md` link to it.

## Constraints

- No change to the BA or Dev auto behaviour, prompts or results.
- Every new CLI or state path is validated (`safe_name` story ids).
- No new MCP tool, so the tests-gate golden is untouched. If one is added
  anyway, update `tests-gate/golden/mcp_tools.json` and the e2e
  `EXPECTED_TOOLS`.
- CHANGELOG bullets go into the open `## 1.37.3` entry.

## Left to the builder

- The Chromium probe snippet.
- How `pick_tester` returns its cause (a small result type, or `None` plus a
  flag).
- The guide's exact prose. Follow the Dev guide's layout.
- Fixtures: reuse `plan_hub`, `publish_tests`, `STRATEGY_FOR_PLAN_HUB`, and
  the runner fakes in `tests/test_autorun_*`.

## Calls made in this document (owner to check)

- With nothing testable, the runner exits 0 (B1). It does not wait for
  Dev fixes.
- Auto merges its own report PR on a green `lint`, under merge policy C.
  Manual mode still never merges. `Bash(kb pr merge*)` leaves the tester
  deny list, and a refresh removes it.
- The runner checks deploys and other Testers' claims before it spends a
  run. The skill still owns its claim and lock.
- `incomplete` `MAX_ATTEMPTS` (2) times sets the story aside instead of stopping the loop.
- `claim-taken` is reported as `blocked-env`.
- Auto never writes a new strategy, only amends an existing one.
- Branch `auto/strategy` for auto amends (D8), `strategy/rev-<N>` by hand.
