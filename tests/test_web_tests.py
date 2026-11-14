"""The Test Report menu: `/ui/tests*` read-only pages over `<repo>-test` docs."""

import re
import shutil

import pytest

from strata_kb.serving.accounts import Accounts
from tests.test_planingest import MISSION_ID
from tests.test_testflow import STORY, _text, publish_tests

SHA = "a" * 64
REPO = "tester-one"
RD = "### RD1 — old filter broken   Story: ST-0 · TC-3\nSteps to reproduce: open\n\n"


def _publish(hub, story, *reports, repo=REPO):
    """(Re)publish `<repo>-test`: drop the earlier entry, then write it afresh."""
    shutil.rmtree(hub.root / "federation" / repo, ignore_errors=True)
    publish_tests(hub.root, repo, story, *reports)


def _main(html: str) -> str:
    return re.search(r"<main.*?</main>", html, re.S).group(0)


def _row_of(html: str, story: str) -> str:
    return next(
        r
        for r in re.findall(r'<div class="queue-row".*?</div>', html, re.S)
        if story in r
    )


def test_menu_link_on_every_page(web_client_logged_in):
    for path in ("/ui", "/ui/tickets", "/ui/questions", "/ui/tests"):
        resp = web_client_logged_in.get(path)
        assert resp.status_code == 200, path
        assert 'href="/ui/tests"' in resp.text, path
    page = web_client_logged_in.get("/ui/tests").text
    assert re.search(r'class="active">Test Report<', page)


def test_empty_state_without_test_docs(web_client_logged_in):
    page = web_client_logged_in.get("/ui/tests").text
    assert "No test reports yet" in page


def test_no_hub_is_503_not_500(web_client_logged_in, monkeypatch):
    from strata_kb.web import api

    monkeypatch.setattr(api, "hub_handle", lambda config: None)
    assert web_client_logged_in.get("/ui/tests").status_code == 503
    assert web_client_logged_in.get("/api/tests/known-failures").status_code == 503


def test_list_filters_by_status(web_client_logged_in, plan_hub):
    _publish(plan_hub, STORY, _text(STORY, 1, "FAIL", guilty=f"{STORY}.web"))
    page = lambda f: web_client_logged_in.get(f"/ui/tests?status={f}").text  # noqa: E731
    assert STORY in page("all") and "FAIL" in page("all")
    assert STORY in page("reopened")
    assert STORY not in page("closed")
    assert STORY not in page("testing")
    _publish(
        plan_hub,
        STORY,
        _text(STORY, 1, "FAIL", guilty=f"{STORY}.web"),
        _text(STORY, 2, "PASS"),
    )
    assert STORY in page("closed")
    assert STORY not in page("reopened")
    assert "R2" in _row_of(page("all"), STORY)


def test_bad_status_filter_falls_back_to_all(web_client_logged_in, plan_hub):
    _publish(plan_hub, STORY, _text(STORY, 1))
    assert STORY in web_client_logged_in.get("/ui/tests?status=nope").text


def test_regression_badge_and_filter(web_client_logged_in, plan_hub):
    _publish(plan_hub, STORY, _text(STORY, 1, "FAIL", guilty=f"{STORY}.web"))
    assert "regression" not in _row_of(
        web_client_logged_in.get("/ui/tests").text, STORY
    ).lower().replace("regression-", "")
    _publish(
        plan_hub,
        STORY,
        _text(STORY, 1, "FAIL", guilty=f"{STORY}.web").replace(
            "Regression: no", "Regression: yes"
        ),
    )
    page = web_client_logged_in.get("/ui/tests?status=regression").text
    assert STORY in page and ">regression<" in page


def test_unknown_story_is_labelled(web_client_logged_in, plan_hub):
    _publish(plan_hub, "ZZ-9", _text("ZZ-9", 1))
    row = _row_of(web_client_logged_in.get("/ui/tests").text, "ZZ-9")
    assert "unknown story" in row


def test_known_story_links_ticket(web_client_logged_in, plan_hub):
    _publish(plan_hub, STORY, _text(STORY, 1))
    row = _row_of(web_client_logged_in.get("/ui/tests").text, STORY)
    assert f"/ui/tickets/{MISSION_ID}/{STORY}?repo=ba-one" in row
    assert f"/ui/tests/{STORY}/R1" in row


