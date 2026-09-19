from __future__ import annotations

import hashlib
import hmac
import logging
import time

from starlette.requests import Request

from center_kb.web.ratelimit import client_key

logger = logging.getLogger("center_kb.web.auth")

COOKIE_NAME = "center_kb_session"
# 12 h: long enough for a working day, short enough that a cookie copied off
# a machine stops working without an operator having to rotate the token.
SESSION_MAX_AGE = 43200
# Exact intake paths only — no /intake/ prefix wildcard, so a future intake
# route is auth-gated by default. publish + manifest enforce OIDC themselves;
# status is public by design (zero-secret dev polling, keyed by rid+commit).
EXEMPT_PATHS = (
    "/api/health",
    "/ui/login",
    "/ui/logout",
    "/intake/publish",
    "/intake/manifest",
    "/intake/status",
)
EXEMPT_PREFIXES = ("/ui/static/",)


def make_session(token: str, now: float | None = None) -> str:
    """`<issued-at>.<hmac_sha256(token, issued-at)>`.

    The cookie is derived from the token instead of being the token (M4):
    /api and /mcp accept the token, so a cookie that WAS the token made
    every browser session an admin-equivalent credential at rest. Stateless
    on purpose — a server-side store would add a second sweeper to bound
    and would log everyone out on restart.
    """
    issued = int(now if now is not None else time.time())
    sig = hmac.new(
        token.encode("utf-8"), str(issued).encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{issued}.{sig}"


def verify_session(value: str, token: str, now: float | None = None) -> bool:
    issued_raw, _, sig = value.partition(".")
    if not sig or not sig.isascii() or not issued_raw.isdecimal() or not issued_raw.isascii():
        return False
    expected = hmac.new(
        token.encode("utf-8"), issued_raw.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    age = (now if now is not None else time.time()) - int(issued_raw)
    return 0 <= age <= SESSION_MAX_AGE


def is_authorized_request(request, token: str) -> bool:
    """The Request-level twin of TokenAuthMiddleware._authorized -- for code
    that has a Starlette Request (not a bare ASGI scope) and needs the same
    verdict. _authorized DELEGATES here (fix round 1, Critical) rather than
    re-parsing, so there is one cookie parser for both, not a twin someone
    can drift out of sync: a second hand-rolled parser (stdlib SimpleCookie,
    which _authorized used to carry) disagreed with Starlette's own
    `request.cookies` (cookie_parser) on 8 of 26 measured real Cookie-header
    shapes, in both directions.

    Fix round 3 (Critical): this was ALSO called directly from api.py's
    /api/health handler to vary its response body by auth. Don't do that
    again for an auth-exempt route -- /api/health sits in EXEMPT_PATHS, so
    TokenAuthMiddleware's rate limiter never runs for it; an auth-varying
    body there let a caller compare guesses against the token at unmetered,
    full speed (measured: 20/20 wrong guesses -> 200, limiter never touched)
    -- a strictly worse channel than the duplicate-header ones fixed above,
    since it needs no header trickery at all. This function is only safe to
    call from a path the middleware itself meters (i.e. not in EXEMPT_PATHS/
    EXEMPT_PREFIXES)."""
    auth_header = request.headers.get("authorization", "")
    try:
        if hmac.compare_digest(auth_header, f"Bearer {token}"):
            return True
    except TypeError:
        return False
    return verify_session(request.cookies.get(COOKIE_NAME, ""), token)


def cookie_is_secure(request, trusted_proxies: int = 0) -> bool:
    """https on the wire, or an X-Forwarded-Proto we are configured to
    believe. No CENTER_KB_HTTP_INSECURE_COOKIE knob: CENTER_KB_TRUSTED_PROXIES
    already declares whether a proxy in front is ours to trust, and a second
    flag for the same fact would let them disagree.

    Right-anchored, matching ratelimit.client_key's X-Forwarded-For
    convention: an appending trusted proxy chain writes its own observation
    onto the END of the header, so the hop that matters is the
    trusted_proxies-th from the right, not the first (leftmost) entry --
    which a client in front of the chain can set to whatever it likes.
    Fix round 1: a forged leftmost entry can only push Secure ON (the
    scheme == "https" branch above wins unconditionally, so it can never be
    spoofed OFF) -- self-DoS via a dropped cookie, not a downgrade -- but
    reading one trusted-hop header leftmost and the other right-anchored in
    the same file is the kind of inconsistency that bites later."""
    if request.url.scheme == "https":
        return True
    if trusted_proxies <= 0:
        return False
    protos = [
        p.strip().lower()
        for v in request.headers.getlist("x-forwarded-proto")
        for p in v.split(",")
        if p.strip()
    ]
    return len(protos) >= trusted_proxies and protos[-trusted_proxies] == "https"


class TokenAuthMiddleware:
    """Accept 'Authorization: Bearer <token>' OR the center_kb_session cookie.

    Unauthorized: browser-facing paths (/, /ui*) get a 302 to /ui/login;
    everything else (API, MCP) gets 401 JSON.
    """

    def __init__(self, app, token: str, limiter=None, trusted_proxies: int = 0) -> None:
        self.app = app
        self.token = token
        # The SAME limiter instance the login form uses (app.py builds one and
        # injects it into both). Separate buckets would leave the bypass M6
        # describes open in the other direction: spend on the header, retry on
        # the form.
        self.limiter = limiter
        self.trusted_proxies = trusted_proxies

    def _authorized(self, scope) -> bool:
        # Delegates to is_authorized_request instead of re-parsing: a second
        # cookie parser here is exactly the drift class that helper's
        # docstring warns about (fix round 1, Critical). Request(scope) with
        # no receive is enough -- headers/cookies need no body read (same
        # pattern already used below in __call__).
        return is_authorized_request(Request(scope), self.token)

    def _credential_presented(self, scope) -> bool:
        """Whether the request carried ANY credential (an Authorization
        header or a center_kb_session cookie), valid or not -- gates the
        rate limiter.

        Fix round 1 (Critical): M6 is "a failed attempt at the shared
        secret" -- absence of a credential is not an attempt at it. Before
        this gate, the limiter counted every anonymous browser hit
        (including the automatic /favicon.ico every browser fires), so 5
        ordinary page views from a logged-out visitor -- zero bad tokens,
        zero login attempts -- locked out the FIRST subsequent login POST
        carrying the correct token.

        Fix round 1 (Critical): the cookie check MUST use the same parser as
        _authorized (Request.cookies / Starlette's cookie_parser), not
        SimpleCookie. Task 11's re-review established the invariant
        `_authorized ⟹ _credential_presented` -- if this stayed on
        SimpleCookie after _authorized moved off it, a Cookie header
        SimpleCookie rejects but cookie_parser accepts would authorize
        without ever being counted as a credential attempt, reopening an
        unlimited-retry channel at the shared secret.

        Fix round 2 (Critical): the Authorization header read MUST also use
        the same first-duplicate-wins semantics as _authorized (Starlette's
        Headers.get, via Request(scope)) -- the old _decode_headers dict
        comprehension was last-duplicate-wins. A guess sent as
        `Authorization: Bearer <guess>` plus a second, empty `Authorization:`
        header (two distinct entries a real ASGI server delivers verbatim)
        made _authorized compare the first (the real guess) while this method
        saw only the second (empty, falsy) -- the guess was evaluated but
        never charged to the limiter: an unlimited-rate brute-force channel.
        One Request(scope) instance now backs both header reads in this
        method, and it is built fresh from the same scope _authorized used,
        so the two can no longer disagree about which duplicate is "the"
        Authorization header."""
        request = Request(scope)
        if request.headers.get("authorization", ""):
            return True
        return request.cookies.get(COOKIE_NAME) is not None

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
        if self._credential_presented(scope):
            # Request(scope) with no receive is enough for headers + client;
            # we never read the body here. Reuses client_key so the header
            # path and the login form agree on what a client IS,
            # trusted-proxy hops included.
            key = client_key(Request(scope), self.trusted_proxies)
            limited = self.limiter is not None and not self.limiter.allow(key)
            if limited:
                logger.warning("auth rate-limited for %s on %s", key, path)
                if path == "/" or path.startswith("/ui"):
                    # Same lockout-notice class as login_post's 429/413
                    # (ui.py, L22/L23): a caching intermediary or the
                    # browser's own bfcache serving this stale after the
                    # window clears would wrongly keep showing "locked out".
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 429,
                            "headers": [
                                (b"content-type", b"text/html; charset=utf-8"),
                                (b"cache-control", b"no-store"),
                            ],
                        }
                    )
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b"<h1>Too many attempts</h1><p>Try again later.</p>",
                        }
                    )
                    return
                await send(
                    {
                        "type": "http.response.start",
                        "status": 429,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {"type": "http.response.body", "body": b'{"error": "too many attempts"}'}
                )
                return
        if path == "/" or path.startswith("/ui"):
            # anonymous browser hit — normal flow, redirect without logging.
            #
            # Fix (final review item 1): also clear center_kb_session here.
            # SESSION_MAX_AGE (12h) guarantees every user's own cookie ages
            # out mid-day; without this, the browser keeps resending the
            # dead-but-real cookie on every page view, _credential_presented
            # charges each one (M6, above), and 5 requests -- two or three
            # page opens -- exhausts the budget and 429s the NEXT login POST,
            # even with the correct token. Chose clearing over teaching
            # verify_session to distinguish aged-out-but-signed from forged:
            # one header at the single redirect every unauthenticated /ui
            # hit already funnels through, vs. threading a 3-way verdict
            # through verify_session/_credential_presented/is_authorized_
            # request and their tests. Charging above already happened
            # before this line, so this cannot open a retry channel -- a
            # forged/garbage cookie a scripted attacker resends manually
            # (ignoring Set-Cookie, as a script can) is still charged every
            # time; only a real browser's dead cookie stops being resent.
            headers = [
                (b"location", b"/ui/login"),
                (
                    b"set-cookie",
                    (
                        f"{COOKIE_NAME}=; Path=/; Max-Age=0; "
                        "Expires=Thu, 01 Jan 1970 00:00:00 GMT"
                    ).encode("ascii"),
                ),
            ]
            await send(
                {
                    "type": "http.response.start",
                    "status": 302,
                    "headers": headers,
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return
        client = scope.get("client")
        logger.warning(
            "unauthorized request: %s %s from %s",
            scope.get("method", "?"),
            path,
            client[0] if client else "unknown",
        )
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
