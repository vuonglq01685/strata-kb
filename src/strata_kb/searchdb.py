from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb import models
from strata_kb.embed import (
    _L2_HEAD_CHARS,
    SEMANTIC_MIN_SCORE,
    Embedder,
    _serialize,
)
from strata_kb.federation import load_federation
from strata_kb.mdutils import slice_section

if TYPE_CHECKING:
    from strata_kb.federation import FederatedRepo
    from strata_kb.hub import HubHandle

logger = logging.getLogger("strata_kb.searchdb")


class IndexBusyError(RuntimeError):
    """The index file is held by another process and could not be replaced.

    Deliberately stays out of the KbError family (Wave G fix round 2, item
    7; comment added round 3, Minor 2): transient and deliberately
    swallowed in publish._publish_direct -- joining would invite a future
    `except KbError` guard to turn a retryable condition into a terminal
    refusal.
    """


class TooManyTagsError(ValueError):
    """`tags` exceeded MAX_TAGS — refused rather than silently truncated."""


SCHEMA_VERSION = "2"
K_LEG = 50  # top-k per leg fed into RRF
RRF_K = 60  # standard RRF constant
MAX_TAGS = 100  # F-C10: `tags` is agent-supplied and expands to one SQL bind each
DB_NAME = "search.db"
_KNN_OVERFETCH = 4  # vec0 cannot pre-filter by tag — over-fetch, then filter after
_EMBED_BATCH = 256  # sections per embedder.embed() call
_BUSY_TIMEOUT_MS = 5000
# bm25 column weights (title, summary, body_l2, body_l3) — title strongest,
# L3 weakest so long raw sections do not drown out title/summary matches (spec §3).
_BM25_WEIGHTS = "4.0, 2.0, 1.5, 1.0"


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


def _conn_vec_loaded(conn: sqlite3.Connection) -> bool:
    """Whether the vec0 extension is loaded on THIS connection — a successful
    sqlite_vec import is not enough (the Python build may lack loadable-extension
    support)."""
    try:
        conn.execute("SELECT vec_version()")
    except sqlite3.OperationalError:
        return False
    return True


_VEC_MODULE = None
_VEC_WARMED = False


def warm_vec() -> bool:
    """Import sqlite_vec exactly once, off any event loop. Never raises.

    Reviewer C F-C1: this import pulls numpy's native `_multiarray_umath`, and
    doing it inside a tool call that FastMCP runs inline on the asyncio
    event-loop thread deadlocks on Windows — the server stays alive and never
    answers. Every entry point that owns an event loop calls this before the
    loop starts; the CLI does not, so `kb` keeps its startup time."""
    global _VEC_MODULE, _VEC_WARMED
    if _VEC_WARMED:
        return _VEC_MODULE is not None
    try:
        import sqlite_vec
    except ImportError:
        _VEC_MODULE = None
    except Exception as exc:  # noqa: BLE001 -- degrade to FTS-only, see comment below
        # Not a plain "not installed" — a partially-initialized numpy, a
        # DLL/version mismatch, or some other failure the import machinery
        # doesn't wrap as ImportError. Degrade to FTS-only same as above, but
        # this case is unexpected enough to be worth a log line (fires once,
        # thanks to _VEC_WARMED).
        logger.warning("sqlite_vec import failed unexpectedly — semantic leg disabled: %s", exc)
        _VEC_MODULE = None
    else:
        _VEC_MODULE = sqlite_vec
    _VEC_WARMED = True
    return _VEC_MODULE is not None


def _load_vec(conn: sqlite3.Connection) -> bool:
    if not warm_vec():
        return False
    try:
        conn.enable_load_extension(True)
        try:
            _VEC_MODULE.load(conn)
        finally:
            conn.enable_load_extension(False)
    except (AttributeError, sqlite3.OperationalError) as exc:
        # Python build lacks loadable-extension support / extension failed to
        # load → degrade to FTS-only instead of breaking search entirely (spec §5)
        logger.warning("sqlite-vec could not be loaded — semantic leg disabled: %s", exc)
        return False
    return True


