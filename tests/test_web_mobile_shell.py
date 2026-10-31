"""Mobile shell markup: tab bar, More sheet, sheet pills, compact top-bar controls."""

import re

import pytest

from tests import test_web_plans, test_web_registry, test_web_ui
from tests.test_planstatus import MISSION_ID
from tests.test_web_ui import _client

demo_doc_hub = test_web_ui.demo_doc_hub  # re-export the fixture for pytest
# registry fixtures re-exported so the admin client works here
_git_identity = test_web_registry._git_identity
registry_hub = test_web_registry.registry_hub
intake_config = test_web_registry.intake_config
pushes = test_web_registry.pushes
recording_push = test_web_registry.recording_push
make_client = test_web_registry.make_client
admin_registry_client = test_web_registry.admin_registry_client

READER = "/ui/docs/demo-doc/1.1?repo=demo-kb"


def get(hub, path):
    return _client(hub / ".kb", str(hub)).get(path).text


def _slice(text, start, end):
    i = text.index(start)
    return text[i : text.index(end, i)]


def _main_span(text):
    start = text.index('<main class="content">')
    return start, text.index("</main>", start)


def test_viewport_meta_allows_cover_and_zoom(demo_doc_hub):
    text = get(demo_doc_hub, "/ui")
    assert 'content="width=device-width, initial-scale=1, viewport-fit=cover"' in text
    assert "user-scalable" not in text and "maximum-scale" not in text


def test_tab_bar_lists_five_main_menus_in_order(demo_doc_hub):
    bar = _slice(get(demo_doc_hub, "/ui"), '<nav class="tab-bar"', "</nav>")
    hrefs = re.findall(r'href="([^"]+)"', bar)
    assert hrefs == ["/ui", "/ui/docs", "/ui/tickets", "/ui/code", "/ui/questions"]


@pytest.mark.parametrize(
    "path,active",
    [
        ("/ui", "/ui"),
        ("/ui/docs", "/ui/docs"),
        ("/ui/code", "/ui/code"),
        (READER, "/ui/docs"),
    ],
)
def test_tab_bar_marks_active_menu(demo_doc_hub, path, active):
    bar = _slice(get(demo_doc_hub, path), '<nav class="tab-bar"', "</nav>")
    assert re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', bar) == [active]


@pytest.mark.parametrize("path", ["/ui/tickets", "/ui/questions"])
def test_tab_bar_marks_active_menu_on_full_app_routes(web_client_logged_in, path):
    # /ui/tickets and /ui/questions are mounted by the full app, not ui.build_routes alone
    bar = _slice(web_client_logged_in.get(path).text, '<nav class="tab-bar"', "</nav>")
    assert re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', bar) == [path]


def test_new_shell_markup_sits_outside_main(demo_doc_hub):
    text = get(demo_doc_hub, READER)
    start, end = _main_span(text)
    for marker in [
        '<nav class="tab-bar"',
        'class="sheet-pills"',
        'id="sheet_more"',
        'id="sheet_scrim"',
    ]:
        assert not (start <= text.index(marker) < end)


@pytest.mark.parametrize(
    "path,label",
    [
        ("/ui", "Store health"),
        ("/ui?q=airspace", "Filters"),
        ("/ui/docs/demo-doc?repo=demo-kb", "Coverage"),
        (READER, "On this page"),
    ],
)
def test_right_rail_pill_label_per_page(demo_doc_hub, path, label):
    text = get(demo_doc_hub, path)
    assert re.search(
        rf'data-sheet-open="sheet_rail_right"[^>]*>\s*{re.escape(label)}\s*<', text
    )


def test_no_right_rail_pill_when_rail_block_is_empty(demo_doc_hub):
    assert 'data-sheet-open="sheet_rail_right"' not in get(demo_doc_hub, "/ui/docs")


def test_pill_row_is_marked_left_only_when_no_right_pill(demo_doc_hub):
    assert '<div class="sheet-pills" data-left-only>' in get(demo_doc_hub, "/ui/docs")
    assert "data-left-only" not in get(demo_doc_hub, READER)


def test_left_rail_pill_is_sections_on_reader_and_tags_elsewhere(demo_doc_hub):
    reader = get(demo_doc_hub, READER)
    assert re.search(
        r'data-sheet-open="sheet_rail_left"[^>]*>\s*Sections · 1\s*<', reader
    )
    docs = get(demo_doc_hub, "/ui/docs")
    assert re.search(r'data-sheet-open="sheet_rail_left"[^>]*>\s*Tags\s*<', docs)


def test_left_pill_precedes_right_pill(demo_doc_hub):
    pills = _slice(get(demo_doc_hub, READER), 'class="sheet-pills"', "</div>")
    assert pills.index('"sheet_rail_left"') < pills.index('"sheet_rail_right"')


def test_sheet_triggers_are_buttons_bound_to_existing_ids(demo_doc_hub):
    text = get(demo_doc_hub, READER)
    triggers = re.findall(r'<button[^>]*data-sheet-open="([^"]+)"[^>]*>', text)
    assert set(triggers) == {"sheet_rail_left", "sheet_rail_right", "sheet_more"}
    for tag in re.findall(r"<button[^>]*data-sheet-open=[^>]*>", text):
        assert 'type="button"' in tag and 'aria-expanded="false"' in tag
        target = re.search(r'aria-controls="([^"]+)"', tag).group(1)
        assert f'id="{target}"' in text


