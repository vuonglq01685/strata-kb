from __future__ import annotations

import pytest

from strata_kb.autorun.done import all_done
from strata_kb.missionnext import StoryStatus, render, to_json


def S(us_id: str, status: str) -> StoryStatus:
    return StoryStatus(us_id, "M-x", "t", status, ())


def test_to_json_carries_unparented():
    bug = StoryStatus("BUG-1", "", "Bug", "ready", ())
    data = to_json([S("US1", "done")], [], [bug])
    assert data["unparented"] == [
        {
            "us_id": "BUG-1",
            "mission_id": "",
            "title": "Bug",
            "status": "ready",
            "reasons": [],
        }
    ]
    assert to_json([], [])["unparented"] == []


def test_render_lists_unparented_only_when_present():
    bug = StoryStatus("BUG-1", "", "Bug", "ready", ())
    assert "Unparented:" in render([], [], unparented=[bug])
    assert "Unparented:" not in render([], [])


def test_all_done_dev_requires_every_story_and_bug():
    ok, why = all_done([S("US1", "done")], [S("BUG-1", "ready")], ba=False)
    assert (ok, why) == (False, "BUG-1 ready")


def test_all_done_dev_true_counts_every_ticket():
    ok, why = all_done([S("US1", "done")], [S("BUG-1", "done")], ba=False)
    assert (ok, why) == (True, "all 2 tickets done")


def test_all_done_dev_names_first_not_done_story():
    ok, why = all_done([S("US1", "done"), S("US2", "blocked")], [], ba=False)
    assert (ok, why) == (False, "US2 blocked")


def test_all_done_dev_with_nothing_is_not_done():
    assert all_done([], [], ba=False) == (False, "no tickets")


def test_all_done_ba_blocks_on_open_questions():
    assert all_done([S("US1", "done")], [], ba=True, open_questions=1)[0] is False


@pytest.mark.parametrize("status", ["to-draft", "draft", "blocked"])
def test_all_done_ba_blocks_on_unfinished_story(status):
    ok, why = all_done([S("US1", status)], [], ba=True)
    assert (ok, why) == (False, f"US1 {status}")


def test_all_done_ba_ok_when_ready_and_no_questions():
    ok, _ = all_done([S("US1", "ready"), S("US2", "done")], [], ba=True)
    assert ok is True
