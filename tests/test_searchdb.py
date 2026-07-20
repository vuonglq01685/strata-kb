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
        # WAL + busy_timeout already set (spec §3.2)
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
    conn = searchdb.open_db(hub)  # version mismatch → delete + recreate
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
    # schema already exists → open_db must not write anything — query must run in
    # parallel with a long sync holding the writer lock (spec §3.2), index untouched
    hub = _handle(tmp_path)
    conn = searchdb.open_db(hub)
    conn.execute("INSERT INTO repos VALUES('r', 'fp')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(searchdb, "_BUSY_TIMEOUT_MS", 100)
    holder = sqlite3.connect(searchdb.db_path(hub))
    holder.execute("BEGIN IMMEDIATE")  # hold write lock like a running sync
    try:
        conn = searchdb.open_db(hub)  # pure read — no waiting, no error
        try:
            assert conn.execute("SELECT COUNT(*) FROM repos").fetchone() == (1,)
        finally:
            conn.close()
    finally:
        holder.rollback()
        holder.close()


def test_open_db_cold_locked_raises_instead_of_rebuild(tmp_path, monkeypatch):
    # without a schema, open_db must write — on lock: raise, absolutely never
    # treat it as corruption and delete the file (another process is creating the index)
    hub = _handle(tmp_path)
    path = searchdb.db_path(hub)
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(searchdb, "_BUSY_TIMEOUT_MS", 100)
    holder = sqlite3.connect(path)
    holder.execute("BEGIN IMMEDIATE")  # lock on a file with no schema yet
    try:
        with pytest.raises(sqlite3.OperationalError):
            searchdb.open_db(hub)
    finally:
        holder.rollback()
        holder.close()


def test_open_db_corrupt_rebuild_leaves_no_open_connection(tmp_path, monkeypatch):
    # a half-open connection on the corrupt file must be closed before delete_db —
    # Windows cannot unlink an open file (spec windows-support §R5)
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
    # create fake -wal/-shm files to make sure they get cleaned up
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
    # table sits AFTER a long summary — outside the old body_head window
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
    # term exists only in raw L3 (section fold) — L2 summary never mentions it
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
    assert report.sections_updated == 1  # hash covers body_l3 → re-index


def test_sync_survives_missing_raw_md(fed_hub):
    entry = fed_hub / "federation" / "arinc-kb"
    (entry / "arinc-424" / "ch1.raw.md").unlink()
    _bump_meta(entry)
    hub = HubHandle(root=fed_hub)
    report = searchdb.sync(hub, None)
    assert report.sections_updated >= 1  # no failure, body_l3 empty
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
        assert ranked.index("1.1") < ranked.index("2.1")  # title+summary beats L3 spam
    finally:
        conn.close()


def test_sync_builds_sections_fts_tags(fed_hub):
    hub = HubHandle(root=fed_hub)
    report = searchdb.sync(hub, None)
    assert report.repos_synced == 2
    assert report.sections_updated == 2  # each fixture repo has 1 section
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
    report = searchdb.sync(hub, None)  # no repo changed
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
    _bump_meta(entry)  # a real publish always bumps published_at
    report = searchdb.sync(hub, None)
    assert report.repos_synced == 1
    assert report.sections_updated == 1
    assert report.sections_deleted == 0


def test_sync_unchanged_content_rewrites_nothing(fed_hub):
    # fingerprint changes (re-publish) but each section's content-hash stays the same
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    _bump_meta(fed_hub / "federation" / "arinc-kb")
    report = searchdb.sync(hub, None)
    assert report.repos_synced == 1
    assert report.sections_updated == 0


def test_sync_content_hash_hit_refreshes_stale_section_metadata(fed_hub):
    """content_hash covers title+summary+body_l2+body_l3 — doc_revision/title/file
    can drift from the current hub (rename, bump revision) without the hash changing.
    Must refresh these 3 columns (correct citation/path) without rewriting FTS/re-embedding."""
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    entry = fed_hub / "federation" / "arinc-kb"
    index_path = entry / "index.yaml"
    index = models.load_yaml_model(index_path, models.KBIndex)
    index.docs[0].revision = "Supplement 23"  # bump revision, content unchanged
    models.save_yaml_model(index_path, index)
    manifest_path = entry / "arinc-424" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].file = "ch1-renamed"  # rename file, content unchanged
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
    assert report.sections_updated == 0  # section content unchanged — no rewrite
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
    # remove repo icao-kb from the federation entirely
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
    assert not legacy.exists()  # spec §4: clean up old caches best-effort


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
    r2 = searchdb.sync(hub, FakeEmbedder())  # embedder appears → backfill embeddings
    assert r2.embedded == 2
    assert r2.sections_updated == 0  # no manifest re-parse


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
    assert _vec_count(hub) == 2  # old row deleted, new row added


