# src/center_kb/ghapp.py
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

API = "https://api.github.com"
_GH_URL_RE = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$")


class GHAppError(RuntimeError):
    """GitHub App call failed (token is never included in the message)."""


@dataclass
class AppCreds:
    app_id: str
    private_key_pem: str


def _default_http(req: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
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
    req = urllib.request.Request(
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


def mint_installation_token(
    creds: AppCreds, repo_full: str, http=_default_http
) -> str:
    app_jwt = _app_jwt(creds)
    status, inst = _call(
        "GET", f"{API}/repos/{repo_full}/installation", app_jwt, None, http
    )
    if status != 200:
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
    if status != 201:
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
    if status == 201:
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