def is_lock_error(exc: sqlite3.Error) -> bool:
    """Transient lock contention (another process is writing) — not corruption;
    the index must never be deleted for this."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    name = getattr(exc, "sqlite_errorname", "") or ""  # Python >= 3.11
    if name:
        # SQLITE_BUSY(_SNAPSHOT...), SQLITE_LOCKED(_SHAREDCACHE),
        # SQLITE_PROTOCOL ("locking protocol" — the substring match misses it)
        return name.startswith(("SQLITE_BUSY", "SQLITE_LOCKED", "SQLITE_PROTOCOL"))
    return "locked" in str(exc) or "busy" in str(exc)


def classify_db_error(exc: sqlite3.Error) -> str:
    """'lock' | 'client' | 'corrupt' — what to do about a sqlite error.

    Reviewer C F-C2/F-C10: `IntegrityError` (a lost UNIQUE race between two
    cold builds) and `OperationalError: too many SQL variables` (an oversized
    client-supplied `tags` list) are both CALLER problems. They were diagnosed
    as corruption, so the index every user of the hub shares was deleted — and
    on Windows the unlink then raised PermissionError in the user's face."""
    if is_lock_error(exc):
        return "lock"
    if isinstance(exc, sqlite3.IntegrityError):
        return "client"
    if isinstance(exc, sqlite3.OperationalError) and (
        "too many sql variables" in str(exc).lower()
    ):
        return "client"
    return "corrupt"


def _raw_connect(path: Path) -> tuple[sqlite3.Connection, bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_MS / 1000)
    try:
        vec_loaded = _load_vec(conn)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    except BaseException:
        conn.close()  # corrupt file: without a close, Windows cannot unlink it
        raise
    return conn, vec_loaded


# Individual statements, not executescript: sqlite3.Connection.executescript
# issues COMMIT first and then auto-commits each statement, so a concurrent
# opener can see tables without schema_version and treat that as mismatch.
_SCHEMA_STATEMENTS: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS repos(
    repo_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS sections(
    id INTEGER PRIMARY KEY,
    repo_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    section_id TEXT NOT NULL,
    title TEXT NOT NULL,
    file TEXT NOT NULL,
    doc_revision TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    UNIQUE(repo_id, doc_id, section_id)
)""",
    """CREATE TABLE IF NOT EXISTS doc_tags(
    repo_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY(repo_id, doc_id, tag)
)""",
    # regular FTS5 (stores text) — contentless ruled out: no DELETE/UPDATE support
    "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5("
    "title, summary, body_l2, body_l3, tokenize='unicode61')",
)


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create (or complete) the schema in one IMMEDIATE transaction.

    A peer that lost the race blocks on busy_timeout, then sees
    schema_version already written — it must not delete a file the winner
    still holds (Windows cannot unlink an open handle).
    """
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for stmt in _SCHEMA_STATEMENTS:
            conn.execute(stmt)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def _has_vec_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vec_sections'"
    ).fetchone()
    return row is not None


def delete_db(hub: "HubHandle") -> None:
    """Delete the index file (plus -wal/-shm). The caller must close every
    connection first (Windows cannot unlink an open file — spec windows-support
    §R5).

    Reviewer C F-C2: a bare `unlink()` raised `PermissionError [WinError 32]`
    straight at the user when another process still held the file. hashsync's
    force-unlink (chmod +w, retry) exists for exactly this case; a file still
    held after it becomes a clean IndexBusyError, never a traceback.

    The `exists()` check above is not a lock — the file can vanish between it
    and `unlink_force` (another process's own `delete_db`, or SQLite's own
    -wal/-shm cleanup on a concurrent close), so a plain `unlink()` inside
    `unlink_force` can still raise `FileNotFoundError`. That's not busy, it's
    already gone — treat it the same as `not p.exists()` and move on."""
    from strata_kb import hashsync

    path = db_path(hub)
    for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if not p.exists():
            continue
        try:
            hashsync.unlink_force(p)
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise IndexBusyError(
                f"search index {p.name} is in use by another process — "
                "close other kb commands and retry"
            ) from exc


