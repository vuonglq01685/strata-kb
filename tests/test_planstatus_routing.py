"""`planstatus` routing: each unparented ticket goes to its target repo, `-
Blocked by:` of a ticket published in the same plan blocks it, and done is read
from the target's `-svc` history."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from strata_kb import hubapi, models, planingest, planstatus
from strata_kb.hub import HubHandle
from strata_kb.mcp import ServerConfig
from strata_kb.web import api
from tests.conftest import make_fed_entry
from tests.test_missionlint import MISSION_ID
from tests.test_planingest import (
    PARENT,
    context_block,
    mission_text,
    ticket_text,
    write_repo,
)
from tests.test_planstatus import BACKLOG, SEQUENCING, US, _mirror

DEVS = ("payments-api", "web-app")
GROUND = "- Grounded on: demo:demo-code @ c12b24f"


def _ticket(
    block: str,
    tid: str,
    *,
    target: str | None = None,
    grounded: str | None = None,
    blocked_by: str = "None",
) -> str:
    text = ticket_text(block, parent=None).replace("TAL-1580", tid)
    if target:
        text = text.replace(
            "> Revision: 1\n", f"> Revision: 1\n> Target repo: {target}\n"
        )
    text = text.replace(GROUND, grounded or "- Grounded on: none")
    return text.replace("- Blocked by: None", f"- Blocked by: {blocked_by}")


def _dev(hub: Path, repo: str, done: tuple[str, ...] = ()) -> None:
    entry = make_fed_entry(
        hub / "federation",
        repo,
        f"{repo}-svc",
        tags=["code", "curated"],
        sec_id="hist.x",
    )
    rows = "".join(f"| {tid} | t | |\n" for tid in done)
    (entry / f"{repo}-svc" / "history.md").write_text(
        f"# {repo}-svc\n\n| Ticket | Title | Domain refs |\n| --- | --- | --- |\n{rows}",
        encoding="utf-8",
    )


def _publish_code(hub: HubHandle, repo: str) -> None:
    path = hub.federation_dir / repo / "index.yaml"
    index = models.load_yaml_model(path, models.KBIndex)
    index.docs.append(
        models.IndexEntry(id=f"{repo}-code", title="code", tags=["code"], summary="")
    )
    models.save_yaml_model(path, index)


@pytest.fixture
def build(fed_hub: Path, tmp_path: Path):
    """`make(tickets, devs=DEVS, done={repo: ids})` → hub handle with a BA
    plan of unparented tickets (id -> `_ticket` kwargs) and the dev repos."""

    def make(
        tickets: dict[str, dict],
        devs: tuple[str, ...] = DEVS,
        done: dict[str, tuple[str, ...]] | None = None,
    ) -> HubHandle:
        block = context_block(fed_hub)
        root = tmp_path / "ba-x"
        write_repo(
            root,
            {},
            {f"{tid}.md": _ticket(block, tid, **kw) for tid, kw in tickets.items()},
        )
        report = planingest.run(
            root, root / ".kb", "demo", root / "missions", root / "tickets"
        )
        assert report.skipped == [], report.skipped
        _mirror(fed_hub, root, "ba-x")
        for repo in devs:
            _dev(fed_hub, repo, (done or {}).get(repo, ()))
        return HubHandle(root=fed_hub)

    return make


def _rows(hub: HubHandle, **kw):
    _, unparented, _ = planstatus.next_from_hub(hub, **kw)
    return {u.us_id: u for u in unparented}


def test_target_from_header_and_grounding(build):
    hub = build(
        {
            "T-1": {"target": "web-app"},
            "T-2": {
                "grounded": "- Grounded on: payments-api:payments-api-code @ abc1234"
            },
            "T-3": {"grounded": "- Grounded on: web-app-code @ abc1234"},
        }
    )
    _publish_code(hub, "web-app")
    rows = _rows(hub)
    assert rows["T-1"].target_repo == "web-app"
    assert rows["T-2"].target_repo == "payments-api"
    # an unqualified entry resolves through the one repo that publishes the doc
    assert rows["T-3"].target_repo == "web-app"
    assert planstatus.dev_repos(hub) == ["payments-api", "web-app"]


def test_no_target_with_two_dev_repos_is_blocked(build):
    row = _rows(build({"T-1": {}}))["T-1"]
    assert (row.status, row.reasons, row.target_repo) == (
        "blocked",
        ("no target repo",),
        None,
    )


def test_single_dev_repo_routes_legacy_tickets(build):
    hub = build({"T-1": {}, "T-2": {}}, devs=("web-app",), done={"web-app": ("T-2",)})
    rows = _rows(hub)
    assert {k: (r.target_repo, r.status, r.reasons) for k, r in rows.items()} == {
        "T-1": ("web-app", "ready", ()),
        "T-2": ("web-app", "done", ()),
    }


def test_unknown_target_is_blocked(build):
    row = _rows(build({"T-1": {"target": "ghost"}}))["T-1"]
    assert (row.status, row.reasons, row.target_repo) == (
        "blocked",
        ("target ghost is not a dev repo on the hub",),
        "ghost",
    )


def test_done_read_from_target_svc(build):
    hub = build(
        {"T-1": {"target": "web-app"}, "T-2": {"target": "payments-api"}},
        done={"web-app": ("T-1", "T-2")},
    )
    rows = _rows(hub)
    assert rows["T-1"].status == "done"
    assert rows["T-2"].status == "ready"


def test_blocked_by_published_sibling_blocks_until_done(build):
    hub = build(
        {
            "T-1": {"target": "web-app"},
            "T-2": {"target": "web-app", "blocked_by": "T-1 — needs the API"},
        }
    )
    row = _rows(hub)["T-2"]
    assert (row.status, row.reasons) == ("blocked", ("blocked by T-1 (not done)",))


def test_blocked_by_published_sibling_unblocks_when_done(build):
    hub = build(
        {
            "T-1": {"target": "web-app"},
            "T-2": {"target": "web-app", "blocked_by": "T-1 — needs the API"},
        },
        done={"web-app": ("T-1",)},
    )
    rows = _rows(hub)
    assert (rows["T-1"].status, rows["T-2"].status) == ("done", "ready")


@pytest.mark.parametrize("blocked_by", ["ABC-123 — vendor", "the vendor API"])
def test_blocked_by_jira_key_or_prose_never_blocks(build, blocked_by):
    hub = build({"T-1": {"target": "web-app", "blocked_by": blocked_by}})
    assert _rows(hub)["T-1"].status == "ready"


def test_dependency_cycle_blocks_both(build):
    hub = build(
        {
            "T-1": {"target": "web-app", "blocked_by": "T-2 — x"},
            "T-2": {"target": "web-app", "blocked_by": "T-1 — y"},
        }
    )
    rows = _rows(hub)
    assert rows["T-1"].reasons == ("dependency cycle: T-1 → T-2 → T-1",)
    assert rows["T-2"].reasons == ("dependency cycle: T-2 → T-1 → T-2",)
    assert {r.status for r in rows.values()} == {"blocked"}


def test_for_repo_filters_rows(build):
    hub = build({"T-1": {"target": "web-app"}, "T-2": {"target": "payments-api"}})
    assert set(_rows(hub, for_repo="web-app")) == {"T-1"}
    assert set(_rows(hub)) == {"T-1", "T-2"}


def test_hubapi_story_tolerates_missing_target_repo():
    row = {
        "us_id": "T-1",
        "mission_id": "",
        "title": "t",
        "status": "ready",
        "reasons": [],
        "depends_on": [],
    }
    assert hubapi._story(row).target_repo is None
    assert hubapi._story({**row, "target_repo": "web-app"}).target_repo == "web-app"


def test_plan_api_passes_for_repo(build, fed_hub):
    build({"T-1": {"target": "web-app"}, "T-2": {"target": "payments-api"}})
    config = ServerConfig(kb_dir=fed_hub / ".kb", hub=str(fed_hub))
    client = TestClient(Starlette(routes=api.build_routes(config)))

    body = client.get("/api/plan/next", params={"for_repo": "web-app"}).json()
    assert [u["us_id"] for u in body["unparented"]] == ["T-1"]
    assert body["unparented"][0]["target_repo"] == "web-app"


def _code_only_dev(hub: Path, repo: str) -> None:
    """A Dev repo that publishes `<repo>-code` but no `-svc` yet."""
    make_fed_entry(hub / "federation", repo, f"{repo}-code", tags=["code", "generated"])


def _mission_plan(
    fed_hub: Path, tmp_path: Path, ticket_target: str, loose: dict[str, dict]
) -> None:
    """BA plan whose mission is grounded on payments-api, with one published
    story ticket (US2) targeting `ticket_target`, plus unparented tickets."""
    block = context_block(fed_hub)
    root = tmp_path / "ba-x"
    grounded = "- Grounded on: payments-api:payments-api-code @ abc1234"
    mission = mission_text(
        block,
        overrides={"## US backlog": BACKLOG, "## Sequencing": SEQUENCING},
        extra={"## Services & order": grounded},
    )
    story = _ticket(block, US[1], target=ticket_target).replace(
        "> Revision: 1\n", f"> Revision: 1\n{PARENT}\n", 1
    )
    write_repo(
        root,
        {f"{MISSION_ID}.md": mission},
        {
            f"{MISSION_ID}/{US[1]}.md": story,
            **{f"{t}.md": _ticket(block, t, **kw) for t, kw in loose.items()},
        },
    )
    report = planingest.run(
        root, root / ".kb", "demo", root / "missions", root / "tickets"
    )
    assert report.skipped == [], report.skipped
    _mirror(fed_hub, root, "ba-x")


def test_explicit_target_with_unpublished_svc_is_not_done_from_mission(
    fed_hub, tmp_path
):
    _mission_plan(fed_hub, tmp_path, "web-app", {"T-1": {"target": "web-app"}})
    _code_only_dev(fed_hub, "web-app")  # web-app-svc not published
    _dev(fed_hub, "payments-api", ("T-1", US[1]))  # the mission's svc lists both
    hub = HubHandle(root=fed_hub)

    stories, unparented, notes = planstatus.next_from_hub(hub)

    (row,) = unparented
    assert (row.status, row.reasons) == ("ready", ("done: unknown",))
    assert {s.us_id: s.status for s in stories}[US[1]] != "done"
    assert "ba-x-plan: done: unknown (web-app-svc not published)" in notes


def test_mission_story_target_and_done_come_from_its_ticket(fed_hub, tmp_path):
    _mission_plan(fed_hub, tmp_path, "web-app", {})
    _dev(fed_hub, "web-app", (US[1],))
    _dev(fed_hub, "payments-api", (US[0],))
    hub = HubHandle(root=fed_hub)

    stories, _, _ = planstatus.next_from_hub(hub)

    by_id = {s.us_id: s for s in stories}
    assert (by_id[US[1]].target_repo, by_id[US[1]].status) == ("web-app", "done")
    # no published ticket: no target, mission-level done (payments-api-svc)
    assert (by_id[US[0]].target_repo, by_id[US[0]].status) == (None, "done")
    assert by_id[US[2]].target_repo is None
    assert planstatus.next_from_hub(hub, for_repo="web-app")[0] == [by_id[US[1]]]


def test_mission_story_not_done_in_other_targets_svc(fed_hub, tmp_path):
    _mission_plan(fed_hub, tmp_path, "web-app", {})
    _dev(fed_hub, "web-app")  # published, does not list the story
    _dev(fed_hub, "payments-api", (US[1],))  # the mission's svc does
    stories, _, _ = planstatus.next_from_hub(HubHandle(root=fed_hub))
    assert {s.us_id: s.status for s in stories}[US[1]] == "ready"


def test_zero_dev_repos_keep_explicit_target_without_blocking(build):
    hub = build({"T-1": {"target": "web-app"}, "T-2": {}}, devs=())
    rows = _rows(hub)
    assert (rows["T-1"].target_repo, rows["T-1"].status) == ("web-app", "ready")
    assert (rows["T-2"].target_repo, rows["T-2"].status) == (None, "ready")


@pytest.mark.parametrize(
    "blocked_by", ["T-1, T-2 — both", "T-1 T-2", "\n  - T-1\n  - T-2 — both"]
)
def test_blocked_by_lists_block_on_every_published_id(build, blocked_by):
    hub = build(
        {
            "T-1": {"target": "web-app"},
            "T-2": {"target": "web-app"},
            "T-3": {"target": "web-app", "blocked_by": blocked_by},
        },
        done={"web-app": ("T-1",)},
    )
    row = _rows(hub)["T-3"]
    assert (row.status, row.reasons) == ("blocked", ("blocked by T-2 (not done)",))


@pytest.mark.parametrize("target", [None, "ghost"])
def test_mission_story_ticket_without_routable_target_is_blocked(
    fed_hub, tmp_path, target
):
    _mission_plan(fed_hub, tmp_path, target or "", {})
    _dev(fed_hub, "web-app")
    _dev(fed_hub, "payments-api")
    stories, _, _ = planstatus.next_from_hub(HubHandle(root=fed_hub))
    row = {s.us_id: s for s in stories}[US[1]]
    assert row.status == "blocked"
    assert row.reasons == (
        ("no target repo",)
        if target is None
        else (f"target {target} is not a dev repo on the hub",)
    )
