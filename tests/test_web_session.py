"""M4: the /ui cookie used to be the bearer token itself."""
import time

import pytest

from center_kb.web import auth

TOKEN = "s3cr3t-token-abcdefgh"


def test_session_round_trip():
    value = auth.make_session(TOKEN)
    assert auth.verify_session(value, TOKEN) is True


def test_session_value_is_not_the_token():
    assert TOKEN not in auth.make_session(TOKEN)


def test_expired_session_is_rejected():
    issued = time.time() - auth.SESSION_MAX_AGE - 1
    value = auth.make_session(TOKEN, now=issued)
    assert auth.verify_session(value, TOKEN) is False


def test_tampered_signature_is_rejected():
    value = auth.make_session(TOKEN)
    ts, _, sig = value.partition(".")
    assert auth.verify_session(f"{ts}.{'0' * len(sig)}", TOKEN) is False


def test_forged_timestamp_is_rejected():
    """Extending your own session must not work without the token.

    The brief's original `f"{time.time():.0f}.{sig}"` races make_session's
    int(now) truncation against this line's round-to-nearest, so whenever
    the real issue time's fractional second is < .5 the "forged" value
    rounds right back to the real one and the assertion flips ~50% of runs
    (confirmed empirically, see the fix report for the earlier rewrite's own
    bug: it forged into the future and verified at the *original* `now`, so
    `age` went negative and the age bound rejected it before the signature
    was ever consulted -- passes even with the HMAC check deleted).

    This version forges a timestamp INSIDE a valid age window (age 5,
    comfortably under SESSION_MAX_AGE) so nothing but the HMAC check can
    reject it: verified locally that removing `hmac.compare_digest` from
    `verify_session` flips this test to a false pass (see fix report).
    """
    now = 1_700_000_000.0
    value = auth.make_session(TOKEN, now=now)
    _, _, sig = value.partition(".")
    forged = f"{int(now) + 5}.{sig}"
    assert auth.verify_session(forged, TOKEN, now=now + 10) is False


def test_future_dated_session_is_rejected():
    """A session validly signed for a future issue time is still outside the
    valid window (age < 0) -- the lower bound that the flawed original
    forged-timestamp test only incidentally exercised."""
    now = 1_700_000_000.0
    value = auth.make_session(TOKEN, now=now + 3600)
    assert auth.verify_session(value, TOKEN, now=now) is False


@pytest.mark.parametrize(
    "value",
    [
        "",
        "no-dot",
        "abc.def",
        ".",
        "x.y.z",
        "١٢٣.abc",  # isdecimal() accepts non-ASCII digits; .encode("ascii") would raise
        "123.café",  # non-ASCII sig; hmac.compare_digest raises TypeError on this
    ],
)
def test_malformed_cookie_is_rejected_without_raising(value):
    assert auth.verify_session(value, TOKEN) is False


def test_login_sets_an_httponly_capped_cookie_that_is_not_the_token(web_client):
    resp = web_client.post(
        "/ui/login", data={"token": TOKEN}, follow_redirects=False
    )
    cookie = resp.headers["set-cookie"]
    assert "center_kb_session=" in cookie
    assert TOKEN not in cookie
    assert "HttpOnly" in cookie
    assert "Max-Age=43200" in cookie
    assert "SameSite=lax" in cookie
    # web_client talks plain http (no TLS, no trusted proxy) -- cookie_is_secure
    # must come back False, so Secure must be absent from the wire.
    assert "Secure" not in cookie


def test_login_over_https_sets_a_secure_cookie(web_client_https):
    resp = web_client_https.post(
        "/ui/login", data={"token": TOKEN}, follow_redirects=False
    )
    cookie = resp.headers["set-cookie"]
    assert "Secure" in cookie


