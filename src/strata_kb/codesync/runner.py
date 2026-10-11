"""The hub-sync job (spec §6): one scan, one issue update, then sleep.

`run_once` is the unit (also what cron or a GitHub Actions workflow calls);
`run_loop` only repeats it. Neither pulls, commits or pushes: the `hub`
service keeps /data current.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import NoReturn

import yaml

from strata_kb import ghapp, gitio
from strata_kb.codesync import baseline, scan
from strata_kb.codesync import issue as issue_mod
from strata_kb.errors import KbError

logger = logging.getLogger("strata_kb.codesync.runner")

INTERVAL_ENV = "STRATA_KB_CODE_SYNC_INTERVAL"
DEFAULT_INTERVAL = 86400
MIN_INTERVAL = 60


def interval_from_env() -> int:
    """Seconds between runs. SystemExit (no traceback) on a bad value, like
    `ratelimit.trusted_proxies_from_env`: a typo must not become a busy loop."""
    raw = os.environ.get(INTERVAL_ENV, str(DEFAULT_INTERVAL))
    if not raw.isdecimal() or int(raw) < MIN_INTERVAL:
        raise SystemExit(
            f"{INTERVAL_ENV} must be an integer of at least {MIN_INTERVAL} "
            f"seconds, got '{raw}' -- unset it for the default ({DEFAULT_INTERVAL})"
        )
    return int(raw)


_GITHUB_ERRORS = (ghapp.GHAppError, OSError, ValueError)


def _why(exc: BaseException) -> str:
    """One log-safe line for a failed GitHub call: URLs carry no credentials
    and messages never carry a token."""
    text = " ".join(f"{type(exc).__name__}: {exc}".split())
    return gitio.redact_url(text)


def _github(root: Path, http) -> tuple[str, str] | str:
    """`(repo_full, token)`, or the reason the issue cannot be updated."""
    url = gitio.remote_url(root)
    if not url:
        return "no origin remote"
    try:
        repo_full = ghapp.repo_full_from_url(url)
        token = issue_mod.issue_token(repo_full, http=http)
    except Exception as exc:  # noqa: BLE001 -- also jwt/crypto key errors (optional dep)
        return _why(exc)
    return (repo_full, token) if token else "no GitHub credentials"


def _rest_baseline(creds: tuple[str, str], http) -> tuple[str | None, str | None]:
    """`(sha, error)`: the baseline on the rolling PR branch, read over REST
    (the image has no fetched bot branch), trusted only while its PR is open:
    a closed-unmerged round never landed. `sha` None with no error means no
    open PR or no file (404); `error` means a GitHub call failed."""
    repo_full, token = creds
    try:
        if ghapp.find_open_pr(repo_full, token, baseline.BOT_BRANCH, http=http) is None:
            return None, None
        text = ghapp.read_file(
            repo_full, token, baseline.BASELINE_FILE, baseline.BOT_BRANCH, http=http
        )
    except _GITHUB_ERRORS as exc:
        return None, f"bot-branch baseline not read ({_why(exc)})"
    return (None if text is None else baseline.parse(text)), None


def run_once(root: Path, *, issue: bool, http=ghapp._default_http) -> int:
    """Exit code: 0 nothing to do, 2 findings, 1 scan error."""
    creds = _github(root, http) if issue else None
    reason = creds if isinstance(creds, str) else None
    try:
        sha = None
        if isinstance(creds, tuple):
            sha, reason = _rest_baseline(creds, http)
        r = scan.run_scan(
            root, baseline_sha=sha, baseline_source="bot-branch", bot_ref=False
        )
    except (KbError, ValueError, yaml.YAMLError, OSError) as exc:
        # Never reach sync_issue: an error must not close or rewrite the issue.
        logger.error("code-sync scan failed: %s", " ".join(str(exc).split()))
        return 1
    logger.info(
        "code-sync: %d finding(s) at %s (baseline %s)",
        len(r.findings),
        r.scan_sha[:12],
        r.baseline_sha[:12] if r.baseline_sha else "none",
    )
    if isinstance(creds, tuple) and reason is None:
        try:
            outcome = issue_mod.sync_issue(
                r, repo_full=creds[0], token=creds[1], http=http
            )
        except _GITHUB_ERRORS as exc:
            reason = _why(exc)
        else:
            logger.info("issue %s", outcome)
    if reason is not None:
        logger.info("issue not updated: %s", reason)
    if (reason is not None or creds is None) and r.findings:
        logger.info("work order:\n%s", scan.render_markdown(r))
    return scan.exit_code(r)


def run_loop(
    root: Path,
    *,
    interval: int,
    issue: bool,
    sleep=time.sleep,
    http=ghapp._default_http,
) -> NoReturn:
    while True:
        try:
            run_once(root, issue=issue, http=http)
        except Exception as exc:  # noqa: BLE001 -- the service must outlive any one run
            logger.error("code-sync run failed: %s", _why(exc))
        sleep(interval)
