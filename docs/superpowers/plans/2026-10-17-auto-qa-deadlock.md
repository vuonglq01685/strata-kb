# Auto Q&A deadlock + cloud-run fixes (1.30.2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One ticket the Q&A thread cannot finish never stops the BA loop, no draft is lost, and a cloud session runs `kb auto run` without a human fixing permissions, trust or the session branch (issue #124).

**Architecture:** Skill text (`bodies/ba-answer-questions.md`) lets the Q&A run re-ground on an `architecture` finding and resume a parked draft. `QaThread` runs one ticket per tick, parks a ticket on `dor-unticked` and saves its draft to `auto/qa-parked/<ticket>`. `run_once` stops with `parked: …` when only parked work is left and puts the repo root back on its branch after every task. `prompt_for` gains two rules; `run_task` gains `model`/`effort`; `kb auto run` gains `--model`/`--effort` and, on cloud, writes Claude Code trust for its directories.

**Tech Stack:** Python 3.11+, typer, pytest, git CLI via `strata_kb.gitio`.

**Spec:** `docs/superpowers/specs/2026-10-16-auto-qa-deadlock-design.md`

## Global Constraints

- Version **1.30.2** (patch, owner decided). `CHANGELOG.md` heading `## 1.30.2 — 2026-10-17`.
- Shared skill text is edited only in `src/strata_kb/templates/init/bodies/`; never in rendered stubs.
- Never add `git -C *` or GitNexus entries to `claude-settings-auto.json`; never touch its deny list.
- Trust is written only when `strata_kb.cloud.is_cloud()` is true.
- Never overwrite an unparseable `~/.claude.json`; keep every other key; write atomically (temp + `os.replace`).
- Only `dor-unticked` results park. `ci-red`, `hub-refused`, `qa-needs-hub-server`, crashes keep the two-in-a-row stop (`MAX_FAILURES = 2`).
- Park set is in memory only (lives as long as the `QaThread`).
- Parked branch name: `auto/qa-parked/<ticket>`. Parked branches are never deleted by code.
- Park stop reason: `parked: <t1>[, <t2>...]` (sorted), via `runner._stop` (exit 2).
- Every git failure in park-save or branch-restore is a logged warning, never a stop or crash.
- Before each commit: `pytest -q <touched test files>`; before push: `scripts/gate.sh`.

## Review Focus

