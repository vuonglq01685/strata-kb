# src/center_kb/web/ratelimit.py
"""In-process sliding-window rate limiter — no external dependency.

Defense-in-depth for the shared-secret login and the intake surface: the
default token has 192-bit entropy, but an operator may configure a weaker
one, and unauthorized attempts need a cost. Per-process state is enough for
the single-instance deployments this server targets.
"""
from __future__ import annotations

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
