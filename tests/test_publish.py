import hashlib
import os
import subprocess
import time
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from center_kb import assetstore, ghio, gitio, models, pubgate
from center_kb.federation import FederationMeta, write_federation_index
from center_kb.hub import HubHandle
from center_kb.publish import (
    PublishError,
    _dest_record_assets,
    _neutralize_excludes,
    publish,
    unreviewed_sections,
)
from tests.conftest import make_fed_entry
from tests.test_assetstore import make_dangling_link, remove_dangling_link


def test_neutralize_excludes_does_not_inherit_stdin(tmp_path, monkeypatch):
    """Every git subprocess must be shielded from inheriting a stdin that may
    be a protocol channel (e.g. the MCP server's stdio JSON-RPC pipe) — this
    is the property gitio.py's git subprocess calls already hold via
    stdin=subprocess.DEVNULL. _neutralize_excludes' `git config` call must
    hold it too.
    """
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("center_kb.publish.subprocess.run", fake_run)

    _neutralize_excludes(tmp_path)

    assert captured.get("stdin") is subprocess.DEVNULL


def test_unreviewed_sections_counts_non_reviewed_rows(git_kb):
    assert unreviewed_sections(git_kb["kb"]) == (2, 1)
    mpath = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    m.sections[0].status = "reviewed"
    models.save_yaml_model(mpath, m)
    assert unreviewed_sections(git_kb["kb"]) == (1, 1)
    # "pending" (not just "summarized") counts as unreviewed too
    m = models.load_yaml_model(mpath, models.Manifest)
    m.sections[1].status = "pending"
    models.save_yaml_model(mpath, m)
    assert unreviewed_sections(git_kb["kb"]) == (1, 1)