def _has_schema(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    return row is not None


def open_db(hub: "HubHandle") -> sqlite3.Connection:
    """Open the index, creating the schema if missing. Corrupt DB /
    schema_version mismatch / vec_sections present but sqlite-vec not installed
    → delete + rebuild exactly once.

    The warm path (schema already present) only READS — it takes no write lock,
    so queries can run in parallel with a long sync that is writing (spec §3.2)."""
    path = db_path(hub)
    last_exc: Exception | None = None
    for attempt in (1, 2):
        conn: sqlite3.Connection | None = None
        try:
            conn, vec_loaded = _raw_connect(path)
            if not _has_schema(conn):
                _create_schema(conn)  # cold — needs write; raises under lock
            row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            ver = row[0] if row else None
            if ver is None:
                # In-progress or leftover cold build (tables visible, version
                # not yet inserted). Complete it under BEGIN IMMEDIATE — never
                # delete a file another process still holds.
                _create_schema(conn)
                row = conn.execute(
                    "SELECT value FROM meta WHERE key='schema_version'"
                ).fetchone()
                ver = row[0] if row else None
            if ver == SCHEMA_VERSION and (vec_loaded or not _has_vec_table(conn)):
                return conn
            reason = (
                f"schema_version {ver!r} != {SCHEMA_VERSION!r}"
                if ver != SCHEMA_VERSION
                else "vec_sections exists but sqlite-vec is not installed"
            )
        except sqlite3.DatabaseError as exc:
            # F-C2: route through the same classifier query._search_index uses —
            # lock = contention, client = caller input. Neither is corruption,
            # so neither may reach delete_db() (spec §2 — "no client input
            # reaches delete_db()").
            if classify_db_error(exc) in ("lock", "client"):
                if conn is not None:
                    conn.close()
                raise
            last_exc = exc
            reason = str(exc)
        if conn is not None:
            conn.close()  # Windows: close before unlink
        if attempt == 2:
            raise RuntimeError(
                f"search.db unusable even after a rebuild: {reason}"
            ) from last_exc
        logger.warning("rebuilding search.db (%s)", reason)
        delete_db(hub)
    raise AssertionError("unreachable")


def _repo_fingerprint(repo_dir: Path) -> str:
    """Stat manifest of the whole federation entry directory.

    Reviewer C F-C3: hashing only `_meta.yaml` and `index.yaml` made an edit
    committed directly in `federation/` on the hub invisible to search forever,
    while `kb get` returned it.

    Stat, don't read: this runs on EVERY query, so its cost must not scale with
    corpus bytes. (relpath, size, mtime_ns) catches both committed and
    uncommitted hub-side edits; `kb reindex --force` is the escape hatch for
    the theoretical edit that preserves all three.

    Review round 2 (F-C3 findings 1+2): walks with `os.scandir` +
    `DirEntry.is_dir(follow_symlinks=False)` / `.is_file(follow_symlinks=False)`
    / `.stat(follow_symlinks=False)` — the standard fast-walk recipe — instead
    of `Path.rglob` + `Path.stat`. `DirEntry.stat()` reuses the stat data the
    directory enumeration already returned (no extra syscall per file on
    Windows); `is_dir(follow_symlinks=False)` / `is_file(follow_symlinks=False)`
    both report False for a symlink entry (of either a file or a directory)
    without following it — that's how a symlinked directory is skipped
    without ever being descended into.

    The relpath is built by plain string slicing (`entry.path` is always
    `<repo_dir><sep><...>` because the walk only ever scans paths it built
    from `repo_dir` itself), not `Path(entry.path).relative_to(repo_dir)`:
    profiling this rewrite showed `Path.relative_to` — not `DirEntry.stat` —
    was the dominant remaining cost, roughly doubling the walk on its own
    (measured on a 1202-file synthetic tree: 24.84ms stat-only vs 43.66ms
    with `Path.relative_to` added, vs 23.30ms with string slicing). Skipping
    it is what actually delivers the scandir speedup end to end; see the
    commit message for the full before/after curve.

    A per-entry OSError (a file vanishing between being listed and being
    stat'd — a concurrent `git pull`/publish on the hub, which is also the
    query source, is a real race) is swallowed and that entry skipped: a
    per-query freshness check must never raise a traceback at the caller.

    Cost scales with directory count as much as file count (`os.scandir()`
    is one syscall per directory), not corpus bytes: measured, the 20ms
    gate is crossed around 2,900-3,700 files for a few chapter-heavy doc
    dirs, and around 700-900 files for many single-chapter doc dirs (this
    repo's own `.kb/` shape, scaled up) — both a couple of orders past the
    pre-rewrite `Path.rglob` walk's ~465-file crossing point. `kb reindex
    --force` is the fallback for a corpus that outgrows this per-query check."""
    h = hashlib.sha256()
    if not repo_dir.is_dir():
        return h.hexdigest()
    records: list[tuple[str, int, int]] = []
    base = str(repo_dir)
    if not base.endswith(os.sep):
        base += os.sep
    stack: list[str] = [str(repo_dir)]
    while stack:
        current = stack.pop()
        try:
            it = os.scandir(current)
        except OSError:
            continue  # dir vanished/unreadable between being queued and scanned
        try:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        rel = entry.path[len(base):].replace(os.sep, "/")
                        records.append((rel, st.st_size, st.st_mtime_ns))
                    # else: a symlink (to a file or a directory) — skip, don't descend
                except OSError:
                    continue  # vanished/unreadable between scandir() and is_dir/stat
        finally:
            it.close()  # release the directory handle promptly (not just on GC)
    for rel, size, mtime_ns in sorted(records):
        h.update(f"{rel}\0{size}\0{mtime_ns}\0".encode("utf-8"))
    return h.hexdigest()


def _section_parts(
    kb_dir: Path, doc_id: str, sec: models.SectionEntry
) -> tuple[str, str, str, str]:
    """(title, summary, body_l2, body_l3) — body_l2 = FULL L2 slice (summary
    + tables, no cap), body_l3 = full L3 slice from .raw.md."""
    body_l2 = ""
    l2_path = kb_dir / doc_id / f"{sec.file}.md"
    if l2_path.exists():
        body_l2 = slice_section(l2_path.read_text(encoding="utf-8"), sec.id) or ""
    body_l3 = ""
    l3_path = kb_dir / doc_id / f"{sec.file}.raw.md"
    if l3_path.exists():
        body_l3 = slice_section(l3_path.read_text(encoding="utf-8"), sec.id) or ""
    else:
        logger.warning("raw L3 missing — FTS indexes L2 only: %s", l3_path)
    return sec.title, sec.summary, body_l2, body_l3


def _embed_text(title: str, summary: str, body: str) -> str:
    """Same text format as the old embed._section_text — used for embedding (body
    always capped at _L2_HEAD_CHARS, bounding the embedding model input)."""
    text = f"{title}\n{summary}"
    return f"{text}\n{body}" if body else text


def _content_digest(title: str, summary: str, body_l2: str, body_l3: str) -> str:
    """Change-detection hash — covers EVERY FTS column (the embed text stays
    capped: hash and embed were decoupled as of schema v2)."""
    joined = "\n".join((title, summary, body_l2, body_l3))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _delete_section(conn: sqlite3.Connection, rowid: int) -> None:
    conn.execute("DELETE FROM sections WHERE id = ?", (rowid,))
    conn.execute("DELETE FROM fts WHERE rowid = ?", (rowid,))
    if _has_vec_table(conn):
        conn.execute("DELETE FROM vec_sections WHERE rowid = ?", (rowid,))


def _drop_repo(conn: sqlite3.Connection, repo_id: str) -> int:
    rowids = [
        r[0]
        for r in conn.execute("SELECT id FROM sections WHERE repo_id = ?", (repo_id,))
    ]
    for rowid in rowids:
        _delete_section(conn, rowid)
    conn.execute("DELETE FROM doc_tags WHERE repo_id = ?", (repo_id,))
    return len(rowids)


def _sync_repo(
    conn: sqlite3.Connection, repo: "FederatedRepo", report: SyncReport
) -> None:
    rid = repo.meta.repo_id
    stored = {
        (doc_id, sec_id): (rowid, chash)
        for rowid, doc_id, sec_id, chash in conn.execute(
            "SELECT id, doc_id, section_id, content_hash FROM sections "
            "WHERE repo_id = ?",
            (rid,),
        )
    }
    seen: set[tuple[str, str]] = set()
    for doc in repo.index.docs:
        manifest_path = repo.kb_dir / doc.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        for sec in manifest.sections:
            key = (doc.id, sec.id)
            seen.add(key)
            title, summary, body_l2, body_l3 = _section_parts(
                repo.kb_dir, doc.id, sec
            )
            digest = _content_digest(title, summary, body_l2, body_l3)
            old = stored.get(key)
            if old is not None and old[1] == digest:
                # content_hash covers title+summary+body_l2+body_l3 — an equal
                # hash means the content is unchanged; only file/doc_revision
                # can drift (L2 file rename, revision bump) without a content
                # change. Refresh those 2 columns so citation/path stay accurate
                # (no FTS rewrite, no re-embed).
                conn.execute(
                    "UPDATE sections SET file = ?, doc_revision = ? "
                    "WHERE id = ? AND (file != ? OR doc_revision != ?)",
                    (sec.file, doc.revision, old[0], sec.file, doc.revision),
                )
                continue
            # delete + insert (new rowid) — the vec backfill relies on new
            # rowids lacking an embedding to know what needs re-embedding.
            # Delete by natural key, not by the `stored` rowid snapshot: another
            # process may have replaced the row since the snapshot was read —
            # losing the race must be idempotent and must not break UNIQUE
            # (spec §5: losing the race only wastes work, never corrupts data).
            for (cur_id,) in conn.execute(
                "SELECT id FROM sections WHERE repo_id = ? AND doc_id = ? "
                "AND section_id = ?",
                (rid, doc.id, sec.id),
            ).fetchall():
                _delete_section(conn, cur_id)
            cur = conn.execute(
                "INSERT INTO sections(repo_id, doc_id, section_id, title, file, "
                "doc_revision, content_hash) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (rid, doc.id, sec.id, sec.title, sec.file, doc.revision, digest),
            )
            conn.execute(
                "INSERT INTO fts(rowid, title, summary, body_l2, body_l3) "
                "VALUES(?, ?, ?, ?, ?)",
                (cur.lastrowid, title, summary, body_l2, body_l3),
            )
            report.sections_updated += 1
    for key, (rowid, _) in stored.items():
        if key not in seen:
            _delete_section(conn, rowid)
            report.sections_deleted += 1
    conn.execute("DELETE FROM doc_tags WHERE repo_id = ?", (rid,))
    for doc in repo.index.docs:
        for tag in {t.strip().lower() for t in doc.tags} | {doc.id.lower()}:
            conn.execute(
                "INSERT OR IGNORE INTO doc_tags(repo_id, doc_id, tag) "
                "VALUES(?, ?, ?)",
                (rid, doc.id, tag),
            )


def _sync_vectors(
    conn: sqlite3.Connection, embedder: Embedder | None, report: SyncReport
) -> None:
    if embedder is None or not _conn_vec_loaded(conn):
        return
    meta = dict(conn.execute("SELECT key, value FROM meta"))
    model_changed = (
        meta.get("embed_model") != embedder.name
        or meta.get("embed_dim") != str(embedder.dim)
    )
    if _has_vec_table(conn) and model_changed:
        conn.execute("DROP TABLE vec_sections")  # model/dim change → rebuild vec table
    table_created = not _has_vec_table(conn)
    if table_created:
        conn.execute(
            f"CREATE VIRTUAL TABLE vec_sections USING vec0("
            f"embedding float[{embedder.dim}])"
        )
    if table_created or model_changed:
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('embed_model', ?)",
            (embedder.name,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('embed_dim', ?)",
            (str(embedder.dim),),
        )
        # mark dirty in the SAME transaction as the new model meta: the first
        # batch commit seals the meta — if the backfill is interrupted mid-way
        # while coverage still says 'complete' from the old model, the vector
        # gaps stay hidden forever
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('vec_coverage', 'dirty')"
        )
    elif meta.get("vec_coverage") == "complete":
        return  # no new sections, model unchanged → skip the O(N) anti-join
    # Anti-join finds rowids missing an embedding — do NOT load FTS text here:
    # every search() calls open_fresh → _sync_vectors; only SELECT text when
    # rowids are missing, and chunk by _EMBED_BATCH: 1 bind/section in a single
    # IN(...) statement blows SQLITE_MAX_VARIABLE_NUMBER (32766 on default
    # builds) well before the 100k scope target, and fetchall of the whole
    # corpus text burns RAM for nothing.
    missing_ids = [
        r[0]
        for r in conn.execute(
            "SELECT s.id FROM sections s LEFT JOIN vec_sections v "
            "ON v.rowid = s.id WHERE v.rowid IS NULL"
        )
    ]
    for start in range(0, len(missing_ids), _EMBED_BATCH):
        chunk = missing_ids[start : start + _EMBED_BATCH]
        placeholders = ",".join("?" * len(chunk))
        batch = conn.execute(
            "SELECT s.id, f.title, f.summary, f.body_l2 FROM sections s "  # noqa: S608 -- placeholders is a "?"-count string only, values bind via `chunk` below
            f"JOIN fts f ON f.rowid = s.id WHERE s.id IN ({placeholders})",
            chunk,
        ).fetchall()
        vectors = embedder.embed(
            [
                _embed_text(title, summary, body[:_L2_HEAD_CHARS])
                for _, title, summary, body in batch
            ]
        )
        for (rowid, *_), vec in zip(batch, vectors):
            if len(vec) != embedder.dim:
                raise ValueError(
                    f"embedder returned a {len(vec)}-dim vector, expected "
                    f"{embedder.dim} dims (embedder.dim) — check the embedder"
                )
            conn.execute(
                "INSERT INTO vec_sections(rowid, embedding) VALUES(?, ?)",
                (rowid, _serialize(vec)),
            )
        report.embedded += len(batch)
        conn.commit()  # per batch — an interrupted cold build keeps embedded batches
    # only mark complete once the entire backfill is done — a mid-way failure
    # leaves it dirty so the next sync resumes the scan
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('vec_coverage', 'complete')"
    )


