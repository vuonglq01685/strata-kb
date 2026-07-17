from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from center_kb import assetstore, config, models


NAME_PNG = "a" * 64 + ".png"
NAME_WEBP = "b" * 64 + ".webp"


def test_memory_store_roundtrip():
    store = assetstore.MemoryStore()
    assert not store.exists(NAME_PNG)
    assert store.get(NAME_PNG) is None
    store.put(NAME_PNG, b"PNGDATA")
    assert store.exists(NAME_PNG)
    assert store.get(NAME_PNG) == b"PNGDATA"


def test_from_config_none_and_s3():
    assert assetstore.from_config(config.AssetStoreConfig()) is None
    cfg = config.AssetStoreConfig(mode="s3", bucket="kb-assets")
    store = assetstore.from_config(cfg)
    assert isinstance(store, assetstore.S3Store)


def test_s3_mode_requires_bucket():
    with pytest.raises(assetstore.AssetStoreError, match="bucket"):
        assetstore.from_config(config.AssetStoreConfig(mode="s3"))


class _FakeClientError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class _StubS3Client:
    """Stands in for boto3's S3 client — records calls, no network."""

    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.put_calls: list[str] = []

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _FakeClientError("404")
        return {}

    def put_object(self, Bucket, Key, Body, ContentType, CacheControl):
        self.objects[Key] = {
            "Body": Body, "ContentType": ContentType, "CacheControl": CacheControl,
        }
        self.put_calls.append(Key)

    def get_object(self, Bucket, Key):
        import io

        if Key not in self.objects:
            raise _FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key]["Body"])}


def _s3(client):
    cfg = config.AssetStoreConfig(mode="s3", bucket="kb-assets", prefix="assets/")
    return assetstore.S3Store(cfg, client=client)


def test_s3_put_sets_metadata_and_prefix():
    client = _StubS3Client()
    _s3(client).put(NAME_PNG, b"PNGDATA")
    obj = client.objects[f"assets/{NAME_PNG}"]
    assert obj["ContentType"] == "image/png"
    assert "immutable" in obj["CacheControl"]


def test_s3_put_skips_existing_key():
    client = _StubS3Client()
    store = _s3(client)
    store.put(NAME_WEBP, b"X")
    store.put(NAME_WEBP, b"X")
    assert client.put_calls == [f"assets/{NAME_WEBP}"]


def test_s3_get_and_exists_and_miss():
    client = _StubS3Client()
    store = _s3(client)
    assert store.get(NAME_PNG) is None
    assert not store.exists(NAME_PNG)
    store.put(NAME_PNG, b"PNGDATA")
    assert store.exists(NAME_PNG)
    assert store.get(NAME_PNG) == b"PNGDATA"


def test_s3_non_missing_error_wraps_as_assetstoreerror():
    class _Boom:
        def head_object(self, Bucket, Key):
            raise _FakeClientError("AccessDenied")

    with pytest.raises(assetstore.AssetStoreError):
        _s3(_Boom()).exists(NAME_PNG)


