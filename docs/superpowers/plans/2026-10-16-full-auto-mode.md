# Full-auto mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-repo `auto:` switch and a `kb auto run` loop that drive a BA repo and a Dev repo unattended, one fresh `claude -p` process per task, until every ticket on the hub is done.

**Architecture:** A new `strata_kb.autorun` package holds the loop, modelled on `codesync/runner.py` (`run_once` is the unit, `run_loop` repeats it). It never holds model context: it picks the next task from `kb mission next` / `planstatus`, runs `claude -p "/<skill> <id>"` as a subprocess, parses an `AUTO-RESULT:` line, stores state in `.kb/auto/`, and repeats. The BA runner also starts a Q&A thread that answers open questions in a separate worktree and process. The shipped skill bodies gain an "Auto mode" section that turns each human gate into an agent decision when the switch is on. The hub gains one JSON route so the runner can read Q&A state without MCP.

**Tech Stack:** Python 3.12, typer, pydantic, starlette, subprocess, threading, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-16-full-auto-mode-design.md`

## Global Constraints

- Switch lives in `.kb/config.yaml` as `auto: {enabled: false, qa_interval: 300, idle_interval: 600, hotfix_base: ""}`; default off; off path of every skill body renders byte-for-byte as today.
- One task = one fresh `claude -p` process; permission mode `acceptEdits`, never `bypassPermissions` / `--dangerously-skip-permissions`.
- Result line contract (last non-empty line of the reply): `AUTO-RESULT: done` | `AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]` | `AUTO-RESULT: failed <reason>`. Missing line = `failed no result line`.
- Stop after **2** failed attempts of the same task (`failed ci-red ...` counts as both spent, stop at once). Usage-limit stops never count; backoff 900 s, doubling, cap 3600 s.
- Auto mode supports one BA and one Dev repo per hub; `kb auto on` warns (never refuses) when the registry lists more than one `dev`.
- `kb auto run` refuses when: switch off, kind not `ba`/`dev`, `intake:` empty, or the registry entry of this repo is not `auto_merge: true`.
- Stop condition: every mission story `done`, every unparented ticket/bug `done`; BA additionally needs no `open` questions and no `to-draft`/`draft`/`blocked` story.
- Admin merge (`gh pr merge --admin`) only after every required check is green.
- Commit message types: feat, fix, refactor, docs, test, chore. Version becomes `1.29.0`.

## Review Focus

1. A `claude -p` reply whose last line is not an `AUTO-RESULT:` line (agent chatted after it, or crashed) must become `failed no result line`, never `done` — pinned in Task 4.
2. `kb auto off` written while a task runs must stop the loop at the next boundary, never kill the running process — pinned in Task 7.
3. A Dev question whose state is `waiting` (answered, ticket not yet republished) must not resume the ticket — pinned in Task 7.
4. The BA Q&A thread must never start a second process while one runs, and must run in its worktree, not the main tree — pinned in Task 8.
5. Merging an existing `.claude/settings.json` must keep the user's own `permissions.allow` entries and hooks — pinned in Task 10.

---

### Task 1: `auto:` config block and `kb auto on|off|status`

**Files:**
- Modify: `src/strata_kb/config.py` (add `AutoConfig`, field on `KBConfig`)
- Modify: `src/strata_kb/templates/init/config-ba.yaml`, `config-dev.yaml` (commented `auto:` block)
- Create: `src/strata_kb/autorun/__init__.py`, `src/strata_kb/autorun/switch.py`
- Modify: `src/strata_kb/cli.py` (new `auto_app` typer: `on`, `off`, `status`; `run` comes in Task 9)
- Test: `tests/test_autorun_switch.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `AutoConfig(enabled: bool=False, qa_interval: int=300, idle_interval: int=600, hotfix_base: str="")` on `KBConfig.auto`.
- Produces: `switch.set_enabled(config_path: Path, on: bool) -> None` (edits only the `auto.enabled` line, keeps comments; appends an `auto:` block when absent, like `_record_kind` in `initcmd.py`).
- Produces: `switch.warnings_for_on(kb_dir: Path, hub: str) -> list[str]`: always the admin-merge/no-review warning; plus the one-Dev warning when `load_registry(handle.federation_dir)` has >1 entry with `kind == "dev"` (hub resolved with `cli._hub_or_reason`; unreachable hub adds a "registry not checked" line).
- Produces: `switch.status(kb_dir: Path) -> dict` = `{"enabled", "qa_interval", "idle_interval", "hotfix_base", "task", "attempts", "waiting_on", "stop_reason"}` (state fields from Task 5; `None` before any run).

