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
    resp = _client().get("/mcp", headers={"Authorization": "Bearer sai"})
    assert resp.status_code == 401


def test_correct_token_passes():
    resp = _client().get("/mcp", headers={"Authorization": "Bearer secret-token"})
    assert resp.status_code == 200
    assert resp.text == "ok"


# --- F3: app HTTP thật (FastMCP streamable_http_app), không phải dummy app ---


def test_http_initialize_handshake_real_app(fixture_kb):
    """create_http_app thật nhận request MCP `initialize` qua middleware bearer.

    Dùng TestClient với lifespan (`with TestClient(app) as client`) để
    session manager của FastMCP khởi động — nếu không, request treo/lỗi vì
    session manager chưa chạy. Host header phải khớp allowlist DNS-rebinding
    mặc định của FastMCP ("localhost:*"), nên dùng base_url có port rõ ràng.
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

        # sai token trên app thật (không phải dummy) → middleware vẫn chặn 401
        bad_headers = {**headers, "Authorization": "Bearer sai"}
        resp_bad = client.post("/mcp", json=payload, headers=bad_headers)
        assert resp_bad.status_code == 401
