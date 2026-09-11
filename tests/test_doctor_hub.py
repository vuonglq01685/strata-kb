import hashlib
import subprocess

from center_kb.doctor import check_hub
from center_kb.hub import HubHandle
from center_kb.publish import publish
from tests.conftest import make_fed_entry

CRED = "https://x-access-token:ghs_SECRETTOKEN@github.com/org/kb-hub.git"


def test_hub_unreachable_is_error(fixture_kb):
    issues, stale = check_hub(fixture_kb, None)
    assert stale is False
    assert issues and issues[0].level == "error"


def test_credential_check_is_scoped_to_local_config(
    tmp_path, hub_worktree, git_kb, monkeypatch
):
    """M3: without --local, `git config --get-regexp` merges system/global
    scope too -- a remote.*.url the operator's OWN global gitconfig defines
    (unrelated to this hub clone) would be misreported as living in this
    clone's own .git/config."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global.gitconfig"))
    subprocess.run(
        ["git", "config", "--global", "remote.decoy.url", CRED], check=True
    )
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    assert not any("credential" in i.message for i in issues)


def test_old_git_warns_when_hub_ref_carries_a_credential(
    git_kb, hub_worktree, monkeypatch
):
    """M4: GIT_CONFIG_COUNT (how credential_env hands git a token without
    putting it in argv) needs git >= 2.31 -- on an older git the env is
    silently ignored and the operator gets git's own opaque auth error
    instead of a message naming the way forward."""
    from center_kb import gitio as gitio_mod

    real_run = gitio_mod._run

    def fake_run(root, *args):
        if args == ("--version",):
            return subprocess.CompletedProcess(
                args, 0, stdout="git version 2.20.1\n", stderr=""
            )
        return real_run(root, *args)

    monkeypatch.setattr(gitio_mod, "_run", fake_run)
    handle = HubHandle(root=hub_worktree, token="ghs_FAKE")
    issues, _ = check_hub(git_kb["kb"], handle)
    assert any("2.31" in i.message for i in issues)


def test_modern_git_does_not_warn_about_its_own_version(git_kb, hub_worktree):
    handle = HubHandle(root=hub_worktree, token="ghs_FAKE")
    issues, _ = check_hub(git_kb["kb"], handle)
    assert not any("2.31" in i.message for i in issues)


def test_no_credential_check_without_a_token_on_the_handle(git_kb, hub_worktree):
    """The version probe only matters when this hub ref actually carries a
    credential -- skip the extra `git --version` call otherwise."""
    handle = HubHandle(root=hub_worktree)
    issues, _ = check_hub(git_kb["kb"], handle)
    assert not any("2.31" in i.message for i in issues)


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


def test_doctor_warns_about_a_non_allowlisted_file_in_an_entry(
    hub_worktree, git_kb, run_git
):
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    (hub_worktree / "federation" / "child" / "config.yaml").write_text(
        "hub: leftover\n", encoding="utf-8", newline="\n"
    )
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    assert any("config.yaml" in i.message and i.level == "warning" for i in issues)
    # Item 7's second, milder finding (wave L1 brief) measured this exact
    # message: a republish from the source repo actually removes an
    # entry-level stray automatically (hashsync.diff_manifests/apply_sync),
    # so "delete them on the hub" overstates what the operator must do by
    # hand. Left UNCHANGED anyway -- this string is byte-for-byte
    # tests-gate/conftest.py's LEGACY_CONFIG_MIRROR_WARNING, a golden-
    # fixture regression assertion this wave does not own and must not
    # touch (out of scope: "anything under tests-gate/"). The slim-layout
    # sweep's parallel message (same finding, no such collision) was
    # corrected instead -- see test_doctor_still_calls_a_top_level... below
    # and the report for this decision in full.


def test_doctor_catches_a_stray_at_every_federation_level(hub_worktree, git_kb):
    """F-D9 finding 5: iter_entry_dirs only ever yields leaves, so the old
    check_hub loop never inspected federation/ itself or a namespace
    directory (e.g. federation/mid/ after a hub-to-hub publish) -- exactly
    where a mid hub's own top-level federation/ files land under
    _snapshot_federation, so the credential-leak case this warning exists
    for was the one it missed. Plants the reviewer's own three-level repro
    and requires all three to be caught, not just the leaf."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish
    from tests.conftest import make_fed_entry

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    fed = hub_worktree / "federation"
    (fed / "leaked-top.yaml").write_text("secret: top\n", encoding="utf-8")
    ns = fed / "mid"
    ns.mkdir()
    (ns / "leaked-ns.yaml").write_text("secret: ns\n", encoding="utf-8")
    make_fed_entry(ns, "repo-a", "doc-a")
    (ns / "repo-a" / "leaked-leaf.yaml").write_text("secret: leaf\n", encoding="utf-8")

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    warnings = [i.message for i in issues if i.level == "warning"]
    assert any("federation/" in m and "leaked-top.yaml" in m for m in warnings), warnings
    assert any("federation/mid" in m and "leaked-ns.yaml" in m for m in warnings), warnings
    assert any(
        "federation/mid/repo-a" in m and "leaked-leaf.yaml" in m for m in warnings
    ), warnings


