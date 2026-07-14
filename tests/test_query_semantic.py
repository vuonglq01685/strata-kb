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


class BrokenEmbedder(FakeEmbedder):
    """Nổ ngay lần embed đầu tiên — mô phỏng onnx runtime fail lúc sync."""

    def embed(self, texts):
        raise RuntimeError("onnx runtime blew up")


def test_embedder_failure_during_sync_degrades_to_keyword(fed_hub, caplog):
    # spec §5: embedding best-effort — embed fail lúc lazy sync không được
    # giết query; FTS leg vẫn phải trả kết quả
    from center_kb import searchdb

    hub = HubHandle(root=fed_hub)
    with caplog.at_level("WARNING", logger="center_kb.searchdb"):
        results = search(hub, "restrictive airspace", embedder=BrokenEmbedder())
    assert results
    assert all(r.match_mode == "keyword" for r in results)
    assert any("vector sync failed" in r.message for r in caplog.records)
    # FTS/sections work phải được commit dù embed fail — không sync lại từ đầu
    conn = searchdb.open_db(hub)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0] > 0
    finally:
        conn.close()


def test_corruption_during_freshness_sync_rebuilds_once(fed_hub, monkeypatch):
    # corruption lộ ra trong freshness sync (qua open_db meta check nhưng
    # DML fail) cũng phải rebuild-once như corruption lúc query (spec §5)
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
    assert calls["n"] == 2  # lần 1 hỏng → rebuild → lần 2 thành công


def test_sqlite_vec_load_failure_degrades_to_keyword(fed_hub, monkeypatch):
    # Python build thiếu loadable-extension support (enable_load_extension
    # vắng / load fail) → FTS-only, không vỡ toàn bộ search (spec §5)
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
    # database is locked trong lúc query = process khác đang sync —
    # phải raise, tuyệt đối không xoá index đang được ghi (spec §3.2)
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


def test_corrupt_db_rebuilt_once_transparently(fed_hub):
    from center_kb import searchdb

    hub = HubHandle(root=fed_hub)
    search(hub, "airspace")  # build index
    searchdb.db_path(hub).write_bytes(b"corrupted")
    results = search(hub, "restrictive airspace designation")  # rebuild + trả kết quả
    assert results
