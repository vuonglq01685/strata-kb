import re
from importlib import resources

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from center_kb import assetstore, models
from center_kb.mcp import ServerConfig
from center_kb.web import ui
from center_kb.web.auth import COOKIE_NAME, TokenAuthMiddleware
from tests.conftest import make_fed_entry

TOKEN = "secret-token"
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _main(resp) -> str:
    """Slice the <main> content out of a shell page, excluding the rails.

    The shell's left rail renders a catalog card per doc, tag chips, and a
    status legend on every page (see base.html/_partials/left_rail.html),
    which can shadow assertions meant to target the main content only.
    """
    text = resp.text
    start = text.index('<main class="content">')
    return text[start : text.index("</main>", start)]


def _topbar(resp) -> str:
    """Slice the topbar search form out of a shell page.

    The rail's own budget form (search.html) also emits a hidden `tags`
    input, so a page-wide substring check can pass even when the topbar
    form itself carries nothing — scope assertions about the topbar's
    hidden fields to this region instead.
    """
    text = resp.text
    start = text.index('<form class="topbar-search"')
    return text[start : text.index("</form>", start)]


def _add_section(fed_hub, repo_id: str, doc_id: str, section: models.SectionEntry) -> None:
    """Append a second section to an existing make_fed_entry manifest.

    make_fed_entry always writes exactly one section; several doc-page tests
    need a manifest with 2+ sections to prove server-side filtering actually
    excludes non-matching rows (rather than trivially passing because the
    manifest only ever had one row to begin with).
    """
    manifest_path = fed_hub / "federation" / repo_id / doc_id / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections.append(section)
    models.save_yaml_model(manifest_path, manifest)


def _append_section_body(
    fed_hub, repo_id: str, doc_id: str, file: str, sec_id: str, title: str, body: str
) -> None:
    """Append a '## <id> <title>' unit to a section's L2 (.md) and L3
    (.raw.md) files so get_section()/slice_section() can actually resolve
    content for it.

    _add_section() only appends manifest metadata; sibling sections used to
    test prev/next pager binding must also exist as real content, otherwise
    requesting that sibling directly 404s.
    """
    for suffix in (".md", ".raw.md"):
        path = fed_hub / "federation" / repo_id / doc_id / f"{file}{suffix}"
        path.write_text(
            path.read_text(encoding="utf-8") + f"\n## {sec_id} {title}\n\n{body}\n",
            encoding="utf-8",
        )


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


def test_home_bare_q_param_renders_search_screen(demo_doc_hub):
    # The left rail's nav "Search" link points at "/ui?q=" (an empty but
    # PRESENT q param) so it lands on the search screen rather than the
    # overview -- and search() must not be asked to match on "".
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui", params={"q": ""})
    assert resp.status_code == 200
    main = _main(resp)
    assert '<h1 style="font-size:22px">Search</h1>' in main
    assert "empty-state" in main
    assert "Store overview" not in resp.text


def test_home_no_params_renders_overview(demo_doc_hub):
    # A bare /ui (q param entirely absent, not just empty) still renders the
    # overview -- proves the dispatch checks for presence, not truthiness.
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui")
    assert resp.status_code == 200
    assert "Store overview" in resp.text


def test_topbar_form_preserves_tags_and_budget_on_search(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui", params={"q": "airspace", "tags": "demo", "budget": "3000"}
    )
    assert resp.status_code == 200
    topbar = _topbar(resp)
    assert '<input type="hidden" name="tags" value="demo">' in topbar
    assert '<input type="hidden" name="budget" value="3000">' in topbar


def test_topbar_form_has_no_hidden_tags_budget_on_overview(demo_doc_hub):
    # Overview (and other non-search screens) pass no raw_tags/budget to
    # _render_page, so the shell defaults stay falsy and the topbar form
    # must not carry stale/empty hidden fields.
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui")
    assert resp.status_code == 200
    assert 'name="tags"' not in resp.text
    assert 'name="budget"' not in resp.text


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
    # Route through the search screen to preserve the original intent.
    # Task 6's search.html renders the shared shell (topbar "hub offline"
    # chip) with an empty result set rather than a dedicated down-message —
    # hub-down-on-overview is covered by test_ui_root_hub_down_shows_offline.
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    resp = _client(tmp_path / ".kb", str(tmp_path / "missing-hub")).get(
        "/ui", params={"q": "airspace"}
    )
    assert resp.status_code == 200
    assert "hub offline" in resp.text


