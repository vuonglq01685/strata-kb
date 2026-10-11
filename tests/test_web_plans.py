"""The Plans menu: BA missions and tickets with derived status, outside Documents."""

import re

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from strata_kb.mcp import ServerConfig
from strata_kb.serving.auth import TokenAuthMiddleware
from strata_kb.web import ui
from tests.conftest import make_fed_entry
from tests.test_planingest import context_block
from tests.test_planstatus import MISSION_ID, US, add_symlinked_plan, publish_ba

TOKEN = "secret-token"


def _client(hub, *, authed: bool = False) -> TestClient:
    config = ServerConfig(kb_dir=hub.root / ".kb", hub=str(hub.root))
    app = Starlette(routes=ui.build_routes(config, TOKEN))
    return TestClient(TokenAuthMiddleware(app, TOKEN) if authed else app)


def test_plans_page_lists_repo_and_mission_with_counts(plan_hub):
    resp = _client(plan_hub).get("/ui/plans")
    assert resp.status_code == 200
    assert 'href="/ui/plans?repo=ba-one"' in resp.text
    assert f'href="/ui/plans/{MISSION_ID}?repo=ba-one"' in resp.text
    for count in ("1 done", "1 ready", "1 not ready", "1 blocked"):
        assert count in resp.text
    assert "tickets without mission" in resp.text


def test_repo_page_lists_unparented_tickets(plan_hub):
    resp = _client(plan_hub).get("/ui/plans", params={"repo": "ba-one"})
    assert resp.status_code == 200
    assert 'href="/ui/plans/tickets/TAL-1580?repo=ba-one"' in resp.text


def test_mission_page_shows_backlog_statuses_and_ticket_links(plan_hub):
    resp = _client(plan_hub).get(f"/ui/plans/{MISSION_ID}?repo=ba-one")
    assert resp.status_code == 200
    text = resp.text
    for us in US:
        assert us in text
    assert ">done<" in text and ">ready<" in text
    assert ">not ready<" in text and ">blocked<" in text
    assert f"US {US[2]} not done" in text
    # only the published ticket links
    assert f'href="/ui/plans/{MISSION_ID}/{US[1]}?repo=ba-one"' in text
    assert f"/{US[2]}" not in text.replace(f"US {US[2]}", "")
    assert "Dispatchers need controlled airspace" in text


def test_ticket_page_renders_the_ticket_body(plan_hub):
    resp = _client(plan_hub).get(f"/ui/plans/{MISSION_ID}/{US[1]}?repo=ba-one")
    assert resp.status_code == 200
    assert "TAL-1580 — Show restrictive airspace details" in resp.text
    assert "<h2" in resp.text and "Acceptance Criteria" in resp.text
    assert "Definition of Ready" not in resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/ui/plans?repo=nope",
        "/ui/plans/M-nope",
        f"/ui/plans/{MISSION_ID}?repo=nope",
        f"/ui/plans/{MISSION_ID}/M-nope-US9",
        f"/ui/plans/{MISSION_ID}/{US[2]}",  # backlog story, no ticket
        f"/ui/plans/M-other/{US[1]}",
        f"/ui/plans/{MISSION_ID}/{US[1]}?repo=nope",
        "/ui/plans/..%2Fx",
    ],
)
def test_unknown_plan_mission_or_story_is_404(plan_hub, path):
    resp = _client(plan_hub).get(path)
    assert resp.status_code == 404
    assert "Not found" in resp.text


def test_docs_do_not_list_the_plan_document(plan_hub):
    client = _client(plan_hub)
    assert "ba-one-plan" not in client.get("/ui/docs").text
    assert "ba-one-plan" not in client.get("/ui/docs", params={"filter": "plan"}).text
    assert "icao-annex-2" in client.get("/ui/docs").text


def test_overview_and_tag_rail_skip_the_plan_document(plan_hub):
    client = _client(plan_hub)
    overview = client.get("/ui").text
    assert "ba-one-plan" not in overview
    # icao-annex-2, arinc-424 and dev-svc; the plan is not a document
    assert re.search(r"Documents</span>\s*<span class=\"value\">3<", overview)
    docs = client.get("/ui/docs").text
    assert 'data-text="generated"' not in docs  # plan-ingest's own tag


def test_left_rail_has_a_plans_link_on_every_page(plan_hub):
    client = _client(plan_hub)
    for path in (
        "/ui",
        "/ui?q=",
        "/ui/docs",
        "/ui/docs/arinc-424",
        "/ui/docs/arinc-424/5.3?repo=arinc-kb",
        "/ui/plans",
        "/ui/plans?repo=ba-one",
        f"/ui/plans/{MISSION_ID}?repo=ba-one",
        "/ui/plans?repo=nope",
    ):
        assert re.search(
            r'<a href="/ui/plans"[^>]*>Plans</a>', client.get(path).text
        ), path
    assert 'class="active">Plans</a>' in client.get("/ui/plans").text


