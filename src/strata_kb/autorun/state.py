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


def load(kb_dir: Path) -> AutoState:
    path = _auto_dir(kb_dir) / STATE_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return AutoState(
            task=raw["task"],
            attempts=int(raw["attempts"]),
            waiting_on=tuple(int(n) for n in raw["waiting_on"]),
            stop_reason=raw["stop_reason"],
            updated_at=str(raw["updated_at"]),
        )
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError, KeyError, TypeError) as exc:
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
