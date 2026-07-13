from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class GHError(RuntimeError):
    """GitHub CLI (`gh`) failed or is missing."""


def _run_gh(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def gh_available() -> bool:
    return shutil.which("gh") is not None


def pr_url_for_branch(root: Path, branch: str) -> str:
    """URL of the open PR for `branch`; '' if there is none yet."""
    proc = _run_gh(root, "pr", "view", branch, "--json", "url", "--jq", ".url")
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def create_pr(root: Path, branch: str, title: str, body: str) -> str:
    proc = _run_gh(
        root, "pr", "create", "--head", branch, "--title", title, "--body", body
    )
    if proc.returncode != 0:
        raise GHError(f"gh pr create failed: {proc.stderr.strip()}")
    lines = proc.stdout.strip().splitlines()
    return lines[-1] if lines else ""
