"""trust — pre-accept Claude Code's folder-trust dialog for the dirs a task runs in.

A cloud session has no human to click "trust this folder", so `claude -p` in a
fresh worktree would stall. We set `hasTrustDialogAccepted` per project in
`~/.claude.json`. The caller gates this on `cloud.is_cloud()`; this module
never touches a file it cannot parse and keeps every other key.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

TRUST_KEY = "hasTrustDialogAccepted"


def trust_dirs(paths: Sequence[Path], config: Path | None = None) -> None:
    config = config or Path.home() / ".claude.json"
    try:
        text = config.read_text(encoding="utf-8") if config.exists() else ""
        data = json.loads(text) if text.strip() else {}
    except (OSError, ValueError) as exc:
        logger.warning("trust: cannot read %s, leaving it alone: %s", config, exc)
        return
    projects = data.get("projects", {}) if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        logger.warning("trust: %s has an unexpected shape, leaving it alone", config)
        return
    for path in paths:
        entry = projects.get(str(path.resolve()))
        if not isinstance(entry, dict):
            entry = projects[str(path.resolve())] = {}
        entry[TRUST_KEY] = True
    data["projects"] = projects
    try:
        _write_atomic(config, json.dumps(data, indent=2))
    except OSError as exc:
        logger.warning("trust: cannot write %s: %s", config, exc)


def _write_atomic(target: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