def test_doctor_warns_about_fed_top_exclude_names_at_a_nested_level(
    hub_worktree, git_kb
):
    """M2 (routed, Wave F fix round 2): FED_TOP_EXCLUDE (index.yaml/
    registry.yaml/.gitkeep) is legitimate only directly under federation/
    itself -- the ns_strays sweep exempted those three names at EVERY
    namespace depth, so a same-named file dropped at a nested namespace
    directory (e.g. federation/<mid>/ after a hub-to-hub publish) went
    unreported. Not credential-bearing (the verdict calls it cosmetic), but
    exactly as suspicious there as any other stray. Uses registry.yaml, not
    index.yaml -- the latter also doubles as iter_entry_dirs'/
    iter_namespace_dirs' own leaf-marker filename, which would couple this
    probe to M3's fix instead of isolating M2's."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    mid = hub_worktree / "federation" / "mid"
    mid.mkdir()
    (mid / "registry.yaml").write_text("repos: {}\n", encoding="utf-8")

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    warnings = [i.message for i in issues if i.level == "warning"]
    assert any(
        "federation/mid" in m and "registry.yaml" in m for m in warnings
    ), warnings


def test_doctor_scans_inside_a_broken_federation_entry(hub_worktree, git_kb):
    """M3 (routed, the more consequential of the two Minors, Wave F fix
    round 2): a directory holding _meta.yaml with no index.yaml (a
    half-written entry -- exactly what an interrupted publish leaves behind)
    was skipped entirely by iter_namespace_dirs, mirroring iter_entry_dirs's
    own skip of it as an unusable entry -- so nothing below it, including a
    leaked credential, was ever scanned, and doctor raised no issue about
    the broken entry either to signal that a whole subtree had gone
    unscanned. Plants a leaked HUB_TOKEN directly inside the broken entry
    and a second stray one level further down, per the reviewer's repro."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    broken = hub_worktree / "federation" / "broken-mid"
    broken.mkdir()
    (broken / "_meta.yaml").write_text(
        "repo_id: broken-mid\nsource_commit: abc1234\n", encoding="utf-8"
    )
    (broken / ".env").write_text("HUB_TOKEN=ghp_leakedtoken\n", encoding="utf-8")
    deeper = broken / "sub"
    deeper.mkdir()
    (deeper / "stray.bin").write_text("x", encoding="utf-8")

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    warnings = [i.message for i in issues if i.level == "warning"]
    assert any(
        "federation/broken-mid" in m and ".env" in m for m in warnings
    ), warnings
    assert any(
        "federation/broken-mid/sub" in m and "stray.bin" in m for m in warnings
    ), warnings


