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
NEW_KEYS = {
    "is_parent": False,
    "parent": "",
    "own_fix_ready": False,
    "test_status": "",
    "test_round": 0,
    "regression_bug": False,
}


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


# --- parent bugs: the own-fix row is not a child here (Task 2 rolls it up) ---


def _bug_parent(own_fix: str = "yes") -> str:
    from tests.test_ticketlint_family import bug_parent_text

    return bug_parent_text().replace("| yes |", f"| {own_fix} |", 1)


def test_family_rows_of_a_parent_bug_has_no_row_for_the_parent_itself():
    parent = missionnext.StoryStatus("BUG-12", "", "Bug", "x", ())
    facts = planparents.Facts(written=frozenset(), dor={}, done=frozenset())
    rows = planparents.family_rows(parent, _bug_parent(), facts)
    assert [r.us_id for r in rows] == ["BUG-12", "BUG-12.api", "BUG-12.web"]
    assert [r.parent for r in rows] == ["", "BUG-12", "BUG-12"]


def test_done_parents_of_a_parent_bug_needs_its_own_fix():
    done = {"BUG-12.api", "BUG-12.web"}
    yes, no = _bug_parent(), _bug_parent("no")
    assert planparents.done_parents({"BUG-12": no}, done) == {"BUG-12"}
    assert planparents.done_parents({"BUG-12": no}, {"BUG-12.api"}) == set()
    assert planparents.done_parents({"BUG-12": yes}, done) == set()
    assert planparents.done_parents({"BUG-12": yes}, done, {"BUG-12"}) == {"BUG-12"}


# --- parent bugs: roll-up of the children plus the own fix ---
PID = "BUG-12"
BUG_API, BUG_WEB = f"{PID}.api", f"{PID}.web"


@pytest.fixture
def bug_build(fed_hub: Path, tmp_path: Path):
    """`make(done=, own_fix=)` → hub with the published parent bug BUG-12
    (own fix routed to `api`) and its two child bugs."""
    from tests.test_ticketlint_family import bug_family

    def make(
        done: dict[str, tuple[str, ...]] | None = None,
        own_fix: str = "yes",
        own_blocked: str = "-",
    ):
        texts = bug_family()
        texts[PID] = (
            texts[PID]
            .replace("| - | yes |", f"| {own_blocked} | {own_fix} |", 1)
            .replace("> Kind: parent bug\n", "> Kind: parent bug\n> Target repo: api\n")
        )
        tickets = {
            f"bugs/{i}.md": t.replace("- [ ] ", "- [x] ") for i, t in texts.items()
        }
        root = tmp_path / "ba-x"
        write_repo(root, {}, tickets)
        folder = root / "tickets" / "bugs" / PID
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "toast.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        planingest.run(root, root / ".kb", "demo", root / "missions", root / "tickets")
        _mirror(fed_hub, root, "ba-x")
        for repo in ("api", "web"):
            _dev(fed_hub, repo, (done or {}).get(repo, ()))
        return HubHandle(root=fed_hub)

    return make


KIDS_DONE = {"api": (BUG_API,), "web": (BUG_WEB,)}


def test_own_fix_done_alone_does_not_finish_parent_bug(bug_build):
    rows = _rows(bug_build(done={"api": (PID,)}))
    assert rows[PID].status != "done"
    assert "0/2 done" in rows[PID].reasons and "own fix done" in rows[PID].reasons


def test_own_fix_no_needs_children_only(bug_build):
    rows = _rows(bug_build(done=KIDS_DONE, own_fix="no"))
    assert rows[PID].status == "done"
    assert rows[PID].reasons == ("2/2 done",)
    assert not rows[PID].own_fix_ready


def test_parent_bug_done_when_children_and_own_fix_done(bug_build):
    rows = _rows(bug_build(done={"api": (BUG_API, PID), "web": (BUG_WEB,)}))
    assert (rows[PID].status, rows[PID].reasons) == (
        "done",
        ("2/2 done", "own fix done"),
    )
    assert rows[PID].target_repo == "api" and rows[PID].is_parent


def test_own_fix_ready_after_blockers_done(bug_build):
    hub = bug_build(own_blocked=BUG_WEB)
    pending = _rows(hub)[PID]
    assert pending.reasons == ("0/2 done", "own fix pending")
    assert not pending.own_fix_ready


@pytest.mark.parametrize(
    ("done", "ready"),
    [
        ({"api": (BUG_API,)}, False),
        (KIDS_DONE, True),
        ({"api": (BUG_API, PID), "web": (BUG_WEB,)}, False),  # fix already done
    ],
)
def test_own_fix_ready_follows_its_blockers(bug_build, done, ready):
    assert _rows(bug_build(done=done, own_blocked=BUG_WEB))[PID].own_fix_ready is ready


def test_own_fix_without_blockers_is_ready_at_once(bug_build):
    assert _rows(bug_build())[PID].own_fix_ready


def _lint_errors(hub: HubHandle, pid: str) -> list[str]:
    from strata_kb.familyhub import lint
    from tests.test_ticketlint_family import bug_family

    texts = bug_family(pid)
    report = lint(texts[pid], hub, ticket_id=pid, load_ticket=texts.get)
    return [str(i) for i in report.issues]


def test_published_parent_bug_may_be_done_in_svc(bug_build):
    hub = bug_build(done={"api": (PID,)})
    assert not [e for e in _lint_errors(hub, PID) if "already implemented" in e]


def test_done_bug_not_on_hub_cannot_become_parent(bug_build):
    hub = bug_build(done={"api": ("BUG-99",)})
    assert any("already implemented" in e for e in _lint_errors(hub, "BUG-99"))


def test_test_report_overlays_parent_and_guilty_child_only(build):
    from tests.test_testflow import _text, publish_tests

    hub = build(done={"demo": (API,), "web": (WEB,)})
    publish_tests(
        hub.root,
        "qa-repo",
        US1,
        _text(US1, 1, "FAIL", guilty=API),
    )
    rows = _rows(hub)
    assert [(rows[i].status, rows[i].test_status) for i in (US1, API, WEB)] == [
        ("done", "reopened"),
        ("done", "reopened"),
        ("done", ""),
    ]
    assert rows[US1].test_round == 1
