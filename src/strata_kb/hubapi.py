"""hubapi — the hub's `/api/plan/next`, `/api/registry/entry` and `/api/resolve`.

On Claude Code cloud nothing from the hub is copied to disk: the runner and a
few CLI commands read the plan, one registry entry and the resolved kb-context
refs live from the hub server, with the URL and token the session already has.
Same client shape as `autorun/qa.py`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from urllib.parse import urlencode

from strata_kb import httpio
from strata_kb.dockersetup import TOKEN_VAR
from strata_kb.errors import KbError
from strata_kb.kbcontext import KBContextError, parse_ref
from strata_kb.mcpsetup import HUB_URL_VAR
from strata_kb.missionnext import StoryStatus
from strata_kb.resolve import ResolvedRef

Http = Callable[..., tuple[int, bytes]]

PLAN_ROUTE = "/api/plan/next"
REGISTRY_ROUTE = "/api/registry/entry"
RESOLVE_ROUTE = "/api/resolve"
NOT_REGISTERED = "repo_not_registered"


def _story(row: dict) -> StoryStatus:
    return StoryStatus(
        us_id=row["us_id"],
        mission_id=row["mission_id"],
        title=row["title"],
        status=row["status"],
        reasons=tuple(row["reasons"]),
        depends_on=tuple(row["depends_on"]),
    )


def _resolved(row: dict) -> ResolvedRef:
    try:
        ref = parse_ref(row["ref"])
    except KBContextError as exc:
        raise KbError(
            f"hub {RESOLVE_ROUTE} returned a ref we cannot read: {exc}"
        ) from exc
    return ResolvedRef(
        ref=ref,
        status=row["status"],
        citation=row["citation"],
        content=row["content"],
        tokens=row["tokens"],
        reason=row["reason"],
        pinned_rev=row["pinned_rev"],
    )


class HubApi:
    def __init__(self, base_url: str, token: str, http: Http = httpio.request) -> None:
        self.base_url = base_url
        self._token = token
        self._http = http

    def plan_next(
        self, repo: str | None = None
    ) -> tuple[list[StoryStatus], list[StoryStatus], list[str]]:
        """Same triple as `planstatus.next_from_hub`."""
        query = f"?{urlencode({'repo': repo})}" if repo else ""
        data = self._json("GET", PLAN_ROUTE + query, PLAN_ROUTE)
        try:
            return (
                [_story(s) for s in data["stories"]],
                [_story(s) for s in data["unparented"]],
                list(data["notes"]),
            )
        except (KeyError, TypeError) as exc:
            raise self._bad_body(PLAN_ROUTE) from exc

    def registry_entry(self, repo_id: str) -> dict | None:
        """The repo's registry facts; None when the hub does not list it."""
        data = self._json(
            "GET",
            f"{REGISTRY_ROUTE}?{urlencode({'repo_id': repo_id})}",
            REGISTRY_ROUTE,
            absent=NOT_REGISTERED,
        )
        return data or None

    def resolve(self, text: str) -> tuple[str, list[ResolvedRef]]:
        data = self._json(
            "POST", RESOLVE_ROUTE, RESOLVE_ROUTE, body=text.encode("utf-8")
        )
        try:
            return data["version"], [_resolved(r) for r in data["results"]]
        except (KeyError, TypeError) as exc:
            raise self._bad_body(RESOLVE_ROUTE) from exc

    def _json(
        self,
        method: str,
        target: str,
        route: str,
        body: bytes | None = None,
        absent: str = "",
    ) -> dict:
        """The 2xx JSON object; `{}` for a 404 whose error code is `absent`."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "text/plain; charset=utf-8"
        code, raw = self._http(method, f"{self.base_url}{target}", headers, body)
        if code == 0:  # httpio: the request never completed
            raise KbError(f"hub unreachable: {raw.decode('utf-8', 'replace')}")
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        reason = data.get("error") if isinstance(data, dict) else None
        if code == 404:
            if absent and reason == absent:
                return {}
            # A hub that has the route answers with its own error code (or
            # `absent`); a bare 404 means the route itself is missing.
            raise KbError(
                f"hub server has no {route} — upgrade it to strata-kb 1.30.0 or later"
            )
        if not 200 <= code < 300:
            raise KbError(
                f"hub {route} returned {code}" + (f": {reason}" if reason else "")
            )
        if not isinstance(data, dict):
            raise self._bad_body(route)
        return data

    @staticmethod
    def _bad_body(route: str) -> KbError:
        return KbError(f"hub {route} returned an unexpected body")


def from_env() -> HubApi:
    url, token = os.environ.get(HUB_URL_VAR, ""), os.environ.get(TOKEN_VAR, "")
    for name, value in ((HUB_URL_VAR, url), (TOKEN_VAR, token)):
        if not value:
            raise KbError(f"{name} is not set — the runner reads Q&A from the hub")
    return HubApi(url.rstrip("/"), token)
