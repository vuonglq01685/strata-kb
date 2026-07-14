# Hybrid Search Index (SQLite FTS5 + vec0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay pipeline search per-query (YAML parse + BM25Plus rebuild + semantic fallback per-repo) bằng một index SQLite persistent duy nhất (`<hub.root>/.kb-work/search.db`) gồm FTS5 + vec0, sync incremental theo repo-fingerprint + content-hash, query hybrid trộn RRF.

**Architecture:** Module mới `center_kb/searchdb.py` sở hữu toàn bộ lifecycle index (schema, sync, fts/knn/rrf). `query.search` trở thành orchestrator mỏng: open-fresh (lazy check) → 2 leg → RRF → budget packing. Trigger eager tại `kb reindex` và `kb publish` direct mode. Phần index per-repo cũ trong `embed.py` bị xoá; `rank_bm25` gỡ khỏi dependencies.

**Tech Stack:** Python ≥3.11, sqlite3 stdlib (FTS5 built-in), sqlite-vec + fastembed (optional extra `[embed]`), pydantic models sẵn có, pytest.

**Spec:** `docs/superpowers/specs/2026-07-14-hybrid-search-index-design.md`

## Global Constraints

- DB duy nhất tại `<hub.root>/.kb-work/search.db` — derived cache cục bộ, **không bao giờ commit** (gitio.commit_paths đã scope theo path, không cần đổi).
- Zero-server: chỉ SQLite. Không Elasticsearch/Tantivy/daemon.
- Không đổi format `.kb/` hay federation layout. Không thay `get_section()`.
- Chữ ký `search(hub, text, tags=None, budget=2000, semantic=False, embedder=None)` giữ nguyên — cli/mcp/web không đổi call site. `QueryResult` giữ nguyên field.
- Hằng số: `K_LEG = 50`, `RRF_K = 60`, `SCHEMA_VERSION = "1"`, FTS5 `tokenize='unicode61'`, `body_head` = 500 ký tự đầu L2 (`_L2_HEAD_CHARS` từ embed.py). `SEMANTIC_MIN_SCORE` giữ nguyên từ embed.py.
- FTS5 dạng thường (lưu text), KHÔNG contentless (`content=''` bị loại — không hỗ trợ DELETE/UPDATE trực tiếp dưới SQLite < 3.43).
- Connection: WAL mode + `busy_timeout` 5000ms.
- Degradation: thiếu fastembed → FTS-only; index hỏng/lệch version → xoá + rebuild một lần, vẫn fail → raise. Windows: close mọi connection **trước khi** unlink, xoá kèm `-wal`/`-shm`, `PermissionError` → raise không retry-loop (spec windows-support §R5).
- `rank-bm25` gỡ khỏi `pyproject.toml` dependencies. sqlite-vec/fastembed vẫn là optional extra `[embed]` — core install phải chạy FTS-only được.
- Test hermetic: unit test **không bao giờ** load model fastembed thật (máy dev có thể có fastembed). Autouse fixture ép `default_embedder → None`, trừ test đánh dấu `@pytest.mark.real_embedder` hoặc chạy `--run-slow`.
- Chạy test bằng venv của repo: `.venv/bin/python -m pytest ...` (dưới đây viết tắt `pytest`).

## File Structure

| File | Vai trò |
|---|---|
| `src/center_kb/searchdb.py` (mới) | Toàn bộ index lifecycle: schema, open/rebuild, sync incremental, fts_search, knn_search, rrf_merge, load_sections, tokenize |
| `src/center_kb/query.py` | Orchestrator mỏng: search() hybrid + budget packing; get_section giữ nguyên. Xoá `_gather_candidates`, `_repo_candidates`, `_semantic_fallback`, `_Candidate`, `_filter_tags`, BM25Plus |
| `src/center_kb/embed.py` | Giữ `Embedder` (+ thêm `name`), `_FastEmbedder`, `default_embedder`, `_serialize`, constants. Xoá `_connect`, `ensure_index`, `semantic_search`, `_section_text`, `SEMANTIC_FALLBACK_THRESHOLD` |
| `src/center_kb/cli.py` | `reindex` gọi `searchdb.sync` eager; docstring/help text cập nhật |
| `src/center_kb/publish.py` | `_publish_direct` gọi `searchdb.sync` best-effort sau publish |
| `tests/test_searchdb.py` (mới) | Unit tests searchdb (Tasks 1–5) |
| `tests/conftest.py` | `FakeEmbedder` chuyển vào đây (+ axis "corridor"); autouse fixture `_no_real_embedder` |
| `tests/test_query.py`, `tests/test_query_semantic.py`, `tests/test_embed.py` | Cập nhật theo hành vi hybrid |
| `scripts/perf_search_smoke.py` (mới) | Perf smoke, không gate CI |

Public API của searchdb (contract cho mọi task):

```python
SCHEMA_VERSION = "1"
K_LEG = 50
RRF_K = 60
DB_NAME = "search.db"

@dataclass(frozen=True)
class SectionRow:
    rowid: int; repo_id: str; doc_id: str; section_id: str
    title: str; file: str; doc_revision: str

@dataclass
class SyncReport:
    repos_synced: int = 0; sections_updated: int = 0
    sections_deleted: int = 0; embedded: int = 0

def db_path(hub: HubHandle) -> Path
def open_db(hub: HubHandle) -> sqlite3.Connection        # tạo schema, rebuild 1 lần nếu hỏng/lệch version
def delete_db(hub: HubHandle) -> None                    # unlink db + -wal + -shm (caller đã close conn)
def sync(hub: HubHandle, embedder: Embedder | None) -> SyncReport
def open_fresh(hub: HubHandle, embedder: Embedder | None) -> sqlite3.Connection  # open + sync, trả conn
def tokenize(text: str) -> list[str]
def fts_search(conn, text: str, tags: list[str] | None = None, k: int = K_LEG) -> list[tuple[int, float]]
def knn_search(conn, embedder: Embedder, text: str, tags: list[str] | None = None, k: int = K_LEG) -> list[tuple[int, float]]
def rrf_merge(fts_hits: list[tuple[int, float]], knn_hits: list[tuple[int, float]], k: int = RRF_K) -> list[tuple[int, float, str]]  # (rowid, score, mode)
def load_sections(conn, rowids: Iterable[int]) -> dict[int, SectionRow]
```

---

### Task 1: searchdb skeleton — schema, open_db, rebuild khi hỏng/lệch version

**Files:**
- Create: `src/center_kb/searchdb.py`
- Create: `tests/test_searchdb.py`
- Modify: `src/center_kb/embed.py` (thêm `name` vào `Embedder` protocol + `_FastEmbedder`)

**Interfaces:**
- Consumes: `center_kb.embed.Embedder`, `center_kb.hub.HubHandle`
- Produces: `db_path(hub)`, `open_db(hub)`, `delete_db(hub)`, `SCHEMA_VERSION`, `DB_NAME`, `SectionRow`, `SyncReport`, `_has_vec_table(conn)`, `_vec_available()` — Tasks 2–5 xây tiếp trên file này

- [ ] **Step 1: Viết failing tests**

Tạo `tests/test_searchdb.py`:

