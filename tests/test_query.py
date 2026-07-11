from pathlib import Path

from center_kb.query import get_section, search


def test_search_finds_relevant_section_with_citation(fixture_kb: Path):
    results = search(fixture_kb, "airspace designation type")
    assert results
    top = results[0]
    assert top.doc_id == "demo-doc"
    assert top.section_id == "1.1"
    assert top.citation == "demo-doc §1.1 (Rev 1)"
    assert "designation" in top.content.lower()


def test_search_tag_filter_excludes_unmatched_docs(fixture_kb: Path):
    assert search(fixture_kb, "airspace", tags=["demo"])
    # nonexistent tag -> no doc matches -> no results
    assert search(fixture_kb, "airspace", tags=["nonexistent-tag"]) == []


def test_search_doc_id_as_tag_activates_doc(fixture_kb: Path):
    results = search(fixture_kb, "airway route", tags=["demo-doc"])
    assert results
    assert results[0].section_id == "1.2"


def test_search_respects_budget(fixture_kb: Path):
    unlimited = search(fixture_kb, "records structure", budget=100_000)
    assert len(unlimited) == 2
    tiny = search(fixture_kb, "records structure", budget=1)
    assert len(tiny) == 1  # the first result is always returned, then it stops


def test_get_section_l2_and_l3(fixture_kb: Path):
    l2 = get_section(fixture_kb, "demo-doc", "1.1", level="l2")
    assert l2 is not None
    assert "Condensed" in l2.content
    l3 = get_section(fixture_kb, "demo-doc", "§1.1", level="l3")
    assert l3 is not None
    assert "Full raw text" in l3.content


def test_get_section_missing_returns_none(fixture_kb: Path):
    assert get_section(fixture_kb, "demo-doc", "9.9") is None
    assert get_section(fixture_kb, "no-such-doc", "1.1") is None


def test_search_query_with_no_matching_terms_returns_empty(fixture_kb: Path):
    assert search(fixture_kb, "zzz qqq nonexistent") == []


def test_search_excludes_sections_without_any_query_term(fixture_kb: Path):
    results = search(fixture_kb, "airspace designation", budget=100_000)
    assert [r.section_id for r in results] == ["1.1"]  # 1.2 contains none of the query terms
