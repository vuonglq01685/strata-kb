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
    # A real hub scaffolded via `kb init --kind hub` ships a `.gitignore`
    # covering `.kb-work/` (F-C17); publish() builds the search index there,
    # so without this the new F-C17 doctor check would (correctly) flag it.
    (hub_worktree / ".gitignore").write_text(".kb-work/\n", encoding="utf-8")
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


def test_doctor_warns_when_the_index_is_untracked_and_unignored(fed_hub):
    # warn_untracked_index=True models the hub maintainer's own checkout —
    # the only caller who can act on "add it to the hub's .gitignore"
    # (F-C17 review round 2, gate backcompat).
    from center_kb import doctor
    from center_kb.hub import HubHandle

    work = fed_hub / ".kb-work"
    work.mkdir(exist_ok=True)
    (work / "search.db").write_bytes(b"\x00")

    issues, _ = doctor.check_hub(
        fed_hub / ".kb", HubHandle(root=fed_hub), warn_untracked_index=True
    )
    assert any(".kb-work/" in i.message for i in issues)

    (fed_hub / ".gitignore").write_text(".kb-work/\n", encoding="utf-8")
    issues, _ = doctor.check_hub(
        fed_hub / ".kb", HubHandle(root=fed_hub), warn_untracked_index=True
    )
    assert not any(".kb-work/" in i.message for i in issues)


def test_doctor_does_not_warn_about_kb_work_on_the_child_path(fed_hub):
    # F-C17 review round 2, gate backcompat: child/dev/ba callers reach a hub
    # (or its cache clone) read-only via the `else` branch in cli.py, which
    # never passes warn_untracked_index — "add it to the hub's .gitignore"
    # is un-actionable there. Default (no flag) must stay silent even with
    # an untracked, unignored index present.
    from center_kb import doctor
    from center_kb.hub import HubHandle

    work = fed_hub / ".kb-work"
    work.mkdir(exist_ok=True)
    (work / "search.db").write_bytes(b"\x00")

    issues, _ = doctor.check_hub(fed_hub / ".kb", HubHandle(root=fed_hub))
    assert not any(".kb-work/" in i.message for i in issues)


def test_doctor_does_not_crash_on_a_non_utf8_gitignore(fed_hub):
    # F-C17 review round 2, Important: PowerShell 5.1's `echo x > .gitignore`
    # writes UTF-16LE. `check_hub` must not traceback reading a .gitignore it
    # doesn't own — an unreadable file counts as not-ignored.
    from center_kb import doctor
    from center_kb.hub import HubHandle

    work = fed_hub / ".kb-work"
    work.mkdir(exist_ok=True)
    (work / "search.db").write_bytes(b"\x00")
    (fed_hub / ".gitignore").write_bytes(".kb-work/\n".encode("utf-16"))

    issues, _ = doctor.check_hub(
        fed_hub / ".kb", HubHandle(root=fed_hub), warn_untracked_index=True
    )
    assert any(".kb-work/" in i.message for i in issues)
