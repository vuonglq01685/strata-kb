"""Security response headers for every path, including redirects and errors.

Outside TokenAuthMiddleware on purpose: its 302 to /ui/login and its 401/429
JSON are responses too, and a header policy with holes at the auth boundary
is the wrong shape. Defence in depth — the escaping in mdrender/Jinja is
what actually stops XSS today; this is what limits the damage if that ever
regresses.
"""
from __future__ import annotations

# style-src allows 'unsafe-inline': the templates carry ~30 inline style=
# attributes plus three <noscript><style> blocks. script-src does NOT —
# that is the directive that matters, and the UI has exactly one external
# script (/ui/static/app.js) and zero inline script. search.html's token
# budget slider and semantic-KNN checkbox used to auto-submit via an inline
# onchange attribute (Task 10 fix round 1 caught this: it would silently
# stop working under this CSP) — they now do it through app.js's delegated
# `change` listener keyed on `data-autosubmit`, which is what keeps this
# statement true. tests/test_templates.py::
# test_web_templates_carry_no_inline_event_handlers guards the regression.
CSP = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    )
)

STATIC_HEADERS = (
    (b"content-security-policy", CSP.encode("ascii")),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
)
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # HSTS only over https: pinning a plain-HTTP dev host for a year is a
        # foot-gun, and a browser ignores the header on http anyway.
        extra = list(STATIC_HEADERS)
        if scope.get("scheme") == "https":
            extra.append(HSTS)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [
                    (k, v) for k, v in extra if k not in present
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)
