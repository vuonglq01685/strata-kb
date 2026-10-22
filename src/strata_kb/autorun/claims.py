"""claims -- the runner's side of ticket claims: take, phase, heartbeat, stop.

One `RunnerClaims` per `kb auto run` on a dev repo. It wraps `ClaimClient` and
`LocalClaims` (the token store `kb claim` in the skills shares) and remembers
each claim's last phase and state, so the loop's exit can release only a claim
that is still mid-work, never a `stopped` or `publishing` one.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

from strata_kb import ghrest
from strata_kb.claimclient import (
    ClaimClient,
    ClaimLostError,
    ClaimTakenError,
    LocalClaims,
)
from strata_kb.errors import KbError
from strata_kb.ticketclaim import WORKING_PHASES

logger = logging.getLogger("strata_kb.autorun.claims")

_PR_NUMBER = re.compile(r"/pull/(\d+)")


class RunnerClaims:
    def __init__(
        self, root: Path, kb_dir: Path, client: ClaimClient, holder: str
    ) -> None:
        self._root, self._client, self._holder = root, client, holder
        self._local = LocalClaims(kb_dir)
        self._known: dict[str, dict] = {}  # ticket -> last claim dict seen
        self._lost: dict[str, str] = {}
        self._lock = threading.Lock()  # the heartbeat thread beats beside the loop

    def held_by_others(self, mine: str | None) -> set[str]:
        """Tickets of every held claim but `mine`'s. A `review` claim whose PR
        was closed unmerged is reported to the hub, which frees it."""
        claims = self._client.held()
        for claim in claims:
            if claim.get("phase") == "review" and claim.get("pr"):
                self._report_closed_pr(claim)
        return {c["ticket"] for c in claims if c["ticket"] != mine}

    def _report_closed_pr(self, claim: dict) -> None:
        match = _PR_NUMBER.search(str(claim["pr"]))
        if match is None:
            return
        try:
            if ghrest.view_pr(self._root, match.group(1)).get("state") == "CLOSED":
                self._client.pr_closed(claim["id"], claim["pr"])
        except KbError as exc:
            logger.warning("PR of %s not checked: %s", claim.get("ticket"), exc)

    def claim(self, ticket: str) -> bool:
        """Take `ticket` (re-claiming with the stored token after a restart).
        False when another Dev holds it."""
        saved = self._local.get(ticket)
        try:
            claim, token = self._client.take(
                ticket, self._holder, saved[1] if saved else None
            )
            if claim.get("state") == "stopped":  # our own, resumed
                claim = self._client.update(claim["id"], token, state="active")
        except ClaimTakenError as exc:
            logger.info(
                "%s is held by %s", ticket, exc.claim.get("holder", "another Dev")
            )
            return False
        except ClaimLostError as exc:
            self._lose(ticket, exc)
            return False
        self._local.put(ticket, claim["id"], token)
        self._remember(ticket, claim)
        return True

    def phase(self, ticket: str, phase: str) -> bool:
        """Move the claim to `phase`; False when it was lost."""
        return self._update(ticket, phase=phase)

    def beat(self, ticket: str) -> bool:
        """Heartbeat. False only when the claim is lost; any other error is a
        warning and the next beat retries."""
        try:
            return self._update(ticket)
        except KbError as exc:
            logger.warning("claim heartbeat on %s failed: %s", ticket, exc)
            return True

    def stop(self, ticket: str, reason: str) -> None:
        """Mark the claim `stopped`: it stays held until the Dev resumes it."""
        try:
            self._update(ticket, state="stopped", stop_reason=reason)
        except KbError as exc:
            logger.warning("claim on %s not marked stopped: %s", ticket, exc)

    def release_if_working(self, ticket: str, reason: str) -> None:
        with self._lock:
            claim = self._known.get(ticket) or {}
        if claim.get("state") == "stopped" or claim.get("phase") not in WORKING_PHASES:
            return
        saved = self._local.get(ticket)
        if saved is None:
            return
        try:
            self._client.release(saved[0], saved[1], reason)
        except ClaimLostError as exc:
            self._lose(ticket, exc)
            return
        except KbError as exc:
            logger.warning("claim on %s not released: %s", ticket, exc)
            return
        self._local.drop(ticket)
        with self._lock:
            self._known.pop(ticket, None)

    def lost_reason(self, ticket: str) -> str:
        with self._lock:
            return self._lost.get(ticket, "")

    def _update(self, ticket: str, **fields: str) -> bool:
        saved = self._local.get(ticket)
        if saved is None:
            with self._lock:
                self._lost[ticket] = "no claim held on this machine"
            return False
        try:
            claim = self._client.update(saved[0], saved[1], **fields)
        except ClaimLostError as exc:
            self._lose(ticket, exc)
            return False
        self._remember(ticket, claim)
        return True

    def _remember(self, ticket: str, claim: dict) -> None:
        with self._lock:
            self._known[ticket] = claim
            self._lost.pop(ticket, None)

    def _lose(self, ticket: str, exc: ClaimLostError) -> None:
        self._local.drop(ticket)
        with self._lock:
            self._known.pop(ticket, None)
            self._lost[ticket] = f"{exc.close_reason} by {exc.closed_by}"
        logger.warning("claim on %s lost: %s", ticket, self.lost_reason(ticket))
