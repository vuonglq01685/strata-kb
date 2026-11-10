# Harness sprint 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb auto run` can run unattended: GitHub-enforced merge safety (policy C), a record per task run, a hook that forces the `AUTO-RESULT:` line, parked PRs that wait for a human, allowlist gaps closed, ticket grounding in CI, and `kb upgrade` to roll it out.

**Architecture:** The runner stays a subprocess driver of `claude -p`. New small modules under `src/strata_kb/autorun/` (`runlog.py`, `ghpolicy.py`, `guard.py`) hold the logic; `cli.py` only gets thin commands. Everything that reaches running repos goes through the init templates and `kb upgrade`.

**Tech Stack:** Python 3.11+, typer, pytest, `gh` via `ghrest.api`, Markdown/JSON/YAML templates in `src/strata_kb/templates/init/`.

**Spec:** `docs/superpowers/specs/2026-11-10-harness-sprint1-design.md` (G1–G7). Read it first; this plan does not repeat its rationale.

## Global Constraints

- Version `1.35.0` → `1.36.0` (Task 10): `pyproject.toml`, `uv.lock`, `tests/test_readme.py`, new `## 1.36.0 — 2026-11-10` CHANGELOG entry.
- No new Python dependency.
- No new required CI job name. `kb-pr-lint`/`pr-lint` and `kb-ticket-lint`/`lint` stay frozen.
- `state.json`: only the additive `waiting_review` field; an old file loads unchanged.
- Fail closed: any GitHub read error in the policy check is a refusal, never a pass.
- A broken guard never wedges a session: internal error → exit 0, no output.
- Template text is pinned by `tests/test_templates.py` / `tests/test_template_bodies.py`: update the canon in the same task as the text.
- Docs en + vi.
- Test gate per task: the touched test files pass; before the last commit the full `pytest -q`, `ruff check`, `ruff format --check`, `pyright` are clean apart from baseline failures (record the baseline in Task 1 step 0).

## Review Focus

1. **Claude CLI older than the envelope fields** (plain-text stdout, or no `session_id`/`total_cost_usd`): run record still written with `None` fields, task result unchanged. → Task 1 test `test_meta_missing_fields_are_none`.
2. **Stop hook on a non-auto session or a nested `kb summarize`**: never blocks. → Task 4 tests `test_guard_silent_outside_auto`, `test_llm_runner_drops_auto_task_env`.
3. **Repo set up by today's docs (classic protection, no CODEOWNERS)**: preflight refuses with fix text naming each missing piece, not a traceback. → Task 7 test `test_refusal_lists_every_missing_piece`.
4. **Parked PR closed without merge, or `kb pr view` erroring**: closed → dropped with a warning; error → stays parked, loop continues. → Task 3 tests `test_parked_closed_is_dropped`, `test_parked_view_error_keeps_waiting`.
5. **`kb upgrade` on a repo whose `.claude/settings.json` has the owner's own allow/deny/hooks**: kept, only additions merged. → Task 9 test `test_upgrade_keeps_user_settings`.

---

### Task 1: Run record (`runs.jsonl`)

**Files:**
- Modify: `src/strata_kb/llm.py` (add `envelope_meta`)
- Modify: `src/strata_kb/autorun/claude.py` (`TaskResult.meta`, `_write_log` returns `Path`, `run_task` fills meta)
- Create: `src/strata_kb/autorun/runlog.py`
- Modify: `src/strata_kb/autorun/runner.py` (`run_once` around the `run_task` call, ~line 557)
- Modify: `src/strata_kb/autorun/qathread.py` (`_answer`, ~line 177)
- Test: `tests/test_autorun_claude.py`, `tests/test_autorun_runlog.py` (new), `tests/test_autorun_runner.py`, `tests/test_autorun_qathread.py`

