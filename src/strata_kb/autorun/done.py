"""The runner's stop test: is the product done for this role."""

from __future__ import annotations

from collections.abc import Sequence

from strata_kb.missionnext import OWN_FIX_PENDING, StoryStatus

# BA reports these first: they say more than "US3 ready" does.
_BA_FIRST = frozenset({"to-draft", "draft", "blocked"})


def all_done(
    stories: Sequence[StoryStatus],
    unparented: Sequence[StoryStatus],
    *,
    ba: bool,
    open_questions: int = 0,
    repo_id: str | None = None,
) -> tuple[bool, str]:
    """(True, "all N tickets done") or (False, first reason). Both roles need
    every story and unparented ticket `done`: the BA loop does not stop while
    Dev work is open. BA also needs no open question, and names a story still
    to write (`to-draft`/`draft`/`blocked`) before one merely `ready`. No
    tickets at all is not done: an empty hub is a hub the plan has not reached
    yet. A Dev (`repo_id` given) counts only rows routed to its repo or not routed yet."""
    tickets = [*stories, *unparented]
    if not ba:  # a parent is rolled up from its children: no Dev work of its own
        # ...except a parent bug's own fix, pending for its target repo
        tickets = [
            t
            for t in tickets
            if not t.is_parent or (t.target_repo and OWN_FIX_PENDING in t.reasons)
        ]
    if repo_id and not ba:
        tickets = [t for t in tickets if t.target_repo in (repo_id, None)]
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
