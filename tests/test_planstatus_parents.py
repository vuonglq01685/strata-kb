"""Plan status of parent stories: a rolled-up parent row, children with the
dependencies of the split, and the same rows from the local `kb mission next`."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from strata_kb import hubapi, missionnext, planingest, planparents, planstatus
from strata_kb.hub import HubHandle
from tests.test_missionlint import MISSION_ID
from tests.test_planingest import (
    API,
    US1,
    WEB,
    child_story,
    context_block,
    family,
    mission_text,
    parent_story,
    write_repo,
)
from tests.test_planstatus import _mirror
from tests.test_planstatus_routing import _dev

GOLDEN = Path(__file__).parent / "data" / "planstatus_golden.json"
NEW_KEYS = {"is_parent": False, "parent": ""}


def _plan_json(hub: HubHandle) -> dict:
    stories, unparented, notes = planstatus.next_from_hub(hub)
    return missionnext.to_json(stories, notes, unparented)


def _strip_new(data: dict) -> dict:
    """Drop the two parent fields, which every row carries (default values)."""
    for key in ("stories", "unparented"):
        for row in data[key]:
            for new, default in NEW_KEYS.items():
                assert row.pop(new, default) == default
    return data


def test_plan_without_parents_unchanged(plan_hub):
    actual = _strip_new(_plan_json(plan_hub))
    if os.environ.get("UPDATE_GOLDEN"):  # regenerate from the pre-change code only
        GOLDEN.write_text(json.dumps(actual, indent=1), encoding="utf-8")
    assert actual == json.loads(GOLDEN.read_text(encoding="utf-8"))


# --- parent stories ---
US2 = f"{MISSION_ID}-US2"
US3 = f"{MISSION_ID}-US3"
LATER_ROW = "| 2 | 2026-10-11 | scope | AC changed | {aff} | B4 D4 (agent) |\n"
BLOCKED_SPLIT = (
    f"| {API} | demo | AC1, AC2 | - | - | data |\n"
    f"| {WEB} | web | AC3, AC4 | {API} | - | ui |\n"
)


@pytest.fixture
def build(fed_hub: Path, tmp_path: Path):
    """`make(devs=, done=, mission=, **family kwargs)` → hub handle with the
    published plan of one parent story (`US1`) and its two children."""

    def make(
        devs: tuple[str, ...] = ("demo", "web"),
        done: dict[str, tuple[str, ...]] | None = None,
        mission: str | None = None,
        unticked: tuple[str, ...] = (),
        unwritten: tuple[str, ...] = (),
        **kw,
    ) -> HubHandle:
        block = context_block(fed_hub)
        missions, tickets = family(block, **kw)
        for name in unwritten:  # planned child: a split row, no file
            del tickets[f"{name}.md"]
        if mission:
            missions = {f"{MISSION_ID}.md": mission}
        if kw.get("split") == BLOCKED_SPLIT:  # the child names its blocker too
            tickets[f"{WEB}.md"] = tickets[f"{WEB}.md"].replace(
                "- Blocked by: None", f"- Blocked by: {API}"
            )
        for name, first_ac in ((API, 1), (WEB, 3)):
            if name in unticked:  # not ready for Dev: plan-ingest does not publish it
                repo = "demo" if name == API else "web"
                tickets[f"{name}.md"] = child_story(
                    block, name, repo, first_ac, ticked=False
                )
        root = tmp_path / "ba-x"
        write_repo(root, missions, tickets)
        planingest.run(root, root / ".kb", "demo", root / "missions", root / "tickets")
        _mirror(fed_hub, root, "ba-x")
        for repo in devs:
            _dev(fed_hub, repo, (done or {}).get(repo, ()))
        return HubHandle(root=fed_hub)

    return make


def _rows(hub: HubHandle) -> dict[str, missionnext.StoryStatus]:
    stories, unparented, _ = planstatus.next_from_hub(hub)
    return {r.us_id: r for r in (*stories, *unparented)}


@pytest.mark.parametrize(
    ("done", "status", "reason"),
    [
        ({}, "in progress", "0/2 done"),
        ({"demo": (API,)}, "in progress", "1/2 done"),
        ({"demo": (API,), "web": (WEB,)}, "done", "2/2 done"),
    ],
)
def test_parent_row_rolls_up_in_progress_done(build, done, status, reason):
    rows = _rows(build(done=done))
    parent = rows[US1]
    assert (parent.status, parent.reasons) == (status, (reason,))
    assert parent.is_parent and parent.target_repo is None
    assert [rows[API].parent, rows[WEB].parent] == [US1, US1]
    assert not rows[API].is_parent
    assert rows[API].target_repo == "demo" and rows[WEB].target_repo == "web"


def test_parent_row_rolls_up_blocked(build):
    # demo is no dev repo on this hub: API is refused, WEB waits for it
    rows = _rows(build(devs=("web",), split=BLOCKED_SPLIT))
    assert rows[API].status == rows[WEB].status == "blocked"
    assert (rows[US1].status, rows[US1].reasons) == ("blocked", ("0/2 done",))


@pytest.mark.parametrize("done", [{}, {"demo": (API,)}, {"web": (WEB,)}])
def test_parent_is_never_ready(build, done):
    assert _rows(build(done=done))[US1].status != "ready"


def test_child_depends_on_from_split_exact_dotted_ids(build):
    rows = _rows(build(split=BLOCKED_SPLIT))
    assert rows[API].depends_on == ()
    assert rows[WEB].depends_on == (API,)
    assert rows[WEB].status == "blocked"
    assert rows[WEB].reasons == (f"blocked by {API} (not done)",)
    assert rows[API].status == "ready"


def test_child_ready_once_its_split_blocker_is_done(build):
    rows = _rows(build(split=BLOCKED_SPLIT, done={"demo": (API,)}))
    assert rows[WEB].status == "ready" and rows[WEB].reasons == ()


def _sequenced(fed_hub: Path) -> str:
    backlog = "| US ID | Title |\n|---|---|\n" + "\n".join(
        f"| {u} | Story |" for u in (US1, US2, US3)
    )
    sequencing = (
        "| US ID | Depends on | Size | Notes |\n|---|---|---|---|\n"
        f"| {US3} | None | S | |\n| {US1} | {US3} | M | |\n| {US2} | {US1} | S | |"
    )
    return mission_text(
        context_block(fed_hub),
        overrides={"## US backlog": backlog, "## Sequencing": sequencing},
    )


def test_mission_child_inherits_mission_depends_on(build, fed_hub):
    rows = _rows(build(mission=_sequenced(fed_hub)))
    assert rows[US1].depends_on == (US3,)
    assert rows[API].depends_on == (US3,)
    assert rows[WEB].depends_on == (US3,)
    assert rows[API].status == "blocked"
    assert rows[API].reasons == (f"blocked by {US3} (not done)",)
    assert rows[API].mission_id == MISSION_ID
    # a story depending on the parent waits for the roll-up
    assert rows[US2].status == "blocked"


def test_story_depending_on_parent_waits_for_the_roll_up(build):
    # the default mission sequences US2 after US1 (the parent)
    assert _rows(build())[US2].reasons == (f"US {US1} not done",)


def test_story_depending_on_a_done_parent_is_to_draft(build):
    done = _rows(build(done={"demo": (API,), "web": (WEB,)}))
    assert done[US1].status == "done" and done[US2].status == "to-draft"


def test_unwritten_split_child_is_to_draft(build):
    rows = _rows(build(unticked=(WEB,)))
    assert rows[WEB].status == "to-draft"
    assert rows[WEB].reasons == ("child not written yet",)
    assert rows[WEB].parent == US1 and rows[WEB].target_repo == "web"
    assert rows[US1].reasons == ("0/2 done",) and rows[US1].status == "in progress"


def test_demoted_child_is_off_the_hub_until_written_again(build):
    # WEB is demoted by a later parent row: plan-ingest does not publish it
    rows = _rows(build(rev=2, extra_log=LATER_ROW.format(aff=WEB)))
    assert rows[WEB].status == "to-draft"
    assert rows[API].status == "ready"


def test_done_child_not_demoted(build):
    rows = _rows(
        build(
            rev=2,
            extra_log=LATER_ROW.format(aff=WEB),
            done={"web": (WEB,)},
        )
    )
    assert rows[WEB].status == "done"
    assert rows[US1].reasons == ("1/2 done",)


def test_hubapi_story_tolerates_missing_parent_keys():
    old = {
        "us_id": "A",
        "mission_id": "M",
        "title": "t",
        "status": "ready",
        "reasons": [],
        "depends_on": [],
    }
    row = hubapi._story(old)
    assert (row.is_parent, row.parent) == (False, "")
    new = hubapi._story({**old, "is_parent": True, "parent": "P"})
    assert (new.is_parent, new.parent) == (True, "P")


# --- mission blockers reach the family ---

OPEN_D1 = (
    "| # | Decision | Status | Owner | Blocks |\n|---|---|---|---|---|\n"
    f"| D1 | Map rendering library | OPEN | tech-lead | {US1} |"
)


def _family(fed_hub: Path, **overrides):
    """Rows of the parent for a mission with `overrides`, no child written
    (a blocked parent still publishes; the hub is not involved here)."""
    mission = mission_text(context_block(fed_hub), overrides=overrides)
    parent = missionnext.StoryStatus(US1, MISSION_ID, "Story", "x", ())
    facts = planparents.Facts(
        written=frozenset(),
        dor={},
        done=frozenset(),
        mission_texts={MISSION_ID: mission},
    )
    return planparents.family_rows(parent, parent_story(), facts)


def test_unwritten_child_of_a_blocked_mission_parent_is_blocked(fed_hub):
    head, api, web = _family(fed_hub, **{"## Technology decisions": OPEN_D1})
    assert api.status == web.status == "blocked"
    assert api.reasons[0].startswith("D1 OPEN")
    assert head.reasons[0] == "0/2 done" and head.reasons[1].startswith("D1 OPEN")


def test_unwritten_child_waits_for_the_mission_dependency(build, fed_hub):
    rows = _rows(build(mission=_sequenced(fed_hub), unticked=(WEB,)))
    assert rows[WEB].status == "blocked"
    assert rows[WEB].reasons == (f"US {US3} not done",)


def test_unwritten_child_of_an_open_question_is_blocked(fed_hub):
    question = (
        "- [ ] Q1 — Which tile provider? — owner: tech-lead — impact: cost — "
        f"blocks: {US1}"
    )
    _, api, _ = _family(fed_hub, **{"## Open questions": question})
    assert api.status == "blocked" and "Q1" in api.reasons[0]


def test_planned_child_reads_to_draft(build):
    split = (
        f"| {API} | demo | AC1, AC2 | - | - | data |\n"
        f"| {WEB} | web | - | - | - | ui |\n"
    )
    hub = build(split=split, unwritten=(WEB,))
    rows = _rows(hub)
    assert rows[WEB].status == "to-draft"
    assert rows[WEB].reasons == ("child not written yet",)
    assert (rows[US1].status, rows[US1].reasons) == ("in progress", ("0/2 done",))
