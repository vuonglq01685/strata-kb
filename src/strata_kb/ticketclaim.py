"""Ticket claims on the hub: a Dev takes a hub ticket so no other Dev works it.

Claims live in SQLite at `<hub root>/.kb-qa/claims.db` (kept out of git), one
short-lived connection per call, in the style of `ticketqa.QaStore`. All
timestamps come from the hub clock. Expiry is lazy: a read or a write that
finds an unheld open claim closes it (`close_reason = "expired"`); no job runs.

A claim is held while it is open and any of: it is `stopped`; it is in phase
`review` or `publishing` with a PR set; or it was seen less than `ttl` seconds
ago. The claimer gets a secret token, stored only as a sha256 hash.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from strata_kb.errors import KbError

PHASES: tuple[str, ...] = (
    "claimed",
    "design",
    "plan",
    "execute",
    "handover",
    "waiting-qa",
    "review",
    "publishing",
)
WORKING_PHASES = ("claimed", "design", "plan", "execute", "handover", "waiting-qa")
STATES = ("active", "stopped")
DEFAULT_TTL = 14400  # 4 h
MAX_NAME = 100
MAX_REASON = 1000
MAX_PR = 500

# Phases that stay held, whatever the clock says, while their PR is set.
PR_PHASES = ("review", "publishing")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    ticket TEXT NOT NULL,
    holder TEXT NOT NULL,
    phase TEXT NOT NULL,
    state TEXT NOT NULL,
    pr TEXT NOT NULL,
    stop_reason TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    closed_at TEXT,
    closed_by TEXT,
    close_reason TEXT,
    token_hash TEXT NOT NULL
)
"""
_ONE_OPEN = (
    "CREATE UNIQUE INDEX IF NOT EXISTS one_open_claim "
    "ON claims(repo, ticket) WHERE closed_at IS NULL"
)
_COLUMNS = (
    "id, repo, ticket, holder, phase, state, pr, stop_reason, claimed_at, "
    "last_seen, closed_at, closed_by, close_reason"
)
# An open claim nobody holds: not stopped, not in a PR phase with a PR, and
# last seen at or before the cutoff (parameter 1 of the clause).
_UNHELD = (
    "closed_at IS NULL AND state != 'stopped' "
    f"AND NOT (phase IN ({', '.join('?' * len(PR_PHASES))}) AND pr != '') "
    "AND last_seen <= ?"
)


class ClaimError(KbError):
    """Invalid claim operation (bad input, unknown or closed claim)."""


class ClaimTaken(ClaimError):
    def __init__(self, claim: Claim) -> None:
        super().__init__(f"{claim.repo}:{claim.ticket} is taken by {claim.holder}")
        self.claim = claim


class ClaimLost(ClaimError):
    def __init__(self, close_reason: str, closed_by: str) -> None:
        super().__init__(f"lost: {close_reason} by {closed_by}")
        self.close_reason = close_reason
        self.closed_by = closed_by


class BadClaimToken(ClaimError):
    pass


class UnknownClaim(ClaimError):
    pass


@dataclass(frozen=True)
class Claim:
    id: int
    repo: str
    ticket: str
    holder: str
    phase: str
    state: str
    pr: str
    stop_reason: str
    claimed_at: str
    last_seen: str
    closed_at: str | None
    closed_by: str | None
    close_reason: str | None


def claims_db_path(hub_root: Path) -> Path:
    return hub_root / ".kb-qa" / "claims.db"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _name(label: str, value: str) -> None:
    """One printable line, so it cannot forge a line in a list or the page."""
    if not value.strip():
        raise ClaimError(f"{label} must not be empty")
    if len(value) > MAX_NAME:
        raise ClaimError(f"{label} is {len(value)} characters; the limit is {MAX_NAME}")
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise ClaimError(f"{label} must not contain a control character")


