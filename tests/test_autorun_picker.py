from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from strata_kb import planstatus
from strata_kb.autorun.picker import Task, dev_candidates, pick_ba, pick_dev
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
    assert kwargs["encoding"] == "utf-8"


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
        "parent mission rev 3 affects this story",
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


def test_dev_ready_unparented_ticket_beats_mission_story(tmp_path: Path, monkeypatch):
    _workflow(tmp_path)
    _hub(
        monkeypatch,
        [_status("US1", "ready")],
        [
            _status("TAL-1", "blocked", ""),
            _status("TAL-2", "ready", ""),
            _status("BUG-9", "done", ""),
        ],
    )
    assert pick_dev(None, tmp_path) == Task("dev-implement-ticket", "TAL-2")  # type: ignore[arg-type]


def test_dev_ready_bug_beats_ready_unparented_ticket(tmp_path: Path, monkeypatch):
    _workflow(tmp_path)
    _hub(
        monkeypatch,
        [],
        [_status("TAL-1", "ready", ""), _status("BUG-2", "ready", "")],
    )
    assert pick_dev(None, tmp_path) == Task("dev-fix-bug", "BUG-2")  # type: ignore[arg-type]


def test_dev_nothing_to_do(tmp_path: Path, monkeypatch):
    _workflow(tmp_path)
    _hub(monkeypatch, [_status("US1", "done")], [_status("BUG-1", "done", "")])
    assert pick_dev(None, tmp_path) is None  # type: ignore[arg-type]


def test_ba_demoted_ticket_is_amended_not_a_mission_blocker(tmp_path: Path):
    stories = [_story("US1", "draft", ["parent mission rev 4 affects this story"])]
    assert pick_ba(tmp_path, tmp_path, _runner(stories)) == Task(
        "ba-ticket-author", "--amend US1"
    )


def test_ba_draft_with_d_row_reason_is_a_mission_blocker(tmp_path: Path):
    stories = [_story("US1", "draft", ["D3 OPEN (owner: ba)"], mission="M-z")]
    assert pick_ba(tmp_path, tmp_path, _runner(stories)) == Task(
        "ba-mission-plan", "--amend M-z"
    )


@pytest.mark.parametrize("reason", ["Q2 open (owner: ba)", "open question 'which db?'"])
def test_ba_question_reasons_are_mission_blockers(tmp_path: Path, reason: str):
    stories = [_story("US1", "draft", [reason], mission="M-q")]
    assert pick_ba(tmp_path, tmp_path, _runner(stories)) == Task(
        "ba-mission-plan", "--amend M-q"
    )


def test_ba_first_blocker_in_mission_order_wins(tmp_path: Path):
    stories = [
        _story("US1", "blocked", ["D1 OPEN (owner: a)"], mission="M-a"),
        _story("US2", "blocked", ["Q1 open (owner: b)"], mission="M-b"),
    ]
    assert pick_ba(tmp_path, tmp_path, _runner(stories)) == Task(
        "ba-mission-plan", "--amend M-a"
    )


@pytest.mark.parametrize(
    "stdout", ["{}", "null", "[]", '{"stories": [{}], "next": null}']
)
def test_ba_unexpected_json_shape_raises(tmp_path: Path, stdout: str):
    with pytest.raises(KbError, match="unexpected JSON"):
        pick_ba(tmp_path, tmp_path, _runner([], stdout=stdout))


def test_ba_bad_json_message_quotes_stdout(tmp_path: Path):
    with pytest.raises(KbError, match="'not json'"):
        pick_ba(tmp_path, tmp_path, _runner([], stdout="not json"))


def _dep(us_id: str, status: str, depends_on=()) -> StoryStatus:
    return StoryStatus(us_id, "M-x", "t", status, (), tuple(depends_on))


def test_dev_skips_ready_story_with_open_dependency(tmp_path: Path, monkeypatch):
    _workflow(tmp_path)
    _hub(
        monkeypatch,
        [_dep("US1", "draft"), _dep("US2", "ready", ["US1"])],
        [],
    )
    assert pick_dev(None, tmp_path) is None  # type: ignore[arg-type]


