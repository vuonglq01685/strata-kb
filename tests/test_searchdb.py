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


def test_open_db_warm_read_only_under_writer_lock(tmp_path, monkeypatch):
    # schema đã có → open_db không được ghi gì — query phải chạy song song
    # với một sync dài đang giữ writer lock (spec §3.2), index không bị đụng
    hub = _handle(tmp_path)
    conn = searchdb.open_db(hub)
    conn.execute("INSERT INTO repos VALUES('r', 'fp')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(searchdb, "_BUSY_TIMEOUT_MS", 100)
    holder = sqlite3.connect(searchdb.db_path(hub))
    holder.execute("BEGIN IMMEDIATE")  # giữ write lock như một sync đang chạy
    try:
        conn = searchdb.open_db(hub)  # đọc thuần — không đợi, không lỗi
        try:
            assert conn.execute("SELECT COUNT(*) FROM repos").fetchone() == (1,)
        finally:
            conn.close()
    finally:
        holder.rollback()
        holder.close()


def test_open_db_cold_locked_raises_instead_of_rebuild(tmp_path, monkeypatch):
    # chưa có schema thì open_db phải ghi — gặp lock: raise, tuyệt đối không
    # coi là corruption mà xoá file (process khác đang tạo index)
    hub = _handle(tmp_path)
    path = searchdb.db_path(hub)
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(searchdb, "_BUSY_TIMEOUT_MS", 100)
    holder = sqlite3.connect(path)
    holder.execute("BEGIN IMMEDIATE")  # lock trên file chưa có schema
    try:
        with pytest.raises(sqlite3.OperationalError):
            searchdb.open_db(hub)
    finally:
        holder.rollback()
        holder.close()


def test_open_db_corrupt_rebuild_leaves_no_open_connection(tmp_path, monkeypatch):
    # connection mở dở trên file hỏng phải được close trước delete_db —
    # Windows không unlink được file đang mở (spec windows-support §R5)
    hub = _handle(tmp_path)
    path = searchdb.db_path(hub)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not a sqlite database at all")
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    conn = searchdb.open_db(hub)
    conn.close()
    for c in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")


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


def test_fts_indexes_l2_beyond_500_chars(fed_hub):
    # table nằm SAU summary dài — ngoài cửa sổ body_head cũ
    entry = fed_hub / "federation" / "arinc-kb"
    l2 = entry / "arinc-424" / "ch1.md"
    l2.write_text(
        "## 5.3 Restrictive Airspace\n\n"
        + ("Prose padding sentence. " * 30)  # > 500 chars
        + "\n\n| Part | Torque |\n|---|---|\n| BOLTQX9 | 12 Nm |\n",
        encoding="utf-8",
    )
    _bump_meta(entry)
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    conn = searchdb.open_db(hub)
    try:
        hits = searchdb.fts_search(conn, "BOLTQX9")
        assert len(hits) == 1
    finally:
        conn.close()


def test_fts_indexes_l3_only_terms(fed_hub):
    # term chỉ tồn tại trong raw L3 (section fold) — L2 summary không nhắc
    entry = fed_hub / "federation" / "arinc-kb"
    l3 = entry / "arinc-424" / "ch1.raw.md"
    l3.write_text(
        "## 5.3 Restrictive Airspace\n\nFull raw text.\n\n"
        "### 5.3-notes Folded notes\n\nUnique term ZEBRAFOLD77 here.\n",
        encoding="utf-8",
    )
    _bump_meta(entry)
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    conn = searchdb.open_db(hub)
    try:
        hits = searchdb.fts_search(conn, "ZEBRAFOLD77")
        assert len(hits) == 1
    finally:
        conn.close()


def test_sync_reindexes_when_only_l3_changes(fed_hub):
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    entry = fed_hub / "federation" / "arinc-kb"
    l3 = entry / "arinc-424" / "ch1.raw.md"
    l3.write_text(
        l3.read_text(encoding="utf-8") + "\nAppended raw-only fact QUOKKA55.\n",
        encoding="utf-8",
    )
    _bump_meta(entry)
    report = searchdb.sync(hub, None)
    assert report.sections_updated == 1  # hash phủ body_l3 → re-index


def test_sync_survives_missing_raw_md(fed_hub):
    entry = fed_hub / "federation" / "arinc-kb"
    (entry / "arinc-424" / "ch1.raw.md").unlink()
    _bump_meta(entry)
    hub = HubHandle(root=fed_hub)
    report = searchdb.sync(hub, None)
    assert report.sections_updated >= 1  # không fail, body_l3 rỗng
    conn = searchdb.open_db(hub)
    try:
        assert conn.execute("SELECT COUNT(*) FROM fts").fetchone() == (2,)
    finally:
        conn.close()


def test_bm25_title_match_outranks_l3_only_match(fed_hub, tmp_path):
    fed = fed_hub / "federation"
    make_fed_entry(
        fed, "title-kb", "title-doc",
        sec_id="1.1", sec_title="Corridor Spacing",
        sec_summary="About corridor spacing.",
        l2="## 1.1 Corridor Spacing\n\nCondensed corridor text.\n",
        l3="## 1.1 Corridor Spacing\n\nRaw corridor text.\n",
    )
    make_fed_entry(
        fed, "body-kb", "body-doc",
        sec_id="2.1", sec_title="Unrelated Title",
        sec_summary="Unrelated summary.",
        l2="## 2.1 Unrelated Title\n\nUnrelated condensed.\n",
        l3="## 2.1 Unrelated Title\n\ncorridor corridor corridor mentioned in raw.\n",
    )
    from center_kb.federation import write_federation_index

    write_federation_index(fed)
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    conn = searchdb.open_db(hub)
    try:
        hits = searchdb.fts_search(conn, "corridor")
        rows = searchdb.load_sections(conn, [h[0] for h in hits])
        ranked = [rows[h[0]].section_id for h in hits]
        assert ranked.index("1.1") < ranked.index("2.1")  # title+summary thắng L3 spam
    finally:
        conn.close()


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


def test_sync_content_hash_hit_refreshes_stale_section_metadata(fed_hub):
    """content_hash phủ title+summary+body_l2+body_l3 — doc_revision/title/file
    có thể lệch khỏi hub hiện tại (rename, bump revision) mà hash không đổi.
    Phải refresh 3 cột này (citation/path đúng) mà không rewrite FTS/re-embed."""
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    entry = fed_hub / "federation" / "arinc-kb"
    index_path = entry / "index.yaml"
    index = models.load_yaml_model(index_path, models.KBIndex)
    index.docs[0].revision = "Supplement 23"  # bump revision, content giữ nguyên
    models.save_yaml_model(index_path, index)
    manifest_path = entry / "arinc-424" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].file = "ch1-renamed"  # rename file, content giữ nguyên
    models.save_yaml_model(manifest_path, manifest)
    (entry / "arinc-424" / "ch1-renamed.md").write_text(
        (entry / "arinc-424" / "ch1.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (entry / "arinc-424" / "ch1-renamed.raw.md").write_text(
        (entry / "arinc-424" / "ch1.raw.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    report = searchdb.sync(hub, None)
    assert report.repos_synced == 1
    assert report.sections_updated == 0  # nội dung section không đổi — không rewrite
    conn = searchdb.open_db(hub)
    try:
        row = conn.execute(
            "SELECT doc_revision, file FROM sections WHERE repo_id='arinc-kb'"
        ).fetchone()
        assert row == ("Supplement 23", "ch1-renamed")
        assert conn.execute("SELECT COUNT(*) FROM fts").fetchone() == (2,)
    finally:
        conn.close()


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


def test_sync_warm_full_vec_coverage_skips_embed_call(fed_hub):
    """Mọi search() gọi open_fresh → _sync_vectors — với embedder có mặt, sync
    warm (đã embed đủ) trước đây phải load TOÀN BỘ sections JOIN fts vào Python
    để tìm rowid thiếu embedding, mỗi lần search. Warm sync giờ không được gọi
    embedder.embed() (spy đếm) và report.embedded phải = 0."""
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, FakeEmbedder())  # cold: embed toàn bộ, vec coverage đủ

    class CountingEmbedder(FakeEmbedder):
        def __init__(self):
            self.calls = 0

        def embed(self, texts):
            self.calls += 1
            return super().embed(texts)

    counting = CountingEmbedder()
    report = searchdb.sync(hub, counting)  # warm: vec coverage đã đủ
    assert report.embedded == 0
    assert counting.calls == 0  # không gọi embedder.embed() — không có gì để embed

    conn = searchdb.open_fresh(hub, counting)  # lazy check qua open_fresh cũng vậy
    try:
        assert counting.calls == 0
    finally:
        conn.close()


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


def test_sync_strict_raises_on_embedder_failure(fed_hub):
    # kb reindex phải thấy lỗi embed (strict) — chỉ query path mới degrade
    class Broken(FakeEmbedder):
        def embed(self, texts):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        searchdb.sync(HubHandle(root=fed_hub), Broken())


def test_interrupted_model_change_backfill_resumes(fed_hub, monkeypatch):
    # đổi model → drop/recreate vec + seal meta model mới ở commit batch đầu;
    # nếu backfill bị ngắt giữa chừng, vec_coverage phải dirty — sync sau
    # quét tiếp, không được kẹt 'complete' còn sót từ model cũ
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, FakeEmbedder())  # model cũ, coverage complete

    class NewModel(FakeEmbedder):
        name = "fake-4d-v2"

    class FlakyNewModel(NewModel):
        calls = 0

        def embed(self, texts):
            type(self).calls += 1
            if type(self).calls > 1:
                raise RuntimeError("interrupted mid-backfill")
            return super().embed(texts)

    monkeypatch.setattr(searchdb, "_EMBED_BATCH", 1)
    with pytest.raises(RuntimeError):
        searchdb.sync(hub, FlakyNewModel())  # batch 1 commit rồi nổ
    report = searchdb.sync(hub, NewModel())  # cùng model mới, chạy lành
    assert report.embedded == 1  # phần thiếu được quét tiếp
    conn = searchdb.open_db(hub)
    try:
        n_sec = conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        n_vec = conn.execute("SELECT COUNT(*) FROM vec_sections").fetchone()[0]
        assert n_vec == n_sec == 2
    finally:
        conn.close()


def test_concurrent_sync_same_repo_survives_losing_race(fed_hub, monkeypatch):
    # spec §5: thua race chỉ tốn công — không được vỡ UNIQUE (rồi bị query
    # path coi là corruption mà xoá index process thắng đang ghi)
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    entry = fed_hub / "federation" / "arinc-kb"
    l2 = entry / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("designation codes", "RACE codes"),
        encoding="utf-8",
    )
    _bump_meta(entry)
    real_parts = searchdb._section_parts
    fired = {"done": False}

    def hook(kb_dir, doc_id, sec):
        if not fired["done"]:
            fired["done"] = True
            searchdb.sync(hub, None)  # process B thắng race trên connection riêng
        return real_parts(kb_dir, doc_id, sec)

    monkeypatch.setattr(searchdb, "_section_parts", hook)
    searchdb.sync(hub, None)  # A thua race — phải idempotent, không nổ
    conn = searchdb.open_db(hub)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sections").fetchone() == (2,)
        assert conn.execute("SELECT COUNT(*) FROM fts").fetchone() == (2,)
    finally:
        conn.close()


