from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from aero_kb.web.auth import COOKIE_NAME, TokenAuthMiddleware


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


def test_mcp_module_still_exports_bearer_alias():
    from aero_kb.mcp import BearerAuthMiddleware

    assert BearerAuthMiddleware is TokenAuthMiddleware
