from starlette.applications import Starlette
from starlette.testclient import TestClient

from aero_kb.mcp import ServerConfig
from aero_kb.web import ui
from aero_kb.web.auth import COOKIE_NAME

TOKEN = "secret-token"


def _client(fixture_kb):
    config = ServerConfig(kb_dir=fixture_kb, hub=None)
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