def test_dev_takes_next_story_whose_dependencies_are_done(tmp_path: Path, monkeypatch):
    _workflow(tmp_path)
    _hub(
        monkeypatch,
        [
            _dep("US1", "draft"),
            _dep("US2", "ready", ["US1"]),
            _dep("US3", "done"),
            _dep("US4", "ready", ["US3"]),
        ],
        [],
    )
    assert pick_dev(None, tmp_path) == Task("dev-implement-ticket", "US4")  # type: ignore[arg-type]


def test_dev_ignores_directory_named_like_a_workflow(tmp_path: Path, monkeypatch):
    _hub(monkeypatch, [], [])
    (tmp_path / ".github" / "workflows" / "x.yml").mkdir(parents=True)
    assert pick_dev(None, tmp_path) == Task("dev-test-workflow", "")  # type: ignore[arg-type]


def test_ba_skip_passes_over_a_draft_to_the_next_draft(tmp_path: Path):
    stories = [
        _story("US1", "draft", ["DoR 7/8 ticked"]),
        _story("US2", "draft", ["DoR 5/8 ticked"]),
    ]
    skip = {"ba-ticket-author:--amend US1"}
    assert pick_ba(tmp_path, tmp_path, _runner(stories), skip=skip) == Task(
        "ba-ticket-author", "--amend US2"
    )


def test_ba_skipped_drafts_fall_through_to_to_draft(tmp_path: Path):
    stories = [
        _story("US1", "draft", ["DoR 7/8 ticked"]),
        _story("US2", "to-draft"),
        _story("US3", "to-draft"),
    ]
    run = _runner(stories, nxt="US2")
    skip = {"ba-ticket-author:--amend US1"}
    assert pick_ba(tmp_path, tmp_path, run, skip=skip) == Task(
        "ba-ticket-author", "US2"
    )
    skip.add("ba-ticket-author:US2")
    assert pick_ba(tmp_path, tmp_path, run, skip=skip) == Task(
        "ba-ticket-author", "US3"
    )
    skip.add("ba-ticket-author:US3")
    assert pick_ba(tmp_path, tmp_path, run, skip=skip) is None


def test_dev_skip_passes_over_a_ready_ticket(tmp_path: Path, monkeypatch):
    _workflow(tmp_path)
    _hub(monkeypatch, [_dep("US1", "ready"), _dep("US2", "ready")], [])
    skip = {"dev-implement-ticket:US1"}
    assert pick_dev(None, tmp_path, skip) == Task("dev-implement-ticket", "US2")  # type: ignore[arg-type]


def test_dev_skipped_test_workflow_picks_nothing(tmp_path: Path, monkeypatch):
    _hub(monkeypatch, [_dep("US1", "ready")], [])
    assert pick_dev(None, tmp_path, {"dev-test-workflow:"}) is None  # type: ignore[arg-type]


def test_dev_candidates_skip_held(tmp_path: Path, monkeypatch):
    _workflow(tmp_path)
    _hub(monkeypatch, [_status("US1", "ready"), _status("US2", "ready")], [])
    tasks = dev_candidates(None, tmp_path, held={"US1"})  # type: ignore[arg-type]
    assert tasks == [Task("dev-implement-ticket", "US2")]
    assert pick_dev(None, tmp_path, held={"US1"}) == tasks[0]  # type: ignore[arg-type]


def test_dev_candidates_keep_pick_order_and_skip(tmp_path: Path, monkeypatch):
    _workflow(tmp_path)
    _hub(
        monkeypatch,
        [_status("US1", "ready")],
        [_status("TAL-1", "ready", ""), _status("BUG-2", "ready", "")],
    )
    keys = [t.key for t in dev_candidates(None, tmp_path)]  # type: ignore[arg-type]
    assert keys == [
        "dev-fix-bug:BUG-2",
        "dev-implement-ticket:TAL-1",
        "dev-implement-ticket:US1",
    ]
    skipped = dev_candidates(None, tmp_path, skip=[keys[0]])  # type: ignore[arg-type]
    assert [t.key for t in skipped] == keys[1:]
