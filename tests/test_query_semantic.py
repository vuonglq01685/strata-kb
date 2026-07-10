from aero_kb.query import search

from tests.test_embed import FakeEmbedder  # tái dùng fake 4 chiều


def test_bm25_miss_falls_back_to_semantic(fixture_kb):
    # query không chung token nào với summary ("controlled zones") nhưng
    # FakeEmbedder map 'airspace' → trục 1 nên semantic vẫn bắt được
    results = search(
        fixture_kb, "airspace controlled zones", semantic=True,
        embedder=FakeEmbedder(),
    )
    assert results
    assert results[0].section_id == "1.1"


def test_semantic_flag_false_and_good_bm25_skips_embedding(fixture_kb):
    # embedder=None mà BM25 có kết quả tốt → không được đụng embedding
    results = search(fixture_kb, "airspace designation", embedder=None)
    assert results  # nguyên hành vi BM25


def test_no_embedder_no_crash_on_miss(fixture_kb):
    # BM25 miss hoàn toàn + không có embedder → trả rỗng, không exception
    results = search(fixture_kb, "zzz qqq xxx", embedder=None)
    assert results == []


def test_garbage_query_semantic_returns_empty_not_nearest(fixture_kb):
    # Query rác: BM25 miss + semantic fallback nhưng mọi score dưới sàn
    # SEMANTIC_MIN_SCORE → không được nhồi kết quả gần-nhất-nhưng-vô-nghĩa
    results = search(
        fixture_kb, "zzz qqq xxx", semantic=True, embedder=FakeEmbedder()
    )
    assert results == []
