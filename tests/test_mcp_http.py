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
