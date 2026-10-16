"""ghrest -- `gh pr` replacement over `gh api` (REST).

Claude Code cloud blocks GitHub GraphQL ("HTTP 403: GitHub GraphQL is not
available from Claude Code sessions; use the REST API"), and `gh pr ...` is
GraphQL. `gh api` REST works. Every PR dict returned here carries the keys of
`gh pr --json` (number, url, state OPEN|CLOSED|MERGED, mergedAt, title, body,
headRefName, headRefOid) so the skills swap `gh pr` for `kb pr` one-for-one.
Every `gh` call has ghio's 60 s timeout; any failure is a GHError.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from strata_kb import gitio
from strata_kb.ghio import _GH_TIMEOUT_SECONDS, GHError
from strata_kb.pubgate import _SCP_RE, owner_repo_from_remote

EXIT_PENDING = 8  # `gh pr checks`' code for "still running"
_STATES = ("open", "closed", "merged", "all")
_MERGE_METHODS = ("squash", "merge", "rebase")
_CHECK_OK = {"success", "neutral", "skipped"}


def _gh(root: Path, args: list[str], stdin: str | None) -> str:
    """Run `gh <args>`, return stdout. Seam the tests fake."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GH_TIMEOUT_SECONDS,
            **(
                {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
            ),
        )
    except FileNotFoundError:
        raise GHError("gh not found: install and authenticate the GitHub CLI") from None
    except subprocess.TimeoutExpired:
        raise GHError(f"gh timed out after {_GH_TIMEOUT_SECONDS}s") from None
    if proc.returncode != 0:
        raise GHError(f"gh {' '.join(args[:1])} failed: {proc.stderr.strip()}")
    return proc.stdout


def origin_slug(root: Path) -> tuple[str, str]:
    """(host, 'owner/repo') of the `origin` remote."""
    proc = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
    )
    url = proc.stdout.strip()
    if proc.returncode != 0 or not url:
        raise GHError("no 'origin' remote to derive the GitHub repository from")
    slug = owner_repo_from_remote(url)
    m = _SCP_RE.match(url)
    host = m.group("host") if m else urlsplit(url).hostname
    if not slug or not host:
        raise GHError(
            f"cannot derive owner/repo and host from origin '{gitio.redact_url(url)}'"
        )
    return host, slug


def api(root: Path, method: str, path: str, body: dict | None = None) -> Any:
    host, _ = origin_slug(root)
    args = ["api", "--hostname", host, "-X", method, path]
    if body is not None:
        args += ["--input", "-"]
    out = _gh(root, args, json.dumps(body) if body is not None else None)
    if not out.strip():
        return None
    try:
        return json.loads(out)
    except ValueError as exc:
        raise GHError(f"gh api {method} {path} returned invalid JSON: {exc}") from None


def _pr_json(raw: dict) -> dict:
    merged_at = raw.get("merged_at")
    state = "MERGED" if merged_at else str(raw.get("state", "")).upper()
    return {
        "number": raw["number"],
        "url": raw["html_url"],
        "state": state,
        "mergedAt": merged_at,
        "title": raw.get("title") or "",
        "body": raw.get("body") or "",
        "headRefName": raw["head"]["ref"],
        "headRefOid": raw["head"].get("sha", ""),
        # null for a deleted fork
        "headRepoFullName": (raw["head"].get("repo") or {}).get("full_name") or "",
    }


def find_prs(root: Path, head: str, state: str = "open") -> list[dict]:
    if state not in _STATES:
        raise GHError(f"unknown state '{state}': use one of {', '.join(_STATES)}")
    _, slug = origin_slug(root)
    owner = slug.split("/", 1)[0]
    rest_state = "closed" if state == "merged" else state
    query = f"head={quote(f'{owner}:{head}', safe='')}&state={rest_state}&per_page=100"
    prs = [_pr_json(p) for p in api(root, "GET", f"repos/{slug}/pulls?{query}")]
    return [p for p in prs if p["state"] == "MERGED"] if state == "merged" else prs