def test_vector_backfill_survives_low_sql_variable_limit(tmp_path, monkeypatch):
    # nhiều build SQLite giới hạn SQLITE_MAX_VARIABLE_NUMBER=32766 — backfill
    # 100k section phải chunk IN(...) thay vì 1 bind/section trong 1 câu SQL
    from center_kb.federation import FederationMeta

    hub = _handle(tmp_path)
    entry = tmp_path / "federation" / "big-kb"
    doc_dir = entry / "big-doc"
    doc_dir.mkdir(parents=True)
    secs, body = [], []
    for i in range(10):
        sid = f"1.{i}"
        secs.append(
            models.SectionEntry(
                id=sid, title=f"S{i}", summary=f"summary {i}",
                status="summarized", file="ch1",
            )
        )
        body.append(f"## {sid} S{i}\n\ncontent {i}\n")
    (doc_dir / "ch1.md").write_text("\n".join(body), encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(id="big-doc", title="Big", sections=secs),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id="big-doc", title="Big", summary="s")]),
    )
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(
            repo_id="big-kb", source_commit="abc1234",
            published_at="2026-07-13T00:00:00+00:00",
        ),
    )
    real_raw = searchdb._raw_connect

    def limited(path):
        conn, vec = real_raw(path)
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 8)
        return conn, vec

    monkeypatch.setattr(searchdb, "_raw_connect", limited)
    monkeypatch.setattr(searchdb, "_EMBED_BATCH", 4)  # chunk phải lọt limit 8
    report = searchdb.sync(hub, FakeEmbedder())
    assert report.embedded == 10


