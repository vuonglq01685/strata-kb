"""`familyhub.closed_story_issues` — amending a closed story is refused."""

from __future__ import annotations

import re

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


def _doc(rev: int | None, *, parent: str = "", head: str = "") -> str:
    lines = [f"# {STORY} — t", ""]
    lines += [head] if head else []
    lines += [f"> Revision: {rev}"] if rev else []
    lines += [f"> Parent story: {parent} @ rev 1"] if parent else []
    return "\n".join(lines) + "\n\n## Summary\n\nx\n"


def _closed_msgs(text, hub, ticket_id=STORY) -> list[str]:
    rep = familyhub.lint(text, hub, ticket_id=ticket_id)
    return [i.message for i in rep.issues if i.message == MSG]


def test_lint_amended_closed_parent_story_is_error(plan_hub):
    pub = _close(plan_hub)
    text = _doc(pub + 1, head="> Kind: parent")
    assert _closed_msgs(text, plan_hub) == [MSG]


def test_lint_unchanged_child_under_closed_parent_passes(plan_hub):
    pub = _close(plan_hub)
    assert _closed_msgs(_doc(pub, parent=STORY), plan_hub) == []


def test_lint_unchanged_ticket_without_revision_line_passes(plan_hub):
    _close(plan_hub)
    l3 = ticketfetch.find(plan_hub, STORY)[2]
    raw = l3.read_text(encoding="utf-8")
    l3.write_text(re.sub(r"^> Revision: \d+\n", "", raw, flags=re.M), encoding="utf-8")
    assert planrev.parse_revision(ticketfetch.render(plan_hub, STORY)) is None
    assert _closed_msgs(_doc(None), plan_hub) == []


def test_lint_child_bug_under_closed_parent_bug_is_not_checked(plan_hub):
    pub = _close(plan_hub)
    text = _doc(pub + 1, parent=STORY, head="> Type: bug")
    assert _closed_msgs(text, plan_hub, f"{STORY}.b") == []


def test_lint_without_ticket_id_notes_skip(plan_hub):
    rep = familyhub.lint(_doc(1), plan_hub)
    assert familyhub.CLOSED_SKIP_NOTE in rep.notes


def test_planless_hub_has_no_closed_story_issue(fed_hub):
    from strata_kb.hub import HubHandle

    assert familyhub.closed_story_issues(STORY, "", 2, HubHandle(root=fed_hub)) == []