def test_publish_direct_refreshes_search_db(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb", mode="direct")
    assert (hub_worktree / ".kb-work" / "search.db").exists()


def test_direct_publish_mirrors_full_tree(git_kb, hub_worktree):
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert report.mode == "direct"
    assert report.n_docs == 1
    entry = hub_worktree / "federation" / "demo-kb"
    assert (entry / "index.yaml").exists()
    assert (entry / "demo-doc" / "_manifest.yaml").exists()
    assert (entry / "demo-doc" / "ch1-records.md").exists()       # L2
    assert (entry / "demo-doc" / "ch1-records.raw.md").exists()   # L3
    meta = models.load_yaml_model(entry / "_meta.yaml", FederationMeta)
    assert meta.repo_id == "demo-kb"
    assert meta.source_commit == report.source_commit


def test_direct_publish_regenerates_aggregate_index(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    idx = models.load_yaml_model(
        hub_worktree / "federation" / "index.yaml", models.FederationIndex
    )
    assert [(e.repo_id, e.doc_id) for e in idx.docs] == [("demo-kb", "demo-doc")]


def test_direct_publish_commits_on_hub(git_kb, hub_worktree, run_git):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    log = run_git(hub_worktree, "log", "--oneline")
    assert "publish: demo-kb" in log


def test_direct_publish_threads_the_hub_token_into_the_push(
    git_kb, tmp_path, run_git, monkeypatch
):
    """C1 (call-site half): publish()'s push-retry loop must pass
    handle.token through to gitio.push -- reverting just the call site
    (gitio.push(handle.root) instead of gitio.push(handle.root,
    handle.token)) is a one-line regression the gitio-level credential
    tests, which call gitio.push directly, cannot see."""
    origin = tmp_path / "hub-origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    seed = tmp_path / "hub-seed"
    (seed / ".kb").mkdir(parents=True)
    (seed / "federation").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")
    (seed / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(tmp_path, "init", str(seed))
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "hub v0")
    run_git(seed, "remote", "add", "origin", str(origin))
    run_git(seed, "push", "-u", "origin", "HEAD")

    # hub_ref carries a credential for a host that is never actually
    # dereferenced -- the cache is pre-seeded (below) with a real local
    # origin, so only cache_key()/the extracted token need to line up with
    # what resolve_hub computes.
    fake_hub_ref = "https://x-access-token:ghs_FAKETOKEN@example.invalid/hub.git"
    stripped = "https://example.invalid/hub.git"
    cache_base = tmp_path / "cache"
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(cache_base))
    key = hashlib.sha1(stripped.encode("utf-8")).hexdigest()[:12]
    cache = cache_base / key
    cache_base.mkdir(parents=True, exist_ok=True)
    run_git(tmp_path, "clone", str(origin), str(cache))
    run_git(cache, "config", "core.autocrlf", "false")  # a "healthy" cache
    run_git(cache, "config", "user.name", "test")
    run_git(cache, "config", "user.email", "test@test.local")
    (cache_base / f"{key}.last-pull").write_text(str(time.time()), encoding="utf-8")

    calls: list[dict] = []
    real_run = gitio.subprocess.run

    def spy(cmd, **kwargs):
        calls.append({"argv": list(cmd), "env": kwargs.get("env")})
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(gitio.subprocess, "run", spy)

    publish(git_kb["kb"], fake_hub_ref, repo_id="child", mode="direct")

    push_calls = [
        c for c in calls
        if c["argv"][:2] == ["git", "push"] and "origin" in c["argv"] and "HEAD" in c["argv"]
    ]
    assert push_calls, "publish() never pushed"
    env = push_calls[0]["env"]
    assert env is not None, "the push carried no credential env at all"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert "ghs_FAKETOKEN" not in push_calls[0]["argv"]


def test_republish_replaces_entry_wholesale(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    stray = hub_worktree / "federation" / "demo-kb" / "stale-doc"
    stray.mkdir()
    (stray / "x.md").write_text("stale", encoding="utf-8")
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert not stray.exists()


def test_invalid_repo_id_rejected(git_kb, hub_worktree):
    with pytest.raises(pubgate.GateError):
        publish(git_kb["kb"], str(hub_worktree), repo_id="../evil")


def test_unreachable_hub_raises(git_kb, tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    with pytest.raises(PublishError):
        publish(git_kb["kb"], str(tmp_path / "does-not-exist"))


def test_auto_mode_is_direct_for_local_path_hub(git_kb, hub_worktree, monkeypatch):
    # a dev machine may have a real gh -- stub can_open_pr (not just
    # gh_available) so this stays hermetic even if _can_pr's has_remote=False
    # short-circuit (see test below) ever stops covering this path.
    monkeypatch.setattr(ghio, "can_open_pr", lambda root: True)
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert report.mode == "direct"


def test_direct_publish_never_consults_gh_for_a_hub_with_no_remote(
    git_kb, hub_worktree, monkeypatch
):
    # decide_mode reads can_pr only for a non-direct mode against a hub with
    # a remote (pubgate.py:176-199) -- but can_open_pr used to be evaluated
    # eagerly as a call argument on every publish, so a hung `gh` (captive
    # portal, stalled proxy, slow GHE) blocked a purely local publish
    # indefinitely. publish._can_pr must short-circuit before ever asking.
    def _must_not_be_called(root):
        raise AssertionError("gh must not be consulted")

    monkeypatch.setattr(ghio, "can_open_pr", _must_not_be_called)
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb", mode="direct")
    assert report.mode == "direct"


def test_pr_mode_pushes_branch_and_opens_pr(git_kb, hub_with_origin, monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(ghio, "gh_available", lambda: True)
    monkeypatch.setattr(ghio, "can_open_pr", lambda root: True)
    monkeypatch.setattr(ghio, "pr_url_for_branch", lambda root, branch: "")

    def fake_create(root, branch, title, body):
        calls["branch"] = branch
        calls["title"] = title
        return "https://github.com/org/hub/pull/7"

    monkeypatch.setattr(ghio, "create_pr", fake_create)
    report = publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="pr")
    assert report.mode == "pr"
    assert report.pr_url.endswith("/pull/7")
    assert calls["branch"] == "publish/demo-kb"
    # the hub worktree returns to its original branch, main gets no publish commit
    assert not (hub_with_origin / "federation" / "demo-kb").exists()
    assert gitio.current_branch(hub_with_origin) in ("main", "master")
    assert not (hub_with_origin / ".kb-work" / "search.db").exists()


def test_pr_mode_updates_existing_pr_without_creating(git_kb, hub_with_origin, monkeypatch):
    monkeypatch.setattr(ghio, "gh_available", lambda: True)
    monkeypatch.setattr(ghio, "can_open_pr", lambda root: True)
    monkeypatch.setattr(
        ghio, "pr_url_for_branch",
        lambda root, branch: "https://github.com/org/hub/pull/7",
    )

    def boom(root, branch, title, body):
        raise AssertionError("create_pr must not be called when a PR is open")

    monkeypatch.setattr(ghio, "create_pr", boom)
    report = publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="pr")
    assert report.pr_url.endswith("/pull/7")


def test_pr_mode_without_gh_raises_with_two_exits(git_kb, hub_with_origin, monkeypatch):
    monkeypatch.setattr(ghio, "gh_available", lambda: False)
    with pytest.raises(pubgate.GateError) as exc:
        publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="pr")
    assert "gh" in str(exc.value) and "--direct" in str(exc.value)


def test_publish_twice_no_change_is_noop(git_kb, hub_worktree, run_git):
    """2nd publish with no source change: no new hub commit, _meta.yaml unchanged."""
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    meta_path = hub_worktree / "federation" / "demo-kb" / "_meta.yaml"
    meta_before = meta_path.read_text(encoding="utf-8")
    log_before = run_git(hub_worktree, "log", "--oneline")

    time.sleep(1.1)  # published_at has second resolution — cross a tick so a
    # timestamp-only rewrite (old rmtree+copytree behavior) would be visible
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")

    assert meta_path.read_text(encoding="utf-8") == meta_before
    log_after = run_git(hub_worktree, "log", "--oneline")
    assert log_after == log_before
    assert report.n_docs >= 0  # report still returns normally


def test_publish_removed_file_deleted_on_hub(git_kb, hub_worktree):
    extra = git_kb["kb"] / "stray.md"
    extra.write_text("temp", encoding="utf-8")
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert (hub_worktree / "federation" / "demo-kb" / "stray.md").exists()

    extra.unlink()
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert not (hub_worktree / "federation" / "demo-kb" / "stray.md").exists()


def test_warn_legacy_ids_flags_xn_sections(tmp_path, caplog):
    import logging

    from center_kb import models, publish

    doc_dir = tmp_path / "kb" / "old-doc"
    doc_dir.mkdir(parents=True)
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="old-doc",
            title="Old Doc",
            sections=[
                models.SectionEntry(id="5.6", title="Real", file="ch5"),
                models.SectionEntry(id="5.6-x74", title="Commentary", file="ch5"),
            ],
        ),
    )
    with caplog.at_level(logging.WARNING, logger="center_kb.publish"):
        hits = publish.warn_legacy_ids(tmp_path / "kb")
    assert hits == ["old-doc §5.6-x74"]
    assert any("re-ingest" in r.message for r in caplog.records)