- **Ticket id with odd characters** (`M-content-management-US1`, dots, slashes absent): branch `auto/qa-parked/<ticket>` must be a valid ref; a ticket id git rejects → warning, ticket still parked. Test in Task 3.
- **Root is not a git repo / detached HEAD** when `run_once` remembers the branch: no crash, task still runs; detached HEAD restores the commit. Tests in Task 4.
- **`~/.claude.json` missing, empty, invalid JSON, or `projects` not a dict**: create / skip-with-warning / skip-with-warning; never raise. Tests in Task 5.
- **Open questions whose dict lacks `ticket`** (older hub): treat as an unparked ticket `""`; run the skill with no arg (today's behaviour), never park `""`. Test in Task 3.
- **Draft save with nothing to commit** (skill stopped before editing): no push, ticket still parked. Test in Task 3.

---

### Task 1: Skill text — re-ground, resume a parked draft, one stop reason

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/ba-answer-questions.md` (step 3 bullets; `## Hard rules` bullets "One amendment per ticket…" and "Code-level detail…"; `## Auto mode` DoR bullet; `### Result line` `failed` bullet)
- Test: `tests/test_templates.py` (section `# --- ba-answer-questions`, ~line 3544)

**Interfaces:**
- Produces: the skill ends `AUTO-RESULT: failed dor-unticked <ticket-id>` for every ticket-level stop; it resumes from `auto/qa-parked/<ticket-id>`. Task 3 relies on both names.

- [ ] **Step 1: Write the failing test** `test_ba_answer_questions_regrounds_and_resumes_parked_draft` reading the rendered `claude-skill-ba-answer-questions.md` (use the file's existing `_read_init_template` + whitespace normalisation helper). Assert, each as a substring of the normalised text:
  - `question, architecture`
  - `kb_ticket_stale`
  - `auto/qa-parked/<ticket-id>`
  - `git fetch origin auto/qa-parked/<ticket-id>`
  - `git merge --no-edit FETCH_HEAD`
  - `git merge --abort`
  - `dor-unticked <ticket-id>`
  - and that `"the only amendment trigger this skill uses"` is **not** present.
- [ ] **Step 2: Run** `pytest tests/test_templates.py -k reground -q` → FAIL.
- [ ] **Step 3: Edit the body.** Content to carry (wording is the implementer's, meaning is fixed by spec §5.1–5.2):
  - Step 3 change-log bullet: Trigger is `question`; when `kb_ticket_stale` on the ticket reports an `architecture` finding, it is `question, architecture` and `/sa-ticket-ground` runs first as a separate run (ba-ticket-author amend step 4). Still one amendment, one bump, one row. `kb-context` findings are not re-pinned here.
  - Step 3 resume bullet: `git fetch origin auto/qa-parked/<ticket-id>`; if it exists, read the ticket's `> Revision:` on `FETCH_HEAD` with `git diff`/`git log -p`; merge with `git merge --no-edit FETCH_HEAD` only when that revision is above both the default branch's and the hub revision; else ignore it. Conflict → `git merge --abort` and amend fresh.
  - Hard rules: `question` stays exclusive to this skill; `/sa-ticket-ground` runs when `kb ticket check` fails with `re-run /sa-ticket-ground` **or** `kb_ticket_stale` reports an `architecture` finding.
  - Auto mode DoR bullet + Result line: every ticket-level stop (a DoR box unticked, `kb ticket check` still failing after the re-ground, `kb_ticket_lint` never passing) ends `failed dor-unticked <ticket-id>`; the runner saves the draft to `auto/qa-parked/<ticket-id>` and parks the ticket.
- [ ] **Step 4: Run** `pytest tests/test_templates.py tests/test_template_bodies.py tests/test_init.py -q` → PASS.
- [ ] **Step 5: Commit** `fix(auto): Q&A skill re-grounds architecture drift and resumes parked drafts (#124)`.

### Task 2: Task prompt rules and `run_task` model/effort

**Files:**
- Modify: `src/strata_kb/autorun/claude.py` (`prompt_for` ~57, `run_task` ~110)
- Test: `tests/test_autorun_claude.py`

**Interfaces:**
- Produces: `run_task(root: Path, prompt: str, *, log_dir: Path, executable: str = "claude", timeout: int = DEFAULT_TIMEOUT, model: str = "", effort: str = "") -> TaskResult`. Task 5 binds `model`/`effort` with `functools.partial`.

- [ ] **Step 1: Write failing tests:**
  - `test_prompt_for_forbids_git_dash_c`: `"never use `git -C`" in prompt_for("x", "", "ba")`.
  - `test_prompt_for_skips_unrunnable_repo_rule`: prompt contains `CLAUDE.md` and `skip that step` and `PR`.
  - `test_run_task_passes_model_and_effort`: monkeypatch `subprocess.run` in `strata_kb.autorun.claude` to capture `cmd` and return a `CompletedProcess` whose stdout is a valid JSON reply ending `AUTO-RESULT: done` (copy the shape from an existing run_task test); call with `model="claude-sonnet-5-5", effort="high"`; assert `cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5"` and `cmd[cmd.index("--effort") + 1] == "high"`.
  - `test_run_task_omits_empty_model_and_effort`: same, defaults → `"--model" not in cmd and "--effort" not in cmd`.
- [ ] **Step 2: Run** `pytest tests/test_autorun_claude.py -q` → 4 FAIL.
- [ ] **Step 3: Implement.** Two sentences added to `prompt_for`'s fixed text (before the AUTO-RESULT forms): "Run git from the working directory; never use `git -C`." and "When a rule of this repo (`CLAUDE.md`, `AGENTS.md`, …) needs a command you are not allowed to run, skip that step and name it in the PR's notes; do not stop or fail for it." `run_task` appends `--model <model>` / `--effort <effort>` only when non-empty (`claude --help` lists both flags).
- [ ] **Step 4: Run** `pytest tests/test_autorun_claude.py -q` → PASS (existing `prompt_for` tests still pass).
- [ ] **Step 5: Commit** `fix(auto): task prompt bans git -C and skips unrunnable repo rules; run_task model/effort (#124)`.

### Task 3: `QaThread` — one ticket per run, park on `dor-unticked`, save the draft

**Files:**
- Modify: `src/strata_kb/autorun/qathread.py`
- Test: `tests/test_autorun_qathread.py` (update `FakeQa` to return `{"id": i, "ticket": t}`; existing tests use ticket `"T-1"`)

**Interfaces:**
- Consumes: Task 1's result reason `dor-unticked <ticket-id>`; `gitio.checkout_branch`, `gitio.commit_all`, `gitio.has_remote`, `gitio.push_branch(root, branch, force=True)`.
- Produces (Task 4 uses these):
  - `PARKED_PREFIX = "auto/qa-parked/"` (module constant)
  - `QaThread.parked -> frozenset[str]` (property, under `self._lock`)
  - `QaThread.only_parked_left() -> bool`: True when `parked` is non-empty, the hub's open questions for the repo are non-empty, and every one's `ticket` is parked. A `KbError` from the hub → False.

- [ ] **Step 1: Write failing tests:**
  - `test_tick_runs_the_oldest_unparked_ticket`: FakeQa open `[(3, "T-b"), (2, "T-a")]` → runner prompt's first line is `/ba-answer-questions T-a`.
  - `test_dor_unticked_parks_the_launched_ticket_without_counting`: runner result `TaskResult("failed", (), "dor-unticked something-else")`, launched on `T-a` → after the answer finishes, `thread.parked == {"T-a"}` and `thread.failed_twice is False`; run it twice → still False.
  - `test_parked_ticket_is_skipped_next_tick`: after parking `T-a`, open `[(2,"T-a"),(3,"T-b")]` → next prompt names `T-b`; open only `[(2,"T-a")]` → `tick()` returns False.
  - `test_park_saves_draft_branch`: runner writes a file into the worktree before returning `dor-unticked T-a` → `git rev-parse --verify auto/qa-parked/T-a` succeeds in the repo and its tip contains the file (no remote in the fixture → no push).
  - `test_park_with_clean_worktree_creates_no_commit`: runner changes nothing → ticket parked, no new commit on `auto/qa-parked/T-a` beyond the base (or branch absent — pick one and assert it).
  - `test_park_git_error_is_a_warning`: monkeypatch `gitio.commit_all` to raise `gitio.GitError("boom")` → ticket still parked, no exception escapes, `caplog` has a WARNING containing `T-a`.
  - `test_question_without_ticket_runs_bare_and_never_parks`: open `[{"id": 1}]` → prompt first line `/ba-answer-questions`; a `dor-unticked` result then counts as a failure (two → `failed_twice`).
  - `test_other_failures_still_count`: `TaskResult("failed", (), "ci-red http://x")` twice → `failed_twice` True.
  - `test_only_parked_left`: parked `{"T-a"}` + open `[(2,"T-a")]` → True; + `(3,"T-b")` → False; nothing parked → False; no open questions → False; FakeQa `fail=True` → False.
- [ ] **Step 2: Run** `pytest tests/test_autorun_qathread.py -q` → new tests FAIL.
- [ ] **Step 3: Implement** in `qathread.py`:
  - `_next_ticket(questions: list[dict], parked: frozenset[str]) -> str | None` (module function): drop questions whose `ticket` is parked; return the `ticket` (`""` if absent) of the lowest `id`; `None` when nothing is left.
  - `tick`: list open questions once (`self._qa.list("open", repo=self._repo)`), pick with `_next_ticket`; `None` → return False; else fresh worktree and start `_answer(ticket)`.
  - `_answer(ticket: str)`: prompt `claude.prompt_for(SKILL, ticket, "ba")`. On `result.kind == "failed"` and `result.reason.startswith("dor-unticked")` and `ticket` non-empty → `_park(ticket)` and return without `_record`. Everything else unchanged.
  - `_park(ticket: str) -> None`: add to the set under the lock; in `self.worktree`: `checkout_branch(wt, PARKED_PREFIX + ticket, "HEAD")`, `commit_all(wt, f"auto: park Q&A draft for {ticket}")`, push with `push_branch(wt, branch)` only if committed and `has_remote(wt)`; `KbError` (GitError is one) → `logger.warning`. Always end with one `logger.warning("Q&A parked %s; draft on %s", ticket, branch)`.
  - `open_question_count` stays (runner uses it).
- [ ] **Step 4: Run** `pytest tests/test_autorun_qathread.py -q` → PASS.
- [ ] **Step 5: Commit** `fix(auto): Q&A thread parks a dor-unticked ticket and keeps its draft (#124)`.

### Task 4: `run_once` — stop on parked-only work; restore the root's branch

**Files:**
- Modify: `src/strata_kb/autorun/runner.py` (`run_once` ~269-317)
- Test: `tests/test_autorun_runner.py`

**Interfaces:**
- Consumes: `QaThread.parked`, `QaThread.only_parked_left()`, `PARKED_PREFIX` (Task 3).
- Produces: `_remember_branch(root: Path) -> str | None` and `_restore_branch(root: Path, ref: str | None) -> None` (module-private).

- [ ] **Step 1: Write failing tests:**
  - `test_parked_only_stops_the_loop`: a fake qa_thread object with `failed_twice=False`, `parked=frozenset({"T-a"})`, `only_parked_left()=True`; monkeypatch `picker.pick_ba` to return `None`; BA cfg; `_check_done` not finished (a `ready` story) → outcome `"stopped"`, saved state's `stop_reason == "parked: T-a"`.
  - `test_parked_with_task_left_keeps_running`: same but `pick_ba` returns a task → task runs, outcome not `"stopped"`.
  - `test_parked_with_unparked_question_idles`: `only_parked_left()=False`, no task → `"idle"`.
  - `test_root_branch_restored_after_task` (real repo via the `git_repo`/`run_git` fixtures): root on `main`; the fake `run_task` runs `git switch -c auto/US1` in root → after `run_once`, `gitio.current_branch(root) == "main"`.
  - `test_root_branch_restored_after_task_exception`: fake `run_task` switches branch then raises → branch is `main`, outcome is the existing failed-attempt path.
  - `test_detached_head_restores_commit`: root detached at commit X; task switches to a branch → `gitio.head_commit(root) == X`.
  - `test_restore_failure_is_a_warning`: task switches branch and leaves a conflicting dirty file so checkout fails → no exception, WARNING logged.
  - Existing `env` tests (root not a git repo) must still pass unchanged.
- [ ] **Step 2: Run** `pytest tests/test_autorun_runner.py -q` → new tests FAIL.
- [ ] **Step 3: Implement:**
  - `_remember_branch`: `gitio.current_branch(root)`; `"HEAD"` → `gitio.head_commit(root)`; `GitError` → `None`.
  - `_restore_branch`: `None` → return; current already equal (branch name or, when ref is a sha, `head_commit`) → return; else `gitio.checkout(root, ref)`; `GitError` → `logger.warning("could not return %s to %s: %s", root, ref, exc)`.
  - In `run_once`: wrap the `run_task` try/except in `try: … finally: _restore_branch(root, ref)` with `ref = _remember_branch(root)` taken just before.
  - After `task = _task_for(...)`, when `task is None` and `qa_thread is not None and qa_thread.only_parked_left()`: `parked = sorted(qa_thread.parked)` → `return _stop(kb_dir, state, "parked: " + ", ".join(parked), hint)` with hint `"Drafts are on " + ", ".join(PARKED_PREFIX + t for t in parked) + ". Fix the ticket, then run `kb auto run` to resume."`
- [ ] **Step 4: Run** `pytest tests/test_autorun_runner.py tests/test_autorun_qathread.py -q` → PASS.
- [ ] **Step 5: Commit** `fix(auto): stop on parked-only work and return the root to its branch after each task (#124)`.

### Task 5: `kb auto run --model/--effort` and cloud trust

**Files:**
- Create: `src/strata_kb/autorun/trust.py`
- Modify: `src/strata_kb/cli.py` (`auto_run` ~1081-1131)
- Test: `tests/test_autorun_trust.py` (new), `tests/test_cli_auto.py`

**Interfaces:**
- Consumes: `claude.run_task(..., model=, effort=)` (Task 2); `run_loop(root, kb_dir, hub_flag=..., run_task=...)` (existing `**deps`); `run_once(..., run_task=...)`; `cloud.is_cloud()`.
- Produces: `trust_dirs(paths: Sequence[Path], config: Path | None = None) -> None` — `config` defaults to `Path.home() / ".claude.json"`.

- [ ] **Step 1: Write failing tests** in `tests/test_autorun_trust.py`:
  - `test_trust_creates_file`: missing config → file has `{"projects": {"<abs a>": {"hasTrustDialogAccepted": true}}}`.
  - `test_trust_keeps_other_keys`: existing `{"x": 1, "projects": {"/o": {"k": 2}, "<abs a>": {"allowedTools": []}}}` → `x`, `/o` and `allowedTools` kept; `<abs a>` gains the flag.
  - `test_trust_skips_invalid_json`: config text `{nope` → unchanged bytes, WARNING logged, no raise.
  - `test_trust_skips_non_dict_projects`: `{"projects": []}` → unchanged, WARNING.
  - `test_trust_resolves_relative_paths`: `Path(".kb/auto/worktrees/qa")` under `monkeypatch.chdir(tmp)` → key is the absolute resolved path.
  In `tests/test_cli_auto.py`:
  - `test_auto_run_passes_model_and_effort`: monkeypatch `runner.preflight` → `[]`, `runner.run_loop` → capture kwargs and return 0; invoke `auto run --model m1 --effort high`; assert captured `run_task.keywords == {"model": "m1", "effort": "high"}`.
  - `test_auto_run_defaults_model_to_opus`: same setup, invoke `auto run` with no flags → `run_task.keywords == {"model": "opus", "effort": ""}`; `--model ""` → `{"model": "", "effort": ""}`.
  - `test_auto_run_writes_trust_on_cloud_only`: monkeypatch `trust.trust_dirs` to record; env `STRATA_KB_CLOUD=1` → called with `[root, root/".kb"/"auto"/"worktrees"/"qa"]` (resolved) for a BA config, `[root]` for Dev; env `STRATA_KB_CLOUD=0` → not called.
- [ ] **Step 2: Run** `pytest tests/test_autorun_trust.py tests/test_cli_auto.py -q` → FAIL.
- [ ] **Step 3: Implement:**
  - `trust.py`: read JSON if the file exists (empty file = `{}`); `ValueError`/non-dict root/non-dict `projects` → `logger.warning` and return; set `projects[str(p.resolve())].setdefault`→`["hasTrustDialogAccepted"] = True` (make the entry a dict if absent); write to a temp file in the same dir, `os.replace`. `OSError` on write → warning.
  - `cli.auto_run`: options `model: str = typer.Option("opus", "--model", help="Model for each task's claude -p (default opus; empty = claude's default)")`, `effort: str = typer.Option("", "--effort", help="Effort level for each task's claude -p (empty = claude's default)")`. Build `task_runner = functools.partial(claude.run_task, model=model, effort=effort)`; pass `run_task=task_runner` to both `run_once` and `run_loop`. After preflight passes and before the lock: `if cloud.is_cloud(): trust.trust_dirs(dirs)` where `dirs = [root]` plus `(kb_dir / "auto" / "worktrees" / "qa").resolve()` when `load_config(kb_dir).kind == "ba"`.
- [ ] **Step 4: Run** `pytest tests/test_autorun_trust.py tests/test_cli_auto.py tests/test_autorun_runner.py -q` → PASS.
- [ ] **Step 5: Commit** `fix(auto): kb auto run --model/--effort; trust task dirs on cloud (#124)`.

### Task 6: Release 1.30.2 — docs, changelog, version, gate

**Files:**
- Modify: `pyproject.toml` (`version = "1.30.2"`), `uv.lock` (strata-kb package version → regenerate with `uv lock` if `uv` exists, else edit the one `version` line of the `strata-kb` package), `CHANGELOG.md`, `tests/test_readme.py` (`test_version_is_1_30_1_everywhere` → `..._1_30_2_...`, expects `1.30.2` and `1.30.2 — 2026-10-17`), `README.md:308` (`run [--once] [--hub URL] [--model ID] [--effort LEVEL]`), `docs/src/guide-{ba,dev}.{en,vi}.md` command-table row (`run [--once] [--model] [--effort]`).

- [ ] **Step 1: Update** `tests/test_readme.py` version test first → run `pytest tests/test_readme.py -q -k version` → FAIL.
- [ ] **Step 2: Bump** pyproject, uv.lock; add `## 1.30.2 — 2026-10-17` to `CHANGELOG.md` above 1.30.1: one-line summary, then bullets **Q&A deadlock** (re-ground on `architecture`, park on `dor-unticked`, draft on `auto/qa-parked/<ticket>`, `parked: …` stop), **Task prompt** (no `git -C`; skip unrunnable repo rules, note in PR), **`kb auto run --model/--effort`**, **Cloud trust**, **Root branch restored**, and the line "The guide PDFs under `docs/` were not rebuilt for this release; the Markdown sources are current." (the version test asserts it). Update README and the four guide rows.
- [ ] **Step 3: Run** `pytest -q` → PASS, then `scripts/gate.sh` → green.
- [ ] **Step 4: Commit** `chore: release 1.30.2 (#124)` and push `fix/auto-qa-deadlock-124`.
