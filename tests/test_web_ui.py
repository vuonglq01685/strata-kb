import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from center_kb.mcp import ServerConfig
from center_kb.web import ui
from center_kb.web.auth import COOKIE_NAME
from tests.conftest import make_fed_entry

TOKEN = "secret-token"

DEMO_TABLE = "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n| R | Restricted |"

DEMO_L2 = f"""## 1.1 Airspace Records

Condensed: airspace record structure with designation and type fields.

{DEMO_TABLE}
"""

DEMO_L3 = f"""## 1.1 Airspace Records

Full raw text about airspace records. Designation, type, multiple code, level.

{DEMO_TABLE}
"""


def _client(kb_dir, hub: str) -> TestClient:
    config = ServerConfig(kb_dir=kb_dir, hub=hub)
    return TestClient(Starlette(routes=ui.build_routes(config, TOKEN)))


@pytest.fixture
def demo_doc_hub(fed_hub):
    """fed_hub plus a 'demo-kb:demo-doc' entry carrying a table (verbatim-render check)."""
    make_fed_entry(
        fed_hub / "federation", "demo-kb", "demo-doc",
        title="Demo Document", tags=["demo", "airspace"],
        summary="Demo aviation data spec.",
        sec_id="1.1", sec_title="Airspace Records",
        sec_summary="Airspace record structure: designation, type, level.",
        l2=DEMO_L2, l3=DEMO_L3,
    )
    return fed_hub