**Interfaces:**
- Produces:
  - `llm.envelope_meta(stdout: str) -> dict[str, object]` — keys `session_id`, `total_cost_usd`, `num_turns`, `duration_ms`, `is_error`, `subtype`; a key absent or stdout not a JSON object → value `None`. Never raises.
  - `claude.TaskResult.meta: Mapping[str, object] = field(default_factory=dict)` (frozen dataclass stays frozen; use `types.MappingProxyType` or a plain dict built once). `run_task` puts the envelope meta plus `"log": str(log_path)` in it on every return path (timeout/OSError: envelope keys `None`).
  - `runlog.RUNS_NAME = "runs.jsonl"`
  - `runlog.append(kb_dir: Path, *, skill: str, arg: str, attempt: int, result: TaskResult, started_at: str, ended_at: str, head_before: str | None, head_after: str | None) -> None` — writes one line `{"schema": 1, "run_id": uuid4 hex, "started_at", "ended_at", "skill", "arg", "attempt", "outcome": result.kind, "reason", "ids": list, "session_id", "cost_usd", "turns", "duration_ms", "head_before", "head_after", "log"}` to `kb_dir/"auto"/RUNS_NAME` with one `os.write` on an `O_APPEND|O_CREAT` fd. `OSError` → `logging.warning`, no raise.

- [ ] **Step 0:** Record the baseline: `pytest -q 2>&1 | tail -5` and note any failing test ids in the task report.
- [ ] **Step 1: Write failing tests.**
  - `test_autorun_claude.py::test_meta_kept_from_envelope` — fake reply dict `{"type":"result","result":"x\nAUTO-RESULT: done","session_id":"s1","total_cost_usd":0.5,"num_turns":7,"duration_ms":1200}` → `result.meta["session_id"] == "s1"`, `["total_cost_usd"] == 0.5`, `["num_turns"] == 7`, `Path(result.meta["log"]).exists()`.
  - `test_meta_missing_fields_are_none` — plain string reply → `result.kind == "done"`, `result.meta["session_id"] is None`.
  - `test_timeout_meta_has_log` — timeout path → `result.meta["log"]` set, `session_id` None.
  - `test_autorun_runlog.py::test_append_writes_one_schema1_line` — two appends → two lines, each `json.loads` with `schema == 1`, distinct `run_id`.
  - `test_append_oserror_only_warns` — `kb_dir/"auto"` is a file → no raise, warning in `caplog`.
  - `test_autorun_runner.py::test_run_once_records_run` — after one `run_once` with a fake `run_task` returning `TaskResult("done", meta={"session_id": "s"})`, `runs.jsonl` has one line with `skill`, `arg`, `attempt == 0`, `outcome == "done"`, `session_id == "s"`.
  - `test_autorun_qathread.py::test_answer_records_run` — line with `skill == "ba-answer-questions"`.
- [ ] **Step 2:** Run `pytest tests/test_autorun_claude.py tests/test_autorun_runlog.py tests/test_autorun_runner.py tests/test_autorun_qathread.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the interfaces above. `head_before`/`head_after` via `gitio.head_commit(root)` wrapped in `try/except gitio.GitError → None`; in `run_once` take `head_before` before `run_task` and `head_after` before `_restore_branch`. Fake `run_task`s in existing tests return `TaskResult` without meta — `runlog.append` must accept empty meta (`.get`).
- [ ] **Step 4:** Re-run the Step 2 command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: record every auto task run in .kb/auto/runs.jsonl`.

### Task 2: `AUTO-RESULT: blocked-review <pr-url>` parsing

**Files:**
- Modify: `src/strata_kb/autorun/claude.py` (`Kind`, `parse_result`, `prompt_for`)
- Test: `tests/test_autorun_claude.py`

**Interfaces:**
- Produces: `Kind` gains `"blocked-review"`; `parse_result` returns `TaskResult("blocked-review", (url,))` when the rest is one token matching `https://[^\s]+/pull/\d+`; anything else → existing `bad result line`. `claude.RESULT_FORMS: tuple[str, ...]` — the five line templates `prompt_for` prints (Task 4 reuses it).

