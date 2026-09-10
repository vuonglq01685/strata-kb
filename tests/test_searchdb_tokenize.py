"""Query-side tokenizer.

Reviewer C F-C9: `tokenize()` was `re.findall(r"[a-z0-9]+", text.lower())` —
ASCII only — while the index is `unicode61` and DOES hold non-ASCII tokens
(the report's probe: MATCH "đường" → 1 hit). So `đường băng sân bay` became
['ng','b','ng','s','n','bay'] and `kb query` answered with two confident,
wrong results and no warning. C2 requires L2 in the source language, so a
Vietnamese KB would be indexed and unsearchable.
"""
import unicodedata

from center_kb import searchdb
from center_kb.hub import HubHandle
from center_kb.query import search_detailed
from tests.conftest import make_fed_entry


def test_tokenize_keeps_non_ascii_letters():
    assert searchdb.tokenize("đường băng sân bay") == [
        "đường", "băng", "sân", "bay",
    ]


def test_tokenize_normalizes_nfd_input_to_match_nfc():
    """Review round 2, F-C9: an NFD query (macOS, some IMEs) spells each
    accented letter as base + combining mark; the combining mark is category
    Mn, not \\w, so [^\\W_]+ would split right through it while unicode61
    folds combining marks on both sides. NFC-normalise first so both forms
    tokenize identically."""
    nfc = "đường băng sân bay"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd, "fixture must actually exercise the NFD code path"
    assert searchdb.tokenize(nfd) == searchdb.tokenize(nfc) == [
        "đường", "băng", "sân", "bay",
    ]


def test_tokenize_treats_underscore_as_a_separator():
    """unicode61 does, so the query side must too — otherwise 'foo_bar'
    becomes a token the index can never contain."""
    assert searchdb.tokenize("foo_bar") == ["foo", "bar"]


def test_tokenize_still_splits_the_domain_punctuation():
    assert searchdb.tokenize("ARINC-424 §5.129 CUST/AREA") == [
        "arinc", "424", "5", "129", "cust", "area",
    ]


def test_vietnamese_term_round_trips_index_to_query(tmp_path, run_git):
    fed = tmp_path / "hub" / "federation"
    fed.mkdir(parents=True)
    (tmp_path / "hub" / ".kb").mkdir()
    make_fed_entry(
        fed, "vn-kb", "quy-chuan",
        sec_id="2.1", sec_title="Đường băng",
        l2="## 2.1 Đường băng\n\nĐường băng phải có ký hiệu nhận dạng rõ ràng.\n",
        l3="## 2.1 Đường băng\n\nĐường băng phải có ký hiệu nhận dạng rõ ràng.\n",
    )
    from center_kb.federation import write_federation_index

    write_federation_index(fed)
    hub = HubHandle(root=tmp_path / "hub")
    outcome = search_detailed(hub, "đường băng")
    assert outcome.results, "a Vietnamese query found nothing in a Vietnamese KB"
    assert outcome.results[0].section_id == "2.1"


def test_query_with_no_usable_tokens_says_so(fed_hub):
    outcome = search_detailed(HubHandle(root=fed_hub), "§§§ ---")
    assert outcome.results == []
    assert any("no searchable terms" in n for n in outcome.notes)


def test_long_punctuation_only_query_is_truncated_in_the_note(fed_hub):
    """Minor finding, promoted on final-branch review: the no-searchable-terms
    note echoed the raw query back unbounded — an MCP agent handing back an
    arbitrarily long punctuation-only string landed the whole thing in the
    payload. Bounded to 120 chars with an ellipsis."""
    long_query = "§---" * 75  # 300 chars, no alphanumeric tokens
    assert len(long_query) == 300
    outcome = search_detailed(HubHandle(root=fed_hub), long_query)
    assert outcome.results == []
    note = "".join(outcome.notes)
    assert "…" in note
    assert "no searchable terms" in note
    assert len(note) < len(long_query)


def test_empty_query_produces_no_note(fed_hub):
    """An empty query is the nav link's empty state, not a caller mistake."""
    outcome = search_detailed(HubHandle(root=fed_hub), "   ")
    assert outcome.notes == []
