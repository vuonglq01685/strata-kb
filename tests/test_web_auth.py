import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from center_kb.web.auth import COOKIE_NAME, TokenAuthMiddleware, make_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _app():
    async def ok(request):
        return PlainTextResponse("ok")

    routes = [
        Route(path, ok, methods=["GET"])
        for path in ["/", "/mcp", "/api/docs", "/api/health", "/ui", "/ui/login", "/ui/static/style.css"]
    ]
    return Starlette(routes=routes)


def _client():
    return TestClient(TokenAuthMiddleware(_app(), "secret-token"))


def test_api_without_token_401_json():
    resp = _client().get("/api/docs")
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


def test_bearer_header_passes():
    resp = _client().get("/api/docs", headers={"Authorization": "Bearer secret-token"})
    assert resp.status_code == 200


def test_cookie_passes():
    # M4: the cookie is a signed session derived from the token, not the
    # token itself -- a raw token value no longer authorises (see
    # tests/test_web_session.py::test_a_raw_token_cookie_no_longer_authorises).
    c = _client()
    c.cookies.set(COOKIE_NAME, make_session("secret-token"))
    assert c.get("/api/docs").status_code == 200


def test_wrong_cookie_401():
    # A well-formed session signed with the WRONG token must not verify.
    c = _client()
    c.cookies.set(COOKIE_NAME, make_session("wrong-token"))
    assert c.get("/api/docs").status_code == 401


# --- _authorized / _credential_presented parser-agreement table -----------
#
# Fix round 1 (Critical): _authorized parsed Cookie headers with stdlib
# SimpleCookie while auth.is_authorized_request (added for /api/health) used
# Starlette's cookie_parser -- they disagreed on 8/26 measured real
# Cookie-header shapes. Fixed by making _authorized delegate to
# is_authorized_request and moving _credential_presented's cookie read onto
# the same parser.
#
# Fix round 2 (Critical): that fix left the Authorization axis still
# diverging -- _authorized read it via Request.headers.get (Starlette's
# Headers, FIRST duplicate wins), _credential_presented via a dict
# comprehension (LAST duplicate wins). `Authorization: Bearer <guess>` plus a
# second, empty `Authorization:` header (two distinct entries a real ASGI
# server delivers verbatim -- confirmed against the h11 parser uvicorn uses
# here) made _authorized compare the guess while _credential_presented saw
# only the trailing empty value -- the guess was evaluated but never charged
# to the rate limiter: an unlimited-rate brute-force channel. Fixed by
# reading the Authorization header through the same Request(scope) instance
# in both methods.
#
# This table pins BOTH axes so a future parser swap on either side cannot
# reopen either bug silently: for every shape, _authorized(scope) implies
# _credential_presented(scope) -- an evaluated credential must always be a
# charged one. A bare implication is too weak on its own (("Bearer wrong",
# "") scores fine under the implication while being the actual attack -- both
# sides are False), so the table also carries an explicit "charged" column:
# whether a real login-guess value sits in the position _authorized actually
# reads from (its first Authorization entry, or a present Cookie), which
# _credential_presented MUST agree with independent of whether that guess
# happens to be right.

TOKEN = "secret-token"
_VALID_SESSION = make_session(TOKEN)


def _scope(headers: list[tuple[str, str]]) -> dict:
    return {
        "type": "http",
        "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers],
        "path": "/api/docs",
        "client": ("1.2.3.4", 1234),
    }