def test_tag_only_search_lists_matching_docs(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui", params={"tags": "airspace"})
    assert resp.status_code == 200
    main = _main(resp)
    assert "icao-annex-2" in main
    assert 'class="chip' in main
    assert "filtered by" in main
    # tag-browse (no q) is still a _search_screen dispatch, so the topbar
    # form must carry the tags forward same as the q-driven search screen.
    topbar = _topbar(resp)
    assert '<input type="hidden" name="tags" value="airspace">' in topbar


def test_tag_only_search_no_match_shows_message(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"tags": "no-such-tag"}
    )
    assert resp.status_code == 200
    # the shell's left-rail catalog always lists every doc (see
    # test_shell_header_and_left_rail_on_docs_page), so "icao-annex-2" can
    # legitimately appear there; what matters is that no *matching* doc
    # card renders in the main content for this tag.
    assert "doc-card" not in resp.text
    assert "No documents" in resp.text


def test_search_result_links_to_section_page_with_repo(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "restrictive airspace"}
    )
    assert 'href="/ui/docs/arinc-424/5.3?repo=arinc-kb"' in resp.text


def test_search_shows_result_card_with_status_and_score(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui", params={"q": "airspace"}
    )
    assert resp.status_code == 200
    assert "result-card" in resp.text
    assert "score-fill" in resp.text
    # fixtures' real manifest status ("summarized") -- pins the
    # (r.source, r.doc_id, r.section_id) status_map keying, not just the
    # always-present badge-mode span.
    assert "badge-summarized" in resp.text
    assert "hub federation" in resp.text  # scope note preserved


def test_search_score_normalization_top_card_is_full_width(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui", params={"q": "airspace"}
    )
    widths = re.findall(r'score-fill" style="width:(\d+)%"', resp.text)
    assert widths, "expected at least one score-fill bar"
    assert widths[0] == "100"  # top-scoring result normalizes to full width
    # fixture yields 100/98/97 -- not every bar should be full width, or the
    # normalization would be a no-op constant.
    assert any(w != "100" for w in widths)


def test_search_budget_clamped_and_echoed(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui", params={"q": "airspace", "budget": "999999"}
    )
    assert resp.status_code == 200
    assert re.search(r'name="budget"[^>]*value="8000"', resp.text)
    assert "budget 8000 tk" in resp.text


def test_search_budget_clamped_to_lower_bound(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui", params={"q": "airspace", "budget": "50"}
    )
    assert resp.status_code == 200
    assert re.search(r'name="budget"[^>]*value="200"', resp.text)


def test_search_budget_invalid_falls_back_to_default(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui", params={"q": "airspace", "budget": "abc"}
    )
    assert resp.status_code == 200
    assert re.search(r'name="budget"[^>]*value="2000"', resp.text)


def test_search_no_results_empty_state(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "zzzznotfound"}
    )
    assert "No matching section" in resp.text


def test_search_budget_form_hidden_field_preserves_query(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui", params={"q": "airspace"}
    )
    assert '<input type="hidden" name="q" value="airspace">' in resp.text
    assert "Results for “airspace”" in resp.text


def test_search_result_shows_token_count(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui", params={"q": "airspace"}
    )
    assert re.search(r'class="tk">\s*\d+ tk', resp.text)


