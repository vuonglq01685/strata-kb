"""Connect a reader repo (child | ba | dev) to the hub's HTTP MCP service.

`kb init` scaffolds `.mcp.json` with `${STRATA_KB_HUB_URL}` and
`${STRATA_KB_HTTP_TOKEN}` placeholders, and `.cursor/mcp.json` with Cursor's
`${env:STRATA_KB_HUB_URL}` and `${env:STRATA_KB_HTTP_TOKEN}` — both expanded
by the editor from the *process environment*. Nothing set them. This module
writes both into `.env` (the file a child's docker-compose already reads)
and then proves them against the hub.

The mirror image of `dockersetup`: that one stands the service up, this one
connects a client to it. Same shape — pure logic plus helpers the tests
monkeypatch, with the CLI in `cli.py` doing only dispatch.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from strata_kb import dockersetup, gitio, httpio
from strata_kb.dockersetup import TOKEN_VAR
from strata_kb.errors import KbError

HUB_URL_VAR = "STRATA_KB_HUB_URL"

# Short, because a human is waiting on it. httpio's own default (60s) is for
# CI publishing, where a slow hub is worth waiting out.
PROBE_TIMEOUT = 10

__all__ = [
    "HUB_URL_VAR",
    "TOKEN_VAR",
    "EnvReport",
    "McpSetupError",
    "ProbeResult",
    "is_plaintext_remote",
    "normalize_hub_url",
    "probe",
    "read_env_value",
    "require_client_kind",
    "write_env",
]


class McpSetupError(KbError):
    """Setup cannot proceed (wrong repo kind, unusable URL, missing value).
    Joins the KbError family so the CLI's single `except KbError` turns it
    into a one-line, exit-1 message."""


@dataclass(frozen=True)
class EnvReport:
    env_created: bool
    gitignore_updated: bool


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    message: str
    warning: str = ""
    token_rejected: bool = False


def normalize_hub_url(raw: str) -> str:
    """Trim, drop a trailing '/', and refuse a non-http(s) scheme.

    The trailing slash matters: the scaffolded `.mcp.json` appends `/mcp`, so
    a stored `http://h:8321/` would produce `http://h:8321//mcp`.
    """
    url = raw.strip().rstrip("/")
    if not url:
        raise McpSetupError("the hub URL is empty")
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        # Truncate: a token pasted into --hub-url by mistake must not land
        # on the terminal in full.
        shown = raw if len(raw) <= 16 else f"{raw[:16]}…"
        raise McpSetupError(
            f"the hub URL must start with http:// or https:// — got '{shown}'"
        )
    return url


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_plaintext_remote(url: str) -> bool:
    """True for `http://` to a host that isn't loopback -- the token would
    cross the network unencrypted. `https://` and loopback hosts are fine."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http":
        return False
    host = (parsed.hostname or "").lower()
    return host not in _LOOPBACK_HOSTS


def require_client_kind(repo_root: Path) -> str:
    """Return the repo kind, refusing the one kind that has no use for this."""
    kind = dockersetup.repo_kind(repo_root)
    if kind == "hub":
        raise McpSetupError(
            "this repo is the hub — it serves MCP over stdio from its own "
            ".mcp.json and needs no mcp-setup. Run this in a child, ba or "
            "dev repo."
        )
    return kind


