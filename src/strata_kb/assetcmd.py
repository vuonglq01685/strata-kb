"""Operator commands for the asset store: migrate (none→s3 backfill) and
verify (coverage check). Both run against a hub clone and never touch a
child's .kb/."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from strata_kb import assetstore, gitio
from strata_kb.errors import KbError

logger = logging.getLogger("strata_kb.assetcmd")

# Content-addressed asset filenames as referenced from markdown, e.g.
# "assets/<sha256>.png" (spec A) — same shape as assetstore._ASSET_NAME_RE,
# duplicated here bound to the "assets/" prefix rather than a bare filename.
_REF_RE = re.compile(r"assets/([0-9a-f]{64}\.(?:png|webp))")


class AssetCmdError(KbError):
    """Preconditions unmet (mode/config), distinct from store failures.
    Caught in the same except tuple as assetstore.AssetStoreError, already a
    KbError -- joins the family too (Wave G fix round 2, item 7)."""


@dataclass
class MigrateReport:
    per_rid: dict[str, int] = field(default_factory=dict)
    committed: bool = False
    # path-ids of federation/ entries holding exactly one of _meta.yaml /
    # index.yaml (federation.iter_entry_dirs's own "broken" shape) -- found
    # under federation/ but never handed to the per-rid loop above, so an
    # empty per_rid here is NOT the same claim as "no in-git assets under
    # federation/" (ruling P53, item 3, wave L1 brief). See migrate_assets.
    skipped: list[str] = field(default_factory=list)


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


def _rid_dirs(handle) -> list[tuple[str, Path]]:
    """(entry path-id, directory) for every LEAF entry under federation/.

    Iterating the top level treated `mid` as the repo for a nested entry
    `mid/deep`: the record landed at federation/mid/_assets.yaml with the
    path `deep/doc/assets/<sha>.png`, so the leaf every reader actually uses
    -- via federation.iter_entry_dirs -- had no record at all.
    """
    from strata_kb import federation

    return federation.iter_entry_dirs(handle.federation_dir)


def migrate_assets(handle, store=None) -> MigrateReport:
    """Divert every in-git asset under federation/ to the store, rid by rid.

    Idempotent: content-addressed puts skip existing keys; upload precedes
    unlink (spec B ordering) so there is no image-down window. A failed
    rid's working tree is restored before the error surfaces, so a later
    unrelated commit can never pick up half-migrated state.

    Each entry's committed record is read with assetstore.load_record
    BEFORE divert_and_record runs (task 21 fix round, P32): migrate is
    documented as idempotent and expected to be re-run, and on a re-run an
    entry with nothing left to divert has `diverted == []` — if that
    entry's record could not be read, divert_and_record's own lenient
    merge (needed elsewhere, see its docstring) would see the same "empty"
    and unlink the record outright while the store still holds the only
    copy of what it named. Pre-checking here means that never happens:
    load_record raises before divert_and_record is ever called for the
    entry, so nothing is derived from the failed read and nothing is
    unlinked -- the same except below restores the working tree and
    re-raises, naming the file, exiting non-zero.

    report.skipped (item 3, ruling P53) is populated from
    federation.scan_broken_entries, read-only and additional to the sweep
    above -- it does not widen what gets diverted, only what the caller is
    told. Before this, an entry with exactly one of _meta.yaml/index.yaml
    was invisible to this function entirely (iter_entry_dirs logs a
    warning and moves on), so a hub with committed raw bytes sitting
    under exactly that shape made this function return an empty per_rid
    -- indistinguishable, to the caller, from a hub with genuinely nothing
    left under federation/."""
    store = _require_store(handle, store)
    report = MigrateReport()
    for entry_rel, rid_dir in _rid_dirs(handle):
        try:
            assetstore.load_record(rid_dir)
            diverted = assetstore.divert_and_record(rid_dir, store)
        except assetstore.AssetStoreError:
            rel = f"federation/{entry_rel}"
            for args in (("checkout", "--", rel), ("clean", "-fd", "--", rel)):
                result = gitio._run(handle.root, *args)
                if result.returncode != 0:
                    logger.warning("restore failed: git %s: %s", args, result.stderr)
            raise
        if diverted:
            report.per_rid[entry_rel] = len(diverted)
    from strata_kb import federation

    report.skipped = sorted(
        entry_rel
        for entry_rel, _entry_dir in federation.scan_broken_entries(handle.federation_dir).broken
    )
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
    corrupt: list[str] = field(default_factory=list)
    # A path under federation/ or .kb/ that could not be read while walking
    # for local asset names or markdown files -- a broken link (NTFS
    # junction whose target is gone, dangling symlink, vanished target).
    # Distinct from `corrupt` (bytes that fail to hash to their own name):
    # this is "could not even look", not "looked and it was wrong". See
    # _walk_md_root's docstring for why this is reported rather than either
    # raised or silently dropped.
    broken_links: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            not self.missing_records
            and not self.dangling_refs
            and not self.corrupt
            and not self.broken_links
        )


def _record_entries(entry_rel: str, rid_dir: Path, corrupt: list[str]) -> list[str]:
    """`.assets` at rid_dir's record, or [] when genuinely absent.

    Goes through assetstore.load_record — the same primitive migrate's
    pre-flight uses — instead of its own bare `except Exception: return
    []` (Important 3, wave I-1 round 2): that used to report a record
    verify cannot read, or reads back degenerate (unreadable, corrupt, or
    present-but-empty — see load_record), as clean, with `ok=True` unless
    some markdown happened to still reference the asset. verify is
    read-only — nothing here derives a write or a delete from the failed
    read — so the failure is surfaced as a finding naming the file instead
    of raised: `kb assets verify`'s whole job is telling an operator the
    store and the records disagree, and a record it cannot itself read is
    exactly that disagreement."""
    try:
        return assetstore.load_record(rid_dir).assets
    except assetstore.AssetStoreError as exc:
        corrupt.append(f"{entry_rel}: {rid_dir / assetstore.RECORD_NAME} ({exc})")
        return []


def _entry_resolves(
    rid_dir: Path, rel: str, store, corrupt: list[str], entry_rel: str
) -> bool:
    """Resolvable AND intact. `kb assets verify` used to call store.exists,
    which cannot tell a good object from a tampered one.

    `PurePosixPath(rel).name`, not `Path(rel).name` (item 6, wave L1
    brief): `rel` is a record entry, a POSIX-spelled relative path by
    construction (assetstore.divert_assets, the only writer of them
    anywhere in this tree, writes `.as_posix()`), and `Path(rel).name`
    binds to the host -- a WindowsPath splits it on backslash, a
    PosixPath does not, so a backslash-bearing entry's "basename" would
    differ by host (ruling P49, assetstore.asset_sha/is_asset_name's own
    fix, b92637f). Currently dead ground, not a live bug: load_record
    already rejects any entry `is_asset_name` refuses -- including a
    backslash-bearing one -- before this function ever sees it, so `rel`
    here is always well-formed. Kept platform-correct anyway, on the same
    logic load_record's own docstring gives for closing this gap in a
    second file -- the mechanism, not today's reachability, is the
    property that must hold."""
    local = rid_dir / rel
    if local.is_file():
        if not assetstore.verify_bytes(PurePosixPath(rel).name, local.read_bytes()):
            corrupt.append(f"{entry_rel}: {rel}")
        return True
    if store is None:
        return False
    try:
        return assetstore.get_verified(store, PurePosixPath(rel).name) is not None
    except assetstore.AssetIntegrityError:
        corrupt.append(f"{entry_rel}: {rel}")
        return True


def _broken_link_clause(path: Path, display_root: Path) -> str:
    try:
        shown = path.relative_to(display_root)
    except ValueError:
        shown = path
    return (
        f"{shown}: could not be read -- may be a broken link or a vanished "
        "target; remove or restore whatever is at that path, then retry"
    )


def _walk_md_root(
    md_root: Path, display_root: Path, broken: list[str]
) -> tuple[set[str], list[Path]]:
    """One walk of `md_root` collecting (a) every asset basename directly
    inside an 'assets/' directory and (b) every markdown file's path --
    replacing the separate `root.glob("**/assets/*")` and
    `root.rglob("*.md")` calls this used to make.

    Walked with `os.walk(onerror=...)`, not `Path.glob`/`Path.rglob` (item
    2, wave L1 brief; measured pre-existing on 2fe4d62): both glob methods
    use pathlib's recursive '**' selector, which raises an uncaught
    FileNotFoundError partway through the walk when it meets a broken link
    anywhere under md_root -- reproduced here with a real broken NTFS
    junction: `Path("federation").glob("**/assets/*")` dies with
    `FileNotFoundError: [WinError 3] ... 'federation\\demo\\assets\\
    broken_junction'`, so `kb assets verify` exited 1 with a bare traceback
    and no message naming the way forward. `os.walk`'s `onerror` hook is
    the one traversal primitive that neither crashes nor silently drops the
    rest of the walk on a scandir failure at any depth: it names the exact
    path that could not be read and keeps going, so the broken path
    becomes a `[broken]` finding instead of an unhandled exception --
    consistent with the rest of this module, where verify is read-only and
    every read failure surfaces as a finding, never a raise (see
    _record_entries above). This is deliberately not symmetric with
    assetstore.load_record's dangling-link handling, which *raises*: that
    raise exists because a dangling link at a record path could otherwise
    be misread as "nothing to preserve" and drive migrate to delete the
    record while the store still holds the only copy -- a destructive
    action gated on the read. Nothing here is destructive; verify only
    reports what it found, so the read-only module norm applies instead.

    A filename that os.walk still hands back as "not a directory" but that
    Path.is_file() then refuses (a dangling POSIX symlink sitting directly
    inside assets/, which os.walk's own is_dir() check cannot distinguish
    from a real file without raising) is reported the same way, not
    silently excluded from local_names.
    """
    names: set[str] = set()
    md_files: list[Path] = []

    def _onerror(exc: OSError) -> None:
        path = Path(exc.filename or str(exc))
        broken.append(_broken_link_clause(path, display_root))

    for dirpath, _dirnames, filenames in os.walk(md_root, onerror=_onerror):
        dpath = Path(dirpath)
        is_assets_dir = dpath.name == "assets"
        for fname in filenames:
            fpath = dpath / fname
            if fname.endswith(".md"):
                md_files.append(fpath)
            if not is_assets_dir:
                continue
            if fpath.is_file():
                names.add(fname)
            else:
                broken.append(_broken_link_clause(fpath, display_root))
    return names, md_files


def verify_assets(handle, store=None) -> VerifyReport:
    """Read-only coverage check: record entries resolvable, markdown refs
    resolvable, orphan record entries listed (informational)."""
    if store is None:
        store = assetstore.store_for_hub(handle)  # None in mode: none
    report = VerifyReport()
    referenced: set[str] = set()
    recorded: dict[str, str] = {}  # basename -> "rid: relpath"

    for entry_rel, rid_dir in _rid_dirs(handle):
        for rel in _record_entries(entry_rel, rid_dir, report.corrupt):
            label = f"{entry_rel}: {rel}"
            # PurePosixPath, not Path -- same reasoning as _entry_resolves
            # above (item 6, wave L1 brief): recorded's keys are matched
            # against local_names/referenced below, both content-addressed
            # basenames, and must not depend on which host verify runs on.
            recorded[PurePosixPath(rel).name] = label
            if not _entry_resolves(rid_dir, rel, store, report.corrupt, entry_rel):
                report.missing_records.append(label)

    md_roots = [handle.federation_dir, handle.kb_dir]
    local_names: set[str] = set()
    md_files: list[Path] = []
    for root in md_roots:
        if not root.is_dir():
            continue
        names, files = _walk_md_root(root, handle.root, report.broken_links)
        local_names |= names
        md_files.extend(files)

    for md in md_files:
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
    report.missing_records.sort()
    report.corrupt.sort()
    report.broken_links = sorted(set(report.broken_links))
    return report