def test_doctor_does_not_flag_a_legitimate_asset_inside_a_broken_entry(
    hub_worktree, git_kb
):
    """Important 2 (Wave G fix round 2 re-review), Ruling P35: since M3,
    iter_namespace_dirs walks INTO a broken entry (exactly one of
    _meta.yaml/index.yaml -- an interrupted publish), so it also recurses
    into that entry's <doc>/ and <doc>/assets/ directories, which ARE
    namespace directories by its predicate. check_hub's ns_strays sweep
    passed p.name, a bare basename, to pubgate.is_kb_artifact, whose asset
    rule (len(parts) >= 2 and parts[-2] == "assets") is unreachable with one
    path component -- so a legitimately published asset under a
    half-written entry was reported as a credential-bearing stray, telling
    the operator to delete real data and rotate a token that was never
    there. Measured on this exact repro: 1 warning before the fix, 0
    after."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish
    from tests.conftest import make_fed_entry

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    fed = hub_worktree / "federation"
    entry = make_fed_entry(fed, "half-written", "doc-a")
    (entry / "_meta.yaml").unlink()  # interrupted publish -- exactly one marker left
    assets = entry / "doc-a" / "assets"
    assets.mkdir()
    (assets / ("a" * 64 + ".png")).write_bytes(b"\x89PNG\r\n")

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    stray_warnings = [
        i.message
        for i in issues
        if i.level == "warning" and "would never write" in i.message
    ]
    assert stray_warnings == [], stray_warnings


def test_doctor_scans_a_valid_leaf_entry_nested_beneath_a_broken_one(
    hub_worktree, git_kb
):
    """Important 3 (Wave G fix round 2 re-review), Ruling P36: iter_entry_dirs
    keeps its stop at a broken entry and iter_namespace_dirs `continue`s at
    a leaf without sweeping it -- so a fully valid leaf entry nested two
    tiers beneath a broken outer entry was reached by neither sweep.
    Plants a leaked hub_token inside such a nested leaf, plus a control
    leaf at a healthy (non-nested) level carrying the byte-identical file --
    both must be caught. Also asserts doctor now raises an Issue naming the
    broken entry itself, so a skipped subtree is no longer silent."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish
    from tests.conftest import make_fed_entry

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    fed = hub_worktree / "federation"

    broken = fed / "broken-outer"
    broken.mkdir()
    (broken / "_meta.yaml").write_text(
        "repo_id: broken-outer\nsource_commit: abc1234\n", encoding="utf-8"
    )
    nested = make_fed_entry(broken, "leaf-a", "doc-a")
    (nested / "config.yaml").write_text(
        "hub_token: ghp_LEAFLEAK\n", encoding="utf-8"
    )

    make_fed_entry(fed, "healthy", "doc-b")
    (fed / "healthy" / "config.yaml").write_text(
        "hub_token: ghp_LEAFLEAK\n", encoding="utf-8"
    )

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    warnings = [i.message for i in issues if i.level == "warning"]
    assert any(
        "federation/broken-outer/leaf-a" in m and "config.yaml" in m
        for m in warnings
    ), warnings
    assert any(
        "federation/healthy" in m and "config.yaml" in m for m in warnings
    ), warnings
    assert any(
        "federation/broken-outer" in m
        and "missing" in m
        and "leaf-a" not in m
        for m in warnings
    ), warnings