def test_rail_tags_keep_their_opening(demo_doc_hub):
    text = get(demo_doc_hub, READER)
    assert '<aside class="rail rail-left" id="sheet_rail_left"' in text
    assert '<aside class="rail rail-right" id="sheet_rail_right"' in text


@pytest.mark.parametrize("level", ["l2", "l3"])
def test_body_headings_cannot_collide_with_shell_ids(demo_doc_hub, level):
    # inject_heading_anchors slugs headings to [a-z0-9-], so shell ids use "_" to stay unreachable
    names = ["More", "Sheet more", "Sheet rail left", "Sheet rail right", "Sheet scrim"]
    for suffix in (".md", ".raw.md"):
        path = demo_doc_hub / "federation/demo-kb/demo-doc" / f"ch1{suffix}"
        extra = "".join(f"\n### {n}\n\ntext\n" for n in names)
        path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")
    text = (
        _client(demo_doc_hub / ".kb", str(demo_doc_hub))
        .get("/ui/docs/demo-doc/1.1", params={"level": level, "repo": "demo-kb"})
        .text
    )
    assert 'id="more"' in text  # the "More" heading really got its slug anchor
    for sheet_id in (
        "sheet_more",
        "sheet_rail_left",
        "sheet_rail_right",
        "sheet_scrim",
    ):
        assert text.count(f'id="{sheet_id}"') == 1


def test_topbar_has_compact_controls(demo_doc_hub):
    text = get(demo_doc_hub, "/ui")
    bar = _slice(text, '<header class="topbar"', "</header>")
    assert 'aria-label="hub online"' in bar
    assert re.search(
        r'<button type="button" class="topbar-btn" data-search-toggle[^>]*'
        r'aria-controls="topbar_search" aria-expanded="false"',
        bar,
    )
    assert 'id="topbar_search"' in bar
    assert re.search(
        r'<button type="button" class="topbar-btn" data-sheet-open="sheet_more"', bar
    )
    form = _slice(bar, '<form class="topbar-search"', "</form>")
    assert '<button type="button" data-search-toggle' in form


def test_more_sheet_prints_chip_titles_as_text(demo_doc_hub):
    # fed_hub is a git repo, so the commit chip renders with title "hub HEAD <sha> · <date>"
    more = _slice(get(demo_doc_hub, "/ui"), 'id="sheet_more"', "</form>")
    assert re.search(r'class="chip-detail">\s*hub HEAD ', more)
    assert 'action="/ui/logout"' in more
    # dialog semantics are added by app.js on open, so the no-JS in-flow sheet is not modal
    assert 'role="dialog"' not in more and "aria-modal" not in more


def test_desktop_topbar_chips_have_no_detail_spans(demo_doc_hub):
    bar = _slice(get(demo_doc_hub, "/ui"), '<div class="topbar-status">', "</div>")
    assert "chip-detail" not in bar


def test_more_sheet_registry_link_only_for_admin(
    demo_doc_hub, web_client, web_client_logged_in
):
    more = _slice(web_client_logged_in.get("/ui").text, 'id="sheet_more"', "</form>")
    assert 'href="/ui/registry"' in more
    anon = _slice(get(demo_doc_hub, "/ui"), 'id="sheet_more"', "</form>")
    assert 'href="/ui/registry"' not in anon


def test_noscript_fallback_hides_sheet_controls(demo_doc_hub):
    block = _slice(get(demo_doc_hub, "/ui"), "<noscript><style>", "</style></noscript>")
    assert ".sheet-pill" in block and ".topbar-btn" in block


def test_topbar_status_markup_is_byte_identical_to_pre_macro_markup():
    from strata_kb.web.templating import render

    shell = {
        "hub_ok": True,
        "pull": {"failed": False, "label": "pulled 5m ago", "title": "last pull"},
        "commit": {
            "sha": "abc1234",
            "date": "2026-10-31",
            "title": "hub HEAD abc1234 · 2026-10-31",
        },
        "repo_count": 3,
        "version": "1.2.3",
        "q": "",
        "screen": "overview",
        "menu_kind": "",
        "tree": [],
        "tree_doc": None,
        "tags": [],
        "is_admin": False,
    }
    html = render("base.html", shell=shell)
    # literal copy of what f688e9c's base.html rendered for this shell
    expected = (
        '  <div class="topbar-status">\n    \n'
        '    <span class="hub-chip hub-online"><span class="dot"></span>hub online</span>\n'
        "    \n    \n"
        '    <span class="hub-chip hub-pulled" title="last pull"><span class="dot"></span>pulled 5m ago</span>\n'
        "    \n    \n"
        '    <span class="topbar-fed" title="hub HEAD abc1234 · 2026-10-31">@abc1234 · 2026-10-31</span>\n'
        "    \n"
        '    <span class="topbar-fed">federation · 3 repos</span>\n'
        '    <span class="topbar-fed" title="strata-kb version this hub runs">strata-kb 1.2.3</span>\n'
        "  </div>"
    )
    assert expected in html


def test_data_cards_marker_on_sections(demo_doc_hub):
    text = get(demo_doc_hub, "/ui/docs/demo-doc?repo=demo-kb")
    assert 'class="panel sec-table" data-cards="sections"' in text


def test_data_cards_marker_on_stories(plan_hub):
    text = (
        test_web_plans._client(plan_hub)
        .get(f"/ui/tickets/{MISSION_ID}?repo=ba-one")
        .text
    )
    assert 'class="panel sec-table" data-cards="stories"' in text


def test_data_cards_marker_on_registry(admin_registry_client):
    text = admin_registry_client.get("/ui/registry").text
    assert 'class="sec-table" data-cards="registry"' in text
