"""The Dev's view of ticket claims: `/api/claims` on the hub, no MCP.

Same client shape as `autorun/qa.py`. `LocalClaims` keeps the claim id and
secret token per ticket in `.kb/auto/claims.json` (git-ignored) so a later
`kb claim update` can prove it is the holder.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

from strata_kb import gitio, httpio
from strata_kb.autorun import state as autostate
from strata_kb.dockersetup import TOKEN_VAR
from strata_kb.errors import KbError
from strata_kb.mcpsetup import HUB_URL_VAR

Http = Callable[..., tuple[int, bytes]]

ROUTE = "/api/claims"
CLAIM_AS_VAR = "STRATA_KB_CLAIM_AS"
CLAIMS_FILE = "claims.json"


class ClaimTakenError(KbError):
    def __init__(self, claim: dict) -> None:
        super().__init__("ticket is already claimed")
        self.claim = claim


class ClaimLostError(KbError):
    def __init__(self, close_reason: str, closed_by: str) -> None:
        super().__init__(f"lost: {close_reason} by {closed_by}")
        self.close_reason = close_reason
        self.closed_by = closed_by


class ClaimRouteMissing(KbError):
    def __init__(self) -> None:
        super().__init__(
            f"hub server has no {ROUTE} — upgrade it to strata-kb 1.31.0 or later"
        )


class ClaimClient:
    def __init__(self, base_url: str, token: str, http: Http = httpio.request) -> None:
        self.base_url = base_url
        self._token = token
        self._http = http

    def take(
        self, ticket: str, holder: str, claim_token: str | None = None
    ) -> tuple[dict, str]:
        body = {"ticket": ticket, "holder": holder}
        if claim_token:
            body["token"] = claim_token
        data = self._call("POST", ROUTE, body)
        try:
            return data["claim"], data["token"]
        except KeyError as exc:
            raise self._bad_body() from exc

    def update(self, claim_id: int, claim_token: str, **fields: str) -> dict:
        data = self._call(
            "PATCH", f"{ROUTE}/{claim_id}", {"token": claim_token, **fields}
        )
        return self._claim(data)

    def release(self, claim_id: int, claim_token: str, reason: str) -> None:
        self._call(
            "DELETE", f"{ROUTE}/{claim_id}", {"token": claim_token, "reason": reason}
        )

    def held(self, repo: str = "", ticket: str = "") -> list[dict]:
        query = urlencode({k: v for k, v in (("repo", repo), ("ticket", ticket)) if v})
        data = self._call("GET", f"{ROUTE}?{query}" if query else ROUTE)
        if not isinstance(data.get("claims"), list):
            raise self._bad_body()
        return data["claims"]

    def pr_closed(self, claim_id: int, pr: str) -> dict:
        return self._claim(
            self._call("POST", f"{ROUTE}/{claim_id}/pr-closed", {"pr": pr})
        )

    def _claim(self, data: dict) -> dict:
        if not isinstance(data.get("claim"), dict):
            raise self._bad_body()
        return data["claim"]

    @staticmethod
    def _bad_body() -> KbError:
        return KbError(f"hub {ROUTE} returned an unexpected body")

    def _call(self, method: str, target: str, body: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode("utf-8")
        code, raw = self._http(method, f"{self.base_url}{target}", headers, payload)
        if code == 0:  # httpio: the request never completed
            raise KbError(f"hub unreachable: {raw.decode('utf-8', 'replace')}")
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            data = {}
        reason = data.get("error")
        if code == 404 and not reason:  # a hub with the route answers with a code
            raise ClaimRouteMissing
        if code == 409 and reason == "taken":
            raise ClaimTakenError(data.get("claim") or {})
        if code == 409 and reason == "lost":
            raise ClaimLostError(
                str(data.get("close_reason", "")), str(data.get("closed_by", ""))
            )
        if not 200 <= code < 300:
            detail = data.get("detail")
            raise KbError(
                f"hub {ROUTE} returned {code}"
                + (f": {reason}" if reason else "")
                + (f" — {detail}" if detail and isinstance(detail, str) else "")
            )
        return data


def from_env() -> ClaimClient:
    url, token = os.environ.get(HUB_URL_VAR, ""), os.environ.get(TOKEN_VAR, "")
    for name, value in ((HUB_URL_VAR, url), (TOKEN_VAR, token)):
        if not value:
            raise KbError(f"{name} is not set — claims live on the hub")
    return ClaimClient(url.rstrip("/"), token)


def holder_name(root: Path) -> str:
    """`$STRATA_KB_CLAIM_AS`, else `<git user.name>@<hostname>`."""
    override = os.environ.get(CLAIM_AS_VAR, "")
    if override:
        return override
    user = gitio.config_value(root, "user.name") or "unknown"
    return f"{user}@{socket.gethostname()}"


class LocalClaims:
    """`{ticket: {"id", "token"}}` in `.kb/auto/claims.json`."""

    def __init__(self, kb_dir: Path) -> None:
        self._path = autostate.log_dir(kb_dir).parent / CLAIMS_FILE

    def get(self, ticket: str) -> tuple[int, str] | None:
        entry = self._read().get(ticket)
        if not isinstance(entry, dict):
            return None
        claim_id, token = entry.get("id"), entry.get("token")
        if isinstance(claim_id, int) and isinstance(token, str):
            return claim_id, token
        return None

    def put(self, ticket: str, claim_id: int, token: str) -> None:
        self._write({**self._read(), ticket: {"id": claim_id, "token": token}})

    def drop(self, ticket: str) -> None:
        data = self._read()
        if data.pop(ticket, None) is not None:
            self._write(data)

    def _read(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, indent=2)
                handle.write("\n")
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
