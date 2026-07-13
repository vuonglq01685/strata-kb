from center_kb.doctor import check_hub
from center_kb.hub import HubHandle
from center_kb.publish import publish
from tests.conftest import make_fed_entry


def test_hub_unreachable_is_error(fixture_kb):
    issues, stale = check_hub(fixture_kb, None)
    assert stale is False
    assert issues and issues[0].level == "error"


def test_stale_cache_warns_and_flags(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    handle = HubHandle(root=hub_worktree, stale=True, age_seconds=90.0)
    issues, stale = check_hub(git_kb["kb"], handle, repo_id="demo-kb")
    assert stale is True
    assert any("stale" in i.message for i in issues)


def test_clean_state_after_publish_is_ok(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    issues, stale = check_hub(git_kb["kb"], HubHandle(root=hub_worktree), repo_id="demo-kb")
    assert issues == [] and stale is False


def test_unpublished_repo_warns(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree), repo_id="ghost-kb")
    assert any(i.level == "warning" and "kb publish" in i.message for i in issues)


def test_local_changes_since_publish_warn(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(l2.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree), repo_id="demo-kb")
    assert any(
        i.level == "warning" and "differs from the published snapshot" in i.message
        for i in issues
    )


def test_out_of_sync_aggregate_index_errors(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    (hub_worktree / "federation" / "index.yaml").write_text(
        "docs: []\n", encoding="utf-8"
    )
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree), repo_id="demo-kb")
    assert any(i.level == "error" and "kb reindex" in i.message for i in issues)


def test_missing_aggregate_index_errors(git_kb, hub_worktree):
    # hub_worktree has never been published to → no federation/index.yaml yet
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    assert any(i.level == "error" and "kb reindex" in i.message for i in issues)


def test_corrupt_aggregate_index_errors(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    (hub_worktree / "federation" / "index.yaml").write_text(
        "docs: [1, 2\n", encoding="utf-8"
    )
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree), repo_id="demo-kb")
    assert any(
        i.level == "error" and "corrupt" in i.message and "kb reindex" in i.message
        for i in issues
    )
    # multi-line ParserError text must be collapsed to a single scannable line
    assert all("\n" not in i.message for i in issues)


def test_old_format_entry_warns(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    legacy = hub_worktree / "federation" / "legacy-kb" / "manifests"
    legacy.mkdir(parents=True)
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    assert any("legacy-kb" in i.message and "kb publish" in i.message for i in issues)


def test_duplicate_doc_id_across_repos_warns(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    make_fed_entry(hub_worktree / "federation", "dup-kb", "demo-doc")
    from center_kb.federation import write_federation_index

    write_federation_index(hub_worktree / "federation")
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    assert any("appears in 2 federation repos" in i.message for i in issues)