def test_search_hub_down_shows_hub_unreachable_message(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    resp = _client(tmp_path / ".kb", str(tmp_path / "missing-hub")).get(
        "/ui", params={"q": "airspace"}
    )
    assert resp.status_code == 200
    assert "Results for" in resp.text
    assert "Hub unreachable" in resp.text
    assert "hub offline" in resp.text
    assert "No matching section" not in resp.text


def test_search_density_and_budget_controls_have_a11y_labels(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui", params={"q": "airspace"}
    )
    assert 'aria-label="Token budget"' in resp.text
    assert 'role="group" aria-label="Result density"' in resp.text
    assert re.search(
        r'data-density-btn="compact" aria-pressed="true"', resp.text
    )
    assert re.search(
        r'data-density-btn="full" aria-pressed="false"', resp.text
    )
    # expand/collapse toggle buttons start collapsed -> aria-expanded="false"
    assert re.search(r'data-toggle-card aria-expanded="false"', resp.text)


def test_docs_page_shows_repo_badge(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs")
    assert 'class="badge badge-mode"' in resp.text
    assert "arinc-kb" in resp.text
    assert "icao-kb" in resp.text


def test_docs_page_doc_links_carry_repo_param(fed_hub):
    # The left rail's catalog cards also link to /ui/docs/{id}?repo=..., so
    # scope the assertion to <main> to pin the doc-card links specifically.
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs")
    main = _main(resp)
    assert 'href="/ui/docs/arinc-424?repo=arinc-kb"' in main
    assert 'href="/ui/docs/icao-annex-2?repo=icao-kb"' in main


def test_docs_page_renders_tag_chips(fed_hub):
    # The left rail also renders a tag cloud of chips for every known tag;
    # scope to <main> so this pins the doc-card chip rendering specifically.
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs")
    main = _main(resp)
    assert 'class="chip' in main
    assert "airspace" in main


def test_docs_page_lists_docs(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui/docs")
    main = _main(resp)
    assert "demo-doc" in main
    assert "Demo Document" in main


def test_docs_page_hub_down_shows_no_tags_empty_state(tmp_path, monkeypatch):
    # Bare /ui/docs (no tags typed) with an empty/hub-down store must not
    # show the "tag spelling" copy — that variant only makes sense when the
    # visitor actually filtered by tags and got zero matches.
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    resp = _client(tmp_path / ".kb", str(tmp_path / "missing-hub")).get("/ui/docs")
    assert resp.status_code == 200
    main = _main(resp)
    assert "No documents in the store yet." in main
    assert "Ingest and publish a document to see it here." in main
    assert "tag spelling" not in main


def test_doc_page_lists_sections_with_status(demo_doc_hub):
    # The left rail's legend spells out "summarized — awaiting SME" on every
    # page regardless of this doc's actual section statuses, so a bare
    # "summarized" in resp.text substring check is trivially true. Scope to
    # <main> and assert the actual status-badge class the section row emits.
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb"}
    )
    main = _main(resp)
    assert "Airspace Records" in main
    assert "badge-summarized" in main


def test_doc_page_section_links_carry_repo_param(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/arinc-424", params={"repo": "arinc-kb"}
    )
    assert 'href="/ui/docs/arinc-424/5.3?repo=arinc-kb"' in resp.text
    assert "repo arinc-kb" in resp.text


def test_doc_page_404(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs/nope")
    assert resp.status_code == 404


def test_doc_page_ambiguous_returns_400(fed_hub):
    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/docs/arinc-424")
    assert resp.status_code == 400
    assert "dup-kb:arinc-424" in resp.text


def test_doc_page_rows_carry_data_attrs_and_token_count(demo_doc_hub):
    # Directly set a non-zero, distinctive L2 token count on the fixture
    # section (make_fed_entry never sets `tokens`, so it defaults to 0 —
    # asserting "0" alone wouldn't prove the tk cell is bound to real data).
    manifest_path = demo_doc_hub / "federation" / "demo-kb" / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].tokens = models.SectionTokens(l2=137, l3=0)
    models.save_yaml_model(manifest_path, manifest)

    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb"}
    )
    assert resp.status_code == 200
    main = _main(resp)
    assert "data-row" in main
    assert "data-status=" in main
    assert "sec-grid" in main
    assert 'class="tk">137</span>' in main


def test_doc_page_server_side_filter_matches_case_insensitively(demo_doc_hub):
    _add_section(
        demo_doc_hub, "demo-kb", "demo-doc",
        models.SectionEntry(
            id="2.1", title="Weather Minima",
            summary="Ceiling and visibility limits.",
            status="summarized", file="ch1",
        ),
    )
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb", "filter": "AIRSPACE"}
    )
    assert resp.status_code == 200
    main = _main(resp)
    assert main.count("data-row") == 1
    assert "Airspace Records" in main
    assert "Weather Minima" not in main


def test_doc_page_bogus_status_falls_back_to_all(demo_doc_hub):
    _add_section(
        demo_doc_hub, "demo-kb", "demo-doc",
        models.SectionEntry(
            id="2.1", title="Weather Minima",
            summary="Ceiling and visibility limits.",
            status="reviewed", file="ch1",
        ),
    )
    client = _client(demo_doc_hub / ".kb", str(demo_doc_hub))
    resp_all = client.get("/ui/docs/demo-doc", params={"repo": "demo-kb"})
    resp_bogus = client.get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb", "status": "bogus"}
    )
    assert resp_bogus.status_code == 200
    all_rows = _main(resp_all).count("data-row")
    assert all_rows == 2  # sanity: both fixture sections present with no filter
    assert _main(resp_bogus).count("data-row") == all_rows