- [ ] **Step 1: Failing tests:** `test_parse_blocked_review` (`"AUTO-RESULT: blocked-review https://github.com/o/r/pull/12"` → kind, ids `("https://github.com/o/r/pull/12",)`); `test_parse_blocked_review_bad_url` (`"... blocked-review soon"` → `failed`, reason starts `bad result line`); `test_prompt_lists_five_forms` (`prompt_for(...)` contains every `RESULT_FORMS` entry and says "one of these five forms").
- [ ] **Step 2:** `pytest tests/test_autorun_claude.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat: blocked-review result form`.

### Task 3: Park PRs waiting for a human (`waiting_review`)

**Files:**
- Modify: `src/strata_kb/autorun/state.py` (field + `_parse`)
- Modify: `src/strata_kb/autorun/runner.py` (`_settle`, `_skip`, `run_once` before `_task_for`, `_after_task`, `_beat_waiting`)
- Modify: `src/strata_kb/autorun/switch.py` (`status` adds `"waiting_review"`)
- Test: `tests/test_autorun_state.py`, `tests/test_autorun_runner.py`, `tests/test_autorun_switch.py`

**Interfaces:**
- Consumes: Task 2's `blocked-review` kind; `ghrest.view_pr(root, ref) -> dict` (fields as `_pr_json` emits; merged/closed state — read `_pr_json` for the key names).
- Produces: `AutoState.waiting_review: tuple[str, ...] = ()`, each entry `"<task-key> <pr-url>"`. `runner._review_check(root: Path, kb_dir: Path, state: AutoState, view_pr=ghrest.view_pr) -> AutoState`.

Behaviour (spec G7): `_settle` on `blocked-review` → no attempt counted, `task=None`, `attempts=0`, entry appended (deduped). `_skip` adds every parked task key. `_review_check` per entry: merged → removed and `last_done=<key>` (same as `done`); closed unmerged → removed, `logger.warning`; open → kept; `KbError` from `view_pr` → kept, `logger.warning`. Dev claims: `_after_task` maps `blocked-review` → phase `"review"` (a `PR_PHASES` phase, so the claim does not expire; pass the PR url if `claims.phase` takes one — check `RunnerClaims.phase`). Nothing pickable while PRs are parked → `run_once` returns `"idle"` (the loop sleeps, never stops).

- [ ] **Step 1: Failing tests:**
  - `test_autorun_state.py::test_old_state_loads_without_waiting_review` (JSON without the key → `()`), `test_waiting_review_roundtrip`, `test_waiting_review_must_be_strings` (→ `_empty()` with warning).
  - `test_autorun_runner.py::test_blocked_review_parks_without_attempt`, `test_parked_task_is_skipped_by_pick`, `test_parked_merged_counts_done` (`last_done` set, entry gone), `test_parked_closed_is_dropped`, `test_parked_view_error_keeps_waiting`, `test_only_parked_left_is_idle_not_stop`.
  - `test_autorun_switch.py::test_status_lists_waiting_review`.
- [ ] **Step 2:** `pytest tests/test_autorun_state.py tests/test_autorun_runner.py tests/test_autorun_switch.py -q` → FAIL.
- [ ] **Step 3: Implement.** Call `_review_check` right after the `waiting_split` block in `run_once`; save state only when it changed.
- [ ] **Step 4:** Same command, plus `pytest tests-gate -q -k regression` → PASS.
- [ ] **Step 5: Commit** `feat: park auto tasks whose PR waits for a human review`.

### Task 4: `kb guard stop` and nested-run env

**Files:**
- Create: `src/strata_kb/autorun/guard.py`
- Modify: `src/strata_kb/cli.py` (hidden `guard` typer group, command `stop`, beside the `usage` group)
- Modify: `src/strata_kb/llm.py` (`Runner` child env drops `STRATA_KB_AUTO_TASK`)
- Test: `tests/test_autorun_guard.py` (new), `tests/test_llm.py`

