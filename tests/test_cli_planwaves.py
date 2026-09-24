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


def test_plan_waves_no_tasks_is_an_error(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("no tasks here", encoding="utf-8")
    result = runner.invoke(app, ["plan", "waves", str(path)])
    assert result.exit_code == 1
    assert "error: no `### Task <n>` headings found" in result.output


def test_docs_name_the_plan_waves_command():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "| `kb plan waves` | Dependency waves of a dev plan: which tasks can run in parallel lanes; errors on a shared file without a dependency, a cycle, or a missing `Depends on:` line |" in readme
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.index("## Unreleased") < changelog.index("## 1.3.0")
    assert "`kb plan waves`" in changelog
