"""Operator commands for the asset store: migrate (none→s3 backfill) and
verify (coverage check). Both run against a hub clone and never touch a
child's .kb/."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from center_kb import assetstore, gitio

logger = logging.getLogger("center_kb.assetcmd")


class AssetCmdError(RuntimeError):
    """Preconditions unmet (mode/config), distinct from store failures."""


@dataclass
class MigrateReport:
    per_rid: dict[str, int] = field(default_factory=dict)
    committed: bool = False


def _require_store(handle, store):
    if store is not None:
        return store
    resolved = assetstore.store_for_hub(handle)
    if resolved is None:
        raise AssetCmdError(
            "asset_store.mode is not s3 in the hub's .kb/config.yaml — "
            "run `kb init --assets s3` and fill the bucket first"
        )
    resolved.exists(assetstore.PROBE_NAME)  # reachability; raises AssetStoreError
    return resolved


def _rid_dirs(handle) -> list[Path]:
    fed = handle.federation_dir
    if not fed.is_dir():
        return []
    return sorted(p for p in fed.iterdir() if p.is_dir())


def migrate_assets(handle, store=None) -> MigrateReport:
    """Divert every in-git asset under federation/ to the store, rid by rid.

    Idempotent: content-addressed puts skip existing keys; upload precedes
    unlink (spec B ordering) so there is no image-down window. A failed
    rid's working tree is restored before the error surfaces, so a later
    unrelated commit can never pick up half-migrated state."""
    store = _require_store(handle, store)
    report = MigrateReport()
    for rid_dir in _rid_dirs(handle):
        try:
            diverted = assetstore.divert_and_record(rid_dir, store)
        except assetstore.AssetStoreError:
            rel = f"federation/{rid_dir.name}"
            for args in (("checkout", "--", rel), ("clean", "-fd", "--", rel)):
                result = gitio._run(handle.root, *args)
                if result.returncode != 0:
                    logger.warning("restore failed: git %s: %s", args, result.stderr)
            raise
        if diverted:
            report.per_rid[rid_dir.name] = len(diverted)
    if report.per_rid:
        report.committed = gitio.commit_paths(
            handle.root, "assets: migrate to object store", ["federation"]
        )
    return report
