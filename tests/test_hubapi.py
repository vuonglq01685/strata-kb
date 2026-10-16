"""hubapi — the cloud client of the hub's /api/plan, /api/registry and /api/resolve."""

from __future__ import annotations

import json

import pytest

from strata_kb import hubapi, kbcontext, planstatus, resolve
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle
from tests.test_planingest import context_block

TOKEN = "s3cr3t-token-abcdefgh"


def client_http(client, token: str = TOKEN):
    """An `httpio.request` double that sends the call to a Starlette TestClient."""

    def http(method, url, headers, body=None, timeout=60):
        path = "/" + url.split("//", 1)[1].split("/", 1)[1]
        resp = client.request(method, path, headers=headers, content=body)
        return resp.status_code, resp.content

    return http


def canned(status: int, payload=None, raw: bytes | None = None):
    calls: list[tuple] = []

    def http(method, url, headers, body=None, timeout=60):
        calls.append((method, url, headers, body))
        return status, raw if raw is not None else json.dumps(payload).encode()

    http.calls = calls  # type: ignore[attr-defined]
    return http


def api(http) -> hubapi.HubApi:
    return hubapi.HubApi("http://hub:8080", TOKEN, http=http)


def test_hubapi_plan_next_round_trips_storystatus(web_client, hub_with_ticket, fed_hub):
    hub = hub_with_ticket(rev=1)
    expected = planstatus.next_from_hub(hub)

    got = api(client_http(web_client)).plan_next()

    assert got == expected
    assert got[0] or got[1]


def test_hubapi_plan_next_sends_repo_and_bearer():
    http = canned(200, {"stories": [], "unparented": [], "notes": ["n"]})

    assert api(http).plan_next("ba one") == ([], [], ["n"])

    method, url, headers, _ = http.calls[0]
    assert (method, url) == ("GET", "http://hub:8080/api/plan/next?repo=ba+one")
    assert headers["Authorization"] == f"Bearer {TOKEN}"


def test_hubapi_plan_next_without_repo_has_no_query():
    http = canned(200, {"stories": [], "unparented": [], "notes": []})
    api(http).plan_next()
    assert http.calls[0][1] == "http://hub:8080/api/plan/next"


@pytest.mark.parametrize(
    ("call", "route"),
    [
        (lambda a: a.plan_next(), "/api/plan/next"),
        (lambda a: a.registry_entry("svc"), "/api/registry/entry"),
        (lambda a: a.resolve("kb-context:\n"), "/api/resolve"),
    ],
)
@pytest.mark.parametrize("body", [b"Not Found", b'{"error": "something_else"}'])
def test_hubapi_404_route_names_1_30_0(call, route, body):
    with pytest.raises(KbError) as exc:
        call(api(canned(404, raw=body)))
    assert str(exc.value) == (
        f"hub server has no {route} — upgrade it to strata-kb 1.30.0 or later"
    )


def test_hubapi_registry_entry_none_when_repo_not_registered():
    http = canned(404, {"error": "repo_not_registered", "detail": "x"})
    assert api(http).registry_entry("ghost") is None
    assert http.calls[0][1] == "http://hub:8080/api/registry/entry?repo_id=ghost"


def test_hubapi_registry_entry_returns_facts():
    facts = {"repo_id": "svc", "kind": "dev", "auto_merge": True, "dev_repos": 1}
    assert api(canned(200, facts)).registry_entry("svc") == facts


def test_hubapi_unreachable_names_the_reason_not_the_token():
    http = canned(0, raw=b"connection refused")
    with pytest.raises(KbError, match="hub unreachable: connection refused") as exc:
        api(http).plan_next()
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize(
    ("status", "payload", "needle"),
    [
        (503, {"error": "hub_unreachable"}, "returned 503: hub_unreachable"),
        (400, {"error": "kb_context_error"}, "returned 400: kb_context_error"),
        (401, None, "returned 401"),
    ],
)
def test_hubapi_non_2xx_is_kberror_with_code(status, payload, needle):
    http = canned(status, payload) if payload else canned(status, raw=b"nope")
    with pytest.raises(KbError, match=needle):
        api(http).plan_next()


@pytest.mark.parametrize("raw", [b"<html>", b"[]", b'{"stories": 3}'])
def test_hubapi_bad_body_is_kberror(raw):
    with pytest.raises(KbError, match="unexpected body"):
        api(canned(200, raw=raw)).plan_next()


def test_hubapi_resolve_matches_local_resolve_refs(web_client, fed_hub):
    block = context_block(fed_hub)
    ctx = kbcontext.parse(block)
    local = resolve.resolve_refs(HubHandle(root=fed_hub), ctx)

    version, results = api(client_http(web_client)).resolve(block)

    assert version == ctx.version
    assert results == local
    assert results


def test_hubapi_resolve_posts_utf8_text():
    http = canned(200, {"version": "v", "results": []})
    assert api(http).resolve("héllo") == ("v", [])
    method, url, headers, body = http.calls[0]
    assert (method, url) == ("POST", "http://hub:8080/api/resolve")
    assert body == "héllo".encode()
    assert headers["Authorization"] == f"Bearer {TOKEN}"


def test_hubapi_resolve_oversized_body_is_kberror():
    with pytest.raises(KbError, match="413: body_too_large"):
        api(canned(413, {"error": "body_too_large"})).resolve("x")


@pytest.mark.parametrize("repo_id", [None, "ba-one", "acme/ba-one"])
def test_str_kbref_round_trips_through_parse_ref(repo_id):
    ref = kbcontext.KBRef(doc_id="hr-handbook", section_id="4.12", repo_id=repo_id)
    assert kbcontext.parse_ref(str(ref)) == ref


def test_hubapi_resolve_rejects_unparseable_ref():
    row = {
        "ref": "???", "status": "ok", "citation": "c", "content": "",
        "tokens": 0, "reason": "", "pinned_rev": "",
    }  # fmt: skip
    with pytest.raises(KbError, match="ref"):
        api(canned(200, {"version": "v", "results": [row]})).resolve("x")


def test_from_env(monkeypatch):
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub:1/")
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", TOKEN)
    client = hubapi.from_env()
    assert client.base_url == "http://hub:1"


@pytest.mark.parametrize("missing", ["STRATA_KB_HUB_URL", "STRATA_KB_HTTP_TOKEN"])
def test_from_env_names_the_missing_variable(monkeypatch, missing):
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub:1")
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", TOKEN)
    monkeypatch.delenv(missing)
    with pytest.raises(KbError, match=f"{missing} is not set"):
        hubapi.from_env()
