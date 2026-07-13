import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from center_kb.mcp import ServerConfig
from center_kb.web import api


@pytest.fixture
def client_factory(tmp_path):
    """Build a Starlette TestClient wired to api.build_routes for a given hub."""

    def _make(hub: str) -> TestClient:
        config = ServerConfig(kb_dir=tmp_path / ".kb", hub=hub)
        return TestClient(Starlette(routes=api.build_routes(config)))

    return _make


# --- Step 1 brief tests (verbatim) -----------------------------------------


def test_health_reports_hub(client_factory, fed_hub):
    client = client_factory(hub=str(fed_hub))
    data = client.get("/api/health").json()
    assert data["hub_configured"] is True
    assert data["hub_reachable"] is True


def test_docs_lists_federation_with_repo(client_factory, fed_hub):
    client = client_factory(hub=str(fed_hub))
    docs = client.get("/api/docs").json()["docs"]
    assert {(d["repo"], d["id"]) for d in docs} == {
        ("arinc-kb", "arinc-424"), ("icao-kb", "icao-annex-2"),
    }


def test_search_returns_federation_content(client_factory, fed_hub):
    client = client_factory(hub=str(fed_hub))
    data = client.get("/api/search", params={"q": "restrictive airspace"}).json()
    assert data["results"][0]["citation"].startswith("arinc-kb:arinc-424")
    assert "Condensed" in data["results"][0]["content"]


def test_section_route_with_repo_param(client_factory, fed_hub):
    client = client_factory(hub=str(fed_hub))
    resp = client.get(
        "/api/docs/arinc-424/sections/5.3", params={"repo": "arinc-kb", "level": "l3"}
    )
    assert resp.status_code == 200
    assert "Full raw" in resp.json()["content"]


def test_ambiguous_doc_returns_400(client_factory, fed_hub):
    from tests.conftest import make_fed_entry

    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    client = client_factory(hub=str(fed_hub))
    resp = client.get("/api/docs/arinc-424/sections/5.3")
    assert resp.status_code == 400
    assert "dup-kb:arinc-424" in resp.json()["detail"]


def test_hub_unreachable_returns_503(client_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    client = client_factory(hub=str(tmp_path / "missing-hub"))
    assert client.get("/api/docs").status_code == 503


# --- adapted regression coverage (hub-unreachable, doc/section shapes) -----


def test_health_hub_unreachable(client_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache2"))
    data = client_factory(hub=str(tmp_path / "missing-hub-2")).get("/api/health").json()
    assert data["hub_configured"] is True
    assert data["hub_reachable"] is False


def test_doc_detail_returns_manifest_sections(client_factory, fed_hub):
    data = client_factory(hub=str(fed_hub)).get(
        "/api/docs/arinc-424", params={"repo": "arinc-kb"}
    ).json()
    assert data["id"] == "arinc-424"
    assert data["repo"] == "arinc-kb"
    ids = [s["id"] for s in data["sections"]]
    assert ids == ["5.3"]
    assert data["sections"][0]["status"] == "summarized"


def test_doc_detail_404_names_known_docs(client_factory, fed_hub):
    resp = client_factory(hub=str(fed_hub)).get("/api/docs/nope")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "doc_not_found"
    assert "arinc-kb:arinc-424" in body["detail"]


def test_section_l2_and_l3(client_factory, fed_hub):
    c = client_factory(hub=str(fed_hub))
    l2 = c.get("/api/docs/arinc-424/sections/5.3", params={"repo": "arinc-kb"}).json()
    assert l2["level"] == "l2"
    assert l2["citation"] == "arinc-kb:arinc-424 §5.3"
    assert "Condensed" in l2["content"]
    l3 = c.get(
        "/api/docs/arinc-424/sections/5.3", params={"repo": "arinc-kb", "level": "l3"}
    ).json()
    assert "Full raw" in l3["content"]


def test_section_bad_level_400(client_factory, fed_hub):
    resp = client_factory(hub=str(fed_hub)).get(
        "/api/docs/arinc-424/sections/5.3", params={"repo": "arinc-kb", "level": "l9"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_level"


def test_section_404(client_factory, fed_hub):
    resp = client_factory(hub=str(fed_hub)).get(
        "/api/docs/arinc-424/sections/9.9", params={"repo": "arinc-kb"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "section_not_found"


def test_search_missing_q_400(client_factory, fed_hub):
    resp = client_factory(hub=str(fed_hub)).get("/api/search")
    assert resp.status_code == 400
    assert resp.json()["error"] == "missing_query"


def test_search_bad_budget_400(client_factory, fed_hub):
    resp = client_factory(hub=str(fed_hub)).get(
        "/api/search", params={"q": "x", "budget": "lots"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_budget"
