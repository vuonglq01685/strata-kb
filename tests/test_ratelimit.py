"""Rate limiting + auth-failure logging: brute-force defense-in-depth and an
audit trail for unauthorized attempts (OWASP A09)."""
from __future__ import annotations

import logging

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from strata_kb.web.auth import TokenAuthMiddleware
from strata_kb.web.ratelimit import SlidingWindowLimiter


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
    with caplog.at_level(logging.WARNING, logger="strata_kb.web.auth"):
        resp = c.get("/api/x", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401
    assert "/api/x" in caplog.text
    assert "unauthorized" in caplog.text.lower()


def test_middleware_does_not_log_browser_redirect(caplog):
    """Anonymous browser hit on /ui is a normal flow (302), not an attack signal."""
    c = _app_behind_auth()
    with caplog.at_level(logging.WARNING, logger="strata_kb.web.auth"):
        resp = c.get("/ui", follow_redirects=False)
    assert resp.status_code == 302
    assert caplog.text == ""


# ---- F-D12 item 4: trusted_proxies_from_env is the single parser shared by
# the intake route (intake.intake_config_from_env) and the web UI login
# limiter (web.ui.login_post) -- see intake.py's test_trusted_proxies_env_*
# for the original per-caller coverage this now backs.


def test_trusted_proxies_from_env_defaults_to_zero(monkeypatch):
    from strata_kb.web import ratelimit

    monkeypatch.delenv("STRATA_KB_TRUSTED_PROXIES", raising=False)
    assert ratelimit.trusted_proxies_from_env() == 0


def test_trusted_proxies_from_env_parses_a_valid_value(monkeypatch):
    from strata_kb.web import ratelimit

    monkeypatch.setenv("STRATA_KB_TRUSTED_PROXIES", "2")
    assert ratelimit.trusted_proxies_from_env() == 2


def test_trusted_proxies_from_env_non_numeric_exits_loudly(monkeypatch):
    from strata_kb.web import ratelimit

    monkeypatch.setenv("STRATA_KB_TRUSTED_PROXIES", "not-a-number")
    with pytest.raises(SystemExit) as exc:
        ratelimit.trusted_proxies_from_env()
    assert "STRATA_KB_TRUSTED_PROXIES" in str(exc.value)
    assert "not-a-number" in str(exc.value)


def test_trusted_proxies_from_env_negative_exits_loudly(monkeypatch):
    """Parses fine under plain int() but client_key treats it the same as
    0 (header ignored) -- the same silent defeat the loud failure exists to
    prevent, so it must be rejected too, not just non-numeric garbage."""
    from strata_kb.web import ratelimit

    monkeypatch.setenv("STRATA_KB_TRUSTED_PROXIES", "-1")
    with pytest.raises(SystemExit) as exc:
        ratelimit.trusted_proxies_from_env()
    assert "STRATA_KB_TRUSTED_PROXIES" in str(exc.value)
