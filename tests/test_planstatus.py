"""`planstatus` — plan status derived from a hub's `*-plan` documents and the
Dev repo's `-svc` history. Read-only; nothing is stored."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from strata_kb import planingest, planstatus
from strata_kb.hub import HubHandle
from tests.conftest import make_fed_entry
from tests.test_missionlint import MISSION_ID
from tests.test_planingest import context_block, mission_text, ticket_text, write_repo

US = [f"{MISSION_ID}-US{n}" for n in range(1, 5)]
BACKLOG = "| US ID | Title |\n|---|---|\n" + "\n".join(
    f"| {us} | Story {n} |" for n, us in enumerate(US, 1)
)
SEQUENCING = (
    "| US ID | Depends on | Size | Notes |\n|---|---|---|---|\n"
    f"| {US[0]} | None | M | |\n"
    f"| {US[1]} | {US[0]} | S | |\n"
    f"| {US[2]} | {US[0]} | S | |\n"
    f"| {US[3]} | {US[2]} | S | |"
)
GROUNDED = "- Grounded on: dev-one:dev-code @ abc1234"
HISTORY = (
    "# dev-svc\n\n| Ticket | Title | Domain refs |\n| --- | --- | --- |\n"
    f"| {US[0]} | Story 1 | |\n"
)


def _mirror(hub: Path, ba_root: Path, repo_id: str) -> None:
    namespace, _, leaf = repo_id.rpartition("/")  # "mid/ba-x" nests under mid/
    doc_id = f"{leaf}-plan"
    entry = make_fed_entry(
        hub / "federation" / namespace,
        leaf,
        doc_id,
        title=f"{leaf} {planingest.TITLE_SUFFIX}",
        tags=["plan", "generated"],
    )
    shutil.rmtree(entry / doc_id)
    shutil.copytree(ba_root / ".kb" / "demo-plan", entry / doc_id)
    manifest = entry / doc_id / "_manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("demo-plan", doc_id),
        encoding="utf-8",
    )


def publish_ba(
    hub: Path, root: Path, block: str, repo_id: str = "ba-one", *, grounded=True
) -> None:
    """A BA repo with a four-story mission (US2 has a published ticket) and
    one ticket without a mission, run through plan-ingest and mirrored."""
    extra = {"## Services & order": GROUNDED} if grounded else None
    mission = mission_text(
        block,
        overrides={"## US backlog": BACKLOG, "## Sequencing": SEQUENCING},
        extra=extra,
    )
    write_repo(
        root,
        {f"{MISSION_ID}.md": mission},
        {
            f"{MISSION_ID}/{US[1]}.md": ticket_text(block),
            "TAL-1580.md": ticket_text(block, parent=None),
        },
    )
    report = planingest.run(
        root, root / ".kb", "demo", root / "missions", root / "tickets"
    )
    assert report.skipped == [], report.skipped
    _mirror(hub, root, repo_id)


def publish_svc(hub: Path, history: str = HISTORY) -> None:
    entry = make_fed_entry(hub / "federation", "dev-one", "dev-svc", sec_id="hist.x")
    (entry / "dev-svc" / "history.md").write_text(history, encoding="utf-8")


def add_symlinked_plan(repo_kb: Path, outside: Path) -> None:
    """Index a second plan document `x-plan` whose folder is a symlink to a
    copy of the first one at `outside` — a folder the snapshot does not own."""
    from strata_kb import models

    real = next(repo_kb.glob("*-plan"))
    shutil.copytree(real, outside)
    manifest = outside / "_manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(real.name, "x-plan"),
        encoding="utf-8",
    )
    try:
        (repo_kb / "x-plan").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this machine cannot create symlinks")
    index = models.load_yaml_model(repo_kb / "index.yaml", models.KBIndex)
    index.docs.append(
        models.IndexEntry(
            id="x-plan",
            title=f"x {planingest.TITLE_SUFFIX}",
            tags=["plan", "generated"],
            summary="",
        )
    )
    models.save_yaml_model(repo_kb / "index.yaml", index)


def _statuses(repos: list[planstatus.PlanRepo]) -> dict[str, str]:
    return {s.us_id: s.status for r in repos for m in r.missions for s in m.stories}


def test_hub_plans_statuses(plan_hub):
    repos, notes = planstatus.hub_plans(plan_hub)
    assert notes == []
    assert _statuses(repos) == {
        US[0]: "done",
        US[1]: "ready",
        US[2]: "to-draft",
        US[3]: "blocked",
    }
    (repo,) = repos
    assert (repo.repo, repo.doc) == ("ba-one", "ba-one-plan")
    (mission,) = repo.missions
    assert mission.mission_id == MISSION_ID
    assert mission.title == "Filter and display controlled airspace"
    assert mission.summary.startswith("Dispatchers need controlled airspace")
    assert mission.tickets == frozenset({US[1]})
    blocked = mission.stories[-1]
    assert blocked.reasons == (f"US {US[2]} not done",)
    assert mission.counts == {"done": 1, "ready": 1, "to-draft": 1, "blocked": 1}


def test_hub_plans_unparented_tickets(plan_hub):
    (repo,), _ = planstatus.hub_plans(plan_hub)
    assert repo.unparented == [
        ("TAL-1580", "TAL-1580 — Show restrictive airspace details")
    ]


def test_hub_plans_missing_svc_is_a_note(fed_hub, tmp_path):
    publish_ba(fed_hub, tmp_path / "ba-one", context_block(fed_hub))
    repos, notes = planstatus.hub_plans(HubHandle(root=fed_hub))
    assert len(notes) == 1
    assert notes[0].startswith("ba-one-plan: done: unknown (dev-svc not published")
    assert _statuses(repos)[US[0]] == "to-draft"


def test_hub_plans_without_grounded_on_is_a_note(fed_hub, tmp_path):
    publish_ba(fed_hub, tmp_path / "ba-one", context_block(fed_hub), grounded=False)
    repos, notes = planstatus.hub_plans(HubHandle(root=fed_hub))
    assert notes == ["ba-one-plan: done: unknown (no 'Grounded on:' line in a mission)"]
    assert US[0] in _statuses(repos)


def test_hub_plans_repo_filter(plan_hub, tmp_path):
    publish_ba(
        plan_hub.root, tmp_path / "ba-two", context_block(plan_hub.root), "ba-two"
    )
    both, _ = planstatus.hub_plans(plan_hub)
    assert [r.repo for r in both] == ["ba-one", "ba-two"]
    (only,), _ = planstatus.hub_plans(plan_hub, "ba-two")
    assert only.repo == "ba-two"
    assert planstatus.hub_plans(plan_hub, "nope") == ([], [])


def test_ticket_holders_and_unparented_group(plan_hub):
    ((repo, t),) = planstatus.ticket_holders(plan_hub, MISSION_ID, US[1])
    assert repo == "ba-one"
    assert t.title.startswith("TAL-1580")
    assert "## Acceptance Criteria" in t.markdown
    assert "### Acceptance Criteria" not in t.markdown
    loose = planstatus.ticket_holders(plan_hub, planstatus.TICKETS_GROUP, "TAL-1580")
    assert [r for r, _ in loose] == ["ba-one"]


@pytest.mark.parametrize(
    "repo, group, story",
    [
        ("ba-one", MISSION_ID, "M-nope"),  # unknown story
        ("ba-one", "M-other", US[1]),  # story is in another mission
        ("ba-one", MISSION_ID, US[2]),  # backlog story without a ticket
        ("nope", MISSION_ID, US[1]),
        ("ba-one", "../x", US[1]),
        ("ba-one", MISSION_ID, "a/b"),
        (None, MISSION_ID, ".."),
    ],
)
def test_ticket_holders_unknown_or_unsafe_is_empty(plan_hub, repo, group, story):
    assert planstatus.ticket_holders(plan_hub, group, story, repo) == []


def test_holders_without_repo_name_every_publisher(plan_hub, tmp_path):
    publish_ba(
        plan_hub.root, tmp_path / "ba-two", context_block(plan_hub.root), "ba-two"
    )
    assert [m.repo for m in planstatus.mission_holders(plan_hub, MISSION_ID)] == [
        "ba-one",
        "ba-two",
    ]
    assert [
        m.repo for m in planstatus.mission_holders(plan_hub, MISSION_ID, "ba-two")
    ] == ["ba-two"]
    assert planstatus.mission_holders(plan_hub, "../x") == []
    both = planstatus.ticket_holders(plan_hub, MISSION_ID, US[1])
    assert [r for r, _ in both] == ["ba-one", "ba-two"]


def test_nested_ba_leaf_is_not_served(plan_hub, tmp_path):
    publish_ba(
        plan_hub.root, tmp_path / "mid-ba", context_block(plan_hub.root), "mid/ba-x"
    )
    assert all(p.repo != "mid/ba-x" for p in planstatus.hub_plans(plan_hub)[0])
    assert not planstatus.ticket_holders(plan_hub, MISSION_ID, US[1], "mid/ba-x")


def test_plan_href_puts_the_repo_in_the_query():
    assert (
        planstatus.plan_href("mid/ba-x", "M-a", "M-a")
        == "/ui/plans/M-a?repo=mid%2Fba-x"
    )
    assert (
        planstatus.plan_href("ba", "M-a", "M-a-US1") == "/ui/plans/M-a/M-a-US1?repo=ba"
    )
    assert (
        planstatus.plan_href("ba", "tickets", "TAL-1")
        == "/ui/plans/tickets/TAL-1?repo=ba"
    )


def test_unreadable_plan_manifest_is_skipped(plan_hub):
    manifest = plan_hub.root / "federation/ba-one/ba-one-plan/_manifest.yaml"
    manifest.write_text("sections: [", encoding="utf-8")
    assert planstatus.hub_plans(plan_hub) == ([], [])


def test_section_paths_name_the_group_of_each_plan_section(plan_hub):
    paths = planstatus.section_paths(plan_hub)
    assert paths[("ba-one", "ba-one-plan", MISSION_ID)] == MISSION_ID
    assert paths[("ba-one", "ba-one-plan", US[1])] == MISSION_ID
    assert paths[("ba-one", "ba-one-plan", "TAL-1580")] == planstatus.TICKETS_GROUP


def test_a_symlinked_plan_folder_is_ignored(plan_hub, tmp_path):
    add_symlinked_plan(plan_hub.root / "federation/ba-one", tmp_path / "outside")
    repos, _ = planstatus.hub_plans(plan_hub)
    assert [r.doc for r in repos] == ["ba-one-plan"]
    assert {(r, d) for (r, d, _) in planstatus.section_paths(plan_hub)} == {
        ("ba-one", "ba-one-plan")
    }


def test_only_generated_plan_documents_are_plans():
    marked = ("ba-one — plan", ["plan", "generated"])
    assert planstatus.is_plan(*marked)
    assert not planstatus.is_plan("Release plan", ["plan", "generated"])
    assert not planstatus.is_plan("ba-one — plan", ["plan"])
    assert not planstatus.is_plan("ba-one — plan", ["generated"])
    docs = [{"id": "release-plan", "title": "Release plan", "tags": ["ops"]}]
    assert planstatus.without_plans(docs) == docs