def test_doc_page_rail_binds_coverage_and_files(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb"}
    )
    assert resp.status_code == 200
    # demo_doc_hub's single fixture section defaults to status="summarized"
    # (make_fed_entry's default) -> reviewed 0/1, summarized 1/1.
    assert re.search(r'<span>reviewed</span><span class="v">0 / 1</span>', resp.text)
    assert re.search(r'<span>summarized</span><span class="v">1 / 1</span>', resp.text)
    assert "_manifest.yaml" in resp.text
    assert "ch1" in resp.text  # section file name from the manifest


def test_doc_page_row_data_text_is_lowercased(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb"}
    )
    assert resp.status_code == 200
    # scoped to <main>: the rail's tag chips also carry a data-text attribute
    # (search-panel filtering), which would otherwise shadow the row's own.
    match = re.search(r'data-text="([^"]*)"', _main(resp))
    assert match, "expected a data-text attribute on the section row"
    assert match.group(1) == (
        "1.1 airspace records airspace record structure: designation, type, level."
    )


def test_doc_page_shown_label_carries_true_total(demo_doc_hub):
    # data-total must reflect the manifest's true section count (server-side),
    # since the JS filter uses it as the "N of M shown" denominator and the
    # visible <span data-row> count in the DOM can be a server-filtered
    # subset that doesn't match the real total.
    _add_section(
        demo_doc_hub, "demo-kb", "demo-doc",
        models.SectionEntry(
            id="2.1", title="Weather Minima",
            summary="Ceiling and visibility limits.",
            status="reviewed", file="ch1",
        ),
    )
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb", "status": "summarized"}
    )
    assert resp.status_code == 200
    main = _main(resp)
    assert 'data-total="2"' in main
    assert main.count("data-row") == 1  # server-side filter still narrows the rows


def test_doc_page_filter_form_has_hidden_repo_field(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb"}
    )
    assert resp.status_code == 200
    assert '<input type="hidden" name="repo" value="demo-kb">' in resp.text


def test_doc_page_filter_input_echoes_raw_case(demo_doc_hub):
    # Matching is case-insensitive, but the input's value= must echo back
    # exactly what the user typed, not the lowercased form used to match.
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb", "filter": "AIRSPACE"}
    )
    assert resp.status_code == 200
    assert 'value="AIRSPACE"' in resp.text
    assert 'value="airspace"' not in resp.text


def test_doc_page_status_hidden_field_precedes_buttons_and_marks_active(demo_doc_hub):
    # The hidden #status field only helps the JS requestSubmit() path (see
    # app.js): it must render BEFORE the status buttons in source order so
    # duplicate-key GET params still resolve to the (later) button's own
    # value on a real click / no-JS submit. Also pin that the server marks
    # the active status button with aria-pressed="true", not just the "on"
    # class.
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb", "status": "reviewed"}
    )
    assert resp.status_code == 200
    text = resp.text
    hidden_idx = text.index('<input type="hidden" name="status"')
    first_btn_idx = text.index("data-status-btn")
    assert hidden_idx < first_btn_idx
    assert re.search(r'data-status-btn="reviewed"\s+aria-pressed="true"', text)
    assert re.search(r'data-status-btn="all"\s+aria-pressed="false"', text)


def test_doc_page_server_side_status_filter(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb", "status": "reviewed"}
    )
    assert resp.status_code == 200
    # demo_doc_hub's fixture section defaults to status="summarized"
    # (make_fed_entry's default) -> filtered out server-side by "reviewed".
    main = _main(resp)
    assert "data-row" not in main
    assert "No section matches that filter." in main


def test_docs_page_cards_show_repo_and_tags(demo_doc_hub):
    # The left rail's catalog-card href also embeds the repo id
    # ("?repo=demo-kb"), so scope to <main> to pin the doc-card body text.
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui/docs")
    main = _main(resp)
    assert "doc-card" in main
    assert "demo-kb" in main
    assert "chip" in main