- [ ] **Step 1: Write failing tests**

```python
def test_auto_config_defaults_off(tmp_path):
    (tmp_path / "config.yaml").write_text("kind: ba\n")
    assert load_config(tmp_path).auto == AutoConfig()

def test_set_enabled_edits_only_the_flag(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("kind: ba\n# keep me\nauto:\n  enabled: false\n  qa_interval: 120\n")
    set_enabled(p, True)
    assert "# keep me" in p.read_text() and "qa_interval: 120" in p.read_text()
    assert load_config(tmp_path).auto.enabled is True

def test_set_enabled_appends_block_when_absent(tmp_path): ...

def test_warnings_mention_admin_merge_and_two_devs(hub_with_two_dev_repos): ...

def test_cli_auto_status_json(tmp_path, runner): ...  # exit 0, enabled false
def test_cli_auto_on_refuses_outside_ba_dev(tmp_path, runner): ...  # kind child → exit 1
```

- [ ] **Step 2: Run, verify FAIL** — `pytest tests/test_autorun_switch.py -v` → ImportError.
- [ ] **Step 3: Implement `AutoConfig`, `switch.py`, `auto_app` (`kb auto on` prints warnings in plain prose, then `auto: on`; `off`; `status [--json]`).**
- [ ] **Step 4: Run, verify PASS** — `pytest tests/test_autorun_switch.py tests/test_config.py -v`.
- [ ] **Step 5: Commit** — `feat: auto switch in .kb/config.yaml and kb auto on/off/status`

### Task 2: Status for unparented tickets and bugs; "all done" helper

**Files:**
- Modify: `src/strata_kb/planstatus.py` (`PlanRepo.unparented` becomes `list[StoryStatus]` with status `done`/`ready`; `_done_ids` reused), `src/strata_kb/missionnext.py` (`to_json` gains `unparented`, `render` lists them under `Unparented:`)
- Modify: `src/strata_kb/cli.py` `mission_next --from-hub`, `src/strata_kb/mcp.py` `kb_mission_next` (pass the new list through)
- Create: `src/strata_kb/autorun/done.py`
- Test: `tests/test_planstatus.py`, `tests/test_autorun_done.py`

**Interfaces:**
- Produces: `planstatus.next_from_hub(hub, repo=None) -> tuple[list[StoryStatus], list[StoryStatus], list[str]]` (stories, unparented, notes). Unparented `StoryStatus` has `mission_id=""`, status `done` when its id is in `_done_ids` of the plan doc, else `ready`; `done=None` → `ready` with reason `"done: unknown"`.
- Produces: `missionnext.to_json(results, notes, unparented=()) -> dict` with key `"unparented": [...]`.
- Produces: `done.all_done(stories, unparented, *, ba: bool, open_questions: int = 0) -> tuple[bool, str]` — `(True, "all N tickets done")` or `(False, "<first reason>")`; BA also requires `open_questions == 0` and no story in `to-draft`/`draft`/`blocked`.

- [ ] **Step 1: Write failing tests**

