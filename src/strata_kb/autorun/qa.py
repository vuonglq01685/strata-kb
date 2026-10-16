"""The runner's view of ticket Q&A: `GET /api/questions` on the hub, no MCP."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from urllib.parse import urlencode

from strata_kb import httpio
from strata_kb.dockersetup import TOKEN_VAR
from strata_kb.errors import KbError
from strata_kb.mcpsetup import HUB_URL_VAR

Http = Callable[..., tuple[int, bytes]]


class QaClient:
    def __init__(self, base_url: str, token: str, http: Http = httpio.request) -> None:
        self.base_url = base_url
        self._token = token
        self._http = http

    def list(
        self, status: str = "open", repo: str = "", ticket: str = ""
    ) -> list[dict]:
        params = {"status": status, "repo": repo, "ticket": ticket}
        query = urlencode({k: v for k, v in params.items() if v})
        code, body = self._http(
            "GET",
            f"{self.base_url}/api/questions?{query}",
            {"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
        )
        return self._questions(code, body)

    def states(self, ids: list[int]) -> dict[int, str]:
        """State of each id found; an id the hub does not know is absent."""
        wanted = set(ids)
        return {
            q["id"]: q["state"] for q in self.list(status="all") if q["id"] in wanted
        }

    def _questions(self, code: int, body: bytes) -> list[dict]:
        if code == 0:  # httpio: the request never completed
            raise KbError(f"hub unreachable: {body.decode('utf-8', 'replace')}")
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if not 200 <= code < 300:
            reason = data.get("error") if isinstance(data, dict) else None
            raise KbError(
                f"hub /api/questions returned {code}"
                + (f": {reason}" if reason else "")
            )
        if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
            raise KbError("hub /api/questions returned an unexpected body")
        return data["questions"]


def from_env() -> QaClient:
    url, token = os.environ.get(HUB_URL_VAR, ""), os.environ.get(TOKEN_VAR, "")
    for name, value in ((HUB_URL_VAR, url), (TOKEN_VAR, token)):
        if not value:
            raise KbError(f"{name} is not set — the runner reads Q&A from the hub")
    return QaClient(url.rstrip("/"), token)
