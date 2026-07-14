import sqlite3

import pytest

sqlite_vec = pytest.importorskip("sqlite_vec")  # noqa: F401

from center_kb import models, searchdb
from center_kb.federation import FederationMeta
from center_kb.hub import HubHandle
from tests.conftest import FakeEmbedder, make_fed_entry


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
        "restrictive",
        "airspace",
        "5",
        "3",
    ]