```python
def test_unparented_bug_is_done_when_in_hist(hub_with_plan_and_svc_hist):
    stories, unparented, _ = next_from_hub(hub)
    assert {u.us_id: u.status for u in unparented} == {"BUG-1": "done", "BUG-2": "ready"}

def test_to_json_carries_unparented(): ...

def test_all_done_dev_requires_every_story_and_bug():
    ok, why = all_done([S("US1","done")], [S("BUG-1","ready")], ba=False)
    assert (ok, why) == (False, "BUG-1 ready")

def test_all_done_ba_blocks_on_open_questions():
    assert all_done([S("US1","done")], [], ba=True, open_questions=1)[0] is False
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** Update every caller of `next_from_hub` (cli, mcp, web `planui` if it unpacks the tuple — grep first).
- [ ] **Step 4: Run** — `pytest tests/test_planstatus.py tests/test_autorun_done.py tests/test_cli_mission.py tests/test_mcp.py -v` → PASS.
- [ ] **Step 5: Commit** — `feat: status for unparented tickets and bugs; all-done check`

### Task 3: Hub `/api/questions` route and runner Q&A client

**Files:**
- Modify: `src/strata_kb/web/api.py` (new `Route("/api/questions", ...)`, GET, params `repo`, `ticket`, `status` default `open`; same auth as the other `/api` routes)
- Create: `src/strata_kb/autorun/qa.py`
- Test: `tests/test_api_questions.py`, `tests/test_autorun_qa.py`

**Interfaces:**
- Produces: JSON `{"questions": [{"id", "repo", "ticket", "state", "question", "asked_by", "asked_at", "blocks", "answer", "answer_rev"}]}` from `ticketqa.list_questions`; 400 on bad `status`; 503 `"Q&A needs the shared hub server"` when `hub_serves_own_checkout` is false (mirror `mcp._qa`).
- Produces: `qa.QaClient(base_url: str, token: str, http=httpio.request)` with `list(status="open", repo="", ticket="") -> list[dict]` and `states(ids: list[int]) -> dict[int, str]` (one `status=all` call, filtered). `qa.from_env() -> QaClient` reads `STRATA_KB_HUB_URL` / `STRATA_KB_HTTP_TOKEN` (the vars `.mcp.json` already uses) and raises `KbError` naming the missing one.

- [ ] **Step 1: Write failing tests** — route returns the open question of a fixture ticket; bad status → 400; `QaClient.states([3])` → `{3: "answered"}` with a stub `http`; `from_env` without token → `KbError`.
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — `pytest tests/test_api_questions.py tests/test_autorun_qa.py -v` → PASS.
- [ ] **Step 5: Commit** — `feat: /api/questions JSON route and autorun Q&A client`

### Task 4: One task = one `claude -p` process

**Files:**
- Create: `src/strata_kb/autorun/claude.py`
- Test: `tests/test_autorun_claude.py`, fixture `tests/fake_claude.py` (a script the tests put on `PATH` as `claude`; it reads `FAKE_CLAUDE_REPLIES` — a JSON list file — and prints the next `{"type":"result","result":...}` envelope, or `{"is_error":true,"result":"..."}`)

**Interfaces:**
- Produces: `TaskResult(kind: Literal["done","blocked-qa","failed","usage-limit"], ids: tuple[int, ...] = (), reason: str = "")`.
- Produces: `parse_result(reply: str) -> TaskResult` (last non-empty line must start with `AUTO-RESULT: `; `blocked-qa` ids parsed from `Q12,Q13`).
- Produces: `run_task(root: Path, prompt: str, *, log_dir: Path, executable: str = "claude", timeout: int = 4 * 3600) -> TaskResult`: runs `[executable, "-p", "--output-format", "json", "--permission-mode", "acceptEdits"]` with `cwd=root`, prompt on stdin (reuse `llm._extract_reply` shape), writes `<log_dir>/<ts>-<slug>.log` (prompt, stdout, stderr, duration, exit). An error envelope or non-zero exit whose text matches `re.I` `limit` → `usage-limit` with the message as reason; any other error → `failed`.
- Produces: `prompt_for(skill: str, arg: str, kind: str) -> str`: `"/{skill} {arg}\n\nAuto mode is ON for this {kind} repo: ...end your reply with exactly one AUTO-RESULT: line ..."` (the exact wording is the builder's; it must name the three forms).

- [ ] **Step 1: Write failing tests**

```python
def test_parse_done(): assert parse_result("...\nAUTO-RESULT: done\n").kind == "done"
def test_parse_blocked_ids(): assert parse_result("AUTO-RESULT: blocked-qa Q12,Q13").ids == (12, 13)
def test_missing_line_is_failed(): assert parse_result("done!\n") == TaskResult("failed", (), "no result line")
def test_trailing_chatter_after_line_is_failed(): ...  # "AUTO-RESULT: done\nAlso note..." → failed
def test_run_task_fresh_process_and_log(fake_claude, tmp_path): ...  # log file written, kind done
def test_usage_limit_envelope(fake_claude): ...  # {"is_error":true,"result":"You've hit your usage limit"} → usage-limit
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement `claude.py` and the fake.**
- [ ] **Step 4: Run** — `pytest tests/test_autorun_claude.py -v` → PASS.
- [ ] **Step 5: Commit** — `feat: autorun task runner over claude -p`

### Task 5: Runner state in `.kb/auto/`

**Files:**
- Create: `src/strata_kb/autorun/state.py`
- Modify: `src/strata_kb/initcmd.py` (`_ensure_kb_doc_ignored(target, ".kb/auto/", report)` for `ba` and `dev`), `src/strata_kb/autorun/switch.py` (`status()` reads it)
- Test: `tests/test_autorun_state.py`, `tests/test_init.py`

