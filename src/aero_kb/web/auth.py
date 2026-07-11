from __future__ import annotations

import hmac
from http.cookies import CookieError, SimpleCookie

COOKIE_NAME = "aero_kb_token"
EXEMPT_PATHS = ("/api/health", "/ui/login")
EXEMPT_PREFIXES = ("/ui/static/",)


class TokenAuthMiddleware:
    """Accept 'Authorization: Bearer <token>' OR the aero_kb_token cookie.

    Unauthorized: browser-facing paths (/, /ui*) get a 302 to /ui/login;
    everything else (API, MCP) gets 401 JSON.
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    def _authorized(self, scope) -> bool:
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        try:
            if hmac.compare_digest(auth, f"Bearer {self.token}"):
                return True
        except TypeError:
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("cookie", ""))
        except CookieError:
            return False
        morsel = cookie.get(COOKIE_NAME)
        try:
            return morsel is not None and hmac.compare_digest(morsel.value, self.token)
        except TypeError:
            return False

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if (
            path in EXEMPT_PATHS
            or any(path.startswith(p) for p in EXEMPT_PREFIXES)
            or self._authorized(scope)
        ):
            await self.app(scope, receive, send)
            return
        if path == "/" or path.startswith("/ui"):
            await send(
                {
                    "type": "http.response.start",
                    "status": 302,
                    "headers": [(b"location", b"/ui/login")],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b'{"error": "unauthorized"}'}
        )