def test_sync_warm_full_vec_coverage_skips_embed_call(fed_hub):
    """Every search() calls open_fresh → _sync_vectors — with an embedder present,
    a warm sync (fully embedded) previously had to load ALL sections JOIN fts into
    Python to find rowids missing embeddings, on every search. A warm sync must now
    not call embedder.embed() (counting spy) and report.embedded must be 0."""
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, FakeEmbedder())  # cold: embed everything, vec coverage complete

    class CountingEmbedder(FakeEmbedder):
        def __init__(self):
            self.calls = 0

        def embed(self, texts):
            self.calls += 1
            return super().embed(texts)

    counting = CountingEmbedder()
    report = searchdb.sync(hub, counting)  # warm: vec coverage already complete
    assert report.embedded == 0
    assert counting.calls == 0  # no embedder.embed() call — nothing to embed

    conn = searchdb.open_fresh(hub, counting)  # lazy check via open_fresh, same thing
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
    assert report.embedded == 2  # re-embed everything
    conn = searchdb.open_db(hub)
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        assert meta["embed_model"] == "fake-4d-v2"
    finally:
        conn.close()


class _BadDimEmbedder:
    """Declares dim=4 but returns 3-dimensional vectors."""

    dim = 4
    name = "bad-dim"

    def embed(self, texts):
        return [[0.0, 0.0, 0.0] for _ in texts]


def test_sync_raises_on_wrong_vector_dim(fed_hub):
    with pytest.raises(ValueError):
        searchdb.sync(HubHandle(root=fed_hub), _BadDimEmbedder())


def test_sync_strict_raises_on_embedder_failure(fed_hub):
    # kb reindex must see the embed error (strict) — only the query path degrades
    class Broken(FakeEmbedder):
        def embed(self, texts):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        searchdb.sync(HubHandle(root=fed_hub), Broken())


def test_interrupted_model_change_backfill_resumes(fed_hub, monkeypatch):
    # model change → drop/recreate vec + seal the new model meta at the first batch
    # commit; if backfill is interrupted midway, vec_coverage must be dirty — the next
    # sync keeps scanning, must not get stuck on a leftover 'complete' from the old model
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, FakeEmbedder())  # old model, coverage complete

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
        searchdb.sync(hub, FlakyNewModel())  # batch 1 commits, then blows up
    report = searchdb.sync(hub, NewModel())  # same new model, clean run
    assert report.embedded == 1  # the missing part gets picked up by the scan
    conn = searchdb.open_db(hub)
    try:
        n_sec = conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        n_vec = conn.execute("SELECT COUNT(*) FROM vec_sections").fetchone()[0]
        assert n_vec == n_sec == 2
    finally:
        conn.close()


def test_concurrent_sync_same_repo_survives_losing_race(fed_hub, monkeypatch):
    # spec §5: losing the race only wastes work — must not break UNIQUE (and then
    # have the query path treat it as corruption and delete the index the winning
    # process is writing)
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
            searchdb.sync(hub, None)  # process B wins the race on its own connection
        return real_parts(kb_dir, doc_id, sec)

    monkeypatch.setattr(searchdb, "_section_parts", hook)
    searchdb.sync(hub, None)  # A loses the race — must be idempotent, no blow-up
    conn = searchdb.open_db(hub)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sections").fetchone() == (2,)
        assert conn.execute("SELECT COUNT(*) FROM fts").fetchone() == (2,)
    finally:
        conn.close()


def test_vector_backfill_survives_low_sql_variable_limit(tmp_path, monkeypatch):
    # many SQLite builds cap SQLITE_MAX_VARIABLE_NUMBER=32766 — backfilling
    # 100k sections must chunk IN(...) instead of 1 bind/section in a single SQL statement
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
    monkeypatch.setattr(searchdb, "_EMBED_BATCH", 4)  # chunks must fit within limit 8
    report = searchdb.sync(hub, FakeEmbedder())
    assert report.embedded == 10


