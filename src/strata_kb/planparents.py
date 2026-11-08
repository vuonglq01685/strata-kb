"""Parent stories in plan status: one parent row that rolls up its children,
and one child row per `## Split` row.

A parent is never worked on itself, so it is never `ready`: it is `done` when
every child is, `blocked` when no child is ready and one is blocked, else
`in progress`. A child's dependencies are the split's `Blocked by` ids (exact
ids, nothing fuzzy) plus the parent's own mission `Depends on`. The hub and the
local `kb mission next` both build their rows here, from the same `Facts`.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from strata_kb import missionnext, storylint, ticket

IN_PROGRESS = "in progress"
_H1_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.M)


def is_parent(text: str) -> bool:
    return ticket.ticket_kind(text) in ("parent story", "parent bug")


def is_parent_story(text: str) -> bool:
    return ticket.ticket_kind(text) == "parent story"


def is_parent_bug(text: str) -> bool:
    return ticket.ticket_kind(text) == "parent bug"


def title_of(text: str) -> str:
    m = _H1_RE.search(text)
    return m.group(1) if m else ""


@dataclass(frozen=True)
class Facts:
    """What a caller knows about the tickets of one plan."""

    written: frozenset[str]  # ticket ids that exist (hub: published)
    dor: dict[str, tuple[int, int]]  # id -> ticked, total Definition of Ready boxes
    done: frozenset[str]  # ids done: children, mission stories, parents
    mission_texts: dict[str, str] = field(default_factory=dict)  # mission id -> text
    titles: dict[str, str] = field(default_factory=dict)  # ticket id -> title
    targets: dict[str, str | None] = field(default_factory=dict)  # child -> routed repo
    unknown: frozenset[str] = frozenset()  # ids whose done nothing could answer
    demoted: dict[str, str] = field(default_factory=dict)  # id -> demotion reason
    refusal: Callable[[str | None], str | None] = lambda _target: None


def done_parents(parents: dict[str, str], done: Iterable[str]) -> set[str]:
    """Ids of the parents whose split children are all in `done`."""
    done = set(done)
    out = set()
    for pid, text in parents.items():
        split = storylint.parse_split(text)
        if split and all(r.child in done for r in split):
            out.add(pid)
    return out


def family_rows(
    parent: missionnext.StoryStatus, text: str, facts: Facts
) -> list[missionnext.StoryStatus]:
    """The parent row followed by one row per split row."""
    split = storylint.parse_split(text)
    ids = {r.child for r in split}
    mission = facts.mission_texts.get(parent.mission_id)
    inherited = (
        tuple(missionnext.story_blockers(mission, parent.us_id)) if mission else ()
    )
    kids = []
    for row in split:
        deps = tuple(
            dict.fromkeys(
                [
                    *(t for t in row.blocked_by if t in ids and t != row.child),
                    *parent.depends_on,
                ]
            )
        )
        kids.append(_child(parent, row, deps, inherited, facts))
    done = sum(k.status == "done" for k in kids)
    if kids and done == len(kids):
        status = "done"
    elif any(k.status == "blocked" for k in kids) and not any(
        k.status == "ready" for k in kids
    ):
        status = "blocked"
    else:
        status = IN_PROGRESS
    head = dataclasses.replace(
        parent,
        status=status,
        # the mission's open decisions stay visible: the BA amends the mission
        reasons=(f"{done}/{len(kids)} done", *inherited),
        target_repo=None,
        is_parent=True,
    )
    return [head, *kids]


def _child(
    parent: missionnext.StoryStatus,
    row: storylint.SplitRow,
    deps: tuple[str, ...],
    inherited: tuple[str, ...],
    facts: Facts,
) -> missionnext.StoryStatus:
    cid = row.child
    target = facts.targets.get(cid) or row.repo
    status, reasons = _child_status(cid, target, deps, inherited, parent, facts)
    title = facts.titles.get(cid) or f"{parent.title} ({row.repo})"
    return missionnext.StoryStatus(
        cid,
        parent.mission_id,
        title,
        status,
        reasons,
        deps,
        target,
        parent=parent.us_id,
    )


def _child_status(
    cid: str,
    target: str,
    deps: tuple[str, ...],
    inherited: tuple[str, ...],
    parent: missionnext.StoryStatus,
    facts: Facts,
) -> tuple[str, tuple[str, ...]]:
    """done → no ticket (blocked while the mission blocks it, else to-draft) →
    draft (mission blockers, demotion, DoR) → blocked (routing refusal,
    dependency not done) → ready."""
    parent_id = parent.us_id
    if cid in facts.done:
        return "done", ()
    if cid not in facts.written:
        gated = (
            *inherited,
            *(f"US {d} not done" for d in parent.depends_on if d not in facts.done),
        )
        if gated:
            return "blocked", gated
        return "to-draft", ("child not written yet",)
    if inherited:
        return "draft", inherited
    demoted = facts.demoted.get(cid) or facts.demoted.get(parent_id)
    if demoted:
        return "draft", (demoted,)
    ticked, total = facts.dor.get(cid, (0, 0))
    if not total or ticked != total:
        why = (
            f"DoR {ticked}/{total} ticked"
            if total
            else "no Definition of Ready section"
        )
        return "draft", (why,)
    if refusal := facts.refusal(target):
        return "blocked", (refusal,)
    if pending := [d for d in deps if d not in facts.done]:
        return "blocked", tuple(f"blocked by {d} (not done)" for d in pending)
    return "ready", (("done: unknown",) if cid in facts.unknown else ())


def expand(
    rows: list[missionnext.StoryStatus], parents: dict[str, str], facts: Facts
) -> list[missionnext.StoryStatus]:
    """`rows` with each parent story's row replaced by its family."""
    out: list[missionnext.StoryStatus] = []
    for r in rows:
        if r.us_id in parents:
            out += family_rows(r, parents[r.us_id], facts)
        else:
            out.append(r)
    return out
