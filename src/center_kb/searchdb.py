from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from center_kb import models
from center_kb.embed import (
    _L2_HEAD_CHARS,
    SEMANTIC_MIN_SCORE,
    Embedder,
    _serialize,
)
from center_kb.mdutils import slice_section

if TYPE_CHECKING:
    from center_kb.federation import FederatedRepo
    from center_kb.hub import HubHandle

logger = logging.getLogger("center_kb.searchdb")

SCHEMA_VERSION = "1"
K_LEG = 50  # top-k mỗi leg đưa vào RRF
RRF_K = 60  # hằng số RRF chuẩn
DB_NAME = "search.db"
_KNN_OVERFETCH = 4  # vec0 không pre-filter tag được — over-fetch rồi lọc sau
_EMBED_BATCH = 256  # số section mỗi lần gọi embedder.embed()
_BUSY_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class SectionRow:
    rowid: int
    repo_id: str
    doc_id: str
    section_id: str
    title: str
    file: str
    doc_revision: str


@dataclass
class SyncReport:
    repos_synced: int = 0
    sections_updated: int = 0
    sections_deleted: int = 0
    embedded: int = 0


def db_path(hub: "HubHandle") -> Path:
    return hub.root / ".kb-work" / DB_NAME


def _vec_available() -> bool:
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        return False
    return True


def _load_vec(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec
    except ImportError:
        return False
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return True


def _raw_connect(path: Path) -> tuple[sqlite3.Connection, bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    vec_loaded = _load_vec(conn)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    return conn, vec_loaded


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS repos(
    repo_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sections(
    id INTEGER PRIMARY KEY,
    repo_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    section_id TEXT NOT NULL,
    title TEXT NOT NULL,
    file TEXT NOT NULL,
    doc_revision TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    UNIQUE(repo_id, doc_id, section_id)
);
CREATE TABLE IF NOT EXISTS doc_tags(
    repo_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY(repo_id, doc_id, tag)
);
"""


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    # FTS5 thường (lưu text) — contentless bị loại vì không DELETE/UPDATE được
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5("
        "title, summary, body_head, tokenize='unicode61')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def _has_vec_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vec_sections'"
    ).fetchone()
    return row is not None


def delete_db(hub: "HubHandle") -> None:
    """Xoá file index (kèm -wal/-shm). Caller phải close mọi connection trước
    (Windows không unlink được file đang mở — spec windows-support §R5).
    PermissionError → propagate, không retry."""
    path = db_path(hub)
    for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        p.unlink(missing_ok=True)


def open_db(hub: "HubHandle") -> sqlite3.Connection:
    """Mở index, tạo schema nếu thiếu. DB hỏng / schema_version lệch /
    có vec_sections nhưng sqlite-vec không cài → xoá + rebuild đúng một lần."""
    path = db_path(hub)
    last_exc: Exception | None = None
    for attempt in (1, 2):
        conn: sqlite3.Connection | None = None
        try:
            conn, vec_loaded = _raw_connect(path)
            _create_schema(conn)
            ver = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()[0]
            if ver == SCHEMA_VERSION and (vec_loaded or not _has_vec_table(conn)):
                return conn
            reason = (
                f"schema_version {ver!r} != {SCHEMA_VERSION!r}"
                if ver != SCHEMA_VERSION
                else "vec_sections exists but sqlite-vec is not installed"
            )
        except sqlite3.DatabaseError as exc:
            last_exc = exc
            reason = str(exc)
        if conn is not None:
            conn.close()  # Windows: close trước khi unlink
        if attempt == 2:
            raise RuntimeError(
                f"search.db unusable even after a rebuild: {reason}"
            ) from last_exc
        logger.warning("rebuilding search.db (%s)", reason)
        delete_db(hub)
    raise AssertionError("unreachable")
