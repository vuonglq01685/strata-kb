"""ClaimClient: the hub /api/claims wire, error mapping, holder name, local token file."""

from __future__ import annotations

import json

import pytest

from strata_kb import claimclient
from strata_kb.claimclient import (
    ClaimClient,
    ClaimLostError,
    ClaimRouteMissing,
    ClaimTakenError,
    LocalClaims,
)
from strata_kb.errors import KbError


class FakeHttp:
    def __init__(self, code: int, payload: object = None, raw: bytes | None = None):
        self.code = code
        self.body = raw if raw is not None else json.dumps(payload).encode()
        self.calls: list[tuple] = []

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        return self.code, self.body


def client(http: FakeHttp) -> ClaimClient:
    return ClaimClient("http://hub", "t", http)


def test_take_sends_bearer_and_body():
    http = FakeHttp(201, {"claim": {"id": 4}, "token": "ct"})
    claim, token = client(http).take("US1", "a@m1")
    method, url, headers, body = http.calls[0]
    assert (method, url) == ("POST", "http://hub/api/claims")
    assert headers["Authorization"] == "Bearer t"
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"ticket": "US1", "holder": "a@m1"}
    assert (claim, token) == ({"id": 4}, "ct")


def test_take_resends_known_token():
    http = FakeHttp(200, {"claim": {"id": 4}, "token": "ct"})
    client(http).take("US1", "a@m1", "ct")
    assert json.loads(http.calls[0][3])["token"] == "ct"


def test_take_409_raises_taken_with_claim():
    claim = {"holder": "b@m2", "phase": "design"}
    http = FakeHttp(409, {"error": "taken", "claim": claim})
    with pytest.raises(ClaimTakenError) as exc:
        client(http).take("US1", "a@m1")
    assert exc.value.claim == claim


def test_update_sends_patch_with_token_and_fields():
    http = FakeHttp(200, {"claim": {"id": 4, "phase": "plan"}})
    assert client(http).update(4, "ct", phase="plan") == {"id": 4, "phase": "plan"}
    method, url, _, body = http.calls[0]
    assert (method, url) == ("PATCH", "http://hub/api/claims/4")
    assert json.loads(body) == {"token": "ct", "phase": "plan"}


def test_update_409_lost():
    http = FakeHttp(
        409, {"error": "lost", "close_reason": "expired", "closed_by": "hub"}
    )
    with pytest.raises(ClaimLostError) as exc:
        client(http).update(4, "ct", phase="plan")
    assert (exc.value.close_reason, exc.value.closed_by) == ("expired", "hub")


def test_release_sends_delete_with_reason():
    http = FakeHttp(200, {})
    client(http).release(4, "ct", "done")
    method, url, _, body = http.calls[0]
    assert (method, url) == ("DELETE", "http://hub/api/claims/4")
    assert json.loads(body) == {"token": "ct", "reason": "done"}


def test_held_filters_in_query():
    http = FakeHttp(200, {"claims": [{"id": 1}]})
    assert client(http).held(ticket="US 1") == [{"id": 1}]
    assert http.calls[0][1] == "http://hub/api/claims?ticket=US+1"


def test_pr_closed_posts_pr():
    http = FakeHttp(200, {"claim": {"id": 4}})
    assert client(http).pr_closed(4, "u") == {"id": 4}
    assert http.calls[0][1] == "http://hub/api/claims/4/pr-closed"
    assert json.loads(http.calls[0][3]) == {"pr": "u"}


def test_bare_404_is_route_missing():
    with pytest.raises(ClaimRouteMissing) as exc:
        client(FakeHttp(404, raw=b"Not Found")).held()
    assert (
        str(exc.value)
        == "hub server has no /api/claims — upgrade it to strata-kb 1.31.0 or later"
    )


def test_404_with_error_code_is_not_route_missing():
    with pytest.raises(KbError, match="unknown_ticket") as exc:
        client(FakeHttp(404, {"error": "unknown_ticket"})).take("US1", "a")
    assert not isinstance(exc.value, ClaimRouteMissing)


def test_other_status_is_kb_error():
    with pytest.raises(KbError, match="hub /api/claims returned 403: bad_token"):
        client(FakeHttp(403, {"error": "bad_token"})).release(4, "x", "r")


def test_unreachable():
    with pytest.raises(KbError, match="hub unreachable: refused"):
        client(FakeHttp(0, raw=b"refused")).held()


def test_holder_name_default(monkeypatch, tmp_path):
    monkeypatch.delenv("STRATA_KB_CLAIM_AS", raising=False)
    monkeypatch.setattr(claimclient.gitio, "config_value", lambda _r, _k: "vuong")
    monkeypatch.setattr(claimclient.socket, "gethostname", lambda: "laptop-2")
    assert claimclient.holder_name(tmp_path) == "vuong@laptop-2"


def test_holder_name_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("STRATA_KB_CLAIM_AS", "ci-bot")
    assert claimclient.holder_name(tmp_path) == "ci-bot"


def test_from_env_requires_url_and_token(monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB_URL", raising=False)
    with pytest.raises(KbError, match="STRATA_KB_HUB_URL is not set"):
        claimclient.from_env()
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub/")
    monkeypatch.delenv("STRATA_KB_HTTP_TOKEN", raising=False)
    with pytest.raises(KbError, match="STRATA_KB_HTTP_TOKEN is not set"):
        claimclient.from_env()
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", "t")
    assert claimclient.from_env().base_url == "http://hub"


def test_local_claims_roundtrip_and_corrupt_file(tmp_path):
    local = LocalClaims(tmp_path / ".kb")
    assert local.get("US1") is None
    local.put("US1", 4, "ct")
    assert LocalClaims(tmp_path / ".kb").get("US1") == (4, "ct")
    path = tmp_path / ".kb" / "auto" / "claims.json"
    assert json.loads(path.read_text()) == {"US1": {"id": 4, "token": "ct"}}
    local.drop("US1")
    local.drop("US1")
    assert local.get("US1") is None
    path.write_text("{not json")
    assert local.get("US1") is None
    local.put("US2", 5, "x")
    assert local.get("US2") == (5, "x")


@pytest.mark.parametrize("error", ["bad_request", "ambiguous"])
def test_400_detail_is_in_the_message(error):
    http = FakeHttp(400, {"error": error, "detail": "pass <repo>:<id>"})
    with pytest.raises(
        KbError, match=f"hub /api/claims returned 400: {error} — pass <repo>:<id>"
    ):
        client(http).take("US1", "a")


def test_error_without_detail_has_no_dash():
    with pytest.raises(KbError) as exc:
        client(FakeHttp(400, {"error": "bad_request"})).take("US1", "a")
    assert str(exc.value) == "hub /api/claims returned 400: bad_request"
