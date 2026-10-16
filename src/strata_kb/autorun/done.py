"""The runner's stop test: is the product done for this role."""

from __future__ import annotations

from collections.abc import Sequence

from strata_kb.missionnext import StoryStatus

# BA reports these first: they say more than "US3 ready" does.
_BA_FIRST = frozenset({"to-draft", "draft", "blocked"})


def all_done(
    stories: Sequence[StoryStatus],
    unparented: Sequence[StoryStatus],
    *,
    ba: bool,
    open_questions: int = 0,
) -> tuple[bool, str]:
    """(True, "all N tickets done") or (False, first reason). Both roles need
    every story and unparented ticket `done`: the BA loop does not stop while
    Dev work is open. BA also needs no open question, and names a story still
    to write (`to-draft`/`draft`/`blocked`) before one merely `ready`. No
    tickets at all is not done: an empty hub is a hub the plan has not reached
    yet."""
    tickets = [*stories, *unparented]
    if not tickets:
        return False, "no tickets"
    open_ = [t for t in tickets if t.status != "done"]
    if ba:
        open_.sort(key=lambda t: t.status not in _BA_FIRST)  # stable
    if open_:
        return False, f"{open_[0].us_id} {open_[0].status}"
    if ba and open_questions:
        noun = "question" if open_questions == 1 else "questions"
        return False, f"{open_questions} open {noun}"
    return True, f"all {len(tickets)} tickets done"