```python
import sqlite3

import pytest

from center_kb import searchdb
from center_kb.hub import HubHandle


def _handle(tmp_path) -> HubHandle:
    (tmp_path / "federation").mkdir(exist_ok=True)
    (tmp_path / ".kb").mkdir(exist_ok=True)
    return HubHandle(root=tmp_path)


def test_open_db_creates_schema(tmp_path):
    hub = _handle(tmp_path)
    conn = searchdb.open_db(hub)
    try:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"meta", "repos", "sections", "doc_tags", "fts"} <= tables
        ver = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        assert ver == (searchdb.SCHEMA_VERSION,)
        # WAL + busy_timeout đã set (spec §3.2)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()
    assert searchdb.db_path(hub) == tmp_path / ".kb-work" / "search.db"


def test_open_db_rebuilds_on_schema_version_mismatch(tmp_path):
    hub = _handle(tmp_path)
    conn = searchdb.open_db(hub)
    conn.execute("UPDATE meta SET value='0' WHERE key='schema_version'")
    conn.execute("INSERT INTO repos VALUES('old-repo', 'fp')")
    conn.commit()
    conn.close()
    conn = searchdb.open_db(hub)  # version lệch → xoá + tạo lại
    try:
        assert conn.execute("SELECT COUNT(*) FROM repos").fetchone() == (0,)
        ver = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        assert ver == (searchdb.SCHEMA_VERSION,)
    finally:
        conn.close()


def test_open_db_rebuilds_on_corrupt_file(tmp_path):
    hub = _handle(tmp_path)
    path = searchdb.db_path(hub)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not a sqlite database at all")
    conn = searchdb.open_db(hub)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sections").fetchone() == (0,)
    finally:
        conn.close()


def test_delete_db_removes_wal_shm(tmp_path):
    hub = _handle(tmp_path)
    conn = searchdb.open_db(hub)
    conn.execute("INSERT INTO repos VALUES('r', 'fp')")
    conn.commit()
    conn.close()
    path = searchdb.db_path(hub)
    # tạo file -wal/-shm giả để chắc chắn bị dọn
    (path.parent / (path.name + "-wal")).touch()
    (path.parent / (path.name + "-shm")).touch()
    searchdb.delete_db(hub)
    assert not path.exists()
    assert not (path.parent / (path.name + "-wal")).exists()
    assert not (path.parent / (path.name + "-shm")).exists()
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `pytest tests/test_searchdb.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'center_kb.searchdb'` (hoặc ImportError).

- [ ] **Step 3: Implement**

Sửa `src/center_kb/embed.py` — thêm `name` vào protocol và `_FastEmbedder`:

```python
class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class _FastEmbedder:
    """fastembed ONNX — bge-small-en-v1.5, 384 dimensions, fully local."""

    dim = 384
    name = "BAAI/bge-small-en-v1.5"

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=self.name)
```

Tạo `src/center_kb/searchdb.py`:

```python
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
        conn, vec_loaded = _raw_connect(path)
        try:
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
        conn.close()  # Windows: close trước khi unlink
        if attempt == 2:
            raise RuntimeError(
                f"search.db unusable even after a rebuild: {reason}"
            ) from last_exc
        logger.warning("rebuilding search.db (%s)", reason)
        delete_db(hub)
    raise AssertionError("unreachable")
```

- [ ] **Step 4: Chạy test, xác nhận PASS**

Run: `pytest tests/test_searchdb.py tests/test_embed.py -v`
Expected: 4 test mới PASS; test_embed.py vẫn PASS (chỉ thêm attr `name`).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/searchdb.py src/center_kb/embed.py tests/test_searchdb.py
git commit -m "feat: searchdb skeleton - single search.db schema with rebuild-on-mismatch"
```

---

### Task 2: sync() incremental — fingerprint, sections, fts, doc_tags, dọn DB legacy

**Files:**
- Modify: `src/center_kb/searchdb.py` (thêm sync + helpers)
- Modify: `tests/test_searchdb.py` (thêm tests)

**Interfaces:**
- Consumes: Task 1 (`open_db`, `SyncReport`, `_has_vec_table`); `center_kb.federation.load_federation`; `center_kb.models.Manifest`; `slice_section`, `_L2_HEAD_CHARS`
- Produces: `sync(hub, embedder) -> SyncReport`, `open_fresh(hub, embedder) -> Connection`, `_delete_section(conn, rowid)`, `_embed_text(title, summary, body)`, `_section_parts(kb_dir, doc_id, sec)`, stub `_sync_vectors(conn, embedder, report)` (Task 3 sẽ implement). Bảng `sections`/`fts`/`doc_tags`/`repos` được populate — Tasks 4–5 query trên đó.
- Lưu ý contract: fingerprint = sha256(`_meta.yaml` bytes + `index.yaml` bytes). Mọi thay đổi nội dung thật đi qua publish nên `published_at` đổi → fingerprint đổi. Test mô phỏng thay đổi phải bump `_meta.yaml`.

- [ ] **Step 1: Viết failing tests**

Thêm vào `tests/test_searchdb.py`:

```python
from center_kb import models
from center_kb.federation import FederationMeta
from tests.conftest import make_fed_entry


def _bump_meta(entry, stamp="2026-07-14T09:00:00+00:00"):
    meta_path = entry / "_meta.yaml"
    meta = models.load_yaml_model(meta_path, FederationMeta)
    meta.published_at = stamp
    models.save_yaml_model(meta_path, meta)


def test_sync_builds_sections_fts_tags(fed_hub):
    hub = HubHandle(root=fed_hub)
    report = searchdb.sync(hub, None)
    assert report.repos_synced == 2
    assert report.sections_updated == 2  # mỗi repo fixture có 1 section
    conn = searchdb.open_db(hub)
    try:
        rows = conn.execute(
            "SELECT repo_id, doc_id, section_id, title, file FROM sections "
            "ORDER BY repo_id"
        ).fetchall()
        assert rows == [
            ("arinc-kb", "arinc-424", "5.3", "Restrictive Airspace", "ch1"),
            ("icao-kb", "icao-annex-2", "1.1", "Airspace Records", "ch1"),
        ]
        assert conn.execute("SELECT COUNT(*) FROM fts").fetchone() == (2,)
        tags = {
            t for (t,) in conn.execute(
                "SELECT tag FROM doc_tags WHERE repo_id='arinc-kb'"
            )
        }
        assert tags == {"arinc424", "arinc-424"}  # tag + doc_id (lowercase)
    finally:
        conn.close()


def test_sync_fingerprint_skip_reparses_nothing(fed_hub, monkeypatch):
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    manifest_loads = []
    real = models.load_yaml_model

    def spy(path, model):
        if model is models.Manifest:
            manifest_loads.append(path)
        return real(path, model)

    monkeypatch.setattr(models, "load_yaml_model", spy)
    report = searchdb.sync(hub, None)  # không repo nào đổi
    assert report.repos_synced == 0
    assert report.sections_updated == 0
    assert manifest_loads == []  # 0 manifest parse (spec §3.4)


def test_sync_updates_only_changed_section(fed_hub):
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    entry = fed_hub / "federation" / "arinc-kb"
    manifest_path = entry / "arinc-424" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = "Changed summary about corridors."
    models.save_yaml_model(manifest_path, manifest)
    _bump_meta(entry)  # publish thật luôn bump published_at
    report = searchdb.sync(hub, None)
    assert report.repos_synced == 1
    assert report.sections_updated == 1
    assert report.sections_deleted == 0


def test_sync_unchanged_content_rewrites_nothing(fed_hub):
    # fingerprint đổi (re-publish) nhưng content-hash từng section giữ nguyên
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    _bump_meta(fed_hub / "federation" / "arinc-kb")
    report = searchdb.sync(hub, None)
    assert report.repos_synced == 1
    assert report.sections_updated == 0


def test_sync_deletes_removed_section_and_repo(fed_hub):
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    # xoá hẳn repo icao-kb khỏi federation
    import shutil

    shutil.rmtree(fed_hub / "federation" / "icao-kb")
    report = searchdb.sync(hub, None)
    assert report.sections_deleted == 1
    conn = searchdb.open_db(hub)
    try:
        repos = {r for (r,) in conn.execute("SELECT repo_id FROM repos")}
        assert repos == {"arinc-kb"}
        assert conn.execute("SELECT COUNT(*) FROM fts").fetchone() == (1,)
        assert conn.execute(
            "SELECT COUNT(*) FROM doc_tags WHERE repo_id='icao-kb'"
        ).fetchone() == (0,)
    finally:
        conn.close()


def test_sync_removes_legacy_embedding_dbs(fed_hub):
    hub = HubHandle(root=fed_hub)
    legacy = fed_hub / ".kb-work" / "embeddings-arinc-kb.db"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"old cache")
    searchdb.sync(hub, None)
    assert not legacy.exists()  # spec §4: dọn cache cũ best-effort


def test_open_fresh_returns_synced_connection(fed_hub):
    conn = searchdb.open_fresh(HubHandle(root=fed_hub), None)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sections").fetchone() == (2,)
    finally:
        conn.close()


def test_sync_empty_federation(tmp_path):
    hub = _handle(tmp_path)
    report = searchdb.sync(hub, None)
    assert report.sections_updated == 0
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `pytest tests/test_searchdb.py -v`
Expected: các test mới FAIL với `AttributeError: module 'center_kb.searchdb' has no attribute 'sync'`.

- [ ] **Step 3: Implement — thêm vào `searchdb.py`**

```python
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
    """Task 3 implement — stub để sync() gọi được từ Task 2."""


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
    conn: sqlite3.Connection, hub: "HubHandle", embedder: Embedder | None
) -> SyncReport:
    from center_kb.federation import load_federation

    report = SyncReport()
    repos = load_federation(hub.federation_dir)
    live_ids = {r.meta.repo_id for r in repos}
    stored_fp = dict(conn.execute("SELECT repo_id, fingerprint FROM repos"))
    for rid in sorted(set(stored_fp) - live_ids):
        report.sections_deleted += _drop_repo(conn, rid)
        conn.execute("DELETE FROM repos WHERE repo_id = ?", (rid,))
    for repo in repos:
        fp = _repo_fingerprint(repo.kb_dir)
        if stored_fp.get(repo.meta.repo_id) == fp:
            continue  # repo không đổi — 0 manifest parse
        _sync_repo(conn, repo, report)
        conn.execute(
            "INSERT INTO repos(repo_id, fingerprint) VALUES(?, ?) "
            "ON CONFLICT(repo_id) DO UPDATE SET fingerprint = excluded.fingerprint",
            (repo.meta.repo_id, fp),
        )
        report.repos_synced += 1
    _sync_vectors(conn, embedder, report)
    conn.commit()
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
    """Open + lazy freshness check (sync incremental nếu lệch), trả connection."""
    conn = open_db(hub)
    try:
        _sync_conn(conn, hub, embedder)
    except BaseException:
        conn.close()
        raise
    return conn