def test_warn_legacy_ids_clean_kb_silent(tmp_path, caplog):
    import logging

    from center_kb import models, publish

    doc_dir = tmp_path / "kb" / "clean-doc"
    doc_dir.mkdir(parents=True)
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="clean-doc",
            title="Clean",
            sections=[models.SectionEntry(id="5.6-commentary", title="C", file="ch5")],
        ),
    )
    with caplog.at_level(logging.WARNING, logger="center_kb.publish"):
        hits = publish.warn_legacy_ids(tmp_path / "kb")
    assert hits == []
    assert not caplog.records


def test_direct_push_race_reindexes_after_rebase(git_kb, hub_with_origin, run_git, tmp_path):
    rival = tmp_path / "rival-clone"
    run_git(tmp_path, "clone", str(tmp_path / "hub-origin.git"), str(rival))
    run_git(rival, "config", "user.name", "t")
    run_git(rival, "config", "user.email", "t@t")
    make_fed_entry(rival / "federation", "other-kb", "other-doc")
    write_federation_index(rival / "federation")
    run_git(rival, "add", "-A")
    run_git(rival, "commit", "-m", "publish: other-kb")
    run_git(rival, "push")

    publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="direct")

    idx = models.load_yaml_model(
        hub_with_origin / "federation" / "index.yaml", models.FederationIndex
    )
    assert {(e.repo_id, e.doc_id) for e in idx.docs} == {
        ("demo-kb", "demo-doc"),
        ("other-kb", "other-doc"),
    }