def test_doctor_reports_strays_in_namespace_directories_regardless_of_name(
    hub_worktree, git_kb
):
    """N-1 (Wave G fix round 4 re-review, review-waveG-fix3-verdict.md): the
    round-3 fix passed is_kb_artifact a federation-relative path
    unconditionally, so a direct child of any non-leaf directory named
    "assets" put that directory's OWN basename in is_kb_artifact's
    parts[-2] slot -- exactly the slot its asset rule checks -- silently
    exempting a stray sitting directly inside it. pubgate.REPO_ID_RE
    reserves only Windows device names, so "assets" is a perfectly legal
    repo-id / plain directory name. Plants the byte-identical leaked file
    directly inside a namespace directory named "assets" and its sibling
    "notassets" -- P40 requires both reported alike, since neither
    directory is an entry (no _meta.yaml/index.yaml above the file at
    all, so no asset exemption can apply regardless of the directory's
    own name)."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    fed = hub_worktree / "federation"
    leak = "hub_token: ghp_ASSETSLEAK\n"
    (fed / "assets").mkdir()
    (fed / "assets" / "config.yaml").write_text(leak, encoding="utf-8")
    (fed / "notassets").mkdir()
    (fed / "notassets" / "config.yaml").write_text(leak, encoding="utf-8")

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    warnings = [i.message for i in issues if i.level == "warning"]
    assert any(
        "federation/assets" in m and "config.yaml" in m for m in warnings
    ), warnings
    assert any(
        "federation/notassets" in m and "config.yaml" in m for m in warnings
    ), warnings


def test_doctor_does_not_flag_a_legitimate_file_under_a_dot_named_namespace(
    hub_worktree, git_kb
):
    """N-7 (mirror of N-1, Wave G fix round 4): is_kb_artifact rejects a
    path if ANY segment starts with "." -- under the round-3 fix's
    federation-relative path, a legitimate .md file sitting directly
    inside a dot-named namespace directory picked up that directory's own
    name as a leading segment and was wrongly reported as a stray. P40:
    with no entry above the file, no asset exemption applies, but the
    dotfile check must not see the namespace directory's own name either
    -- only the file's own path within whatever entry (if any) is judging
    it. pubgate.REPO_ID_RE requires a leading alphanumeric so `kb publish`
    can never create a dot-named entry -- only a hand-made directory
    reaches this, low reach but the same argument as N-1."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    fed = hub_worktree / "federation"
    hidden = fed / ".hidden-ns"
    hidden.mkdir()
    (hidden / "readme.md").write_text("# notes\n", encoding="utf-8")

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    stray_warnings = [
        i.message
        for i in issues
        if i.level == "warning" and "would never write" in i.message
    ]
    assert stray_warnings == [], stray_warnings


def test_doctor_reports_a_stray_beside_manifests_inside_a_broken_entry(
    hub_worktree, git_kb
):
    """N-4 (Wave G fix round 4): every one of the three federation.py
    walkers `continue`s past a directory using the old slim layout (one
    holding manifests/), so a stray dropped directly beside manifests/ was
    invisible to every sweep, including when that slim directory sits
    inside a broken entry -- the exact shape that made the broken-entry
    Issue's "its own subtree is still scanned for strays" claim false.
    Plants a leaked hub_token directly beside manifests/, nested inside a
    broken entry, and asserts both the slim-layout Issue and the stray
    warning fire for that nested path."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    fed = hub_worktree / "federation"
    broken = fed / "broken-outer"
    broken.mkdir()
    (broken / "_meta.yaml").write_text(
        "repo_id: broken-outer\nsource_commit: abc1234\n", encoding="utf-8"
    )
    legacy = broken / "legacy"
    (legacy / "manifests").mkdir(parents=True)
    (legacy / "config.yaml").write_text(
        "hub_token: ghp_SLIMLEAK\n", encoding="utf-8"
    )

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    warnings = [i.message for i in issues if i.level == "warning"]
    assert any(
        "federation/broken-outer/legacy" in m
        and "config.yaml" in m
        and "would never write" in m
        for m in warnings
    ), warnings
    assert any(
        "federation/broken-outer/legacy" in m and "old slim layout" in m
        for m in warnings
    ), warnings


def test_doctor_reports_a_stray_beside_manifests_at_the_top_level(
    hub_worktree, git_kb
):
    """N-4, the pre-existing top-level gap the brief asked to be recorded
    separately: the same leak beside a top-level slim entry's manifests/
    was unreported before this round -- only the "uses the old slim
    layout" Issue fired, which says nothing about strays. Now closed by
    the same generalized sweep that handles the nested case above."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    fed = hub_worktree / "federation"
    legacy = fed / "legacy-top"
    (legacy / "manifests").mkdir(parents=True)
    (legacy / "config.yaml").write_text(
        "hub_token: ghp_SLIMLEAK\n", encoding="utf-8"
    )

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    warnings = [i.message for i in issues if i.level == "warning"]
    assert any(
        "federation/legacy-top" in m
        and "config.yaml" in m
        and "would never write" in m
        for m in warnings
    ), warnings
    # Not double-reported by the old depth-1-only check this loop replaced.
    slim_issues = [m for m in warnings if "old slim layout" in m]
    assert slim_issues == ["federation/legacy-top uses the old slim layout — "
                            "run `kb publish` from that repo to upgrade it"], slim_issues
    # Item 7's second, milder finding (wave L1 brief): "delete them on the
    # hub" used to be the whole remedy here too, but republishing from that
    # repo (which the slim-layout warning above already tells the operator
    # to do, to upgrade the entry) removes the stray automatically as part
    # of the same diff/apply_sync sync this digest mirrors -- no separate
    # manual step is needed for THAT half. "rotate any credential" must
    # still stand: git history keeps the bytes regardless of who deletes
    # the working-tree copy or when (ruling P66 / item 5's exact concern).
    # Unlike the leaf-entry sweep's identical-shaped message (left
    # unchanged: it is byte-for-byte tests-gate/conftest.py's
    # LEGACY_CONFIG_MIRROR_WARNING, out of this wave's scope to touch),
    # nothing in tests-gate/ depends on this message's exact wording.
    stray_msg = next(m for m in warnings if "config.yaml" in m and "would never write" in m)
    assert "delete them on the hub" not in stray_msg, stray_msg
    assert "republish" in stray_msg and "automatically" in stray_msg, stray_msg
    assert "rotate any credential" in stray_msg, stray_msg