def test_login_page_renders(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/login")
    assert resp.status_code == 200
    assert 'name="token"' in resp.text


def test_login_correct_token_sets_cookie_and_redirects(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).post(
        "/ui/login", data={"token": TOKEN}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui"
    assert COOKIE_NAME in resp.headers.get("set-cookie", "")
    assert "httponly" in resp.headers["set-cookie"].lower()


def test_login_wrong_token_shows_error_no_cookie(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).post(
        "/ui/login", data={"token": "wrong"}
    )
    assert resp.status_code == 200
    assert "set-cookie" not in resp.headers
    assert "Invalid token" in resp.text


def test_home_shows_search_form(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui")
    assert resp.status_code == 200
    assert 'name="q"' in resp.text


def test_home_with_query_renders_results(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "airspace designation"}
    )
    assert "icao-annex-2" in resp.text
    assert "§1.1" in resp.text


def test_home_scope_label_is_hub_federation(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui")
    assert "hub federation" in resp.text


def test_home_hub_unreachable_shows_message(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    resp = _client(tmp_path / ".kb", str(tmp_path / "missing-hub")).get("/ui")
    assert resp.status_code == 200
    assert "Hub unreachable" in resp.text


def test_tag_only_search_lists_matching_docs(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui", params={"tags": "airspace"})
    assert resp.status_code == 200
    assert "icao-annex-2" in resp.text
    assert 'class="chip' in resp.text


def test_tag_only_search_no_match_shows_message(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"tags": "no-such-tag"}
    )
    assert resp.status_code == 200
    assert "icao-annex-2" not in resp.text
    assert "No documents" in resp.text


def test_search_result_links_to_section_page_with_repo(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "restrictive airspace"}
    )
    assert 'href="/ui/docs/arinc-424/5.3?repo=arinc-kb"' in resp.text


def test_docs_page_shows_repo_badge(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs")
    assert 'class="source-badge source-remote"' in resp.text
    assert "arinc-kb" in resp.text
    assert "icao-kb" in resp.text


def test_docs_page_doc_links_carry_repo_param(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs")
    assert 'href="/ui/docs/arinc-424?repo=arinc-kb"' in resp.text
    assert 'href="/ui/docs/icao-annex-2?repo=icao-kb"' in resp.text


def test_docs_page_renders_tag_chips(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs")
    assert 'class="chip' in resp.text
    assert "airspace" in resp.text


def test_docs_page_lists_docs(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui/docs")
    assert "demo-doc" in resp.text
    assert "Demo Document" in resp.text


def test_doc_page_lists_sections_with_status(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb"}
    )
    assert "Airspace Records" in resp.text
    assert "summarized" in resp.text


def test_doc_page_section_links_carry_repo_param(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/arinc-424", params={"repo": "arinc-kb"}
    )
    assert 'href="/ui/docs/arinc-424/5.3?repo=arinc-kb"' in resp.text
    assert "repo: arinc-kb" in resp.text


def test_doc_page_404(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs/nope")
    assert resp.status_code == 404


def test_doc_page_ambiguous_returns_400(fed_hub):
    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs/arinc-424")
    assert resp.status_code == 400
    assert "dup-kb:arinc-424" in resp.text


def test_section_page_renders_l2_with_table_and_citation(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}
    )
    assert resp.status_code == 200
    assert "demo-kb:demo-doc §1.1" in resp.text
    assert "<td>Prohibited</td>" in resp.text          # table rendered verbatim
    assert "level=l3" in resp.text                     # toggle link to L3
    assert "repo=demo-kb" in resp.text                 # toggle link keeps repo


def test_section_page_l3(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"level": "l3", "repo": "demo-kb"}
    )
    assert "Full raw text" in resp.text


def test_remote_repo_section_page_returns_200_with_l2_content(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/icao-annex-2/1.1", params={"repo": "icao-kb"}
    )
    assert resp.status_code == 200
    assert "Condensed" in resp.text


def test_section_page_404(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/arinc-424/9.9", params={"repo": "arinc-kb"}
    )
    assert resp.status_code == 404


def test_section_page_ambiguous_returns_400(fed_hub):
    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs/arinc-424/5.3")
    assert resp.status_code == 400
    assert "dup-kb:arinc-424" in resp.text


def test_section_page_hub_unreachable_returns_503(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    resp = _client(tmp_path / ".kb", str(tmp_path / "missing-hub")).get(
        "/ui/docs/arinc-424/5.3"
    )
    assert resp.status_code == 503


def test_static_css(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/static/style.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")


def test_home_query_highlights_matched_keywords(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "airspace designation"}
    )
    assert "<mark>Airspace</mark>" in resp.text
    assert "<mark>designation</mark>" in resp.text


def test_tag_only_search_has_no_highlight(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui", params={"tags": "airspace"})
    assert "<mark>" not in resp.text


def test_home_query_shows_keyword_match_badge(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "airspace designation"}
    )
    assert 'class="match-badge match-keyword"' in resp.text


def test_result_head_hides_raw_rrf_score(fed_hub):
    # RRF score ~0.016-0.033 → "score 0.02" cho mọi kết quả = vô nghĩa với
    # người đọc; badge match-mode + token count là đủ
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "airspace designation"}
    )
    assert "score 0.0" not in resp.text
    assert "tk</span>" in resp.text  # token count vẫn hiển thị


def test_home_query_shows_semantic_match_badge_on_fallback(fed_hub, monkeypatch):
    from center_kb.query import QueryResult
    from center_kb.web import ui as ui_module

    fake_result = QueryResult(
        doc_id="demo-doc", section_id="1.1", title="Airspace Records",
        score=0.42, citation="demo-doc §1.1 (Rev 1)",
        content="## 1.1 Airspace Records\n\nFuzzy semantic match.",
        tokens=5, source="local", match_mode="semantic",
    )
    monkeypatch.setattr(ui_module, "search", lambda *a, **k: [fake_result])
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "airspace designation"}
    )
    assert 'class="match-badge match-semantic"' in resp.text


def test_static_css_widens_main_and_defines_new_styles(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/static/style.css")
    assert "max-width: 76rem" in resp.text
    assert ".detail" in resp.text
    assert "mark {" in resp.text
    assert ".match-keyword" in resp.text
    assert ".match-semantic" in resp.text


def test_section_page_wraps_content_in_detail_container(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/arinc-424/5.3", params={"repo": "arinc-kb"}
    )
    assert 'class="detail"' in resp.text