# Real content hash: spec A guarantees filename sha == sha256(bytes) — the
# no-op test below depends on this invariant (synthesized_asset_entries()
# derives its "hash" from the filename, not the bytes).
SHA_Y = hashlib.sha256(b"YBYTES").hexdigest()


def _child_kb_with_asset(tmp_path) -> Path:
    """A git-backed child .kb/ (doc1, one section) plus a content-addressed
    image asset under doc1/assets/ — for _snapshot() divert tests.

    _snapshot() only needs `gitio.git_root()` to resolve (for the
    source_url default) — a bare `git init` with no commits is enough.
    """
    root = tmp_path / "child"
    kb = root / ".kb"
    doc_dir = kb / "doc1"
    doc_dir.mkdir(parents=True)
    (doc_dir / "ch1.md").write_text("## 1.1 Doc One\n\nBody text.\n", encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="doc1",
            title="Doc One",
            sections=[
                models.SectionEntry(
                    id="1.1", title="Doc One", summary="s",
                    status="summarized", file="ch1",
                )
            ],
        ),
    )
    models.save_yaml_model(
        kb / "index.yaml",
        models.KBIndex(
            docs=[models.IndexEntry(id="doc1", title="Doc One", summary="s")]
        ),
    )
    assets_dir = doc_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / f"{SHA_Y}.png").write_bytes(b"YBYTES")
    subprocess.run(
        ["git", "init"], cwd=root, capture_output=True, text=True, check=True
    )
    return kb


def test_snapshot_diverts_assets_and_keeps_child_intact(tmp_path, hub_worktree):
    from center_kb import publish

    kb_abs = _child_kb_with_asset(tmp_path)
    handle = HubHandle(root=hub_worktree)
    store = assetstore.MemoryStore()
    n_docs, changed, _skipped = publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=store)
    assert changed
    dest = handle.federation_dir / "rid-a"
    assert store.get(f"{SHA_Y}.png") == b"YBYTES"
    assert not (dest / "doc1" / "assets" / f"{SHA_Y}.png").exists()
    rec = models.load_yaml_model(dest / "_assets.yaml", models.AssetsRecord)
    assert rec.assets == [f"doc1/assets/{SHA_Y}.png"]
    # the child's live .kb is untouched
    assert (kb_abs / "doc1" / "assets" / f"{SHA_Y}.png").exists()


def test_snapshot_second_publish_is_noop_with_store(tmp_path, hub_worktree):
    from center_kb import publish

    kb_abs = _child_kb_with_asset(tmp_path)
    handle = HubHandle(root=hub_worktree)
    store = assetstore.MemoryStore()
    publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=store)
    n_docs, changed, _skipped = publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=store)
    assert not changed  # synthesized entries make diverted assets look present


def test_snapshot_upload_failure_raises_before_any_write_is_kept(tmp_path, hub_worktree):
    from center_kb import publish

    kb_abs = _child_kb_with_asset(tmp_path)
    handle = HubHandle(root=hub_worktree)

    class _FailingStore(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    with pytest.raises(assetstore.AssetStoreError):
        publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=_FailingStore())


