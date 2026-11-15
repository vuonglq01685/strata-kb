# Tester Loop Block 2 (`kb test next`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Tester (and block 3's auto picker) asks `kb test next` which story to test next, in the strategy's order; `/tester-test-story` with no argument proposes it.

**Architecture:** One function `strategyhub.next_stories` over the existing `plan_view` + `teststrategy.order`; a CLI command beside `kb test stale` reusing its file/hub handling; a skill-body section; CHANGELOG bullet in the open 1.37.3 entry.

**Tech Stack:** Python 3.12, typer, pytest.

**Spec:** `docs/superpowers/specs/2026-11-15-tester-loop-test-next-design.md` (base: `2026-11-15-test-strategy-design.md` D3/D8, `2026-11-14-tester-role-design.md` D3).

## Global Constraints

- Version stays 1.37.3 (no bump); add CHANGELOG bullets to the existing `## 1.37.3` entry.
- Order rules and the testable rule are reused unchanged (`teststrategy.order`, `strategyhub.testable` via `plan_view`).
- Exit codes: 0 a story printed; 3 nothing testable; 1 hub/read error.
- No strategy file, or `> Plan: —`: plan order over every plan (`plan_view(..., all_plans=True)`) and one stderr warning line.
- Tests run with `GIT_CONFIG_GLOBAL=<scratchpad>/test-gitconfig`.

## Review Focus

1. Strategy file unreadable (bad UTF-8) → treated like no strategy, with the warning; never a traceback (Task 1).
2. A story both testable and `testing` (held by another Tester) → not listed (Task 1; `testable` already excludes it — pin it).
3. `--json` with nothing testable → `[]` and exit 3, not an empty line (Task 1).

---

### Task 1: `strategyhub.next_stories` and `kb test next`

**Files:**
- Modify: `src/strata_kb/strategyhub.py`, `src/strata_kb/cli.py` (`test_app` command `next`, beside `test_stale`)
- Test: `tests/test_strategyhub.py` (or a new `tests/test_test_next.py`)

**Interfaces:**
- Produces:
  - `strategyhub.next_stories(hub: HubHandle, strategy: Strategy | None) -> list[Placement]` — `plan = plan_view(hub, strategy.plan)` when the strategy names a plan, else `plan_view(hub, None, all_plans=True)`; returns `teststrategy.order(strategy, [s for s in plan.stories if s.us_id in plan.testable])` (strategy None → plan order).
  - CLI `kb test next [--file docs/test-strategy.md] [--kb-dir .kb] [--hub HUB(envvar STRATA_KB_HUB)] [--json] [--all]`. Text: one line per story `"<story>  tier=<n> rank=<n|last|-> how=<id|mission|area|outside> row=<target|->"`; default only the first, `--all` every one. JSON: list of `{"story", "tier", "rank", "how", "target"}` (`rank` null for none, `"last"` for last; `target` null without row); default a one-element list, `--all` all.
  - Strategy read like `test_stale`: missing or unreadable (`OSError`, `UnicodeDecodeError`) → `None` + stderr warning `kb test next: no usable <file>, plan order` (wording yours); `> Plan: —` → plan order over every plan with stderr warning `kb test next: strategy names no plan, plan order over every plan`.
  - Exit 3 (`typer.Exit(3)`) when the list is empty, after printing `[]` for `--json` or `kb test next: nothing testable` for text.

- [ ] **Step 1: Failing tests** (fixtures: `plan_hub`, `STRATEGY_FOR_PLAN_HUB` in tests/test_strategyhub.py; `publish_tests`/`_text` in tests/test_testflow.py)

```python
def test_next_stories_testable_only_in_order(plan_hub):        # US1 done (testable), US2 ready → [US1]
def test_next_stories_without_strategy_is_plan_order(plan_hub)
def test_next_stories_skips_testing_story(plan_hub)             # held tester claim (testing) → excluded
def test_cli_test_next_first_and_all(plan_hub, tmp_path, monkeypatch)   # text first line names US1; --all lists all; exit 0
def test_cli_test_next_json_shape(plan_hub, tmp_path, monkeypatch)      # keys story/tier/rank/how/target
def test_cli_test_next_nothing_testable_exits_3(plan_hub, tmp_path, monkeypatch)  # PASS report closes US1 → --json "[]" exit 3
def test_cli_test_next_unreadable_strategy_warns(plan_hub, tmp_path, monkeypatch) # bad UTF-8 → warning on stderr, exit 0
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** the file + tests/test_strategyhub.py + tests/test_readme.py (top-level command table lists `kb test` already; add a `kb test next` README row if the table lists subcommands) — PASS. **Step 5: Commit** `feat: kb test next`.

---

### Task 2: `/tester-test-story` with no argument, auto allowlist, CHANGELOG

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/tester-test-story.md`, `src/strata_kb/templates/init/claude-command-tester-test-story.md` / `copilot-*` / `cursor-*` argument hints if they say the story is required, `src/strata_kb/initcmd.py` (`TESTER_ALLOW` gains `Bash(kb test next*)`), `CHANGELOG.md` (1.37.3 entry), `README.md` if Task 1 did not add the row
- Test: `tests/test_tester_skills.py`, `tests/test_init_settings.py`

**Interfaces:**
- Consumes: Task 1 CLI.
- Produces (body text, asserted): a short section before Step 1: "No story given: run `kb test next --json`; exit 3 → say nothing is testable and stop; otherwise propose the first story with its `how`/`rank` and ask the Tester to confirm or name another; a confirmed story continues at Step 1." The strategy never blocks testing (keep that rule).

- [ ] **Step 1: Failing tests:** body contains `kb test next --json` and `exit 3`; `TESTER_ALLOW` contains `Bash(kb test next*)`; CHANGELOG 1.37.3 entry mentions `kb test next`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Write.** **Step 4: Run** `tests/test_tester_skills.py tests/test_init_settings.py tests/test_init_tester.py tests/test_readme.py`, then the full suite once (19 baseline env failures only) — PASS. **Step 5: Commit** `feat: /tester-test-story proposes the next story`.
