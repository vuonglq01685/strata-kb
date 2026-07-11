from starlette.applications import Starlette
from starlette.testclient import TestClient

from aero_kb.mcp import ServerConfig
from aero_kb.web import api


def _client(fixture_kb, hub=None):
    config = ServerConfig(kb_dir=fixture_kb, hub=hub)
    return TestClient(Starlette(routes=api.build_routes(config)))


def test_health_no_auth_needed_shape(fixture_kb):
    resp = _client(fixture_kb).get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "hub_configured": False}


def test_docs_lists_local_index(fixture_kb):
    data = _client(fixture_kb).get("/api/docs").json()
    assert data["docs"][0]["id"] == "demo-doc"
    assert data["docs"][0]["source"] == "local"
    assert data["docs"][0]["tags"] == ["demo", "airspace"]


def test_doc_detail_returns_manifest_sections(fixture_kb):
    data = _client(fixture_kb).get("/api/docs/demo-doc").json()
    assert data["id"] == "demo-doc"
    assert data["revision"] == "Rev 1"
    ids = [s["id"] for s in data["sections"]]
    assert ids == ["1.1", "1.2"]
    assert data["sections"][0]["status"] == "summarized"


def test_doc_detail_404_names_known_docs(fixture_kb):
    resp = _client(fixture_kb).get("/api/docs/nope")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "doc_not_found"
    assert "demo-doc" in body["detail"]


def test_section_l2_and_l3(fixture_kb):
    c = _client(fixture_kb)
    l2 = c.get("/api/docs/demo-doc/sections/1.1").json()
    assert l2["level"] == "l2"
    assert l2["citation"] == "demo-doc §1.1 (Rev 1)"
    assert "Condensed" in l2["content"]
    l3 = c.get("/api/docs/demo-doc/sections/1.1", params={"level": "l3"}).json()
    assert "Full raw text" in l3["content"]


def test_section_bad_level_400(fixture_kb):
    resp = _client(fixture_kb).get("/api/docs/demo-doc/sections/1.1", params={"level": "l9"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_level"


def test_section_404(fixture_kb):
    resp = _client(fixture_kb).get("/api/docs/demo-doc/sections/9.9")
    assert resp.status_code == 404
    assert resp.json()["error"] == "section_not_found"


def test_search_returns_results_with_citation(fixture_kb):
    data = _client(fixture_kb).get("/api/search", params={"q": "airspace designation"}).json()
    assert data["query"] == "airspace designation"
    assert data["results"][0]["doc_id"] == "demo-doc"
    assert data["results"][0]["citation"].startswith("demo-doc §")


def test_search_missing_q_400(fixture_kb):
    resp = _client(fixture_kb).get("/api/search")
    assert resp.status_code == 400
    assert resp.json()["error"] == "missing_query"


def test_search_bad_budget_400(fixture_kb):
    resp = _client(fixture_kb).get("/api/search", params={"q": "x", "budget": "lots"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_budget"


def test_docs_includes_hub_and_federation(fixture_kb, hub_worktree):
    data = _client(fixture_kb, hub=str(hub_worktree)).get("/api/docs").json()
    by_id = {d["id"]: d for d in data["docs"]}
    assert by_id["demo-doc"]["source"] == "local"
    assert by_id["arinc-424"]["source"] == "hub"
