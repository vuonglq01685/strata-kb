"""/api/claims: the hub's JSON view of ticket claims."""

from datetime import UTC, datetime, timedelta

import pytest

from strata_kb.ticketclaim import ClaimStore, claims_db_path
from strata_kb.web import claim_api
from tests.test_planingest import US1, context_block
from tests.test_planstatus import US
from tests.test_ticketfetch import publish_plan

REPO = "ba-one"


@pytest.fixture
def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _take(web_client, auth, holder="a@m1", **extra):
    return web_client.post(
        "/api/claims", json={"ticket": US1, "holder": holder, **extra}, headers=auth
    )


def _delete(web_client, auth, cid, body):
    return web_client.request("DELETE", f"/api/claims/{cid}", json=body, headers=auth)


def test_requires_auth(web_client):
    assert web_client.post("/api/claims", json={}).status_code == 401


def test_take_list_update_release(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    r = _take(web_client, auth)
    assert r.status_code == 201
    cid, tok = r.json()["claim"]["id"], r.json()["token"]
    (c,) = web_client.get("/api/claims", headers=auth).json()["claims"]
    assert (c["repo"], c["ticket"], c["holder"], c["phase"]) == (
        REPO,
        US1,
        "a@m1",
        "claimed",
    )
    assert "token" not in c and "token_hash" not in c
    r = web_client.patch(
        f"/api/claims/{cid}", json={"token": tok, "phase": "design"}, headers=auth
    )
    assert r.json()["claim"]["phase"] == "design"
    assert _delete(web_client, auth, cid, {"token": tok, "reason": "x"}).json() == {}
    assert web_client.get("/api/claims", headers=auth).json()["claims"] == []


def test_list_filters(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    _take(web_client, auth)
    got = web_client.get("/api/claims", params={"repo": "x"}, headers=auth)
    assert got.json()["claims"] == []
    got = web_client.get(
        "/api/claims", params={"repo": REPO, "ticket": US1}, headers=auth
    )
    assert len(got.json()["claims"]) == 1


def test_second_take_is_409_with_holder(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    _take(web_client, auth)
    r = _take(web_client, auth, holder="b@m2")
    assert r.status_code == 409
    assert r.json()["error"] == "taken"
    assert r.json()["claim"]["holder"] == "a@m1"


def test_retake_with_token_is_200(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    first = _take(web_client, auth).json()
    r = _take(web_client, auth, token=first["token"])
    assert r.status_code == 200
    assert r.json() == {
        "claim": {**first["claim"], "last_seen": r.json()["claim"]["last_seen"]},
        "token": first["token"],
    }


def test_take_unknown_ticket_404(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    r = web_client.post(
        "/api/claims", json={"ticket": "NOPE-1", "holder": "a@m1"}, headers=auth
    )
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_ticket"


def test_take_ambiguous_ticket(web_client, hub_with_ticket, hub_dir, tmp_path, auth):
    hub_with_ticket(rev=1)
    publish_plan(hub_dir, "ba-two", tmp_path / "ba-two", context_block(hub_dir))
    r = _take(web_client, auth)
    assert r.status_code == 400
    assert r.json()["error"] == "ambiguous"
    assert "ba-one:" in r.json()["detail"] and "ba-two:" in r.json()["detail"]
    qualified = web_client.post(
        "/api/claims", json={"ticket": f"ba-two:{US1}", "holder": "a@m1"}, headers=auth
    )
    assert qualified.status_code == 201
    assert qualified.json()["claim"]["repo"] == "ba-two"


@pytest.mark.parametrize(
    "body",
    [
        {"holder": "a@m1"},
        {"ticket": US1},
        {"ticket": US1, "holder": 5},
        {"ticket": US1, "holder": "a", "token": 5},
        {"ticket": US1, "holder": " "},
        {"ticket": "../x", "holder": "a"},
        [],
    ],
)
def test_take_bad_body_400(web_client, hub_with_ticket, auth, body):
    hub_with_ticket(rev=1)
    r = web_client.post("/api/claims", json=body, headers=auth)
    assert r.status_code == 400
    assert r.json()["error"] == "bad_request"


def test_bad_json_400(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    r = web_client.post("/api/claims", content=b"{nope", headers=auth)
    assert r.status_code == 400
    assert r.json()["error"] == "bad_request"


def test_patch_lost_after_expiry(web_client, hub_with_ticket, hub_dir, auth):
    hub_with_ticket(rev=1)
    past = datetime.now(UTC) - timedelta(hours=6)
    old = ClaimStore(claims_db_path(hub_dir), now=lambda: past)
    claim, tok = old.take(REPO, US1, "a@m1")
    r = web_client.patch(
        f"/api/claims/{claim.id}", json={"token": tok, "phase": "plan"}, headers=auth
    )
    assert r.status_code == 409
    body = r.json()
    assert (body["error"], body["close_reason"], body["closed_by"]) == (
        "lost",
        "expired",
        "hub",
    )


def test_patch_bad_token_403(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    cid = _take(web_client, auth).json()["claim"]["id"]
    r = web_client.patch(
        f"/api/claims/{cid}", json={"token": "wrong", "phase": "plan"}, headers=auth
    )
    assert r.status_code == 403
    assert r.json()["error"] == "bad_token"


def test_patch_unknown_claim_404(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    r = web_client.patch("/api/claims/99", json={"token": "t"}, headers=auth)
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_claim"


def test_patch_bad_field_400(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    r = _take(web_client, auth).json()
    url = f"/api/claims/{r['claim']['id']}"
    bad = web_client.patch(
        url, json={"token": r["token"], "phase": "bogus"}, headers=auth
    )
    assert bad.status_code == 400 and bad.json()["error"] == "bad_request"
    missing = web_client.patch(url, json={"phase": "plan"}, headers=auth)
    assert missing.status_code == 400
    nonint = web_client.patch("/api/claims/abc", json={"token": "t"}, headers=auth)
    assert nonint.status_code == 404


def test_patch_stop_and_resume(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    r = _take(web_client, auth).json()
    url = f"/api/claims/{r['claim']['id']}"
    stopped = web_client.patch(
        url,
        json={"token": r["token"], "state": "stopped", "stop_reason": "qa"},
        headers=auth,
    ).json()["claim"]
    assert (stopped["state"], stopped["stop_reason"]) == ("stopped", "qa")


def test_delete_lost_and_bad_token(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    r = _take(web_client, auth).json()
    cid, tok = r["claim"]["id"], r["token"]
    assert (
        _delete(web_client, auth, cid, {"token": "no", "reason": "x"}).status_code
        == 403
    )
    assert (
        _delete(web_client, auth, cid, {"token": tok, "reason": "x"}).status_code == 200
    )
    again = _delete(web_client, auth, cid, {"token": tok, "reason": "x"})
    assert again.status_code == 409 and again.json()["error"] == "lost"


def test_pr_closed_route(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    r = _take(web_client, auth).json()
    cid, tok = r["claim"]["id"], r["token"]
    pr = "https://example.test/pr/1"
    web_client.patch(
        f"/api/claims/{cid}",
        json={"token": tok, "phase": "review", "pr": pr},
        headers=auth,
    )
    other = web_client.post(
        f"/api/claims/{cid}/pr-closed",
        json={"pr": "https://example.test/pr/2"},
        headers=auth,
    )
    assert other.status_code == 409
    assert other.json()["error"] == "pr_mismatch"
    ok = web_client.post(f"/api/claims/{cid}/pr-closed", json={"pr": pr}, headers=auth)
    assert ok.status_code == 200
    assert ok.json()["claim"]["phase"] == "execute"
    assert ok.json()["claim"]["pr"] == ""


def test_pr_closed_unknown_claim_404(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    r = web_client.post(
        "/api/claims/9/pr-closed", json={"pr": "https://x"}, headers=auth
    )
    assert r.status_code == 404


def test_get_closes_done_ticket(web_client, plan_hub, auth):
    ticket = US[1]  # the story with a published ticket
    taken = web_client.post(
        "/api/claims", json={"ticket": ticket, "holder": "a@m1"}, headers=auth
    )
    assert taken.status_code == 201
    assert len(web_client.get("/api/claims", headers=auth).json()["claims"]) == 1

    history = plan_hub.root / "federation/dev-one/dev-svc/history.md"
    history.write_text(
        history.read_text(encoding="utf-8") + f"| {ticket} | Story 2 | |\n",
        encoding="utf-8",
    )

    assert web_client.get("/api/claims", headers=auth).json()["claims"] == []
    last = ClaimStore(claims_db_path(plan_hub.root)).last_closed(REPO, ticket)
    assert last is not None and last.close_reason == "done"


def test_get_survives_plan_read_failure(web_client, hub_with_ticket, auth, monkeypatch):
    from strata_kb import planstatus

    hub_with_ticket(rev=1)
    _take(web_client, auth)

    def boom(*_a, **_k):
        raise OSError("plan unreadable")

    monkeypatch.setattr(planstatus, "next_from_hub", boom)
    r = web_client.get("/api/claims", headers=auth)
    assert r.status_code == 200
    assert len(r.json()["claims"]) == 1


def test_body_too_large_413(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    r = web_client.post(
        "/api/claims",
        json={"ticket": US1, "holder": "a", "pad": "x" * 9000},
        headers=auth,
    )
    assert r.status_code == 413
    chunked = web_client.post(
        "/api/claims",
        content=iter([b"x" * 5000, b"y" * 5000]),
        headers=auth,
    )
    assert chunked.status_code == 413


def test_needs_hub_server_503(hub_dir, token, tmp_path, auth):
    from starlette.testclient import TestClient

    from strata_kb.mcp import ServerConfig
    from strata_kb.web.app import create_app

    config = ServerConfig(kb_dir=tmp_path / ".kb", hub=str(hub_dir))
    with TestClient(create_app(config, token)) as c:
        r = c.get("/api/claims", headers=auth)
    assert r.status_code == 503
    assert r.json()["error"] == "qa_needs_hub_server"  # the spec's key
    assert r.json()["detail"] == "claims need the shared hub server"


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "", "1.5"])
def test_bad_ttl_env_falls_back(monkeypatch, raw):
    monkeypatch.setenv("STRATA_KB_CLAIM_TTL", raw)
    assert claim_api.claim_ttl_from_env() == 14400


def test_ttl_env_used(monkeypatch):
    monkeypatch.setenv("STRATA_KB_CLAIM_TTL", "60")
    assert claim_api.claim_ttl_from_env() == 60
    monkeypatch.delenv("STRATA_KB_CLAIM_TTL")
    assert claim_api.claim_ttl_from_env() == 14400
