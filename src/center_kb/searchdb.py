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
from center_kb.federation import load_federation
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


def _conn_vec_loaded(conn: sqlite3.Connection) -> bool:
    """Extension vec0 có load được trên connection NÀY không — import sqlite_vec
    thành công chưa đủ (Python build có thể thiếu loadable-extension support)."""
    try:
        conn.execute("SELECT vec_version()")
    except sqlite3.OperationalError:
        return False
    return True


def _load_vec(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec
    except ImportError:
        return False
    try:
        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
    except (AttributeError, sqlite3.OperationalError) as exc:
        # Python build thiếu loadable-extension support / extension load fail
        # → degrade FTS-only thay vì vỡ toàn bộ search (spec §5)
        logger.warning("sqlite-vec could not be loaded — semantic leg disabled: %s", exc)
        return False
    return True


def is_lock_error(exc: sqlite3.Error) -> bool:
    """Tranh chấp lock tạm thời (process khác đang ghi) — không phải corruption,
    tuyệt đối không được xoá index."""
    return isinstance(exc, sqlite3.OperationalError) and (
        "locked" in str(exc) or "busy" in str(exc)
    )


def _raw_connect(path: Path) -> tuple[sqlite3.Connection, bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        vec_loaded = _load_vec(conn)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    except BaseException:
        conn.close()  # file hỏng: không close thì Windows không unlink được
        raise
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
            if is_lock_error(exc):
                if conn is not None:
                    conn.close()
                raise
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


def _repo_fingerprint(repo_dir: Path) -> str:
    h = hashlib.sha256()
    for name in ("_meta.yaml", "index.yaml"):
        h.update((repo_dir / name).read_bytes())
    return h.hexdigest()


def _section_parts(
    kb_dir: Path, doc_id: str, sec: models.SectionEntry
) -> tuple[str, str, str]:
    """(title, summary, body_head) — body_head = 500 ký tự đầu L2."""
    body = ""
    l2_path = kb_dir / doc_id / f"{sec.file}.md"
    if l2_path.exists():
        content = slice_section(l2_path.read_text(encoding="utf-8"), sec.id)
        if content:
            body = content[:_L2_HEAD_CHARS]
    return sec.title, sec.summary, body


def _embed_text(title: str, summary: str, body: str) -> str:
    """Cùng format text với embed._section_text cũ — dùng cho content_hash + embedding."""
    text = f"{title}\n{summary}"
    return f"{text}\n{body}" if body else text


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
            title, summary, body = _section_parts(repo.kb_dir, doc.id, sec)
            digest = hashlib.sha256(
                _embed_text(title, summary, body).encode("utf-8")
            ).hexdigest()
            old = stored.get(key)
            if old is not None and old[1] == digest:
                # content_hash chỉ hash _embed_text(...) (title+summary+body) —
                # title/file/doc_revision có thể đổi (rename, bump revision)
                # mà không đổi nội dung section; giữ content_hash semantics
                # nguyên vẹn nhưng vẫn refresh 3 cột này để citation/path
                # không bị lệch (không rewrite FTS, không re-embed).
                conn.execute(
                    "UPDATE sections SET title = ?, file = ?, doc_revision = ? "
                    "WHERE id = ? AND (title != ? OR file != ? OR doc_revision != ?)",
                    (
                        sec.title, sec.file, doc.revision, old[0],
                        sec.title, sec.file, doc.revision,
                    ),
                )
                continue
            if old is not None:
                # delete + insert (rowid mới) — vec-backfill Task 3 dựa vào
                # rowid mới thiếu embedding để biết cần re-embed
                _delete_section(conn, old[0])
            cur = conn.execute(
                "INSERT INTO sections(repo_id, doc_id, section_id, title, file, "
                "doc_revision, content_hash) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (rid, doc.id, sec.id, sec.title, sec.file, doc.revision, digest),
            )
            conn.execute(
                "INSERT INTO fts(rowid, title, summary, body_head) "
                "VALUES(?, ?, ?, ?)",
                (cur.lastrowid, title, summary, body),
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
        conn.execute("DROP TABLE vec_sections")  # đổi model/dim → rebuild bảng vec
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
    if not (table_created or model_changed) and meta.get("vec_coverage") == "complete":
        return  # không có section mới, model không đổi → khỏi anti-join O(N)
    # Anti-join tìm rowid thiếu embedding — KHÔNG load FTS text ở đây: mỗi
    # search() gọi open_fresh → _sync_vectors; chỉ SELECT text khi có rowid thiếu.
    missing_ids = [
        r[0]
        for r in conn.execute(
            "SELECT s.id FROM sections s LEFT JOIN vec_sections v "
            "ON v.rowid = s.id WHERE v.rowid IS NULL"
        )
    ]
    if not missing_ids:
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('vec_coverage', 'complete')"
        )
        return
    placeholders = ",".join("?" * len(missing_ids))
    missing = conn.execute(
        "SELECT s.id, f.title, f.summary, f.body_head FROM sections s "
        f"JOIN fts f ON f.rowid = s.id WHERE s.id IN ({placeholders})",
        missing_ids,
    ).fetchall()
    for start in range(0, len(missing), _EMBED_BATCH):
        batch = missing[start : start + _EMBED_BATCH]
        vectors = embedder.embed(
            [_embed_text(title, summary, body) for _, title, summary, body in batch]
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
        conn.commit()  # per batch — cold build bị ngắt giữ lại batch đã embed
    # chỉ đánh dấu complete khi toàn bộ backfill xong — fail giữa chừng để
    # dirty cho lần sync sau quét tiếp
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('vec_coverage', 'complete')"
    )


def _cleanup_legacy(hub: "HubHandle") -> None:
    """Dọn embeddings-<rid>.db của kiến trúc cũ — cache thuần, bỏ rơi (spec §4)."""
    work = hub.root / ".kb-work"
    if not work.is_dir():
        return
    for p in work.glob("embeddings-*.db"):
        try:
            p.unlink()
        except OSError:  # đang bị process khác giữ (Windows) — lần sau dọn tiếp
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
            continue  # repo không đổi — 0 manifest parse
        before_updated = report.sections_updated
        _sync_repo(conn, repo, report)
        conn.execute(
            "INSERT INTO repos(repo_id, fingerprint) VALUES(?, ?) "
            "ON CONFLICT(repo_id) DO UPDATE SET fingerprint = excluded.fingerprint",
            (repo.meta.repo_id, fp),
        )
        report.repos_synced += 1
        if report.sections_updated > before_updated:
            # rowid mới chưa có embedding — cho phép _sync_vectors bỏ qua
            # anti-join O(N) khi không có gì mới (chỉ INSERT tạo lỗ;
            # delete xoá vec row kèm, metadata refresh giữ nguyên rowid)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) "
                "VALUES('vec_coverage', 'dirty')"
            )
        # commit per repo: sync bị ngắt giữ lại repo đã xong, và thu hẹp
        # writer-lock window cho process đọc song song. Đồng thời đảm bảo
        # FTS/sections đã bền trước phase embed — embed fail không rollback.
        conn.commit()
    try:
        _sync_vectors(conn, embedder, report)
        if conn.in_transaction:
            conn.commit()
    except sqlite3.DatabaseError:
        raise  # index hỏng — để tầng trên rebuild/raise, không nuốt
    except Exception as exc:
        if vectors_strict:
            raise  # kb reindex phải thấy lỗi embed
        if conn.in_transaction:
            conn.rollback()
        # spec §5: embedding best-effort — query degrade về FTS leg
        logger.warning("vector sync failed — keyword search only: %s", exc)
    _cleanup_legacy(hub)
    return report


def sync(hub: "HubHandle", embedder: Embedder | None) -> SyncReport:
    """Incremental sync: repo fingerprint → skip/diff theo content-hash."""
    conn = open_db(hub)
    try:
        return _sync_conn(conn, hub, embedder)
    finally:
        conn.close()


def open_fresh(hub: "HubHandle", embedder: Embedder | None) -> sqlite3.Connection:
    """Open + lazy freshness check (sync incremental nếu lệch), trả connection.
    Embed fail ở đây không giết query — degrade FTS-only (vectors_strict=False)."""
    conn = open_db(hub)
    try:
        _sync_conn(conn, hub, embedder, vectors_strict=False)
    except BaseException:
        conn.close()
        raise
    return conn


def tokenize(text: str) -> list[str]:
    # ASCII-only trong khi corpus được FTS index bằng unicode61 — term
    # non-ASCII (vd tiếng Việt) có trong index nhưng query không chạm tới.
    # Chấp nhận: corpus aviation spec tiếng Anh; mở rộng khi có nhu cầu thật.
    return re.findall(r"[a-z0-9]+", text.lower())


def _norm_tags(tags: list[str] | None) -> list[str]:
    return sorted({t.strip().lower() for t in tags or [] if t.strip()})


def _fts_match(text: str) -> str:
    """Query text → FTS5 MATCH string: quote từng token, OR semantics.
    User input không bao giờ chạm cú pháp FTS trực tiếp."""
    return " OR ".join(f'"{tok}"' for tok in tokenize(text))


def fts_search(
    conn: sqlite3.Connection,
    text: str,
    tags: list[str] | None = None,
    k: int = K_LEG,
) -> list[tuple[int, float]]:
    """Keyword leg — (section_rowid, score) best-first; score = -bm25 (dương)."""
    match = _fts_match(text)
    if not match:
        return []
    sql = (
        "SELECT fts.rowid, -bm25(fts) FROM fts "
        "JOIN sections s ON s.id = fts.rowid WHERE fts MATCH ?"
    )
    params: list[object] = [match]
    tag_list = _norm_tags(tags)
    if tag_list:
        placeholders = ",".join("?" * len(tag_list))
        sql += (
            " AND EXISTS (SELECT 1 FROM doc_tags t WHERE t.repo_id = s.repo_id"
            f" AND t.doc_id = s.doc_id AND t.tag IN ({placeholders}))"
        )
        params += tag_list
    sql += " ORDER BY bm25(fts) LIMIT ?"  # bm25 nhỏ hơn = khớp tốt hơn
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
        f"SELECT s.id FROM sections s WHERE s.id IN ({ph_rows}) AND EXISTS ("
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
    đã lọc SEMANTIC_MIN_SCORE. vec0 không pre-filter tag → over-fetch rồi lọc."""
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
    """Reciprocal Rank Fusion: score = Σ 1/(k + rank) trên các leg chứa rowid.
    Trả (rowid, score, mode) sort giảm dần theo score, tie-break rowid tăng dần."""
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
        "SELECT id, repo_id, doc_id, section_id, title, file, doc_revision "
        f"FROM sections WHERE id IN ({placeholders})",
        ids,
    )
    return {r[0]: SectionRow(*r) for r in rows}
