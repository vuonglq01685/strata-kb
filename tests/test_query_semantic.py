import pytest

from center_kb import models
from center_kb.federation import FederationMeta
from center_kb.hub import HubHandle
from center_kb.query import search
from tests.conftest import FakeEmbedder

pytest.importorskip("sqlite_vec")


def _bump_meta(entry, stamp="2026-07-14T09:00:00+00:00"):
    meta_path = entry / "_meta.yaml"
    meta = models.load_yaml_model(meta_path, FederationMeta)
    meta.published_at = stamp
    models.save_yaml_model(meta_path, meta)


def test_hybrid_both_legs_match_mode_hybrid(fed_hub):
    # 'airspace' hits both FTS (title/summary) and KNN (axis 0) → hybrid
    results = search(
        HubHandle(root=fed_hub), "restrictive airspace", embedder=FakeEmbedder()
    )
    assert results
    assert results[0].match_mode == "hybrid"
    assert (fed_hub / ".kb-work" / "search.db").exists()


def test_semantic_only_when_no_keyword_overlap(fed_hub):
    # 'corridor' is absent from the corpus (FTS miss) but FakeEmbedder maps to the
    # same axis as 'airspace' → only the KNN leg returns → match_mode semantic
    results = search(
        HubHandle(root=fed_hub), "corridor clearance", embedder=FakeEmbedder()
    )
    assert results
    assert all(r.match_mode == "semantic" for r in results)


def test_keyword_only_without_embedder(fed_hub):
    results = search(HubHandle(root=fed_hub), "airspace designation type")
    assert results  # autouse fixture forces default_embedder → None
    assert all(r.match_mode == "keyword" for r in results)


def test_no_embedder_no_crash_on_miss(fed_hub):
    assert search(HubHandle(root=fed_hub), "zzz qqq xxx", embedder=None) == []


def test_garbage_query_semantic_returns_empty_not_nearest(fed_hub):
    # every KNN score below SEMANTIC_MIN_SCORE → no near-but-meaningless result padding
    results = search(
        HubHandle(root=fed_hub), "zzz qqq xxx", semantic=True, embedder=FakeEmbedder()
    )
    assert results == []


def test_semantic_flag_without_embedder_warns(fed_hub, caplog):
    with caplog.at_level("WARNING", logger="center_kb.query"):
        results = search(HubHandle(root=fed_hub), "airspace", semantic=True)
    assert results  # FTS leg still returns
    assert any("semantic" in r.message.lower() for r in caplog.records)


def test_knn_leg_error_falls_back_to_keyword(fed_hub, caplog):
    class ExplodingEmbedder(FakeEmbedder):
        calls = 0

        def embed(self, texts):
            # call 1 (sync) works, call 2 (query vector) blows up
            type(self).calls += 1
            if type(self).calls > 1:
                raise RuntimeError("boom")
            return super().embed(texts)

    with caplog.at_level("WARNING", logger="center_kb.query"):
        results = search(
            HubHandle(root=fed_hub), "restrictive airspace",
            embedder=ExplodingEmbedder(),
        )
    assert results  # keyword leg still returns
    assert all(r.match_mode == "keyword" for r in results)


class BrokenEmbedder(FakeEmbedder):
    """Blows up on the very first embed — simulates onnx runtime failing during sync."""

    def embed(self, texts):
        raise RuntimeError("onnx runtime blew up")


def test_embedder_failure_during_sync_degrades_to_keyword(fed_hub, caplog):
    # spec §5: embedding is best-effort — an embed failure during lazy sync must not
    # kill the query; the FTS leg must still return results
    from center_kb import searchdb

    hub = HubHandle(root=fed_hub)
    with caplog.at_level("WARNING", logger="center_kb.searchdb"):
        results = search(hub, "restrictive airspace", embedder=BrokenEmbedder())
    assert results
    assert all(r.match_mode == "keyword" for r in results)
    assert any("vector sync failed" in r.message for r in caplog.records)
    # FTS/sections work must be committed even if embed fails — no full re-sync
    conn = searchdb.open_db(hub)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0] > 0
    finally:
        conn.close()


def test_corruption_during_freshness_sync_rebuilds_once(fed_hub, monkeypatch):
    # corruption surfacing during freshness sync (passes the open_db meta check but
    # DML fails) must also rebuild-once like corruption during query (spec §5)
    import sqlite3

    from center_kb import searchdb

    hub = HubHandle(root=fed_hub)
    search(hub, "airspace")  # build index
    real_open_fresh = searchdb.open_fresh
    calls = {"n": 0}

    def flaky(hub_, embedder):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.DatabaseError("database disk image is malformed")
        return real_open_fresh(hub_, embedder)

    monkeypatch.setattr(searchdb, "open_fresh", flaky)
    results = search(hub, "restrictive airspace designation")
    assert results
    assert calls["n"] == 2  # call 1 broken → rebuild → call 2 succeeds


