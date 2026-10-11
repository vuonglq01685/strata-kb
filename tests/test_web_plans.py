"""The Plans menu: BA missions and tickets with derived status, outside Documents."""

import re

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from strata_kb.mcp import ServerConfig
from strata_kb.serving.auth import TokenAuthMiddleware
from strata_kb.web import ui
from tests.test_planstatus import MISSION_ID, US

TOKEN = "secret-token"


def _client(hub, *, authed: bool = False) -> TestClient:
    config = ServerConfig(kb_dir=hub.root / ".kb", hub=str(hub.root))
    app = Starlette(routes=ui.build_routes(config, TOKEN))
    return TestClient(TokenAuthMiddleware(app, TOKEN) if authed else app)


def test_plans_page_lists_repo_and_mission_with_counts(plan_hub):
    resp = _client(plan_hub).get("/ui/plans")
    assert resp.status_code == 200
    assert 'href="/ui/plans/ba-one"' in resp.text
    assert f'href="/ui/plans/ba-one/{MISSION_ID}"' in resp.text
    for count in ("1 done", "1 ready", "1 not ready", "1 blocked"):
        assert count in resp.text
    assert "tickets without mission" in resp.text


def test_repo_page_lists_unparented_tickets(plan_hub):
    resp = _client(plan_hub).get("/ui/plans/ba-one")
    assert resp.status_code == 200
    assert 'href="/ui/plans/ba-one/tickets/TAL-1580"' in resp.text


def test_mission_page_shows_backlog_statuses_and_ticket_links(plan_hub):
    resp = _client(plan_hub).get(f"/ui/plans/ba-one/{MISSION_ID}")
    assert resp.status_code == 200
    text = resp.text
    for us in US:
        assert us in text
    assert ">done<" in text and ">ready<" in text
    assert ">not ready<" in text and ">blocked<" in text
    assert f"US {US[2]} not done" in text
    # only the published ticket links
    assert f'href="/ui/plans/ba-one/{MISSION_ID}/{US[1]}"' in text
    assert f"/{US[2]}" not in text.replace(f"US {US[2]}", "")
    assert "Dispatchers need controlled airspace" in text


def test_ticket_page_renders_the_ticket_body(plan_hub):
    resp = _client(plan_hub).get(f"/ui/plans/ba-one/{MISSION_ID}/{US[1]}")
    assert resp.status_code == 200
    assert "TAL-1580 — Show restrictive airspace details" in resp.text
    assert "<h2" in resp.text and "Acceptance Criteria" in resp.text
    assert "Definition of Ready" not in resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/ui/plans/nope",
        "/ui/plans/ba-one/M-nope",
        f"/ui/plans/ba-one/{MISSION_ID}/M-nope-US9",
        f"/ui/plans/ba-one/{MISSION_ID}/{US[2]}",  # backlog story, no ticket
        f"/ui/plans/ba-one/M-other/{US[1]}",
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
        "/ui/plans/ba-one",
        f"/ui/plans/ba-one/{MISSION_ID}",
        "/ui/plans/nope",
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
        "/ui/plans/ba-one",
        f"/ui/plans/ba-one/{MISSION_ID}",
        f"/ui/plans/ba-one/{MISSION_ID}/{US[1]}",
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
    assert f'href="/ui/plans/ba-one/{MISSION_ID}"' in resp.text
    assert "/ui/docs/ba-one-plan" not in resp.text


def test_hub_strings_are_escaped(plan_hub):
    l3 = plan_hub.root / "federation/ba-one/ba-one-plan" / f"{MISSION_ID}.raw.md"
    l3.write_text(
        l3.read_text(encoding="utf-8").replace(
            f"| {US[0]} | Story 1 |", f"| {US[0]} | <script>alert(1)</script> |"
        ),
        encoding="utf-8",
    )
    text = _client(plan_hub).get(f"/ui/plans/ba-one/{MISSION_ID}").text
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
