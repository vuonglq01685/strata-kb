import pytest

from center_kb import models
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
    assert len(results) == 1  # always returns >= 1 when there is a match


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


def test_get_section_folded_id_l3_returns_subtree(fed_hub):
    entry = fed_hub / "federation" / "arinc-kb"
    (entry / "arinc-424" / "ch1.raw.md").write_text(
        "## 5.3 Restrictive Airspace\n\nParent raw.\n\n"
        "### 5.3.1 Folded torque\n\nTorque 12 Nm bolt XYZ.\n\n"
        "### 5.3.2 Folded other\n\nOther text.\n",
        encoding="utf-8",
    )
    hub = HubHandle(root=fed_hub)
    r = get_section(hub, "arinc-424", "5.3.1", level="l3")
    assert r is not None
    assert r.section_id == "5.3.1"
    assert "Torque 12 Nm" in r.content
    assert "Folded other" not in r.content
    assert "§5.3.1" in r.citation


def test_get_section_folded_id_l2_returns_parent(fed_hub):
    hub = HubHandle(root=fed_hub)
    r = get_section(hub, "arinc-424", "5.3.1", level="l2")
    assert r is not None
    assert r.section_id == "5.3"  # L2 không có anchor con — trả parent, không nói dối
    assert "§5.3" in r.citation


def test_get_section_folded_id_unknown_returns_none(fed_hub):
    hub = HubHandle(root=fed_hub)
    assert get_section(hub, "arinc-424", "9.9.9", level="l3") is None


def test_get_section_prefix_picks_longest_parent(fed_hub):
    # manifest có cả "5" lẫn "5.3" → "5.3.1" phải chọn "5.3"
    entry = fed_hub / "federation" / "arinc-kb"
    manifest_path = entry / "arinc-424" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections.insert(
        0, models.SectionEntry(id="5", title="Chapter Five", file="ch1")
    )
    models.save_yaml_model(manifest_path, manifest)
    (entry / "arinc-424" / "ch1.raw.md").write_text(
        "## 5 Chapter Five\n\nChapter body.\n\n"
        "## 5.3 Restrictive Airspace\n\nParent raw.\n\n"
        "### 5.3.1 Folded torque\n\nTorque 12 Nm bolt XYZ.\n",
        encoding="utf-8",
    )
    hub = HubHandle(root=fed_hub)
    r = get_section(hub, "arinc-424", "5.3.1", level="l3")
    assert r is not None and "Torque 12 Nm" in r.content