def test_doctor_is_clean_after_publishing_a_kb_that_holds_a_config_yaml(
    git_kb, hub_worktree
):
    """Ruling P54 (release e2e run, 2026-09-11): every operator was told to
    `kb publish` again immediately after a successful publish, forever, by a
    warning they could never clear.

    `_kb_tree_digest` hashed every file except `_meta.yaml`, so it counted the
    local `.kb/config.yaml` that `pubgate.is_kb_artifact()` deliberately
    refuses to mirror (this batch's own credential-leak fix). The two trees
    can then never agree: local has `config.yaml`, the published entry never
    will, and the advice names the command that just ran.

    `kb init` writes `.kb/config.yaml`, so this is every real KB -- but
    `fixture_kb` has none, which is exactly why the whole unit suite stayed
    green while `tests-gate/e2e/test_journey.py::test_doctor_is_clean_after_
    publish` went red. Plant one here so the unit level can see it too.
    """
    (hub_worktree / ".gitignore").write_text(".kb-work/\n", encoding="utf-8")
    (git_kb["kb"] / "config.yaml").write_text(
        "kind: child\nhub: ../hub\n", encoding="utf-8"
    )
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")

    issues, stale = check_hub(
        git_kb["kb"], HubHandle(root=hub_worktree), repo_id="demo-kb"
    )
    assert [i.message for i in issues] == []
    assert stale is False