def test_is_lock_error_matches_by_errorname():
    # SQLITE_PROTOCOL renders as "locking protocol" — substring "locked"/"busy"
    # misses → used to be treated as corruption. Match by sqlite_errorname.
    class _ProtocolErr(sqlite3.OperationalError):
        sqlite_errorname = "SQLITE_PROTOCOL"

    class _NoSuchTable(sqlite3.OperationalError):
        sqlite_errorname = "SQLITE_ERROR"

    assert searchdb.is_lock_error(_ProtocolErr("locking protocol"))
    assert searchdb.is_lock_error(sqlite3.OperationalError("database is locked"))
    assert not searchdb.is_lock_error(_NoSuchTable("no such table: x"))
    assert not searchdb.is_lock_error(sqlite3.DatabaseError("malformed"))


def test_sync_commits_per_repo_midway_failure_keeps_finished_repos(fed_hub):
    # a cold sync interrupted midway must not lose finished repos — commit per
    # repo (also narrows the writer-lock window for concurrently reading processes)
    hub = HubHandle(root=fed_hub)
    # load_federation sorts by name: arinc-kb syncs first, broken icao-kb blows up after
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
    # the anti-join probing for rowids missing embeddings used to run O(N) on EVERY
    # query even warm — meta 'vec_coverage=complete' must skip it when there are no
    # new sections
    hub = HubHandle(root=fed_hub)
    emb = FakeEmbedder()
    searchdb.sync(hub, emb)
    conn = searchdb.open_db(hub)
    conn.execute(
        "DELETE FROM vec_sections WHERE rowid = (SELECT MIN(id) FROM sections)"
    )
    conn.commit()
    conn.close()
    searchdb.sync(hub, emb)  # warm no-op — must not rescan
    conn = searchdb.open_db(hub)
    try:
        n_sec = conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        n_vec = conn.execute("SELECT COUNT(*) FROM vec_sections").fetchone()[0]
        assert n_vec == n_sec - 1  # artificial hole intact = scan was skipped
    finally:
        conn.close()
    # section content changes → new insert → coverage dirty → rescan, patches the hole too
    entry = fed_hub / "federation" / "arinc-kb"
    l2 = entry / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"),
        encoding="utf-8",
    )
    _bump_meta(entry)  # change fingerprint so the repo is not skipped
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
        assert rows[hits[0][0]].repo_id == "arinc-kb"  # most matching terms
        assert all(h[1] > 0 for h in hits)
        # both repos contain 'airspace'
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
        # doc_id also works as a tag
        hits2 = searchdb.fts_search(conn, "airspace", tags=["icao-annex-2"])
        rows2 = searchdb.load_sections(conn, [h[0] for h in hits2])
        assert rows2 and all(r.repo_id == "icao-kb" for r in rows2.values())
    finally:
        conn.close()


def test_fts_search_escapes_fts_syntax(fed_hub):
    conn = searchdb.open_fresh(HubHandle(root=fed_hub), None)
    try:
        # must not blow up with a syntax error on input containing FTS5 syntax
        for q in ['NEAR(airspace records)', 'title:"x" OR *', 'a"b', "air-space"]:
            searchdb.fts_search(conn, q)  # just must not raise
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
        # 'corridor' → airspace axis: both airspace sections match
        hits = searchdb.knn_search(conn, emb, "corridor clearance")
        assert len(hits) == 2
        assert all(score >= 0.6 for _, score in hits)  # SEMANTIC_MIN_SCORE
        # garbage: every score below threshold → empty, no nearest-but-irrelevant padding
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
    conn = searchdb.open_fresh(HubHandle(root=fed_hub), None)  # never embedded
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
    # rowid 2 appears in both legs → highest score
    assert fused[0][0] == 2
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)
    # tie (1 and 3 both 1/61? no — 1 rank1 fts = 1/61, 3 rank2 knn = 1/62)
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
    # tie score → sort by ascending rowid, deterministic
    tie = searchdb.rrf_merge([(5, 1.0)], [(4, 1.0)])
    assert [t[0] for t in tie] == [4, 5]
