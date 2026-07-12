from starlette.applications import Starlette
from starlette.testclient import TestClient

from center_kb.mcp import ServerConfig
from center_kb.web import ui
from center_kb.web.auth import COOKIE_NAME

TOKEN = "secret-token"


def _client(fixture_kb, hub=None):
    config = ServerConfig(kb_dir=fixture_kb, hub=hub)
    return TestClient(Starlette(routes=ui.build_routes(config, TOKEN)))


def test_login_page_renders(fixture_kb):
    resp = _client(fixture_kb).get("/ui/login")
    assert resp.status_code == 200
    assert 'name="token"' in resp.text


def test_login_correct_token_sets_cookie_and_redirects(fixture_kb):
    resp = _client(fixture_kb).post(
        "/ui/login", data={"token": TOKEN}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui"
    assert COOKIE_NAME in resp.headers.get("set-cookie", "")
    assert "httponly" in resp.headers["set-cookie"].lower()


def test_login_wrong_token_shows_error_no_cookie(fixture_kb):
    resp = _client(fixture_kb).post("/ui/login", data={"token": "wrong"})
    assert resp.status_code == 200
    assert "set-cookie" not in resp.headers
    assert "Invalid token" in resp.text


def test_home_shows_search_form(fixture_kb):
    resp = _client(fixture_kb).get("/ui")
    assert resp.status_code == 200
    assert 'name="q"' in resp.text


def test_home_with_query_renders_results(fixture_kb):
    resp = _client(fixture_kb).get("/ui", params={"q": "airspace designation"})
    assert "demo-doc" in resp.text
    assert "§1.1" in resp.text


def test_search_with_hub_is_published_only(fixture_kb, hub_worktree):
    # hub configured → the UI searches published knowledge only (hub + federation),
    # never the local working copy
    resp = _client(fixture_kb, hub=str(hub_worktree)).get(
        "/ui", params={"q": "airspace records designation"}
    )
    assert "arinc-424" in resp.text
    assert "demo-doc" not in resp.text


def test_search_without_hub_falls_back_to_local(fixture_kb):
    resp = _client(fixture_kb).get("/ui", params={"q": "airspace designation"})
    assert "demo-doc" in resp.text


def test_tag_only_search_lists_matching_docs(fixture_kb):
    resp = _client(fixture_kb).get("/ui", params={"tags": "airspace"})
    assert resp.status_code == 200
    assert "demo-doc" in resp.text
    assert 'class="chip' in resp.text


def test_tag_only_search_no_match_shows_message(fixture_kb):
    resp = _client(fixture_kb).get("/ui", params={"tags": "no-such-tag"})
    assert resp.status_code == 200
    assert "demo-doc" not in resp.text
    assert "No documents" in resp.text


def test_remote_result_links_to_doc_page_not_section(fixture_kb, hub_worktree):
    from tests.test_query_hub import _fed_entry

    _fed_entry(hub_worktree, "crew-ops", "roster-sop", "Crew roster duty limits and rest rules.")
    resp = _client(fixture_kb, hub=str(hub_worktree)).get(
        "/ui", params={"q": "crew roster duty rest"}
    )
    assert 'href="/ui/docs/roster-sop"' in resp.text
    assert 'href="/ui/docs/roster-sop/3.2"' not in resp.text


def test_docs_page_self_hub_labels_domain_docs_as_hub(fixture_kb):
    # Self-hub deployment (Dockerfile CMD: --kb /data/.kb --hub /data) — kb_dir
    # and hub.kb_dir are the SAME directory. The Browse page must label its own
    # docs the same way the search page does (source=hub, not source=local),
    # matching the "published knowledge" framing used once a hub is configured.
    resp = _client(fixture_kb, hub=str(fixture_kb.parent)).get("/ui/docs")
    assert "demo-doc" in resp.text
    assert 'class="source-badge source-hub"' in resp.text
    assert 'class="source-badge source-local"' not in resp.text


def test_docs_page_renders_tag_chips(fixture_kb):
    resp = _client(fixture_kb).get("/ui/docs")
    assert 'class="chip' in resp.text
    assert "airspace" in resp.text


def test_docs_page_lists_docs(fixture_kb):
    resp = _client(fixture_kb).get("/ui/docs")
    assert "demo-doc" in resp.text
    assert "Demo Document" in resp.text


def test_doc_page_lists_sections_with_status(fixture_kb):
    resp = _client(fixture_kb).get("/ui/docs/demo-doc")
    assert "Airspace Records" in resp.text
    assert "summarized" in resp.text


def test_doc_page_404(fixture_kb):
    assert _client(fixture_kb).get("/ui/docs/nope").status_code == 404


def test_section_page_renders_l2_with_table_and_citation(fixture_kb):
    resp = _client(fixture_kb).get("/ui/docs/demo-doc/1.1")
    assert resp.status_code == 200
    assert "demo-doc §1.1 (Rev 1)" in resp.text
    assert "<td>Prohibited</td>" in resp.text          # table rendered verbatim
    assert 'level=l3' in resp.text                     # toggle link to L3


def test_section_page_l3(fixture_kb):
    resp = _client(fixture_kb).get("/ui/docs/demo-doc/1.1", params={"level": "l3"})
    assert "Full raw text" in resp.text


def test_section_page_404(fixture_kb):
    assert _client(fixture_kb).get("/ui/docs/demo-doc/9.9").status_code == 404


def test_static_css(fixture_kb):
    resp = _client(fixture_kb).get("/ui/static/style.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")


def test_home_query_highlights_matched_keywords(fixture_kb):
    resp = _client(fixture_kb).get("/ui", params={"q": "airspace designation"})
    assert "<mark>Airspace</mark>" in resp.text
    assert "<mark>designation</mark>" in resp.text


def test_tag_only_search_has_no_highlight(fixture_kb):
    resp = _client(fixture_kb).get("/ui", params={"tags": "airspace"})
    assert "<mark>" not in resp.text


def test_home_query_shows_keyword_match_badge(fixture_kb):
    resp = _client(fixture_kb).get("/ui", params={"q": "airspace designation"})
    assert 'class="match-badge match-keyword"' in resp.text


def test_home_query_shows_semantic_match_badge_on_fallback(fixture_kb, monkeypatch):
    from center_kb.query import QueryResult
    from center_kb.web import ui as ui_module

    fake_result = QueryResult(
        doc_id="demo-doc", section_id="1.1", title="Airspace Records",
        score=0.42, citation="demo-doc §1.1 (Rev 1)",
        content="## 1.1 Airspace Records\n\nFuzzy semantic match.",
        tokens=5, source="local", match_mode="semantic",
    )
    monkeypatch.setattr(ui_module, "search", lambda *a, **k: [fake_result])
    resp = _client(fixture_kb).get("/ui", params={"q": "airspace designation"})
    assert 'class="match-badge match-semantic"' in resp.text
