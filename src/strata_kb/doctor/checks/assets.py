"""Checks on asset storage."""

from __future__ import annotations

from pathlib import Path

from strata_kb.doctor.issues import Issue, _flatten

ASSET_SIZE_WARN_BYTES = 100 * 1024 * 1024


def check_asset_store(kb_dir: Path, handle, store=None) -> list[Issue]:
    """Storage health per asset_store mode; [] when the block is absent."""
    from strata_kb import assetstore
    from strata_kb.config import load_config

    try:
        cfg = load_config(kb_dir).asset_store
    except Exception:  # noqa: BLE001 — check_kind already reports invalid config
        return []
    if cfg.mode == "none":
        total = 0
        roots = [kb_dir]
        if handle is not None:
            roots.append(handle.federation_dir)
        for root in roots:
            if not root.is_dir():
                continue
            total += sum(
                p.stat().st_size for p in root.glob("**/assets/*") if p.is_file()
            )
        if total > ASSET_SIZE_WARN_BYTES:
            return [
                Issue(
                    "warning",
                    f"in-git assets total {total // (1024 * 1024)} MB — consider "
                    "asset_store mode: s3 (kb assets migrate) or git-LFS",
                )
            ]
        return []
    if store is None:
        try:
            store = assetstore.from_config(cfg)
        except assetstore.AssetStoreError as exc:
            return [Issue("error", f"asset_store: {_flatten(exc)}")]
        if store is None:  # mode "none" returned above; from_config agrees
            return []
    try:
        store.exists(assetstore.PROBE_NAME)
    except assetstore.AssetStoreError as exc:
        return [Issue("error", f"asset store unreachable: {_flatten(exc)}")]
    return []
