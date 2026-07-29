import re
from importlib import resources

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from center_kb import assetstore
from center_kb.mcp import ServerConfig
from center_kb.web import ui
from center_kb.web.auth import COOKIE_NAME, TokenAuthMiddleware
from tests.conftest import make_fed_entry

TOKEN = "secret-token"
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}

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


def _authed_client(kb_dir, hub: str, store_factory=None) -> TestClient:
    """Like _client, but wrapped in TokenAuthMiddleware.

    Only the /assets route needs this: it's the one route in this module that
    must enforce auth by default (not in EXEMPT_PATHS/EXEMPT_PREFIXES), so its
    tests need the middleware layer present to observe 401s.

    `store_factory` is a test seam threaded through to `build_routes` — it
    lets asset-store fallthrough tests inject a fake store instead of the
    real `assetstore.store_for_hub` default.
    """
    config = ServerConfig(kb_dir=kb_dir, hub=hub)
    app = TokenAuthMiddleware(
        Starlette(routes=ui.build_routes(config, TOKEN, store_factory=store_factory)),
        TOKEN,
    )
    return TestClient(app)


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


def test_ui_root_without_query_renders_overview(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui")
    assert resp.status_code == 200
    assert "Store overview" in resp.text
    assert "Review queue" in resp.text
    assert "Documents" in resp.text  # stat card


def test_overview_queue_lists_unreviewed_sections(fed_hub):
    # fed_hub fixture ships at least one non-reviewed section
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui")
    assert "badge-pending" in resp.text or "badge-summarized" in resp.text


def test_overview_stat_grid_renders_fixture_derived_counts(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui")
    assert resp.status_code == 200
    assert "stat-card" in resp.text
    # fed_hub ships 2 docs (1 section each) and demo_doc_hub adds a 3rd doc
    # (1 section) -> 3 sections total, proving the stat grid is wired to
    # real aggregation output rather than a static template value.
    assert re.search(r'Sections</span>\s*<span class="value">3</span>', resp.text)


def test_overview_queue_and_panel_labels_match_fixture(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui")
    assert resp.status_code == 200
    # both fed_hub sections default to status="summarized" (non-reviewed),
    # so both surface in the queue with repo-scoped links and §-citations.
    assert 'href="/ui/docs/arinc-424/5.3?repo=arinc-kb"' in resp.text
    assert 'href="/ui/docs/icao-annex-2/1.1?repo=icao-kb"' in resp.text
    assert "§5.3" in resp.text
    assert "§1.1" in resp.text
    # panel label counts pending+summarized (both visible queue rows are
    # "summarized" -> 2 awaiting); rail health stays pending-only (0, since
    # neither section is "pending") — the two labels must not collapse to
    # the same number.
    assert "2 sections awaiting review" in resp.text
    assert "0 sections pending" in resp.text


def test_ui_root_hub_down_shows_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    resp = _client(tmp_path, str(tmp_path / "nope")).get("/ui")
    assert resp.status_code == 200
    assert "hub offline" in resp.text


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


def test_login_failure_is_logged(fed_hub, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="center_kb.web.ui"):
        _client(fed_hub / ".kb", str(fed_hub)).post(
            "/ui/login", data={"token": "wrong"}
        )
    assert "login" in caplog.text.lower()
    # the submitted value must never be logged (it may be a near-miss token)
    assert "wrong" not in caplog.text


def test_login_rate_limited_after_repeated_failures(fed_hub):
    c = _client(fed_hub / ".kb", str(fed_hub))
    for _ in range(5):
        resp = c.post("/ui/login", data={"token": "wrong"})
        assert resp.status_code == 200
    limited = c.post("/ui/login", data={"token": "wrong"})
    assert limited.status_code == 429
    # correct token also refused while limited — limiter keys on the client,
    # a brute-forcer must not confirm a hit inside the lockout window
    still = c.post("/ui/login", data={"token": TOKEN}, follow_redirects=False)
    assert still.status_code == 429


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
    # Bare /ui now renders the Overview screen (Task 5), which spells this
    # "Hub federation" (capitalized kicker) rather than the old search
    # scope label. Route through the search screen (still lowercase) to
    # preserve the original assertion's intent.
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui", params={"q": "airspace"})
    assert "hub federation" in resp.text


def test_home_hub_unreachable_shows_message(tmp_path, monkeypatch):
    # Bare /ui now renders the Overview screen (Task 5) when the hub is
    # down, not the old search page's "Hub unreachable." results message.
    # Route through the search screen to preserve the original intent;
    # hub-down-on-overview is covered by test_ui_root_hub_down_shows_offline.
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    resp = _client(tmp_path / ".kb", str(tmp_path / "missing-hub")).get(
        "/ui", params={"q": "airspace"}
    )
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
    # RRF scores ~0.016-0.033 → "score 0.02" on every result = meaningless to
    # the reader; the match-mode badge + token count are enough
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "airspace designation"}
    )
    assert "score 0.0" not in resp.text
    assert "tk</span>" in resp.text  # token count still shown


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


def test_home_query_shows_escaped_snippet_when_present(fed_hub, monkeypatch):
    from center_kb.query import QueryResult
    from center_kb.web import ui as ui_module

    fake_result = QueryResult(
        doc_id="demo-doc", section_id="1.1", title="Airspace Records",
        score=0.42, citation="demo-doc §1.1 (Rev 1)",
        content="## 1.1 Airspace Records\n\nCondensed match.",
        tokens=5, source="local", match_mode="keyword",
        snippet="raw <b>GRYPHON42</b> context",
    )
    monkeypatch.setattr(ui_module, "search", lambda *a, **k: [fake_result])
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "airspace designation"}
    )
    assert 'class="result-snippet"' in resp.text
    assert "raw match:" in resp.text
    assert "&lt;b&gt;GRYPHON42&lt;/b&gt;" in resp.text
    assert "<b>GRYPHON42</b>" not in resp.text


