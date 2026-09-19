# src/strata_kb/web/ratelimit.py
"""In-process sliding-window rate limiter — no external dependency.

Defense-in-depth for the shared-secret login and the intake surface: the
default token has 192-bit entropy, but an operator may configure a weaker
one, and unauthorized attempts need a cost. Per-process state is enough for
the single-instance deployments this server targets.
"""
from __future__ import annotations

import ipaddress
import os
import threading
import time
from collections import deque

# When the key table grows past this, empty entries are swept — bounds memory
# against an attacker rotating source IPs.
_SWEEP_THRESHOLD = 4096

LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 60.0
INTAKE_MAX_ATTEMPTS = 30
INTAKE_WINDOW_SECONDS = 60.0


def trusted_proxies_from_env() -> int:
    """STRATA_KB_TRUSTED_PROXIES -> the number of X-Forwarded-For hops to
    trust in `client_key`. The single parser for BOTH rate limiters that key
    on client identity -- the intake route (via
    `intake.intake_config_from_env` -> `IntakeConfig.trusted_proxies`) and
    the web UI login limiter (`web.ui.login_post`, which has no
    `IntakeConfig` to read: `ui.build_routes` only receives `ServerConfig`).
    One parser, one set of rules, so the two limiters cannot drift.

    This server disables uvicorn's own X-Forwarded-For handling
    (`proxy_headers=False`) unconditionally, which makes this the SINGLE
    authority on X-Forwarded-For for the whole app -- leaving it at the
    default `0` behind a reverse proxy means every request (intake AND
    login) keys on the proxy's own address, collapsing each limiter into
    one shared bucket that any client can exhaust for everyone. See
    docs/deploy-remote-mcp.md.

    Raises SystemExit (no traceback, matching mcp.py's other operator-config
    errors) rather than silently falling back to 0 when the value is
    present but invalid -- a silent fallback would silently defeat an
    operator's declared trusted-proxy count for both limiters at once.

    str.isdecimal() (not int()'s own parsing) gates the value: int() also
    accepts a leading '+', underscores as digit-group separators ("1_0" ->
    10), and surrounding whitespace -- none of that reads as an
    operator-intended proxy count. isdecimal() also rejects '-', so a
    negative value (which int() would parse fine, and which `client_key`
    treats the same as 0 -- the same silent header-ignored defeat this loud
    failure exists to prevent) is refused here too.
    """
    raw = os.environ.get("STRATA_KB_TRUSTED_PROXIES", "0")
    if not raw.isdecimal():
        raise SystemExit(
            "STRATA_KB_TRUSTED_PROXIES must be a non-negative integer, got "
            f"'{raw}' -- unset it to disable X-Forwarded-For trust (default "
            "0), or set it to the number of trusted reverse proxies in "
            "front of this server, e.g. STRATA_KB_TRUSTED_PROXIES=1"
        )
    return int(raw)


def client_key(request, trusted_proxies: int = 0) -> str:
    """The rate-limit key for a request.

    trusted_proxies=0 (the default) keys on the socket peer and ignores
    X-Forwarded-For entirely, so the key cannot be spoofed. When an operator
    declares N trusted proxies in front of the server, the client is the
    N-th entry from the right of X-Forwarded-For -- the last hop the trusted
    chain did not write. A header shorter than the declared chain is not
    trustworthy, so it falls back to the peer.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_proxies <= 0:
        return peer
    # RFC 9110 S5.3: repeated field lines are semantically one comma-joined
    # line. request.headers.get() returns only the first line -- a proxy that
    # appends X-Forwarded-For as a SEPARATE header line (Traefik and several
    # CDNs/ALBs do; nginx's $proxy_add_x_forwarded_for does not) would let a
    # client's own forged line survive untouched while the trusted proxy's
    # line sits unread. getlist() + a per-line split collects every hop
    # across every line before indexing from the right.
    hops = [
        h.strip()
        for value in request.headers.getlist("x-forwarded-for")
        for h in value.split(",")
        if h.strip()
    ]
    if len(hops) < trusted_proxies:
        return peer
    hop = hops[-trusted_proxies]
    try:
        # The selected hop becomes a dict key in SlidingWindowLimiter and is
        # logged verbatim for an unauthenticated caller -- an XFF hop that
        # does not even parse as an IP is malformed by definition and not
        # trustworthy as a rate-limit identity. Fall back to the peer rather
        # than admit arbitrary attacker-supplied text (unbounded length,
        # no charset restriction beyond h11's header-value rules).
        ipaddress.ip_address(hop)
    except ValueError:
        return peer
    return hop


class SlidingWindowLimiter:
    """allow(key) -> False once `max_attempts` calls landed inside the window."""

    def __init__(
        self,
        max_attempts: int,
        window_seconds: float,
        clock=time.monotonic,
    ) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        cutoff = now - self._window
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self._max:
                return False
            hits.append(now)
            if len(self._hits) > _SWEEP_THRESHOLD:
                self._sweep(cutoff)
            return True

    def _sweep(self, cutoff: float) -> None:
        """Drop keys whose hits all expired. Caller holds the lock."""
        stale = [
            key
            for key, hits in self._hits.items()
            if not hits or hits[-1] <= cutoff
        ]
        for key in stale:
            del self._hits[key]
