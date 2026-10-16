"""cloud — are we running in a Claude Code cloud session, and where is the hub.

On cloud nothing from the hub is copied: the runner and a few CLI commands
read it live over the hub's `/api/*` routes, using the URL and token every
client already has in its environment.

`STRATA_KB_CLOUD=1|0` forces the switch on or off (tests, a hub server started
inside a cloud session); otherwise `CLAUDE_CODE_REMOTE` set to `1` or `true`
(any case) turns it on.
"""

from __future__ import annotations

import os

from strata_kb.dockersetup import TOKEN_VAR
from strata_kb.mcpsetup import HUB_URL_VAR

CLOUD_VAR = "STRATA_KB_CLOUD"
REMOTE_VAR = "CLAUDE_CODE_REMOTE"


def is_cloud() -> bool:
    forced = os.environ.get(CLOUD_VAR, "").strip()
    if forced in ("0", "1"):
        return forced == "1"
    return os.environ.get(REMOTE_VAR, "").strip().lower() in ("1", "true")


def hub_http() -> tuple[str, str] | None:
    """`(url without trailing slash, token)`; None unless both are set."""
    url = os.environ.get(HUB_URL_VAR, "").strip()
    token = os.environ.get(TOKEN_VAR, "").strip()
    return (url.rstrip("/"), token) if url and token else None
