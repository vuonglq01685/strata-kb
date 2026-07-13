import pytest

from center_kb.hub import HubHandle
from center_kb.query import AmbiguousDocError, get_section, search
from tests.conftest import make_fed_entry


def _handle(fed_hub) -> HubHandle:
    return HubHandle(root=fed_hub)


def test_search_returns_full_l2_with_repo_citation(fed_hub):
    results = search(_handle(fed_hub), "restrictive airspace designation")
    assert results
    top = results[0]
    assert top.source == "arinc-kb"
    assert top.citation.startswith("arinc-kb:arinc-424 §5.3")
    assert "Condensed: restrictive airspace" in top.content
    assert top.match_mode == "keyword"


def test_search_covers_all_federation_repos(fed_hub):
    results = search(_handle(fed_hub), "airspace designation type")
    assert {r.source for r in results} == {"arinc-kb", "icao-kb"}


def test_search_tag_filter(fed_hub):
    results = search(_handle(fed_hub), "airspace", tags=["arinc424"])
    assert results and all(r.source == "arinc-kb" for r in results)


def test_search_empty_federation_returns_empty(tmp_path):
    (tmp_path / "federation").mkdir()
    (tmp_path / ".kb").mkdir()
    assert search(HubHandle(root=tmp_path), "anything") == []


def test_search_no_token_overlap_returns_empty(fed_hub):
    assert search(_handle(fed_hub), "zzz qqq xxx") == []


def test_search_budget_caps_results(fed_hub):
    results = search(_handle(fed_hub), "airspace designation type", budget=1)
    assert len(results) == 1  # luôn trả >= 1 khi có match


def test_get_section_unqualified_unique(fed_hub):
    r = get_section(_handle(fed_hub), "arinc-424", "5.3")
    assert r is not None
    assert r.source == "arinc-kb"
    assert r.citation.startswith("arinc-kb:arinc-424 §5.3")


def test_get_section_l3_and_colon_form(fed_hub):
    r = get_section(_handle(fed_hub), "arinc-kb:arinc-424", "§5.3", level="l3")
    assert r is not None
    assert "Full raw restrictive airspace" in r.content


def test_get_section_repo_param(fed_hub):
    r = get_section(_handle(fed_hub), "arinc-424", "5.3", repo="arinc-kb")
    assert r is not None and r.source == "arinc-kb"


def test_get_section_ambiguous_raises_with_candidates(fed_hub):
    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    with pytest.raises(AmbiguousDocError) as exc:
        get_section(_handle(fed_hub), "arinc-424", "5.3")
    assert "arinc-kb:arinc-424" in str(exc.value)
    assert "dup-kb:arinc-424" in str(exc.value)


def test_get_section_missing_returns_none(fed_hub):
    assert get_section(_handle(fed_hub), "ghost", "1.1") is None
    assert get_section(_handle(fed_hub), "arinc-424", "9.9") is None
