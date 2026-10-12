"""Rolling `kb-code-sync` issue on the hub's GitHub repo (spec §6).

Same lifecycle as kb-doctor's `kb-stale-citations`: create when findings
appear, rewrite the body only when the findings digest changes, close with a
comment when a scan finds nothing. Pure REST via `ghapp`: the runner image has
no `gh`. The caller never reaches here on a scan error, so one never closes it.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Literal

from strata_kb import ghapp
from strata_kb.codesync import scan

logger = logging.getLogger("strata_kb.codesync.issue")

LABEL = "kb-code-sync"
TITLE = "kb code-sync: hub documents to update"

# GitHub rejects an issue body over 65536 chars (422); stay well under.
MAX_BODY_CHARS = 60000
TRUNCATED_LINE = (
    "... work order truncated: run `kb code-sync scan --md` locally for the rest."
)

_MARKER_RE = re.compile(re.escape(scan.DIGEST_PREFIX) + r"([0-9a-f]+) -->")


def _issue_body(r: scan.ScanResult) -> str:
    """The work order, cut to fit GitHub's body cap. The digest marker stays
    the last line so the unchanged-check still finds it."""
    body = scan.render_markdown(r)
    if len(body) <= MAX_BODY_CHARS:
        return body
    marker = body.rstrip("\n").rsplit("\n", 1)[1]
    tail = f"\n{TRUNCATED_LINE}\n\n{marker}\n"
    head = body[: MAX_BODY_CHARS - len(tail)]
    return head.rsplit("\n", 1)[0] + tail


def sync_issue(
    r: scan.ScanResult,
    *,
    repo_full: str,
    token: str,
    http=ghapp._default_http,
) -> Literal["created", "updated", "unchanged", "closed", "none"]:
    # Only issues carrying the job's identity marker are ours: a human-labelled
    # issue (or one from before the marker) is never rewritten or closed.
    existing = ghapp.find_open_issue(
        repo_full,
        token,
        LABEL,
        http=http,
        accept=lambda body: scan.body_marker(body) is not None,
    )
    if not r.findings:
        if existing is None:
            return "none"
        comment = f"kb code-sync: nothing left to update as of {r.scan_sha[:12]}."
        ghapp.close_issue(repo_full, token, existing[0], comment, http=http)
        return "closed"
    body = _issue_body(r)
    if existing is None:
        ghapp.create_issue(repo_full, token, TITLE, body, LABEL, http=http)
        return "created"
    m = _MARKER_RE.search(existing[1])
    if m and m.group(1) == scan.digest(r):
        return "unchanged"
    ghapp.update_issue_body(repo_full, token, existing[0], body, http=http)
    return "updated"


def issue_token(repo_full: str, http=ghapp._default_http) -> str | None:
    """A minted App installation token when App creds are set, else
    STRATA_KB_GH_TOKEN, else None."""
    app_id = os.environ.get("STRATA_KB_GH_APP_ID", "")
    key_path = os.environ.get("STRATA_KB_GH_APP_KEY", "")
    if not (app_id and key_path):
        return os.environ.get("STRATA_KB_GH_TOKEN", "").strip() or None
    try:
        pem = Path(key_path).read_text(encoding="utf-8")
    except OSError as exc:
        logger.error(
            "code-sync issue disabled -- cannot read App key '%s': %s", key_path, exc
        )
        return None
    creds = ghapp.AppCreds(app_id=app_id, private_key_pem=pem)
    return ghapp.mint_installation_token(creds, repo_full, http=http)