def test_home_query_hides_snippet_block_when_empty(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "airspace designation"}
    )
    assert "result-snippet" not in resp.text


@pytest.mark.xfail(
    reason=(
        "style.css was rewritten to the design-token stylesheet in Task 3 "
        "(SDD web UI redesign); the old selectors it asserted "
        "(.detail, mark {}, .match-keyword, .match-semantic, 76rem max-width) "
        "were removed. Task 4+ must update these assertions to match the new "
        "markup/CSS or remove this test once the corresponding screens are rewritten."
    ),
    strict=True,
)
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


def test_asset_route_serves_png(fed_hub):
    sha = "a" * 64
    assets_dir = fed_hub / ".kb" / "somedoc" / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / f"{sha}.png").write_bytes(b"PNGDATA")
    resp = _authed_client(fed_hub / ".kb", str(fed_hub)).get(
        f"/assets/{sha}.png", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert "immutable" in resp.headers["cache-control"]
    assert resp.content == b"PNGDATA"


def test_asset_route_rejects_bad_names(fed_hub):
    client = _authed_client(fed_hub / ".kb", str(fed_hub))
    for bad in ("../../etc/passwd", "x.png", "A" * 64 + ".png", "a" * 64 + ".gif"):
        resp = client.get(f"/assets/{bad}", headers=AUTH_HEADERS)
        assert resp.status_code == 404


def test_asset_route_missing_file_404(fed_hub):
    resp = _authed_client(fed_hub / ".kb", str(fed_hub)).get(
        f"/assets/{'f' * 64}.webp", headers=AUTH_HEADERS
    )
    assert resp.status_code == 404


def test_asset_route_requires_auth(fed_hub):
    resp = _authed_client(fed_hub / ".kb", str(fed_hub)).get(
        f"/assets/{'a' * 64}.png"
    )  # no token, no cookie
    assert resp.status_code == 401


def test_asset_route_hub_unreachable_503(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    resp = _authed_client(tmp_path / ".kb", str(tmp_path / "missing-hub")).get(
        f"/assets/{'a' * 64}.png", headers=AUTH_HEADERS
    )
    assert resp.status_code == 503


def test_asset_route_second_request_hits_cache(fed_hub):
    sha = "b" * 64
    assets_dir = fed_hub / ".kb" / "somedoc" / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / f"{sha}.png").write_bytes(b"PNGDATA2")
    client = _authed_client(fed_hub / ".kb", str(fed_hub))
    first = client.get(f"/assets/{sha}.png", headers=AUTH_HEADERS)
    second = client.get(f"/assets/{sha}.png", headers=AUTH_HEADERS)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.content == b"PNGDATA2"
    assert second.content == first.content


def test_asset_route_does_not_cache_misses(fed_hub):
    sha = "c" * 64
    client = _authed_client(fed_hub / ".kb", str(fed_hub))
    miss = client.get(f"/assets/{sha}.png", headers=AUTH_HEADERS)
    assert miss.status_code == 404
    assets_dir = fed_hub / ".kb" / "somedoc" / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / f"{sha}.png").write_bytes(b"PNGDATA3")
    hit = client.get(f"/assets/{sha}.png", headers=AUTH_HEADERS)
    assert hit.status_code == 200
    assert hit.content == b"PNGDATA3"


