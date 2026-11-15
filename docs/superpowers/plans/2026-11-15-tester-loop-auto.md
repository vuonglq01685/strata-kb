# Tester Loop Block 3 (`kb auto` for the Tester) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb auto run` drives a `tester` repo unattended on the Tester's VM. It picks a strategy amend or the next story, tests it, merges the report, and stops when nothing is testable.

**Architecture:** Reuse the BA/Dev runner (`autorun/runner.py`). The tester-only branches go in `_task_for`, `_settle` and `preflight`. The new picker `pick_tester` goes in `autorun/picker.py`, over `strategyhub` (block 2) and the hub claim API. There are two result kinds in `autorun/claude.py` and two state fields in `autorun/state.py`. Two skill bodies gain an Auto mode section. A strategy badge reads the change log. A Tester guide is added.

**Tech Stack:** Python 3.12, typer, pytest, Jinja templates, `docs/src/build_pdf.py`.

**Spec:** `docs/superpowers/specs/2026-11-15-tester-loop-auto-design.md` (E1–E7). Base: `2026-11-14-tester-role-design.md` D12, and `2026-11-15-test-strategy-design.md` D8 phase 3.

## Global Constraints

- Version stays 1.37.3. CHANGELOG bullets go into the existing `## 1.37.3` entry.
- BA and Dev behaviour, prompts (`prompt_for` for kinds `ba`/`dev`) and results stay byte-for-byte unchanged. Pin this with a test.
- New tester states load from old state files (defaults). Expired `waiting` entries are dropped on load.
- No new MCP tool. If one is added after all, update `tests-gate/golden/mcp_tools.json` (`STRATA_KB_CLOUD=0 KB_VENV=.venv UPDATE_GOLDEN=1`) and the e2e `EXPECTED_TOOLS`.
- Story ids from the hub or the state file are checked with `safe_name` before any subprocess argument or path.
- Tests run with `GIT_CONFIG_GLOBAL=<scratchpad>/test-gitconfig`. The baseline has 19 env failures (test_sectioner ×16, test_cli_errors, test_ingest_cli, test_ingest_seam).

## Review Focus

1. A tester `blocked-env`/`incomplete` result never counts as a BA/Dev failure, and never stops the loop on its own (Tasks 1, 3).
2. The pick never spends an LLM run on a story held by another Tester, or one that the deploy check reports not deployed (Task 2).
3. Exit `done` only when nothing is testable and no amend is due. All held, cooling or not deployed means `idle` (Task 3).
4. The retired deny `Bash(kb pr merge*)` is removed only for kind tester, and only that entry (Task 4).
5. In manual mode the skill bodies still say a human merges (Tasks 5, 6).

---

### Task 1: Result kinds and runner state

**Files:**
- Modify: `src/strata_kb/autorun/claude.py`, `src/strata_kb/autorun/state.py`, `src/strata_kb/autorun/guard.py` (only if it hard-codes the forms)
- Test: `tests/test_autorun_claude.py`, `tests/test_autorun_state.py`, `tests/test_autorun_guard.py`

**Interfaces:**
- Produces:
  - `Kind` gains `"blocked-env"` and `"incomplete"`.
  - `parse_result`: `AUTO-RESULT: blocked-env <story> <reason>`, where `<reason>` is one of `env-locked`, `not-deployed`, `env-unhealthy` or `claim-taken`, gives `TaskResult("blocked-env", (story, reason))`. `AUTO-RESULT: incomplete <story>` gives `TaskResult("incomplete", (story,))`. A story must match the ticket-id shape (`safe_name`). Anything else is `failed bad result line`.
  - `TESTER_RESULT_FORMS = RESULT_FORMS + ("AUTO-RESULT: blocked-env <story> <env-locked|not-deployed|env-unhealthy|claim-taken>", "AUTO-RESULT: incomplete <story>")`. `result_forms(kind) -> tuple[str, ...]` returns `TESTER_RESULT_FORMS` for `tester`, else `RESULT_FORMS`.
  - `prompt_for(skill, arg, kind)` prints `result_forms(kind)` and "in one of these N forms" with N = their count. The BA/Dev text is unchanged (pinned by test against the current string).
  - `guard` (Stop hook) accepts the tester forms in a tester repo. It reads the kind the way it reads it today, or from `load_config`.
  - `AutoState` gains `waiting: tuple[str, ...] = ()` (entries `"<story> <until-epoch-int>"`) and `env_wait_until: float | None = None`. `_parse` validates them: `waiting` is a list of strings, each `"<id> <int>"`; `env_wait_until` is a number or null. Bad shape → `ValueError`, as for the other fields. `load` drops `waiting` entries whose epoch is `<= time.time()`, and an `env_wait_until` in the past.
  - Helper `state.waiting_stories(state, now) -> frozenset[str]`.

