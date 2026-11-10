"""`kb upgrade`: re-run the init refresh on a new branch and open a PR.

A human runs it (`kb init` is denied to the auto agent). It never merges.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from strata_kb import __version__, ghrest, gitio
from strata_kb.config import load_config
from strata_kb.errors import KbError
from strata_kb.initcmd import KIND_BA, KIND_DEV, InitReport, init_repo
from strata_kb.llm import AUTO_TASK_ENV


@dataclass(frozen=True)
class UpgradeResult:
    branch: str | None  # None when nothing changed
    report: InitReport
    pr_url: str | None


def _pr_body(report: InitReport) -> str:
    parts = ["Refreshed by `kb upgrade`. Review, then merge by hand."]
    for title, items in (
        ("Created", report.created),
        ("Updated", report.updated),
        ("Skipped", report.skipped),
        ("Notes", report.notes),
    ):
        if items:
            parts.append(f"### {title}\n" + "\n".join(f"- {i}" for i in items))
    return "\n\n".join(parts)


def _check_preconditions(root: Path, branch: str) -> str:
    """Refuse unsafe starts; return the repo kind."""
    if os.environ.get(AUTO_TASK_ENV) == "1":
        raise KbError("kb upgrade is for humans — it is not allowed in an auto task")
    kind = load_config(root / ".kb").kind
    if kind not in (KIND_BA, KIND_DEV):
        raise KbError(
            "kb upgrade supports ba or dev repos only "
            f"(this repo: {kind or 'no kind recorded'})"
        )
    if gitio.current_branch(root) == "HEAD":
        raise KbError("detached HEAD — check out a branch, then re-run")
    if gitio.is_dirty(root, root):
        raise KbError("uncommitted changes — commit or stash them, then re-run")
    if gitio.rev_exists(root, f"refs/heads/{branch}") or (
        gitio.has_remote(root) and gitio.remote_branch_exists(root, branch)
    ):
        raise KbError(f"branch {branch} already exists — merge or delete it first")
    return kind


def upgrade(
    root: Path,
    *,
    open_pr: bool = True,
    opener: Callable[..., dict] = ghrest.open_pr,
) -> UpgradeResult:
    root = gitio.git_root(root)
    branch = f"kb/upgrade-{__version__}"
    kind = _check_preconditions(root, branch)
    original = gitio.current_branch(root)
    base = gitio.default_branch(root)
    start = base if gitio.rev_exists(root, f"refs/heads/{base}") else f"origin/{base}"
    gitio.checkout_branch(root, branch, start)
    pushed = False
    try:
        # init_repo unions the langs recorded in .kb/config.yaml itself
        report = init_repo(root, kind)
        title = f"chore: kb upgrade to {__version__}"
        # An empty commit (changes only in gitignored paths) is "no change" too.
        if (
            not report.created and not report.updated and not gitio.is_dirty(root, root)
        ) or not gitio.commit_all(root, title):
            gitio.checkout(root, original)
            gitio.delete_branch(root, branch)
            return UpgradeResult(None, report, None)
        if not open_pr:
            return UpgradeResult(branch, report, None)
        gitio.push_branch(root, branch, force=False)
        pushed = True
        url = opener(root, title, _pr_body(report), head=branch, base=base).get("url")
        gitio.checkout(root, original)
        return UpgradeResult(branch, report, url)
    except Exception as exc:
        msg = f"kb upgrade failed: {exc} — local branch {branch} was kept for you"
        if pushed:
            msg += (
                f"; it was pushed too: open the PR with `kb pr open --head {branch}` "
                "or delete the remote branch before re-running"
            )
        try:
            gitio.checkout(root, original)
        except Exception as restore_exc:  # noqa: BLE001 -- keep the first failure visible
            msg += f"; also could not return to {original}: {restore_exc}"
        raise KbError(msg) from exc