```

- [ ] **Step 4: Chạy test, xác nhận PASS**

Run: `pytest tests/test_searchdb.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/searchdb.py tests/test_searchdb.py
git commit -m "feat: searchdb incremental sync by repo fingerprint + content hash"
```

---

### Task 3: vector sync — backfill, đổi model, validate dim

**Files:**
- Modify: `src/center_kb/searchdb.py` (implement `_sync_vectors`)
- Modify: `tests/conftest.py` (thêm `FakeEmbedder` dùng chung)
- Modify: `tests/test_searchdb.py` (thêm tests)

**Interfaces:**
- Consumes: Task 2 (`sync`, bảng `sections`+`fts` đã populate); `_serialize`, `Embedder` (có `name`, `dim`)
- Produces: bảng `vec_sections` (rowid = sections.id), meta keys `embed_model`/`embed_dim`; `tests.conftest.FakeEmbedder` (dim=4, name="fake-4d", axis: airspace|corridor / airway / roster) — Task 5, 6 dùng lại
- Semantics: row thiếu embedding (mới, đổi, hoặc sync trước không có embedder) được embed bù theo batch; đổi `name`/`dim` → DROP vec_sections + re-embed toàn bộ; embedder trả sai dim → `ValueError`

- [ ] **Step 1: Thêm `FakeEmbedder` vào `tests/conftest.py`**

```python
class FakeEmbedder:
    """Vector 4 chiều deterministic theo marker word — không cần model thật.

    'corridor' cùng axis với 'airspace' để test semantic-leg tìm được section
    airspace từ query không chứa keyword nào trùng FTS.
    """

    dim = 4
    name = "fake-4d"

    def embed(self, texts):
        out = []
        for t in texts:
            t = t.lower()
            out.append(
                [
                    1.0 if ("airspace" in t or "corridor" in t) else 0.0,
                    1.0 if "airway" in t else 0.0,
                    1.0 if "roster" in t else 0.0,
                    0.1,
                ]
            )
        return out
```

(Đặt ở module level của conftest.py, sau các import — KHÔNG phải fixture.)

- [ ] **Step 2: Viết failing tests — thêm vào `tests/test_searchdb.py`**

```python
sqlite_vec = pytest.importorskip("sqlite_vec")  # đặt đầu file, sau import pytest

from tests.conftest import FakeEmbedder


def _vec_count(hub):
    conn = searchdb.open_db(hub)
    try:
        return conn.execute("SELECT COUNT(*) FROM vec_sections").fetchone()[0]
    finally:
        conn.close()


def test_sync_embeds_all_sections(fed_hub):
    hub = HubHandle(root=fed_hub)
    report = searchdb.sync(hub, FakeEmbedder())
    assert report.embedded == 2
    assert _vec_count(hub) == 2
    conn = searchdb.open_db(hub)
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        assert meta["embed_model"] == "fake-4d"
        assert meta["embed_dim"] == "4"
    finally:
        conn.close()


def test_sync_without_embedder_then_backfill(fed_hub):
    hub = HubHandle(root=fed_hub)
    r1 = searchdb.sync(hub, None)  # FTS-only
    assert r1.embedded == 0
    r2 = searchdb.sync(hub, FakeEmbedder())  # embedder xuất hiện → embed bù
    assert r2.embedded == 2
    assert r2.sections_updated == 0  # không re-parse manifest


def test_sync_reembeds_only_changed_section(fed_hub):
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, FakeEmbedder())
    entry = fed_hub / "federation" / "arinc-kb"
    manifest_path = entry / "arinc-424" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = "Restrictive airspace corridors updated."
    models.save_yaml_model(manifest_path, manifest)
    _bump_meta(entry)
    report = searchdb.sync(hub, FakeEmbedder())
    assert report.embedded == 1
    assert _vec_count(hub) == 2  # row cũ xoá, row mới thêm


def test_sync_model_change_rebuilds_vec_table(fed_hub):
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, FakeEmbedder())

    class V2(FakeEmbedder):
        name = "fake-4d-v2"

    report = searchdb.sync(hub, V2())
    assert report.embedded == 2  # re-embed toàn bộ
    conn = searchdb.open_db(hub)
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        assert meta["embed_model"] == "fake-4d-v2"
    finally:
        conn.close()


class _BadDimEmbedder:
    """Khai dim=4 nhưng trả vector 3 chiều."""

    dim = 4
    name = "bad-dim"

    def embed(self, texts):
        return [[0.0, 0.0, 0.0] for _ in texts]


def test_sync_raises_on_wrong_vector_dim(fed_hub):
    with pytest.raises(ValueError):
        searchdb.sync(HubHandle(root=fed_hub), _BadDimEmbedder())