**Interfaces:**
- Produces: `AutoState(task: str | None, attempts: int, waiting_on: tuple[int, ...], stop_reason: str | None, updated_at: str)`; `load(kb_dir) -> AutoState`, `save(kb_dir, state) -> None` (atomic write of `.kb/auto/state.json`), `log_dir(kb_dir) -> Path` (`.kb/auto/logs`, created).
- `task` is `"<skill>:<id>"`, e.g. `dev-implement-ticket:M-x-US3`.

- [ ] **Step 1: Write failing tests** — round-trip; missing file → empty state; `kb init --kind dev` adds `.kb/auto/` to `.gitignore` once.
- [ ] **Step 2: Run, verify FAIL.** **Step 3: Implement.** **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** — `feat: autorun state file`

### Task 6: Task picker (BA and Dev)

**Files:**
- Create: `src/strata_kb/autorun/picker.py`
- Test: `tests/test_autorun_picker.py`

**Interfaces:**
- Produces: `Task(skill: str, arg: str)`; `key` property = `f"{skill}:{arg}"`.
- Produces: `pick_ba(root: Path, kb_dir: Path, run=subprocess.run) -> Task | None`: runs `kb mission next --json` (cwd `root`), then, in order: a story with a mission-blocker reason (any reason not starting with `DoR ` and not `US ... not done`) → `Task("ba-mission-plan", f"--amend {mission_id}")`; a `draft` story → `Task("ba-ticket-author", f"--amend {us_id}")`; `next` (to-draft) → `Task("ba-ticket-author", us_id)`; else `None`.
- Produces: `pick_dev(hub: HubHandle, root: Path) -> Task | None`: when no file under `root/.github/workflows/` contains `kb-test` → `Task("dev-test-workflow", "")`; else first `ready` unparented bug (`BUG-` prefix) → `Task("dev-fix-bug", id)`; else first `ready` story in mission order → `Task("dev-implement-ticket", us_id)`; else `None`.

- [ ] **Step 1: Write failing tests** — one per rule above (BA blocker beats draft beats to-draft; Dev test-workflow beats bug beats story; nothing → None).
- [ ] **Step 2: Run, FAIL.** **Step 3: Implement.** **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** — `feat: autorun task picker for ba and dev repos`

### Task 7: The loop: `run_once`, `run_loop`, stop rules

**Files:**
- Create: `src/strata_kb/autorun/runner.py`
- Test: `tests/test_autorun_runner.py`

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: `preflight(root, kb_dir) -> list[str]` (refusal reasons: switch off; kind; empty `intake`; registry entry missing or not `auto_merge`).
- Produces: `run_once(root, kb_dir, *, cfg: KBConfig, hub: HubHandle, qa: QaClient, run_task=claude.run_task, now=time.time) -> Outcome` where `Outcome = Literal["ran", "idle", "waiting", "stopped", "done"]`.
- Produces: `run_loop(root, kb_dir, *, sleep=time.sleep, **deps) -> int` (exit 0 on `done`, 2 on `stopped`).

Rules `run_once` must follow, in order:
1. Reload config; `auto.enabled` false → `stopped` with `stop_reason="switched off"`.
2. `all_done(...)` true → `done`.
3. State `waiting_on` non-empty (Dev): `qa.states(ids)`; all `answered` → clear and re-run the same task; any `open`/`waiting` → `waiting` (sleep `qa_interval`).
4. Pick a task; `None` → `idle` (sleep `idle_interval`).
5. Run it. `done` → reset attempts, state task `None`. `blocked-qa` → store `waiting_on`. `usage-limit` → sleep backoff (900→1800→3600 s), attempts unchanged, retry. `failed ci-red ...` → `stopped` at once. Other `failed` → attempts += 1; `>= 2` → `stopped` with the reason, else retry.
6. `stopped` prints the task, PR/reason and "fix, then `kb auto run` to resume".

- [ ] **Step 1: Write failing tests** (fake `run_task` returning scripted results; fake `qa`)

```python
def test_switch_off_stops_at_task_boundary(...)  # task returns done, then config flipped → next run_once → stopped
def test_waiting_question_does_not_resume(...)   # states → {12: "waiting"} → Outcome "waiting"
def test_answered_question_reruns_same_task(...)
def test_second_failure_stops(...)               # failed, failed → stopped; attempts == 2
def test_ci_red_stops_immediately(...)
def test_usage_limit_backoff_sequence(...)       # sleeps 900, 1800, 3600, 3600
def test_all_done_exits_zero(...)
def test_preflight_refuses_without_auto_merge(...)
```