def _reason(label: str, value: str) -> None:
    if len(value) > MAX_REASON:
        raise ClaimError(
            f"{label} is {len(value)} characters; the limit is {MAX_REASON}"
        )


def _pr(value: str) -> None:
    if value and not (value.startswith("https://") and len(value) <= MAX_PR):
        raise ClaimError(f"pr must be empty or an https:// URL of at most {MAX_PR}")


def _one_of(label: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ClaimError(f"{label} must be one of {', '.join(allowed)}, not {value!r}")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _same_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(_hash(token), token_hash)


def _claim(row: tuple) -> Claim:
    return Claim(*row[:13])


class ClaimStore:
    def __init__(
        self,
        db_path: Path,
        ttl: int = DEFAULT_TTL,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._path = db_path
        self._ttl = ttl
        self._now = now
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute(_SCHEMA)
            conn.execute(_ONE_OPEN)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    @contextmanager
    def _txn(self) -> Iterator[tuple[sqlite3.Connection, str]]:
        """One write transaction that has already closed expired claims. A
        `ClaimError` still commits (so a noticed expiry sticks): raise it only
        before the real write."""
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                now = self._now()
                self._expire(conn, now)
                yield conn, _stamp(now)
            except ClaimError:
                conn.commit()
                raise
            except BaseException:
                conn.rollback()
                raise
            conn.commit()

    def _expire(self, conn: sqlite3.Connection, now: datetime) -> None:
        cutoff = _stamp(now - timedelta(seconds=self._ttl))
        sql = (
            "UPDATE claims SET closed_at = ?, closed_by = 'hub', "  # noqa: S608 - fixed fragments
            f"close_reason = 'expired' WHERE {_UNHELD}"
        )
        conn.execute(sql, (_stamp(now), *PR_PHASES, cutoff))

    def _load(self, conn: sqlite3.Connection, claim_id: int) -> tuple[Claim, str]:
        row = conn.execute(
            f"SELECT {_COLUMNS}, token_hash FROM claims WHERE id = ?",  # noqa: S608 - constant columns
            (claim_id,),
        ).fetchone()
        if row is None:
            raise UnknownClaim(f"claim {claim_id} does not exist")
        return _claim(row), row[13]

    def _load_held(self, conn: sqlite3.Connection, claim_id: int, token: str) -> Claim:
        """The claim, if the token is right and it is still open."""
        claim, token_hash = self._load(conn, claim_id)
        if not _same_token(token, token_hash):
            raise BadClaimToken(f"wrong token for claim {claim_id}")
        if claim.closed_at is not None:
            raise ClaimLost(claim.close_reason or "", claim.closed_by or "")
        return claim

    def take(
        self, repo: str, ticket: str, holder: str, token: str | None = None
    ) -> tuple[Claim, str]:
        _name("repo", repo)
        _name("ticket", ticket)
        _name("holder", holder)
        with self._txn() as (conn, now):
            row = conn.execute(
                f"SELECT {_COLUMNS}, token_hash FROM claims "  # noqa: S608 - constant columns
                "WHERE repo = ? AND ticket = ? AND closed_at IS NULL",
                (repo, ticket),
            ).fetchone()
            if row is None:
                token = secrets.token_urlsafe(32)
                cur = conn.execute(
                    "INSERT INTO claims (repo, ticket, holder, phase, state, pr, "
                    "stop_reason, claimed_at, last_seen, token_hash) "
                    "VALUES (?, ?, ?, 'claimed', 'active', '', '', ?, ?, ?)",
                    (repo, ticket, holder, now, now, _hash(token)),
                )
                return self._load(conn, cur.lastrowid or 0)[0], token
            if token is None or not _same_token(token, row[13]):
                raise ClaimTaken(_claim(row))
            # A retry by the holder proves it is alive.
            conn.execute("UPDATE claims SET last_seen = ? WHERE id = ?", (now, row[0]))
            return self._load(conn, row[0])[0], token

    def update(
        self,
        claim_id: int,
        token: str,
        *,
        phase: str | None = None,
        pr: str | None = None,
        state: str | None = None,
        stop_reason: str | None = None,
    ) -> Claim:
        if phase is not None:
            _one_of("phase", phase, PHASES)
        if state is not None:
            _one_of("state", state, STATES)
        if pr is not None:
            _pr(pr)
        if stop_reason is not None:
            _reason("stop_reason", stop_reason)
        if state == "active" and stop_reason is None:
            stop_reason = ""  # resuming clears why it stopped
        changes = {
            col: val
            for col, val in (
                ("phase", phase),
                ("pr", pr),
                ("state", state),
                ("stop_reason", stop_reason),
            )
            if val is not None
        }
        with self._txn() as (conn, now):
            self._load_held(conn, claim_id, token)
            sets = "".join(f", {col} = ?" for col in changes)
            conn.execute(
                f"UPDATE claims SET last_seen = ?{sets} WHERE id = ?",  # noqa: S608 - fixed column names
                (now, *changes.values(), claim_id),
            )
            return self._load(conn, claim_id)[0]

    def _close(
        self, conn: sqlite3.Connection, claim_id: int, now: str, by: str, why: str
    ) -> None:
        conn.execute(
            "UPDATE claims SET closed_at = ?, closed_by = ?, close_reason = ? "
            "WHERE id = ?",
            (now, by, why, claim_id),
        )

    def release(self, claim_id: int, token: str, reason: str) -> None:
        _reason("reason", reason)
        with self._txn() as (conn, now):
            claim = self._load_held(conn, claim_id, token)
            self._close(conn, claim_id, now, claim.holder, f"released: {reason}")

    def admin_release(self, claim_id: int, admin: str, reason: str) -> None:
        _name("admin", admin)
        _reason("reason", reason)
        with self._txn() as (conn, now):
            claim, _ = self._load(conn, claim_id)
            if claim.closed_at is not None:
                raise ClaimError(f"claim {claim_id} is already closed")
            self._close(conn, claim_id, now, admin, f"admin: {reason}")

    def pr_closed(self, claim_id: int, pr: str) -> Claim:
        with self._txn() as (conn, now):
            claim, _ = self._load(conn, claim_id)
            if claim.closed_at is not None:
                raise ClaimError(f"claim {claim_id} is already closed")
            if not pr or pr != claim.pr:
                raise ClaimError("pr_mismatch")
            conn.execute(
                "UPDATE claims SET phase = 'execute', pr = '', last_seen = ? "
                "WHERE id = ?",
                (now, claim_id),
            )
            return self._load(conn, claim_id)[0]

    def held(self, repo: str = "", ticket: str = "") -> list[Claim]:
        where = [
            f"{col} = ?" for col, val in (("repo", repo), ("ticket", ticket)) if val
        ]
        args = [val for val in (repo, ticket) if val]
        clause = "".join(f" AND {w}" for w in where)
        with self._txn() as (conn, _):
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM claims WHERE closed_at IS NULL{clause} "  # noqa: S608 - fixed fragments
                "ORDER BY id",
                args,
            ).fetchall()
        return [_claim(r) for r in rows]

    def close_done(self, done: set[tuple[str, str]]) -> None:
        if not done:
            return
        with self._txn() as (conn, now):
            conn.executemany(
                "UPDATE claims SET closed_at = ?, closed_by = 'hub', "
                "close_reason = 'done' "
                "WHERE repo = ? AND ticket = ? AND closed_at IS NULL",
                [(now, repo, ticket) for repo, ticket in sorted(done)],
            )

    def last_closed(self, repo: str, ticket: str) -> Claim | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM claims "  # noqa: S608 - constant columns
                "WHERE repo = ? AND ticket = ? AND closed_at IS NOT NULL "
                "ORDER BY id DESC LIMIT 1",
                (repo, ticket),
            ).fetchone()
        return _claim(row) if row else None
