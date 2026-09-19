import pytest

from strata_kb import models
from strata_kb.hub import HubHandle
from strata_kb.query import AmbiguousDocError, get_section, search
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
    assert r.section_id == "5.3"  # L2 has no child anchor — return the parent, don't lie
    assert "§5.3" in r.citation


def test_get_section_folded_id_unknown_returns_none(fed_hub):
    hub = HubHandle(root=fed_hub)
    assert get_section(hub, "arinc-424", "9.9.9", level="l3") is None


def test_get_section_prefix_picks_longest_parent(fed_hub):
    # manifest has both "5" and "5.3" → "5.3.1" must pick "5.3"
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


def test_get_section_nested_qualifier(tmp_path):
    from strata_kb.hub import HubHandle
    from strata_kb.query import get_section
    from tests.conftest import make_fed_entry

    hub_root = tmp_path / "hub"
    make_fed_entry(hub_root / "federation" / "mid", "repo-x", "doc-x")
    handle = HubHandle(root=hub_root)
    r = get_section(handle, "mid/repo-x:doc-x", "1.1")
    assert r is not None
    assert r.source == "mid/repo-x"
    assert r.citation.startswith("mid/repo-x:doc-x §1.1")


def test_search_use_semantic_false_skips_embedder(monkeypatch):
    import strata_kb.query as query_mod
    seen = {}

    def spy(hub, embedder, text, tags):
        seen["embedder"] = embedder
        return [], {}, False, {}, False

    monkeypatch.setattr(query_mod, "_search_index", spy)
    sentinel = object()
    assert query_mod.search(
        object(), "airspace", use_semantic=False, embedder=sentinel
    ) == []
    assert seen["embedder"] is None


def test_search_use_semantic_default_passes_embedder(monkeypatch):
    import strata_kb.query as query_mod
    seen = {}

    def spy(hub, embedder, text, tags):
        seen["embedder"] = embedder
        return [], {}, False, {}, False

    monkeypatch.setattr(query_mod, "_search_index", spy)
    sentinel = object()
    query_mod.search(object(), "airspace", embedder=sentinel)
    assert seen["embedder"] is sentinel


def test_busy_index_surfaces_a_note_instead_of_silent_stale_results(
    fed_hub, monkeypatch
):
    """R19 (final-branch review, Important): a lock error from `open_fresh`
    used to be handled with `logger.warning` only and a silent fall-back to
    the existing index — on a cold hub (never synced) that existing index is
    empty, so the caller got a confident 'No matching section found' with no
    hint a rebuild was in progress elsewhere. It must be a note the MCP/CLI/
    web caller actually sees, not something that only reaches stderr.

    `fed_hub` is a fresh tmp_path per test and nothing has synced its index
    yet, so the real (unmocked) `searchdb.open_db` already returns a
    freshly-created, empty-schema connection here — exactly the "fresh empty
    schema" the fallback branch is meant to serve."""
    import sqlite3

    from strata_kb import searchdb
    from strata_kb.query import BUSY_INDEX_NOTE, search_detailed

    lock_exc = sqlite3.OperationalError("database is locked")
    assert searchdb.is_lock_error(lock_exc)

    def raise_locked(hub, embedder):
        raise lock_exc

    monkeypatch.setattr(searchdb, "open_fresh", raise_locked)
    outcome = search_detailed(
        _handle(fed_hub), "restrictive airspace", use_semantic=False
    )
    assert outcome.results == []
    assert BUSY_INDEX_NOTE in outcome.notes


def test_unknown_tag_lists_the_published_vocabulary(fed_hub):
    """Reviewer C battery #32: `--tags nonexistent-tag` returned 0 results with
    no hint that the tag itself was the problem."""
    from strata_kb.query import search_detailed

    outcome = search_detailed(_handle(fed_hub), "runway", tags=["nonexistent-tag"])
    assert outcome.results == []
    note = "".join(outcome.notes)
    assert "nonexistent-tag" in note
    assert "arinc424" in note  # a real published tag


