# `kb plan waves` and parallel task lanes — PR 3 (Dev side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `dev-plan` records a `Depends on:` line per task, `kb plan waves` computes file-disjoint dependency waves deterministically, and `dev-execute` runs a multi-task wave in git worktree lanes merged back per task.

**Architecture:** One pure engine module `planwaves.py` (text in, errors + waves out) and a thin `kb plan waves` CLI over it; the four `dev-plan` and four `dev-execute` wrappers gain the dependency rule, the fifth A2 question and the lane procedure, pinned by string tests; `QUICKSTART-dev.md`, README and CHANGELOG document it.

**Tech Stack:** Python 3.12, typer, pytest; Markdown wrappers under `src/strata_kb/templates/init/`.

**Spec:** `docs/superpowers/specs/2026-09-24-mission-next-greenfield-design.md` — §2 N5–N6, §5, §6, §7 PR 3. Independent of PR 1 (#68) and PR 2.

## Global Constraints

- Branch `dev/plan-waves`, cut from `main`; the PR targets `main`.
- No version bump in `pyproject.toml` / `uv.lock`; CHANGELOG under `## Unreleased` (create the section above `## 1.3.0 — 2026-09-24` if it is absent on `main`).
- `planwaves.py` has no filesystem, CLI or MCP imports.
- Task-heading contract, pinned in `dev-plan` text and the engine: `### Task <n>: <title>` (any heading level 2–4 starting with `Task <n>` is accepted by the parser); the line directly under it is `Depends on: none` or `Depends on: task 2, task 5`; paths live under the `**Files:**` heading as `- Create: \`path\``, `- Modify: \`path:lines\``, `- Test: \`path\``.
- Dev wrapper invariants the tests pin: the three SHARED-* blocks (`## Freshness re-check…`, `## Hard rules`, `## Next step…`) are byte-identical canon across 20 wrappers — never edit them; `copilot-<skill>.prompt.md` and `cursor-<skill>.md` differ only on frontmatter line 2; every dev wrapper ends with `  Flow order never hides a blocker.\n`; the `claude-command-` wrappers are compressed prose that still carries every needle.
- Lane cap is a fixed 3 (`ponytail:` constant in prose; raise once a measured run says so).
- Every test in the foreground (`uv run pytest … -q`); never `run_in_background`. The controller runs the full suite once at the end.
- Commit per task with explicit `git add <paths>` and `git commit -F <msgfile>`; never `git add -A` / `-a` / `.`.
- Before the final commit, run `mcp__gitnexus__detect_changes({scope: "all"})` and report it.

---

### Task 1: `planwaves` engine — parse tasks, check, waves

**Depends on:** none

**Files:**
- Create: `src/strata_kb/planwaves.py`
- Test: `tests/test_planwaves.py` (create)

**Interfaces:**
- Consumes: stdlib only.
- Produces (module `strata_kb.planwaves`):
  - `Task(number: int, depends_on: tuple[int, ...] | None, paths: tuple[str, ...])` — frozen dataclass; `depends_on is None` = no `Depends on:` line.
  - `parse_plan(text: str) -> list[Task]`.
  - `check(tasks: list[Task]) -> tuple[list[str], list[list[int]]]` — `(errors, waves)`; `waves` is empty when `errors` is non-empty. Error strings, exactly: `task 4 depends on task 9 — no such task`; `tasks 2 and 3 share src/x.py but neither depends on the other`; `dependency cycle: 2 → 5 → 2`; `task 3 has no Depends on: line`; `task 2 is defined twice`.
  - `render(waves: list[list[int]]) -> str` — `wave 1: task 1, task 2` lines.
  - `to_json(errors, waves) -> dict` — `{"errors": [...], "waves": [[1, 2], [3]]}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planwaves.py`:

```python
"""Engine tests for `kb plan waves` (`strata_kb.planwaves`). Text in, waves out."""

from __future__ import annotations

from strata_kb import planwaves

PLAN = """# ABC-12 plan
cmd.test: pytest -q
cmd.lint: ruff check src tests
status: approved

### Task 1: model
Depends on: none

**Files:**
- Create: `src/app/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Produces: `Model`

**Steps:**
- [ ] step

### Task 2: api
Depends on: task 1

**Files:**
- Create: `src/app/api.py`
- Modify: `src/app/__init__.py:1-3`
- Test: `tests/test_api.py`

**Steps:**
- [ ] step

### Task 3: docs
Depends on: none

**Files:**
- Modify: `README.md`

**Steps:**
- [ ] step

### Task 4: verify
Depends on: task 1, task 2, task 3

**Files:**
- Test: `tests/`

**Steps:**
- [ ] step
"""


def test_parse_plan_reads_numbers_dependencies_and_paths():
    tasks = planwaves.parse_plan(PLAN)
    assert [t.number for t in tasks] == [1, 2, 3, 4]
    assert tasks[0].depends_on == ()
    assert tasks[1].depends_on == (1,)
    assert tasks[3].depends_on == (1, 2, 3)
    assert tasks[1].paths == ("src/app/api.py", "src/app/__init__.py", "tests/test_api.py")
    assert tasks[0].paths == ("src/app/model.py", "tests/test_model.py")


def test_parse_plan_accepts_bold_and_bare_numbers_and_missing_line():
    text = "### Task 1: a\n**Depends on:** 2, 3\n\n### Task 2: b\n\n### Task 3: c\nDepends on: n/a\n"
    tasks = planwaves.parse_plan(text)
    assert tasks[0].depends_on == (2, 3)
    assert tasks[1].depends_on is None
    assert tasks[2].depends_on == ()


def test_check_waves_on_the_golden_plan():
    errors, waves = planwaves.check(planwaves.parse_plan(PLAN))
    assert errors == []
    assert waves == [[1, 3], [2], [4]]


def test_check_names_every_error():
    text = (
        "### Task 1: a\nDepends on: none\n**Files:**\n- Create: `x.py`\n\n"
        "### Task 2: b\nDepends on: task 9\n**Files:**\n- Modify: `x.py`\n\n"
        "### Task 3: c\n**Files:**\n- Create: `y.py`\n\n"
        "### Task 4: d\nDepends on: task 5\n\n### Task 5: e\nDepends on: task 4\n"
    )
    errors, waves = planwaves.check(planwaves.parse_plan(text))
    assert "task 2 depends on task 9 — no such task" in errors
    assert "tasks 1 and 2 share x.py but neither depends on the other" in errors
    assert "task 3 has no Depends on: line" in errors
    assert "dependency cycle: 4 → 5 → 4" in errors
    assert waves == []


def test_check_shared_path_is_fine_when_a_dependency_path_exists():
    text = (
        "### Task 1: a\nDepends on: none\n**Files:**\n- Create: `x.py`\n\n"
        "### Task 2: b\nDepends on: task 1\n**Files:**\n- Modify: `x.py`\n\n"
        "### Task 3: c\nDepends on: task 2\n**Files:**\n- Modify: `x.py`\n"
    )
    errors, waves = planwaves.check(planwaves.parse_plan(text))
    assert errors == []
    assert waves == [[1], [2], [3]]


def test_check_duplicate_task_number_and_self_dependency():
    text = "### Task 1: a\nDepends on: none\n\n### Task 1: b\nDepends on: task 1\n"
    errors, _ = planwaves.check(planwaves.parse_plan(text))
    assert "task 1 is defined twice" in errors


def test_render_and_json():
    waves = [[1, 3], [2], [4]]
    assert planwaves.render(waves) == "wave 1: task 1, task 3\nwave 2: task 2\nwave 3: task 4"
    assert planwaves.to_json([], waves) == {"errors": [], "waves": [[1, 3], [2], [4]]}
    assert planwaves.to_json(["e"], []) == {"errors": ["e"], "waves": []}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_planwaves.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'strata_kb.planwaves'`.

- [ ] **Step 3: Create `src/strata_kb/planwaves.py`**

```python
"""`kb plan waves` engine — dependency waves of a dev plan.

A `docs/impl/<ticket-id>-plan.md` written by `dev-plan` carries, per
`### Task <n>` heading, a `Depends on:` line and a `**Files:**` list (spec
2026-09-24-mission-next-greenfield-design §5). Two tasks with no dependency
path between them must be file-disjoint — that is what lets `dev-execute`
run a wave in parallel worktree lanes and merge them back without conflict.
This module checks that and computes the waves. Text in, errors and waves
out; no filesystem, CLI or MCP imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TASK_RE = re.compile(r"^#{2,4}\s+Task\s+(?P<n>\d+)\b")
DEPENDS_RE = re.compile(r"^\*{0,2}Depends on:?\*{0,2}\s*(?P<rest>.*?)\s*$", re.I)
SECTION_RE = re.compile(r"^\*\*(?P<name>Files|Interfaces|Steps):?\*\*:?\s*$")
FILE_LINE_RE = re.compile(r"^\s*-\s*(?:Create|Modify|Test|Delete)\s*:\s*(?P<rest>.+?)\s*$", re.I)
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")

_NONE_WORDS = frozenset({"", "none", "-", "n/a"})


@dataclass(frozen=True)
class Task:
    number: int
    depends_on: tuple[int, ...] | None   # None = no `Depends on:` line
    paths: tuple[str, ...]


def _path_of(rest: str) -> str | None:
    """The path on a `- Create: \\`src/x.py:10-20\\`` line: the first backtick
    span (else the first token), with a trailing `:<line>[-<line>]` dropped."""
    m = CODE_SPAN_RE.search(rest)
    token = m.group(1).strip() if m else (rest.split() or [""])[0]
    token = LINE_SUFFIX_RE.sub("", token).strip()
    return token or None


def _deps_of(rest: str) -> tuple[int, ...]:
    if rest.strip().lower() in _NONE_WORDS:
        return ()
    return tuple(dict.fromkeys(int(n) for n in re.findall(r"\d+", rest)))


def parse_plan(text: str) -> list[Task]:
    """Tasks in file order. A `Depends on:` line binds to the task heading
    above it; `**Files:**` lines are read until the next bold section or
    task heading."""
    tasks: list[Task] = []
    number: int | None = None
    depends: tuple[int, ...] | None = None
    paths: list[str] = []
    in_files = False

    def flush() -> None:
        if number is not None:
            tasks.append(Task(number, depends, tuple(dict.fromkeys(paths))))

    for raw in text.splitlines():
        line = raw.rstrip()
        m = TASK_RE.match(line)
        if m:
            flush()
            number, depends, paths, in_files = int(m.group("n")), None, [], False
            continue
        if number is None:
            continue
        m = DEPENDS_RE.match(line.strip())
        if m and depends is None:
            depends = _deps_of(m.group("rest"))
            continue
        m = SECTION_RE.match(line.strip())
        if m:
            in_files = m.group("name") == "Files"
            continue
        if in_files:
            m = FILE_LINE_RE.match(line)
            if m:
                path = _path_of(m.group("rest"))
                if path:
                    paths.append(path)
    flush()
    return tasks


def _reachable(start: int, deps: dict[int, tuple[int, ...]]) -> set[int]:
    """Every task `start` depends on, transitively."""
    seen: set[int] = set()
    stack = list(deps.get(start, ()))
    while stack:
        n = stack.pop()
        if n in seen or n not in deps:
            continue
        seen.add(n)
        stack.extend(deps[n])
    return seen


def _find_cycle(deps: dict[int, tuple[int, ...]]) -> list[int] | None:
    state: dict[int, int] = {}
    path: list[int] = []

    def visit(n: int) -> list[int] | None:
        state[n] = 1
        path.append(n)
        for d in deps.get(n, ()):
            if d not in deps:
                continue
            if state.get(d) == 1:
                return path[path.index(d):] + [d]
            if state.get(d) is None:
                found = visit(d)
                if found:
                    return found
        path.pop()
        state[n] = 2
        return None

    for n in deps:
        if state.get(n) is None:
            found = visit(n)
            if found:
                return found
    return None


def check(tasks: list[Task]) -> tuple[list[str], list[list[int]]]:
    """(errors, waves). Waves are empty whenever an error is reported —
    a plan with a cycle or an undeclared shared file has no safe order."""
    errors: list[str] = []
    seen: set[int] = set()
    for t in tasks:
        if t.number in seen:
            errors.append(f"task {t.number} is defined twice")
        seen.add(t.number)
    deps: dict[int, tuple[int, ...]] = {}
    for t in tasks:
        if t.depends_on is None:
            errors.append(f"task {t.number} has no Depends on: line")
            deps[t.number] = ()
            continue
        deps[t.number] = t.depends_on
        for d in t.depends_on:
            if d not in seen:
                errors.append(f"task {t.number} depends on task {d} — no such task")

    cycle = _find_cycle(deps)
    if cycle:
        errors.append("dependency cycle: " + " → ".join(str(n) for n in cycle))

    reach = {n: _reachable(n, deps) for n in deps} if not cycle else {}
    by_number = {t.number: t for t in tasks}
    numbers = sorted(by_number)
    if not cycle:
        for i, a in enumerate(numbers):
            for b in numbers[i + 1:]:
                shared = sorted(set(by_number[a].paths) & set(by_number[b].paths))
                if shared and b not in reach[a] and a not in reach[b]:
                    for p in shared:
                        errors.append(f"tasks {a} and {b} share {p} but neither depends on the other")

    if errors:
        return errors, []
    waves: list[list[int]] = []
    placed: set[int] = set()
    remaining = set(deps)
    while remaining:
        wave = sorted(n for n in remaining if all(d in placed for d in deps[n]))
        waves.append(wave)
        placed.update(wave)
        remaining -= set(wave)
    return [], waves


def render(waves: list[list[int]]) -> str:
    return "\n".join(
        f"wave {i}: " + ", ".join(f"task {n}" for n in wave)
        for i, wave in enumerate(waves, start=1)
    )


def to_json(errors: list[str], waves: list[list[int]]) -> dict:
    return {"errors": list(errors), "waves": [list(w) for w in waves]}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_planwaves.py -q && uv run ruff check src/strata_kb/planwaves.py tests/test_planwaves.py`
Expected: 7 PASS, ruff clean. (Duplicate task numbers make `by_number` keep the last definition; the duplicate error already fails the check, so no wave is computed — the test asserts only the message.)

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/planwaves.py tests/test_planwaves.py
git commit -F <scratchpad>/msg-pr3-task1.txt
```
Message: `feat: planwaves engine — Depends on lines, file-disjoint check, dependency waves`

---

### Task 2: CLI `kb plan waves`, README, CHANGELOG

**Depends on:** task 1

**Files:**
- Modify: `src/strata_kb/cli.py` (typer group after `pr_app`, ~line 76; a command after `pr_lint`)
- Modify: `README.md` (command overview table, after the `kb pr lint` row, ~line 275)
- Modify: `CHANGELOG.md` (`## Unreleased`)
- Test: `tests/test_cli_planwaves.py` (create)

**Interfaces:**
- Consumes: `planwaves.parse_plan`, `check`, `render`, `to_json`.
- Produces: `kb plan waves <plan-file|-> [--json]` — exit 0 with the waves, exit 1 with one `error: …` line per finding (text mode) or `{"errors": [...], "waves": []}` (`--json`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_planwaves.py`:

```python
"""CLI tests for `kb plan waves`."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from strata_kb.cli import app
from tests.test_planwaves import PLAN

runner = CliRunner()


def test_plan_waves_prints_waves_and_exits_0(tmp_path):
    path = tmp_path / "ABC-12-plan.md"
    path.write_text(PLAN, encoding="utf-8")
    result = runner.invoke(app, ["plan", "waves", str(path)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "wave 1: task 1, task 3\nwave 2: task 2\nwave 3: task 4"


def test_plan_waves_json(tmp_path):
    path = tmp_path / "ABC-12-plan.md"
    path.write_text(PLAN, encoding="utf-8")
    result = runner.invoke(app, ["plan", "waves", str(path), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"errors": [], "waves": [[1, 3], [2], [4]]}


def test_plan_waves_errors_exit_1(tmp_path):
    path = tmp_path / "ABC-12-plan.md"
    path.write_text("### Task 1: a\n**Files:**\n- Create: `x.py`\n", encoding="utf-8")
    result = runner.invoke(app, ["plan", "waves", str(path)])
    assert result.exit_code == 1
    assert "error: task 1 has no Depends on: line" in result.output
    assert "wave" not in result.output


def test_plan_waves_reads_stdin():
    result = runner.invoke(app, ["plan", "waves", "-"], input=PLAN)
    assert result.exit_code == 0, result.output
    assert result.output.startswith("wave 1: task 1, task 3")


def test_plan_waves_non_utf8_is_a_red_line(tmp_path):
    path = tmp_path / "p.md"
    path.write_bytes(b"\xff\xfe# bad")
    result = runner.invoke(app, ["plan", "waves", str(path)])
    assert result.exit_code == 1
    assert "not valid UTF-8" in result.output


def test_docs_name_the_plan_waves_command():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "| `kb plan waves` | Dependency waves of a dev plan: which tasks can run in parallel lanes; errors on a shared file without a dependency, a cycle, or a missing `Depends on:` line |" in readme
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.index("## Unreleased") < changelog.index("## 1.3.0")
    assert "`kb plan waves`" in changelog
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli_planwaves.py -q`
Expected: FAIL — typer `No such command 'plan'` (exit 2) and the docs assertion.

- [ ] **Step 3: Add the typer group and command to `cli.py`**

After the `pr_app` block (line 76) add:

```python
plan_app = typer.Typer(help="Dev plan tools: dependency waves of docs/impl/<ticket-id>-plan.md.")
app.add_typer(plan_app, name="plan")
```

After `pr_lint` add:

```python
@plan_app.command("waves")
def plan_waves(
    source: str = typer.Argument(..., help="Plan file (or '-' to read from stdin)"),
    json_output: bool = typer.Option(
        False, "--json", help="Emit {\"errors\": [...], \"waves\": [[...]]} instead of text"
    ),
) -> None:
    """Dependency waves of a dev plan: wave n = tasks whose every `Depends on:`
    task sits in an earlier wave. Exit 1 on a shared file without a
    dependency path, a cycle, an unknown task, or a missing `Depends on:`
    line — those plans have no safe parallel order."""
    from strata_kb import planwaves

    if source == "-":
        text = sys.stdin.read()
    else:
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            typer.secho(f"file '{source}' is not valid UTF-8: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)

    errors, waves = planwaves.check(planwaves.parse_plan(text))
    if json_output:
        typer.echo(json.dumps(planwaves.to_json(errors, waves)))
    else:
        for e in errors:
            typer.echo(f"error: {e}")
        if not errors:
            typer.echo(planwaves.render(waves))
    if errors:
        raise typer.Exit(1)
```

- [ ] **Step 4: README and CHANGELOG**

README, command overview table, after the `| \`kb pr lint\` | … |` row insert:

```markdown
| `kb plan waves` | Dependency waves of a dev plan: which tasks can run in parallel lanes; errors on a shared file without a dependency, a cycle, or a missing `Depends on:` line |
```

CHANGELOG, under `## Unreleased` (create the heading above `## 1.3.0 — 2026-09-24` if `main` does not have it yet), add:

```markdown
- `kb plan waves <plan-file>`: the dependency waves of a `docs/impl/<ticket-id>-plan.md` — wave n holds the tasks whose every `Depends on:` task sits in an earlier wave — and an exit-1 error for a file shared by two tasks with no dependency path, a cycle, an unknown task, or a task with no `Depends on:` line. Deterministic; `dev-execute` runs it before parallelising.
```

- [ ] **Step 5: Run the tests, lint**

Run: `uv run pytest tests/test_cli_planwaves.py tests/test_planwaves.py -q && uv run ruff check src tests`
Expected: all PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/cli.py README.md CHANGELOG.md tests/test_cli_planwaves.py
git commit -F <scratchpad>/msg-pr3-task2.txt
```
Message: `feat: kb plan waves — dependency waves of a dev plan`

---

### Task 3: `dev-plan` wrappers — `Depends on:` per task, fifth A2 question

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-dev-plan.md` (**Write the plan** bullet ~line 39-50; A2 question list ~line 99-105), identically the body of `copilot-dev-plan.prompt.md` and `cursor-dev-plan.md`; `claude-command-dev-plan.md` (prose ~line 41-47 and its A2 list ~line 92-98)
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: the contract from Global Constraints (`### Task <n>: <title>`, `Depends on:` line).
- Produces: the strings `Depends on: none`, `kb plan waves`, `file-disjoint` in all four wrappers' bodies.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
# --- plan waves (spec 2026-09-24 §5): dev-plan and dev-execute -------------


def test_dev_plan_records_a_depends_on_line_per_task():
    for name in _dev_wrapper_names("dev-plan"):
        body = _dev_wrapper_body(name)
        assert "### Task <n>: <title>" in body, name
        assert "`Depends on: none` or `Depends on: task 2, task 5`" in body, name
        assert "derived, never chosen" in body, name
        assert "file-disjoint" in body, name
        assert "The closing verification task depends on every other task" in body, name
        assert "kb plan waves docs/impl/<ticket-id>-plan.md" in body, name


def test_dev_plan_a2_asks_the_fifth_question_and_runs_plan_waves():
    for name in _dev_wrapper_names("dev-plan"):
        body = _dev_wrapper_body(name)
        assert "Is every `Depends on:` line consistent with Files and Interfaces" in body, name
        assert "The reviewer also runs `kb plan waves` and quotes its output; an error there is a BLOCKER on its own" in body, name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "depends_on_line_per_task or fifth_question"`
Expected: 2 FAIL.

- [ ] **Step 3: Edit `claude-skill-dev-plan.md`, then copy the body to copilot/cursor**

In the **Write the plan** bullet, after `step 1 always being the failing test.` insert:

```
  Every task heading is `### Task <n>: <title>`, and the line directly
  under it is `Depends on: none` or `Depends on: task 2, task 5` —
  derived, never chosen: task B depends on task A when B consumes an
  Interface A produces, **or** B and A share a path under **Files**. Two
  tasks with no dependency path are therefore file-disjoint, which is
  what lets `dev-execute` run them in parallel lanes. The closing
  verification task depends on every other task. Run
  `kb plan waves docs/impl/<ticket-id>-plan.md` before offering GATE 2:
  it prints the waves and fails on a shared path without a dependency,
  a cycle, an unknown task, or a missing line.
```

In the A2 list, after the bullet ending `name its verification?` add:

```
- Is every `Depends on:` line consistent with Files and Interfaces — no
  two tasks without a dependency path share a path, every consumed
  interface names its producer, no cycle? A miss is a BLOCKER. The
  reviewer also runs `kb plan waves` and quotes its output; an error
  there is a BLOCKER on its own.
```

Change `It answers four questions and nothing else:` to `It answers five questions and nothing else:`.

The three full wrappers are byte-identical from `## Freshness re-check` to end of file (verified 2026-09-25): copy the skill's slice from that heading to EOF over `copilot-dev-plan.prompt.md` and `cursor-dev-plan.md`, keeping each file's own text above it.

- [ ] **Step 4: Edit `claude-command-dev-plan.md`**

In the prose paragraph, after `and **Steps** as \`- [ ]\` checkboxes, step 1 always being the failing test.` insert: ` Every task heading is \`### Task <n>: <title>\`, and the line directly under it is \`Depends on: none\` or \`Depends on: task 2, task 5\` — derived, never chosen: task B depends on task A when B consumes an Interface A produces, or B and A share a path under Files, so two tasks with no dependency path are file-disjoint and \`dev-execute\` can run them in parallel lanes. The closing verification task depends on every other task, and \`kb plan waves docs/impl/<ticket-id>-plan.md\` runs before GATE 2 is offered — it prints the waves and fails on a shared path without a dependency, a cycle, an unknown task, or a missing line.`

In its A2 section, apply the same fifth bullet and the four→five change as in step 3.

- [ ] **Step 5: Run the dev wrapper suites**

Run: `uv run pytest tests/test_templates.py -q -k "dev_plan or shared or copilot_and_cursor or next_step or every_landed"`
Expected: all PASS — including the SHARED-* byte-identity test, the copilot/cursor line-2 test and the end-of-file test.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/templates/init/claude-skill-dev-plan.md src/strata_kb/templates/init/claude-command-dev-plan.md src/strata_kb/templates/init/copilot-dev-plan.prompt.md src/strata_kb/templates/init/cursor-dev-plan.md tests/test_templates.py
git commit -F <scratchpad>/msg-pr3-task3.txt
```
Message: `docs(skills): dev-plan records Depends on per task; A2 checks it and runs kb plan waves`

---

### Task 4: `dev-execute` wrappers — waves and lanes

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-dev-execute.md` (after the **Isolate** bullet, ~line 45; the **Resumable** bullet, ~line 111), identically the bodies of `copilot-dev-execute.prompt.md` and `cursor-dev-execute.md`; `claude-command-dev-execute.md` (prose ~line 37-39 and ~83-87)
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: `kb plan waves` from Task 2 (text only).
- Produces: the lane procedure strings in all four wrappers' bodies.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
def test_dev_execute_runs_plan_waves_and_lanes():
    for name in _dev_wrapper_names("dev-execute"):
        body = _dev_wrapper_body(name)
        assert "run `kb plan waves docs/impl/<ticket-id>-plan.md`" in body, name
        assert "an error returns the plan to `dev-plan`" in body, name
        assert "runs sequentially as today" in body, name
        assert "git worktree add .worktrees/<ticket-id>-task-<n> -b <ticket-id>-task-<n> HEAD" in body, name
        assert "git merge-base --is-ancestor" in body, name
        assert "at most **3 lanes at a time**" in body, name
        assert "Never use `run_in_background`; run every test in the foreground and let the call block." in body, name
        assert "git merge --no-ff <ticket-id>-task-<n>" in body, name
        assert "a conflict is a plan defect" in body, name
        assert "git diff <merge-base>..<lane-branch>" in body, name
        assert "the first wave with an unticked task" in body, name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_templates.py -q -k plan_waves_and_lanes`
Expected: FAIL.

- [ ] **Step 3: Edit `claude-skill-dev-execute.md`, then copilot/cursor**

After the **Isolate** bullet (after `**Never work directly on the default branch.**`) insert a new bullet:

```
- **Waves** — run `kb plan waves docs/impl/<ticket-id>-plan.md`; an
  error returns the plan to `dev-plan` (the same route an incomplete
  task block takes). A plan whose tasks carry no `Depends on:` lines
  runs sequentially as today — say so in the Next-step block. A wave of
  one task runs the per-task flow below unchanged. A wave of two or more
  tasks, when the runtime can dispatch subagents, runs each task in its
  own **lane**:
  - `git worktree add .worktrees/<ticket-id>-task-<n> -b <ticket-id>-task-<n> HEAD`
    from the ticket branch. A worktree the runtime provides is
    acceptable only if its base contains the ticket branch's HEAD —
    check with `git merge-base --is-ancestor`; otherwise create the lane
    by hand.
  - Dispatch one implementer per lane, at most **3 lanes at a time** —
    a larger wave runs in batches of 3 (`ponytail:` fixed cap; raise it
    once a measured wave shows the machine and the suite can take
    more). The implementer gets the same three things as below plus its
    lane path and this sentence: "Never use `run_in_background`; run
    every test in the foreground and let the call block." Scoped tests
    inside the lane; the implementer commits on its lane branch and
    writes `docs/impl/<ticket-id>-review/task-<n>-report.md` inside the
    lane.
  - Merge back in task-number order: `git merge --no-ff
    <ticket-id>-task-<n>` into the ticket branch; copy the report out
    of the lane if it did not land in the merge. A conflict is a plan
    defect: stop, do not resolve, return to `dev-plan` naming the two
    tasks.
  - Verify the wave: run `cmd.test` and `cmd.lint` once after the last
    merge of the wave and show the output.
  - A3 per task as below, with the diff written from
    `git diff <merge-base>..<lane-branch>`; tick only after A3 is clean,
    then `git worktree remove` the lane and delete its branch.
  Without subagents: sequential in wave order, today's fallback.
```

In the **Resumable** bullet, change `and continues at the first unticked task.` to `and continues at the first unticked task — that is, the first wave with an unticked task; ticked siblings are skipped, and the remaining tasks of that wave run under the same rules.` (the substring `first unticked task` is pinned by `test_dev_execute_is_resumable` and must survive).

The three full wrappers are byte-identical from `## Freshness re-check` to end of file (verified 2026-09-25): copy the skill's slice from that heading to EOF over `copilot-dev-execute.prompt.md` and `cursor-dev-execute.md`, keeping each file's own text above it.

- [ ] **Step 4: Edit `claude-command-dev-execute.md`**

After `Never work directly on the default branch.` insert: ` Then run \`kb plan waves docs/impl/<ticket-id>-plan.md\`; an error returns the plan to \`dev-plan\`, a plan without \`Depends on:\` lines runs sequentially as today, a wave of one task runs the per-task flow unchanged, and a wave of two or more tasks — when the runtime can dispatch subagents — runs each task in its own lane: \`git worktree add .worktrees/<ticket-id>-task-<n> -b <ticket-id>-task-<n> HEAD\` from the ticket branch (a runtime-provided worktree only if its base contains the ticket branch's HEAD, checked with \`git merge-base --is-ancestor\`), at most **3 lanes at a time**, each implementer handed its lane path and the sentence "Never use \`run_in_background\`; run every test in the foreground and let the call block.", scoped tests inside the lane, lanes merged back in task-number order with \`git merge --no-ff <ticket-id>-task-<n>\` — a conflict is a plan defect, returned to \`dev-plan\` naming the two tasks — the full \`cmd.test\` / \`cmd.lint\` run once after the wave, A3 per task from \`git diff <merge-base>..<lane-branch>\`, the lane removed after A3 is clean.`

Change `continues at the first unticked task.` to `continues at the first unticked task — that is, the first wave with an unticked task, ticked siblings skipped.`

- [ ] **Step 5: Run the dev wrapper suites**

Run: `uv run pytest tests/test_templates.py -q -k "dev_execute or shared or copilot_and_cursor or next_step"`
Expected: all PASS — including `test_dev_execute_is_resumable` (the `first unticked task` substring survives), the SHARED-* byte-identity test, the copilot/cursor line-2 test and the end-of-file test.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/templates/init/claude-skill-dev-execute.md src/strata_kb/templates/init/claude-command-dev-execute.md src/strata_kb/templates/init/copilot-dev-execute.prompt.md src/strata_kb/templates/init/cursor-dev-execute.md tests/test_templates.py
git commit -F <scratchpad>/msg-pr3-task4.txt
```
Message: `docs(skills): dev-execute runs kb plan waves and executes a wave in worktree lanes`

---

### Task 5: QUICKSTART-dev, full suite, graph check

**Depends on:** task 2, task 3, task 4

**Files:**
- Modify: `src/strata_kb/templates/init/QUICKSTART-dev.md` (after the `## Where work lives` paragraph ending `so the context cache never lands in a PR).`, ~line 160; CLI reference after the `kb svc note` bullet, ~line 465)
- Modify: `CHANGELOG.md` (extend the Task 2 bullet)
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_quickstart_dev_documents_plan_waves_and_lanes():
    text = _normalised(_read_init_template("QUICKSTART-dev.md"))
    assert "### Waves and lanes" in text
    assert "`Depends on:` line" in text
    assert "`kb plan waves docs/impl/<ticket-id>-plan.md`" in text
    assert "at most 3 lanes at a time" in text
    assert "- `kb plan waves <plan-file> [--json]`" in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_templates.py -q -k quickstart_dev_documents_plan_waves`
Expected: FAIL.

- [ ] **Step 3: QUICKSTART-dev.md**

After the paragraph ending `(so the context cache never lands in a PR).` insert:

```markdown

### Waves and lanes

Every task in `docs/impl/<ticket-id>-plan.md` carries a `Depends on:` line
under its `### Task <n>:` heading — `none`, or the tasks whose Interfaces it
consumes or whose files it shares. `dev-plan` derives it; the A2 reviewer
checks it. `kb plan waves docs/impl/<ticket-id>-plan.md` turns those lines
into waves (wave n = tasks whose dependencies all sit in earlier waves) and
fails when two tasks share a file without a dependency between them, when
there is a cycle, or when a line is missing — a plan like that has no safe
parallel order. `dev-execute` runs it after isolating the branch: a wave of
one task runs as before; a wave of several runs each task in its own git
worktree lane cut from the ticket branch, at most 3 lanes at a time, merged
back in task order with `--no-ff`, the full suite run once per wave. A merge
conflict means the plan was wrong and goes back to `dev-plan`.
```

In `## CLI reference`, after the `kb svc note …` bullet insert:

```markdown
- `kb plan waves <plan-file> [--json]` — dependency waves of a dev plan;
  exit 1 on a shared file without a dependency, a cycle, or a missing
  `Depends on:` line
```

- [ ] **Step 4: CHANGELOG**

Extend the Task 2 bullet with: ` Dev repos: \`dev-plan\` writes a \`Depends on:\` line per task (derived from Interfaces and shared files) and its A2 review asks a fifth question and runs \`kb plan waves\`; \`dev-execute\` runs a wave of independent tasks in git worktree lanes (at most 3 at a time, merged back with \`--no-ff\`, a conflict returned to \`dev-plan\`). \`QUICKSTART-dev.md\` gains *Waves and lanes*. Re-run \`kb init --kind dev\` to pick up the new text.`

- [ ] **Step 5: Doc tests, then the full suite and lint in the foreground**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -q`
Expected: PASS.

Run: `uv run pytest -q` (about 20 minutes; Bash `timeout: 1500000`; let it block) and `uv run ruff check src tests`
Expected: all PASS, ruff clean.

- [ ] **Step 6: Graph change analysis, then commit**

Call `mcp__gitnexus__detect_changes({scope: "all"})`; re-run on `partial` / `truncated`; paste the summary in the report.

```bash
git add src/strata_kb/templates/init/QUICKSTART-dev.md CHANGELOG.md tests/test_templates.py
git commit -F <scratchpad>/msg-pr3-task5.txt
```
Message: `docs: waves and lanes in QUICKSTART-dev and the CHANGELOG`

---

## Self-review

- **Spec coverage (§5):** 5.1 `dev-plan` `Depends on:` + derivation rule + fifth A2 question + `kb plan waves` in A2 — Task 3; 5.2 engine errors, output, `--json`, wave rule — Tasks 1–2; 5.3 `dev-execute` waves, lanes, cap 3, foreground sentence, merge back, conflict route, A3 diff, resume, fallback — Task 4; 5.4 docs — Tasks 2 (README) and 5 (QUICKSTART, CHANGELOG). Deviation from spec §5.2: the closing-verification annotation on the last wave is not printed (YAGNI); JSON carries an `errors` key alongside `waves`.
- **Placeholders:** none.
- **Invariants:** Tasks 3–4 stay outside the SHARED-* blocks, keep copilot == cursor except line 2, and keep the `first unticked task` substring that `test_dev_execute_is_resumable` pins.
- **Type consistency:** `parse_plan -> list[Task]`, `check -> tuple[list[str], list[list[int]]]`, `render(waves) -> str`, `to_json(errors, waves) -> dict` used identically in Tasks 1 and 2; `_dev_wrapper_names`, `_dev_wrapper_body`, `_normalised`, `_read_init_template` exist in `tests/test_templates.py`.