def test_section_page_renders_l2_with_table_and_citation(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}
    )
    assert resp.status_code == 200
    assert "demo-kb:demo-doc §1.1" in resp.text
    assert "<td>Prohibited</td>" in resp.text          # table rendered verbatim
    main = _main(resp)
    assert "level=l3" in main                          # toggle link to L3
    # scoped to <main> (not resp.text): the left rail also renders repo
    # metadata on every page, so an unscoped "repo=demo-kb" substring check
    # would pass even if the level-toggle links themselves dropped ?repo=.
    assert "level=l3&repo=demo-kb" in main             # toggle link keeps repo


def test_section_page_l3(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"level": "l3", "repo": "demo-kb"}
    )
    assert "Full raw text" in resp.text


def test_section_page_level_tabs_reflect_active_level(demo_doc_hub):
    client = _client(demo_doc_hub / ".kb", str(demo_doc_hub))

    main_l2 = _main(client.get("/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}))
    assert re.search(r'class="on"[^>]*href="[^"]*level=l2', main_l2)
    assert not re.search(r'class="on"[^>]*level=l3', main_l2)

    main_l3 = _main(
        client.get("/ui/docs/demo-doc/1.1", params={"level": "l3", "repo": "demo-kb"})
    )
    assert re.search(r'class="on"[^>]*href="[^"]*level=l3', main_l3)
    assert not re.search(r'class="on"[^>]*level=l2', main_l3)


def test_section_page_qualified_doc_id_resolves_manifest(demo_doc_hub):
    # A qualified path doc-id (repo:doc, no ?repo= query) must resolve the
    # SAME manifest as the plain form. get_section() strips the "repo:"
    # prefix internally and returns the clean id via result.doc_id, but the
    # handler used to pass the RAW (still-qualified) doc_id to
    # api.load_manifest()/the template — manifest lookup silently missed (no
    # pager, no per-level rail metadata) and the breadcrumb linked to a 404.
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-kb:demo-doc/1.1"
    )
    assert resp.status_code == 200
    # manifest was found -> rail binds real per-level entry.tokens (the
    # "Tokens L2"/"Tokens L3" rows), not the generic "Tokens (l2)" fallback
    # used when load_manifest() comes back empty.
    assert "Tokens L2" in resp.text
    main = _main(resp)
    assert '/ui/docs/demo-doc?repo=demo-kb"' in main


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


def test_section_page_new_reader_shell(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}
    )
    assert resp.status_code == 200
    assert "level-tabs" in resp.text
    assert 'id="citation"' in resp.text
    assert "level=l3" in resp.text


def test_section_page_title_xss_escaped(fed_hub):
    make_fed_entry(
        fed_hub / "federation", "demo-kb", "xss-doc",
        title="<script>alert(1)</script>", tags=[],
        summary="x", sec_id="1", sec_title="<script>alert(2)</script>",
        sec_summary="s", l2="## 1 T\n\nbody", l3="## 1 T\n\nbody",
    )
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/xss-doc/1", params={"repo": "demo-kb"}
    )
    assert "<script>alert(2)</script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


def test_section_page_prev_next_pager_links_to_siblings(demo_doc_hub):
    _add_section(
        demo_doc_hub, "demo-kb", "demo-doc",
        models.SectionEntry(id="1.2", title="Next Section", status="pending", file="ch1"),
    )
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}
    )
    main = _main(resp)
    assert '<div class="pager">' in main
    assert 'class="next" href="/ui/docs/demo-doc/1.2?repo=demo-kb"' in main
    assert "§1.2 Next Section" in main
    # 1.1 is the first section: no previous sibling, so no previous-link href
    assert '<span class="dir">← previous</span>' not in main


def test_section_page_prev_link_binds_to_previous_sibling(demo_doc_hub):
    # test_section_page_prev_next_pager_links_to_siblings only proves the
    # *next*-link branch (querying the first of 2 sections, which has no
    # previous sibling). Query the *second* section here so the ← previous
    # branch actually renders and is bound to the right sibling.
    _add_section(
        demo_doc_hub, "demo-kb", "demo-doc",
        models.SectionEntry(id="1.2", title="Weather Minima", status="pending", file="ch1"),
    )
    _append_section_body(
        demo_doc_hub, "demo-kb", "demo-doc", "ch1", "1.2", "Weather Minima",
        "Condensed weather minima content.",
    )
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.2", params={"repo": "demo-kb"}
    )
    main = _main(resp)
    assert '<div class="pager">' in main
    assert '<span class="dir">← previous</span>' in main
    assert 'href="/ui/docs/demo-doc/1.1?repo=demo-kb"' in main
    assert "§1.1" in main