def _cleanup_legacy(hub: "HubHandle") -> None:
    """Clean up embeddings-<rid>.db from the old architecture — pure cache,
    abandoned (spec §4)."""
    work = hub.root / ".kb-work"
    if not work.is_dir():
        return
    for p in work.glob("embeddings-*.db"):
        try:
            p.unlink()
        except OSError:  # held by another process (Windows) — clean up next time
            pass


def _sync_conn(
    conn: sqlite3.Connection,
    hub: "HubHandle",
    embedder: Embedder | None,
    *,
    vectors_strict: bool = True,
) -> SyncReport:
    report = SyncReport()
    repos = load_federation(hub.federation_dir)
    live_ids = {r.meta.repo_id for r in repos}
    stored_fp = dict(conn.execute("SELECT repo_id, fingerprint FROM repos"))
    for rid in sorted(set(stored_fp) - live_ids):
        report.sections_deleted += _drop_repo(conn, rid)
        conn.execute("DELETE FROM repos WHERE repo_id = ?", (rid,))
    if conn.in_transaction:
        conn.commit()
    for repo in repos:
        fp = _repo_fingerprint(repo.kb_dir)
        if stored_fp.get(repo.meta.repo_id) == fp:
            continue  # repo unchanged — 0 manifest parses
        # F-C2: `stored_fp` was read outside any lock, so two cold processes
        # both got here and the loser broke UNIQUE. Take the write lock FIRST,
        # then re-read this repo's fingerprint inside it: the loser now sees
        # the winner's row and skips instead of inserting (spec §5 — losing the
        # race only wastes work, never corrupts data).
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT fingerprint FROM repos WHERE repo_id = ?",
            (repo.meta.repo_id,),
        ).fetchone()
        if row is not None and row[0] == fp:
            conn.commit()
            continue
        before_updated = report.sections_updated
        _sync_repo(conn, repo, report)
        conn.execute(
            "INSERT INTO repos(repo_id, fingerprint) VALUES(?, ?) "
            "ON CONFLICT(repo_id) DO UPDATE SET fingerprint = excluded.fingerprint",
            (repo.meta.repo_id, fp),
        )
        report.repos_synced += 1
        if report.sections_updated > before_updated:
            # new rowids have no embedding yet — lets _sync_vectors skip the
            # O(N) anti-join when nothing is new (only INSERTs create gaps;
            # deletes remove the vec row too, metadata refresh keeps the rowid)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) "
                "VALUES('vec_coverage', 'dirty')"
            )
        # commit per repo: an interrupted sync keeps the repos already done, and
        # narrows the writer-lock window for concurrently reading processes. It
        # also guarantees FTS/sections are durable before the embed phase — an
        # embed failure does not roll them back.
        conn.commit()
    try:
        _sync_vectors(conn, embedder, report)
        if conn.in_transaction:
            conn.commit()
    except sqlite3.DatabaseError:
        raise  # index corrupt — let the layer above rebuild/raise, do not swallow
    except Exception as exc:
        if vectors_strict:
            raise  # kb reindex must see embed failures
        if conn.in_transaction:
            conn.rollback()
        # spec §5: embedding is best-effort — queries degrade to the FTS leg
        logger.warning("vector sync failed — keyword search only: %s", exc)
    _cleanup_legacy(hub)
    return report


