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
from tests.test_planingest import context_block, ticket_text, write_repo
from tests.test_planstatus import _mirror

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
