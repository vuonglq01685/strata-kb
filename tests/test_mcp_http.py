import pytest

starlette = pytest.importorskip("starlette")

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from aero_kb.mcp import BearerAuthMiddleware


def _dummy_app():
    async def ok(request):
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/mcp", ok, methods=["GET", "POST"])])


def _client(token="secret-token"):
    return TestClient(BearerAuthMiddleware(_dummy_app(), token))


def test_missing_token_401():
    resp = _client().get("/mcp")
    assert resp.status_code == 401


def test_wrong_token_401():
    resp = _client().get("/mcp", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_correct_token_passes():
    resp = _client().get("/mcp", headers={"Authorization": "Bearer secret-token"})
    assert resp.status_code == 200
    assert resp.text == "ok"


# --- F3: real HTTP app (FastMCP streamable_http_app), not the dummy app ---


def test_http_initialize_handshake_real_app(fixture_kb):
    """The real create_http_app accepts an MCP `initialize` request through the bearer middleware.

    Uses TestClient with lifespan (`with TestClient(app) as client`) so
    FastMCP's session manager starts up — otherwise the request hangs/errors
    because the session manager isn't running. The Host header must match
    FastMCP's default DNS-rebinding allowlist ("localhost:*"), hence a
    base_url with an explicit port.
    """
    from aero_kb.mcp import ServerConfig, create_http_app

    app = create_http_app(ServerConfig(kb_dir=fixture_kb), "secret-token")
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    headers = {
        "Authorization": "Bearer secret-token",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    with TestClient(app, base_url="http://localhost:8321") as client:
        resp = client.post("/mcp", json=payload, headers=headers)
        assert resp.status_code == 200
        assert "serverInfo" in resp.text

        # wrong token on the real app (not the dummy) → middleware still blocks with 401
        bad_headers = {**headers, "Authorization": "Bearer wrong"}
        resp_bad = client.post("/mcp", json=payload, headers=bad_headers)
        assert resp_bad.status_code == 401