def test_plans_require_the_same_auth_as_docs(plan_hub):
    client = _client(plan_hub, authed=True)
    docs = client.get("/ui/docs", follow_redirects=False)
    for path in (
        "/ui/plans",
        "/ui/plans?repo=ba-one",
        f"/ui/plans/{MISSION_ID}",
        f"/ui/plans/{MISSION_ID}/{US[1]}?repo=ba-one",
    ):
        resp = client.get(path, follow_redirects=False)
        assert (resp.status_code, resp.headers.get("location")) == (
            docs.status_code,
            docs.headers.get("location"),
        )
        assert resp.status_code != 200
    ok = client.get("/ui/plans", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200


def test_search_hit_in_a_plan_links_under_plans(plan_hub):
    resp = _client(plan_hub).get("/ui", params={"q": "dispatchers controlled airspace"})
    assert f'href="/ui/plans/{MISSION_ID}?repo=ba-one"' in resp.text
    assert "/ui/docs/ba-one-plan" not in resp.text


def test_hub_strings_are_escaped(plan_hub):
    l3 = plan_hub.root / "federation/ba-one/ba-one-plan" / f"{MISSION_ID}.raw.md"
    l3.write_text(
        l3.read_text(encoding="utf-8").replace(
            f"| {US[0]} | Story 1 |", f"| {US[0]} | <script>alert(1)</script> |"
        ),
        encoding="utf-8",
    )
    text = _client(plan_hub).get(f"/ui/plans/{MISSION_ID}?repo=ba-one").text
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text


def test_mission_and_ticket_without_repo_resolve_the_unique_holder(plan_hub):
    client = _client(plan_hub)
    mission = client.get(f"/ui/plans/{MISSION_ID}")
    assert mission.status_code == 200 and US[0] in mission.text
    ticket = client.get(f"/ui/plans/{MISSION_ID}/{US[1]}")
    assert ticket.status_code == 200 and "Acceptance Criteria" in ticket.text
    assert client.get("/ui/plans/tickets/TAL-1580").status_code == 200


def test_several_holders_without_repo_is_a_404_naming_them(plan_hub, tmp_path):
    publish_ba(
        plan_hub.root, tmp_path / "ba-two", context_block(plan_hub.root), "ba-two"
    )
    client = _client(plan_hub)
    for path in (f"/ui/plans/{MISSION_ID}", f"/ui/plans/{MISSION_ID}/{US[1]}"):
        resp = client.get(path)
        assert resp.status_code == 404
        assert "ba-one, ba-two" in resp.text and "?repo=" in resp.text
        assert client.get(path, params={"repo": "ba-two"}).status_code == 200


def test_nested_federation_repo_links_resolve(plan_hub, tmp_path):
    publish_ba(
        plan_hub.root, tmp_path / "mid-ba", context_block(plan_hub.root), "mid/ba-x"
    )
    client = _client(plan_hub)
    index = client.get("/ui/plans").text
    repo_link = 'href="/ui/plans?repo=mid/ba-x"'
    assert repo_link in index
    hrefs = {
        h.replace("&amp;", "&")
        for h in re.findall(r'href="(/ui/plans[^"]*repo=mid/ba-x)"', index)
    }
    assert hrefs  # repo page, mission page, tickets-without-mission
    pages = [
        "/ui/plans?repo=mid/ba-x",
        f"/ui/plans/{MISSION_ID}?repo=mid/ba-x",
        f"/ui/plans/{MISSION_ID}/{US[1]}?repo=mid/ba-x",
        "/ui/plans/tickets/TAL-1580?repo=mid/ba-x",
    ]
    for path in {*hrefs, *pages}:
        assert client.get(path).status_code == 200, path
    # a link rendered on the mission page points back to a nested ticket page
    mission = client.get(f"/ui/plans/{MISSION_ID}?repo=mid/ba-x").text
    assert f'href="/ui/plans/{MISSION_ID}/{US[1]}?repo=mid/ba-x"' in mission


def test_search_hit_in_a_nested_plan_links_with_the_encoded_repo(plan_hub, tmp_path):
    publish_ba(
        plan_hub.root, tmp_path / "mid-ba", context_block(plan_hub.root), "mid/ba-x"
    )
    resp = _client(plan_hub).get("/ui", params={"q": "dispatchers controlled airspace"})
    assert f'href="/ui/plans/{MISSION_ID}?repo=mid%2Fba-x"' in resp.text


def test_a_hand_ingested_doc_named_like_a_plan_stays_a_document(plan_hub):
    make_fed_entry(
        plan_hub.root / "federation",
        "ops-one",
        "release-plan",
        title="Release plan",
        tags=["ops"],
        l3="## 1.1 Section One\n\nZeppelin cutover checklist for releases.\n",
    )
    client = _client(plan_hub)
    assert "release-plan" in client.get("/ui/docs").text
    assert "release-plan" not in client.get("/ui/plans").text
    hit = client.get("/ui", params={"q": "zeppelin cutover"}).text
    assert "/ui/docs/release-plan" in hit
    assert "/ui/plans/" not in hit


def test_plans_ui_ignores_a_symlinked_plan_folder(plan_hub, tmp_path):
    add_symlinked_plan(plan_hub.root / "federation/ba-one", tmp_path / "outside")
    client = _client(plan_hub)
    assert client.get("/ui/plans").text.count(f"/ui/plans/{MISSION_ID}?") == 1
    assert (
        client.get(
            f"/ui/plans/{MISSION_ID}/{US[1]}", params={"repo": "ba-one"}
        ).status_code
        == 200
    )