```

Lưu ý: `pytest.importorskip("sqlite_vec")` đưa lên đầu `tests/test_searchdb.py` (dev extra có sqlite-vec nên bình thường không skip).

- [ ] **Step 3: Chạy test, xác nhận FAIL**

Run: `pytest tests/test_searchdb.py -v`
Expected: các test vec FAIL (`no such table: vec_sections` / `report.embedded == 0`).

- [ ] **Step 4: Implement — thay stub `_sync_vectors` trong `searchdb.py`**

```python
def _sync_vectors(
    conn: sqlite3.Connection, embedder: Embedder | None, report: SyncReport
) -> None:
    if embedder is None or not _vec_available():
        return
    meta = dict(conn.execute("SELECT key, value FROM meta"))
    if _has_vec_table(conn) and (
        meta.get("embed_model") != embedder.name
        or meta.get("embed_dim") != str(embedder.dim)
    ):
        conn.execute("DROP TABLE vec_sections")  # đổi model/dim → rebuild bảng vec
    if not _has_vec_table(conn):
        conn.execute(
            f"CREATE VIRTUAL TABLE vec_sections USING vec0("
            f"embedding float[{embedder.dim}])"
        )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('embed_model', ?)",
        (embedder.name,),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('embed_dim', ?)",
        (str(embedder.dim),),
    )
    have = {r[0] for r in conn.execute("SELECT rowid FROM vec_sections")}
    missing = [
        row
        for row in conn.execute(
            "SELECT s.id, f.title, f.summary, f.body_head "
            "FROM sections s JOIN fts f ON f.rowid = s.id"
        )
        if row[0] not in have
    ]
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
```

- [ ] **Step 5: Chạy test, xác nhận PASS**

Run: `pytest tests/test_searchdb.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/searchdb.py tests/test_searchdb.py tests/conftest.py
git commit -m "feat: searchdb vector sync - batch embed, backfill, model-change rebuild"
```

---

### Task 4: tokenize + fts_search — escaping, tag filter, BM25 rank

**Files:**
- Modify: `src/center_kb/searchdb.py`
- Modify: `tests/test_searchdb.py`

**Interfaces:**
- Consumes: Task 2 (bảng `sections`/`fts`/`doc_tags` đã sync)
- Produces: `tokenize(text) -> list[str]`, `fts_search(conn, text, tags=None, k=K_LEG) -> list[tuple[int, float]]` — (section_rowid, score) sort best-first, score = `-bm25(fts)` (dương, lớn = tốt). Task 6 dùng.
- Query text KHÔNG bao giờ đưa thẳng vào MATCH — token hoá rồi quote từng token: `"tok1" OR "tok2"` (chặn inject cú pháp FTS: NEAR, column filter, `*`, `"`).
- Tag semantics giữ nguyên `_filter_tags` cũ: match khi tag của doc (lowercase) HOẶC chính doc_id nằm trong tagset — bảng `doc_tags` đã chứa doc_id như một tag.

- [ ] **Step 1: Viết failing tests — thêm vào `tests/test_searchdb.py`**

```python
def test_fts_search_ranks_and_filters(fed_hub):
    conn = searchdb.open_fresh(HubHandle(root=fed_hub), None)
    try:
        hits = searchdb.fts_search(conn, "restrictive airspace designation")
        assert hits  # (rowid, score) sort best-first
        rows = searchdb.load_sections(conn, [h[0] for h in hits])
        assert rows[hits[0][0]].repo_id == "arinc-kb"  # nhiều term trùng nhất
        assert all(h[1] > 0 for h in hits)
        # cả hai repo đều chứa 'airspace'
        hits_all = searchdb.fts_search(conn, "airspace")
        assert len(hits_all) == 2
    finally:
        conn.close()


def test_fts_search_tag_filter_in_sql(fed_hub):
    conn = searchdb.open_fresh(HubHandle(root=fed_hub), None)
    try:
        hits = searchdb.fts_search(conn, "airspace", tags=["arinc424"])
        rows = searchdb.load_sections(conn, [h[0] for h in hits])
        assert rows and all(r.repo_id == "arinc-kb" for r in rows.values())
        # doc_id cũng hoạt động như tag
        hits2 = searchdb.fts_search(conn, "airspace", tags=["icao-annex-2"])
        rows2 = searchdb.load_sections(conn, [h[0] for h in hits2])
        assert rows2 and all(r.repo_id == "icao-kb" for r in rows2.values())
    finally:
        conn.close()


def test_fts_search_escapes_fts_syntax(fed_hub):
    conn = searchdb.open_fresh(HubHandle(root=fed_hub), None)
    try:
        # không được nổ syntax error với input chứa cú pháp FTS5
        for q in ['NEAR(airspace records)', 'title:"x" OR *', 'a"b', "air-space"]:
            searchdb.fts_search(conn, q)  # chỉ cần không raise
        assert searchdb.fts_search(conn, "") == []
        assert searchdb.fts_search(conn, "!!! ???") == []
    finally:
        conn.close()


def test_tokenize_moved_to_searchdb():
    assert searchdb.tokenize("Restrictive-Airspace §5.3") == [
        "restrictive", "airspace", "5", "3",
    ]
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `pytest tests/test_searchdb.py -v`
Expected: FAIL — `has no attribute 'fts_search'` / `'tokenize'` / `'load_sections'`. (`load_sections` implement luôn ở task này vì test cần đọc row — xem Step 3.)

- [ ] **Step 3: Implement — thêm vào `searchdb.py`**

```python
def tokenize(text: str) -> list[str]:
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
```

- [ ] **Step 4: Chạy test, xác nhận PASS**

Run: `pytest tests/test_searchdb.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/searchdb.py tests/test_searchdb.py
git commit -m "feat: searchdb fts_search with token escaping + SQL tag filter"
```

---

### Task 5: knn_search + rrf_merge

**Files:**
- Modify: `src/center_kb/searchdb.py`
- Modify: `tests/test_searchdb.py`

**Interfaces:**
- Consumes: Task 3 (`vec_sections`, `FakeEmbedder`), Task 4 (`_norm_tags`, `load_sections`)
- Produces: `knn_search(conn, embedder, text, tags=None, k=K_LEG) -> list[tuple[int, float]]` (score = 1/(1+distance), đã lọc `SEMANTIC_MIN_SCORE`); `rrf_merge(fts_hits, knn_hits, k=RRF_K) -> list[tuple[int, float, str]]` với mode ∈ {"keyword","semantic","hybrid"}, sort (-score, rowid). Task 6 dùng cả hai.
- Tag filter KNN: vec0 không pre-filter được → over-fetch `k*4`, lọc bằng `doc_tags` sau, cắt còn k (spec §3.6).

- [ ] **Step 1: Viết failing tests — thêm vào `tests/test_searchdb.py`**

```python
def test_knn_search_ranks_and_min_score(fed_hub):
    hub = HubHandle(root=fed_hub)
    emb = FakeEmbedder()
    conn = searchdb.open_fresh(hub, emb)
    try:
        # 'corridor' → axis airspace: cả 2 section airspace đều match
        hits = searchdb.knn_search(conn, emb, "corridor clearance")
        assert len(hits) == 2
        assert all(score >= 0.6 for _, score in hits)  # SEMANTIC_MIN_SCORE
        # garbage: mọi score dưới ngưỡng → rỗng, không pad nearest-but-irrelevant
        assert searchdb.knn_search(conn, emb, "zzz qqq xxx") == []
    finally:
        conn.close()


def test_knn_search_tag_filter_post_knn(fed_hub):
    hub = HubHandle(root=fed_hub)
    emb = FakeEmbedder()
    conn = searchdb.open_fresh(hub, emb)
    try:
        hits = searchdb.knn_search(conn, emb, "corridor", tags=["arinc424"])
        rows = searchdb.load_sections(conn, [h[0] for h in hits])
        assert rows and all(r.repo_id == "arinc-kb" for r in rows.values())
    finally:
        conn.close()


def test_knn_search_without_vec_table_returns_empty(fed_hub):
    conn = searchdb.open_fresh(HubHandle(root=fed_hub), None)  # chưa từng embed
    try:
        assert searchdb.knn_search(conn, FakeEmbedder(), "corridor") == []
    finally:
        conn.close()


def test_rrf_merge_modes_and_order():
    fts = [(1, 9.0), (2, 5.0)]
    knn = [(2, 0.9), (3, 0.8)]
    fused = searchdb.rrf_merge(fts, knn)
    by_id = {rowid: (score, mode) for rowid, score, mode in fused}
    assert by_id[2][1] == "hybrid"
    assert by_id[1][1] == "keyword"
    assert by_id[3][1] == "semantic"
    # rowid 2 xuất hiện ở cả 2 leg → score cao nhất
    assert fused[0][0] == 2
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)
    # tie (1 và 3 cùng 1/61? không — 1 rank1 fts = 1/61, 3 rank2 knn = 1/62)
    assert by_id[1][0] == pytest.approx(1 / 61)
    assert by_id[3][0] == pytest.approx(1 / 62)


