"""The close-top-2 note.

Reviewer C F-C5: README §7.8 promises kb_search "flags when the top two are
close in score". `_ambiguity_note` requires BOTH hits to be `hybrid`, which
cannot happen without an embedder — so on the shipped default it fired 0/14
times, including on "Restrictive Airspace Designation" where
`beta:arinc-424 §5.129` and `aero:arinc-424 §5.129` were ranks 1 and 2: exactly
the case a BA must be warned about. With the semantic floor lowered so both
legs contribute it fired 9/10, including on unambiguous queries. The flag has
no calibrated middle.

RRF carries no magnitude — adjacent ranks in one leg are always ~1.6% apart —
so the score half of the rule has to read raw BM25.
"""
import pytest

pytest.importorskip("sqlite_vec")

from center_kb.federation import write_federation_index
from center_kb.hub import HubHandle
from center_kb.mdutils import count_tokens
from center_kb.query import QueryResult, _ambiguity_notes, search_detailed
from tests.conftest import make_fed_entry


@pytest.fixture
def colliding_hub(fed_hub):
    """A second repo publishing the same doc id AND the same section id."""
    make_fed_entry(
        fed_hub / "federation", "beta-kb", "arinc-424",
        tags=["arinc424"],
        sec_id="5.3", sec_title="Restrictive Airspace",
        sec_summary="Restrictive airspace: designation, type, multiple code.",
        l2="## 5.3 Restrictive Airspace\n\nCondensed: restrictive airspace designation codes.\n",
        l3="## 5.3 Restrictive Airspace\n\nFull raw restrictive airspace text.\n",
    )
    write_federation_index(fed_hub / "federation")
    return HubHandle(root=fed_hub)


def test_federation_collision_always_flags(colliding_hub):
    outcome = search_detailed(colliding_hub, "restrictive airspace designation")
    assert len(outcome.results) >= 2
    note = "".join(outcome.notes)
    assert "same section" in note
    assert "arinc-kb:arinc-424 §5.3" in note
    assert "beta-kb:arinc-424 §5.3" in note


def test_unambiguous_query_is_silent(fed_hub):
    outcome = search_detailed(HubHandle(root=fed_hub), "restrictive airspace designation")
    assert not any("same section" in n or "score closely" in n for n in outcome.notes)


def _keyword_result(section_id: str) -> QueryResult:
    return QueryResult(
        doc_id="arinc-424",
        section_id=section_id,
        title="Title",
        score=0.0,
        citation=f"arinc-kb:arinc-424 §{section_id}",
        content="content",
        tokens=1,
        content_tokens=count_tokens("content"),
        source="arinc-kb",
        match_mode="keyword",
    )


def test_ambiguity_notes_score_path_fires_on_exact_tie():
    """AMBIG_BM25_RATIO == 1.00 — only an exact tie on the keyword leg's raw
    BM25 scores should fire the score-based note (Task 10 Step 6: no ratio
    below 0.99 separates this corpus's unambiguous battery from a close
    pair, so the threshold was raised to an exact tie)."""
    results = [_keyword_result("1.1"), _keyword_result("1.2")]
    result_rowids = [1, 2]
    fts_scores = {1: 10.0, 2: 10.0}
    notes = _ambiguity_notes(results, result_rowids, fts_scores)
    assert any("score closely" in n for n in notes)


def test_ambiguity_notes_score_path_silent_when_not_tied():
    results = [_keyword_result("1.1"), _keyword_result("1.2")]
    result_rowids = [1, 2]
    fts_scores = {1: 10.0, 2: 9.9}
    notes = _ambiguity_notes(results, result_rowids, fts_scores)
    assert not any("score closely" in n for n in notes)


def test_ambiguity_notes_uses_result_rowids_not_fused():
    """Review round 2: `search_detailed`'s loop skips a fused entry when its
    row or L2 content is missing (stale/partial hub cache), so `fused[:2]`
    can name different rows than `results[:2]`. Row 5 here stands in for a
    skipped fused entry — the cited pair is actually rowids 7 and 3."""
    results = [_keyword_result("1.1"), _keyword_result("1.2")]
    result_rowids = [7, 3]

    tied_scores = {5: 20.0, 7: 10.0, 3: 10.0}
    notes = _ambiguity_notes(results, result_rowids, tied_scores)
    assert any("score closely" in n for n in notes)

    # Pre-fix, pairing fused[:2] = [5, 7] would score hi=fts[5]=1.0,
    # lo=fts[7]=10.0 -> lo/hi = 10.0 >= 1.0 -> fires on a mismatched,
    # inverted pair that was never actually compared. The pair actually
    # cited (7, 3) does not tie, so this must stay silent.
    inverted_scores = {5: 1.0, 7: 10.0, 3: 9.0}
    notes = _ambiguity_notes(results, result_rowids, inverted_scores)
    assert not any("score closely" in n for n in notes)
