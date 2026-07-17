"""Object-store seam for image assets (spec B).

Asset names are bare content-addressed filenames `<sha256>.<png|webp>`
(spec A); the store prepends the configured key prefix. `mode: none`
returns no store and leaves all existing behavior unchanged.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from center_kb import config as config_mod
from center_kb import models

logger = logging.getLogger("center_kb.assetstore")

_MEDIA = {".png": "image/png", ".webp": "image/webp"}
_IMMUTABLE = "private, max-age=31536000, immutable"

RECORD_NAME = "_assets.yaml"
_ASSET_NAME_RE = re.compile(r"^([0-9a-f]{64})\.(?:png|webp)$")

# Well-known nonexistent key for reachability probes (doctor, kb assets):
# a clean "not found" proves bucket + credentials + endpoint work.
PROBE_NAME = "0" * 64 + ".png"


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


def divert_assets(tree_root: Path, store) -> list[str]:
    """Upload every content-addressed asset under tree_root and strip it
    from the tree. Returns sorted relative posix paths. Any store failure
    raises AssetStoreError — the caller must not have committed yet."""
    diverted: list[str] = []
    for path in sorted(tree_root.rglob("assets/*")):
        if not path.is_file() or not _ASSET_NAME_RE.match(path.name):
            continue
        store.put(path.name, path.read_bytes())
        rel = path.relative_to(tree_root).as_posix()
        path.unlink()
        diverted.append(rel)
        try:
            path.parent.rmdir()  # only succeeds when now empty
        except OSError:
            pass
    return sorted(diverted)


def _load_record(dest: Path) -> "models.AssetsRecord":
    record_path = dest / RECORD_NAME
    if not record_path.exists():
        return models.AssetsRecord()
    try:
        return models.load_yaml_model(record_path, models.AssetsRecord)
    except Exception as exc:  # noqa: BLE001 — corrupt record self-heals
        logger.warning("%s unreadable (%s) — treating as empty", record_path, exc)
        return models.AssetsRecord()


def divert_and_record(dest: Path, store, deletes: list[str] | None = None) -> list[str]:
    """Divert assets under dest, then merge the record: existing ∪ new − deletes.
    Intake uploads are incremental, so a plain overwrite would drop
    previously-diverted assets from the record."""
    diverted = divert_assets(dest, store)
    merged = sorted(
        (set(_load_record(dest).assets) | set(diverted)) - set(deletes or [])
    )
    record_path = dest / RECORD_NAME
    if merged:
        models.save_yaml_model(record_path, models.AssetsRecord(assets=merged))
    elif record_path.exists():
        record_path.unlink()
    return diverted


def synthesized_asset_entries(dest: Path) -> dict[str, str]:
    """Manifest entries for diverted assets: {relpath: sha}, sha taken from
    the filename — exact by spec A construction, no bytes needed."""
    entries: dict[str, str] = {}
    for rel in _load_record(dest).assets:
        m = _ASSET_NAME_RE.match(Path(rel).name)
        if m:
            entries[rel] = m.group(1)
    return entries