def sync(hub: "HubHandle", embedder: Embedder | None) -> SyncReport:
    """Incremental sync: repo fingerprint → skip/diff by content-hash."""
    conn = open_db(hub)
    try:
        return _sync_conn(conn, hub, embedder)
    finally:
        conn.close()


def open_fresh(hub: "HubHandle", embedder: Embedder | None) -> sqlite3.Connection:
    """Open + lazy freshness check (incremental sync if stale), return the
    connection. An embed failure here does not kill the query — degrade to
    FTS-only (vectors_strict=False)."""
    conn = open_db(hub)
    try:
        _sync_conn(conn, hub, embedder, vectors_strict=False)
    except BaseException:
        conn.close()
        raise
    return conn


def tokenize(text: str) -> list[str]:
    """Query-side tokens, symmetric with the index's `unicode61` tokenizer.

    Reviewer C F-C9: `[a-z0-9]+` dropped every non-ASCII letter while the FTS
    index holds them, so a Vietnamese query was shredded into 1-2 character
    fragments and answered confidently with junk. `[^\\W_]+` is unicode61's own
    rule: alphanumerics are token characters, and underscore is a separator.
    NFC-normalise first: an NFD query (macOS, some IMEs) spells each accented
    letter as base + combining mark, and a combining mark is category Mn —
    not `\\w` — so `[^\\W_]+` would split right through it; unicode61 folds
    combining marks on both sides, so the query side must match."""
    return re.findall(
        r"[^\W_]+", unicodedata.normalize("NFC", text).lower(), re.UNICODE
    )