def test_rrf_merge_single_leg_and_tie_determinism():
    assert searchdb.rrf_merge([], []) == []
    only_fts = searchdb.rrf_merge([(7, 3.0)], [])
    assert only_fts == [(7, pytest.approx(1 / 61), "keyword")]
    # tie score → sort theo rowid tăng dần, deterministic
    tie = searchdb.rrf_merge([(5, 1.0)], [(4, 1.0)])
    assert [t[0] for t in tie] == [4, 5]
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `pytest tests/test_searchdb.py -v`
Expected: FAIL — `has no attribute 'knn_search'` / `'rrf_merge'`.

- [ ] **Step 3: Implement — thêm vào `searchdb.py`**

```python
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
```

- [ ] **Step 4: Chạy test, xác nhận PASS**

Run: `pytest tests/test_searchdb.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/searchdb.py tests/test_searchdb.py
git commit -m "feat: searchdb knn leg + RRF merge"
```

---

### Task 6: query.search chuyển sang hybrid — xoá đường cũ, cập nhật tests

**Files:**
- Modify: `src/center_kb/query.py` (viết lại search; xoá `_gather_candidates`, `_repo_candidates`, `_semantic_fallback`, `_Candidate`, `_filter_tags`, `_candidate_content`, BM25Plus; `tokenize` re-export từ searchdb)
- Modify: `tests/conftest.py` (autouse fixture `_no_real_embedder`)
- Modify: `pyproject.toml` (đăng ký marker `real_embedder`)
- Modify: `tests/test_query.py` (giữ nguyên assertions, chỉ pass là được)
- Rewrite: `tests/test_query_semantic.py` (hybrid semantics)
- Modify: `tests/test_embed.py` (xoá tests của ensure_index/semantic_search + FakeEmbedder local; giữ default_embedder tests; slow test chuyển sang test_searchdb.py)
- Modify: `src/center_kb/web/ui.py` (CSS cho badge `match-hybrid` — xem Step 6)

**Interfaces:**
- Consumes: toàn bộ searchdb API (open_fresh, fts_search, knn_search, rrf_merge, load_sections, delete_db, tokenize); `embed.default_embedder`
- Produces: `search()` chữ ký y nguyên, `QueryResult` y nguyên field; `match_mode` giờ nhận "keyword"/"semantic"/"hybrid"; `score` = RRF score; `query.tokenize` vẫn import được (web/ui.py:15 đang import). `_citation` đổi thành `_citation(repo_id: str, doc_id: str, revision: str, section_id: str) -> str` — chỉ dùng nội bộ query.py.
- Hành vi giữ: budget packing y hệt cũ (luôn trả ≥1 khi có match; dừng khi vượt budget); federation trống → `[]`; KNN leg lỗi runtime → warning + FTS-only; sqlite DatabaseError giữa query → xoá DB, rebuild đúng 1 lần, vẫn fail → raise.

- [ ] **Step 1: Autouse hermetic fixture — thêm vào `tests/conftest.py`**

```python
@pytest.fixture(autouse=True)
def _no_real_embedder(request, monkeypatch):
    """search() giờ resolve default_embedder() eager mỗi query — unit test phải
    hermetic: máy dev có fastembed cũng không được load/download model thật.
    Bỏ qua khi test đánh dấu real_embedder hoặc chạy --run-slow."""
    if request.node.get_closest_marker("real_embedder") or request.config.getoption(
        "--run-slow"
    ):
        yield
        return
    from center_kb import embed

    monkeypatch.setattr(embed, "default_embedder", lambda: None)
    yield
```

Đăng ký marker trong `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "real_embedder: test dùng default_embedder thật (fastembed) — bị autouse fixture bỏ qua",
]
```

- [ ] **Step 2: Rewrite `tests/test_query_semantic.py` (failing trước khi sửa query.py)**

```python
import pytest

from center_kb.hub import HubHandle
from center_kb.query import search
from tests.conftest import FakeEmbedder

pytest.importorskip("sqlite_vec")


def test_hybrid_both_legs_match_mode_hybrid(fed_hub):
    # 'airspace' trúng cả FTS (title/summary) lẫn KNN (axis 0) → hybrid
    results = search(
        HubHandle(root=fed_hub), "restrictive airspace", embedder=FakeEmbedder()
    )
    assert results
    assert results[0].match_mode == "hybrid"
    assert (fed_hub / ".kb-work" / "search.db").exists()


def test_semantic_only_when_no_keyword_overlap(fed_hub):
    # 'corridor' không có trong corpus (FTS miss) nhưng FakeEmbedder map cùng
    # axis với 'airspace' → chỉ KNN leg trả → match_mode semantic
    results = search(
        HubHandle(root=fed_hub), "corridor clearance", embedder=FakeEmbedder()
    )
    assert results
    assert all(r.match_mode == "semantic" for r in results)


def test_keyword_only_without_embedder(fed_hub):
    results = search(HubHandle(root=fed_hub), "airspace designation type")
    assert results  # autouse fixture ép default_embedder → None
    assert all(r.match_mode == "keyword" for r in results)


def test_no_embedder_no_crash_on_miss(fed_hub):
    assert search(HubHandle(root=fed_hub), "zzz qqq xxx", embedder=None) == []


def test_garbage_query_semantic_returns_empty_not_nearest(fed_hub):
    # mọi KNN score dưới SEMANTIC_MIN_SCORE → không pad kết quả gần-mà-vô-nghĩa
    results = search(
        HubHandle(root=fed_hub), "zzz qqq xxx", semantic=True, embedder=FakeEmbedder()
    )
    assert results == []


def test_semantic_flag_without_embedder_warns(fed_hub, caplog):
    with caplog.at_level("WARNING", logger="center_kb.query"):
        results = search(HubHandle(root=fed_hub), "airspace", semantic=True)
    assert results  # vẫn trả FTS leg
    assert any("semantic" in r.message.lower() for r in caplog.records)


def test_knn_leg_error_falls_back_to_keyword(fed_hub, caplog):
    class ExplodingEmbedder(FakeEmbedder):
        calls = 0

        def embed(self, texts):
            # lần 1 (sync) chạy được, lần 2 (query vector) nổ
            type(self).calls += 1
            if type(self).calls > 1:
                raise RuntimeError("boom")
            return super().embed(texts)

    with caplog.at_level("WARNING", logger="center_kb.query"):
        results = search(
            HubHandle(root=fed_hub), "restrictive airspace",
            embedder=ExplodingEmbedder(),
        )
    assert results  # keyword leg vẫn trả
    assert all(r.match_mode == "keyword" for r in results)


def test_corrupt_db_rebuilt_once_transparently(fed_hub):
    from center_kb import searchdb

    hub = HubHandle(root=fed_hub)
    search(hub, "airspace")  # build index
    searchdb.db_path(hub).write_bytes(b"corrupted")
    results = search(hub, "restrictive airspace designation")  # rebuild + trả kết quả
    assert results
```

- [ ] **Step 3: Chạy test, xác nhận FAIL**

Run: `pytest tests/test_query_semantic.py -v`
Expected: FAIL (code cũ vẫn BM25 fallback — `match_mode` không bao giờ là "hybrid"; import FakeEmbedder từ conftest OK).

- [ ] **Step 4: Viết lại `src/center_kb/query.py`**

File đầy đủ sau khi sửa (get_section/AmbiguousDocError giữ nguyên):

