"""claimbeat -- heartbeat a claim while a task runs, beside the main loop.

Same shape as `QaThread`: a daemon thread that waits on an Event, so `stop()`
wakes it at once. A lost claim sets `lost`; the runner checks it when the task
ends (the task itself is not interrupted).
"""

from __future__ import annotations

import logging
import threading

from strata_kb.autorun.claims import RunnerClaims

logger = logging.getLogger("strata_kb.autorun.claimbeat")


class ClaimBeat:
    def __init__(self, claims: RunnerClaims, interval: int) -> None:
        self._claims, self._interval = claims, interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lost = threading.Event()

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def start(self, ticket: str) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(ticket,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _loop(self, ticket: str) -> None:
        while not self._stop.wait(self._interval):
            try:
                if not self._claims.beat(ticket):
                    self._lost.set()
                    return
            except Exception as exc:  # noqa: BLE001 -- a heartbeat must never kill the thread's owner
                logger.warning("claim heartbeat on %s failed: %s", ticket, exc)
