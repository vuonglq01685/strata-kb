"""`familyhub.closed_story_issues` — amending a closed story is refused."""

from __future__ import annotations

from strata_kb import familyhub, planrev, ticketfetch
from tests.test_testflow import STORY, _text, publish_tests

MSG = "story is closed — write a new story"


def _close(hub) -> int:
    publish_tests(hub.root, "tester-one", STORY, _text(STORY, 1, "PASS"))
    return planrev.parse_revision(ticketfetch.render(hub, STORY)) or 1


def test_amend_of_closed_story_is_error(plan_hub):
    pub = _close(plan_hub)
    (issue,) = familyhub.closed_story_issues(STORY, "", pub + 1, plan_hub)
    assert (issue.level, issue.message) == ("error", MSG)


def test_unchanged_ticket_under_closed_story_passes(plan_hub):
    pub = _close(plan_hub)
    assert familyhub.closed_story_issues(STORY, "", pub, plan_hub) == []


def test_new_child_under_closed_parent_is_error(plan_hub):
    _close(plan_hub)
    (issue,) = familyhub.closed_story_issues(f"{STORY}.new", STORY, 1, plan_hub)
    assert (issue.level, issue.message) == ("error", MSG)


def test_open_story_amend_passes(plan_hub):
    assert familyhub.closed_story_issues(STORY, "", 9, plan_hub) == []


def test_no_hub_warns():
    (issue,) = familyhub.closed_story_issues(STORY, "", 2, None)
    assert (issue.level, issue.message) == (
        "warning",
        "story status not checked (hub unreachable)",
    )