```python
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from center_kb import models
from center_kb.mdutils import count_tokens, slice_section
from center_kb.searchdb import tokenize  # noqa: F401 — re-export (web/ui.py import)

if TYPE_CHECKING:
    from center_kb.hub import HubHandle
    from center_kb.searchdb import SectionRow

logger = logging.getLogger("center_kb.query")


class AmbiguousDocError(LookupError):
    """doc_id exists in several federation repos — must be qualified as repo:doc."""

    def __init__(self, doc_id: str, repo_ids: list[str]) -> None:
        self.doc_id = doc_id
        self.repo_ids = repo_ids
        options = ", ".join(f"{rid}:{doc_id}" for rid in repo_ids)
        super().__init__(
            f"doc '{doc_id}' exists in {len(repo_ids)} federation repos — "
            f"qualify the ref: {options}"
        )


@dataclass
class QueryResult:
    doc_id: str
    section_id: str
    title: str
    score: float
    citation: str
    content: str
    tokens: int
    source: str = ""  # repo-id trong federation
    match_mode: str = "keyword"  # "keyword" | "semantic" | "hybrid"


def _citation(repo_id: str, doc_id: str, revision: str, section_id: str) -> str:
    base = f"{repo_id}:{doc_id} §{section_id}"
    return f"{base} ({revision})" if revision else base


def _row_content(hub: "HubHandle", row: "SectionRow") -> str | None:
    l2_path = hub.federation_dir / row.repo_id / row.doc_id / f"{row.file}.md"
    if not l2_path.exists():
        return None
    return slice_section(l2_path.read_text(encoding="utf-8"), row.section_id)


def _search_index(
    hub: "HubHandle", embedder, text: str, tags: list[str] | None
) -> tuple[list[tuple[int, float, str]], dict[int, "SectionRow"]]:
    """Chạy 2 leg + RRF trên index. DB hỏng giữa chừng → xoá, rebuild đúng
    một lần; vẫn fail → raise (spec §5)."""
    from center_kb import searchdb

    for attempt in (1, 2):
        conn = searchdb.open_fresh(hub, embedder)
        try:
            fts_hits = searchdb.fts_search(conn, text, tags)
            knn_hits: list[tuple[int, float]] = []
            if embedder is not None:
                try:
                    knn_hits = searchdb.knn_search(conn, embedder, text, tags)
                except sqlite3.DatabaseError:
                    raise  # index hỏng — để nhánh rebuild xử lý
                except Exception as exc:  # embedding best-effort, không vỡ query
                    logger.warning("semantic leg failed — keyword only: %s", exc)
            fused = searchdb.rrf_merge(fts_hits, knn_hits)
            return fused, searchdb.load_sections(conn, [r for r, _, _ in fused])
        except sqlite3.DatabaseError as exc:
            conn.close()  # Windows: close trước khi unlink
            if attempt == 2:
                raise
            logger.warning("search.db corrupt — rebuilding once: %s", exc)
            searchdb.delete_db(hub)
        finally:
            conn.close()
    raise AssertionError("unreachable")


def search(
    hub: "HubHandle",
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    semantic: bool = False,
    embedder=None,  # center_kb.embed.Embedder | None — injectable cho test
) -> list[QueryResult]:
    from center_kb import embed as embed_mod

    if embedder is None:
        embedder = embed_mod.default_embedder()
    if semantic and embedder is None:
        logger.warning(
            "semantic search requested but no embedder is available — "
            'keyword results only (enable with: pip install "center-kb[embed]")'
        )
    fused, rows = _search_index(hub, embedder, text, tags)

    results: list[QueryResult] = []
    used = 0
    for rowid, score, mode in fused:
        row = rows.get(rowid)
        if row is None:
            continue
        content = _row_content(hub, row)
        if content is None:
            continue
        n_tokens = count_tokens(content)
        if results and used + n_tokens > budget:
            break
        results.append(
            QueryResult(
                doc_id=row.doc_id,
                section_id=row.section_id,
                title=row.title,
                score=score,
                citation=_citation(
                    row.repo_id, row.doc_id, row.doc_revision, row.section_id
                ),
                content=content,
                tokens=n_tokens,
                source=row.repo_id,
                match_mode=mode,
            )
        )
        used += n_tokens
        if used >= budget:
            break
    return results


def _get_section_in(
    repo_kb: Path, repo_id: str, doc_id: str, section_id: str, level: str
) -> QueryResult | None:
    manifest_path = repo_kb / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    sec = next((s for s in manifest.sections if s.id == section_id), None)
    if sec is None:
        return None
    suffix = ".raw.md" if level == "l3" else ".md"
    path = repo_kb / doc_id / f"{sec.file}{suffix}"
    if not path.exists():
        return None
    content = slice_section(path.read_text(encoding="utf-8"), section_id)
    if content is None:
        return None
    return QueryResult(
        doc_id=doc_id,
        section_id=section_id,
        title=sec.title,
        score=0.0,
        citation=_citation(repo_id, manifest.id, manifest.revision, section_id),
        content=content,
        tokens=count_tokens(content),
        source=repo_id,
    )


def get_section(
    hub: "HubHandle",
    doc_id: str,
    section_id: str,
    level: str = "l2",
    repo: str | None = None,
) -> QueryResult | None:
    from center_kb.federation import load_federation

    section_id = section_id.lstrip("§")
    if ":" in doc_id and repo is None:
        repo, doc_id = doc_id.split(":", 1)
    holders = [
        r for r in load_federation(hub.federation_dir)
        if (repo is None or r.meta.repo_id == repo)
        and (r.kb_dir / doc_id / "_manifest.yaml").exists()
    ]
    if not holders:
        return None
    if len(holders) > 1:
        raise AmbiguousDocError(doc_id, [r.meta.repo_id for r in holders])
    r = holders[0]
    return _get_section_in(r.kb_dir, r.meta.repo_id, doc_id, section_id, level)
```

Lưu ý cho implementer:
- Import `rank_bm25`, `SEMANTIC_FALLBACK_THRESHOLD`, `re` đều biến mất khỏi query.py. `tokenize` local bị xoá — thay bằng re-export từ searchdb (giữ import path `center_kb.query.tokenize` cho web/ui.py:15 và tests).
- Trong `_search_index`, `conn.close()` gọi 2 lần trên nhánh lỗi (except rồi finally) — sqlite3 cho phép double-close, chấp nhận để giữ luật "close trước unlink" trên Windows.

- [ ] **Step 5: Cập nhật tests còn lại**

`tests/test_embed.py` — xoá: `FakeEmbedder` (class local), `_BadDimEmbedder`, `test_ensure_index_builds_then_incremental`, `test_ensure_index_reembeds_changed_section`, `test_semantic_search_ranks_by_similarity`, `test_semantic_search_filters_below_min_score`, `test_ensure_index_raises_on_wrong_vector_dim`, `test_ensure_index_removes_deleted_section`, `test_real_fastembed_roundtrip`. Giữ lại và đánh dấu:

```python
import pytest

sqlite_vec = pytest.importorskip("sqlite_vec")

from center_kb import embed


@pytest.mark.real_embedder
def test_default_embedder_none_when_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("fastembed"):
            raise ImportError("no fastembed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert embed.default_embedder() is None
```

(marker `real_embedder` để autouse fixture không thay `default_embedder` bằng lambda — test này tự fake ImportError nên vẫn hermetic.)

Slow test model thật chuyển sang cuối `tests/test_searchdb.py`:

```python
@pytest.mark.real_embedder
@pytest.mark.skipif(
    "not config.getoption('--run-slow', default=False)",
    reason="requires --run-slow (downloads a ~100MB model)",
)
def test_real_fastembed_roundtrip(fed_hub):
    from center_kb.embed import default_embedder
    from center_kb.query import search

    embedder = default_embedder()
    if embedder is None:
        pytest.skip("fastembed not installed")
    results = search(
        HubHandle(root=fed_hub), "controlled airspace zones", embedder=embedder
    )
    assert results and results[0].source in {"arinc-kb", "icao-kb"}
```

`tests/test_query.py` — không sửa assertion nào; chạy để xác nhận hành vi giữ nguyên.

- [ ] **Step 6: Badge `hybrid` trên web UI**

`web/ui.py` `_match_badge` đã render class `match-hybrid` tự động. Tìm CSS hiện có: `grep -n "match-semantic" src/center_kb/web/ui.py src/center_kb/templates/web/*.css 2>/dev/null`. Thêm rule `.match-hybrid` cạnh `.match-semantic` với màu riêng (copy block `.match-semantic`, đổi tên class + đổi màu nền — ví dụ nếu semantic là tím thì hybrid dùng teal). Nếu không tìm thấy style riêng cho `.match-semantic` (badge đang ăn style chung `.match-badge`) thì không cần sửa gì — badge hybrid render bằng style chung, spec coi phần này là cosmetic.