**Interfaces:**
- Consumes: `claude.parse_result`, `claude.RESULT_FORMS`, `claude.AUTO_TASK_ENV`.
- Produces: `guard.stop_decision(payload: dict, env: Mapping[str, str]) -> dict | None` — `None` = allow. Returns `{"decision": "block", "reason": <text listing RESULT_FORMS>}` only when `env.get(AUTO_TASK_ENV) == "1"`, `payload.get("stop_hook_active")` is not true, and the last assistant text fails `parse_result` with reason `no result line` or starting `bad result line`. Last assistant text: `payload["last_assistant_message"]` when a str, else the last `assistant` row's text blocks from `payload["transcript_path"]` (JSONL; reuse `usage.transcript._rows` if it fits, else read lines). CLI: `kb guard stop --hook-stdin` reads stdin JSON, prints `json.dumps(decision)` when not None, always exits 0; any exception → exit 0, no stdout, one line appended to `.kb/auto/logs/guard.log` if `.kb/auto` exists.

- [ ] **Step 1: Failing tests:** `test_guard_blocks_missing_line`, `test_guard_blocks_bad_line`, `test_guard_allows_valid_line` (each of the five forms), `test_guard_never_blocks_when_stop_hook_active`, `test_guard_silent_outside_auto`, `test_guard_reads_transcript_when_no_last_message`, `test_cli_guard_stop_bad_json_exits_zero_silently` (CliRunner, stdin `"{"`); `test_llm.py::test_llm_runner_drops_auto_task_env` (monkeypatch env `STRATA_KB_AUTO_TASK=1`, fake claude records `auto_task` → `None`).
- [ ] **Step 2:** `pytest tests/test_autorun_guard.py tests/test_llm.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat: kb guard stop forces the AUTO-RESULT line`.

### Task 5: Auto settings — deny `--admin`, Stop guard hook, allowlist gaps

**Files:**
- Modify: `src/strata_kb/templates/init/claude-settings-auto.json`
- Test: `tests/test_init_settings.py`, `tests/test_templates.py`

**Interfaces:**
- Consumes: Task 4's command line `kb guard stop --hook-stdin`.
- Produces: settings template with deny `Bash(gh pr merge*--admin*)`, `Bash(kb pr merge*--admin*)`, `Bash(kb upgrade*)`; a **separate** `Stop` hook group `{"hooks":[{"type":"command","command":"kb guard stop --hook-stdin","timeout":10}]}`; narrowest allow patterns for `kb get`, `mkdir`, `kb build`, `kb summarize`, `kb approve` forms used by auto-mode paths of `templates/init/bodies/*.md` and `claude-command-*.md` / `claude-skill-*.md` (grep them; a form used only outside auto mode is not added).

- [ ] **Step 1: Failing tests:**
  - `test_init_settings.py::test_guard_hook_reaches_existing_settings` — existing settings holding only today's Stop usage group → after `merge_settings`, `Stop` has two groups, guard included.
  - `test_templates.py::test_auto_settings_deny_admin_merge`, `test_auto_settings_stop_guard_own_group`.
  - `test_templates.py::test_auto_commands_are_allowed` — for every `kb <sub>` and `mkdir` command inside a fenced or backticked span in each body's `## Auto mode` section, some allow pattern matches it (`fnmatch` on `Bash(<cmd>)`); an explicit `EXEMPT` set lists any deliberate gaps with a one-line reason.
