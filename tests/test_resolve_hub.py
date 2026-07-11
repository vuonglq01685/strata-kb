import pytest

from center_kb import gitio, kbcontext, models
from center_kb.hub import HubHandle
from center_kb.resolve import render_resolved, resolve_refs


def _ctx(version, *refs, hub_version=None):
    return kbcontext.KBContext(
        version=version,
        hub_version=hub_version,
        refs=[kbcontext.parse_ref(r) for r in refs],
    )


@pytest.fixture
def hub_git(hub_worktree, run_git):
    """Hub with 2 commits: rev1 = original; rev2 (HEAD) = §5.3 L2 edit (amendment)."""
    rev1 = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    l2 = hub_worktree / ".kb" / "arinc-424" / "ch5-airspace.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "designation, type, multiple code, level.",
            "designation, type, multiple code, level, NEW controlling agency.",
        ),
        encoding="utf-8",
    )
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub amendment")
    rev2 = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    return {"root": hub_worktree, "rev1": rev1, "rev2": rev2}


def test_local_ref_without_hub_unchanged(git_kb):
    ctx = _ctx(git_kb["rev1"], "demo-doc §1.1")
    results = resolve_refs(git_kb["kb"], ctx)
    assert results[0].status == "stale"  # amendment at rev2, same as the Phase 2 fixture
    assert results[0].pinned_rev == git_kb["rev1"]


def test_hub_ref_resolves_at_hub_version(git_kb, hub_git):
    handle = HubHandle(root=hub_git["root"])
    ctx = _ctx(git_kb["rev2"], "arinc-424 §5.3", hub_version=hub_git["rev1"])
    results = resolve_refs(git_kb["kb"], ctx, hub=handle)
    r = results[0]
    assert r.status == "stale"  # hub was amended after the pin
    assert r.pinned_rev == hub_git["rev1"]
    assert "NEW controlling agency" not in r.content  # correct pinned content
    assert "Supplement 22" in r.citation


def test_hub_ref_ok_when_pinned_at_head(git_kb, hub_git):
    handle = HubHandle(root=hub_git["root"])
    ctx = _ctx(git_kb["rev2"], "arinc-424 §5.3", hub_version=hub_git["rev2"])
    results = resolve_refs(git_kb["kb"], ctx, hub=handle)
    assert results[0].status == "ok"


def test_hub_ref_missing_hub_version_broken(git_kb, hub_git):
    handle = HubHandle(root=hub_git["root"])
    ctx = _ctx(git_kb["rev2"], "arinc-424 §5.3")  # no hub_version
    results = resolve_refs(git_kb["kb"], ctx, hub=handle)
    assert results[0].status == "broken"
    assert "hub_version" in results[0].reason
    assert "kb context new" in results[0].reason


def test_hub_ref_without_hub_handle_broken_not_crash(git_kb):
    # block cites a hub doc but runs without --hub → broken via the local Phase 2 path
    ctx = _ctx(git_kb["rev1"], "arinc-424 §5.3", hub_version="abc1234")
    results = resolve_refs(git_kb["kb"], ctx)
    assert results[0].status == "broken"


def test_remote_ref_resolves_summary_from_federation(git_kb, hub_git, run_git):
    # create a federation entry in the hub then commit — rev3 contains federation
    hub_root = hub_git["root"]
    from center_kb.federation import FederationMeta

    entry = hub_root / "federation" / "crew-ops"
    (entry / "manifests").mkdir(parents=True)
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(repo_id="crew-ops", source_url="git@host:crew-ops.git",
                       source_commit="abc1234"),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id="roster-sop", title="Roster SOP")]),
    )
    models.save_yaml_model(
        entry / "manifests" / "roster-sop.yaml",
        models.Manifest(
            id="roster-sop", title="Roster SOP",
            sections=[models.SectionEntry(
                id="3.2", title="Roster Rules",
                summary="Crew roster duty limits and rest rules.",
                status="reviewed", file="ch3",
            )],
        ),
    )
    run_git(hub_root, "add", "-A")
    run_git(hub_root, "commit", "-m", "federation crew-ops")
    rev3 = run_git(hub_root, "rev-parse", "--short", "HEAD")

    handle = HubHandle(root=hub_root)
    ctx = _ctx(git_kb["rev2"], "crew-ops:roster-sop §3.2", hub_version=rev3)
    results = resolve_refs(git_kb["kb"], ctx, hub=handle)
    r = results[0]
    assert r.status == "ok"
    assert "duty limits" in r.content
    assert "[remote]" in r.content
    assert r.pinned_rev == rev3


def test_render_resolved_uses_per_ref_rev(git_kb, hub_git):
    handle = HubHandle(root=hub_git["root"])
    ctx = _ctx(
        git_kb["rev1"], "demo-doc §1.1", "arinc-424 §5.3", hub_version=hub_git["rev1"]
    )
    results = resolve_refs(git_kb["kb"], ctx, hub=handle)
    text = render_resolved(results)
    assert f"@ {git_kb['rev1']}" in text
    assert f"@ {hub_git['rev1']}" in text
