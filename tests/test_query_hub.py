from center_kb import models
from center_kb.hub import HubHandle
from center_kb.query import get_section, search


def _fed_entry(hub_root, repo_id, doc_id, summary):
    from center_kb.federation import FederationMeta

    entry = hub_root / "federation" / repo_id
    (entry / "manifests").mkdir(parents=True)
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(
            repo_id=repo_id, source_url=f"git@host:{repo_id}.git", source_commit="abc1234"
        ),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(
            docs=[models.IndexEntry(id=doc_id, title=doc_id, tags=["ops"], summary=summary)]
        ),
    )
    models.save_yaml_model(
        entry / "manifests" / f"{doc_id}.yaml",
        models.Manifest(
            id=doc_id,
            title=doc_id,
            sections=[
                models.SectionEntry(
                    id="3.2",
                    title="Roster Rules",
                    summary=summary,
                    status="reviewed",
                    file="ch3",
                )
            ],
        ),
    )


def test_search_without_hub_unchanged(fixture_kb):
    results = search(fixture_kb, "airspace designation")
    assert results
    assert all(r.source == "local" for r in results)


def test_search_includes_hub_domain_docs(fixture_kb, hub_worktree):
    handle = HubHandle(root=hub_worktree)
    results = search(fixture_kb, "restrictive airspace designation", hub=handle)
    hub_hits = [r for r in results if r.source == "hub"]
    assert hub_hits
    assert hub_hits[0].doc_id == "arinc-424"
    assert "Restrictive" in hub_hits[0].content  # full L2, not summary
    assert "arinc-424 §5.3" in hub_hits[0].citation


def test_search_federation_returns_summary_with_pointer(fixture_kb, hub_worktree):
    _fed_entry(hub_worktree, "crew-ops", "roster-sop", "Crew roster duty limits and rest rules.")
    handle = HubHandle(root=hub_worktree)
    results = search(fixture_kb, "crew roster duty rest", hub=handle)
    remote = [r for r in results if r.source == "remote:crew-ops"]
    assert remote
    r = remote[0]
    assert r.citation.startswith("crew-ops:roster-sop §3.2")
    assert "duty limits" in r.content
    assert "[remote]" in r.content and "crew-ops" in r.content


def test_local_wins_doc_id_collision(fixture_kb, hub_worktree):
    # hub also has a 'demo-doc' → query returns only the local version
    hub_kb = hub_worktree / ".kb"
    index = models.load_yaml_model(hub_kb / "index.yaml", models.KBIndex)
    index.docs.append(
        models.IndexEntry(
            id="demo-doc", title="Demo (hub copy)", tags=["demo", "airspace"],
            summary="Hub copy of demo doc.",
        )
    )
    models.save_yaml_model(hub_kb / "index.yaml", index)
    (hub_kb / "demo-doc").mkdir()
    models.save_yaml_model(
        hub_kb / "demo-doc" / "_manifest.yaml",
        models.Manifest(
            id="demo-doc",
            title="Demo (hub copy)",
            sections=[
                models.SectionEntry(
                    id="1.1", title="Airspace Records",
                    summary="HUB VERSION airspace records.", status="reviewed", file="ch1",
                )
            ],
        ),
    )
    handle = HubHandle(root=hub_worktree)
    results = search(fixture_kb, "airspace records designation", hub=handle)
    demo_hits = [r for r in results if r.doc_id == "demo-doc"]
    assert demo_hits
    assert all(r.source == "local" for r in demo_hits)


def test_tag_filter_applies_across_sources(fixture_kb, hub_worktree):
    handle = HubHandle(root=hub_worktree)
    results = search(fixture_kb, "restrictive airspace", tags=["arinc424"], hub=handle)
    assert results
    assert all(r.source == "hub" for r in results)  # local doc doesn't have the arinc424 tag


def test_search_published_only_excludes_local(fixture_kb, hub_worktree):
    # include_local=False → only published sources (hub domain docs + federation)
    handle = HubHandle(root=hub_worktree)
    results = search(
        fixture_kb, "restrictive airspace designation", hub=handle, include_local=False
    )
    assert results
    assert all(r.source != "local" for r in results)
    assert any(r.source == "hub" for r in results)


def test_search_published_only_hub_not_blocked_by_local_collision(
    fixture_kb, hub_worktree
):
    # local demo-doc exists, but with include_local=False the hub copy must appear
    hub_kb = hub_worktree / ".kb"
    index = models.load_yaml_model(hub_kb / "index.yaml", models.KBIndex)
    index.docs.append(
        models.IndexEntry(
            id="demo-doc", title="Demo (hub copy)", tags=["demo", "airspace"],
            summary="Hub copy of demo doc.",
        )
    )
    models.save_yaml_model(hub_kb / "index.yaml", index)
    (hub_kb / "demo-doc").mkdir()
    (hub_kb / "demo-doc" / "ch1.md").write_text(
        "## 1.1 Airspace Records\n\nHUB VERSION airspace records designation.\n",
        encoding="utf-8",
    )
    models.save_yaml_model(
        hub_kb / "demo-doc" / "_manifest.yaml",
        models.Manifest(
            id="demo-doc",
            title="Demo (hub copy)",
            sections=[
                models.SectionEntry(
                    id="1.1", title="Airspace Records",
                    summary="HUB VERSION airspace records.", status="reviewed", file="ch1",
                )
            ],
        ),
    )
    handle = HubHandle(root=hub_worktree)
    results = search(
        fixture_kb, "airspace records designation", hub=handle, include_local=False
    )
    demo_hits = [r for r in results if r.doc_id == "demo-doc"]
    assert demo_hits
    assert all(r.source == "hub" for r in demo_hits)


def test_get_section_falls_back_to_hub(fixture_kb, hub_worktree):
    handle = HubHandle(root=hub_worktree)
    assert get_section(fixture_kb, "arinc-424", "5.3") is None  # no hub → not found
    result = get_section(fixture_kb, "arinc-424", "5.3", hub=handle)
    assert result is not None
    assert result.source == "hub"
    assert "Restrictive" in result.content


def test_cli_query_with_hub(fixture_kb, hub_worktree):
    from typer.testing import CliRunner

    from center_kb.cli import app

    result = CliRunner().invoke(
        app,
        ["query", "restrictive airspace", "--kb-dir", str(fixture_kb),
         "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 0, result.output
    assert "arinc-424 §5.3" in result.output
