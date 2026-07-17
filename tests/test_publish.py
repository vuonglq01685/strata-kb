import hashlib
import subprocess
import time
from pathlib import Path

import pytest

from center_kb import assetstore, ghio, gitio, models
from center_kb.federation import FederationMeta, write_federation_index
from center_kb.hub import HubHandle
from center_kb.publish import PublishError, publish
from tests.conftest import make_fed_entry


@pytest.fixture
def hub_with_origin(hub_worktree, run_git, tmp_path):
    origin = tmp_path / "hub-origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(hub_worktree, "remote", "add", "origin", str(origin))
    run_git(hub_worktree, "push", "-u", "origin", "HEAD")
    return hub_worktree


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


def test_republish_replaces_entry_wholesale(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    stray = hub_worktree / "federation" / "demo-kb" / "stale-doc"
    stray.mkdir()
    (stray / "x.md").write_text("stale", encoding="utf-8")
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert not stray.exists()


def test_invalid_repo_id_rejected(git_kb, hub_worktree):
    with pytest.raises(PublishError):
        publish(git_kb["kb"], str(hub_worktree), repo_id="../evil")


def test_unreachable_hub_raises(git_kb, tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    with pytest.raises(PublishError):
        publish(git_kb["kb"], str(tmp_path / "does-not-exist"))


def test_auto_mode_is_direct_for_local_path_hub(git_kb, hub_worktree, monkeypatch):
    # a dev machine may have a real gh — stub it out so auto-detect depends
    # only on the remote
    monkeypatch.setattr(ghio, "gh_available", lambda: True)
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert report.mode == "direct"


def test_pr_mode_pushes_branch_and_opens_pr(git_kb, hub_with_origin, monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(ghio, "gh_available", lambda: True)
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
    with pytest.raises(PublishError) as exc:
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
    n_docs, changed = publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=store)
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
    n_docs, changed = publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=store)
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
    n_docs, changed = publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=store)
    assert changed
    assert store.get(f"{SHA_Y}.png") == b"YBYTES"  # asset uploaded
    dest = handle.federation_dir / "rid-a"
    assert not list(dest.rglob("*.png"))  # no binaries left in the tree
