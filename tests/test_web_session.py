"""M4: the /ui cookie used to be the bearer token itself."""

import time

import pytest

from strata_kb.serving import auth
from strata_kb.serving.accounts import User, password_version

TOKEN = "s3cr3t-token-abcdefgh"


def _login(client, admin_user):
    username, password = admin_user
    return client.post(
        "/ui/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


KEY = b"k" * 32
USER = User("alice", "dev", "scrypt$n=16384,r=8,p=1$c2FsdA==$aGFzaA==", "", "")


def test_session_round_trip():
    value = auth.make_user_session(KEY, USER)
    assert auth.read_user_session(value, KEY) == (
        "alice",
        password_version(USER.password_hash),
    )


def test_session_value_is_neither_the_token_nor_the_hash():
    value = auth.make_user_session(KEY, USER)
    assert TOKEN not in value and USER.password_hash not in value


def test_username_with_dots_and_unicode_round_trips():
    user = User("a.b é", "dev", USER.password_hash, "", "")
    value = auth.make_user_session(KEY, user)
    assert auth.read_user_session(value, KEY) is not None
    assert auth.read_user_session(value, KEY)[0] == "a.b é"  # type: ignore[index]


def test_expired_session_is_rejected():
    issued = time.time() - auth.SESSION_MAX_AGE - 1
    value = auth.make_user_session(KEY, USER, now=issued)
    assert auth.read_user_session(value, KEY) is None


def test_tampered_signature_is_rejected():
    value = auth.make_user_session(KEY, USER)
    head, _, sig = value.rpartition(".")
    assert auth.read_user_session(f"{head}.{'0' * len(sig)}", KEY) is None


def test_wrong_key_is_rejected():
    value = auth.make_user_session(KEY, USER)
    assert auth.read_user_session(value, b"x" * 32) is None


def test_forged_timestamp_is_rejected():
    """Extending your own session must not work without the key.

    Forges a timestamp INSIDE a valid age window (age 5, comfortably under
    SESSION_MAX_AGE) so nothing but the HMAC check can reject it. (A forgery
    into the future would be rejected by the age bound before the signature
    was ever consulted, and so pass even with the HMAC check deleted.)
    """
    now = 1_700_000_000.0
    value = auth.make_user_session(KEY, USER, now=now)
    _, rest = value.split(".", 1)
    forged = f"{int(now) + 5}.{rest}"
    assert auth.read_user_session(forged, KEY, now=now + 10) is None


def test_swapped_username_is_rejected():
    """The username is under the signature: re-labelling a session as
    someone else (e.g. an admin) must fail."""
    value = auth.make_user_session(KEY, USER)
    issued, _, rest = value.partition(".")
    _, _, tail = rest.partition(".")
    other = auth.make_user_session(KEY, User("root", "admin", "h", "", ""))
    other_name = other.split(".")[1]
    assert auth.read_user_session(f"{issued}.{other_name}.{tail}", KEY) is None


def test_future_dated_session_is_rejected():
    """A session validly signed for a future issue time is still outside the
    valid window (age < 0)."""
    now = 1_700_000_000.0
    value = auth.make_user_session(KEY, USER, now=now + 3600)
    assert auth.read_user_session(value, KEY, now=now) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "no-dot",
        "abc.def",
        ".",
        "x.y.z",
        "a.b.c.d",
        "١٢٣.abc.def.0",  # isdecimal() accepts non-ASCII digits
        "123.abc.def.café",  # non-ASCII sig; compare_digest raises on this
        "123.@@@.def.00",  # not base64
    ],
)
def test_malformed_cookie_is_rejected_without_raising(value):
    assert auth.read_user_session(value, KEY) is None


def test_login_sets_an_httponly_capped_cookie_that_is_not_the_token(
    web_client, admin_user
):
    resp = _login(web_client, admin_user)
    cookie = resp.headers["set-cookie"]
    assert "strata_kb_session=" in cookie
    assert TOKEN not in cookie
    assert "HttpOnly" in cookie
    assert "Max-Age=43200" in cookie
    assert "SameSite=lax" in cookie
    # web_client talks plain http (no TLS, no trusted proxy) -- cookie_is_secure
    # must come back False, so Secure must be absent from the wire.
    assert "Secure" not in cookie


def test_login_over_https_sets_a_secure_cookie(web_client_https, admin_user):
    resp = _login(web_client_https, admin_user)
    cookie = resp.headers["set-cookie"]
    assert "Secure" in cookie


def test_logout_clears_the_cookie(web_client, admin_user):
    _login(web_client, admin_user)
    resp = web_client.post("/ui/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui/login"
    assert "strata_kb_session=;" in resp.headers["set-cookie"].replace('""', "")


def test_a_raw_token_cookie_no_longer_authorises(web_client):
    web_client.cookies.set("strata_kb_session", TOKEN)
    resp = web_client.get("/ui/docs", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ui/login"


def test_login_clears_the_pre_024_raw_token_cookie(web_client, admin_user):
    """Login must clear cookies from prior product names (raw-token
    center_kb_token, then center_kb_session) so an upgrade does not leave
    an old credential in the jar."""
    resp = _login(web_client, admin_user)
    cookies = resp.headers.get_list("set-cookie")
    assert any("center_kb_token=" in c and "Max-Age=0" in c for c in cookies), cookies
    assert any("center_kb_session=" in c and "Max-Age=0" in c for c in cookies), cookies


def test_logout_clears_the_pre_024_raw_token_cookie(web_client, admin_user):
    _login(web_client, admin_user)
    resp = web_client.post("/ui/logout", follow_redirects=False)
    cookies = resp.headers.get_list("set-cookie")
    assert any("center_kb_token=" in c and "Max-Age=0" in c for c in cookies), cookies
    assert any("center_kb_session=" in c and "Max-Age=0" in c for c in cookies), cookies


def _proto_request(xfp: str):
    """A plain-http Request carrying the given raw X-Forwarded-Proto value,
    for exercising cookie_is_secure's trusted-hop parsing directly."""
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "scheme": "http",
        "headers": [(b"x-forwarded-proto", xfp.encode("ascii"))],
        "client": ("1.2.3.4", 1234),
        "server": ("testserver", 80),
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
        "/ui/login", data={"password": "x" * (64 * 1024)}, follow_redirects=False
    )
    assert resp.status_code == 413
    assert resp.headers["cache-control"] == "no-store"


def test_login_pages_are_not_cacheable(web_client):
    assert web_client.get("/ui/login").headers["cache-control"] == "no-store"
    assert (
        web_client.post(
            "/ui/login",
            data={"username": "nobody", "password": "wrong"},
            follow_redirects=False,
        ).headers["cache-control"]
        == "no-store"
    )


def test_login_success_redirect_is_not_cacheable(web_client, admin_user):
    # Fix round 1 (Minor B): the 303 success redirect is the one response in
    # this handler that carries Set-Cookie -- the most cache-sensitive path,
    # and the one the original test suite skipped.
    resp = _login(web_client, admin_user)
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
