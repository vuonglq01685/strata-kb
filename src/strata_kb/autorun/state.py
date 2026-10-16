"""state — the runner's progress file, `.kb/auto/state.json`.

Local only (`.kb/auto/` is git-ignored). `save` writes a temp file beside the
target and `os.replace`s it, so a reader never sees half a file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
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
    return AutoState(task, attempts, tuple(waiting), stop, stamp)


def load(kb_dir: Path) -> AutoState:
    path = _auto_dir(kb_dir) / STATE_NAME
    try:
        return _parse(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError, KeyError) as exc:
        _log.warning("ignoring unreadable %s: %s", path, exc)
        return _empty()


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
