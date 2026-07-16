from __future__ import annotations

import pytest

from center_kb import assetstore, config


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