# (name, headers, expect_authorized, expect_credential_presented)
_PROBE_SHAPES = [
    ("no headers at all", [], False, False),
    ("empty authorization, no cookie", [("authorization", "")], False, False),
    ("Bearer with no token", [("authorization", "Bearer")], False, True),
    ("Bearer with trailing space, no token", [("authorization", "Bearer ")], False, True),
    ("garbage authorization", [("authorization", "garbage-not-bearer")], False, True),
    ("wrong bearer token", [("authorization", "Bearer wrong-token")], False, True),
    ("correct bearer token", [("authorization", f"Bearer {TOKEN}")], True, True),
    ("garbage cookie value", [("cookie", f"{COOKIE_NAME}=garbage")], False, True),
    ("valid session cookie alone", [("cookie", f"{COOKIE_NAME}={_VALID_SESSION}")], True, True),
    (
        "valid cookie + wrong bearer",
        [("authorization", "Bearer wrong"), ("cookie", f"{COOKIE_NAME}={_VALID_SESSION}")],
        True, True,
    ),
    ("empty cookie header", [("cookie", "")], False, False),
    ("cookie header with no equals sign at all", [("cookie", "nonsense")], False, False),
    ("non-ascii authorization", [("authorization", "Bearer ééé")], False, True),
    ("non-ascii cookie value", [("cookie", f"{COOKIE_NAME}=123.café")], False, True),
    (
        "unquoted space in unrelated cookie value",
        [("cookie", f"other=a b; {COOKIE_NAME}={_VALID_SESSION}")],
        True, True,
    ),
    (
        "unterminated quote",
        [("cookie", f'other="abc; {COOKIE_NAME}={_VALID_SESSION}')],
        True, True,
    ),
    (
        "bare token, no equals sign",
        [("cookie", f"justavalue; {COOKIE_NAME}={_VALID_SESSION}")],
        True, True,
    ),
    (
        "doubled semicolons",
        [("cookie", f"other=x;;{COOKIE_NAME}={_VALID_SESSION}")],
        True, True,
    ),
    (
        "space in a cookie name",
        [("cookie", f"my cookie=x; {COOKIE_NAME}={_VALID_SESSION}")],
        True, True,
    ),
    (
        "backslash-escaped quote",
        [("cookie", f'other="a\\"b"; {COOKIE_NAME}={_VALID_SESSION}')],
        True, True,
    ),
    (
        "session cookie first, space-case second",
        [("cookie", f"{COOKIE_NAME}={_VALID_SESSION}; other=a b")],
        True, True,
    ),
    (
        "comma-separated (RFC2965 style)",
        [("cookie", f"foo=bar, {COOKIE_NAME}={_VALID_SESSION}")],
        False, False,
    ),
    # -- duplicate-header class (fix round 2) --
    (
        "duplicate authorization: guess then trailing empty",
        [("authorization", "Bearer wrong"), ("authorization", "")],
        False, True,  # the guess IS evaluated (and rejected) -> must be charged
    ),
    (
        "duplicate authorization: correct token then trailing empty",
        [("authorization", f"Bearer {TOKEN}"), ("authorization", "")],
        True, True,
    ),
    (
        "duplicate authorization: empty then guess",
        [("authorization", ""), ("authorization", "Bearer wrong")],
        # first entry (empty) is what both methods read -- the second
        # duplicate is never consulted by either, so this is NOT the bypass
        # shape (no guess is ever evaluated) and must stay consistent False/False.
        False, False,
    ),
    # -- duplicate Cookie HEADER LINE class (fix round 3, folded in) --
    # Starlette's HTTPConnection.cookies merges ALL "Cookie" header lines
    # (getlist, not first/last-wins) -- the opposite policy from the
    # Authorization axis above. Both _authorized and _credential_presented
    # read cookies through the same request.cookies, so no divergence is
    # possible today; these rows pin that so a future change to either read
    # site can't reopen this class the way round 2 did on Authorization.
    (
        "two separate Cookie header lines, unrelated + valid session",
        [("cookie", "other=x"), ("cookie", f"{COOKIE_NAME}={_VALID_SESSION}")],
        True, True,
    ),
    (
        "two separate Cookie header lines, garbage session then valid session",
        [("cookie", f"{COOKIE_NAME}=garbage"), ("cookie", f"{COOKIE_NAME}={_VALID_SESSION}")],
        # last header LINE wins on a repeated cookie name (dict.update merge
        # order) -> the valid one survives.
        True, True,
    ),
    (
        "two separate Cookie header lines, valid session then garbage",
        [("cookie", f"{COOKIE_NAME}={_VALID_SESSION}"), ("cookie", f"{COOKIE_NAME}=garbage")],
        # the later header LINE overrides the earlier valid one -> not
        # authorized, but a credential (the garbage cookie) was still
        # presented and must still be charged.
        False, True,
    ),
]


def test_authorized_implies_credential_presented_and_charged_guesses_are_charged():
    mw = TokenAuthMiddleware(_app(), TOKEN)
    for name, headers, expect_authorized, expect_charged in _PROBE_SHAPES:
        scope = _scope(headers)
        authorized = mw._authorized(scope)
        charged = mw._credential_presented(scope)
        assert authorized is expect_authorized, f"{name}: _authorized"
        assert charged is expect_charged, f"{name}: _credential_presented"
        # The invariant itself, re-derived per shape rather than trusted from
        # the table: an authorized/evaluated request must always be charged.
        assert (not authorized) or charged, (
            f"{name}: _authorized=True but _credential_presented=False -- "
            "an evaluated credential was not charged to the limiter"
        )


def test_ui_without_token_redirects_to_login():
    resp = _client().get("/ui", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ui/login"


def test_root_without_token_redirects_to_login():
    resp = _client().get("/", follow_redirects=False)
    assert resp.status_code == 302


def test_exempt_paths_pass_without_token():
    c = _client()
    assert c.get("/api/health").status_code == 200
    assert c.get("/ui/login").status_code == 200
    assert c.get("/ui/static/style.css").status_code == 200


def test_mcp_without_token_401():
    assert _client().get("/mcp").status_code == 401


def test_malformed_cookie_header_is_401_not_crash():
    resp = _client().get("/api/docs", headers={"Cookie": ";;=;;garbage"})
    assert resp.status_code == 401


def test_non_ascii_bearer_token_is_401_not_crash():
    # httpx (0.28+) rejects non-ASCII str header values outright, so the
    # non-ASCII bytes are passed directly to reach the ASGI app unmodified.
    resp = _client().get("/api/docs", headers={"Authorization": "Bearer café".encode()})
    assert resp.status_code == 401


def test_non_ascii_cookie_token_is_401_not_crash():
    resp = _client().get(
        "/api/docs", headers={"Cookie": f"{COOKIE_NAME}=café".encode()}
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_invalid_utf8_header_bytes_are_401_not_crash():
    # A lone 0xE9 byte (latin-1 'é') is not valid UTF-8. ASGI header values
    # are raw bytes per HTTP semantics (latin-1), so this must not crash
    # the strict UTF-8 decode in _authorized() with a UnicodeDecodeError.
    #
    # Starlette's TestClient can't be used here: its _TestClientTransport
    # round-trips header values through str (bytes -> latin-1-decoded str
    # -> value.encode() back to bytes), and re-encoding a str always
    # produces valid UTF-8 — so it can never deliver a genuinely invalid
    # UTF-8 byte sequence to the ASGI app, no matter what bytes are passed
    # in. A raw httpx.ASGITransport preserves the exact wire bytes a real
    # ASGI server would deliver, so it's used directly instead.
    transport = httpx.ASGITransport(app=TokenAuthMiddleware(_app(), "secret-token"))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        resp = await client.get(
            "/api/docs", headers={b"authorization": b"Bearer caf\xe9"}
        )
    assert resp.status_code == 401


def test_mcp_module_still_exports_bearer_alias():
    from center_kb.mcp import BearerAuthMiddleware

    assert BearerAuthMiddleware is TokenAuthMiddleware
