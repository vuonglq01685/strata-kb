from center_kb.hub import HubHandle
from center_kb.query import search

from tests.test_embed import FakeEmbedder  # reuse the 4-dim fake


def test_semantic_fallback_kicks_in_when_bm25_misses(fed_hub):
    # weak keyword signal across both federation repos (tied, well below
    # SEMANTIC_FALLBACK_THRESHOLD) but FakeEmbedder maps 'airspace' → axis 0,
    # so the forced semantic pass finds a confident match in each repo.
    results = search(
        HubHandle(root=fed_hub),
        "airspace corridor clearance limits",
        embedder=FakeEmbedder(),
        semantic=True,
    )
    assert results and results[0].match_mode == "semantic"
    assert (fed_hub / ".kb-work" / "embeddings-arinc-kb.db").exists()


def test_semantic_flag_false_and_good_bm25_skips_embedding(fed_hub):
    # embedder=None but BM25 has results → no crash, keyword mode kept
    # (default_embedder() short-circuits to None; no real embedding happens)
    results = search(
        HubHandle(root=fed_hub), "airspace designation type", embedder=None
    )
    assert results  # normal BM25 behavior
    assert all(r.match_mode == "keyword" for r in results)


def test_no_embedder_no_crash_on_miss(fed_hub):
    # BM25 misses entirely + no embedder → returns empty, no exception
    results = search(HubHandle(root=fed_hub), "zzz qqq xxx", embedder=None)
    assert results == []


def test_garbage_query_semantic_returns_empty_not_nearest(fed_hub):
    # Garbage query: BM25 miss + semantic fallback but every score is below
    # SEMANTIC_MIN_SCORE → must not be padded with nearest-but-meaningless results
    results = search(
        HubHandle(root=fed_hub), "zzz qqq xxx", semantic=True, embedder=FakeEmbedder()
    )
    assert results == []


def test_semantic_fallback_results_have_semantic_match_mode(fed_hub):
    results = search(
        HubHandle(root=fed_hub), "airspace corridor clearance limits", semantic=True,
        embedder=FakeEmbedder(),
    )
    assert results
    assert all(r.match_mode == "semantic" for r in results)
