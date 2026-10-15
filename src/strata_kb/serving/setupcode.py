# src/strata_kb/serving/setupcode.py
"""The one-time first-run setup code.

Held in memory only, printed once to the hub log, never written to disk or sent
in a response. Whoever can read the container log can claim the first admin.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import threading

from strata_kb.serving.accounts import Accounts

# Upper-case letters and digits minus the look-alikes 0, O, 1, I.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_HALF = 4

_log = logging.getLogger("strata_kb.setup")


def new_code() -> str:
    chars = [secrets.choice(_ALPHABET) for _ in range(2 * _HALF)]
    return "".join(chars[:_HALF]) + "-" + "".join(chars[_HALF:])


class SetupCode:
    """The live code, or None once used / when users already exist."""

    def __init__(self, code: str | None = None) -> None:
        self._code = code
        self._lock = threading.Lock()

    @property
    def code(self) -> str | None:
        return self._code

    def matches(self, submitted: str) -> bool:
        """Constant-time check; False when no code is active."""
        with self._lock:
            code = self._code
        if code is None:
            return False
        # Bytes, because compare_digest raises on a non-ASCII str.
        got = submitted.strip().upper().encode("utf-8", errors="surrogatepass")
        return hmac.compare_digest(got, code.encode("ascii"))

    def consume(self) -> None:
        with self._lock:
            self._code = None


def start_setup(accounts: Accounts) -> SetupCode:
    """A fresh logged code when the table is empty, else an inert holder."""
    if accounts.count() > 0:
        return SetupCode(None)
    state = SetupCode(new_code())
    _log.warning(
        "No hub account yet — open /ui/setup and enter setup code: %s", state.code
    )
    return state