def test_snapshot_store_outage_then_retry_never_commits_binaries(tmp_path, hub_worktree):
    """Regression: a store outage mid-divert must not leave un-diverted asset
    bytes sitting in the hub clone's working tree. Left dirty, a retry with a
    healthy store would see dest's manifest already match the child's (bytes
    already copied by apply_sync before the outage) and early-return
    "unchanged" *before* ever reaching divert again -- so _publish_direct /
    _publish_pr would git-add + commit the leftover PNG straight into hub git.
    """
    from center_kb import publish

    kb_abs = _child_kb_with_asset(tmp_path)
    handle = HubHandle(root=hub_worktree)

    class _FailingStore(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    # 1st attempt: every put fails
    with pytest.raises(assetstore.AssetStoreError):
        publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=_FailingStore())

    # working tree restored: no leftover asset bytes, porcelain clean under federation
    status = gitio._run(
        handle.root, "status", "--porcelain", "--", "federation"
    ).stdout.strip()
    assert status == ""

    # 2nd attempt with a healthy store: diverts for real
    store = assetstore.MemoryStore()
    n_docs, changed, _skipped = publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=store)
    assert changed
    assert store.get(f"{SHA_Y}.png") == b"YBYTES"  # asset uploaded
    dest = handle.federation_dir / "rid-a"
    assert not list(dest.rglob("*.png"))  # no binaries left in the tree


def test_report_distinguishes_no_remote_from_nothing_to_push(
    git_kb, hub_with_origin, hub_worktree
):
    first = publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="direct")
    assert first.remote is True and first.pushed is True

    second = publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="direct")
    assert second.remote is True and second.pushed is False


def test_report_marks_a_hub_without_a_remote(git_kb, hub_worktree, run_git, tmp_path):
    """F-D9 finding 7 bullet 5: `report.remote is False` alone passes even if
    PublishReport.remote's `has_remote=` wiring were deleted entirely --
    False is also the dataclass default (publish.py:39). Compare against an
    independent hub that genuinely has a remote so the assertion
    discriminates real detection from "always reports the default"."""
    import shutil

    no_remote = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb", mode="direct")
    assert no_remote.remote is False

    hub2 = tmp_path / "kb-hub-with-remote"
    shutil.copytree(hub_worktree, hub2)
    origin = tmp_path / "hub2-origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(hub2, "remote", "add", "origin", str(origin))
    run_git(hub2, "push", "-u", "origin", "HEAD")

    with_remote = publish(git_kb["kb"], str(hub2), repo_id="demo-kb", mode="direct")
    assert with_remote.remote is True


def test_a_no_change_publish_reports_the_commit_actually_snapshotted(
    git_kb, hub_worktree, run_git
):
    """_snapshot leaves _meta.yaml alone when nothing changed, so on a second
    publish after an unrelated commit the CLI was printing the source repo's
    new HEAD next to a hub entry that still records the old one."""
    from center_kb import gitio

    first = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb", mode="direct")
    (git_kb["root"] / "README.md").write_text(
        "unrelated\n", encoding="utf-8", newline="\n"
    )
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "child: unrelated change outside .kb/")
    second = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb", mode="direct")

    assert second.source_commit == first.source_commit
    assert second.source_commit != gitio.head_commit(git_kb["root"])


def test_cli_does_not_claim_a_hub_has_no_remote_when_it_does(
    git_kb, hub_with_origin
):
    from typer.testing import CliRunner

    from center_kb.cli import app

    runner = CliRunner()
    runner.invoke(
        app,
        ["publish", "--hub", str(hub_with_origin), "--repo-id", "demo-kb",
         "--kb-dir", str(git_kb["kb"]), "--direct"],
    )
    result = runner.invoke(
        app,
        ["publish", "--hub", str(hub_with_origin), "--repo-id", "demo-kb",
         "--kb-dir", str(git_kb["kb"]), "--direct"],
    )
    assert "hub has no remote" not in result.output
    assert "nothing to push" in result.output


# --- publish._dest_record_assets, the DESTINATION-side reader --------------
#
# Wave I-1 round 4: round 3 grew this function two new guards and a mutation
# run found one of them inert -- `if False and record_path.exists():` left 38
# tests passing, because nothing in the tree ever put a non-regular file at a
# DESTINATION record path, and the function had no direct unit test at all.
# These are that test, plus the two checks this round adds.


LINK_CLAUSE = (
    "is not a regular file -- it may be a directory, or a link whose "
    "target is gone"
)