- [ ] **Step 1: Failing tests:**
  - parse each new form, and a bad story id, a bad reason and a missing story;
  - the tester prompt lists 7 forms; the `ba`/`dev` prompt equals the old string;
  - the guard accepts `blocked-env` in a tester repo;
  - the state round-trips the new fields; an old JSON without them loads; expired entries are dropped; a bad shape is rejected.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** the three test files — PASS. **Step 5: Commit** `feat: tester auto result kinds and wait state`.

---

### Task 2: `pick_tester`

**Files:**
- Modify: `src/strata_kb/autorun/picker.py`
- Test: `tests/test_autorun_picker.py` (or a new `tests/test_autorun_picker_tester.py`)

**Interfaces:**
- Consumes: `strategyhub.next_stories`, `strategyhub.strategy_findings`, `strategyhub.plan_view`, `teststrategy.parse`, `claimclient.LocalClaims`, `ClaimClient.held(role="tester")`.
- Produces:
  - `@dataclass(frozen=True) class TesterPick: task: Task | None; cause: Literal["task", "nothing", "waiting"]; cooled: tuple[str, ...] = ()`. `cooled` lists the stories the deploy check reported not deployed in this pick, for the runner to add to `waiting`.
  - `pick_tester(root, kb_dir, hub, *, claims_client, skip=(), waiting=frozenset(), run=subprocess.run) -> TesterPick`. The order:
    1. **Resume.** A claim in `claims_client.held(role="tester")` is ours when `LocalClaims(kb_dir).get(ticket)[0] == claim["id"]`. If ours, with `state` not `stopped` and `phase` not `publishing`, the result is `Task("tester-test-story", ticket)`.
    2. **Amend.** Read `docs/test-strategy.md` from `origin/<default>` after a fetch (`gitio`, as `_plan_tree` does; `git show` text, no worktree needed). With no remote, read the working tree. If the file is missing, skip this step. Otherwise parse it. For `plan_view` by its `> Plan:` (or all plans when `Plan —`), when `strategy_findings` has a finding with code in `{"broken-target", "pin-moved", "kb-context", "coverage"}` and the key `tester-strategy:--amend` is not in `skip`, the result is `Task("tester-strategy", "--amend")`. A strategy that does not parse, or a `PlanNotOnHub`, means no amend (log a warning) and no crash.
    3. **Next story.** For each story in `next_stories(hub, strategy)`: skip it when its key is in `skip`, when it is in `waiting`, or when another Tester's claim holds it (held, and not ours). Otherwise run `kb test-env deployed <story>` (cwd `root`, capture). Exit 0 → `Task("tester-test-story", story)`. Exit 4 → add it to `cooled` and go on. Any other exit → `KbError` (the runner goes idle).
    4. Nothing yielded: `cause="nothing"` when `next_stories` was empty and no amend was due. Otherwise `cause="waiting"`.
  - The hub claim read fails (`KbError`) → raise it (the runner goes idle). It never means "no one holds anything".

- [ ] **Step 1: Failing tests** (fixtures: `plan_hub`, `_two_done` from `tests/test_test_next.py`, `STRATEGY_FOR_PLAN_HUB`, a fake claims client, a fake `run`):
  - `test_pick_tester_resumes_own_working_claim`
  - `test_pick_tester_amend_on_coverage_finding` (a strategy with no row for a testable story)
  - `test_pick_tester_no_amend_for_tc_revision_only`
  - `test_pick_tester_amend_skipped_key_falls_to_story`
  - `test_pick_tester_skips_story_held_by_other_tester`
  - `test_pick_tester_not_deployed_story_is_cooled_next_tried` (exit 4, then exit 0 → the second story, `cooled == (first,)`)
  - `test_pick_tester_nothing_testable_is_nothing`
  - `test_pick_tester_all_held_is_waiting`
  - `test_pick_tester_claim_read_error_raises`
  - `test_pick_tester_bad_strategy_no_amend`
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS. **Step 5: Commit** `feat: pick_tester`.

