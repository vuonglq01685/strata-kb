# src/strata_kb/serving/accounts.py
"""Hub web-UI accounts: SQLite users table, scrypt hashes, session key, bootstrap.

State lives under `<hub root>/.kb-auth/` (kept out of git by
`ensure_git_exclude`): `users.db` holds the accounts, `session.key` signs
session cookies. Stdlib only. Plaintext passwords are never stored or logged.
"""

from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import threading
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from strata_kb.errors import KbError

ROLES: tuple[str, ...] = ("admin", "ba", "dev")

_SCHEME = "scrypt"
_N, _R, _P = 2**14, 8, 1
_SALT_BYTES = 16
_KEY_BYTES = 64
_SESSION_KEY_BYTES = 32
_AUTH_DIR_NAME = ".kb-auth"
_ENV_ADMIN = "STRATA_KB_BOOTSTRAP_ADMIN"
_ENV_HASH = "STRATA_KB_BOOTSTRAP_PASSWORD_HASH"
# Each scrypt holds ~16 MiB; unauthenticated logins run in a 40-thread pool, so
# cap them well inside the hub's 512m container limit.
MAX_CONCURRENT_SCRYPT = 4
_scrypt_slots = threading.BoundedSemaphore(MAX_CONCURRENT_SCRYPT)

_log = logging.getLogger("strata_kb.accounts")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','ba','dev')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class AccountError(KbError):
    """Invalid account operation (bad role, duplicate or missing user, last admin)."""


class AccountExistsError(AccountError):
    """`add_first_admin` found a user already in the table (setup race lost)."""


@dataclass(frozen=True)
class User:
    username: str
    role: str
    password_hash: str
    created_at: str
    updated_at: str


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _scrypt(password: str, salt: bytes) -> bytes:
    # surrogatepass: a lone surrogate in a submitted password must hash, not raise.
    with _scrypt_slots:
        return hashlib.scrypt(
            password.encode("utf-8", errors="surrogatepass"),
            salt=salt,
            n=_N,
            r=_R,
            p=_P,
            dklen=_KEY_BYTES,
            maxmem=256 * _N * _R * _P,
        )


def hash_password(password: str) -> str:
    """`scrypt$n=16384,r=8,p=1$<salt-b64>$<hash-b64>` with a fresh random salt."""
    salt = secrets.token_bytes(_SALT_BYTES)
    key = _scrypt(password, salt)
    return f"{_SCHEME}$n={_N},r={_R},p={_P}${_b64(salt)}${_b64(key)}"


def _parse_hash(stored: str) -> tuple[bytes, bytes] | None:
    """(salt, key) of a stored hash in exactly the current format, else None.

    Only the current parameters are accepted: a stored hash is untrusted input
    (DB row, env var), and anything else is either unverifiable or weak.
    """
    try:
        scheme, params, salt_b64, key_b64 = stored.split("$")
        if scheme != _SCHEME or params != f"n={_N},r={_R},p={_P}":
            return None
        salt = base64.b64decode(salt_b64, validate=True)
        key = base64.b64decode(key_b64, validate=True)
    except (ValueError, binascii.Error):
        return None
    if len(salt) != _SALT_BYTES or len(key) != _KEY_BYTES:
        return None
    return salt, key


def check_password(password: str, stored: str) -> bool:
    """Constant-time check of `password` against `stored`; False when malformed."""
    parsed = _parse_hash(stored)
    if parsed is None:
        return False
    salt, key = parsed
    try:
        return hmac.compare_digest(_scrypt(password, salt), key)
    except ValueError:
        return False


def password_version(stored: str) -> str:
    """Short fingerprint of a stored hash; changes whenever the password does."""
    return hashlib.sha256(stored.encode("utf-8")).hexdigest()[:16]


@functools.cache
def _dummy_hash() -> str:
    return hash_password("strata-kb-timing-dummy")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise AccountError(f"unknown role {role!r}; expected one of {', '.join(ROLES)}")


def _row_to_user(row: tuple[str, str, str, str, str]) -> User:
    username, role, password_hash, created_at, updated_at = row
    return User(username, role, password_hash, created_at, updated_at)