def test_is_lock_error_matches_by_errorname():
    # SQLITE_PROTOCOL hiện là "locking protocol" — substring "locked"/"busy"
    # trượt → từng bị coi là corruption. Match theo sqlite_errorname.
    class _ProtocolErr(sqlite3.OperationalError):
        sqlite_errorname = "SQLITE_PROTOCOL"

    class _NoSuchTable(sqlite3.OperationalError):
        sqlite_errorname = "SQLITE_ERROR"

    assert searchdb.is_lock_error(_ProtocolErr("locking protocol"))
    assert searchdb.is_lock_error(sqlite3.OperationalError("database is locked"))
    assert not searchdb.is_lock_error(_NoSuchTable("no such table: x"))
    assert not searchdb.is_lock_error(sqlite3.DatabaseError("malformed"))


def test_sync_commits_per_repo_midway_failure_keeps_finished_repos(fed_hub):
    # cold sync bị ngắt giữa chừng không được mất repo đã xong — commit per
    # repo (đồng thời thu hẹp writer-lock window cho process đọc song song)
    hub = HubHandle(root=fed_hub)
    # load_federation sort theo tên: arinc-kb sync trước, icao-kb hỏng → nổ sau
    bad = fed_hub / "federation" / "icao-kb" / "icao-annex-2" / "_manifest.yaml"
    bad.write_text("{{{ not valid yaml", encoding="utf-8")
    with pytest.raises(Exception):
        searchdb.sync(hub, None)
    conn = searchdb.open_db(hub)
    try:
        repos = [r[0] for r in conn.execute("SELECT repo_id FROM repos")]
        assert repos == ["arinc-kb"]
        n = conn.execute(
            "SELECT COUNT(*) FROM sections WHERE repo_id = 'arinc-kb'"
        ).fetchone()[0]
        assert n == 1
    finally:
        conn.close()


