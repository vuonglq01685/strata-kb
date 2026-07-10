from aero_kb.query import search

from tests.test_embed import FakeEmbedder  # reuse the 4-dim fake


def test_bm25_miss_falls_back_to_semantic(fixture_kb):
    # query shares no token with the summary ("controlled zones") but
    # FakeEmbedder maps 'airspace' → axis 1, so semantic still catches it
    results = search(
        fixture_kb, "airspace controlled zones", semantic=True,
        embedder=FakeEmbedder(),
    )
    assert results
    assert results[0].section_id == "1.1"


def test_semantic_flag_false_and_good_bm25_skips_embedding(fixture_kb):
    # embedder=None but BM25 has good results → embedding must not be touched
    results = search(fixture_kb, "airspace designation", embedder=None)
    assert results  # normal BM25 behavior


def test_no_embedder_no_crash_on_miss(fixture_kb):
    # BM25 misses entirely + no embedder → returns empty, no exception
    results = search(fixture_kb, "zzz qqq xxx", embedder=None)
    assert results == []


def test_garbage_query_semantic_returns_empty_not_nearest(fixture_kb):
    # Garbage query: BM25 miss + semantic fallback but every score is below
    # SEMANTIC_MIN_SCORE → must not be padded with nearest-but-meaningless results
    results = search(
        fixture_kb, "zzz qqq xxx", semantic=True, embedder=FakeEmbedder()
    )
    assert results == []