class Accounts:
    """The users table. One short-lived connection per call (thread-safe)."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute(_SCHEMA)
        if os.name != "nt":  # POSIX modes only; password hashes stay owner-readable
            db_path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    def count(self) -> int:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def get(self, username: str) -> User | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT username, role, password_hash, created_at, updated_at "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return _row_to_user(row) if row else None

    def list(self) -> list[User]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT username, role, password_hash, created_at, updated_at "
                "FROM users ORDER BY username"
            ).fetchall()
        return [_row_to_user(r) for r in rows]

    def add(self, username: str, password: str, role: str) -> User:
        if not password:
            raise AccountError("password must not be empty")
        return self.add_hashed(username, hash_password(password), role)

    def add_hashed(self, username: str, password_hash: str, role: str) -> User:
        self._check_new(username, password_hash, role)
        now = _now()
        try:
            with closing(self._connect()) as conn, conn:
                self._insert(conn, username, password_hash, role, now)
        except sqlite3.IntegrityError:
            raise AccountError(f"user {username!r} already exists") from None
        return User(username, role, password_hash, now, now)

    def add_first_admin(self, username: str, password: str) -> User:
        """Insert `username` as admin only if the table is still empty.

        One `BEGIN IMMEDIATE` transaction covers the count and the insert, so
        of two concurrent first-run setups exactly one wins; the other gets
        `AccountExistsError`.
        """
        if not password:
            raise AccountError("password must not be empty")
        password_hash = hash_password(password)  # scrypt stays outside the lock
        self._check_new(username, password_hash, "admin")
        now = _now()
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
                raise AccountExistsError("an account already exists")
            self._insert(conn, username, password_hash, "admin", now)
        return User(username, "admin", password_hash, now, now)

    @staticmethod
    def _check_new(username: str, password_hash: str, role: str) -> None:
        # Usernames are stored verbatim everywhere; surrounding whitespace is refused
        # so `add` and `get`/`verify` can never disagree about the key.
        if not username or username != username.strip():
            raise AccountError(
                "username must be non-empty without surrounding whitespace"
            )
        _check_role(role)
        if _parse_hash(password_hash) is None:
            raise AccountError(
                "password hash is malformed; generate one with `kb user hash`"
            )

    @staticmethod
    def _insert(
        conn: sqlite3.Connection,
        username: str,
        password_hash: str,
        role: str,
        now: str,
    ) -> None:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, role, now, now),
        )

    def set_password(self, username: str, password: str) -> None:
        if not password:
            raise AccountError("password must not be empty")
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE username = ?",
                (hash_password(password), _now(), username),
            )
            if cur.rowcount == 0:
                raise AccountError(f"no such user {username!r}")

    def set_role(self, username: str, role: str) -> None:
        _check_role(role)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if role != "admin":
                self._guard_last_admin(conn, username, "demote")
            cur = conn.execute(
                "UPDATE users SET role = ?, updated_at = ? WHERE username = ?",
                (role, _now(), username),
            )
            if cur.rowcount == 0:
                raise AccountError(f"no such user {username!r}")

    def remove(self, username: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._guard_last_admin(conn, username, "remove")
            cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
            if cur.rowcount == 0:
                raise AccountError(f"no such user {username!r}")

    @staticmethod
    def _guard_last_admin(conn: sqlite3.Connection, username: str, verb: str) -> None:
        """Raise if `username` is the only admin (caller holds the write lock)."""
        row = conn.execute(
            "SELECT role FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None or row[0] != "admin":
            return
        admins = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin'"
        ).fetchone()[0]
        if admins <= 1:
            raise AccountError(f"cannot {verb} the last admin {username!r}")

    def verify(self, username: str, password: str) -> User | None:
        user = self.get(username)
        # Always run one scrypt so timing does not reveal whether the user exists.
        ok = check_password(password, user.password_hash if user else _dummy_hash())
        return user if user and ok else None


def auth_dir_for(kb_dir: Path) -> Path:
    return kb_dir.parent / _AUTH_DIR_NAME


def load_or_create_session_key(auth_dir: Path) -> bytes:
    """The 32-byte cookie-signing key; created (mode 0600) on first use."""
    auth_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = auth_dir / "session.key"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        key = path.read_bytes()
        if len(key) != _SESSION_KEY_BYTES:
            raise AccountError(
                f"{path} is corrupt; delete it to log everyone out and recreate"
            ) from None
        return key
    key = secrets.token_bytes(_SESSION_KEY_BYTES)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


def bootstrap_from_env(accounts: Accounts, env: Mapping[str, str]) -> str:
    """Create the first admin from env vars when the table is empty.

    Returns the log line emitted ("" when the vars are unset). Never logs the hash.
    """
    name = env.get(_ENV_ADMIN, "").strip()
    pw_hash = env.get(_ENV_HASH, "").strip()
    if not name and not pw_hash:
        return ""
    if accounts.count() > 0:
        msg = f"{_ENV_ADMIN}/{_ENV_HASH} ignored: users already exist"
        _log.info(msg)
        return msg
    missing = _ENV_ADMIN if not name else _ENV_HASH if not pw_hash else ""
    if missing:
        msg = f"bootstrap admin not created: {missing} is not set"
    elif _parse_hash(pw_hash) is None:
        msg = (
            f"bootstrap admin not created: {_ENV_HASH} is not a password hash; "
            "generate one with `kb user hash`. If the parts after `$` went "
            "missing, single-quote the value in .env"
        )
    else:
        try:
            accounts.add_hashed(name, pw_hash, "admin")
        except AccountError as exc:
            msg = f"bootstrap admin not created: {exc}"
        else:
            msg = f"bootstrap admin '{name}' created"
            _log.info(msg)
            return msg
    _log.error(msg)
    return msg


def ensure_git_exclude(repo_root: Path, entry: str = f"{_AUTH_DIR_NAME}/") -> bool:
    """Append `entry` to `.git/info/exclude`; True when it wrote the line."""
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        return False
    exclude = git_dir / "info" / "exclude"
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if entry in text.splitlines():
        return False
    exclude.parent.mkdir(parents=True, exist_ok=True)
    sep = "" if not text or text.endswith("\n") else "\n"
    exclude.write_text(f"{text}{sep}{entry}\n", encoding="utf-8", newline="\n")
    return True
