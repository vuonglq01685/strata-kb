"""M6: the same secret over Authorization had no lockout at all."""
import time

from strata_kb.web.auth import COOKIE_NAME, SESSION_MAX_AGE, make_session
from strata_kb.web.ratelimit import LOGIN_MAX_ATTEMPTS


def test_failed_header_auth_is_eventually_429(web_client):
    codes = [
        web_client.get(
            "/api/docs", headers={"Authorization": "Bearer wrong"}
        ).status_code
        for _ in range(LOGIN_MAX_ATTEMPTS + 3)
    ]
    assert codes[:LOGIN_MAX_ATTEMPTS] == [401] * LOGIN_MAX_ATTEMPTS
    assert codes[-1] == 429


def test_duplicate_authorization_header_still_spends_the_limiter(web_client):
    """Fix round 2 (Critical): a guess sent as `Authorization: Bearer
    <guess>` plus a second, empty `Authorization:` header (two distinct
    entries -- confirmed h11, uvicorn's parser here, delivers duplicate
    header lines verbatim into the ASGI scope) used to be evaluated by
    _authorized (which read the FIRST entry) but never charged by
    _credential_presented (which read the LAST) -- an unlimited-rate
    brute-force channel against the shared secret. Must behave exactly like
    test_failed_header_auth_is_eventually_429 above: 429 after
    LOGIN_MAX_ATTEMPTS, not 401 forever."""
    dup_headers = [("Authorization", "Bearer wrong"), ("Authorization", "")]
    codes = [
        web_client.get("/api/docs", headers=dup_headers).status_code
        for _ in range(LOGIN_MAX_ATTEMPTS + 3)
    ]
    assert codes[:LOGIN_MAX_ATTEMPTS] == [401] * LOGIN_MAX_ATTEMPTS
    assert codes[-1] == 429


def test_successful_auth_never_counts(web_client, token):
    for _ in range(LOGIN_MAX_ATTEMPTS + 5):
        assert web_client.get(
            "/api/docs", headers={"Authorization": f"Bearer {token}"}
        ).status_code == 200


def test_the_header_path_and_the_login_form_share_one_bucket(web_client):
    """Spending attempts on the header must lock the form — otherwise the
    limiter is decoration."""
    for _ in range(LOGIN_MAX_ATTEMPTS):
        web_client.get("/api/docs", headers={"Authorization": "Bearer wrong"})
    resp = web_client.post(
        "/ui/login", data={"token": "wrong"}, follow_redirects=False
    )
    assert resp.status_code == 429


def test_browser_paths_get_html_and_api_paths_get_json(web_client):
    for _ in range(LOGIN_MAX_ATTEMPTS + 1):
        web_client.get("/api/docs", headers={"Authorization": "Bearer wrong"})
    api_resp = web_client.get("/api/docs", headers={"Authorization": "Bearer wrong"})
    # Fix round 1: a credential-free /ui/docs hit is exempt from the limiter
    # (see test_anonymous_browsing_never_spends_the_bucket) -- this probe
    # needs its own failed attempt to land in the /ui HTML branch.
    ui_resp = web_client.get(
        "/ui/docs", headers={"Authorization": "Bearer wrong"}, follow_redirects=False
    )
    assert api_resp.status_code == 429
    assert api_resp.headers["content-type"].startswith("application/json")
    assert ui_resp.status_code == 429
    assert ui_resp.headers["content-type"].startswith("text/html")
    # M9 fix round 1 (Minor A): same lockout-notice class as login_post's
    # 429/413 -- must not be cached across the lockout window.
    assert ui_resp.headers["cache-control"] == "no-store"


def test_exempt_paths_never_spend_the_bucket(web_client):
    """A k8s liveness probe on /api/health every 5s must never trip the
    limiter -- the whole safety argument for this file rests on the
    exempt/authorised early return running before the limiter check."""
    n = LOGIN_MAX_ATTEMPTS * 2
    assert [web_client.get("/api/health").status_code for _ in range(n)] == [200] * n


def test_anonymous_browsing_never_spends_the_bucket(web_client, token):
    """Critical fix round 1: the limiter used to count every credential-free
    hit (a logged-out GET /, the browser's automatic /favicon.ico, ...), so
    5 ordinary anonymous page loads exhausted the bucket and the very next
    login POST -- even with the CORRECT token -- came back 429. None of
    these requests present an Authorization header or a session cookie, so
    none of them is "a failed attempt at the shared secret" and none of them
    may spend M6's bucket."""
    for _ in range(LOGIN_MAX_ATTEMPTS):
        assert web_client.get("/", follow_redirects=False).status_code == 302
    resp = web_client.post(
        "/ui/login", data={"token": token}, follow_redirects=False
    )
    assert resp.status_code == 303


def test_expired_own_cookie_does_not_lock_out_the_correct_token(web_client, token):
    """Final review item 1: SESSION_MAX_AGE (12h) guarantees every user's OWN
    cookie -- issued by this same server, correctly signed -- eventually
    fails verify_session's age check. Before the fix, _credential_presented
    charges it on every page view exactly like a wrong guess (M6's own
    rule), so ordinary browsing with a stale cookie locks the user out of
    logging back in with the CORRECT token. Reproduces the reviewer's exact
    sequence: 3 page loads, each firing the main /ui request plus the
    browser's automatic /favicon.ico (not covered by the /ui/static/
    exemption).

    domain="testserver.local" matches what a REAL Set-Cookie response
    computes for TestClient's dotless host (http.cookiejar.eff_request_host
    appends ".local") -- without it the fix's own clearing Set-Cookie can
    never find and remove a manually-seeded cookie (jar.clear() no-ops on a
    domain miss), a quirk of this test double a real browser never hits."""
    stale_cookie = make_session(token, now=time.time() - SESSION_MAX_AGE - 1)
    web_client.cookies.set(COOKIE_NAME, stale_cookie, domain="testserver.local")

    codes = []
    for _ in range(3):
        codes.append(web_client.get("/ui", follow_redirects=False).status_code)
        codes.append(web_client.get("/favicon.ico", follow_redirects=False).status_code)
    # Budget must never be exhausted by the user's own dead cookie.
    assert 429 not in codes

    resp = web_client.post(
        "/ui/login", data={"token": token}, follow_redirects=False
    )
    assert resp.status_code == 303


def test_a_forged_session_cookie_is_still_charged_every_time(web_client):
    """The fix above must not open a retry channel: a cookie this server
    never issued (bad signature -- a guess, not a stale real credential)
    must still spend the limiter on every single request, same as before.
    Sent explicitly per request (not via the client's cookie jar): a
    scripted attacker resending a fixed Cookie header ignores the server's
    Set-Cookie response the same way, so this is the channel the fix must
    keep closed."""
    forged = {COOKIE_NAME: "1234567890.notarealsignature"}
    codes = [
        web_client.get("/ui", cookies=forged, follow_redirects=False).status_code
        for _ in range(LOGIN_MAX_ATTEMPTS + 3)
    ]
    assert codes[-1] == 429
