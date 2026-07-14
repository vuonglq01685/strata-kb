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
