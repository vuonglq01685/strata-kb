"""One urllib wrapper for the HTTP calls whose URL an operator supplies.

`ghapp.py` keeps its own helper on purpose: it talks to a fixed API host and
takes an already-built `urllib.request.Request`. This module is for URLs that
come from `kb ci-publish`'s `--intake`/its OIDC token request, or
`--hub-url`, where the scheme guard below is load-bearing — a `file://`
value would otherwise make `urlopen` read a local path (S310). `publish.py`'s
own dev-machine intake flow keeps a separate copy of this guard on purpose
(it must raise before tagging/pushing, not just return a failed status) —
every other caller shares this one.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request


def request(
    method: str,
    url: str,
    headers: dict,
    body: bytes | None = None,
    timeout: int = 60,
) -> tuple[int, bytes]:
    """Perform one HTTP request; never raise for a transport or status error.

    Returns `(status, body)`. Status `0` means the request never completed
    (refused scheme, DNS, connection refused, timeout) and `body` carries the
    reason — the convention every caller in this repo already reads.
    """
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        return 0, f"refusing non-http(s) URL: {url}".encode("utf-8")
    req = urllib.request.Request(url, method=method, data=body, headers=headers)  # noqa: S310 -- scheme validated above
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 -- scheme validated above
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc).encode("utf-8")