def test_warm_sync_skips_vector_scan_when_coverage_complete(fed_hub):
    # anti-join dò rowid thiếu embedding từng chạy O(N) MỖI query dù warm —
    # meta 'vec_coverage=complete' phải skip nó khi không có section mới
    hub = HubHandle(root=fed_hub)
    emb = FakeEmbedder()
    searchdb.sync(hub, emb)
    conn = searchdb.open_db(hub)
    conn.execute(
        "DELETE FROM vec_sections WHERE rowid = (SELECT MIN(id) FROM sections)"
    )
    conn.commit()
    conn.close()
    searchdb.sync(hub, emb)  # warm no-op — không được quét lại
    conn = searchdb.open_db(hub)
    try:
        n_sec = conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        n_vec = conn.execute("SELECT COUNT(*) FROM vec_sections").fetchone()[0]
        assert n_vec == n_sec - 1  # lỗ nhân tạo còn nguyên = scan đã skip
    finally:
        conn.close()
    # section đổi nội dung → insert mới → coverage dirty → scan lại, vá cả lỗ
    entry = fed_hub / "federation" / "arinc-kb"
    l2 = entry / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"),
        encoding="utf-8",
    )
    _bump_meta(entry)  # đổi fingerprint để repo không bị skip
    searchdb.sync(hub, emb)
    conn = searchdb.open_db(hub)
    try:
        n_sec = conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        n_vec = conn.execute("SELECT COUNT(*) FROM vec_sections").fetchone()[0]
        assert n_vec == n_sec
    finally:
        conn.close()


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


def test_rrf_merge_single_leg_and_tie_determinism():
    assert searchdb.rrf_merge([], []) == []
    only_fts = searchdb.rrf_merge([(7, 3.0)], [])
    assert only_fts == [(7, pytest.approx(1 / 61), "keyword")]
    # tie score → sort theo rowid tăng dần, deterministic
    tie = searchdb.rrf_merge([(5, 1.0)], [(4, 1.0)])
    assert [t[0] for t in tie] == [4, 5]