def test_doctor_does_not_call_an_assets_dir_inside_an_entry_a_slim_entry(
    hub_worktree, git_kb
):
    """Minor 1 (Wave G fix round 4 re-review): the extended slim sweep
    treated ANY direct child of a namespace/broken-entry directory holding
    `manifests/` as a slim ENTRY ROOT, at any depth -- so a document's own
    `assets/` directory that happened to contain a `manifests/`
    subdirectory was mislabelled as one, and because the stray sweep then
    resolved paths relative to that `assets/` directory itself, the
    legitimate `pic.png` sitting in it lost exactly the asset exemption
    ruling P40 had just restored. Two false positives from one
    misclassification; neither happened before round 4.

    Ruling P39 binds: an entry is what `federation.iter_entry_dirs` yields,
    and a directory that merely LOOKS like one to a structural heuristic is
    not one. A directory named `assets` sitting INSIDE an entry is an asset
    directory by `pubgate.is_kb_artifact`'s own rule (`parts[-2] ==
    "assets"` makes its direct children artefacts), so it can never be an
    entry root -- see the sibling test below for the case where there is no
    entry above it and it still can be."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    fed = hub_worktree / "federation"
    broken = fed / "broken-outer"
    broken.mkdir()
    (broken / "_meta.yaml").write_text(
        "repo_id: broken-outer\nsource_commit: abc1234\n", encoding="utf-8"
    )
    assets = broken / "doc-a" / "assets"
    (assets / "manifests").mkdir(parents=True)
    (assets / "manifests" / "inner.png").write_bytes(b"PNG")
    (assets / "pic.png").write_bytes(b"PNG")

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    warnings = [i.message for i in issues if i.level == "warning"]
    assert not [m for m in warnings if "assets" in m and "old slim layout" in m], (
        warnings
    )
    assert not [m for m in warnings if "pic.png" in m], warnings


def test_doctor_still_calls_a_top_level_assets_dir_with_manifests_a_slim_entry(
    hub_worktree, git_kb
):
    """The other direction of Minor 1, so the containment cannot be widened
    into a blanket "never call anything named assets an entry". `assets` is
    a legal repo-id (`pubgate.REPO_ID_RE` accepts it), and at
    federation/assets there is no entry above the directory -- P40's
    "assets only exist inside an entry" is precisely what makes it an entry
    root here and an asset directory in the test above."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    fed = hub_worktree / "federation"
    legacy = fed / "assets"
    (legacy / "manifests").mkdir(parents=True)
    (legacy / "config.yaml").write_text(
        "hub_token: ghp_SLIMLEAK\n", encoding="utf-8"
    )

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    warnings = [i.message for i in issues if i.level == "warning"]
    assert any(
        "federation/assets" in m and "old slim layout" in m for m in warnings
    ), warnings
    assert any(
        "federation/assets" in m and "config.yaml" in m and "would never write" in m
        for m in warnings
    ), warnings


def test_doctor_still_sees_drift_in_a_published_asset_file(git_kb, hub_worktree):
    """The path-convention half of ruling P54, pinned separately.

    `is_kb_artifact`'s asset rule is `len(parts) >= 2 and parts[-2] ==
    "assets"`, so the path handed to it has to be relative to the root the
    two sides are compared at -- the `.kb/` directory locally, the
    `federation/<rid>` entry on the hub. That is ruling P40's lesson, and
    item 0's brief says applying P54 with the wrong root reproduces P40 in
    a new place: pass a bare basename and every asset drops out of BOTH
    digests, so a changed asset becomes invisible to the drift check while
    the config.yaml test above stays green.
    """
    (hub_worktree / ".gitignore").write_text(".kb-work/\n", encoding="utf-8")
    assets = git_kb["kb"] / "demo-doc" / "assets"
    assets.mkdir()
    pic = assets / f"{'a' * 64}.png"
    pic.write_bytes(b"PNG-v1")
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")

    issues, _ = check_hub(
        git_kb["kb"], HubHandle(root=hub_worktree), repo_id="demo-kb"
    )
    assert [i.message for i in issues] == []

    pic.write_bytes(b"PNG-v2-different-bytes")
    issues, _ = check_hub(
        git_kb["kb"], HubHandle(root=hub_worktree), repo_id="demo-kb"
    )
    assert any(
        "differs from the published snapshot" in i.message for i in issues
    ), [i.message for i in issues]


