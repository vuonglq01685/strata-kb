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