def _norm_tags(tags: list[str] | None) -> list[str]:
    out = sorted({t.strip().lower() for t in tags or [] if t.strip()})
    if len(out) > MAX_TAGS:
        # Refuse, do not truncate: a silently shortened filter returns results
        # the caller did not ask for. The published federation vocabulary is a
        # handful of tags, so no real caller meets this cap (F-C10).
        raise TooManyTagsError(
            f"too many tags ({len(out)}) — at most {MAX_TAGS} are accepted"
        )
    return out


def _fts_match(text: str) -> str:
    """Query text → FTS5 MATCH string: quote each token, OR semantics.
    User input never touches FTS syntax directly."""
    return " OR ".join(f'"{tok}"' for tok in tokenize(text))


def fts_search(
    conn: sqlite3.Connection,
    text: str,
    tags: list[str] | None = None,
    k: int = K_LEG,
) -> list[tuple[int, float]]:
    """Keyword leg — (section_rowid, score) best-first; score = -bm25 (positive)."""
    match = _fts_match(text)
    if not match:
        return []
    sql = (
        f"SELECT fts.rowid, -bm25(fts, {_BM25_WEIGHTS}) FROM fts "  # noqa: S608 -- _BM25_WEIGHTS is a fixed module constant; text/tags bind as params below
        "JOIN sections s ON s.id = fts.rowid WHERE fts MATCH ?"
    )
    params: list[object] = [match]
    tag_list = _norm_tags(tags)
    if tag_list:
        placeholders = ",".join("?" * len(tag_list))
        sql += (
            " AND EXISTS (SELECT 1 FROM doc_tags t WHERE t.repo_id = s.repo_id"  # noqa: S608 -- placeholders is a "?"-count string only, values bind via `params` below
            f" AND t.doc_id = s.doc_id AND t.tag IN ({placeholders}))"
        )
        params += tag_list
    sql += f" ORDER BY bm25(fts, {_BM25_WEIGHTS}) LIMIT ?"  # lower bm25 = better match
    params.append(k)
    return [(rowid, score) for rowid, score in conn.execute(sql, params)]


