# src/strata_kb/ghapp.py
"""ghapp — GitHub App REST calls for the hub intake service.

Mints an installation token for the hub repo from the App's id and private
key (a short-lived RS256 JWT), opens -- or finds the already-open -- PR
for a branch, and keeps a rolling labelled issue and reads repo files.
Callers: intake.py, web/intake_routes.py and the `kb code-sync` runner. Every
HTTP call goes through an injectable `http` callable so tests never touch
api.github.com; tokens never appear in error messages.
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

API = "https://api.github.com"
_GH_URL_RE = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$")


class GHAppError(RuntimeError):
    """GitHub App call failed (token is never included in the message).

    Deliberately stays out of the KbError family: raised by the server and by
    `kb code-sync` (runner/issue), which catch it themselves, so there is no
    CLI-terminal `except KbError` guard for it to hide from.
    """


@dataclass
class AppCreds:
    app_id: str
    private_key_pem: str


def _default_http(req: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 -- req.full_url is always built from the hardcoded API constant below, never operator-configured
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def repo_full_from_url(url: str) -> str:
    m = _GH_URL_RE.search(url)
    if not m:
        raise GHAppError(f"'{url}' is not a GitHub repo URL")
    return m.group(1)


def _app_jwt(creds: AppCreds) -> str:
    import jwt

    now = int(time.time())
    return jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": creds.app_id},
        creds.private_key_pem,
        algorithm="RS256",
    )


def _call(
    method: str, url: str, bearer: str, body: dict | None, http
) -> tuple[int, dict | list]:
    req = urllib.request.Request(  # noqa: S310 -- url is always built from the hardcoded API constant, never operator-configured
        url,
        method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    status, raw = http(req)
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    return status, data


def mint_installation_token(creds: AppCreds, repo_full: str, http=_default_http) -> str:
    app_jwt = _app_jwt(creds)
    status, inst = _call(
        "GET", f"{API}/repos/{repo_full}/installation", app_jwt, None, http
    )
    if status != 200 or not isinstance(inst, dict):
        raise GHAppError(
            f"GET installation for '{repo_full}' -> {status} - "
            "is the GitHub App installed on the hub repo?"
        )
    status, tok = _call(
        "POST",
        f"{API}/app/installations/{inst['id']}/access_tokens",
        app_jwt,
        {},
        http,
    )
    if status != 201 or not isinstance(tok, dict):
        raise GHAppError(f"mint installation token -> {status}")
    return tok["token"]


def create_or_get_pr(
    repo_full: str,
    token: str,
    head_branch: str,
    title: str,
    body: str,
    base: str = "main",
    http=_default_http,
) -> str:
    status, data = _call(
        "POST",
        f"{API}/repos/{repo_full}/pulls",
        token,
        {"title": title, "body": body, "head": head_branch, "base": base},
        http,
    )
    if status == 201 and isinstance(data, dict):
        return data["html_url"]
    if status == 422:  # PR for this head already open — fetch it
        owner = repo_full.split("/")[0]
        status2, prs = _call(
            "GET",
            f"{API}/repos/{repo_full}/pulls?head={owner}:{head_branch}&state=open",
            token,
            None,
            http,
        )
        if status2 == 200 and isinstance(prs, list) and prs:
            return prs[0]["html_url"]
    raise GHAppError(f"create PR on '{repo_full}' -> {status}")


def find_open_pr(
    repo_full: str, token: str, head_branch: str, http=_default_http
) -> int | None:
    """Number of an open PR from `head_branch` of this repo, else None."""
    owner = repo_full.split("/")[0]
    q = urllib.parse.urlencode({"head": f"{owner}:{head_branch}", "state": "open"})
    status, prs = _call("GET", f"{API}/repos/{repo_full}/pulls?{q}", token, None, http)
    if status != 200 or not isinstance(prs, list):
        raise GHAppError(f"list pulls on '{repo_full}' -> {status}")
    return prs[0]["number"] if prs else None


def find_open_issue(
    repo_full: str,
    token: str,
    label: str,
    http=_default_http,
    accept: Callable[[str], bool] = lambda body: True,
) -> tuple[int, str] | None:
    """(number, body) of the newest open issue carrying `label` whose body
    `accept`s, else None."""
    q = urllib.parse.urlencode(
        {"labels": label, "state": "open", "sort": "created", "direction": "desc"}
    )
    status, data = _call(
        "GET", f"{API}/repos/{repo_full}/issues?{q}", token, None, http
    )
    if status != 200 or not isinstance(data, list):
        raise GHAppError(f"list issues on '{repo_full}' -> {status}")
    for item in data:  # the issues API also returns PRs
        body = item.get("body") or ""
        if "pull_request" not in item and accept(body):
            return item["number"], body
    return None


def create_issue(
    repo_full: str,
    token: str,
    title: str,
    body: str,
    label: str,
    http=_default_http,
) -> int:
    status, _ = _call(
        "POST", f"{API}/repos/{repo_full}/labels", token, {"name": label}, http
    )
    if status not in (201, 422):  # 422 = label already exists
        raise GHAppError(f"create label on '{repo_full}' -> {status}")
    status, data = _call(
        "POST",
        f"{API}/repos/{repo_full}/issues",
        token,
        {"title": title, "body": body, "labels": [label]},
        http,
    )
    if status != 201 or not isinstance(data, dict):
        raise GHAppError(f"create issue on '{repo_full}' -> {status}")
    return data["number"]


def update_issue_body(
    repo_full: str, token: str, number: int, body: str, http=_default_http
) -> None:
    status, _ = _call(
        "PATCH",
        f"{API}/repos/{repo_full}/issues/{number}",
        token,
        {"body": body},
        http,
    )
    if status != 200:
        raise GHAppError(f"update issue #{number} on '{repo_full}' -> {status}")


def close_issue(
    repo_full: str, token: str, number: int, comment: str, http=_default_http
) -> None:
    base = f"{API}/repos/{repo_full}/issues/{number}"
    status, _ = _call("POST", f"{base}/comments", token, {"body": comment}, http)
    if status != 201:
        raise GHAppError(f"comment on issue #{number} of '{repo_full}' -> {status}")
    status, _ = _call(
        "PATCH",
        base,
        token,
        {"state": "closed", "state_reason": "completed"},
        http,
    )
    if status != 200:
        raise GHAppError(f"close issue #{number} on '{repo_full}' -> {status}")


def read_file(
    repo_full: str, token: str, path: str, ref: str, http=_default_http
) -> str | None:
    """UTF-8 text of `path` at `ref` via the contents API; None when absent."""
    url = (
        f"{API}/repos/{repo_full}/contents/{urllib.parse.quote(path)}"
        f"?ref={urllib.parse.quote(ref, safe='')}"
    )
    status, data = _call("GET", url, token, None, http)
    if status == 404:
        return None
    if status != 200 or not isinstance(data, dict) or data.get("encoding") != "base64":
        raise GHAppError(f"read '{path}' on '{repo_full}' -> {status}")
    return base64.b64decode(data["content"]).decode("utf-8")