- [ ] **Step 2: Run, FAIL.** **Step 3: Implement.** **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** — `feat: autorun loop with stop and usage-limit rules`

### Task 8: BA Q&A thread in its own worktree

**Files:**
- Create: `src/strata_kb/autorun/qathread.py`
- Modify: `src/strata_kb/gitio.py` (`worktree_add(root, path, branch, start="main")`, `worktree_remove(root, path)`)
- Modify: `src/strata_kb/autorun/runner.py` (`run_loop` starts the thread for `ba`)
- Test: `tests/test_autorun_qathread.py`, `tests/test_gitio.py`

**Interfaces:**
- Produces: `QaThread(root, kb_dir, qa: QaClient, interval: int, run_task=claude.run_task, sleep=time.sleep)` with `start()`, `stop()`, `tick() -> bool` (one check; returns True when it launched a process). `tick`: `qa.list("open")` non-empty and no process running → ensure worktree `.kb/auto/worktrees/qa` on branch `auto/qa` (recreate from `main` each time) → `run_task(worktree, prompt_for("ba-answer-questions", "", "ba"), ...)` in a thread; while running, further ticks return False.
- Produces: `open_question_count(qa) -> int` for the BA stop check.

- [ ] **Step 1: Write failing tests** — `tick` launches with `cwd == worktree path`, not `root`; second `tick` while running returns False; no open questions → False; worktree branch is `auto/qa`.
- [ ] **Step 2: Run, FAIL.** **Step 3: Implement.** **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** — `feat: BA Q&A thread in a separate worktree`

### Task 9: `kb auto run` CLI

**Files:**
- Modify: `src/strata_kb/cli.py` (`auto_app` gains `run`: options `--once`, `--kb-dir`, `--hub` with envvar `STRATA_KB_HUB`; logging like `code_sync_run`)
- Test: `tests/test_cli_auto.py`

- [ ] **Step 1: Write failing tests** — `kb auto run` with switch off → exit 1 and the preflight reason; `--once` with fake runner → prints the outcome; exit 2 on `stopped`.
- [ ] **Step 2: Run, FAIL.** **Step 3: Implement.** **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** — `feat: kb auto run`

### Task 10: Permission allowlist scaffold

**Files:**
- Create: `src/strata_kb/templates/init/claude-settings-auto.json` (`permissions.allow`: `Bash(kb *)`, `Bash(git add *)`, `Bash(git commit *)`, `Bash(git checkout *)`, `Bash(git switch *)`, `Bash(git branch *)`, `Bash(git worktree *)`, `Bash(git merge *)`, `Bash(git fetch *)`, `Bash(git pull *)`, `Bash(git push origin HEAD*)`, `Bash(gh pr *)`, `Bash(gh run *)`, `Edit`, `Write`, `Read`, `mcp__strata-kb__*`; `permissions.deny`: `Bash(git push --force*)`, `Bash(git push * main)`, `Bash(git push origin main*)`, `Bash(gh repo delete *)`, `Bash(rm -rf /*)`, `Edit(.claude/settings.json)`; plus the usage hooks from `claude-settings-usage.json`)
- Modify: `src/strata_kb/initcmd.py`: for `ba`/`dev`, `.claude/settings.json` maps to the new template; when the file exists, **merge** (new function `merge_settings(existing: dict, template: dict) -> dict`: union of `permissions.allow`/`deny` lists, hooks added only when the same command is absent, every other existing key kept) instead of the protected-file skip
- Modify: `src/strata_kb/initcmd.py` also adds per-language test commands to `allow` from `cfg.langs` via a table `TEST_COMMANDS = {"python": "Bash(pytest *)", "ts": "Bash(npm test*)", ...}` (one entry per conventions language)
- Test: `tests/test_init_settings.py`

- [ ] **Step 1: Write failing tests** — fresh dev repo gets allow/deny; existing file with `permissions.allow: ["Bash(make *)"]` keeps it and gains the template entries; hooks not duplicated; `langs: [python]` adds `Bash(pytest *)`.
- [ ] **Step 2: Run, FAIL.** **Step 3: Implement.** **Step 4: Run** — `pytest tests/test_init_settings.py tests/test_init.py tests/test_templates.py -v` → PASS.
- [ ] **Step 5: Commit** — `feat: kb init scaffolds an auto-mode permission allowlist`