def _tagged_rowids(
    conn: sqlite3.Connection, rowids: list[int], tag_list: list[str]
) -> set[int]:
    if not rowids:
        return set()
    ph_rows = ",".join("?" * len(rowids))
    ph_tags = ",".join("?" * len(tag_list))
    rows = conn.execute(
        f"SELECT s.id FROM sections s WHERE s.id IN ({ph_rows}) AND EXISTS ("  # noqa: S608 -- ph_rows/ph_tags are "?"-count strings only, values bind via the list below
        "SELECT 1 FROM doc_tags t WHERE t.repo_id = s.repo_id "
        f"AND t.doc_id = s.doc_id AND t.tag IN ({ph_tags}))",
        [*rowids, *tag_list],
    )
    return {r[0] for r in rows}


def knn_search(
    conn: sqlite3.Connection,
    embedder: Embedder,
    text: str,
    tags: list[str] | None = None,
    k: int = K_LEG,
) -> list[tuple[int, float]]:
    """Semantic leg — (section_rowid, score) best-first, score = 1/(1+distance),
    already filtered by SEMANTIC_MIN_SCORE. vec0 cannot pre-filter by tag →
    over-fetch, then filter."""
    if not _has_vec_table(conn):
        return []
    query_vec = embedder.embed([text])[0]
    tag_list = _norm_tags(tags)
    fetch_k = k * _KNN_OVERFETCH if tag_list else k
    rows = conn.execute(
        "SELECT rowid, distance FROM vec_sections "
        "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (_serialize(query_vec), fetch_k),
    ).fetchall()
    hits = [
        (rowid, 1.0 / (1.0 + dist))
        for rowid, dist in rows
        if 1.0 / (1.0 + dist) >= SEMANTIC_MIN_SCORE
    ]
    if tag_list:
        allowed = _tagged_rowids(conn, [h[0] for h in hits], tag_list)
        hits = [h for h in hits if h[0] in allowed]
    return hits[:k]


