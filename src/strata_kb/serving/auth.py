"""auth — bearer-token and session-cookie auth for the HTTP servers.

`TokenAuthMiddleware` wraps the one ASGI app `web.app.create_app` builds (MCP
over HTTP, /api, /ui, /intake). It accepts `Authorization: Bearer <token>` or
the `strata_kb_session` cookie (`make_user_session` / `read_user_session`: an
HMAC under the accounts session key naming a user, never the token),
rate-limits requests that present a credential, and lets EXEMPT_PATHS
through. Every verdict goes through `_authorize`, so there is one cookie
parser and one header reader.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import sqlite3
import time
from contextvars import ContextVar
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from strata_kb.serving.accounts import Accounts, User, password_version
from strata_kb.serving.ratelimit import client_key

# Logger name kept from before the move to serving/ (1.15.1): operators
# filter on it.
logger = logging.getLogger("strata_kb.web.auth")

COOKIE_NAME = "strata_kb_session"
# 12 h: long enough for a working day, short enough that a cookie copied off
# a machine stops working without an operator having to rotate the token.
SESSION_MAX_AGE = 43200
# Exact intake paths only — no /intake/ prefix wildcard, so a future intake
# route is auth-gated by default. publish + manifest enforce OIDC themselves;
# status answers {state, pr_url} without a token (zero-secret dev polling,
# keyed by rid+commit) and adds `detail` only for the OIDC caller.
EXEMPT_PATHS = (
    "/api/health",
    "/ui/login",
    "/ui/logout",
    "/intake/publish",
    "/intake/manifest",
    "/intake/status",
)
EXEMPT_PREFIXES = ("/ui/static/",)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64url(text: str) -> bytes | None:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError:
        return None


def _sign(key: bytes, payload: str) -> str:
    return hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()


def make_user_session(key: bytes, user: User, now: float | None = None) -> str:
    """`<issued>.<b64url(username)>.<password_version>.<hmac>`.

    Signed with the accounts store's own session key, never the bearer token:
    /api and /mcp accept the token, so a cookie derived from it would let
    anyone holding the token mint a session as any user. The password
    version rides in the cookie so changing a password ends every session of
    that user without a server-side session table to sweep (or to lose on
    restart).
    """
    issued = int(now if now is not None else time.time())
    name = _b64url(user.username.encode("utf-8", "surrogatepass"))
    payload = f"{issued}.{name}.{password_version(user.password_hash)}"
    return f"{payload}.{_sign(key, payload)}"


def read_user_session(
    value: str, key: bytes, now: float | None = None
) -> tuple[str, str] | None:
    """`(username, password_version)` when the signature and age are valid."""
    parts = value.split(".")
    if len(parts) != 4 or not value.isascii():
        return None
    issued_raw, name, version, sig = parts
    if not issued_raw.isdecimal():
        return None
    if not hmac.compare_digest(sig, _sign(key, ".".join(parts[:3]))):
        return None
    age = (now if now is not None else time.time()) - int(issued_raw)
    raw_name = _unb64url(name)
    if raw_name is None or not 0 <= age <= SESSION_MAX_AGE:
        return None
    return raw_name.decode("utf-8", "surrogatepass"), version


@dataclass(frozen=True)
class SessionAuth:
    """What the middleware needs to turn a cookie into a live account."""

    key: bytes
    accounts: Accounts

    def user_for(self, cookie_value: str) -> User | None:
        parsed = read_user_session(cookie_value, self.key)
        if parsed is None:
            return None
        username, version = parsed
        try:
            user = self.accounts.get(username)
        except (sqlite3.Error, UnicodeError):
            # A locked or unreadable store means "not logged in", never a 500.
            logger.exception("session lookup failed")
            return None
        if user is None or not hmac.compare_digest(
            password_version(user.password_hash), version
        ):
            return None
        return user


def current_user(request) -> User | None:
    """The logged-in account, or None (anonymous, or a bearer-token request)."""
    return getattr(request.state, "user", None)


# The middleware runs in the same task as the routes (and anyio copies the
# context into sync handlers' threads), so page code that has no Request in
# hand -- _shell_ctx -- can still ask who is looking.
_REQUEST_USER: ContextVar[User | None] = ContextVar("strata_kb_user", default=None)


def request_user() -> User | None:
    return _REQUEST_USER.get()


def _authorize(request, token: str, session: SessionAuth | None) -> User | bool:
    """False when unauthorized, True for a bearer request, else the User."""
    auth_header = request.headers.get("authorization", "")
    try:
        if hmac.compare_digest(auth_header, f"Bearer {token}"):
            return True
    except TypeError:
        return False
    if session is None:
        return False
    return session.user_for(request.cookies.get(COOKIE_NAME, "")) or False


def is_authorized_request(
    request, token: str, session: SessionAuth | None = None
) -> bool:
    """The Request-level twin of TokenAuthMiddleware._authorized -- for code
    that has a Starlette Request (not a bare ASGI scope) and needs the same
    verdict. Both go through `_authorize` rather than re-parsing, so there is
    one cookie parser for both, not a twin someone can drift out of sync: a
    second hand-rolled parser (stdlib SimpleCookie) disagreed with
    Starlette's own `request.cookies` (cookie_parser) on 8 of 26 measured
    real Cookie-header shapes, in both directions.

    Authorized means a bearer token OR a session cookie that names a live
    account whose password has not changed since the cookie was issued.

    Do not call this from an auth-exempt route to vary its response by auth
    (e.g. /api/health's body). Such a route sits in EXEMPT_PATHS, so
    TokenAuthMiddleware's rate limiter never runs for it; an auth-varying
    body there lets a caller compare guesses against the token at unmetered,
    full speed (measured: 20/20 wrong guesses -> 200, limiter never touched)
    -- a strictly worse channel than the duplicate-header ones
    _credential_presented guards against, since it needs no header trickery
    at all. This function is only safe to call from a path the middleware
    itself meters (i.e. not in EXEMPT_PATHS/EXEMPT_PREFIXES)."""
    return _authorize(request, token, session) is not False


def cookie_is_secure(request, trusted_proxies: int = 0) -> bool:
    """https on the wire, or an X-Forwarded-Proto we are configured to
    believe. No STRATA_KB_HTTP_INSECURE_COOKIE knob: STRATA_KB_TRUSTED_PROXIES
    already declares whether a proxy in front is ours to trust, and a second
    flag for the same fact would let them disagree.

    Right-anchored, matching ratelimit.client_key's X-Forwarded-For
    convention: an appending trusted proxy chain writes its own observation
    onto the END of the header, so the hop that matters is the
    trusted_proxies-th from the right, not the first (leftmost) entry --
    which a client in front of the chain can set to whatever it likes.
    A forged leftmost entry could only push Secure ON (the
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
    """Accept 'Authorization: Bearer <token>' OR the strata_kb_session cookie.

    Unauthorized: browser-facing paths (/, /ui*) get a 302 to /ui/login;
    everything else (API, MCP) gets 401 JSON.
    """

    def __init__(
        self,
        app,
        token: str,
        limiter=None,
        trusted_proxies: int = 0,
        session: SessionAuth | None = None,
    ) -> None:
        self.app = app
        self.token = token
        self.session = session
        # The SAME limiter instance the login form uses (app.py builds one and
        # injects it into both). Separate buckets would leave the bypass
        # _credential_presented describes open in the other direction: spend
        # on the header, retry on the form.
        self.limiter = limiter
        self.trusted_proxies = trusted_proxies

    def _verdict(self, scope) -> User | bool:
        # Shares _authorize with is_authorized_request instead of re-parsing:
        # a second cookie parser here is exactly the drift class that
        # helper's docstring warns about. Request(scope) with no receive is
        # enough -- headers/cookies need no body read (same pattern already
        # used below in __call__). A User means a cookie session; True is a
        # bearer request, which never carries an account.
        return _authorize(Request(scope), self.token, self.session)

    def _authorized(self, scope) -> bool:
        return self._verdict(scope) is not False

    def _credential_presented(self, scope) -> bool:
        """Whether the request carried ANY credential (an Authorization
        header or a strata_kb_session cookie), valid or not -- gates the
        rate limiter.

        The limiter charges "a failed attempt at the shared secret" --
        absence of a credential is not an attempt at it. Without this gate,
        the limiter counts every anonymous browser hit (including the
        automatic /favicon.ico every browser fires), so 5 ordinary page views
        from a logged-out visitor -- zero bad tokens, zero login attempts --
        lock out the FIRST subsequent login POST carrying the correct token.

        The cookie check MUST use the same parser as _authorized
        (Request.cookies / Starlette's cookie_parser), not SimpleCookie. The
        invariant is `_authorized ⟹ _credential_presented`: with two parsers,
        a Cookie header SimpleCookie rejects but cookie_parser accepts would
        authorize without ever being counted as a credential attempt,
        opening an unlimited-retry channel at the shared secret.

        The Authorization header read MUST also use the same
        first-duplicate-wins semantics as _authorized (Starlette's
        Headers.get, via Request(scope)); a last-duplicate-wins dict
        comprehension does not. A guess sent as `Authorization: Bearer
        <guess>` plus a second, empty `Authorization:` header (two distinct
        entries a real ASGI server delivers verbatim) would make _authorized
        compare the first (the real guess) while this method saw only the
        second (empty, falsy) -- the guess evaluated but never charged to the
        limiter: an unlimited-rate brute-force channel. One Request(scope)
        instance backs both header reads in this method, and it is built
        fresh from the same scope _authorized used, so the two cannot
        disagree about which duplicate is "the" Authorization header."""
        request = Request(scope)
        if request.headers.get("authorization", ""):
            return True
        return request.cookies.get(COOKIE_NAME) is not None

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path in EXEMPT_PATHS or any(path.startswith(p) for p in EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return
        # user_for reads sqlite; keep that (and its up-to-10 s lock wait) off
        # the event loop. The credential rules themselves are unchanged.
        verdict = await run_in_threadpool(self._verdict, scope)
        if verdict is not False:
            user = verdict if isinstance(verdict, User) else None
            if user is not None:
                scope.setdefault("state", {})["user"] = user
            reset = _REQUEST_USER.set(user)
            try:
                await self.app(scope, receive, send)
            finally:
                _REQUEST_USER.reset(reset)
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
                    # (ui.py): a caching intermediary or the
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
                    {
                        "type": "http.response.body",
                        "body": b'{"error": "too many attempts"}',
                    }
                )
                return
        if path == "/" or path.startswith("/ui"):
            # anonymous browser hit — normal flow, redirect without logging.
            #
            # Also clear strata_kb_session here. SESSION_MAX_AGE (12h)
            # guarantees every user's own cookie ages out mid-day; without
            # this, the browser keeps resending the dead-but-real cookie on
            # every page view, _credential_presented charges each one (see
            # its docstring), and 5 requests -- two or three
            # page opens -- exhausts the budget and 429s the NEXT login POST,
            # even with the correct token. Chose clearing over teaching
            # read_user_session to distinguish aged-out-but-signed from
            # forged: one header at the single redirect every unauthenticated
            # /ui hit already funnels through, vs. threading a 3-way verdict
            # through read_user_session/_credential_presented/
            # is_authorized_request and their tests. Charging above already happened
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
        await send({"type": "http.response.body", "body": b'{"error": "unauthorized"}'})