def test_missing_boto3_names_the_extra(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def block(name, *a, **kw):
        if name.startswith("boto3"):
            raise ImportError(name)
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", block)
    cfg = config.AssetStoreConfig(mode="s3", bucket="kb-assets")
    store = assetstore.S3Store(cfg)  # construction OK — import is lazy
    with pytest.raises(assetstore.AssetStoreError, match=r"center-kb\[s3\]"):
        store.exists(NAME_PNG)


def test_store_for_hub_reads_hub_config(tmp_path):
    from center_kb.hub import HubHandle

    kb = tmp_path / ".kb"
    kb.mkdir()
    handle = HubHandle(root=tmp_path)
    assert assetstore.store_for_hub(handle) is None  # no config file → none
    (kb / "config.yaml").write_text(
        "asset_store:\n  mode: s3\n  bucket: kb-assets\n", encoding="utf-8"
    )
    assert isinstance(assetstore.store_for_hub(handle), assetstore.S3Store)


# Real content hashes: spec A guarantees filename sha == sha256(bytes), and
# Task 7's round-trip test depends on this fixture honoring that invariant.
SHA_A = hashlib.sha256(b"A").hexdigest()
SHA_B = hashlib.sha256(b"B").hexdigest()
SHA_C = hashlib.sha256(b"C").hexdigest()


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "rid"
    (root / "doc1" / "assets").mkdir(parents=True)
    (root / "doc1" / "assets" / f"{SHA_A}.png").write_bytes(b"A")
    (root / "doc1" / "assets" / f"{SHA_B}.webp").write_bytes(b"B")
    (root / "doc1" / "ch1-intro.md").write_text("x", encoding="utf-8")
    (root / "doc1" / "assets" / "notes.txt").write_bytes(b"skip me")
    return root


def test_divert_assets_uploads_strips_and_skips_nonassets(tmp_path):
    root = _tree(tmp_path)
    store = assetstore.MemoryStore()
    diverted = assetstore.divert_assets(root, store)
    assert diverted == [
        f"doc1/assets/{SHA_A}.png",
        f"doc1/assets/{SHA_B}.webp",
    ]
    assert store.get(f"{SHA_A}.png") == b"A"
    assert store.get(f"{SHA_B}.webp") == b"B"
    assert not (root / "doc1" / "assets" / f"{SHA_A}.png").exists()
    assert (root / "doc1" / "assets" / "notes.txt").exists()  # not an asset name
    assert (root / "doc1" / "ch1-intro.md").exists()


def test_divert_assets_prunes_empty_assets_dir(tmp_path):
    root = tmp_path / "rid"
    (root / "doc2" / "assets").mkdir(parents=True)
    (root / "doc2" / "assets" / f"{SHA_C}.png").write_bytes(b"C")
    assetstore.divert_assets(root, assetstore.MemoryStore())
    assert not (root / "doc2" / "assets").exists()


def test_divert_and_record_merges_with_existing_and_deletes(tmp_path):
    root = _tree(tmp_path)
    old = f"doc0/assets/{SHA_C}.png"
    gone = f"doc9/assets/{'d' * 64}.png"
    models.save_yaml_model(
        root / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[old, gone]),
    )
    assetstore.divert_and_record(root, assetstore.MemoryStore(), deletes=[gone])
    rec = models.load_yaml_model(root / assetstore.RECORD_NAME, models.AssetsRecord)
    assert rec.assets == sorted(
        [old, f"doc1/assets/{SHA_A}.png", f"doc1/assets/{SHA_B}.webp"]
    )


def test_divert_and_record_corrupt_record_treated_as_empty(tmp_path):
    root = _tree(tmp_path)
    (root / assetstore.RECORD_NAME).write_text("{{not yaml", encoding="utf-8")
    assetstore.divert_and_record(root, assetstore.MemoryStore())
    rec = models.load_yaml_model(root / assetstore.RECORD_NAME, models.AssetsRecord)
    assert f"doc1/assets/{SHA_A}.png" in rec.assets


def test_synthesized_asset_entries_uses_filename_sha(tmp_path):
    root = tmp_path / "rid"
    root.mkdir()
    models.save_yaml_model(
        root / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc1/assets/{SHA_A}.png"]),
    )
    entries = assetstore.synthesized_asset_entries(root)
    assert entries == {f"doc1/assets/{SHA_A}.png": SHA_A}


def test_synthesized_asset_entries_empty_when_no_record(tmp_path):
    root = tmp_path / "rid"
    root.mkdir()
    assert assetstore.synthesized_asset_entries(root) == {}


def test_divert_then_synthesis_roundtrip_no_rediff(tmp_path):
    from center_kb import hashsync

    child = _tree(tmp_path)  # child-side snapshot (assets present)
    dest = tmp_path / "dest"
    local_man = hashsync.build_manifest(child)
    changed, deleted = hashsync.diff_manifests(local_man, {})
    hashsync.apply_sync(child, dest, changed, deleted)
    assetstore.divert_and_record(dest, assetstore.MemoryStore(), deleted)

    hub_man = hashsync.build_manifest(dest, exclude=("_meta.yaml", assetstore.RECORD_NAME))
    hub_man.update(assetstore.synthesized_asset_entries(dest))
    changed2, deleted2 = hashsync.diff_manifests(local_man, hub_man)
    assert changed2 == [] and deleted2 == []