- [ ] **Step 7: Chạy toàn bộ test, xác nhận PASS**

Run: `pytest tests/ -v`
Expected: PASS toàn bộ (test_query.py nguyên trạng phải xanh; test_mcp.py, test_web_ui.py, test_cli*.py không đổi phải xanh — nhờ autouse fixture, search qua CLI/MCP/web trong test luôn FTS-only).

Ghi chú hành vi được chấp nhận (không phải bug): MCP `AMBIGUOUS_SCORE_GAP` giờ so trên RRF score — RRF cluster hẹp nên note "score closely" xuất hiện thường hơn; tuning ngoài scope (spec Non-goals).

- [ ] **Step 8: Commit**

```bash
git add src/center_kb/query.py src/center_kb/web/ui.py tests/ pyproject.toml
git commit -m "feat: query.search hybrid FTS5+KNN with RRF, replace per-query BM25 pipeline"
```

---

### Task 7: trigger eager (reindex/publish), dọn embed.py, gỡ rank-bm25

**Files:**
- Modify: `src/center_kb/cli.py` (lệnh `reindex`)
- Modify: `src/center_kb/publish.py` (`_publish_direct` + logger)
- Modify: `src/center_kb/embed.py` (xoá phần index cũ)
- Modify: `pyproject.toml`, `uv.lock` (gỡ rank-bm25)
- Modify: `tests/test_cli_hub.py`, `tests/test_publish.py` (tests trigger)

**Interfaces:**
- Consumes: `searchdb.sync`, `embed.default_embedder`
- Produces: `kb reindex` build index eager; `kb publish` direct mode sync best-effort; PR mode KHÔNG sync. `embed.py` chỉ còn: `Embedder`, `_FastEmbedder`, `default_embedder`, `_serialize`, `SEMANTIC_MIN_SCORE`, `_L2_HEAD_CHARS`.

- [ ] **Step 1: Viết failing tests**

Thêm vào `tests/test_cli_hub.py`:

```python
def test_reindex_builds_search_db(fed_hub, git_kb):
    result = runner.invoke(
        app, ["reindex", "--hub", str(fed_hub), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0
    assert (fed_hub / ".kb-work" / "search.db").exists()
    assert "search index" in result.output
```

Thêm vào `tests/test_publish.py` (dùng đúng fixture/import style sẵn có của file — publish module đã được import ở đó):

```python
def test_publish_direct_refreshes_search_db(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb", mode="direct")
    assert (hub_worktree / ".kb-work" / "search.db").exists()
```

PR mode (spec §3.5: KHÔNG sync): đọc `tests/test_publish.py`, tìm test PR-mode hiện có (test gọi `publish(..., mode="pr")` với gh stub/fake). Thêm đúng một assertion vào cuối test đó:

```python
    assert not (hub_worktree / ".kb-work" / "search.db").exists()
```

(đổi tên biến hub cho khớp fixture của test đó). Nếu file không có test PR-mode nào chạy được offline thì bỏ qua assertion này — hành vi đã được bảo đảm bằng việc `_publish_pr` không gọi sync.

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `pytest tests/test_cli_hub.py tests/test_publish.py -v`
Expected: 2 test mới FAIL (`search.db` chưa tồn tại).

- [ ] **Step 3: Implement triggers**

`src/center_kb/cli.py` — trong lệnh `reindex` (cli.py:640), chèn sync ngay sau `write_federation_index`, TRƯỚC nhánh early-return "nothing to do":

```python
    from center_kb import gitio, searchdb
    from center_kb.embed import default_embedder
    from center_kb.federation import write_federation_index

    handle = _hub_or_exit(hub, kb_dir)
    write_federation_index(handle.federation_dir)
    sreport = searchdb.sync(handle, default_embedder())
    typer.echo(
        f"kb reindex: search index — {sreport.sections_updated} updated, "
        f"{sreport.sections_deleted} removed, {sreport.embedded} embedded"
    )
    committed = gitio.commit_paths(
        handle.root, "reindex: rebuild federation/index.yaml", ["federation"]
    )
    # ... phần còn lại giữ nguyên
```

`src/center_kb/publish.py` — thêm đầu file:

```python
import logging

logger = logging.getLogger("center_kb.publish")
```

Cuối `_publish_direct`, ngay trước `return PublishReport(...)`:

```python
    from center_kb import searchdb
    from center_kb.embed import default_embedder

    try:
        searchdb.sync(handle, default_embedder())
    except Exception as exc:  # eager refresh best-effort — query sau rebuild lazy
        logger.warning("search index refresh failed: %s", exc)
```

`_publish_pr` KHÔNG đụng.

- [ ] **Step 4: Dọn `embed.py`**

Xoá khỏi `src/center_kb/embed.py`: `SEMANTIC_FALLBACK_THRESHOLD`, `_connect`, `_section_text`, `ensure_index`, `semantic_search`, import `sqlite3` + `models` + `slice_section` (không còn dùng). Giữ: `Embedder`, `_FastEmbedder`, `default_embedder`, `_serialize`, `SEMANTIC_MIN_SCORE`, `_L2_HEAD_CHARS`, import `struct`/`logging`/`Protocol`/`hashlib` (bỏ `hashlib` nếu không còn chỗ dùng). Sửa 2 log message trong `default_embedder`:

```python
        logger.info(
            "fastembed not installed — semantic search disabled, keyword search only "
            '(enable with: pip install "center-kb[embed]")'
        )
        ...
        logger.warning(
            "could not initialize embedder — keyword search only: %s", exc
        )
```

Verify không còn ai import phần đã xoá:

```bash
grep -rn "SEMANTIC_FALLBACK_THRESHOLD\|ensure_index\|semantic_search\|_section_text" src tests --include="*.py"
```

Expected: 0 kết quả (ngoài searchdb nếu đặt tên trùng — không có).

- [ ] **Step 5: Gỡ dependency**

`pyproject.toml`: xoá dòng `"rank-bm25>=0.2.2",` khỏi `dependencies`. Rồi:

```bash
uv lock
grep -rn "rank.bm25\|rank_bm25" src tests pyproject.toml requirements-gate.txt
```

Expected: grep 0 kết quả.

- [ ] **Step 6: Chạy toàn bộ test, xác nhận PASS**

Run: `pytest tests/ -v`
Expected: PASS toàn bộ.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/cli.py src/center_kb/publish.py src/center_kb/embed.py pyproject.toml uv.lock tests/
git commit -m "feat: eager index sync on reindex/publish-direct; drop rank-bm25 and legacy embed index"
```

---

### Task 8: cập nhật docs/templates — mô tả hybrid thay BM25

**Files:**
- Modify: `README.md` (dòng ~322, ~377, ~414, ~460)
- Modify: `src/center_kb/templates/init/QUICKSTART-hub.md` (~dòng 40)
- Modify: `src/center_kb/templates/init/QUICKSTART-child.md` (~dòng 48)
- Modify: `src/center_kb/templates/init/copilot-kb-summarize.instructions.md` (~dòng 56)
- Modify: `src/center_kb/templates/init/claude-skill-kb-summarize.md` (~dòng 95)
- Modify: `src/center_kb/cli.py` (docstring `query`, help `--semantic`)
- Modify: `src/center_kb/mcp.py` (docstring `kb_search`)
- Modify: `tests/test_templates.py` / `tests/test_init.py` nếu có assertion trên text template (grep trước)

**Interfaces:** không có — chỉ copy/text. Nội dung thay thế cụ thể:

- [ ] **Step 1: Sửa từng chỗ**

| Vị trí | Cũ | Mới |
|---|---|---|
| README.md ~322 | "...and BM25 search would stop matching." | "...and keyword search would stop matching." |
| README.md ~377 | "then rank related sections with classic text search (BM25) over L1 one-liners, then load L2 content..." | "then rank related sections with a persistent hybrid index (SQLite FTS5 keyword search + optional semantic KNN, fused with RRF), then load L2 content..." |
| README.md ~414 | "Find sections by natural language (tag match + BM25)" | "Find sections by natural language (tag match + hybrid FTS5/semantic search)" |
| README.md ~460 | mô tả `--semantic` "force lookup by question meaning instead of keyword match alone (BM25)" | "hybrid search already combines keyword and meaning when the embed extra is installed; `--semantic` now only warns clearly when embeddings are unavailable. Optional extra (`pip install -e \".[embed]\"`) — without it, `kb query` still works with keyword match, no error." |
| QUICKSTART-hub.md:40, QUICKSTART-child.md:48, copilot-kb-summarize.instructions.md:56 | "`kb query \"<question>\"` — BM25 search over the summaries" | "`kb query \"<question>\"` — hybrid search (keyword + semantic) over the summaries" |
| claude-skill-kb-summarize.md:95 | "(so BM25 matches technical" | "(so keyword search matches technical" |
| cli.py `query` docstring | "Tag match → BM25 → return L2 sections within budget, with citations." | "Hybrid search (FTS5 keyword + semantic KNN, RRF-fused) → L2 sections within budget, with citations." |
| cli.py `--semantic` help | "Force embedding search (routing step 3)" | "Warn when embeddings are unavailable (hybrid runs both legs automatically)" |
| mcp.py `kb_search` docstring, câu đầu | "Find sections by tag match + BM25 (falls back to semantic search);" | "Find sections by hybrid search (FTS5 keyword + semantic KNN, RRF-fused);" — phần còn lại của docstring giữ nguyên |

