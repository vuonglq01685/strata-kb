"""git for `kb code-ingest`: local (not strata_kb.gitio) because a non-git
scratch directory is a valid code-ingest target, so a failure is a returned
non-zero exit code to inspect, never an exception."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # P55/P57 (Wave J round 2): byte-for-byte the same omission gitio._run
    # had before the Wave J Critical fix -- an inherited stdin can be a
    # caller's protocol stream. Not reached from the MCP stdio server today
    # (only cli.py calls this, off that surface), but the ruling is about
    # the call shape, not about who currently imports the module --
    # DEVNULL costs nothing here since nothing writes to stdin.
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
    )