def test_doctor_is_not_permanently_drifted_by_a_diverted_asset(git_kb, hub_worktree):
    """Item 7 (coordinator follow-up, wave L1 brief): ruling P54 was only
    HALF closed. publish._snapshot folds
    assetstore.synthesized_asset_entries(dest) into its destination
    manifest before diffing (dest_man.update(...)), so a diverted asset --
    real bytes gone from federation/<rid>/, only `_assets.yaml` naming it
    -- compares equal to the local .kb/ that still holds the real bytes
    on disk. _kb_tree_digest did not do the same: it only ever walked
    federation/<rid>/'s REAL files, which no longer include a diverted
    asset at all, so the hub-side digest permanently differed from the
    local one on any hub with an asset store. Reproduced with
    publish._snapshot + assetstore.MemoryStore -- the same test double
    test_publish.py already uses for this exact divert path (no real S3
    is reachable from this sandbox, and this batch's rule is no mocking
    library; MemoryStore is a real, if in-memory, implementation) -- since
    top-level publish() takes no store override and always resolves one
    from the hub's own config.

    Before this fix: `kb doctor: OK` never printed again for this repo --
    a warning ("local .kb differs from the published snapshot ... — run
    `kb publish`") that immediately follows the very publish it tells the
    operator to run, forever, on any hub with an asset store configured.
    """
    from center_kb import assetstore, federation
    from center_kb import publish as publish_mod

    (hub_worktree / ".kb").mkdir(exist_ok=True)
    (hub_worktree / ".kb" / "config.yaml").write_text(
        "kind: hub\nasset_store:\n  mode: s3\n  bucket: b\n", encoding="utf-8"
    )
    assets = git_kb["kb"] / "demo-doc" / "assets"
    assets.mkdir()
    sha = hashlib.sha256(b"PNGBYTES").hexdigest()
    (assets / f"{sha}.png").write_bytes(b"PNGBYTES")

    handle = HubHandle(root=hub_worktree)
    store = assetstore.MemoryStore()
    publish_mod._snapshot(git_kb["kb"], handle, "demo-kb", "c0ffee", store=store)
    # _snapshot alone does not write the hub's AGGREGATE federation/index.yaml
    # (a separate step in publish()) -- write it so the unrelated "federation/
    # index.yaml is missing" issue doesn't muddy this test's one assertion.
    federation.write_federation_index(handle.federation_dir)
    dest_pic = hub_worktree / "federation" / "demo-kb" / "demo-doc" / "assets" / f"{sha}.png"
    # sanity: the divert actually happened (real bytes gone from the hub
    # tree), or the rest of this test would be vacuous
    assert not dest_pic.exists()
    assert store.get(f"{sha}.png") == b"PNGBYTES"

    issues, _ = check_hub(git_kb["kb"], handle, repo_id="demo-kb")
    assert issues == [], [i.message for i in issues]


def test_doctor_resolves_an_asset_against_the_INNERMOST_broken_entry(
    hub_worktree, git_kb
):
    """Ruling P40 says the path handed to `is_kb_artifact` is relative to
    the entry whose artefacts are being judged -- for nested broken
    entries that is the INNERMOST one, and `_enclosing_entry`'s
    longest-prefix key is what makes it so. Nothing pinned that key: it
    survives being replaced with "take the first match" because
    `is_kb_artifact`'s asset rule is depth-independent, so for most shapes
    inner- and outer-relative paths agree.

    They disagree when the inner entry is dot-named -- N-7's shape, one
    level down. Resolved against the inner entry the asset is
    `doc-a/assets/pic.png` and exempt; resolved against the outer one it is
    `.hidden-inner/doc-a/assets/pic.png`, whose leading-dot segment trips
    `is_kb_artifact`'s dotfile rule, and a legitimate asset is reported as
    a leaked stray. Round 5 made `_enclosing_entry` shared by two loops, so
    it is pinned here rather than left to the next refactor."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    fed = hub_worktree / "federation"
    outer = fed / "broken-outer"
    outer.mkdir()
    (outer / "_meta.yaml").write_text(
        "repo_id: broken-outer\nsource_commit: abc1234\n", encoding="utf-8"
    )
    inner = outer / ".hidden-inner"
    inner.mkdir()
    (inner / "_meta.yaml").write_text(
        "repo_id: hidden-inner\nsource_commit: abc5678\n", encoding="utf-8"
    )
    assets = inner / "doc-a" / "assets"
    assets.mkdir(parents=True)
    (assets / "pic.png").write_bytes(b"PNG")
    # and a real stray in the same inner entry, so the sweep is proven to
    # be reaching this subtree at all rather than passing by doing nothing.
    (inner / "config.yaml").write_text("hub_token: ghp_LEAK\n", encoding="utf-8")

    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    warnings = [i.message for i in issues if i.level == "warning"]
    assert not [m for m in warnings if "pic.png" in m], warnings
    assert any("config.yaml" in m and "would never write" in m for m in warnings), (
        warnings
    )
