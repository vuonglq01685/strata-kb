"""wait — block until the auto loop's progress changes, stops, or time is up.

Cloud: the Claude Code session keeps itself alive by re-arming `kb auto wait`
as a background command; each return wakes it with one status line.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from strata_kb.autorun import state as autostate
from strata_kb.autorun.lock import running_pid


def _label(state: autostate.AutoState) -> str:
    return f"{state.task or 'idle'}, attempt {state.attempts}"


def wait_for_change(
    kb_dir: Path,
    max_seconds: int,
    interval: int = 30,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> str:
    start = now()
    first: tuple | None = None
    while True:
        # pid first: a loop that writes stop_reason then exits must still show it
        pid = running_pid(kb_dir)
        state = autostate.load(kb_dir)
        if pid is None:
            if state.stop_reason:
                return f"stopped: {state.stop_reason}"
            return "not running — see .kb/auto/run.log"
        key = (state.task, state.attempts, state.waiting_on)
        if first is None:
            first = key
        elif key != first:
            line = f"progress: {_label(state)}"
            if state.waiting_on:
                line += ", waiting on " + ",".join(f"Q{n}" for n in state.waiting_on)
            return line
        remaining = max_seconds - (now() - start)
        if remaining <= 0:
            return f"still running: {_label(state)}"
        sleep(min(interval, remaining))