def test_doc_id_is_an_accepted_tag(fed_hub):
    """F-C14: searchdb.py:350 indexes doc.id.lower() as a synthetic tag, so
    `--tags arinc-424` works. It stays supported and must not be reported as
    unknown; it deliberately does NOT join the kb-context tag vocabulary."""
    from strata_kb.query import search_detailed

    outcome = search_detailed(_handle(fed_hub), "restrictive", tags=["arinc-424"])
    assert outcome.results
    assert outcome.notes == []


def test_stale_hub_note_reports_age_when_stale_else_empty(fed_hub):
    """M17 judgment call 1: moved verbatim from mcp.py's `_stale_note` to a
    public `query.stale_hub_note`. Pins its own branches directly -- no
    existing test (MCP or otherwise) ever exercised the `stale=True` branch
    before this move; every MCP fixture handle was fresh."""
    from strata_kb.query import stale_hub_note

    assert stale_hub_note(HubHandle(root=fed_hub)) == ""
    assert stale_hub_note(None) == ""
    note = stale_hub_note(HubHandle(root=fed_hub, stale=True, age_seconds=42.0))
    assert note == "[warn] hub cache is stale (~42s) — results may lag the hub\n\n"


def test_budget_tokens_still_include_the_snippet(fed_hub):
    """M17: `tokens` keeps counting content + snippet (the budget the search
    loop actually spent); `content_tokens` is content alone. Reuses the
    fold-notes trick from test_query_semantic.py's snippet tests (a raw-only
    L3 subsection so `_l3_snippet` actually fires) to guarantee a
    snippet-bearing result -- fed_hub's stock fixture content never produces
    one, so an assertion here would otherwise pass vacuously (tokens ==
    content_tokens for every result) both before and after this change.
    Falsifiable: before `content_tokens` existed this raised AttributeError;
    even with the field merely defaulted to 0 and never populated at the
    construction site, the second assertion would fail here because
    count_tokens(r.content) is nonzero for this fixture."""
    from strata_kb import models
    from strata_kb.federation import FederationMeta
    from strata_kb.mdutils import count_tokens

    entry = fed_hub / "federation" / "arinc-kb"
    (entry / "arinc-424" / "ch1.raw.md").write_text(
        "## 5.3 Restrictive Airspace\n\nRaw text.\n\n"
        "### 5.3-notes Folded notes\n\nUnique fact GRYPHON42 lives here only.\n",
        encoding="utf-8",
    )
    meta_path = entry / "_meta.yaml"
    meta = models.load_yaml_model(meta_path, FederationMeta)
    meta.published_at = "2026-07-14T09:00:00+00:00"
    models.save_yaml_model(meta_path, meta)

    results = search(_handle(fed_hub), "GRYPHON42", budget=8000)
    assert results
    r = results[0]
    assert r.snippet, "fixture must produce a snippet-bearing result"
    assert r.content_tokens == count_tokens(r.content)
    assert r.tokens == r.content_tokens + count_tokens(r.snippet)


def test_doc_id_tag_is_not_reported_unknown_on_the_empty_path(fed_hub):
    """F-C14 review fix: `test_doc_id_is_an_accepted_tag` never reaches the
    `not results and tags` branch (it has results), so it cannot tell the
    doc-id guard in `_unknown_tag_notes` apart from a no-op. A query that
    legitimately returns zero results with a doc-id tag must not falsely
    claim the doc id itself is unknown."""
    from strata_kb.query import search_detailed

    outcome = search_detailed(_handle(fed_hub), "zzqx", tags=["arinc-424"])
    assert outcome.results == []
    note = "".join(outcome.notes)
    assert "no document is tagged" not in note

    outcome2 = search_detailed(
        _handle(fed_hub), "zzqx", tags=["arinc-424", "nonexistent-tag"]
    )
    assert outcome2.results == []
    note2 = "".join(outcome2.notes)
    assert "'nonexistent-tag'" in note2
    assert "'arinc-424'" not in note2
