from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from strata_kb.errors import KbError

_GH_TIMEOUT_SECONDS = 60


class GHError(KbError):
    """GitHub CLI (`gh`) failed or is missing. Every cli.py call site already
    catches it and prints a one-line message -- joins the KbError family
    (Wave G fix round 2, item 7)."""


def _run_gh(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["gh", *args], cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        # A hung `gh` (captive portal, stalled proxy, slow GHE) must degrade
        # to a failed probe, not block the publish indefinitely.
        return subprocess.CompletedProcess(
            ["gh", *args], returncode=124, stdout="",
            stderr=f"gh timed out after {_GH_TIMEOUT_SECONDS}s",
        )


def gh_available() -> bool:
    return shutil.which("gh") is not None


def pr_url_for_branch(root: Path, branch: str) -> str:
    """URL of the open PR for `branch`; '' if there is none yet."""
    proc = _run_gh(root, "pr", "view", branch, "--json", "url", "--jq", ".url")
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def can_open_pr(root: Path) -> bool:
    """Can `gh` actually open a pull request on this repo's origin?

    Asked once, before anything is pushed. Replaces the old
    `"github" in remote_url` substring test in publish.py, which was wrong
    in both directions: it routed .../github-mirror-hub.git to PR mode (and
    crashed after force-pushing) and every GitLab/Gitea/self-hosted hub to a
    silent direct push. `gh repo view` respects GH_HOST, so a GitHub
    Enterprise hub answers correctly too.
    """
    if not gh_available():
        return False
    proc = _run_gh(root, "repo", "view", "--json", "name")
    return proc.returncode == 0


def create_pr(root: Path, branch: str, title: str, body: str) -> str:
    proc = _run_gh(
        root, "pr", "create", "--head", branch, "--title", title, "--body", body
    )
    if proc.returncode != 0:
        raise GHError(f"gh pr create failed: {proc.stderr.strip()}")
    lines = proc.stdout.strip().splitlines()
    return lines[-1] if lines else ""