def test_logout_clears_the_cookie(web_client):
    web_client.post("/ui/login", data={"token": TOKEN}, follow_redirects=False)
    resp = web_client.post("/ui/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui/login"
    assert "center_kb_session=;" in resp.headers["set-cookie"].replace('""', "")


def test_a_raw_token_cookie_no_longer_authorises(web_client):
    web_client.cookies.set("center_kb_session", TOKEN)
    resp = web_client.get("/ui/docs", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ui/login"


def test_login_clears_the_pre_024_raw_token_cookie(web_client, token=TOKEN):
    """Final review item 4: pre-0.24 set center_kb_token = the raw shared
    secret. The session-cookie switch (M4) stopped READING that cookie but
    never told the browser to drop it, so upgrading left an admin-equivalent
    secret sitting in every existing user's jar. A fresh login must clear
    it."""
    resp = web_client.post(
        "/ui/login", data={"token": token}, follow_redirects=False
    )
    assert any(
        "center_kb_token=" in c and "Max-Age=0" in c
        for c in resp.headers.get_list("set-cookie")
    ), resp.headers.get_list("set-cookie")


def test_logout_clears_the_pre_024_raw_token_cookie(web_client):
    web_client.post("/ui/login", data={"token": TOKEN}, follow_redirects=False)
    resp = web_client.post("/ui/logout", follow_redirects=False)
    assert any(
        "center_kb_token=" in c and "Max-Age=0" in c
        for c in resp.headers.get_list("set-cookie")
    ), resp.headers.get_list("set-cookie")


def _proto_request(xfp: str):
    """A plain-http Request carrying the given raw X-Forwarded-Proto value,
    for exercising cookie_is_secure's trusted-hop parsing directly."""
    from starlette.requests import Request

    scope = {
        "type": "http", "method": "GET", "path": "/", "scheme": "http",
        "headers": [(b"x-forwarded-proto", xfp.encode("ascii"))],
        "client": ("1.2.3.4", 1234), "server": ("testserver", 80),
        "query_string": b"",
    }
    return Request(scope)


def test_cookie_is_secure_trusts_the_rightmost_forwarded_proto_hop():
    """Fix round 1 (carry-forward 1): the trusted proxy's OWN observation is
    the rightmost entry, matching ratelimit.client_key's X-Forwarded-For
    convention -- a leftmost entry ahead of it is not the trusted hop's."""
    request = _proto_request("http, https")
    assert auth.cookie_is_secure(request, trusted_proxies=1) is True


def test_cookie_is_secure_ignores_a_client_forged_leftmost_forwarded_proto():
    """A client sitting in front of the one trusted proxy can set whatever
    it likes as the FIRST entry; only the trusted proxy's own (rightmost)
    entry may set Secure. Here the trusted proxy's real observation is
    "http" -- the forged leftmost "https" must not override it."""
    request = _proto_request("https, http")
    assert auth.cookie_is_secure(request, trusted_proxies=1) is False


def test_login_rejects_an_oversized_body(web_client):
    resp = web_client.post(
        "/ui/login", data={"token": "x" * (64 * 1024)}, follow_redirects=False
    )
    assert resp.status_code == 413
    assert resp.headers["cache-control"] == "no-store"


def test_login_pages_are_not_cacheable(web_client):
    assert web_client.get("/ui/login").headers["cache-control"] == "no-store"
    assert (
        web_client.post(
            "/ui/login", data={"token": "wrong"}, follow_redirects=False
        ).headers["cache-control"]
        == "no-store"
    )


def test_login_success_redirect_is_not_cacheable(web_client, token):
    # Fix round 1 (Minor B): the 303 success redirect is the one response in
    # this handler that carries Set-Cookie -- the most cache-sensitive path,
    # and the one the original test suite skipped.
    resp = web_client.post(
        "/ui/login", data={"token": token}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["cache-control"] == "no-store"


def test_health_body_does_not_vary_by_credential(web_client, token):
    """Fix round 3 (Critical): /api/health sits in auth.EXEMPT_PATHS, so
    TokenAuthMiddleware's limiter never sees it -- an earlier version of this
    handler returned hub_configured/hub_reachable only to authorized
    callers, which made the route an unmetered oracle: a caller could brute
    force the shared secret by reading the response body instead of the
    status code, at full unthrottled speed (measured: 20/20 wrong-token
    guesses -> 200 with the body identical to a fresh attempt, limiter never
    touched). The fix is to stop the body varying at all -- not to meter a
    liveness probe."""
    anon = web_client.get("/api/health").json()
    assert anon == {"status": "ok"}
    authed = web_client.get(
        "/api/health", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert authed == {"status": "ok"}