def test_report_page_renders_asset_image(web_client_logged_in, plan_hub):
    text = _text(STORY, 1).replace("a.ts | |", f"a.ts | ![shot](assets/{SHA}.png) |")
    _publish(plan_hub, STORY, text)
    resp = web_client_logged_in.get(f"/ui/tests/{STORY}/R1")
    assert resp.status_code == 200
    assert (
        f'<img src="/assets/{SHA}.png"' in resp.text
        or f'src="/assets/{SHA}.png"' in resp.text
    )
    assert f"/ui/tests/{STORY}" in resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/ui/tests/NOPE-1",
        f"/ui/tests/{STORY}/R9",
        f"/ui/tests/{STORY}/R0",
        f"/ui/tests/{STORY}/X1",
        "/ui/tests/..%2Fx/R1",
        "/ui/tests/.hidden/R1",
    ],
)
def test_unknown_story_or_round_is_404(web_client_logged_in, plan_hub, path):
    _publish(plan_hub, STORY, _text(STORY, 1))
    assert web_client_logged_in.get(path).status_code == 404


def test_story_page_lists_rounds(web_client_logged_in, plan_hub):
    _publish(
        plan_hub,
        STORY,
        _text(STORY, 1, "FAIL", guilty=f"{STORY}.web"),
        _text(STORY, 2, "PASS"),
    )
    page = web_client_logged_in.get(f"/ui/tests/{STORY}").text
    assert f"/ui/tests/{STORY}/R1" in page and f"/ui/tests/{STORY}/R2" in page


def test_candidates_show_one_row_per_key(web_client_logged_in, plan_hub):
    rds = "### RD1 — filter broken   Story: ST-0 · TC-3\nSteps: open\n\n"
    kw = {
        "verdict": "FAIL",
        "regression": "size 4, passed 3, failed 1\nFailed: ST-0/TC-3",
        "rds": rds,
    }
    _publish(plan_hub, STORY, _text(STORY, 1, guilty=f"{STORY}.web", **kw))
    _publish(
        plan_hub,
        "ST-OTHER",
        _text("ST-OTHER", 1, guilty="ST-OTHER.web", date="2026-11-15", **kw),
        repo="tester-two",
    )
    page = web_client_logged_in.get("/ui/tests?status=candidates").text
    assert page.count("ST-0/TC-3") == 1
    assert "1 duplicate" in page
    api = web_client_logged_in.get("/api/tests/known-failures").json()
    assert list(api) == ["ST-0/TC-3"]
    assert api["ST-0/TC-3"]["story"] == STORY


def test_known_failures_api_empty(web_client_logged_in):
    resp = web_client_logged_in.get("/api/tests/known-failures")
    assert resp.status_code == 200 and resp.json() == {}


def test_ticket_page_shows_test_status_and_rounds(web_client_logged_in, plan_hub):
    _publish(
        plan_hub,
        STORY,
        _text(STORY, 1, "FAIL", guilty=f"{STORY}.web").replace(
            "Regression: no", "Regression: yes"
        ),
    )
    page = web_client_logged_in.get(
        f"/ui/tickets/{MISSION_ID}/{STORY}?repo=ba-one"
    ).text
    assert "reopened" in page
    assert f'href="/ui/tests/{STORY}/R1"' in page
    assert ">regression<" in page


def test_ticket_page_without_reports_has_no_test_links(web_client_logged_in, plan_hub):
    page = web_client_logged_in.get(
        f"/ui/tickets/{MISSION_ID}/{STORY}?repo=ba-one"
    ).text
    assert "/ui/tests/" not in page


def test_tester_role_can_view_not_registry(web_client, hub_dir, plan_hub):
    Accounts(hub_dir / ".kb-auth" / "users.db").add("tess", "pw-tess", "tester")
    resp = web_client.post(
        "/ui/login",
        data={"username": "tess", "password": "pw-tess"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert web_client.get("/ui/tests").status_code == 200
    assert web_client.get("/api/tests/known-failures").status_code == 200
    assert web_client.get("/ui/registry").status_code == 403
