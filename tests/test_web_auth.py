import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from aero_kb.web.auth import COOKIE_NAME, TokenAuthMiddleware


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
    c = _client()
    c.cookies.set(COOKIE_NAME, "secret-token")
    assert c.get("/api/docs").status_code == 200


def test_wrong_cookie_401():
    c = _client()
    c.cookies.set(COOKIE_NAME, "wrong")
    assert c.get("/api/docs").status_code == 401


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
    resp = _client().get("/api/docs", headers={"Cookie": "aero_kb_token=café".encode()})
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
    from aero_kb.mcp import BearerAuthMiddleware

    assert BearerAuthMiddleware is TokenAuthMiddleware
