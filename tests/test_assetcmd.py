from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from center_kb import assetcmd, assetstore, gitio, models
from center_kb.hub import HubHandle

DATA = b"MIGRATEME"
SHA = hashlib.sha256(DATA).hexdigest()

DATA_A = b"MIGRATEME-A"
SHA_A = hashlib.sha256(DATA_A).hexdigest()
DATA_B = b"MIGRATEME-B"
SHA_B = hashlib.sha256(DATA_B).hexdigest()


@pytest.fixture
def hub_root(tmp_path, run_git) -> Path:
    root = tmp_path / "hub"
    assets = root / "federation" / "rid-a" / "doc1" / "assets"
    assets.mkdir(parents=True)
    (assets / f"{SHA}.png").write_bytes(DATA)
    (root / "federation" / "rid-a" / "doc1" / "ch1.md").write_text(
        f"![x](assets/{SHA}.png)\n", encoding="utf-8"
    )
    (root / ".kb").mkdir()
    (root / ".kb" / "config.yaml").write_text(
        "kind: hub\nasset_store:\n  mode: s3\n  bucket: b\n", encoding="utf-8"
    )
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "seed")
    return root


@pytest.fixture
def hub_root_two_assets(tmp_path, run_git) -> Path:
    """Same shape as hub_root, but rid-a/doc1/assets/ carries TWO assets.

    A single-asset fixture makes the failure-restore path vacuous: divert
    uploads-before-unlinks, so a store that fails on the very first put()
    never gets to unlink anything — the except-block restore then runs
    against an already-pristine tree and passes even if deleted outright.
    With two assets, a store that succeeds on the first put() and fails on
    the second lets the first asset actually get uploaded+unlinked before
    the exception — giving the restore real work to undo.
    """
    root = tmp_path / "hub"
    assets = root / "federation" / "rid-a" / "doc1" / "assets"
    assets.mkdir(parents=True)
    (assets / f"{SHA_A}.png").write_bytes(DATA_A)
    (assets / f"{SHA_B}.png").write_bytes(DATA_B)
    (root / "federation" / "rid-a" / "doc1" / "ch1.md").write_text(
        f"![a](assets/{SHA_A}.png)\n![b](assets/{SHA_B}.png)\n", encoding="utf-8"
    )
    (root / ".kb").mkdir()
    (root / ".kb" / "config.yaml").write_text(
        "kind: hub\nasset_store:\n  mode: s3\n  bucket: b\n", encoding="utf-8"
    )
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "seed")
    return root


def test_migrate_uploads_strips_records_commits(hub_root):
    store = assetstore.MemoryStore()
    report = assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    assert report.per_rid == {"rid-a": 1}
    assert report.committed
    assert store.get(f"{SHA}.png") == DATA
    dest = hub_root / "federation" / "rid-a"
    assert not (dest / "doc1" / "assets" / f"{SHA}.png").exists()
    rec = models.load_yaml_model(dest / "_assets.yaml", models.AssetsRecord)
    assert rec.assets == [f"doc1/assets/{SHA}.png"]
    tracked = gitio._run(hub_root, "ls-files", "--", "federation").stdout
    assert f"{SHA}.png" not in tracked and "_assets.yaml" in tracked
    status = gitio._run(hub_root, "status", "--porcelain").stdout.strip()
    assert status == ""  # everything committed


def test_migrate_second_run_noop(hub_root):
    store = assetstore.MemoryStore()
    assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    report = assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    assert report.per_rid == {} or all(n == 0 for n in report.per_rid.values())
    assert not report.committed


def test_migrate_requires_s3_mode(hub_root):
    (hub_root / ".kb" / "config.yaml").write_text("kind: hub\n", encoding="utf-8")
    with pytest.raises(assetcmd.AssetCmdError, match="mode"):
        assetcmd.migrate_assets(HubHandle(root=hub_root))


def test_migrate_failure_restores_failed_rid(hub_root_two_assets):
    hub_root = hub_root_two_assets

    class _FailOnSecondPut(assetstore.MemoryStore):
        """Succeeds once (so the first asset is genuinely uploaded and
        unlinked from disk), then fails — forcing migrate_assets to restore
        real, on-disk deletions rather than a tree it never touched."""

        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def put(self, name, data):
            self.calls += 1
            if self.calls >= 2:
                raise assetstore.AssetStoreError("bucket down")
            super().put(name, data)

    with pytest.raises(assetstore.AssetStoreError):
        assetcmd.migrate_assets(HubHandle(root=hub_root), store=_FailOnSecondPut())

    # failed rid restored: BOTH binaries present (the first one was really
    # uploaded + unlinked before the second put() failed, so its presence
    # here proves `git checkout` did the restoring, not "was never touched")
    assets_dir = hub_root / "federation" / "rid-a" / "doc1" / "assets"
    assert (assets_dir / f"{SHA_A}.png").exists()
    assert (assets_dir / f"{SHA_B}.png").exists()
    status = gitio._run(
        hub_root, "status", "--porcelain", "--", "federation"
    ).stdout.strip()
    assert status == ""  # nothing staged, nothing left dirty
    assert not (hub_root / "federation" / "rid-a" / "_assets.yaml").exists()


def _migrated_hub(hub_root) -> assetstore.MemoryStore:
    store = assetstore.MemoryStore()
    assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    return store


def test_verify_ok_after_migrate(hub_root):
    store = _migrated_hub(hub_root)
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert report.ok
    assert report.missing_records == [] and report.dangling_refs == []


def test_verify_reports_missing_record_entry(hub_root):
    store = _migrated_hub(hub_root)
    store.data.clear()  # bytes vanished from the bucket
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert not report.ok
    assert any(SHA in m for m in report.missing_records)
    assert any(SHA in d for d in report.dangling_refs)


def test_verify_reports_dangling_ref(hub_root):
    store = _migrated_hub(hub_root)
    ghost = "9" * 64
    md = hub_root / "federation" / "rid-a" / "doc1" / "ch1.md"
    md.write_text(md.read_text(encoding="utf-8") + f"![g](assets/{ghost}.png)\n", encoding="utf-8")
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert any(ghost in d for d in report.dangling_refs)


def test_verify_reports_orphan_record_entry(hub_root):
    store = _migrated_hub(hub_root)
    md = hub_root / "federation" / "rid-a" / "doc1" / "ch1.md"
    md.write_text("no refs anymore\n", encoding="utf-8")
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert report.ok  # orphans are informational only
    assert any(SHA in o for o in report.orphans)


def test_verify_local_mode_checks_files(hub_root):
    # mode none: record entries must resolve as local files
    (hub_root / ".kb" / "config.yaml").write_text(
        "kind: hub\nasset_store:\n  mode: none\n", encoding="utf-8"
    )
    dest = hub_root / "federation" / "rid-a"
    models.save_yaml_model(
        dest / "_assets.yaml", models.AssetsRecord(assets=["doc1/assets/" + "8" * 64 + ".png"])
    )
    report = assetcmd.verify_assets(HubHandle(root=hub_root))
    assert not report.ok and report.missing_records