---

### Task 3: Runner loop for `tester`

**Files:**
- Modify: `src/strata_kb/autorun/runner.py`
- Test: `tests/test_autorun_runner.py` (or a new `tests/test_autorun_runner_tester.py`)

**Interfaces:**
- Consumes: Task 1 (kinds, state), Task 2 (`pick_tester`).
- Produces:
  - `run_once` for `cfg.kind == "tester"`:
    - skip `_check_done`, `_publish_check` and the Q&A wait;
    - if `state.env_wait_until` is in the future → `"idle"`;
    - `_task_for` → `_tester_task`: a stored task is reused. Otherwise call `pick_tester(root, kb_dir, hub, claims_client=<client>, skip=_skip(state), waiting=state.waiting_stories(state, now()))`, then merge `cooled` into `state.waiting` (until = now + `cfg.auto.idle_interval`) and save;
    - `cause == "nothing"` → log `auto mode finished: nothing testable`, return `"done"`;
    - `cause == "waiting"` → `"idle"`;
    - if `state.skipped` is non-empty and nothing is left, reuse the existing "every task left was skipped" stop.
  - `_settle` gains, used only when `cfg.kind == "tester"` (pass `kind`):
    - `blocked-env` with reason `env-locked` → `env_wait_until = now + idle_interval`, `task=None`, `attempts=0`, return `"idle"`;
    - other `blocked-env` → add `"<story> <until>"` to `waiting`, `task=None`, `attempts=0`, return `"ran"`;
    - `incomplete` → `attempts+1`. Below `MAX_ATTEMPTS`: task cleared, story into `waiting`, return `"ran"`. At `MAX_ATTEMPTS`: key into `skipped`, `task=None`, `attempts=0`, warning, return `"ran"`;
    - `failed` whose reason starts with `test-review` → `_stop` at once (like `ci-red`).
  - The claims client for the tester comes from `claimclient.from_env()`, built once in `run_loop` (a deps key `tester_claims`, so tests inject a fake). `build_claims` still returns None for a tester.
  - `run_loop` starts no QaThread for a tester.

- [ ] **Step 1: Failing tests** (fake `run_task`, fake hub via `plan_hub`, a fake claims client, a fake `pick_tester` monkeypatched where simpler):
  - a story task runs, ends `done`, and the next pick happens;
  - `blocked-env not-deployed` → story waiting, no attempt counted, the next pick skips it;
  - `env-locked` → idle until the time passes;
  - `incomplete` twice → skipped, not stopped;
  - `failed test-review X` → stopped;
  - `nothing` → `"done"` (`run_loop` returns `EXIT_DONE`);
  - all waiting → `"idle"`;
  - the BA/Dev `_settle` paths are unchanged (an existing test still passes; add one that a Dev `incomplete`-like `failed` still counts).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** the runner, picker and state tests — PASS. **Step 5: Commit** `feat: kb auto run drives a tester repo`.

---

### Task 4: Tester preflight, merge policy, settings

**Files:**
- Modify: `src/strata_kb/autorun/runner.py` (`preflight`), `src/strata_kb/autorun/ghpolicy.py`, `src/strata_kb/initcmd.py`
- Test: `tests/test_autorun_runner.py` (preflight), `tests/test_autorun_ghpolicy.py`, `tests/test_init_settings.py`, `tests/test_init_tester.py`