- [ ] **Step 2: Verify không sót**

```bash
grep -rn "BM25\|bm25" README.md src/center_kb --include="*.md" --include="*.py" | grep -v "bm25(fts)" | grep -v searchdb
```

Expected: 0 kết quả (riêng `searchdb.py` được phép chứa `bm25(fts)` — hàm SQL của FTS5).

- [ ] **Step 3: Chạy test (templates/init có test text)**

Run: `pytest tests/test_templates.py tests/test_init.py tests/test_mcp.py -v`
Expected: PASS (nếu test assert text cũ chứa "BM25" thì sửa assertion theo text mới).

- [ ] **Step 4: Commit**

```bash
git add README.md src/center_kb tests
git commit -m "docs: describe hybrid search index, retire BM25 wording"
```

---

### Task 9: perf smoke script (không gate CI)

**Files:**
- Create: `scripts/perf_search_smoke.py`

**Interfaces:**
- Consumes: `searchdb.sync/open_fresh/fts_search/knn_search`, `query.search`, `models`, `FederationMeta`, `HubHandle`
- Produces: script CLI in số đo ms — mục tiêu spec §2: keyword leg < 100ms, hybrid < 300ms (warm, không tính refresh). Chỉ chạy tay.

- [ ] **Step 1: Viết script**

```python
#!/usr/bin/env python3
"""Perf smoke cho hybrid search index — chạy tay, KHÔNG phải CI gate.

    python scripts/perf_search_smoke.py --sections 5000
    python scripts/perf_search_smoke.py --sections 100000 --repos 20

Mục tiêu (spec §2): keyword leg < 100ms, hybrid query < 300ms (warm).
"""
from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from center_kb import models, searchdb
from center_kb.federation import FederationMeta
from center_kb.hub import HubHandle
from center_kb.query import search


class HashEmbedder:
    """Embedder rẻ deterministic — token hash vào 64 dim, normalize."""

    dim = 64
    name = "hash-64"

    def embed(self, texts):
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            for tok in t.lower().split():
                vec[hash(tok) % self.dim] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out


WORDS = [
    "airspace", "airway", "waypoint", "procedure", "runway", "approach",
    "departure", "navaid", "frequency", "altitude", "restriction", "sector",
]


def build_hub(root: Path, n_sections: int, n_repos: int) -> None:
    fed = root / "federation"
    per_repo = max(1, n_sections // n_repos)
    for r in range(n_repos):
        rid = f"repo-{r:03d}"
        doc_id = f"doc-{r:03d}"
        doc_dir = fed / rid / doc_id
        doc_dir.mkdir(parents=True)
        sections, lines = [], []
        for s in range(per_repo):
            sid = f"{s // 100 + 1}.{s % 100 + 1}"
            w = [WORDS[(s + i + r) % len(WORDS)] for i in range(4)]
            title = f"{w[0].title()} {w[1].title()} Records {sid}"
            lines.append(
                f"## {sid} {title}\n\nCondensed {' '.join(w)} content row {s}.\n"
            )
            sections.append(
                models.SectionEntry(
                    id=sid, title=title,
                    summary=f"{' '.join(w)} structure fields.",
                    status="summarized", file="body",
                )
            )
        (doc_dir / "body.md").write_text("\n".join(lines), encoding="utf-8")
        models.save_yaml_model(
            doc_dir / "_manifest.yaml",
            models.Manifest(id=doc_id, title=doc_id, sections=sections),
        )
        models.save_yaml_model(
            fed / rid / "index.yaml",
            models.KBIndex(
                docs=[
                    models.IndexEntry(id=doc_id, title=doc_id, tags=[f"tag{r % 5}"])
                ]
            ),
        )
        models.save_yaml_model(
            fed / rid / "_meta.yaml",
            FederationMeta(
                repo_id=rid, source_commit="perf",
                published_at="2026-07-14T00:00:00+00:00",
            ),
        )
    (root / ".kb").mkdir()


def timed_ms(fn, n: int = 5) -> float:
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sections", type=int, default=5000)
    ap.add_argument("--repos", type=int, default=10)
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="kb-perf-"))
    try:
        print(f"building synthetic hub: {args.sections} sections / {args.repos} repos")
        build_hub(tmp, args.sections, args.repos)
        hub = HubHandle(root=tmp)
        emb = HashEmbedder()
        t0 = time.perf_counter()
        report = searchdb.sync(hub, emb)
        print(
            f"sync cold:            {time.perf_counter() - t0:8.1f} s  "
            f"({report.sections_updated} sections, {report.embedded} embedded)"
        )
        print(f"sync warm (no-op):    {timed_ms(lambda: searchdb.sync(hub, emb)):8.1f} ms")
        conn = searchdb.open_fresh(hub, emb)
        q = "airspace restriction sector"
        print(f"fts leg warm:         {timed_ms(lambda: searchdb.fts_search(conn, q)):8.1f} ms")
        print(f"knn leg warm:         {timed_ms(lambda: searchdb.knn_search(conn, emb, q)):8.1f} ms")
        conn.close()
        print(f"search() hybrid warm: {timed_ms(lambda: search(hub, q, embedder=emb)):8.1f} ms")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Chạy smoke nhỏ xác nhận hoạt động**

Run: `.venv/bin/python scripts/perf_search_smoke.py --sections 2000 --repos 5`
Expected: in đủ 5 dòng số đo, không exception. (Số đo warm ở 2k section phải dưới mục tiêu §2 với dư địa lớn; ngưỡng thật đo tay ở 50–100k, không assert trong CI.)

- [ ] **Step 3: Commit**

```bash
git add scripts/perf_search_smoke.py
git commit -m "test: perf smoke script for hybrid search index"
```

---

## Ghi chú review cuối (đã tự soát theo spec)

- §3.1–3.6 phủ ở Tasks 1–6; §3.5 trigger ở Task 7; §3.7 call site không đổi (Task 6 xác nhận qua test cũ); §4 migration ở Tasks 1/2/7/8; §5 degradation ở Tasks 1/6; §6 testing rải theo task tương ứng; §7 đúng thứ tự spec.
- Naming nhất quán: `open_db/open_fresh/sync/delete_db/fts_search/knn_search/rrf_merge/load_sections/SectionRow/SyncReport` — mọi task dùng đúng các tên này.
- Hai hành vi đổi có chủ đích, KHÔNG phải bug khi review: (1) `score` là RRF score (~0.016–0.033) thay vì BM25/cosine; (2) MCP note "score closely" xuất hiện thường hơn — spec Non-goals, tuning sau.