def test_sqlite_vec_load_failure_degrades_to_keyword(fed_hub, monkeypatch):
    # Python build lacking loadable-extension support (enable_load_extension
    # missing / load fails) → FTS-only, must not break search entirely (spec §5)
    import sqlite_vec as vec_mod

    def broken_load(conn):
        raise AttributeError(
            "'sqlite3.Connection' object has no attribute 'enable_load_extension'"
        )

    monkeypatch.setattr(vec_mod, "load", broken_load)
    results = search(
        HubHandle(root=fed_hub), "airspace designation", embedder=FakeEmbedder()
    )
    assert results
    assert all(r.match_mode == "keyword" for r in results)


def test_locked_db_error_propagates_without_delete(fed_hub, monkeypatch):
    # database is locked during a query = another process is syncing —
    # must raise, absolutely never delete an index that is being written (spec §3.2)
    import sqlite3

    from center_kb import searchdb

    hub = HubHandle(root=fed_hub)
    search(hub, "airspace")  # build index

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(searchdb, "fts_search", locked)
    deleted: list[object] = []
    monkeypatch.setattr(searchdb, "delete_db", lambda h: deleted.append(h))
    with pytest.raises(sqlite3.OperationalError):
        search(hub, "airspace")
    assert deleted == []


def test_search_serves_stale_index_when_sync_locked(fed_hub, monkeypatch):
    # a long sync holds the writer lock + fingerprint mismatch (there is sync work) —
    # query serves the existing (stale) index instead of failing after busy_timeout
    import sqlite3

    from center_kb import models, searchdb
    from center_kb.federation import FederationMeta

    hub = HubHandle(root=fed_hub)
    assert search(hub, "restrictive airspace")  # build index
    meta_path = fed_hub / "federation" / "arinc-kb" / "_meta.yaml"
    meta = models.load_yaml_model(meta_path, FederationMeta)
    meta.published_at = "2026-07-14T09:00:00+00:00"  # fingerprint mismatch
    models.save_yaml_model(meta_path, meta)
    monkeypatch.setattr(searchdb, "_BUSY_TIMEOUT_MS", 100)
    holder = sqlite3.connect(searchdb.db_path(hub))
    holder.execute("BEGIN IMMEDIATE")
    try:
        results = search(hub, "restrictive airspace")
    finally:
        holder.rollback()
        holder.close()
    assert results  # no raise — returns results from the old index


def test_corrupt_db_rebuilt_once_transparently(fed_hub):
    from center_kb import searchdb

    hub = HubHandle(root=fed_hub)
    search(hub, "airspace")  # build index
    searchdb.db_path(hub).write_bytes(b"corrupted")
    results = search(hub, "restrictive airspace designation")  # rebuild + return results
    assert results


def test_search_snippet_when_match_only_in_l3(fed_hub):
    entry = fed_hub / "federation" / "arinc-kb"
    (entry / "arinc-424" / "ch1.raw.md").write_text(
        "## 5.3 Restrictive Airspace\n\nRaw text.\n\n"
        "### 5.3-notes Folded notes\n\nUnique fact GRYPHON42 lives here only.\n",
        encoding="utf-8",
    )
    _bump_meta(entry)
    hub = HubHandle(root=fed_hub)
    results = search(hub, "GRYPHON42", embedder=None)
    assert len(results) == 1
    r = results[0]
    assert "gryphon42" not in r.content.lower()  # L2 does not contain the term
    assert "GRYPHON42" in r.snippet
    assert r.snippet.startswith("…") or r.snippet.startswith("##")


def test_search_no_snippet_when_term_in_l2(fed_hub):
    hub = HubHandle(root=fed_hub)
    results = search(hub, "restrictive designation", embedder=None)
    assert results
    assert results[0].snippet == ""


def test_search_snippet_counts_into_budget(fed_hub):
    entry = fed_hub / "federation" / "arinc-kb"
    (entry / "arinc-424" / "ch1.raw.md").write_text(
        "## 5.3 Restrictive Airspace\n\nRaw text.\n\n"
        "### 5.3-notes Folded notes\n\nUnique fact GRYPHON42 lives here only.\n",
        encoding="utf-8",
    )
    _bump_meta(entry)
    hub = HubHandle(root=fed_hub)
    results = search(hub, "GRYPHON42", embedder=None)
    from center_kb.mdutils import count_tokens

    r = results[0]
    assert r.tokens == count_tokens(r.content) + count_tokens(r.snippet)