def test_section_page_no_siblings_hides_pager(demo_doc_hub):
    # demo_doc_hub's demo-doc has exactly one section: no prev, no next.
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}
    )
    main = _main(resp)
    assert '<div class="pager">' not in main


def test_section_page_rail_shows_status_and_token_counts(demo_doc_hub):
    # Give L2/L3 distinct, non-zero token counts (make_fed_entry defaults
    # both to 0) so the assertions prove the rail is bound to the real
    # per-level values, not just that the row labels are present.
    manifest_path = demo_doc_hub / "federation" / "demo-kb" / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].tokens = models.SectionTokens(l2=42, l3=99)
    models.save_yaml_model(manifest_path, manifest)

    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}
    )
    text = resp.text
    assert 'class="badge badge-summarized"' in text
    assert "Tokens L2" in text
    assert "Tokens L3" in text
    assert 'Tokens L2</span><span class="v">42</span>' in text
    assert 'Tokens L3</span><span class="v">99</span>' in text


def test_section_page_rail_shows_revision_when_set(demo_doc_hub):
    manifest_path = demo_doc_hub / "federation" / "demo-kb" / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.revision = "Rev 7"
    models.save_yaml_model(manifest_path, manifest)

    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}
    )
    assert '<span>Revision</span><span class="v">Rev 7</span>' in resp.text


def test_section_page_rail_hides_revision_when_absent(demo_doc_hub):
    # demo_doc_hub's fixture manifest defaults to revision="" (make_fed_entry
    # never sets it) -> the {% if revision %} row must not render at all.
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}
    )
    assert "<span>Revision</span>" not in resp.text


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
    # Task 6 replaced the old .match-badge.match-{mode} pill with the
    # shared status.html badge styling: class="badge badge-mode", text mode.
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "airspace designation"}
    )
    assert 'class="badge badge-mode"' in resp.text
    assert ">keyword<" in resp.text


def test_result_head_hides_raw_rrf_score(fed_hub):
    # RRF scores ~0.016-0.033 → "score 0.02" on every result = meaningless to
    # the reader; the match-mode badge + token count are enough
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "airspace designation"}
    )
    assert "score 0.0" not in resp.text
    assert 'class="tk"' in resp.text  # token count still shown
    assert "score-fill" in resp.text  # relative score still shown as a bar


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
    assert 'class="badge badge-mode"' in resp.text
    assert ">semantic<" in resp.text


def test_home_query_never_renders_raw_snippet_block(fed_hub, monkeypatch):
    # Task 6's search.html dropped the separate raw-match "result-snippet"
    # panel from the old string.Template result blocks — result cards now
    # only show the rendered (already-escaped, keyword-highlighted) body via
    # md_render. HTML-escaping of arbitrary content is covered independently
    # by tests/test_web_mdrender.py; this test preserves the original
    # intent — a raw <b>GRYPHON42</b> snippet must never leak into the page
    # unescaped or otherwise — under the new markup.
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
    assert "result-snippet" not in resp.text
    assert "GRYPHON42" not in resp.text
    # test_home_query_hides_snippet_block_when_empty folded in here: both
    # covered the same "result-snippet" absence, just via a real (unmocked)
    # search vs. this monkeypatched one — the monkeypatched case subsumes it.


def test_static_css_widens_main_and_defines_new_styles(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/static/style.css")
    # the old single-column `.detail` wrapper is gone — the redesign widens
    # the reading area via the shell's 3-column grid instead of a max-width
    assert "grid-template-columns: 248px minmax(0,1fr) 292px" in resp.text
    # keyword-highlight rule (previously asserted with no test protecting it).
    # Anchored to line-start so a substring like ".brand-mark {" can't
    # trivially satisfy this the way a bare "mark {" in resp.text would.
    assert re.search(r"^mark\s*\{", resp.text, re.M)
    # design tokens from the approved redesign mock
    assert "--accent: #1349a5" in resp.text
    assert "--r-md: 8px" in resp.text


def test_section_page_wraps_content_in_reader_container(fed_hub):
    # Task 8 (SDD web UI redesign) replaced the legacy string.Template
    # `<div class="detail">` wrapper with the Jinja reader shell's
    # `<div class="reader">` / `<article class="reader-body">` markup.
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/arinc-424/5.3", params={"repo": "arinc-kb"}
    )
    assert 'class="reader"' in resp.text
    assert 'class="reader-body"' in resp.text


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
    # Windows-style escapes: drive-absolute and backslash traversal params
    # don't start with "/", so they need their own guard (":" / "\\").
    assert c.get("/ui/static/C:%5Cwin%5Cx.css").status_code == 404
    assert c.get("/ui/static/..%5C..%5Cui.py").status_code == 404


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
    assert "demo" in [t["label"] for t in ctx["tags"]]


