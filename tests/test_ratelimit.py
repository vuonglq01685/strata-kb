"""Rate limiting + auth-failure logging: brute-force defense-in-depth and an
audit trail for unauthorized attempts (OWASP A09)."""
from __future__ import annotations

import logging

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from center_kb.web.auth import TokenAuthMiddleware
from center_kb.web.ratelimit import SlidingWindowLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestSlidingWindowLimiter:
    def test_allows_up_to_max_then_blocks(self):
        limiter = SlidingWindowLimiter(max_attempts=3, window_seconds=60)
        assert all(limiter.allow("1.2.3.4") for _ in range(3))
        assert not limiter.allow("1.2.3.4")

    def test_keys_are_independent(self):
        limiter = SlidingWindowLimiter(max_attempts=1, window_seconds=60)
        assert limiter.allow("a")
        assert not limiter.allow("a")
        assert limiter.allow("b")

    def test_window_expiry_frees_slots(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(max_attempts=2, window_seconds=60, clock=clock)
        assert limiter.allow("k")
        assert limiter.allow("k")
        assert not limiter.allow("k")
        clock.now += 61
        assert limiter.allow("k")


def _app_behind_auth():
    async def api(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/api/x", api, methods=["GET"])])
    return TestClient(TokenAuthMiddleware(app, token="tok"))


def test_middleware_logs_unauthorized_api_hit(caplog):
    c = _app_behind_auth()
    with caplog.at_level(logging.WARNING, logger="center_kb.web.auth"):
        resp = c.get("/api/x", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401
    assert "/api/x" in caplog.text
    assert "unauthorized" in caplog.text.lower()


def test_middleware_does_not_log_browser_redirect(caplog):
    """Anonymous browser hit on /ui is a normal flow (302), not an attack signal."""
    c = _app_behind_auth()
    with caplog.at_level(logging.WARNING, logger="center_kb.web.auth"):
        resp = c.get("/ui", follow_redirects=False)
    assert resp.status_code == 302
    assert caplog.text == ""