def _dest_record(tmp_path: Path, assets: list[str]) -> Path:
    record_path = tmp_path / assetstore.RECORD_NAME
    models.save_yaml_model(record_path, models.AssetsRecord(assets=assets))
    return record_path


def test_dest_record_assets_raises_on_a_record_truncated_mid_path(tmp_path):
    """The Critical's first door, at the unit level. models.save_yaml_model
    truncates before writing, so an interrupted publish leaves a record cut
    mid-entry: still valid YAML, still a non-empty list, but its last name is
    `doc/assets/<partial-hex>` rather than `<sha256>.(png|webp)`. This reader
    accepted it while assetstore.load_record -- the reader
    assetstore.divert_and_record uses on the SAME file moments later --
    rejected it, and that disagreement is what deleted the record."""
    sha = hashlib.sha256(b"door-a").hexdigest()
    record_path = _dest_record(tmp_path, [f"doc-a/assets/{sha}.png"])
    full = record_path.read_bytes()
    record_path.write_bytes(full[: len(full) - 14])  # mid-hex, not a boundary
    with pytest.raises(OSError, match="not a content-addressed asset name"):
        _dest_record_assets(record_path)


def test_dest_record_assets_raises_on_a_record_missing_its_trailing_newline(tmp_path):
    """The Critical's second door. Every record this codebase writes ends in
    a newline (yaml.safe_dump always terminates one), so a record that does
    not is a truncated write even when every name it still contains is
    valid -- and pre-fix this reader accepted it and the record was deleted
    on the strength of a read that had in fact failed."""
    sha = hashlib.sha256(b"door-b").hexdigest()
    record_path = _dest_record(tmp_path, [f"doc-a/assets/{sha}.png"])
    full = record_path.read_bytes()
    assert full.endswith(b"\n")  # sanity: a real write always does
    record_path.write_bytes(full[:-1])
    with pytest.raises(OSError, match="does not end with a trailing newline"):
        _dest_record_assets(record_path)


def test_dest_record_assets_raises_on_a_dangling_link_at_the_record_path(tmp_path):
    """Minor 4 (wave I-1 round 4), the destination half. See
    tests/test_assetstore.py's matching test for the measurement; both
    readers followed the link, read exists()=False, and answered "absent"."""
    record_path = tmp_path / assetstore.RECORD_NAME
    kind = make_dangling_link(record_path)
    if kind is None:  # pragma: no cover - depends on the host's privileges
        pytest.skip("this machine can create neither a symlink nor a junction")
    try:
        assert not record_path.exists()
        assert os.path.lexists(record_path)
        # the whole clause, not just its first half -- wave I-1 round 5,
        # Minor 1: round 4 gave load_record's message "or a link whose target
        # is gone" and left this one saying only "is not a regular file", and
        # neither half was pinned, so the two readers described the same
        # corruption two different ways with nothing to notice.
        with pytest.raises(OSError) as excinfo:
            _dest_record_assets(record_path)
        msg = str(excinfo.value)
        # spelled out, NOT `not_a_regular_file_clause(record_path) in msg` --
        # that moves with the mutation and passes for any clause at all
        assert LINK_CLAUSE in msg
        # and both readers go through the one helper, so they cannot drift
        assert assetstore.not_a_regular_file_clause(record_path) in msg
    finally:
        remove_dangling_link(record_path)