def test_asset_route_falls_through_to_store(fed_hub, tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "hubcache"))
    sha = "9" * 64
    store = assetstore.MemoryStore()
    store.put(f"{sha}.webp", b"WEBPBYTES")
    client = _authed_client(
        fed_hub / ".kb", str(fed_hub), store_factory=lambda handle: store
    )
    resp = client.get(f"/assets/{sha}.webp", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert resp.content == b"WEBPBYTES"
    # cached on disk for the next request
    assert (
        tmp_path / "hubcache" / "asset-cache" / f"{sha}.webp"
    ).read_bytes() == b"WEBPBYTES"


def test_asset_route_store_miss_404_and_error_503(fed_hub, tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "hubcache"))

    class _Boom(assetstore.MemoryStore):
        def get(self, name):
            raise assetstore.AssetStoreError("down")

    client_miss = _authed_client(
        fed_hub / ".kb", str(fed_hub), store_factory=lambda handle: assetstore.MemoryStore()
    )
    assert (
        client_miss.get(f"/assets/{'8' * 64}.png", headers=AUTH_HEADERS).status_code
        == 404
    )
    client_err = _authed_client(
        fed_hub / ".kb", str(fed_hub), store_factory=lambda handle: _Boom()
    )
    assert (
        client_err.get(f"/assets/{'8' * 64}.png", headers=AUTH_HEADERS).status_code
        == 503
    )


def test_asset_route_no_store_behaves_as_before(fed_hub):
    client = _authed_client(fed_hub / ".kb", str(fed_hub))  # store_factory default
    assert (
        client.get(f"/assets/{'7' * 64}.png", headers=AUTH_HEADERS).status_code == 404
    )