def read_env_value(repo_root: Path, var: str) -> str:
    """Return `var`'s value from `.env`, or '' when absent or unreadable.

    This is what makes a bare `kb mcp-setup` on a configured repo mean
    "verify again" instead of re-prompting — and it is how the assistant
    wrapper re-runs the command without ever handling the token itself.
    """
    env_path = repo_root / ".env"
    try:
        text = env_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    match = re.search(rf"^{re.escape(var)}=(.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _reject_line_breaks(var: str, value: str) -> None:
    """Refuse a value that would inject extra lines into `.env`.

    Called after the value has been stripped, so this only ever sees an
    *interior* break — a leading/trailing newline (the most common artefact
    of pasting a token out of chat or email) is gone by this point and never
    trips the refusal.

    `dockersetup.set_env_line` does not validate `value` -- it trusted its
    only caller (a `secrets.token_hex(24)` value, which never carries a
    newline). Here both values are user-supplied (a pasted hub URL, a
    pasted token), so the check belongs at this boundary instead.
    """
    if "\n" in value or "\r" in value:
        raise McpSetupError(
            f"the value for {var} contains a newline — refusing to write "
            "it to .env, since that would inject extra lines into the file"
        )


def write_env(repo_root: Path, hub_url: str, token: str) -> EnvReport:
    """Merge both variables into `.env`, then make sure git ignores it.

    Merge, not overwrite: on a child, `.env` is also docker-compose's
    substitution source. `ba` and `dev` repos get no root `.gitignore` from
    `kb init`, so `ensure_gitignored` creates one.

    Both values are stripped before anything else — `read_env_value` already
    strips on the way out, so an unstripped write here would make the
    re-verify path check a value that was never the one saved to disk.
    """
    hub_url = hub_url.strip()
    token = token.strip()
    _reject_line_breaks(HUB_URL_VAR, hub_url)
    _reject_line_breaks(TOKEN_VAR, token)
    # A pre-existing, git-tracked .env (adopting an existing product/
    # requirements repo) is the one case ensure_gitignored below can't
    # cover -- .gitignore stops FUTURE tracking, it can't untrack a file
    # already in the index. Refuse before writing, rather than reporting
    # success while a `git commit -a` would publish the token.
    if (repo_root / ".env").exists() and gitio.is_tracked(repo_root, ".env"):
        raise McpSetupError(
            ".env is already tracked by git — refusing to write a token "
            "into it. Untrack it first (git rm --cached .env), keep it "
            "on disk, then re-run kb mcp-setup."
        )
    # Ensure git ignores .env before the token ever touches it, so a failed
    # gitignore write (e.g. no permission) never leaves a bare token sitting
    # in a file git could track.
    gitignore_updated = dockersetup.ensure_gitignored(repo_root)
    env_path = repo_root / ".env"
    env_created = not env_path.exists()
    text = "" if env_created else env_path.read_text(encoding="utf-8")
    text = dockersetup.set_env_line(text, HUB_URL_VAR, hub_url)
    text = dockersetup.set_env_line(text, TOKEN_VAR, token)
    env_path.write_text(text, encoding="utf-8", newline="\n")
    return EnvReport(env_created, gitignore_updated)


def _default_http(method: str, url: str, headers: dict, body: bytes | None):
    return httpio.request(method, url, headers, body, timeout=PROBE_TIMEOUT)


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _docs_suffix(raw: bytes) -> str:
    """', N documents visible' when the body is the shape /api/docs returns."""
    try:
        payload = json.loads(_decode(raw))
        return f", {len(payload['docs'])} documents visible"
    except (ValueError, KeyError, TypeError):
        return ""


def probe(hub_url: str, token: str, http=None) -> ProbeResult:
    """Two requests that tell a wrong URL apart from a wrong token.

    `/api/health` is in `web.auth.EXEMPT_PATHS`, so reaching it proves the
    URL without involving the token. `/api/docs` is not, so its answer is
    entirely about the token.
    """
    http = http or _default_http

    status, raw = http("GET", f"{hub_url}/api/health", {}, None)
    if status == 0:
        return ProbeResult(
            False,
            f"cannot reach {hub_url} — check the URL, that the hub is "
            f"running, and any firewall. {_decode(raw)}",
        )
    if status != 200:
        return ProbeResult(
            False,
            f"{hub_url}/api/health returned {status} — this URL does not "
            "look like a Strata KB hub",
        )

    status, raw = http(
        "GET", f"{hub_url}/api/docs", {"Authorization": f"Bearer {token}"}, None
    )
    if status == 0:
        return ProbeResult(
            False,
            f"lost the connection to {hub_url} between the two checks. "
            f"{_decode(raw)}",
        )
    if status in (401, 403):
        return ProbeResult(
            False,
            f"the hub was reached but the token was rejected ({status}) — "
            "ask the hub maintainer for a fresh token",
            token_rejected=True,
        )
    if status == 429:
        return ProbeResult(
            False,
            f"{hub_url}/api/docs returned 429 — too many failed attempts. "
            "The hub's auth limiter blocks retries for about a minute; "
            "wait, then re-run `kb mcp-setup`",
        )
    if status == 503:
        # Auth ran before the handler, so a 503 here still proves the token.
        return ProbeResult(
            True,
            "hub reached — token accepted",
            warning=(
                "the hub reports its own KB is not ready (503) — tell the "
                "hub maintainer"
            ),
        )
    if status != 200:
        return ProbeResult(
            False, f"unexpected {status} from {hub_url}/api/docs"
        )
    return ProbeResult(True, f"hub reached — token accepted{_docs_suffix(raw)}")
