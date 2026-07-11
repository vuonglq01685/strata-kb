from pathlib import Path

from center_kb.build import build_kb, kb_stats


def test_stats_reports_tokens_per_tier(fixture_kb: Path):
    build_kb(fixture_kb)  # cap nhat token counts truoc
    l0_tokens, docs = kb_stats(fixture_kb)
    assert l0_tokens > 0
    assert len(docs) == 1
    d = docs[0]
    assert d.doc_id == "demo-doc"
    assert d.n_sections == 2
    assert 0 < d.l2_tokens < d.l3_tokens
    assert d.l1_tokens > 0
    assert 0 < d.saving_pct < 100