def view_pr(root: Path, ref: str | None = None) -> dict:
    """PR by number, by branch, or (None) for the current branch -- any state, newest."""
    ref = (ref or "").strip() or gitio.current_branch(root)
    number = ref.lstrip("#")
    if number.isdigit():
        _, slug = origin_slug(root)
        return _pr_json(api(root, "GET", f"repos/{slug}/pulls/{number}"))
    prs = find_prs(root, ref, "all")
    if not prs:
        raise GHError(f"no pull request found for '{ref}'")
    return max(prs, key=lambda p: p["number"])


def open_pr(
    root: Path,
    title: str,
    body: str,
    head: str | None = None,
    base: str | None = None,
) -> dict:
    _, slug = origin_slug(root)
    payload = {
        "title": title,
        "body": body,
        "head": head or gitio.current_branch(root),
        "base": base or gitio.default_branch(root),
    }
    return _pr_json(api(root, "POST", f"repos/{slug}/pulls", payload))


def _check_run_state(run: dict) -> str:
    if run.get("status") != "completed":
        return "pending"
    return "success" if run.get("conclusion") in _CHECK_OK else "failure"


_STATUS_STATES = {
    "success": "success",
    "pending": "pending",
}  # error/failure -> failure


def checks(root: Path, ref: str | None = None) -> list[dict]:
    """Check runs and commit statuses of the PR head: [{'name', 'state'}]."""
    pr = view_pr(root, ref)
    _, slug = origin_slug(root)
    sha = pr["headRefOid"]
    runs = api(root, "GET", f"repos/{slug}/commits/{sha}/check-runs?per_page=100")
    stats = api(root, "GET", f"repos/{slug}/commits/{sha}/status?per_page=100")
    return [
        {"name": r["name"], "state": _check_run_state(r)}
        for r in (runs or {}).get("check_runs", [])
    ] + [
        {"name": s["context"], "state": _STATUS_STATES.get(s.get("state"), "failure")}
        for s in (stats or {}).get("statuses", [])
    ]


def exit_code(rows: list[dict]) -> int:
    """0 all success, 1 any failure, 8 pending -- and no check yet is pending."""
    if any(r["state"] == "failure" for r in rows):
        return 1
    if not rows or any(r["state"] == "pending" for r in rows):
        return EXIT_PENDING
    return 0


def wait_for_checks(
    root: Path,
    ref: str | None,
    interval: float = 15,
    timeout: float = 3600,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[int, list[dict]]:
    """Poll until checks settle (exit_code != 8) or `timeout` runs out (8)."""
    sleep = sleep or time.sleep
    deadline = clock() + timeout
    while True:
        rows = checks(root, ref)
        code = exit_code(rows)
        if code != EXIT_PENDING or clock() + interval > deadline:
            return code, rows
        sleep(interval)


def merge_pr(
    root: Path,
    ref: str | None,
    method: str = "squash",
    delete_branch: bool = False,
) -> dict:
    if method not in _MERGE_METHODS:
        raise GHError(
            f"unknown merge method '{method}': use one of {', '.join(_MERGE_METHODS)}"
        )
    pr = view_pr(root, ref)
    _, slug = origin_slug(root)
    res = api(
        root,
        "PUT",
        f"repos/{slug}/pulls/{pr['number']}/merge",
        {"merge_method": method},
    )
    if not (res or {}).get("merged"):
        raise GHError(
            f"PR #{pr['number']} not merged: {(res or {}).get('message', 'unknown reason')}"
        )
    merged = view_pr(root, str(pr["number"]))
    # A fork PR's head branch lives in the fork; deleting it by name here would
    # hit origin's own branch of that name (gh skips the delete too).
    if delete_branch and merged["headRepoFullName"].lower() == slug.lower():
        api(
            root,
            "DELETE",
            f"repos/{slug}/git/refs/heads/{quote(pr['headRefName'], safe='/')}",
        )
    return merged


def edit_pr(
    root: Path,
    ref: str | None,
    title: str | None = None,
    body: str | None = None,
) -> dict:
    payload = {k: v for k, v in (("title", title), ("body", body)) if v is not None}
    if not payload:
        raise GHError("nothing to edit: give a title or a body")
    pr = view_pr(root, ref)
    _, slug = origin_slug(root)
    return _pr_json(api(root, "PATCH", f"repos/{slug}/pulls/{pr['number']}", payload))
