"""One JSON line per auto task run, appended to `.kb/auto/runs.jsonl`."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from strata_kb import gitio
from strata_kb.autorun.claude import TaskResult

logger = logging.getLogger(__name__)

RUNS_NAME = "runs.jsonl"
SCHEMA = 1


def stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def head(root: Path) -> str | None:
    try:
        return gitio.head_commit(root, short=False)
    except gitio.GitError:
        return None


def append(
    kb_dir: Path,
    *,
    skill: str,
    arg: str,
    attempt: int,
    result: TaskResult,
    started_at: str,
    ended_at: str,
    head_before: str | None,
    head_after: str | None,
) -> None:
    """Record one run. A write failure only warns: it never fails the task."""
    meta = result.meta
    row = {
        "schema": SCHEMA,
        "run_id": uuid.uuid4().hex,
        "started_at": started_at,
        "ended_at": ended_at,
        "skill": skill,
        "arg": arg,
        "attempt": attempt,
        "outcome": result.kind,
        "reason": result.reason,
        "ids": list(result.ids),
        "session_id": meta.get("session_id"),
        "cost_usd": meta.get("total_cost_usd"),
        "turns": meta.get("num_turns"),
        "duration_ms": meta.get("duration_ms"),
        "head_before": head_before,
        "head_after": head_after,
        "log": meta.get("log"),
    }
    line = (json.dumps(row) + "\n").encode("utf-8")
    try:
        path = kb_dir / "auto" / RUNS_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)  # one write: concurrent appenders never interleave
        finally:
            os.close(fd)
    except OSError as exc:
        logger.warning("run not recorded in %s: %s", RUNS_NAME, exc)