def rrf_merge(
    fts_hits: list[tuple[int, float]],
    knn_hits: list[tuple[int, float]],
    k: int = RRF_K,
) -> list[tuple[int, float, str]]:
    """Reciprocal Rank Fusion: score = Σ 1/(k + rank) over the legs containing
    the rowid. Returns (rowid, score, mode) sorted by descending score,
    ties broken by ascending rowid."""
    scores: dict[int, float] = {}
    legs: dict[int, set[str]] = {}
    for mode, hits in (("keyword", fts_hits), ("semantic", knn_hits)):
        for rank, (rowid, _leg_score) in enumerate(hits, start=1):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (k + rank)
            legs.setdefault(rowid, set()).add(mode)

    def _mode(rowid: int) -> str:
        m = legs[rowid]
        return "hybrid" if len(m) == 2 else next(iter(m))

    return sorted(
        ((rowid, score, _mode(rowid)) for rowid, score in scores.items()),
        key=lambda t: (-t[1], t[0]),
    )


def load_sections(
    conn: sqlite3.Connection, rowids: Iterable[int]
) -> dict[int, SectionRow]:
    ids = list(rowids)
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        "SELECT id, repo_id, doc_id, section_id, title, file, doc_revision "  # noqa: S608 -- placeholders is a "?"-count string only, values bind via `ids` below
        f"FROM sections WHERE id IN ({placeholders})",
        ids,
    )
    return {r[0]: SectionRow(*r) for r in rows}
