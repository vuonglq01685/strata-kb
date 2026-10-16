from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from strata_kb import planstatus
from strata_kb.autorun.picker import Task, pick_ba, pick_dev
from strata_kb.errors import KbError
from strata_kb.missionnext import StoryStatus


def _story(us_id: str, status: str, reasons=(), mission="M-x") -> dict:
    return {
        "us_id": us_id,
        "mission_id": mission,
        "title": "t",
        "status": status,
        "reasons": list(reasons),
    }


def _runner(stories, nxt=None, *, code=0, stdout=None, stderr=""):
    calls: list[tuple] = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        out = (
            stdout
            if stdout is not None
            else json.dumps(
                {"notes": [], "stories": stories, "next": nxt, "unparented": []}
            )
        )
        return subprocess.CompletedProcess(cmd, code, out, stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_task_key():
    assert Task("ba-ticket-author", "US1").key == "ba-ticket-author:US1"


def test_ba_runs_mission_next_in_root(tmp_path: Path):
    run = _runner([])
    assert pick_ba(tmp_path, tmp_path / ".kb", run) is None
    cmd, kwargs = run.calls[0]
    assert cmd == ["kb", "mission", "next", "--json"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True


def test_ba_blocker_beats_draft_and_to_draft(tmp_path: Path):
    stories = [
        _story("US1", "draft", ["DoR 1/3 ticked"]),
        _story("US2", "blocked", ["D2 OPEN (owner: ba)"], mission="M-y"),
        _story("US3", "to-draft"),
    ]
    run = _runner(stories, "US3")
    assert pick_ba(tmp_path, tmp_path, run) == Task("ba-mission-plan", "--amend M-y")


@pytest.mark.parametrize(
    "reason",
    [
        "DoR 0/4 ticked",
        "no Definition of Ready section",
        "US M-x-US1 not done",
        "US M-x-US9 unknown",
    ],
)
def test_ba_ticket_level_reasons_are_not_blockers(tmp_path: Path, reason: str):
    stories = [_story("US1", "blocked", [reason])]
    assert pick_ba(tmp_path, tmp_path, _runner(stories)) is None


def test_ba_draft_beats_to_draft(tmp_path: Path):
    stories = [
        _story("US1", "to-draft"),
        _story("US2", "draft", ["DoR 1/3 ticked"]),
    ]
    run = _runner(stories, "US1")
    assert pick_ba(tmp_path, tmp_path, run) == Task("ba-ticket-author", "--amend US2")


def test_ba_to_draft_uses_next(tmp_path: Path):
    stories = [_story("US1", "done"), _story("US2", "to-draft")]
    run = _runner(stories, "US2")
    assert pick_ba(tmp_path, tmp_path, run) == Task("ba-ticket-author", "US2")


def test_ba_nothing_to_do(tmp_path: Path):
    stories = [_story("US1", "done"), _story("US2", "ready")]
    assert pick_ba(tmp_path, tmp_path, _runner(stories)) is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"code": 2, "stdout": "", "stderr": "boom"},
        {"stdout": "not json"},
    ],
)
def test_ba_subprocess_failure_raises(tmp_path: Path, kwargs):
    with pytest.raises(KbError):
        pick_ba(tmp_path, tmp_path, _runner([], **kwargs))


def test_ba_failure_message_truncates_stderr(tmp_path: Path):
    with pytest.raises(KbError) as exc:
        pick_ba(tmp_path, tmp_path, _runner([], code=1, stdout="", stderr="x" * 500))
    assert "x" * 300 in str(exc.value)
    assert "x" * 301 not in str(exc.value)


def _hub(monkeypatch, stories, unparented):
    monkeypatch.setattr(
        planstatus, "next_from_hub", lambda hub, repo=None: (stories, unparented, [])
    )


def _status(us_id: str, status: str, mission="M-x") -> StoryStatus:
    return StoryStatus(us_id, mission, "t", status, ())


def _workflow(root: Path, text: str = "name: kb-test\n") -> None:
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "kb-test.yml").write_text(text, encoding="utf-8")


def test_dev_test_workflow_beats_bug_and_story(tmp_path: Path, monkeypatch):
    _hub(monkeypatch, [_status("US1", "ready")], [_status("BUG-1", "ready", "")])
    assert pick_dev(None, tmp_path) == Task("dev-test-workflow", "")  # type: ignore[arg-type]


def test_dev_workflow_without_kb_test_still_missing(tmp_path: Path, monkeypatch):
    _hub(monkeypatch, [], [])
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yaml").write_text("name: other\n", encoding="utf-8")
    assert pick_dev(None, tmp_path) == Task("dev-test-workflow", "")  # type: ignore[arg-type]


def test_dev_bug_beats_story(tmp_path: Path, monkeypatch):
    _workflow(tmp_path)
    _hub(
        monkeypatch,
        [_status("US1", "ready")],
        [
            _status("TAL-1", "ready", ""),
            _status("BUG-2", "ready", ""),
            _status("BUG-3", "ready", ""),
        ],
    )
    assert pick_dev(None, tmp_path) == Task("dev-fix-bug", "BUG-2")  # type: ignore[arg-type]


def test_dev_skips_unready_bug(tmp_path: Path, monkeypatch):
    _workflow(tmp_path)
    _hub(
        monkeypatch,
        [_status("US1", "done"), _status("US2", "ready")],
        [_status("BUG-1", "blocked", "")],
    )
    assert pick_dev(None, tmp_path) == Task("dev-implement-ticket", "US2")  # type: ignore[arg-type]


def test_dev_nothing_to_do(tmp_path: Path, monkeypatch):
    _workflow(tmp_path)
    _hub(monkeypatch, [_status("US1", "done")], [_status("BUG-1", "done", "")])
    assert pick_dev(None, tmp_path) is None  # type: ignore[arg-type]


def test_dev_kb_test_yml_counts_even_without_the_mark(tmp_path: Path, monkeypatch):
    _workflow(tmp_path, "name: tests\n")
    _hub(monkeypatch, [], [])
    assert pick_dev(None, tmp_path) is None  # type: ignore[arg-type]
