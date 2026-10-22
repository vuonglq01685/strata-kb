"""Claims on the Ticket menu: badges, the holder line and the admin Release."""

import contextlib
import re
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from strata_kb.serving.accounts import Accounts
from strata_kb.serving.config import ServerConfig
from strata_kb.ticketclaim import ClaimStore, claims_db_path
from strata_kb.web import planui
from strata_kb.web.app import create_app
from tests.test_planstatus import MISSION_ID, US

REPO = "ba-one"
TICKET = US[1]  # the story with a published ticket
PAGE = f"/ui/tickets/{MISSION_ID}/{TICKET}?repo={REPO}"
RELEASE = f"/ui/tickets/{MISSION_ID}/{TICKET}/release?repo={REPO}"
PR = "https://github.com/acme/web/pull/7"


@pytest.fixture
def make_client(plan_hub, token):
    with contextlib.ExitStack() as stack:

        def make() -> TestClient:
            hub = str(plan_hub.root)
            config = ServerConfig(kb_dir=plan_hub.root / ".kb", hub=hub)
            return stack.enter_context(TestClient(create_app(config, token)))

        yield make


def _login(client: TestClient, username: str, password: str) -> TestClient:
    resp = client.post(
        "/ui/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    return client


@pytest.fixture
def admin_client(make_client, admin_user):
    return _login(make_client(), *admin_user)


@pytest.fixture
def dev_client(make_client, plan_hub):
    password = secrets.token_urlsafe(12)
    Accounts(plan_hub.root / ".kb-auth" / "users.db").add("dev1", password, "dev")
    return _login(make_client(), "dev1", password)


@pytest.fixture
def store(plan_hub) -> ClaimStore:
    return ClaimStore(claims_db_path(plan_hub.root))


def _take(store: ClaimStore, holder: str = "a@m1"):
    claim, _ = store.take(REPO, TICKET, holder)
    return claim


def _token_of(client: TestClient) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', client.get(PAGE).text)
    assert match, "no csrf field on the ticket page"
    return match.group(1)


def _release(client: TestClient, claim_id: int, reason: str = "stuck", **extra):
    fields = {"csrf": _token_of(client), "claim_id": claim_id, "reason": reason}
    fields.update(extra)
    return client.post(RELEASE, data=fields, follow_redirects=False)


def _post(client: TestClient, csrf: str, claim_id: int, reason: str = "stuck"):
    data = {"csrf": csrf, "claim_id": claim_id, "reason": reason}
    return client.post(RELEASE, data=data, follow_redirects=False)


def test_claim_badge_per_phase():
    def claim(phase="design", state="active", stop_reason=""):
        return planui.Claim(
            1,
            REPO,
            TICKET,
            "h",
            phase,
            state,
            "",
            stop_reason,
            "",
            "",
            None,
            None,
            None,
        )

    assert planui.claim_badge(None) is None
    for phase in ("claimed", "design", "plan", "execute", "handover", "waiting-qa"):
        assert planui.claim_badge(claim(phase)) == "In progress"
    assert planui.claim_badge(claim("review")) == "In review"
    assert planui.claim_badge(claim("publishing")) == "Publishing"
    stopped = claim("execute", "stopped", "ci-red")
    assert planui.claim_badge(stopped) == "Stopped: ci-red"


def test_ticket_page_shows_holder_line(admin_client, store):
    _take(store)
    text = admin_client.get(PAGE).text
    assert "In progress" in text
    assert "Taken by a@m1" in text
    assert "claimed" in text and "updated" in text


def test_review_badge_links_pr(admin_client, store, plan_hub):
    claim, token = store.take(REPO, TICKET, "a@m1")
    store.update(claim.id, token, phase="review", pr=PR)
    text = admin_client.get(PAGE).text
    assert "In review" in text
    assert f'<a href="{PR}"' in text


def test_non_https_pr_is_not_linked(admin_client, store, plan_hub):
    _take(store)
    with sqlite3.connect(claims_db_path(plan_hub.root)) as conn:
        conn.execute("UPDATE claims SET phase = 'review', pr = 'javascript:alert(1)'")
    text = admin_client.get(PAGE).text
    assert 'href="javascript' not in text


def test_holder_is_escaped(admin_client, store):
    store.take(REPO, TICKET, "<script>alert(1)</script>@m1")
    text = admin_client.get(PAGE).text
    assert "<script>alert(1)" not in text
    assert "&lt;script&gt;alert(1)" in text


def test_stopped_badge(admin_client, store):
    claim, token = store.take(REPO, TICKET, "a@m1")
    store.update(claim.id, token, state="stopped", stop_reason="ci-red")
    assert "Stopped: ci-red" in admin_client.get(PAGE).text


def test_list_page_badges(admin_client, store):
    _take(store)
    mission = admin_client.get(f"/ui/tickets/{MISSION_ID}?repo={REPO}").text
    assert "In progress" in mission
    other = store.take(REPO, "TAL-1580", "b@m2")[0]
    assert other.ticket == "TAL-1580"
    repo_page = admin_client.get(f"/ui/tickets?repo={REPO}").text
    assert "In progress" in repo_page


def test_unclaimed_pages_have_no_badge(admin_client):
    for path in (PAGE, f"/ui/tickets/{MISSION_ID}?repo={REPO}"):
        assert "In progress" not in admin_client.get(path).text


def test_admin_sees_release_and_releases(admin_client, store, admin_user):
    claim = _take(store)
    page = admin_client.get(PAGE).text
    assert "/release?repo=" in page
    assert ">Release<" in page
    resp = _release(admin_client, claim.id, "owner on leave")
    assert resp.status_code == 303
    assert resp.headers["location"].startswith(f"/ui/tickets/{MISSION_ID}/{TICKET}")
    assert store.held(REPO, TICKET) == []
    closed = store.last_closed(REPO, TICKET)
    assert closed.closed_by == admin_user[0]
    assert closed.close_reason == "admin: owner on leave"


def test_release_requires_reason(admin_client, store):
    claim = _take(store)
    for reason in ("", "   ", "x" * 1001):
        assert _release(admin_client, claim.id, reason).status_code == 400
    assert len(store.held(REPO, TICKET)) == 1


def test_release_of_a_stale_claim_id_is_409(admin_client, store):
    claim = _take(store)
    csrf = _token_of(admin_client)
    assert _post(admin_client, csrf, claim.id + 99).status_code == 409
    assert len(store.held(REPO, TICKET)) == 1
    assert _post(admin_client, csrf, claim.id).status_code == 303
    assert _post(admin_client, csrf, claim.id).status_code == 409


def test_dev_role_no_button_and_403(dev_client, store):
    claim = _take(store)
    assert "Release" not in dev_client.get(PAGE).text
    resp = dev_client.post(
        RELEASE,
        data={"csrf": "x", "claim_id": claim.id, "reason": "r"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert len(store.held(REPO, TICKET)) == 1


def test_bearer_post_403(make_client, store, token):
    claim = _take(store)
    resp = make_client().post(
        RELEASE,
        data={"csrf": "x", "claim_id": claim.id, "reason": "r"},
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert len(store.held(REPO, TICKET)) == 1


def test_bad_csrf_403(admin_client, store):
    claim = _take(store)
    resp = _release(admin_client, claim.id, csrf="nope")
    assert resp.status_code == 403
    assert len(store.held(REPO, TICKET)) == 1


def test_last_closed_shown(admin_client, store, admin_user):
    claim = _take(store)
    assert _release(admin_client, claim.id, "wrong owner").status_code == 303
    text = admin_client.get(PAGE).text
    assert f"Released by {admin_user[0]} — wrong owner" in text
    assert "Taken by" not in text


def test_expired_claim_shows_as_last_closed(plan_hub, make_client, admin_user):
    clock = [datetime.now(UTC) - timedelta(days=1)]
    old = ClaimStore(claims_db_path(plan_hub.root), ttl=60, now=lambda: clock[0])
    old.take(REPO, TICKET, "a@m1")
    text = _login(make_client(), *admin_user).get(PAGE).text
    assert "Taken by" not in text
    assert "Expired" in text and "a@m1" in text


def test_broken_claim_store_renders_notice(admin_client, plan_hub):
    db = claims_db_path(plan_hub.root)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.mkdir()
    for path in (
        PAGE,
        f"/ui/tickets/{MISSION_ID}?repo={REPO}",
        f"/ui/tickets?repo={REPO}",
    ):
        resp = admin_client.get(path)
        assert resp.status_code == 200, path
        assert "Claim info is unavailable right now." in resp.text, path


def test_get_does_not_create_the_claims_db(admin_client, plan_hub):
    assert admin_client.get(PAGE).status_code == 200
    assert not claims_db_path(plan_hub.root).exists()


def _mark_done(plan_hub) -> None:
    svc = plan_hub.root / "federation" / "dev-one" / "dev-svc" / "history.md"
    svc.write_text(
        svc.read_text(encoding="utf-8") + f"| {TICKET} | Story 2 | |\n",
        encoding="utf-8",
    )


def test_done_ticket_page_closes_its_held_claim(admin_client, plan_hub, store):
    claim, token = store.take(REPO, TICKET, "a@m1")
    store.update(claim.id, token, phase="publishing", pr=PR)
    _mark_done(plan_hub)
    text = admin_client.get(PAGE).text
    assert "Taken by" not in text and "Publishing" not in text
    assert "Done — the ticket is" in text
    assert store.held(REPO, TICKET) == []
    assert store.last_closed(REPO, TICKET).close_reason == "done"


@pytest.mark.parametrize("status", ["draft", "blocked"])
def test_draft_or_blocked_ticket_page_shows_no_claim(
    admin_client, store, monkeypatch, status
):
    _take(store)
    monkeypatch.setattr(planui, "_story_status", lambda *_: status)
    text = admin_client.get(PAGE).text
    assert "Taken by" not in text and "In progress" not in text
    assert "Release" not in text
    assert len(store.held(REPO, TICKET)) == 1  # untouched, only not shown


def test_done_ticket_page_does_not_create_the_claims_db(admin_client, plan_hub):
    _mark_done(plan_hub)
    assert admin_client.get(PAGE).status_code == 200
    assert not claims_db_path(plan_hub.root).exists()