def test_static_css_served_with_content_type(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/static/style.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")
    assert "--accent" in resp.text


def test_static_js_and_font_served(fed_hub):
    c = _client(fed_hub / ".kb", str(fed_hub))
    js = c.get("/ui/static/app.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("text/javascript")
    font = c.get("/ui/static/fonts/IBMPlexSans-Regular.woff2")
    assert font.status_code == 200
    assert font.headers["content-type"] == "font/woff2"
    assert font.content[:4] == b"wOF2"


def test_static_rejects_traversal_and_unknown_types(fed_hub):
    c = _client(fed_hub / ".kb", str(fed_hub))
    assert c.get("/ui/static/../ui.py").status_code == 404
    assert c.get("/ui/static/fonts/x.ttf").status_code == 404


def test_static_rejects_percent_encoded_traversal(fed_hub):
    # httpx normalizes literal "../" client-side before the request is ever
    # sent, so the ".." guard in static_file is never actually exercised by
    # test_static_rejects_traversal_and_unknown_types above. Percent-encoded
    # dots survive client-side normalization and Starlette decodes them back
    # to ".." in the path param, reaching the in-handler guard.
    c = _client(fed_hub / ".kb", str(fed_hub))
    assert c.get("/ui/static/%2e%2e/ui.py").status_code == 404
    # Mutation-sensitive variant: "../ui.py" resolves to a nonexistent path
    # either way (is_file() is False with or without the ".." guard), so the
    # assertion above alone would still pass if the guard were deleted. This
    # one escapes back onto a *real* file (static/style.css) via
    # fonts/../style.css, so removing the ".." guard flips this to a 200.
    resp = c.get("/ui/static/fonts/%2e%2e/style.css")
    assert resp.status_code == 404


def test_static_rejects_absolute_path_param(fed_hub):
    # A doubled leading slash makes the captured {path:path} param start
    # with "/", turning the joinpath into an absolute-path escape attempt.
    c = _client(fed_hub / ".kb", str(fed_hub))
    assert c.get("/ui/static//etc/hosts.css").status_code == 404
    # Mutation-sensitive variant: "/etc/hosts.css" doesn't exist on disk, so
    # the assertion above alone would still pass even with the leading-"/"
    # guard deleted (is_file() is False either way). pathlib's joinpath()
    # *discards* the base entirely when given an absolute second argument,
    # so an unguarded absolute param is a real arbitrary-file-read primitive
    # (restricted only by the STATIC_TYPES suffix allowlist). Point it at a
    # real .css file that exists outside static/ to prove the escape.
    real_css = str(
        resources.files("center_kb").joinpath("templates/web/static/style.css")
    )
    resp = c.get("/ui/static/" + real_css)
    assert resp.status_code == 404


def test_static_handles_name_too_long_as_404(fed_hub):
    # A pathologically long filename segment makes target.is_file() raise
    # OSError (ENAMETOOLONG on most platforms) instead of returning False.
    # The auth-exempt static route must not leak this as a 500.
    c = _client(fed_hub / ".kb", str(fed_hub))
    resp = c.get(f"/ui/static/{'a' * 301}.css")
    assert resp.status_code == 404


def test_login_page_is_standalone_no_catalog_leak(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui/login")
    assert resp.status_code == 200
    assert 'name="token"' in resp.text
    assert "Demo Document" not in resp.text  # no rail on the login page


@pytest.mark.xfail(reason="docs.html converts in Task 7", strict=True)
def test_shell_header_and_left_rail_on_docs_page(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui/docs")
    assert resp.status_code == 200
    assert "hub online" in resp.text
    assert 'id="global-search"' in resp.text
    assert "Demo Document" in resp.text  # catalog card in left rail


def test_shell_ctx_hub_down_returns_empty_catalog(tmp_path):
    config = ServerConfig(kb_dir=tmp_path / ".kb", hub=str(tmp_path / "missing-hub"))
    ctx = ui._shell_ctx(config, "overview")
    assert ctx["hub_ok"] is False
    assert ctx["repo_count"] == 0
    assert ctx["catalog"] == []
    assert ctx["tags"] == []


def test_shell_ctx_hub_up_populates_catalog_and_tags(demo_doc_hub):
    config = ServerConfig(kb_dir=demo_doc_hub / ".kb", hub=str(demo_doc_hub))
    ctx = ui._shell_ctx(config, "overview", q="foo")
    assert ctx["hub_ok"] is True
    assert ctx["screen"] == "overview"
    assert ctx["q"] == "foo"
    assert ctx["repo_count"] >= 1
    assert ctx["catalog"]  # non-empty: demo-kb:demo-doc is present
    assert "demo" in ctx["tags"]


def test_error_page_hub_down_shows_chip_and_heading(tmp_path):
    config = ServerConfig(kb_dir=tmp_path / ".kb", hub=str(tmp_path / "missing-hub"))
    resp = ui._error_page(config, 404, "Not found", "x")
    assert resp.status_code == 404
    body = resp.body.decode()
    assert "hub offline" in body  # shell chip reflects hub_ok=False
    assert "Not found" in body