### Task 11: BA skill bodies — auto paths

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/ba-ticket-author.md`, `ba-mission-plan.md`, `ba-answer-questions.md`, `src/strata_kb/templates/init/claude-skill-kb-publish.md`
- Test: `tests/test_template_bodies.py`

Each body gains one `## Auto mode` section (same heading in every body) that opens with: *"Run `kb auto status --json`. When `enabled` is false, this section does not apply. When true: ..."* and then, per the spec §6.7 table, replaces exactly these gates: KB-ref pick, the BA-only DoR box, the amend trigger, D-row decide, open-question tick, "never answer yourself", never-commit/push (→ branch `auto/<ticket-id>`, PR, fix CI up to 2 rounds, `gh pr merge --admin` when green, else end `AUTO-RESULT: failed ci-red <pr-url>`), `/kb-publish` go/no-go. Every decision is written as an `**Auto decision:**` line (what was checked, options, choice, why) in the ticket's change log / mission change log. The section ends with the `AUTO-RESULT:` contract.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("name", ["ba-ticket-author", "ba-mission-plan", "ba-answer-questions"])
def test_ba_body_has_auto_mode_section(name): assert "## Auto mode" in body(name) and "AUTO-RESULT:" in body(name)
def test_ba_ticket_author_auto_ticks_dor_box(): ...  # "never — the BA's judgement" row references the Auto mode section
def test_off_path_unchanged(name): ...  # text before "## Auto mode" equals the committed body before this task (snapshot in tests/fixtures/bodies-pre-auto/)
```

- [ ] **Step 2: Run, FAIL.** **Step 3: Edit the bodies.** **Step 4: Run** — `pytest tests/test_template_bodies.py tests/test_templates.py -v` → PASS.
- [ ] **Step 5: Commit** — `feat: BA skills take the auto path when the switch is on`

### Task 12: Dev skill bodies — auto paths and `dev-test-workflow`

**Files:**
- Modify: bodies `dev-implement-ticket.md` (open blocking question → `AUTO-RESULT: blocked-qa Q<ids>`; stale/warn/blocked-deps decided by agent), `dev-design.md` (GATE 1), `dev-plan.md` (GATE 2; build/test commands read from repo), `dev-execute.md` (findings), `dev-handover.md` (GATE 3/4: open PR, fix CI ≤2 rounds, admin merge, then `kb publish`), `dev-fix-bug.md` (branch at once; hotfix base from `auto.hotfix_base` else `main`)
- Create: body `dev-test-workflow.md` + the three stubs (`claude-skill-dev-test-workflow.md`, `claude-command-dev-test-workflow.md`, `copilot-dev-test-workflow.prompt.md`, `cursor-dev-test-workflow.md`) and the `DEV_TEMPLATES` entries in `initcmd.py` — the skill writes `.github/workflows/kb-test.yml` from `detect_langs` and the conventions' test commands, runs it green, merges via the same PR path
- Test: `tests/test_template_bodies.py`, `tests/test_init.py` (expected files for `dev` include the new skill)

- [ ] **Step 1: Write failing tests** — every Dev body has `## Auto mode` and `AUTO-RESULT:`; `dev-handover` auto text names `gh pr merge --admin` and `kb publish`; `dev-implement-ticket` names `blocked-qa`; `dev-test-workflow` renders for `dev` and names `kb-test.yml`; off-path snapshot test as in Task 11.
- [ ] **Step 2: Run, FAIL.** **Step 3: Edit/create.** **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** — `feat: Dev skills take the auto path; dev-test-workflow skill`

### Task 13: Docs, changelog, version

**Files:**
- Modify: `README.md` (new section "Full-auto mode": switch, `kb auto`, what the agent decides, stop rules, security note on admin merge), `src/strata_kb/templates/init/QUICKSTART-ba.md`, `QUICKSTART-dev.md`, `CHANGELOG.md` (`## 1.29.0 — <date>`), `pyproject.toml` version `1.29.0`, `docs/src/` guides (BA, Dev: one subsection each; PDFs not rebuilt, say so in the changelog as 1.28.x did)
- Test: `tests/test_readme.py` (if it checks command lists, add `kb auto`)

- [ ] **Step 1: Write docs.** **Step 2: `pytest tests/test_readme.py tests/test_templates.py -q` → PASS.**
- [ ] **Step 3: Full suite** — `pytest -q -n auto` → PASS; `ruff check src tests && pyright` → clean.
- [ ] **Step 4: Commit** — `docs: full-auto mode; release 1.29.0`
