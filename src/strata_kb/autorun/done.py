"""The runner's stop test: is the product done for this role."""

from __future__ import annotations

from collections.abc import Sequence

from strata_kb.missionnext import StoryStatus

# BA is done when nothing is left to write: a published ticket (ready) is enough.
_BA_OPEN = frozenset({"to-draft", "draft", "blocked"})


def all_done(
    stories: Sequence[StoryStatus],
    unparented: Sequence[StoryStatus],
    *,
    ba: bool,
    open_questions: int = 0,
) -> tuple[bool, str]:
    """(True, "all N tickets done") or (False, first reason). Dev needs every
    story and unparented ticket `done`; BA needs no story still to write
    (`to-draft`/`draft`/`blocked`) and no open question. No tickets at all is
    not done: an empty hub is a hub the plan has not reached yet."""
    tickets = [*stories, *unparented]
    if not tickets:
        return False, "no tickets"
    for t in tickets:
        if (t.status in _BA_OPEN) if ba else (t.status != "done"):
            return False, f"{t.us_id} {t.status}"
    if ba and open_questions:
        return False, f"{open_questions} open questions"
    return True, f"all {len(tickets)} tickets done"