- [ ] **Step 2:** `pytest tests/test_init_settings.py tests/test_templates.py -q` → FAIL.
- [ ] **Step 3: Implement** (JSON only; adjust the test's extraction if bodies use another heading for auto mode).
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat: auto settings deny admin merge, add result guard, close allowlist gaps`.

### Task 6: CODEOWNERS scaffold (created once)

**Files:**
- Create: `src/strata_kb/templates/init/codeowners`
- Modify: `src/strata_kb/initcmd.py` (`BA_LOCAL_OVERRIDES` / dev local-overrides maps gain `".github/CODEOWNERS": "codeowners"`; export `CODEOWNERS_PLACEHOLDER = "@OWNER"`)
- Test: `tests/test_init.py`

**Interfaces:**
- Produces: `initcmd.CODEOWNERS_PLACEHOLDER: str = "@OWNER"`. Template lines (one owner token each): `/.github/CODEOWNERS`, `/.github/workflows/`, `/.claude/settings.json`, `/.claude/agents/`, `/.claude/skills/`, `/.claude/commands/`, plus for ba `/docs/review-rubric.md`, `/docs/review-rubric.local.md` and for dev `/docs/pr-review-rubric.local.md`, `/docs/tdd-exemptions.md` (and the dev base rubric path if init scaffolds one — check `DEV_TEMPLATES`). A header comment: replace `@OWNER` with a user or team; GitHub ignores lines whose owner does not exist. Kind-specific lines: render with the existing `_render` or two template files — builder's call.

- [ ] **Step 1: Failing tests:** `test_init_scaffolds_codeowners_ba`, `test_init_scaffolds_codeowners_dev` (file exists, contains placeholder and `/.github/workflows/`); `test_reinit_never_refreshes_codeowners` (edit the file, re-run `init_repo` → unchanged, listed in `report.skipped`).
- [ ] **Step 2:** `pytest tests/test_init.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat: scaffold CODEOWNERS for sensitive paths`.

### Task 7: GitHub policy check (`ghpolicy`) in preflight and doctor

**Files:**
- Create: `src/strata_kb/autorun/ghpolicy.py`
- Modify: `src/strata_kb/autorun/runner.py` (`preflight` appends `ghpolicy.refusals(root, cfg.kind)`)
- Modify: `src/strata_kb/doctor/__init__.py` (`run`: for kind ba/dev, each refusal → `Issue("error", text)`)
- Test: `tests/test_autorun_ghpolicy.py` (new), `tests/test_autorun_runner.py`, `tests/test_doctor_run.py`

**Interfaces:**
- Consumes: `ghrest.api(root, method, path)`, `ghrest.origin_slug(root)`, `gitio.default_branch(root)`, Task 6's `initcmd.CODEOWNERS_PLACEHOLDER`.
- Produces: `ghpolicy.refusals(root: Path, kind: str, api=ghrest.api) -> list[str]` — empty = policy C holds. Order of checks and exact reads are in spec G1. Constants: `REQUIRED_JOBS = {"dev": ("pr-lint",), "ba": ("lint",)}`, `KB_TEST_WORKFLOW = ".github/workflows/kb-test.yml"`.

Rules (spec G1, condensed):
1. `GET repos/{slug}` → no `permissions` dict → refusal "could not read token permissions".
2. Required checks: union of ruleset `required_status_checks` contexts (`GET repos/{slug}/rules/branches/{b}`) and classic `protection.required_status_checks.contexts` (`GET repos/{slug}/branches/{b}`; admin: `/branches/{b}/protection`). Each `REQUIRED_JOBS[kind]` missing → one refusal naming it. Dev + `kb-test.yml` on the default branch (`GET repos/{slug}/contents/{path}?ref={b}`, 404 = absent) → every job's display name (`name:` else key) required too.
3. Code-owner review on (ruleset `pull_request.parameters.require_code_owner_review` or classic `required_pull_request_reviews.require_code_owner_reviews`).
4. `.github/CODEOWNERS` on the default branch, without `CODEOWNERS_PLACEHOLDER`.
5. `permissions.admin` true → additionally: every ruleset applying to the branch (`GET repos/{slug}/rulesets?includes_parents=true` + `GET repos/{slug}/rulesets/{id}`) has empty `bypass_actors`, or classic `enforce_admins.enabled` is true; else refusal "an admin can bypass the protection on <b>".
6. Any `GHError`/`KbError`/`OSError` on a read → refusal `could not read <what>: <why>` (fail closed); 404 on the rules/branch protection reads means "none", not an error.
Every refusal text ends with the fix (`see "Merge policy" in the Dev/BA guide`).

- [ ] **Step 1: Failing tests** (fake `api` keyed by path): `test_policy_ok_nonadmin_ruleset`, `test_policy_ok_admin_no_bypass`, `test_policy_ok_classic_enforce_admins`, `test_admin_with_bypass_actor_refused`, `test_missing_required_job_refused`, `test_kb_test_jobs_required_once_present`, `test_codeowners_missing_refused`, `test_codeowners_placeholder_refused`, `test_code_owner_review_off_refused`, `test_api_error_fails_closed`, `test_no_permissions_block_refused`, `test_refusal_lists_every_missing_piece` (classic protection, no CODEOWNERS → ≥3 distinct refusals, no exception); `test_autorun_runner.py::test_preflight_includes_policy_refusals` (monkeypatched `ghpolicy.refusals`); `test_doctor_run.py::test_doctor_reports_policy_refusals`.
- [ ] **Step 2:** `pytest tests/test_autorun_ghpolicy.py tests/test_autorun_runner.py tests/test_doctor_run.py -q` → FAIL.
- [ ] **Step 3: Implement.** Existing preflight/doctor tests that do not care must monkeypatch `ghpolicy.refusals` to `lambda *a, **k: []` (add a fixture in `tests/conftest.py` only if more than three files need it).
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat: refuse auto mode when GitHub would let the agent bypass review`.

### Task 8: Skill text — no `--admin`, `blocked-review`; `kb ticket check` in CI

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/dev-handover.md` (~285), `bodies/ba-ticket-author.md` (~487), `bodies/dev-test-workflow.md` (~133), `bodies/kb-auto.md` (step 2, step 9 ~137), `claude-command-dev-handover.md`, `claude-skill-ba-ticket-author.md`, and the Auto-mode result lists of every body whose skill merges a PR
- Modify: `src/strata_kb/autorun/switch.py` (`ADMIN_WARNING`)
- Modify: `src/strata_kb/templates/init/kb-ticket-lint.yml`
- Test: `tests/test_template_bodies.py`, `tests/test_templates.py`, `tests/test_autorun_switch.py`

**Interfaces:**
- Consumes: Task 2's form; the ready rule in `missionnext.py` (~lines 290–325 — expose it as a function if it is inline, e.g. `missionnext.dor_ticked(text: str) -> bool`, without changing its behaviour).
- Produces: exact replacement sentence in the three merging bodies and two inline copies: "Every check green: `kb pr merge --squash --delete-branch`. When the merge is refused for want of an approving review, do not retry: end `AUTO-RESULT: blocked-review <pr-url>`; a human reviews it." (keep the existing "After any merge error, run `kb pr view --json` …" sentence). `kb-auto.md` step 9: `kb pr merge auto/switch --squash --delete-branch`; refused for want of a review → tell the owner to review and merge `auto/switch`, then re-run `/kb-auto`. `ADMIN_WARNING` → "Auto mode merges its own pull requests once every required check is green; pull requests that touch code-owned paths wait for a human review. Set up the merge policy in the guide first." `kb-ticket-lint.yml`: for each changed `tickets/*` file that `python -c` reports ready (the function above), run `kb ticket check "$f" --hub "$STRATA_KB_HUB" --json`; FAIL sets `status=1`; summary table gains a `Grounding` column (`PASS`/`FAIL`/`-`).

- [ ] **Step 1: Failing tests:** `test_template_bodies.py::test_no_admin_merge_anywhere` (no `--admin` in any `templates/init/**` file), `test_merging_bodies_end_blocked_review`; `test_templates.py::test_ticket_lint_runs_ticket_check_for_ready` (workflow text contains `kb ticket check` inside the per-file loop and the ready guard); `test_autorun_switch.py::test_admin_warning_mentions_required_checks`; a unit test for the extracted ready function if one was extracted.
- [ ] **Step 2:** `pytest tests/test_template_bodies.py tests/test_templates.py tests/test_autorun_switch.py tests/test_missionnext*.py -q` → FAIL.
- [ ] **Step 3: Implement**, updating pinned canon in the same commit.
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat: skills park on missing review instead of admin merge; ticket check in CI`.

### Task 9: `kb upgrade`

**Files:**
- Create: `src/strata_kb/upgradecmd.py`
- Modify: `src/strata_kb/cli.py` (top-level `upgrade` command)
- Test: `tests/test_upgrade.py` (new)

**Interfaces:**
- Consumes: `initcmd.init_repo(target, kind) -> InitReport`, `gitio` (status/branch/commit/push helpers — use what `gitio` has), `ghrest.open_pr(root, title, body, head, base) -> dict`, `__version__`, `claude.AUTO_TASK_ENV`.
- Produces: `upgradecmd.upgrade(root: Path, *, open_pr: bool = True, opener=ghrest.open_pr) -> UpgradeResult` with `UpgradeResult(branch: str | None, report: InitReport, pr_url: str | None)`. Branch `kb/upgrade-<__version__>` from the default branch; commit message `chore: kb upgrade to <version>`; PR title the same, body = created/updated/skipped/notes lists. CLI `kb upgrade [--no-pr]`. Refusals (`KbError`, one red line): dirty tree, kind not ba/dev, `AUTO_TASK_ENV == "1"`, branch already exists. No change → branch deleted, "already current", exit 0.

- [ ] **Step 1: Failing tests** (tmp git repo with a bare origin; fake opener): `test_upgrade_refuses_dirty_tree`, `test_upgrade_refuses_in_auto_task`, `test_upgrade_no_change_leaves_no_branch`, `test_upgrade_commits_and_opens_pr`, `test_upgrade_no_pr_stops_after_commit`, `test_upgrade_keeps_user_settings` (settings with an extra allow + extra Stop hook survive, guard hook added).
- [ ] **Step 2:** `pytest tests/test_upgrade.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat: kb upgrade opens a PR with refreshed templates`.

### Task 10: Guides, CHANGELOG, version

**Files:**
- Modify: `docs/src/guide-dev.en.md`, `guide-dev.vi.md` (§4.1 branch protection), `guide-ba.en.md`, `guide-ba.vi.md` (~626–641), `bodies/kb-auto.md` docs if it explains merging, `CHANGELOG.md`, `pyproject.toml`, `uv.lock`, `tests/test_readme.py`
- Test: `tests/test_readme.py`, docs build test if one exists (`ls tests | grep -i docs`)

**Interfaces:** none new.

Content: a "Merge policy" section (same title in en/vi, the refusal texts point to it) with the identity rule and its residual risk, the ruleset JSON sample (required PR, required checks `pr-lint`/`lint` + `kb-test` jobs, `require_code_owner_review: true`, `required_approving_review_count: 0`, `bypass_actors: []`), CODEOWNERS owner step, `kb upgrade` usage, `runs.jsonl` and `blocked-review` in the auto-mode section. Remove the "include administrators" advice. CHANGELOG `## 1.36.0 — 2026-11-10`: one bullet per spec goal G1–G7.

- [ ] **Step 1:** Bump version in `pyproject.toml`, run `uv lock`, update `tests/test_readme.py`.
- [ ] **Step 2:** Write the guide sections and CHANGELOG.
- [ ] **Step 3:** Full gate: `pytest -q`, `ruff check`, `ruff format --check`, `pyright`. Expected: only the Task 1 baseline failures.
- [ ] **Step 4: Commit** `docs: merge policy, kb upgrade, run record; release 1.36.0`.

---

**Task order:** 1 → 10 as numbered. Tasks 6 and 9 are independent of 1–5 and may run earlier.