def test_error_page_hub_down_shows_chip_and_heading(tmp_path):
    config = ServerConfig(kb_dir=tmp_path / ".kb", hub=str(tmp_path / "missing-hub"))
    resp = ui._error_page(config, 404, "Not found", "boom-42")
    assert resp.status_code == 404
    body = resp.body.decode()
    assert "hub offline" in body  # shell chip reflects hub_ok=False
    assert "<h1>Not found</h1>" in body
    assert ">404<" in body  # binds error.html's {{ code }}, not just the heading
    assert "boom-42" in body  # binds error.html's {{ message }}, not just the heading
    assert 'aria-label="Main navigation"' in body
    assert "<title>Not found — CENTER-KB</title>" in body  # binds base.html's title block


def test_app_js_ships_interactivity_hooks(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/static/app.js")
    assert resp.status_code == 200
    for marker in ("global-search", "data-toggle-card", "data-filter", "data-copy"):
        assert marker in resp.text
    # density buttons must stay in sync with aria-pressed, not just the "on" class
    assert 'setAttribute("aria-pressed"' in resp.text
    # clipboard.writeText must be feature-detected before use (undefined on
    # non-localhost http:// origins) and failures must surface visibly
    # instead of dying silently
    assert "navigator.clipboard?.writeText" in resp.text
    assert "copy failed" in resp.text
    # server-filtered doc pages (?status=/?filter=) must fall back to a real
    # form submit instead of a client-side filter that can't see rows the
    # server never sent
    assert "URLSearchParams" in resp.text
    # Enter in the filter box must bypass native implicit submission (which
    # always activates the form's first submit button, silently resetting
    # the status filter to "all") and instead resubmit the form's current
    # field values as-is via requestSubmit().
    assert "requestSubmit" in resp.text
    # hasServerFilter must NOT treat a missing/empty status or "status=all"
    # as a real server-side narrowing -- only a non-empty ?filter= or a
    # concrete non-"all" ?status= counts.
    assert '["", "all"].includes' in resp.text


def test_search_page_hides_js_only_controls_without_js(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui", params={"q": "airspace"})
    assert resp.status_code == 200
    assert "<noscript>" in resp.text
    assert "data-toggle-card" in resp.text
    assert "data-copy-text" in resp.text
    assert "data-density" in resp.text


def test_section_page_hides_copy_button_without_js(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/icao-annex-2/1.1", params={"repo": "icao-kb"}
    )
    assert resp.status_code == 200
    assert "<noscript>" in resp.text
    assert "data-copy" in resp.text


def _left_rail(resp) -> str:
    text = resp.text
    start = text.index('<aside class="rail rail-left"')
    return text[start : text.index("</aside>", start)]


def test_tag_links_toggle_on_and_off():
    from center_kb.web.ui import _tag_links
    links = _tag_links(["airspace", "icao"], ["icao"], q="air")
    by_label = {link["label"]: link for link in links}
    assert by_label["icao"]["on"] is True
    # removing the only selected tag keeps the query
    assert by_label["icao"]["href"] == "/ui?q=air"
    assert by_label["airspace"]["on"] is False
    # adding appends to the current selection
    assert by_label["airspace"]["href"] == "/ui?q=air&tags=icao%2Cairspace"


def test_tag_links_no_query_no_tags_falls_back_to_search_screen():
    from center_kb.web.ui import _tag_links
    links = _tag_links(["icao"], ["icao"], q="")
    assert links[0]["href"] == "/ui?q="


def test_rail_tag_panel_marks_selected_and_searchable(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui?q=air&tags=icao")
    rail = _left_rail(resp)
    assert "Search tags…" in rail
    assert 'class="chip on"' in rail          # selected chip highlighted
    assert "tags=icao%2Cairspace" in rail     # unselected chip adds itself
