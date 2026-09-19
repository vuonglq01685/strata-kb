import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from strata_kb import searchdb
from strata_kb.mcp import ServerConfig
from strata_kb.web import api


@pytest.fixture
def client_factory(tmp_path):
    """Build a Starlette TestClient wired to api.build_routes for a given hub."""

    def _make(hub: str) -> TestClient:
        config = ServerConfig(kb_dir=tmp_path / ".kb", hub=hub)
        return TestClient(Starlette(routes=api.build_routes(config)))

    return _make


# --- Step 1 brief tests (verbatim) -----------------------------------------


def test_health_is_always_minimal(client_factory, fed_hub):
    """Fix round 3 (Critical): /api/health is auth-exempt, so
    TokenAuthMiddleware never meters it -- an auth-varying body here let a
    caller compare guesses against the shared secret at unmetered, full
    speed (measured: 20/20 wrong Authorization guesses -> 200, limiter never
    touched). The route no longer varies by auth or by hub state at all;
    hub_configured/hub_reachable stay available through the authenticated
    /ui and `kb doctor`."""
    client = client_factory(hub=str(fed_hub))
    assert client.get("/api/health").json() == {"status": "ok"}
    assert (
        client.get("/api/health", headers={"Authorization": "Bearer wrong"}).json()
        == {"status": "ok"}
    )


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
    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(tmp_path / "cache"))
    client = client_factory(hub=str(tmp_path / "missing-hub"))
    assert client.get("/api/docs").status_code == 503


# --- adapted regression coverage (hub-unreachable, doc/section shapes) -----


def test_health_stays_minimal_when_hub_unreachable(client_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(tmp_path / "cache2"))
    resp = client_factory(hub=str(tmp_path / "missing-hub-2")).get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


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


def test_section_level_is_case_insensitive(client_factory, fed_hub):
    """R17 (final-branch review, Important): query.normalize_level made the
    CLI and MCP tool case-insensitive on `level`, but this route still had
    its own hand-rolled `level not in ("l2", "l3")` guard — `?level=L3`
    hit 400 here while `kb get --level L3` worked. Both surfaces must agree."""
    resp = client_factory(hub=str(fed_hub)).get(
        "/api/docs/arinc-424/sections/5.3", params={"repo": "arinc-kb", "level": "L3"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["level"] == "l3"
    assert "Full raw" in body["content"]


def test_section_level_verbatim_is_still_rejected(client_factory, fed_hub):
    resp = client_factory(hub=str(fed_hub)).get(
        "/api/docs/arinc-424/sections/5.3",
        params={"repo": "arinc-kb", "level": "verbatim"},
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


def test_search_too_many_tags_400(client_factory, fed_hub):
    """F-C3 addition: an oversized client-supplied `tags` list is a caller
    error (400), not the 500 it was before searchdb.TooManyTagsError was
    handled here."""
    resp = client_factory(hub=str(fed_hub)).get(
        "/api/search",
        params={"q": "x", "tags": ",".join(f"t{i}" for i in range(101))},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "too_many_tags"


def test_api_search_tokens_describe_the_returned_text(client_factory, fed_hub):
    """M17: the REST payload carries only r.content (never r.snippet), so its
    'tokens' figure must equal count_tokens(content) alone. Reuses the
    fold-notes trick from test_query_semantic.py to force a snippet-bearing
    result -- fed_hub's stock fixture never produces one, and without it this
    assertion would pass on the pre-change code too (r.tokens ==
    count_tokens(content) whenever the snippet is empty)."""
    from strata_kb import models
    from strata_kb.federation import FederationMeta
    from strata_kb.hub import HubHandle
    from strata_kb.mdutils import count_tokens
    from strata_kb.query import search

    entry = fed_hub / "federation" / "arinc-kb"
    (entry / "arinc-424" / "ch1.raw.md").write_text(
        "## 5.3 Restrictive Airspace\n\nRaw text.\n\n"
        "### 5.3-notes Folded notes\n\nUnique fact GRYPHON42 lives here only.\n",
        encoding="utf-8",
    )
    meta_path = entry / "_meta.yaml"
    meta = models.load_yaml_model(meta_path, FederationMeta)
    meta.published_at = "2026-07-14T09:00:00+00:00"
    models.save_yaml_model(meta_path, meta)

    # Precondition (review finding 1): confirm the fixture actually produces
    # a snippet-bearing result -- same recipe/query/search() the self-guarding
    # test_query.py::test_budget_tokens_still_include_the_snippet uses, the
    # way test_web_ui.py's test_home_query_tokens_describe_the_rendered_text
    # already does -- so this test does not silently go vacuous if the recipe
    # ever stops firing.
    fixture_result = search(HubHandle(root=fed_hub), "GRYPHON42")[0]
    assert fixture_result.snippet and fixture_result.tokens != fixture_result.content_tokens

    client = client_factory(hub=str(fed_hub))
    body = client.get("/api/search", params={"q": "GRYPHON42"}).json()
    assert body["results"], body
    for r in body["results"]:
        assert r["tokens"] == count_tokens(r["content"])


def test_api_search_reports_stale_hub_note(client_factory, fed_hub, monkeypatch):
    """M17 step 5: api_search adds a "notes" key carrying stale_hub_note(hub)
    when the resolved hub is stale -- untested before this task added it.
    Faking `strata_kb.hub.resolve_hub` (the name `hub_handle` actually
    resolves, same seam test_mcp.py/test_cli_hub.py already use for this)
    is the only way to get a stale HubHandle through a real route: a
    local-path hub (what client_factory always builds) is never stale on
    its own."""
    from strata_kb import hub as hub_mod
    from strata_kb.hub import HubHandle

    monkeypatch.setattr(
        hub_mod, "resolve_hub",
        lambda hub_ref: HubHandle(root=fed_hub, stale=True, age_seconds=42.0),
    )
    client = client_factory(hub=str(fed_hub))
    body = client.get("/api/search", params={"q": "restrictive airspace"}).json()
    assert body["results"]
    assert body["notes"] == [
        "[warn] hub cache is stale (~42s) — results may lag the hub\n\n"
    ]


def test_api_search_omits_notes_key_when_hub_is_fresh(client_factory, fed_hub):
    body = client_factory(hub=str(fed_hub)).get(
        "/api/search", params={"q": "restrictive airspace"}
    ).json()
    assert body["results"]
    assert "notes" not in body


def test_search_index_busy_503(client_factory, fed_hub, monkeypatch):
    """F-C3 addition: a held index file is a 503 (retry later), not a 500."""

    def fake_search(*a, **k):
        raise searchdb.IndexBusyError("search index is in use by another process")

    monkeypatch.setattr("strata_kb.web.api.search", fake_search)
    resp = client_factory(hub=str(fed_hub)).get("/api/search", params={"q": "x"})
    assert resp.status_code == 503
    assert resp.json()["error"] == "index_busy"
