from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from center_kb import assetcmd, assetstore, gitio, models
from center_kb.hub import HubHandle

DATA = b"MIGRATEME"
SHA = hashlib.sha256(DATA).hexdigest()


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


def test_migrate_failure_restores_failed_rid(hub_root):
    class _Down(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    with pytest.raises(assetstore.AssetStoreError):
        assetcmd.migrate_assets(HubHandle(root=hub_root), store=_Down())
    # failed rid restored: binaries back, no half state, nothing staged
    assert (hub_root / "federation" / "rid-a" / "doc1" / "assets" / f"{SHA}.png").exists()
    status = gitio._run(hub_root, "status", "--porcelain", "--", "federation").stdout.strip()
    assert status == ""