def test_dest_record_assets_raises_on_a_directory_at_the_record_path(tmp_path):
    """Minor 1 (wave I-1 round 4): round 3's not-a-regular-file guard on this
    side shipped with no test at all -- `if False and record_path.exists():`
    left the whole federation suite green. The behaviour was right; the proof
    was missing. (The reachable end-to-end shape is pinned separately in
    tests/test_federation_nested.py: apply_sync's empty-directory prune
    removes a directory-shaped record before the reconcile pass whenever the
    plain file diff is non-empty, so only a publish with an empty plain diff
    actually reaches this guard.)"""
    record_path = tmp_path / assetstore.RECORD_NAME
    record_path.mkdir()
    (record_path / "stray.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(OSError, match="is not a regular file"):
        _dest_record_assets(record_path)


@pytest.mark.parametrize(
    "asset",
    [
        "doc-a/assets/{sha}.png",
        "doc-a/assets/{sha}.webp",
        "tài-liệu/assets/{sha}.png",
        "a/b/c/d/e/f/g/h/i/j/assets/{sha}.png",
        "./doc-a/assets/{sha}.png",
        "C:/kb/doc-a/assets/{sha}.png",
        "{sha}.png",
    ],
    ids=[
        "png", "webp", "unicode-doc-id", "deeply-nested",
        "dot-slash-prefix", "windows-drive-prefix", "bare-filename",
    ],
)
def test_dest_record_assets_accepts_every_legal_path_shape(tmp_path, asset):
    """The other half of the two new checks: they must not reject a record
    that is fine. The name-shape check keys on the entry's BASENAME -- never
    on the directory part -- so every legal way of spelling the path to a
    content-addressed asset still reads back. Anything that regresses into
    validating the whole path would fail a real publish on the strength of a
    cosmetic difference, which is the same class of harm in the other
    direction.

    `backslashes` was a member of this list in wave I-1 round 4 and is not
    one any more; it now has its own test below, asserting the opposite. See
    that test for why."""
    sha = hashlib.sha256(b"legal").hexdigest()
    record_path = _dest_record(tmp_path, [asset.format(sha=sha)])
    assert _dest_record_assets(record_path) == [asset.format(sha=sha)]


@pytest.mark.parametrize(
    "asset",
    ["doc-a\\assets\\{sha}.png", "doc-a/assets\\{sha}.png"],
    ids=["all-backslashes", "mixed-separators"],
)
def test_dest_record_assets_rejects_a_backslash_spelled_entry_on_every_host(
    tmp_path, asset
):
    """Wave I-1 round 5, the Critical, and the exact assertion round 4 got
    backwards: `backslashes` was in the legal-shapes list above.

    That assertion was true only because `pathlib.Path` binds to WindowsPath
    on the machine round 4 measured on. On ubuntu-latest -- three of
    `_gate.yml`'s five `t1-tests` legs -- `Path` is PosixPath, a backslash is
    an ordinary character, `.name` is the whole string, and the identical
    record raised instead. Same bytes, two answers, decided by whichever host
    happened to read them: a Windows hub accepted a backslash-spelled record
    and a Linux hub hard-failed the publish, and through _inheritable_assets
    the same upstream name was merged on one and dropped on the other. Ruling
    P49 -- the property is platform-independent, so the mechanism must not be.

    Rejecting (rather than teaching both hosts to accept) is the answer this
    codebase already had, in two places that had nothing to do with this
    round: assetstore.divert_assets, the only writer of record entries
    anywhere in the tree, writes `.as_posix()` -- forward slashes, always;
    and pubgate.is_kb_artifact refuses any relpath containing a backslash
    outright, so a backslash-spelled entry could never be MIRRORED by a
    publish even if this reader accepted it. Accepting would therefore have
    bought a name that is silently un-carryable; refusing names it.

    The two flavour assertions are the platform-independence pin itself: they
    state, on both hosts at once, what the host-bound `Path` would have said
    and which of its two answers is the contract."""
    sha = hashlib.sha256(b"legal").hexdigest()
    entry = asset.format(sha=sha)
    # WindowsPath reads the backslash as a separator and lands on a basename
    # that passes; PurePosixPath does not. The record is posix-spelled by
    # construction, so PurePosixPath decides -- on every host.
    assert assetstore._ASSET_NAME_RE.match(PureWindowsPath(entry).name)
    assert not assetstore._ASSET_NAME_RE.match(PurePosixPath(entry).name)
    record_path = _dest_record(tmp_path, [entry])
    with pytest.raises(OSError, match="not a content-addressed asset name"):
        _dest_record_assets(record_path)


def test_every_dest_record_assets_refusal_names_the_recovery_that_works(tmp_path):
    """The mirror of test_assetstore.py's test of the same name: all four of
    THIS reader's hard refusals route their way-forward through
    assetstore.restore_clause too, so the two readers of one file cannot
    drift into naming two different recoveries (wave I-1 round 5, Important
    1). The not-a-regular-file arm is excluded for the same reason there."""
    record_path = tmp_path / assetstore.RECORD_NAME
    good = f"assets:\n- doc1/assets/{hashlib.sha256(b'r').hexdigest()}.png\n"
    shapes = {
        "corrupt-yaml": "assets: [unclosed\n",
        "present-but-empty": "",
        "mangled-name": "assets:\n- doc1/assets/mangled\n",
        "no-trailing-newline": good.rstrip("\n"),
    }
    for label, text in shapes.items():
        record_path.write_text(text, encoding="utf-8")
        with pytest.raises(OSError) as excinfo:
            _dest_record_assets(record_path)
        msg = str(excinfo.value)
        # the commands spelled out, NOT `restore_clause(record_path) in msg` --
        # that would move with the mutation and pass for any clause at all
        assert f"git log --oneline -- {record_path}" in msg, label
        assert f"git checkout <commit> -- {record_path}" in msg, label
        # and all four arms go through the one helper, so they cannot drift
        assert assetstore.restore_clause(record_path) in msg, label


def test_the_recovery_the_refusal_names_actually_restores_the_record(
    tmp_path, run_git
):
    """Wave I-1 round 5, Important 1: run the shipped instruction end to end.

    Every hard refusal in both readers used to offer `git checkout -- <path>`
    as its example. That command restores the working tree from the INDEX,
    and in the shape these messages are about the index holds the corruption
    -- an interrupted publish's own `git add -A`, or any routine one, puts it
    there. So it exits 0, prints nothing, changes nothing, and the next
    publish fails with the identical message: the operator loops, silently.
    (In the other branch, where the corruption was never staged, the
    publish's own abort-and-restore has already repaired the file before the
    message is read, so it was unnecessary there too -- the named command
    never did useful work in either branch.)

    This drives both commands for real, exactly as the message spells them,
    and asserts what each one does to the bytes -- so the instruction cannot
    drift back into a form that silently no-ops without a test going red."""
    root = tmp_path / "hub"
    root.mkdir()
    run_git(root, "init")
    run_git(root, "config", "user.name", "test")
    run_git(root, "config", "user.email", "test@test.local")
    # what publish itself does to every hub clone it touches, and what makes
    # `git checkout <commit> -- <path>` give the bytes back rather than the
    # dev machine's global core.autocrlf rewriting them on the way out
    gitio.neutralize_line_endings(root)

    sha = hashlib.sha256(b"recovery").hexdigest()
    entry = f"doc-a/assets/{sha}.png"
    record_path = root / assetstore.RECORD_NAME
    models.save_yaml_model(record_path, models.AssetsRecord(assets=[entry]))
    good = record_path.read_bytes()
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "record v1")
    good_commit = run_git(root, "rev-parse", "HEAD")

    # the interrupted write, committed -- what the hub looks like by the time
    # an operator is reading this message
    record_path.write_bytes(good[: good.index(sha.encode()) + 8])
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "publish interrupted mid-write")
    corrupt = record_path.read_bytes()

    with pytest.raises(OSError) as excinfo:
        _dest_record_assets(record_path)
    msg = str(excinfo.value)

    # the short form, run exactly as the message now warns about it
    assert (
        f"NOT plain `git checkout -- {record_path}`, which restores from "
        "the index" in msg
    )
    run_git(root, "checkout", "--", str(record_path))
    assert record_path.read_bytes() == corrupt  # rc=0 and nothing happened

    # the form the message names, run exactly as the message spells it
    assert f"`git log --oneline -- {record_path}` lists them" in msg
    assert f"`git checkout <commit> -- {record_path}`" in msg
    assert good_commit in run_git(root, "log", "--oneline", "--format=%H", "--", str(record_path))
    run_git(root, "checkout", good_commit, "--", str(record_path))
    assert record_path.read_bytes() == good
    assert _dest_record_assets(record_path) == [entry]
