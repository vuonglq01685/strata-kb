"""state — the runner's progress file, `.kb/auto/state.json`.

Local only (`.kb/auto/` is git-ignored). `save` writes a temp file beside the
target and `os.replace`s it, so a reader never sees half a file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

_log = logging.getLogger(__name__)

STATE_NAME = "state.json"


@dataclass(frozen=True)
class AutoState:
    task: str | None  # "<skill>:<id>", e.g. "dev-implement-ticket:M-x-US3"
    attempts: int
    waiting_on: tuple[int, ...]
    stop_reason: str | None
    updated_at: str
    last_done: str | None = None  # key of the task that last ended `done`
    same_pick: int = 0  # consecutive picks equal to `last_done`
    # task keys that ended `done` but stayed picked: the picker passes over them
    skipped: tuple[str, ...] = ()
    # "<run id>:<attempt>" of the failed kb-publish run the loop re-ran once
    publish_retry: str | None = None
    # bugs a Dev asked the BA to split: not re-picked until their row is a parent
    waiting_split: tuple[str, ...] = ()
    # "<task key> <pr url>": PRs on code-owned paths parked for a human review
    waiting_review: tuple[str, ...] = ()
    # "<story> <until-epoch>": stories parked until then (tester env wait)
    waiting: tuple[str, ...] = ()
    # epoch until which the tester env is not retried
    env_wait_until: float | None = None
    # "<task key> <count>": tester tasks that ended `incomplete`, per task
    incomplete: tuple[str, ...] = ()


_WAITING_RE = re.compile(r"\S+ \d+")


def _empty() -> AutoState:
    return AutoState(
        task=None, attempts=0, waiting_on=(), stop_reason=None, updated_at=""
    )


def _auto_dir(kb_dir: Path) -> Path:
    return kb_dir / "auto"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse(raw: object) -> AutoState:
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    task, stop = raw["task"], raw["stop_reason"]
    attempts, waiting, stamp = raw["attempts"], raw["waiting_on"], raw["updated_at"]
    if task is not None and not isinstance(task, str):
        raise ValueError("task must be a string or null")
    if stop is not None and not isinstance(stop, str):
        raise ValueError("stop_reason must be a string or null")
    if not _is_int(attempts) or attempts < 0:
        raise ValueError("attempts must be a non-negative integer")
    if not isinstance(waiting, list) or not all(_is_int(n) for n in waiting):
        raise ValueError("waiting_on must be a list of integers")
    if not isinstance(stamp, str):
        raise ValueError("updated_at must be a string")
    last_done, same_pick = raw.get("last_done"), raw.get("same_pick", 0)
    if last_done is not None and not isinstance(last_done, str):
        raise ValueError("last_done must be a string or null")
    if not _is_int(same_pick) or same_pick < 0:
        raise ValueError("same_pick must be a non-negative integer")
    skipped = raw.get("skipped", [])
    if not isinstance(skipped, list) or not all(isinstance(k, str) for k in skipped):
        raise ValueError("skipped must be a list of strings")
    publish_retry = raw.get("publish_retry")
    if publish_retry is not None and not isinstance(publish_retry, str):
        raise ValueError("publish_retry must be a string or null")
    split = raw.get("waiting_split", [])
    if not isinstance(split, list) or not all(isinstance(k, str) for k in split):
        raise ValueError("waiting_split must be a list of strings")
    review = raw.get("waiting_review", [])
    if not isinstance(review, list) or not all(isinstance(k, str) for k in review):
        raise ValueError("waiting_review must be a list of strings")
    waiting_env = raw.get("waiting", [])
    if not isinstance(waiting_env, list) or not all(
        isinstance(k, str) and _WAITING_RE.fullmatch(k) for k in waiting_env
    ):
        raise ValueError('waiting must be a list of "<id> <int>" strings')
    env_wait = raw.get("env_wait_until")
    if env_wait is not None and (
        isinstance(env_wait, bool) or not isinstance(env_wait, int | float)
    ):
        raise ValueError("env_wait_until must be a number or null")
    inc = raw.get("incomplete", [])
    if not isinstance(inc, list) or not all(
        isinstance(k, str) and _WAITING_RE.fullmatch(k) for k in inc
    ):
        raise ValueError('incomplete must be a list of "<key> <int>" strings')
    return AutoState(
        task,
        attempts,
        tuple(waiting),
        stop,
        stamp,
        last_done,
        same_pick,
        tuple(skipped),
        publish_retry,
        tuple(split),
        tuple(review),
        tuple(waiting_env),
        env_wait,
        tuple(inc),
    )


def load(kb_dir: Path) -> AutoState:
    path = _auto_dir(kb_dir) / STATE_NAME
    try:
        state = _parse(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError, KeyError) as exc:
        _log.warning("ignoring unreadable %s: %s", path, exc)
        return _empty()
    now = time.time()
    return replace(
        state,
        waiting=tuple(w for w in state.waiting if int(w.split()[1]) > now),
        env_wait_until=(
            state.env_wait_until
            if state.env_wait_until is not None and state.env_wait_until > now
            else None
        ),
    )


def waiting_stories(state: AutoState, now: float) -> frozenset[str]:
    """Stories still parked at `now`."""
    return frozenset(
        story for story, until in map(str.split, state.waiting) if int(until) > now
    )


def save(kb_dir: Path, state: AutoState) -> None:
    directory = _auto_dir(kb_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamped = replace(state, updated_at=datetime.now(UTC).isoformat())
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(asdict(stamped), handle, indent=2)
            handle.write("\n")
        os.replace(tmp, directory / STATE_NAME)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def log_dir(kb_dir: Path) -> Path:
    path = _auto_dir(kb_dir) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