**Interfaces:**
- Produces:
  - `preflight` accepts `tester`, with the message "auto mode needs 'ba', 'dev' or 'tester'". For a tester, it adds `_tester_refusals(root, kb_dir)`, which returns these refusals:
    - on cloud → "tester auto runs on the Tester's machine, not on cloud";
    - `testenv.load(root)` fails, or `testenv.verify(root)` != 0 → "test environment not verified — run `/tester-env-setup`" (verify's output goes to the log, not the refusal);
    - each app without `version_check` → "app `<repo>` has no version_check: auto cannot confirm a deploy";
    - the Playwright/Chromium probe fails. Run `npx --no-install playwright --version`, then `node -e` with a headless Chromium launch-and-close through the repo's `@playwright/test`, each with a 60 s timeout (injectable `run`). Refusal: "Playwright with Chromium is not usable here: <first stderr line>";
    - `.claude/settings.json` `permissions.deny` contains `Bash(kb pr merge*)` → "run `kb init --kind tester` to refresh the auto-mode settings";
    - `claimclient.from_env()` raises → "the hub claim API is not set: <reason>".
  - `ghpolicy.REQUIRED_JOBS["tester"] = ("lint",)`. `_GUIDE["tester"] = "Tester"`. `preflight` runs `ghpolicy.refusals` for `tester` too.
  - `initcmd.TESTER_DENY` without `Bash(kb pr merge*)`. Add `RETIRED_TESTER_DENY = ("Bash(kb pr merge*)",)`. For a tester repo, the settings merge removes those exact strings from the existing `deny` before the union. The BA/Dev merge is unchanged. Update the comment above `TESTER_DENY`: the merge is now per mode in the skill body, and auto merges under policy C.

- [ ] **Step 1: Failing tests:**
  - preflight for a tester: each refusal on its own (fakes for verify, run and cloud); none when everything is ok;
  - ghpolicy requires `lint` for a tester;
  - an existing tester settings file with `Bash(kb pr merge*)` in `deny` loses it on refresh, and keeps every other deny;
  - a dev settings file with that string keeps it;
  - a fresh tester settings file has no `Bash(kb pr merge*)` deny, and still has `Bash(gh pr merge*)` and the `--admin` deny.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** the four test files — PASS. **Step 5: Commit** `feat: tester auto preflight and merge settings`.

---

### Task 5: `/tester-test-story` Auto mode

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/tester-test-story.md`
- Test: `tests/test_tester_skills.py`

**Interfaces:**
- Consumes: Task 1 result forms (exact strings).
- Produces: a `## Auto mode` section at the end of the body, before the review contract or after it, following the `ba-ticket-author` style. It opens with "Run `kb auto status --json`. When `enabled` is false, this section does not apply." It covers design E4, point by point:
  - the crash check (Already finished);
  - deploy check: no manual confirm, `blocked-env <story> not-deployed`;
  - lock exit 3 → `env-locked`; claim exit 3 → `claim-taken`;
  - reviews must be subagents (`failed test-review no-subagents`); a standing BLOCKER → `failed test-review <id>`;
  - `INCOMPLETE` → `incomplete <story>`; `BLOCKED-ENV` → `blocked-env <story> env-unhealthy`;
  - the merge rule (`kb pr checks --watch`, up to 2 fix rounds, `kb pr merge --squash --delete-branch`, `blocked-review` when a review is needed, `kb pr view --json` after a merge error, release after the merge);
  - a Result line block listing the 7 forms.

  Also remove the phase-1 sentence "The text `AUTO-RESULT: failed test-review` is reserved for the unattended runner of a later phase: do not write it in this phase." The Stop rule then points to the Auto mode section for unattended runs. Manual steps keep "Never merge it: a human reviews and merges".

- [ ] **Step 1: Failing tests:**
  - the body has the `## Auto mode` heading;
  - each of the 7 forms appears verbatim;
  - `kb pr merge --squash --delete-branch` appears;
  - "Never merge it" still appears (manual);
  - the reserved-phase sentence is gone;
  - the rendered Claude, Copilot and Cursor skill files carry the section (the existing render test pattern).
- [ ] **Step 2: Run** — FAIL. **Step 3: Write.** **Step 4: Run** `tests/test_tester_skills.py tests/test_template_bodies.py` — PASS. **Step 5: Commit** `feat: /tester-test-story auto mode`.

---

### Task 6: `/tester-strategy --amend` Auto mode and the `auto-reordered` badge

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/tester-strategy.md`, `src/strata_kb/teststrategy.py`, `src/strata_kb/web/testui.py`, the strategy page and panel templates under `src/strata_kb/web/templates/`
- Test: `tests/test_tester_skills.py`, `tests/test_teststrategy.py`, the web test of the strategy page/panel (`tests/test_web_tests*.py` or the file that covers `_panel`)

**Interfaces:**
- Produces:
  - A body section `## Auto mode` per design E5:
    - allowed changes: re-pin, re-point, add a row or a `last` row, a rank change with evidence and an agreeing reviewer;
    - Auto decision lines; the reviewer loop; a rank change objected to twice is dropped, and its proposal is recorded;
    - the Review cell starts with `auto`; a rank change adds `priority`;
    - branch `auto/strategy` (`-r2`, … rule); lint, Q1, `kb pr checks --watch`, `kb pr merge --squash --delete-branch`, `blocked-review`;
    - results `done`, `blocked-review <pr-url>`, `failed <lint|ci-red|test-review> …`;
    - never write a new strategy in auto.

    It replaces the line "Auto mode is not available yet: the Tester decides every change." with a pointer to the section. The manual amend keeps "Never merge".
  - `teststrategy.auto_reordered(text: str) -> int | None`. Walk `planrev.parse_change_log(text)` from the end, back to the last row whose `review` does not start with `auto` (case-insensitive, stripped). Among the rows after it, return the max `rev` of those with `priority` in their triggers, or None if there are none.
  - `testui._panel` adds `"auto_reordered": teststrategy.auto_reordered(view.text)`. The strategy page context gets the same key. The templates show `auto-reordered (rev N)` as a badge when it is set (follow the existing badge markup, e.g. the regrounding one).

- [ ] **Step 1: Failing tests:**
  - `auto_reordered`: none; an auto priority row → rev; a later human row clears it; an auto row without priority → None; two auto priority rows → the max;
  - the panel and the page render the badge;
  - the body has `## Auto mode`, `auto/strategy` and `**Auto decision:**`;
  - the "not available yet" line is gone.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** the touched test files — PASS. **Step 5: Commit** `feat: tester strategy auto amend and auto-reordered badge`.

---

### Task 7: Tester guide (EN + VI, PDFs), README, QUICKSTART, CHANGELOG

**Files:**
- Create: `docs/src/guide-tester.en.md`, `docs/src/guide-tester.vi.md`, `docs/strata-guide-tester.en.pdf`, `docs/strata-guide-tester.vi.pdf`
- Modify: `docs/src/build_pdf.py` (titles for `guide-tester.en` / `.vi`), `README.md` (guide list), `src/strata_kb/templates/init/QUICKSTART-tester.md` (link and an auto paragraph), `CHANGELOG.md` (1.37.3 bullets: tester `kb auto`, strategy auto amend and badge, Tester guide, merge deny change)
- Test: `tests/test_doc_lint.py`, `tests/test_build_pdf.py`, `tests/test_readme.py`

**Interfaces:**
- Produces: the guide follows `guide-dev.en.md`'s numbering and layout:
  - 1 what the Tester does;
  - 2 setup: install, `kb init --kind tester`, hub, registry, assistant, `/tester-env-setup`;
  - 3 daily work: `/tester-strategy`, `kb test next`, `/tester-test-story`, the report rounds, regression and bug candidates, the Test Report menu, `kb test stale`;
  - 4 auto mode: security first, merge policy (required `lint` and CODEOWNERS), set up once (Chromium, `version_check`, settings refresh), run and stop, what it does and when it stops (the E6 table);
  - 6 reference: config keys and env vars, git-ignored folders, auto-mode permissions.

  The VI file mirrors the EN headings one for one. It names only real `kb` commands and slash commands, and carries no version numbers (doc lint). Build the PDFs with `python docs/src/build_pdf.py` (see its `main`, and how the other guides were built).

- [ ] **Step 1: Write** the EN guide, then the VI guide. **Step 2: Run** `tests/test_doc_lint.py tests/test_build_pdf.py tests/test_readme.py` — PASS. **Step 3: Build** the PDFs and check they open (page count > 1). **Step 4: Run** the full suite once (19 baseline env failures only), and `STRATA_KB_CLOUD=0 KB_VENV=.venv` tests-gate if any MCP or CLI surface changed. **Step 5: Commit** `docs: Tester guide (EN, VI) and 1.37.3 notes`.
