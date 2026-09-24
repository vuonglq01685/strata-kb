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

```text
### Task 9: phantom
Depends on: task 1

**Files:**
- Create: `ghost.py`
```

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
    text = (
        "### Task 1: a\nDepends on: none\n\n"
        "### Task 1: b\nDepends on: task 1\n\n"
        "### Task 1: c\nDepends on: task 1\n"
    )
    errors, _ = planwaves.check(planwaves.parse_plan(text))
    assert errors.count("task 1 is defined twice") == 1
    assert "dependency cycle: 1 → 1" in errors


def test_check_legacy_plan_reports_only_missing_depends_lines():
    text = (
        "### Task 1: a\n**Files:**\n- Modify: `CHANGELOG.md`\n\n"
        "### Task 2: b\n**Files:**\n- Modify: `CHANGELOG.md`\n"
    )
    errors, waves = planwaves.check(planwaves.parse_plan(text))
    assert errors == [
        "task 1 has no Depends on: line",
        "task 2 has no Depends on: line",
    ]
    assert waves == []


def test_check_mixed_plan_still_runs_shared_path_check():
    text = (
        "### Task 1: a\nDepends on: none\n**Files:**\n- Create: `x.py`\n\n"
        "### Task 2: b\n**Files:**\n- Modify: `x.py`\n"
    )
    errors, waves = planwaves.check(planwaves.parse_plan(text))
    assert "task 2 has no Depends on: line" in errors
    assert "tasks 1 and 2 share x.py but neither depends on the other" in errors
    assert waves == []


def test_check_empty_plan_is_an_error():
    errors, waves = planwaves.check(planwaves.parse_plan("no tasks here"))
    assert errors == ["no `### Task <n>` headings found"]
    assert waves == []


def test_parse_plan_strips_leading_bom():
    # A file starting directly with a task heading (no title line first) is
    # where a leading BOM actually breaks TASK_RE's `^#{2,4}` anchor -- the
    # golden PLAN's own first line is a title, not a heading, so it can't
    # exercise this.
    text = (
        "### Task 1: a\nDepends on: none\n**Files:**\n- Create: `x.py`\n\n"
        "### Task 2: b\nDepends on: task 1\n**Files:**\n- Create: `y.py`\n"
    )
    tasks = planwaves.parse_plan("﻿" + text)
    assert [t.number for t in tasks] == [1, 2]


def test_path_of_strips_leading_dot_slash():
    text = (
        "### Task 1: a\nDepends on: none\n**Files:**\n- Create: `./x.py`\n\n"
        "### Task 2: b\nDepends on: none\n**Files:**\n- Modify: `x.py`\n"
    )
    errors, waves = planwaves.check(planwaves.parse_plan(text))
    assert "tasks 1 and 2 share x.py but neither depends on the other" in errors
    assert waves == []


def test_check_treats_an_unparseable_depends_line_as_missing():
    text = "### Task 1: a\nDepends on: TBD\n**Files:**\n- Create: `x.py`\n"
    errors, waves = planwaves.check(planwaves.parse_plan(text))
    assert "task 1 has no Depends on: line" in errors
    assert waves == []


def test_check_reports_a_task_with_no_paths_under_files():
    # `#### Files` (a heading, not `**Files:**` bold text) never sets
    # `in_files`, so a task written this way parses with zero paths --
    # exactly the kind of format drift the gate must not wave through.
    text = "### Task 1: a\nDepends on: none\n\n#### Files\n- Create: `x.py`\n"
    errors, waves = planwaves.check(planwaves.parse_plan(text))
    assert "task 1 lists no paths under **Files**" in errors
    assert waves == []


def test_check_reports_an_unclosed_code_fence():
    text = (
        "### Task 1: a\nDepends on: none\n**Files:**\n- Create: `x.py`\n\n"
        "```text\nnever closed\n"
    )
    tasks = planwaves.parse_plan(text)
    errors, waves = planwaves.check(tasks, unclosed=planwaves.unclosed_fence(text))
    assert "unclosed code fence" in errors
    assert waves == []


def test_render_and_json():
    waves = [[1, 3], [2], [4]]
    assert planwaves.render(waves) == "wave 1: task 1, task 3\nwave 2: task 2\nwave 3: task 4"
    assert planwaves.to_json([], waves) == {"errors": [], "waves": [[1, 3], [2], [4]]}
    assert planwaves.to_json(["e"], []) == {"errors": ["e"], "waves": []}
