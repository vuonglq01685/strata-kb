"""Operator commands for the asset store: migrate (none→s3 backfill) and
verify (coverage check). Both run against a hub clone and never touch a
child's .kb/."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from center_kb import assetstore, gitio, models

logger = logging.getLogger("center_kb.assetcmd")

# Content-addressed asset filenames as referenced from markdown, e.g.
# "assets/<sha256>.png" (spec A) — same shape as assetstore._ASSET_NAME_RE,
# duplicated here bound to the "assets/" prefix rather than a bare filename.
_REF_RE = re.compile(r"assets/([0-9a-f]{64}\.(?:png|webp))")


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


@dataclass
class VerifyReport:
    missing_records: list[str] = field(default_factory=list)
    dangling_refs: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing_records and not self.dangling_refs


def _record_entries(rid_dir: Path) -> list[str]:
    path = rid_dir / assetstore.RECORD_NAME
    if not path.exists():
        return []
    try:
        return models.load_yaml_model(path, models.AssetsRecord).assets
    except Exception:  # noqa: BLE001 — a corrupt record is a verify finding
        return []


def _entry_resolves(rid_dir: Path, rel: str, store) -> bool:
    if (rid_dir / rel).is_file():
        return True
    return store is not None and store.exists(Path(rel).name)


def verify_assets(handle, store=None) -> VerifyReport:
    """Read-only coverage check: record entries resolvable, markdown refs
    resolvable, orphan record entries listed (informational)."""
    if store is None:
        store = assetstore.store_for_hub(handle)  # None in mode: none
    report = VerifyReport()
    referenced: set[str] = set()
    recorded: dict[str, str] = {}  # basename -> "rid: relpath"

    for rid_dir in _rid_dirs(handle):
        for rel in _record_entries(rid_dir):
            label = f"{rid_dir.name}: {rel}"
            recorded[Path(rel).name] = label
            if not _entry_resolves(rid_dir, rel, store):
                report.missing_records.append(label)

    md_roots = [handle.federation_dir, handle.kb_dir]
    local_names = {
        p.name
        for root in md_roots
        if root.is_dir()
        for p in root.glob("**/assets/*")
        if p.is_file()
    }
    for root in md_roots:
        if not root.is_dir():
            continue
        for md in root.rglob("*.md"):
            for m in _REF_RE.finditer(md.read_text(encoding="utf-8", errors="replace")):
                name = m.group(1)
                referenced.add(name)
                if name in local_names:
                    continue
                if name in recorded and store is not None and store.exists(name):
                    continue
                report.dangling_refs.append(f"{md.relative_to(handle.root)}: {name}")

    report.orphans = sorted(
        label for name, label in recorded.items() if name not in referenced
    )
    report.dangling_refs = sorted(set(report.dangling_refs))
    return report
