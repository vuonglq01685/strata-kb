"""M5: no response carried a single security header."""

REQUIRED = {
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
}


def test_headers_on_an_authorised_page(web_client_logged_in):
    resp = web_client_logged_in.get("/ui")
    assert REQUIRED <= set(resp.headers)


def test_headers_on_the_login_redirect(web_client):
    resp = web_client.get("/ui", follow_redirects=False)
    assert resp.status_code == 302
    assert REQUIRED <= set(resp.headers)


def test_headers_on_a_401(web_client):
    resp = web_client.get("/api/docs")
    assert resp.status_code == 401
    assert REQUIRED <= set(resp.headers)


def test_csp_allows_the_one_external_script_and_inline_styles(web_client_logged_in):
    csp = web_client_logged_in.get("/ui").headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_hsts_only_over_https(web_client, web_client_https):
    assert "strict-transport-security" not in web_client.get(
        "/ui", follow_redirects=False
    ).headers
    assert "strict-transport-security" in web_client_https.get(
        "/ui", follow_redirects=False
    ).headers


def test_a_header_the_wrapped_app_already_set_is_not_duplicated():
    """The middleware's one piece of non-trivial logic -- don't clobber a
    header the wrapped app already sent -- has no route in this app that
    sets any of the five, so nothing else here exercises it.

    Sent mixed-case on purpose (round 2 finding): ASGI header names are
    lowercase by convention, not guarantee, and headers.py's `present` set
    lower()s both sides to match. Lowercase-only input here would leave the
    `.lower()` call free to be deleted without failing this test."""
    from starlette.testclient import TestClient

    from strata_kb.web.headers import SecurityHeadersMiddleware

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"X-Frame-Options", b"SAMEORIGIN")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    resp = TestClient(SecurityHeadersMiddleware(app)).get("/")
    assert resp.headers.get_list("x-frame-options") == ["SAMEORIGIN"]
