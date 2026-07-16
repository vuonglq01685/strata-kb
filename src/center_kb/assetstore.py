"""Object-store seam for image assets (spec B).

Asset names are bare content-addressed filenames `<sha256>.<png|webp>`
(spec A); the store prepends the configured key prefix. `mode: none`
returns no store and leaves all existing behavior unchanged.
"""
from __future__ import annotations

import logging
from pathlib import Path

from center_kb import config as config_mod
from center_kb import models

logger = logging.getLogger("center_kb.assetstore")

_MEDIA = {".png": "image/png", ".webp": "image/webp"}
_IMMUTABLE = "private, max-age=31536000, immutable"


class AssetStoreError(RuntimeError):
    """Store unreachable / misconfigured / operation failed."""


def _media_type(name: str) -> str:
    return _MEDIA.get(Path(name).suffix, "application/octet-stream")


class MemoryStore:
    """Dict-backed store for tests."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def exists(self, name: str) -> bool:
        return name in self.data

    def put(self, name: str, data: bytes) -> None:
        self.data.setdefault(name, data)

    def get(self, name: str) -> bytes | None:
        return self.data.get(name)


def _is_missing(exc: Exception) -> bool:
    code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
    return code in {"404", "NoSuchKey", "NotFound"}


class S3Store:
    """S3-compatible store. boto3 imports lazily at first use so `mode: none`
    installs never need it; `client` is a test seam."""

    def __init__(self, cfg: config_mod.AssetStoreConfig, client=None) -> None:
        if not cfg.bucket:
            raise AssetStoreError("asset_store.mode is s3 but no bucket is set")
        self._cfg = cfg
        self._client = client

    def _c(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise AssetStoreError(
                    'S3 asset store needs boto3 — run: pip install "center-kb[s3]"'
                ) from exc
            kwargs: dict = {}
            if self._cfg.region:
                kwargs["region_name"] = self._cfg.region
            if self._cfg.endpoint:
                kwargs["endpoint_url"] = self._cfg.endpoint
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def _key(self, name: str) -> str:
        return f"{self._cfg.prefix}{name}"

    def exists(self, name: str) -> bool:
        try:
            self._c().head_object(Bucket=self._cfg.bucket, Key=self._key(name))
            return True
        except AssetStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 — classify, then wrap
            if _is_missing(exc):
                return False
            raise AssetStoreError(f"asset store HEAD failed: {exc}") from exc

    def put(self, name: str, data: bytes) -> None:
        if self.exists(name):
            return  # content-addressed → identical bytes, idempotent
        try:
            self._c().put_object(
                Bucket=self._cfg.bucket,
                Key=self._key(name),
                Body=data,
                ContentType=_media_type(name),
                CacheControl=_IMMUTABLE,
            )
        except Exception as exc:  # noqa: BLE001
            raise AssetStoreError(f"asset store PUT failed: {exc}") from exc

    def get(self, name: str) -> bytes | None:
        try:
            resp = self._c().get_object(
                Bucket=self._cfg.bucket, Key=self._key(name)
            )
            return resp["Body"].read()
        except AssetStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            if _is_missing(exc):
                return None
            raise AssetStoreError(f"asset store GET failed: {exc}") from exc


def from_config(cfg: config_mod.AssetStoreConfig):
    """Store per config; None when mode is 'none' (spec A status quo)."""
    if cfg.mode == "none":
        return None
    return S3Store(cfg)


def store_for_hub(handle):
    """The hub repo's own config declares its storage mode — read it from
    the hub clone so children and the intake server need no local config."""
    return from_config(config_mod.load_config(handle.kb_dir).asset_store)
