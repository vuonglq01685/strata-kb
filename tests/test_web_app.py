from starlette.testclient import TestClient

from center_kb.mcp import ServerConfig, create_http_app
from center_kb.web.app import create_app

TOKEN = "secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _config(fed_hub) -> ServerConfig:
    return ServerConfig(kb_dir=fed_hub / ".kb", hub=str(fed_hub))


def test_root_redirects_to_ui(fed_hub):
    client = TestClient(create_app(_config(fed_hub), TOKEN))
    resp = client.get("/", headers=AUTH, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ui"


def test_api_and_ui_reachable_through_one_app(fed_hub):
    client = TestClient(create_app(_config(fed_hub), TOKEN))
    assert client.get("/api/docs", headers=AUTH).status_code == 200
    assert client.get("/ui", headers=AUTH).status_code == 200


def test_unauthenticated_api_401_ui_redirect(fed_hub):
    client = TestClient(create_app(_config(fed_hub), TOKEN))
    assert client.get("/api/docs").status_code == 401
    resp = client.get("/ui", follow_redirects=False)
    assert resp.status_code == 302


def test_full_http_app_serves_mcp_and_api_together(fed_hub):
    """create_http_app: MCP handshake still works AND /api works on the same app."""
    app = create_http_app(_config(fed_hub), TOKEN)
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
        **AUTH,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    with TestClient(app, base_url="http://localhost:8321") as client:
        resp = client.post("/mcp", json=payload, headers=headers)
        assert resp.status_code == 200
        assert "serverInfo" in resp.text
        assert client.get("/api/health").status_code == 200
        assert client.get("/ui", headers=AUTH).status_code == 200
