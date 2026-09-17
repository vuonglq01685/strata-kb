from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import ValidationError

from center_kb import federation, ghio, gitio, models, pubgate
from center_kb import hub as hub_mod
from center_kb.errors import KbError
from center_kb.review import MACHINE_SECTION_PREFIX

logger = logging.getLogger("center_kb.publish")

_LEGACY_ID_RE = re.compile(r"(^|-)x\d+$")

# `git clean -e <spec>` takes a GITIGNORE PATTERN, not a path (task 21 fix
# round 5, I4-1/P38) -- see _gitignore_literal below.
_GITIGNORE_META_RE = re.compile(r"([\\\[\]*?!#])")

PR_BODY_TEMPLATE = (
    "Publish snapshot of repo '{rid}' @ {commit}.\n\n"
    "Merging this PR makes the content searchable across the federation."
)


class PublishError(KbError):
    """Publishing the snapshot to the hub failed."""


@dataclass
class PublishReport:
    repo_id: str
    source_commit: str
    n_docs: int
    pushed: bool
    mode: str = "direct"  # "direct" | "pr"
    pr_url: str = ""
    skipped: list[str] = field(default_factory=list)
    remote: bool = False


def _neutralize_excludes(root: Path) -> None:
    """federation/ is mirrored content wholly managed by publish() — the operator
    machine's global core.excludesFile (e.g. an editor ignoring "*.md" globally)
    must not be allowed to silently drop files from `git add`, which would make
    L2/L3 disappear from the commit even though they still "exists()" on the
    local disk. Set it locally (repo-scoped, does not touch the user's global
    gitconfig) — best-effort, publish still proceeds if this command fails.
    """
    subprocess.run(
        ["git", "config", "core.excludesFile", ""],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
    )


# Moved to federation.FED_TOP_EXCLUDE (F-D9 finding 5) so doctor.check_hub's
# namespace-level stray sweep shares this one definition instead of reaching
# into a private name in a sibling module -- kept as a local alias so every
# existing reference below stays unchanged.
_FED_TOP_EXCLUDE = federation.FED_TOP_EXCLUDE


def _record_assets(record_path: Path) -> list[str]:
    """`.assets` at `record_path`, or [] when absent/corrupt/unreadable.

    SOURCE-side reader only (task 21 fix round 3, P28) -- for the
    destination's own hub-owned record, use _dest_record_assets below
    instead; the two sides are not symmetric, see that function's docstring.

    Self-heals like assetstore._load_record (a stray bookkeeping file must
    not fail a whole publish) without reaching into that private helper
    across modules -- used by _snapshot_federation to read fed_src's own
    record (upstream data this hub does not own) before folding it into
    dest's.

    OSError is caught alongside the YAML/schema errors (task 21 fix round 2,
    N3/m2): _load_record catches bare Exception, so the two readers of the
    same on-disk file disagreed on exactly this one class -- an unreadable
    record (a permission bit, a lock) used to propagate straight out of
    _reconcile_asset_records' post-apply_sync window, past a guard that only
    caught AssetStoreError, and reproduce the C1 outage's exact permanent
    signature: raw bytes committed, changed=False on every retry, never
    repaired. Self-healing this side to [] is safe -- the hub's own record
    (read by _dest_record_assets) is authoritative, and nothing of the
    hub's is at risk when upstream data cannot be read.

    That last clause holds for the READ. It did not hold for what
    _reconcile_asset_records then DID with the result: Case A wrote these
    names into the hub-owned record unfiltered, so a mangled upstream name
    became the hub's problem after all, and cost the hub its record (wave
    I-1 round 4, the Critical's third door). Since that fix this function
    has exactly ONE caller, _inheritable_assets below, which applies the
    name-shape filter to everything it returns before any of it can reach
    a hub-owned record (wave I-1 round 5, Minor 2: the sentence here used
    to say the leniency was kept "for the call sites that only read", and
    after R2 there were none -- a reader would go looking for a set that
    is empty). The leniency is still correct and still load-bearing: it is
    what keeps a stray or half-written bookkeeping file in upstream data
    this hub does not own from failing the whole publish, which is
    precisely what _inheritable_assets relies on when it drops-and-warns
    instead of raising.
    """
    if not record_path.is_file():
        return []
    try:
        return models.load_yaml_model(record_path, models.AssetsRecord).assets
    except (yaml.YAMLError, ValidationError, ValueError, OSError) as exc:
        logger.warning("%s unreadable (%s) — treating as empty", record_path, exc)
        return []


def _dest_record_assets(record_path: Path) -> list[str]:
    """`.assets` at a hub-owned DESTINATION record; [] only when the file is
    genuinely absent -- an unreadable or corrupt one raises instead of
    self-healing (task 21 fix round 3, P28, correcting this round's own
    ruling from round 2).

    Not a twin of _record_assets above. Round 2 widened _record_assets'
    except to include OSError so an unreadable record would self-heal, which
    is right for the SOURCE side (N3) but was wrong here: this reads THIS
    hub's own bookkeeping file, whose names may be the only surviving
    pointer into this hub's asset store. Self-healing an unreadable read to
    [] let the union-merge in _reconcile_asset_records overwrite the file
    with the source's names alone (dropping whatever the unreadable file
    actually held), and when active_store was set, assetstore.
    divert_and_record's own read of the same file (bare `except Exception`)
    saw the same "empty" and unlinked it outright once nothing else
    remained to write -- an unreadable file became a deleted file. The
    corrupt-YAML variant is milder (the file survives, truncated to the
    source's names) but the same principle applies: never delete or
    overwrite data on the strength of a failed read of that data. The two
    sides are not symmetric -- the source's own record is upstream data the
    hub does not own (self-heal is correct there); this is hub-owned data
    with nothing else backing it up.

    Raising a plain OSError (not a new exception type) keeps the failure
    inside _reconcile_asset_records' existing `except (assetstore.
    AssetStoreError, OSError)` arm -- same scoped restore, same message
    naming the file, same non-zero exit through cli.py's existing OSError
    handling -- with no new catch needed anywhere and no call into
    assetstore.divert_and_record (whose own read would otherwise repeat the
    same mistake) once this has already raised.

    Wave I-1 round 3 (P47, Important 3): this had no present-but-empty
    check, the one gap left in P47 at the third of three call sites --
    measured on the tree, a zero-byte DESTINATION record gave `record
    after: False` (unlinked), the exact deletion closed at the other two
    call sites (assetcmd.migrate_assets, intake._publish_in_worktree) via
    assetstore.load_record. Grown in place rather than collapsed into that
    function: see load_record's own docstring ("Made public...") for why --
    in short, collapsing would swap this function's OSError for
    AssetStoreError, and _reconcile_asset_records' read_failed flag (which
    protects an untracked record from the restore's `git clean` half) only
    watches for OSError at its inner boundary, so the swap would need to
    widen that except too or silently regress ruling P33. Also picks up
    load_record's other wave I-1 round 3 fix (Important 1): is_file() alone
    would read a directory-shaped record as absent, which is the same P47
    violation one level removed -- restore-or-remove-it, not delete.

    Wave I-1 round 4 (Critical): round 3 stopped there and left
    assetstore.load_record's OTHER two new checks -- per-entry name shape
    and trailing newline -- on the source-of-truth side only. That
    asymmetry deleted records. Measured end to end through a real
    hub-to-hub publish with no monkeypatch, through three independent
    doors: a truncated destination record and a newline-stripped one both
    sailed past this function (no raise, so no read_failed, no abort, no
    restore), _reconcile_asset_records went on to call assetstore.
    divert_and_record on the same entry, ITS read of the SAME file went
    through load_record, which DID have the checks and raised, its
    deliberate self-heal turned that into `existing = []`, and with
    nothing left to re-divert the merged set was empty and the record was
    unlinked outright -- porcelain `D federation/.../_assets.yaml`, exit 0,
    the object store left holding the only copy. Round 3's own premise
    (save_yaml_model's non-atomic write producing truncated records) was
    therefore made strictly WORSE at the destination by the commit that
    added the detector: before it, all three doors left the record in
    place. Two readers of one file must not disagree about what counts as
    readable, so the checks below are the same ones, in the same order,
    against the same module-owned regex -- only the exception type differs,
    and it must (see above: OSError is what read_failed watches for).

    Wave I-1 round 5 (Critical, ruling P49): round 4's checks below keyed
    on `Path(a).name`, and `Path` is WindowsPath here and PosixPath on CI,
    so a backslash-spelled record entry was accepted on a Windows hub and
    raised on a Linux one -- a platform split in a data-loss-adjacent
    guard, and three red CI legs. The name-shape question now goes through
    assetstore.is_asset_name, which takes the basename with POSIX
    semantics on every host; see its docstring for why a backslash in a
    record entry is an ordinary character rather than a separator, and for
    the two places this codebase had already ruled that (divert_assets'
    as_posix() write and pubgate.is_kb_artifact's backslash refusal).

    The third door is not here: a truncated SOURCE record reaches the
    hub-owned record through _reconcile_asset_records' `inherited` merge,
    which reads fed_src with the fully lenient _record_assets and used to
    write whatever it found straight into dest's record -- past this
    function entirely, because this function had already returned by then.
    That one is closed at the merge, in _reconcile_asset_records.
    """
    from center_kb import assetstore

    if not record_path.is_file():
        # os.path.lexists(), not Path.exists() -- wave I-1 round 4, Minor 4;
        # see assetstore.load_record's matching branch for the measurement
        # (a broken NTFS junction reads exists=False, lexists=True, and the
        # "absent" answer flows on into the very deletion this branch exists
        # to prevent).
        if os.path.lexists(record_path):
            raise OSError(
                f"{assetstore.not_a_regular_file_clause(record_path)}, and "
                "this hub's own asset record may name the only surviving "
                "copy of some assets in the store; refusing to treat it as "
                "absent. remove or restore whatever is at that path so it "
                "is either a regular record file or genuinely absent, then "
                "retry the publish."
            )
        return []
    try:
        raw_text = record_path.read_text(encoding="utf-8")
        record = models.load_yaml_model(record_path, models.AssetsRecord)
    except (yaml.YAMLError, ValidationError, ValueError, OSError) as exc:
        raise OSError(
            f"{record_path} exists but could not be read ({exc}) -- this hub's "
            "own asset record may name the only surviving copy of some assets "
            "in the store; refusing to overwrite or delete it. "
            f"{assetstore.restore_clause(record_path)}, or fix the "
            "permissions/lock, then retry the publish."
        ) from exc
    if not record.assets:
        raise OSError(
            f"{record_path} exists but names no assets -- nothing in this "
            "codebase writes that shape (an entry with nothing left to "
            "divert has its record deleted, not written empty), so a "
            "present-but-empty record is evidence of a truncated or "
            "interrupted write, not evidence the assets are gone; this "
            "hub's own asset record may name the only surviving copy of "
            "some assets in the store, refusing to overwrite or delete it. "
            f"{assetstore.restore_clause(record_path)}, or confirm the "
            "assets really were removed and delete the file outright, then "
            "retry the publish."
        )
    bad = [a for a in record.assets if not assetstore.is_asset_name(a)]
    if bad:
        raise OSError(
            f"{record_path} {assetstore.bad_name_clause(bad)} "
            "(<sha256>.png or .webp) -- evidence of a write truncated "
            "mid-path, not a legitimate shorter list (this tree's record "
            "writers, assetstore.divert_and_record and this module's own "
            "_reconcile_asset_records, are both is_asset_name-fenced and "
            "only ever persist names matching that shape). "
            "this hub's own asset record may name the only surviving copy "
            "of some assets in the store, refusing to overwrite or delete "
            f"it. {assetstore.restore_clause(record_path)}, or confirm the "
            "record really is this short and rewrite it, then retry the "
            "publish."
        )
    if not raw_text.endswith("\n"):
        raise OSError(
            f"{record_path} does not end with a trailing newline -- every "
            "record this codebase writes does (models.save_yaml_model's "
            "yaml.safe_dump always terminates one), so a missing one is "
            "evidence of a truncated write, not a complete list. this "
            "hub's own asset record may name the only surviving copy of "
            "some assets in the store, refusing to overwrite or delete it. "
            f"{assetstore.restore_clause(record_path)}, or confirm the "
            "record really is complete and rewrite it, then retry the "
            "publish."
        )
    return record.assets


def _inheritable_assets(src_record_path: Path, dest_record_path: Path) -> list[str]:
    """The source record's names, minus any that are not content-addressed
    asset names -- what _reconcile_asset_records' Case A may merge INTO this
    hub's own record.

    Wave I-1 round 4, the Critical's third door. _record_assets (above) is
    deliberately, correctly lenient: fed_src's record is upstream data this
    hub does not own, and a stray bookkeeping file there must not fail a
    whole publish. But Case A does not merely READ that data -- it writes it
    into the hub-owned destination record, at which point a mangled upstream
    name becomes this hub's problem. Measured end to end with real git and
    no monkeypatch: a SOURCE record truncated mid-path was merged verbatim
    into an otherwise-perfect destination record, assetstore.
    divert_and_record's own read of that freshly-written file then rejected
    it (assetstore.load_record's name-shape check), its self-heal turned the
    raise into `existing = []`, and with nothing left to re-divert the
    record was unlinked -- porcelain `D federation/.../_assets.yaml`, exit 0,
    the object store holding the only copy. Hardening _dest_record_assets
    alone does not close this one: the destination record was fine when it
    was read; the corruption arrived afterwards, in the merge.

    Dropping rather than raising is the right shape here for the same reason
    _record_assets self-heals: an upstream record this hub does not own must
    not be able to fail the publish. It is also the precedent already set by
    assetstore.synthesized_asset_entries, which silently skips exactly the
    names this skips -- so a name dropped here was never going to be
    transferable anyway. The drop is warned about rather than silent,
    following this module's own rule (see the `dropped` loop below): a thing
    the system drops must be a thing the operator can see it dropped.
    """
    from center_kb import assetstore

    names = _record_assets(src_record_path)
    keep = [a for a in names if assetstore.is_asset_name(a)]
    for name in sorted(set(names) - set(keep)):
        logger.warning(
            "%s names %r, which is not a content-addressed asset name "
            "(<sha256>.png or .webp) -- not merged into %s; the upstream "
            "record looks truncated mid-path, and merging it would make "
            "this hub's own record unreadable to its own writers. restore "
            "the source record from its last known-good commit and publish "
            "again to carry that name up.",
            src_record_path.as_posix(),
            name,
            dest_record_path.as_posix(),
        )
    return keep


def _gitignore_literal(spec: str) -> str:
    """`spec` escaped so git matches it as a literal path, for the one
    place this codebase hands a path to a gitignore-pattern argument
    (`git clean -e`) -- task 21 fix round 5, ruling P38.

    `-e` does NOT take a path. Measured on git 2.45.1 with real
    directories: `-e 'federation/mid/a[b]c/_assets.yaml'` DELETED
    `a[b]c/_assets.yaml` (the file it was added to protect -- the exact
    P28 deletion the exclusion exists to prevent, re-opened) and SPARED
    `abc/_assets.yaml` instead, because the character class `[b]` matched
    `abc`. Defeat and widening in one run, silently. `[` and `]` are legal
    filenames on both platforms, and `pubgate.REPO_ID_RE` only covers
    segments that arrive through publish/intake -- a hand-created or
    merge-introduced entry directory has no such guard.

    Escaping every wildmatch/gitignore metacharacter (`\\ [ ] * ? ! #`)
    makes the pattern match exactly one literal path; re-measured on the
    same shape, the target survived and the bystander was swept, and a
    spurious escape on an ordinary character (`\\.`, `\\-`) is a no-op.
    Trailing whitespace (stripped by gitignore unless escaped) cannot end
    one of these patterns: the last segment is always assetstore.
    RECORD_NAME, and a leading `!`/`#` is likewise unreachable because the
    pattern always begins `federation/` -- both are escaped anyway so the
    helper is correct for any input rather than only for today's callers.
    """
    return _GITIGNORE_META_RE.sub(r"\\\1", spec)


def _restore_federation_after_store_failure(
    handle: hub_mod.HubHandle, dest: Path, *, protect: Path | None = None
) -> None:
    """`git checkout -- <entry>` + `git clean -fd -- <entry>` on handle.root,
    scoped to `dest` (this publish's own federation/<rid> entry, never the
    whole federation/ tree), best-effort (logs on failure, never raises on
    its own).

    `protect`, when given, is a path under dest excluded from the `git
    clean` half (`git clean -fd -e <protect>`, the spec run through
    _gitignore_literal first -- `-e` is a gitignore PATTERN, not a path,
    and an unescaped `[`/`]` in the path both failed to protect it and
    wrongly spared a different record; see that helper, ruling P38) even
    when untracked (task 21 fix round 4, P33/M-2 -- the narrower alternative to a blanket
    checkout-only restore for a dest-record read failure, see
    _reconcile_asset_records). A hub-owned record this hub just refused to
    read may be an entry's only surviving pointer into the store -- unlike
    a plain mirrored file or a not-yet-diverted raw asset copy, which is
    always re-copyable from fed_src on the next apply_sync, losing the
    record is not something a later publish can re-derive.

    Excluding just the record from `git clean`, rather than skipping the
    whole clean half for that cause (the ruling's original framing),
    matters: a scratch measurement showed the blanket skip is unsafe. Its
    scenario -- a brand-new raw asset apply_sync had already copied into
    the SAME entry, moments before a read failure fired on that entry's
    (already-committed, unrelated) record -- survived a checkout-only
    restore untracked (`git checkout` never touches untracked paths), then
    matched dest against fed_src as "unchanged" on every retry thereafter:
    never diverted, never committed, no durable copy anywhere -- worse than
    the original C1 signature, not safer. Excluding only the record keeps
    that raw asset inside the ordinary cleaned set, restoring the
    all-or-nothing guarantee for everything except the one path whose loss
    is genuinely irreversible.

    Shared by _snapshot and _snapshot_federation/_reconcile_asset_records:
    both call assetstore.divert_and_record only after apply_sync has
    already written asset bytes (and any other changed/deleted files) into
    the hub clone's working tree. Left uncleaned after a failure, a retry
    with a healthy store would see dest's manifest already match the
    source's (bytes already copied by apply_sync) and early-return
    "unchanged" *before* ever reaching divert again -- so _publish_direct /
    _publish_pr would then git-add + commit those leftover binaries straight
    into hub git, and no later publish would ever repair it. Restoring dest
    to its last committed state before the caller re-raises is what stops
    that (mirrors intake.intake_publish's matching guard for the same
    failure mode, which operates on a worktree path instead of handle.root
    and raises a different error type, so it is not folded into this same
    helper).

    Scoped to `dest`, not "federation" (task 21 fix round 2, N1): for a
    local-path hub, hub.resolve_hub hands back the operator's own directory
    directly -- there is no clone in between -- so this used to run against
    the operator's real working copy, over the whole federation/ tree.
    Measured: an unrelated tracked edit elsewhere under federation/ got
    reverted, and an unrelated untracked draft got deleted -- a publish that
    fails must leave everything it did not write exactly as it found it.
    Both call sites only ever write under dest = handle.federation_dir / rid
    (checked by the is_relative_to guard each caller runs before writing
    anything), so a pathspec scoped to dest always covers everything this
    failure could have left behind, and never touches anything outside it.
    """
    pathspec = dest.resolve().relative_to(handle.root.resolve()).as_posix()
    co = gitio._run(handle.root, "checkout", "--", pathspec)
    if co.returncode != 0:
        logger.warning(
            "git checkout -- %s failed while restoring after an "
            "asset store failure: %s", pathspec, co.stderr.strip()
        )
    clean_args = ["clean", "-fd"]
    if protect is not None:
        try:
            protect_rel = protect.resolve().relative_to(handle.root.resolve())
        except ValueError:
            # Unreachable today (`protect` is always a record under `dest`),
            # but this function is documented never to raise on its own and
            # is only ever called mid-abort -- a ValueError here would
            # replace the caller's original OSError with a worse one. The
            # `checkout` half above already relies on the same containment;
            # dropping the exclusion is the safe degradation (the clean is
            # scoped to `dest`, so a path outside it was never at risk).
            logger.warning(
                "%s is outside %s — cannot exclude it from the restore's "
                "clean; continuing without the exclusion", protect, handle.root
            )
        else:
            clean_args += ["-e", _gitignore_literal(protect_rel.as_posix())]
    clean_args += ["--", pathspec]
    cl = gitio._run(handle.root, *clean_args)
    if cl.returncode != 0:
        logger.warning(
            "git clean -fd -- %s failed while restoring after an "
            "asset store failure: %s", pathspec, cl.stderr.strip()
        )


def _snapshot(
    kb_abs: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    source_url: str | None = None,
    store=None,
) -> tuple[int, bool, list[str]]:
    """Sync .kb/ → federation/<rid>/ by hash-diff; return (n_docs, changed, skipped).

    `skipped` is the sorted list of relpaths in the local snapshot that
    pubgate.is_kb_artifact() refused to mirror (config.yaml, dotfiles, stray
    non-.kb artefacts) — see PublishReport.skipped.

    changed=False: content on the hub already matches the local snapshot byte
    for byte — nothing is written, not even _meta.yaml (published_at only
    moves when content actually changed, so a back-to-back 2nd publish is a
    true no-op: no commit, no PR).

    The aggregate index.yaml is NOT written here — see publish()/_publish_direct():
    index.yaml is committed separately from the <rid>/ commit so that two repos
    publishing for the first time into one empty hub (federation/index.yaml does
    not exist yet) can never hit an "add/add" conflict on rebase (two branches
    each newly creating one file at the same path with different content is a
    conflict that cannot be auto-merged, whatever the rebase strategy).
    """
    from center_kb import assetstore, hashsync

    dest = handle.federation_dir / rid
    fed_root = handle.federation_dir.resolve()
    if not dest.resolve().is_relative_to(fed_root):
        raise PublishError(
            f"repo-id '{rid}' escapes the federation/ directory on the hub — refusing to publish"
        )
    try:
        active_store = store if store is not None else assetstore.store_for_hub(handle)
    except (yaml.YAMLError, ValidationError, ValueError) as exc:
        # store_for_hub reads the HUB's own .kb/config.yaml (asset_store:) --
        # a corrupt one must name itself, not the caller's (F-D9 finding 2).
        raise PublishError(
            f"{handle.kb_dir / 'config.yaml'} (the hub's own config) is "
            f"unreadable: {exc}"
        ) from exc
    index_path = kb_abs / "index.yaml"
    try:
        local_index = models.load_yaml_model(index_path, models.KBIndex)
    except (yaml.YAMLError, ValidationError, ValueError) as exc:
        raise PublishError(f"{index_path} is unreadable: {exc}") from exc
    local_man = hashsync.build_manifest(kb_abs)
    local_man, skipped = pubgate.split_allowlist(local_man)
    dest_man = hashsync.build_manifest(
        dest, exclude=("_meta.yaml", assetstore.RECORD_NAME)
    )
    if active_store is not None:
        dest_man.update(assetstore.synthesized_asset_entries(dest))
    changed, deleted = hashsync.diff_manifests(local_man, dest_man)
    if not changed and not deleted:
        return len(local_index.docs), False, skipped
    hashsync.apply_sync(kb_abs, dest, changed, deleted)
    if active_store is not None:
        try:
            assetstore.divert_and_record(dest, active_store, deleted)
        except assetstore.AssetStoreError:
            # apply_sync above already wrote asset bytes (and any other
            # changed/deleted files) into the hub clone's working tree
            # before this failed -- see _restore_federation_after_store_failure
            # for why an uncleaned failure here is unrecoverable.
            _restore_federation_after_store_failure(handle, dest)
            raise
    meta = federation.FederationMeta(
        repo_id=rid,
        source_url=(
            source_url
            if source_url is not None
            else gitio.remote_url(gitio.git_root(kb_abs))
        ),
        source_commit=source_commit,
        published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    models.save_yaml_model(dest / "_meta.yaml", meta)
    return len(local_index.docs), True, skipped


def _iter_record_dirs(root: Path, record_name: str) -> list[tuple[str, Path]]:
    """(path-id, dir) of every directory under root directly holding a
    `record_name` file, DFS by name -- found the same way
    hashsync.build_manifest finds files (root.rglob, no leaf predicate)
    rather than through federation.iter_entry_dirs' _meta.yaml-AND-
    index.yaml leaf predicate (task 21 fix round 2, N4/P18).

    _prepare_hub_to_hub_manifests used to enumerate entries for both the
    per-entry asset-name synthesis and the RECORD_NAME pop via
    iter_entry_dirs, but the manifests it populates are built by
    build_manifest, which has no leaf predicate at all. An entry that is a
    valid leaf when its record is written can stop being one on a later
    publish (its _meta.yaml or index.yaml goes missing -- a state
    federation.py explicitly tolerates, warned rather than rejected) without
    the record disappearing from disk. iter_entry_dirs then walks straight
    past it, so neither the synthesis (which keeps an already-diverted
    asset's path "looking present" at the entry that diverted it) nor the
    pop (which excludes the record from the plain file-diff) ever runs for
    it again -- measured: the hub-owned record then reads as "deleted" on
    the far side (popped there, not here) and gets removed while the store
    may hold its only copy, and a raw binary the divert already stripped
    out reads as "changed" and gets copied straight back into hub git. Both
    outcomes are exactly what this task exists to prevent. Enumerating by
    the record's own presence on disk, the same way build_manifest
    enumerates files, is what keeps the two from disagreeing about what
    counts as an entry with a record.
    """
    if not root.is_dir():
        return []
    return sorted(
        (p.parent.relative_to(root).as_posix(), p.parent)
        for p in root.rglob(record_name)
        if p.is_file() and not p.is_symlink()
    )


def _prepare_hub_to_hub_manifests(
    fed_src: Path, dest: Path, active_store
) -> tuple[dict[str, str], dict[str, str], list[str], set[str], list[str]]:
    """Build (src_man, dest_man, skipped, synthesized_src_only,
    dest_raw_assets) for _snapshot_federation's diff.

    `dest_raw_assets` is the sorted dest-relative paths of every file
    physically sitting at the destination that assetstore.divert_assets
    would divert -- the probe that keeps _snapshot_federation's early
    return from skipping _reconcile_asset_records on a publish whose plain
    file diff is empty (task 21 fix round 5, ruling P37; see that early
    return). Read straight off the freshly-built dest manifest BEFORE the
    dest-side synthesis below adds already-diverted names to it, so it
    costs no filesystem I/O at all: build_manifest has just walked and
    hashed every regular file under dest, and its keys ARE the physically
    present ones (synthesized names are exactly the assets with no bytes
    left on disk, which is why they must not be counted here). The
    predicate is divert_assets' own -- a file directly inside a directory
    named `assets` whose name is content-addressed -- matched against
    assetstore's single definition of that name rather than a copy, so
    the gate and the divert cannot drift apart about what "divertible"
    means (the class of disagreement N4/P18 and P31 were both about).
    build_manifest skips symlinks, so a symlinked asset is not counted;
    hashsync.apply_sync copies regular files only, so one cannot arrive
    at dest through a publish.

    RECORD_NAME (_assets.yaml) is popped from BOTH manifests
    unconditionally, whether or not active_store is set. A plain file-diff
    on it is never safe once this hub has ever driven its lifecycle through
    _reconcile_asset_records: fed_src's copy (if any) would look stale and
    get overwritten, and a record this hub wrote itself (fed_src never had
    one) would look deleted on the very next publish and get wiped --
    confirmed by running it. Popping it unconditionally, on both sides,
    means a publish where THIS hub currently has no store leaves whatever
    dest already holds untouched instead of deleting or truncating it (I5)
    -- _reconcile_asset_records' union-merge (also unconditional) is what
    actually grows it; nothing here ever shrinks it.

    The per-entry SOURCE-side asset-name synthesis (the loop over
    _iter_record_dirs(fed_src, ...)) is unconditional for the same reason,
    one level down: an asset already recorded at or below the source (Case A
    -- migrated there, no physical bytes left in fed_src) must "look
    present" in src_man even when this hub has no store of its own, or a raw
    copy already sitting at dest from an earlier, storeless publish reads as
    absent-from-source and apply_sync deletes it -- precisely "migrated
    assets look deleted to an upstream hub", the outcome item 3 exists to
    prevent (I6). synthesized_src_only tracks these paths (no physical file
    anywhere in fed_src -- apply_sync's shutil.copy2 would crash on them) so
    the caller can keep them out of `changed`; their names still reach dest
    through _reconcile_asset_records' Case A, which reads fed_src's record
    directly and does not depend on this diff at all.

    The per-entry DEST-side asset-name synthesis stays gated on
    active_store: its purpose -- stop a still-raw source copy from diffing
    as "changed" forever and being recopied over an asset THIS hub already
    diverted -- only applies while this hub is actively diverting. With no
    store, a stale raw source copy reappearing at dest is a redundant
    mirror of content the source still has, not a loss.

    Both loops walk _iter_record_dirs, not federation.iter_entry_dirs (task
    21 fix round 2, N4/P18): see that function's docstring for why a
    leaf-validity predicate misses entries a plain manifest walk still
    finds, and what breaks when the two disagree.
    """
    from center_kb import assetstore, hashsync

    src_man = hashsync.build_manifest(fed_src, exclude=_FED_TOP_EXCLUDE)
    # keep_records=True: an _assets.yaml already mirrored from a lower hub
    # must not be dropped by the allowlist filter before the RECORD_NAME
    # handling below ever sees it (_snapshot's dest_man drops it outright
    # instead -- see publish.py's _snapshot docstring -- because a child's
    # .kb/ never has one to begin with; here it is hub-written content
    # genuinely being mirrored upward).
    src_man, skipped = pubgate.split_allowlist(src_man, keep_records=True)
    synthesized_src_only: set[str] = set()
    for entry_rel, entry_dir in _iter_record_dirs(fed_src, assetstore.RECORD_NAME):
        for rel, sha in assetstore.synthesized_asset_entries(entry_dir).items():
            path = f"{entry_rel}/{rel}"
            src_man[path] = sha
            synthesized_src_only.add(path)
        src_man.pop(f"{entry_rel}/{assetstore.RECORD_NAME}", None)
    dest_man = hashsync.build_manifest(dest)
    dest_raw_assets = sorted(
        rel
        for rel in dest_man
        if rel.count("/") >= 1
        and rel.rsplit("/", 2)[-2] == "assets"
        and assetstore.is_asset_name(rel)
    )
    for entry_rel, entry_dir in _iter_record_dirs(dest, assetstore.RECORD_NAME):
        if active_store is not None:
            for rel, sha in assetstore.synthesized_asset_entries(entry_dir).items():
                dest_man[f"{entry_rel}/{rel}"] = sha
        dest_man.pop(f"{entry_rel}/{assetstore.RECORD_NAME}", None)
    return src_man, dest_man, skipped, synthesized_src_only, dest_raw_assets


def _asset_entry_root(parts: tuple[str, ...], leaves: frozenset[str]) -> str | None:
    """The dest-relative path-id of the entry owning a divertible asset
    file whose dest-relative path is `parts`; None when no entry encloses
    it at all.

    `leaves` is federation.iter_entry_dirs' own path-ids -- authoritative
    by definition (ruling P39), so the nearest enclosing one wins outright.
    Checking it first is what stops a deeper-than-usual asset
    (`<entry>/<doc-id>/sub/assets/<name>`) from manufacturing a candidate
    BELOW a real entry, which round 4 then dropped and reported as a
    skipped `<entry>/<doc-id>/_assets.yaml` that does not exist (M4-1).

    With no enclosing leaf -- a marker-less entry, exactly the C-1 shape
    this member exists for -- fall back to the layout: `<entry>/<doc-id>/
    assets/<name>`, three up from the file, which is right at any
    namespace depth because it walks UP from the file rather than down a
    fixed count from dest. `<entry>/assets/<name>` (one level shallower)
    is legal too -- assetstore.divert_assets matches `assets/*` at ANY
    depth and pubgate.is_kb_artifact's asset rule is explicitly
    depth-independent, so it mirrors to dest, and the plain-publish path
    (_snapshot -> divert_and_record(dest)) diverts it correctly; round 4's
    fixed arithmetic resolved it to the walk root and silently skipped it,
    leaving raw bytes committed with changed=False forever (M4-3). Two
    parents up covers it.

    `assets/<name>` directly under the walk root has no entry above it at
    all: diverting it would write the record at namespace depth, the exact
    wrong-depth artefact spec 11.2 forbids, so the caller reports it and
    leaves the bytes alone instead. Every root returned is a lexical
    prefix of a path rglob yielded under dest, so it is always inside the
    scope this function may touch -- no resolve()/relative_to() round trip,
    and therefore no ValueError arm to swallow a real case (the arm that
    silently hid this one).
    """
    for i in range(len(parts) - 1, 0, -1):
        cand = "/".join(parts[:i])
        if cand in leaves:
            return cand
    if len(parts) >= 4:  # <entry>/<doc-id>/assets/<name>
        return "/".join(parts[:-3])
    if len(parts) >= 3:  # <entry>/assets/<name>
        return "/".join(parts[:-2])
    return None  # assets/<name> -- the walk root itself is not an entry


def _reconcile_asset_records(
    fed_src: Path, dest: Path, handle: hub_mod.HubHandle, active_store
) -> bool:
    """Per-entry RECORD_NAME reconciliation after apply_sync. Returns
    whether this pass changed the destination tree -- a record's bytes
    changed, or a divert physically removed raw bytes from it (task 21 fix
    round 5: the second half used to be missing, so a divert that merged no
    NEW name into the record reported changed=False, _publish_direct never
    committed, and the hub clone was left holding an uncommitted deletion).
    Candidates dropped from the union are warned about directly rather than
    returned for PublishReport.skipped -- see the filter loops below (M4-1).

    Case A (union-merge, unconditional): names fed_src's own entry already
    recorded -- diverted at or below the source, no raw bytes anywhere in
    fed_src for divert_assets to find here -- must still reach dest's
    record, or excluding RECORD_NAME from the diff in
    _prepare_hub_to_hub_manifests would silently drop them instead of
    merely deferring their transfer. This runs regardless of active_store:
    it is a plain merge of two name sets, needs no store, and a union never
    deletes or truncates what dest already has (I5) -- when this hub has no
    store, this is the only thing still growing the record; when fed_src has
    nothing new (`inherited` empty), dest's own record is left exactly as
    it is, whether or not active_store is set. What may be inherited is
    filtered by _inheritable_assets (wave I-1 round 4, the Critical's third
    door): a name that is not content-addressed cannot be transferred
    anyway, and merging one into the hub-owned record made that record
    unreadable to assetstore.load_record -- whose caller then deleted it.

    Case B (divert, gated on active_store): still-raw asset bytes that just
    landed under dest (copied in from a mid-tier hub with no store of its
    own) get swept into THIS hub's store and merged into dest's own
    _assets.yaml, exactly like a direct child publish would (_snapshot,
    above). Needs a real store, so it only runs when active_store is set.

    The whole per-entry body (Case A's read+write AND Case B's divert) runs
    inside one try/except, not just the divert call (task 21 fix round 2,
    N3): Case A's models.save_yaml_model write is unconditional now, and can
    raise OSError (a lock, a full disk, a permission bit) exactly like a
    store outage can -- the same unrecoverable-retry hazard
    _restore_federation_after_store_failure exists to prevent, but with no
    restore attempted at all if the guard only wrapped divert_and_record.
    OSError is caught alongside AssetStoreError for the same reason --
    _record_assets self-heals its own OSErrors now (see that function), so
    the one left here is the union-merge's write. The DESTINATION record is
    read with _dest_record_assets, not _record_assets (task 21 fix round 3,
    P28): an unreadable destination record raises OSError -- caught by this
    same except, restored and re-raised loudly -- instead of self-healing to
    [] and letting the merge (or divert_and_record's own read of the same
    file) overwrite or delete a record that may be the only surviving
    pointer into this hub's store. The read happens unconditionally, before
    both Case A's write and Case B's divert, so an unreadable record is
    caught before divert_and_record is ever called for this entry -- not
    just when Case A's union-merge would otherwise have run.

    The entries walked are the union of federation.iter_entry_dirs(dest)
    (valid leaves), _iter_record_dirs(dest, RECORD_NAME) (task 21 fix round
    3, R2), and every directory that could CONTAIN divertible bytes (task
    21 fix round 4, P31 -- below), not federation.iter_entry_dirs(dest)
    alone. No two members of the union are enough by themselves: the leaf
    predicate alone misses a half-broken entry (its _meta.yaml or
    index.yaml gone, a state federation.py explicitly tolerates) that
    already has a record and then receives a brand-new raw asset -- Case B
    never runs for it, so the new bytes are never diverted and are
    committed into hub git on this publish's own commit, changed=False on
    every retry thereafter, the C1 signature, reached through the exact
    branch N4/P18 was about. The record-presence walk alone would miss the
    far more common opposite case: a brand-new entry, still a fully valid
    leaf, that has never had a record before -- Case B is what *creates*
    that first record, so skipping every entry without one yet would break
    ordinary first-time hub-to-hub asset diversion outright.

    Ruling P31 (task 21 fix round 4, C-1): the first two members both key on
    something an entry must already HAVE -- a valid leaf pair or an
    existing record. An entry with NEITHER (an interrupted publish on or
    before its *first* ever divert, so no record was ever written; the
    brief's own motivating input) is in no walk at all, so Case B never
    runs for it either, while hashsync.build_manifest (no leaf predicate)
    still puts its raw asset bytes in src_man and apply_sync copies them
    straight into the hub tree -- character for character the original
    Critical, and `kb assets migrate` does not repair it later either,
    since assetcmd.migrate_assets enumerates with federation.iter_entry_dirs
    too. The third member closes this: every file assetstore.divert_assets
    itself would find (the same `rglob("assets/*")` basis), attributed to
    its entry by _asset_entry_root -- see that function for how the root is
    chosen and why the fixed `f.parent.parent.parent` arithmetic round 4
    shipped was not enough on its own (M4-3).

    Only a symlinked asset FILE is skipped here. The claim this docstring
    used to make -- that this "mirrors federation.iter_entry_dirs' own
    symlinked-dir guard" -- was broader than the code (task 21 fix round 5,
    M4-2): `rglob("**/assets/*")`'s `**` does not descend into symlinked
    directories, but the literal `assets` component is matched through
    is_dir(), which follows one, so a symlinked `assets` DIRECTORY is still
    entered and assetstore.divert_assets would unlink through it. Not a new
    exposure (divert_assets has always behaved that way, and
    hashsync.apply_sync copies regular files only, so a symlink cannot
    arrive at dest through a publish) and NOT verified here: this
    environment refuses os.symlink outright (WinError 1314), so the claim
    is narrowed to what can be read off the code rather than widened to
    something no test in this tree can exercise.

    Ruling P39 (task 21 fix round 5, C4-2), which corrects ruling P34: the
    discriminator for what counts as an entry ROOT in this union is
    AUTHORITY first and containment second, and only the containment half
    of P34 survives. The full reasoning sits with the two filter loops
    below, next to the code that implements it.
    """
    from center_kb import assetstore

    record_changed = False
    entries: dict[str, Path] = dict(federation.iter_entry_dirs(dest))
    leaves = frozenset(entries)
    entries.update(_iter_record_dirs(dest, assetstore.RECORD_NAME))
    dropped: list[tuple[str, str]] = []
    for asset_file in sorted(dest.rglob("assets/*")):
        if asset_file.is_symlink() or not asset_file.is_file():
            continue
        parts = asset_file.relative_to(dest).parts
        entry_rel = _asset_entry_root(parts, leaves)
        if entry_rel is None:
            dropped.append((
                "/".join(parts),
                "sits directly under the walk root, so no entry directory "
                "encloses it -- its bytes are left raw rather than diverted "
                "into a record at namespace depth (spec 11.2 fixes the record "
                f"at <entry>/{assetstore.RECORD_NAME})",
            ))
            continue
        entries.setdefault(entry_rel, dest.joinpath(*entry_rel.split("/")))

    # Ruling P39 (task 21 fix round 5, C4-2), correcting P34: the
    # discriminator is AUTHORITY, not structure. Every directory
    # federation.iter_entry_dirs yields is an entry by definition -- that is
    # the enumeration every reader uses and the one spec §11.2 fixes -- so
    # it must always be its own divert root and must never be dropped or
    # subsumed. P34 had only the structural half ("a proper descendant of
    # another candidate is not an entry"), which is backwards the moment any
    # other member yields a directory ABOVE a real entry: measured on a
    # legacy namespace-level _assets.yaml (the artefact the old `kb assets
    # migrate` bug left behind, per assetcmd._rid_dirs' own docstring) the
    # leaf was deleted from the union, the record was written one level too
    # high, and the record every reader consults never learned the new
    # asset's name while the store held its only copy. Silently.
    #
    # So: first drop every non-leaf candidate that is a proper ANCESTOR of a
    # leaf (it is a namespace, not an entry), then P34's surviving half --
    # drop what is left that is a proper DESCENDANT of another candidate
    # (M-3's stray record below entry level, which fed to divert_and_record
    # as its own entry would be walked a second time over bytes the true
    # entry's pass already consumed, and would be unlinked outright if it
    # happened to be empty). Leaves are exempt from both loops, so P39's
    # property holds unconditionally rather than by an argument about what
    # the other members can produce. String prefix on the path-id is enough:
    # every id here came from the same dest-relative posix join, so a
    # genuine descendant always starts with "<ancestor>/".
    for entry_rel in sorted(entries):
        if entry_rel in leaves:
            continue
        below = sorted(leaf for leaf in leaves if leaf.startswith(entry_rel + "/"))
        if below:
            del entries[entry_rel]
            dropped.append((
                entry_rel,
                f"is a namespace above the entry '{below[0]}', not an entry "
                "of its own -- left exactly as it is",
            ))
    for entry_rel in sorted(entries):
        if entry_rel in leaves:
            continue
        above = sorted(
            other
            for other in entries
            if other != entry_rel and entry_rel.startswith(other + "/")
        )
        if above:
            del entries[entry_rel]
            dropped.append((
                entry_rel,
                f"sits inside the entry '{above[-1]}', so it is content, not "
                "an entry of its own -- left exactly as it is",
            ))
    # A thing the system drops must be a thing the operator can see it
    # dropped (P34's own words) -- but through its own warning, not through
    # PublishReport.skipped (task 21 fix round 5, M4-1). cli.
    # _echo_publish_report renders that list as "N file(s) under .kb/ were
    # not published (allowlist)", and for a destination-side reconcile drop
    # all three of "under .kb/", "were not published" and "(allowlist)" are
    # wrong; a warning that misstates its own cause trains operators to
    # ignore warnings. These name the real path and the real reason, and
    # reach the operator on stderr through logging's last-resort handler
    # exactly like this module's other warnings do.
    for rel, reason in sorted(dropped):
        logger.warning("%s %s", (dest / rel).as_posix(), reason)

    for entry_rel, entry_dir in sorted(entries.items()):
        dest_record = entry_dir / assetstore.RECORD_NAME
        before = dest_record.read_bytes() if dest_record.is_file() else None
        read_failed = False
        try:
            inherited = _inheritable_assets(
                fed_src / entry_rel / assetstore.RECORD_NAME, dest_record
            )
            try:
                existing = _dest_record_assets(dest_record)
            except OSError:
                # P33 (task 21 fix round 4, M-2): nothing has been derived
                # from this failed read yet -- Case A's write and Case B's
                # divert below have not run for this entry. Protect just
                # this record from the restore's clean half (see
                # _restore_federation_after_store_failure's `protect`
                # docstring for why a blanket checkout-only skip was
                # measured unsafe instead).
                read_failed = True
                raise
            if inherited:
                models.save_yaml_model(
                    dest_record,
                    models.AssetsRecord(
                        assets=sorted(set(existing) | set(inherited))
                    ),
                )
            if active_store is not None and assetstore.divert_and_record(
                entry_dir, active_store
            ):
                # Raw bytes were physically removed from the hub's working
                # tree. That is a change the caller must commit even when the
                # record's own bytes did not move (the asset was already
                # named in it) -- otherwise the deletion sits uncommitted in
                # the hub clone and nothing ever picks it up.
                record_changed = True
        except (assetstore.AssetStoreError, OSError):
            # apply_sync (and the union-merge above, for entries already
            # visited this loop) already wrote into the hub clone's working
            # tree before this failed -- same unrecoverable-retry hazard
            # _restore_federation_after_store_failure guards against. One
            # restore for the whole federation/<rid> entry undoes every
            # entry this loop has touched so far, not just this one.
            _restore_federation_after_store_failure(
                handle, dest, protect=dest_record if read_failed else None
            )
            raise
        after = dest_record.read_bytes() if dest_record.is_file() else None
        if after != before:
            record_changed = True
    return record_changed


def _snapshot_federation(
    fed_src: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    source_url: str | None = None,
    store=None,
) -> tuple[int, bool, list[str]]:
    """Sync federation/ (hub trung gian) → federation/<rid>/ trên hub cấp trên.

    Khác _snapshot: nguồn là cả cây federation (leaf entries lồng nhau, mỗi leaf
    tự mang _meta.yaml); index.yaml/registry.yaml tầng đỉnh là sản phẩm riêng
    của hub nguồn — không đẩy; KHÔNG viết _meta.yaml ở gốc đích (gốc entry hub
    là namespace, không phải leaf — walk đệ quy phải đi xuyên qua nó).
    Assets (asset bytes dưới assets/) mirror verbatim; các file không thuộc
    allowlist của pubgate.is_kb_artifact() bị lọc bỏ, giống hệt _snapshot --
    xem PublishReport.skipped. NGOẠI LỆ: _assets.yaml (bookkeeping của hub
    nguồn, ghi bởi assetstore.divert_and_record) ĐƯỢC giữ lại
    (split_allowlist(..., keep_records=True)) -- khác _snapshot, nơi
    _assets.yaml chưa từng tồn tại phía .kb/ nguồn nên loại nó là đúng; ở
    đây nó là nội dung do hub nguồn ghi ra và đang được mirror lên, loại nó
    khiến lần publish sau XOÁ mất record trên hub đích.

    F-D11 item 3: also honours `store` the same way _snapshot does, so a
    still-undiverted asset (raw bytes committed by a mid-tier hub with no
    store of its own) gets diverted into THIS hub's store instead of landing
    as a committed binary blob here too. `active_store` is resolved from
    `handle` (the destination hub), never from the source.

    _assets.yaml is never a plain mirrored file here: RECORD_NAME is
    excluded from the plain file-diff on both sides unconditionally, and its
    content is driven explicitly by _reconcile_asset_records instead --
    Case A (union-merge) unconditionally, Case B (divert) only when this hub
    has a store. See _prepare_hub_to_hub_manifests and
    _reconcile_asset_records for the full reasoning, including why a
    storeless publish leaves an existing dest record untouched rather than
    deleting or truncating it.
    """
    from center_kb import assetstore, hashsync

    if not fed_src.is_dir():
        raise PublishError(
            f"federation source '{fed_src}' does not exist — refusing to publish"
        )
    dest = handle.federation_dir / rid
    fed_root = handle.federation_dir.resolve()
    if not dest.resolve().is_relative_to(fed_root):
        raise PublishError(
            f"repo-id '{rid}' escapes the federation/ directory on the hub — refusing to publish"
        )
    try:
        active_store = store if store is not None else assetstore.store_for_hub(handle)
    except (yaml.YAMLError, ValidationError, ValueError) as exc:
        # store_for_hub reads the HUB's own .kb/config.yaml (asset_store:) --
        # a corrupt one must name itself, not the caller's (mirrors _snapshot,
        # F-D9 finding 2).
        raise PublishError(
            f"{handle.kb_dir / 'config.yaml'} (the hub's own config) is "
            f"unreadable: {exc}"
        ) from exc
    (
        src_man,
        dest_man,
        skipped,
        synthesized_src_only,
        dest_raw_assets,
    ) = _prepare_hub_to_hub_manifests(fed_src, dest, active_store)
    if not src_man and dest_man:
        raise PublishError(
            "source federation/ is empty but the hub already holds entries under "
            f"'{rid}' — refusing to wipe them; delete federation/{rid} on the hub "
            "manually if that is really intended"
        )
    n_docs = len(federation.build_federation_index(fed_src).docs)
    changed, deleted = hashsync.diff_manifests(src_man, dest_man)
    changed = [p for p in changed if p not in synthesized_src_only]
    # A record-only change (a Case A name newly reaches this hub with no
    # other file in its entry touched) can leave changed/deleted both empty
    # even though real work remains -- RECORD_NAME was excluded from the
    # diff above precisely so it would never drive this decision on its own.
    # Only skip everything, including the reconcile pass below, when there
    # is truly nothing that could need it.
    #
    # `dest_raw_assets` is the third such term (task 21 fix round 5, ruling
    # P37): a publish against a hub that HAS a store must not leave
    # divertible bytes at the destination, whether or not the plain file
    # diff had any work to do. Gating the reconcile pass on that diff alone
    # made the whole union above unreachable on exactly the publishes that
    # matter -- once a raw asset is already sitting at dest with the same
    # bytes as the source, src_man and dest_man agree, the diff is empty,
    # and reconcile never ran. Measured on two reachable arms: a storeless
    # publish followed by the hub gaining a store, and (worse) any hub that
    # already ran the pre-round-4 code, whose committed raw binary no
    # publish repaired and `kb assets migrate` could not reach either
    # (assetcmd.migrate_assets enumerates with federation.iter_entry_dirs,
    # which walks past a marker-less entry). Both are now repaired by an
    # ordinary publish, which is why migrate_assets needs no widening.
    #
    # The probe costs no filesystem I/O: it is read off the dest manifest
    # build_manifest has already produced (see _prepare_hub_to_hub_
    # manifests), so the no-op path -- every publish of every unchanged
    # entry -- pays one comprehension over keys it already holds and
    # nothing else, and still early-returns whenever dest holds no raw
    # asset bytes, which is the steady state once a store is configured.
    if (
        not changed
        and not deleted
        and not synthesized_src_only
        and not (active_store is not None and dest_raw_assets)
    ):
        return n_docs, False, skipped
    if changed or deleted:
        hashsync.apply_sync(fed_src, dest, changed, deleted)
    record_changed = _reconcile_asset_records(fed_src, dest, handle, active_store)
    return n_docs, bool(changed or deleted or record_changed), sorted(skipped)


def _load_manifest_or_raise(man_path: Path) -> models.Manifest:
    """models.load_yaml_model(man_path, models.Manifest), with corrupt/schema-
    invalid/non-UTF-8 YAML converted to a PublishError naming the file (F-D9
    finding 2 -- yaml.YAMLError/ValidationError's own str() says nothing
    about which file was being read; UnicodeDecodeError is a ValueError, not
    an OSError, so it needs listing explicitly rather than folding into an
    `except OSError` elsewhere)."""
    try:
        return models.load_yaml_model(man_path, models.Manifest)
    except (yaml.YAMLError, ValidationError, ValueError) as exc:
        raise PublishError(f"{man_path} is unreadable: {exc}") from exc


def warn_legacy_ids(kb_dir: Path) -> list[str]:
    """x{n} ids are the opaque fallback of the old CLI (< 2debcbc) or of headings
    that could not be slugged — warn so the repo re-ingests with the new CLI.
    No reject: old data is still valid, just less readable (spec §6b)."""
    hits: list[str] = []
    for man_path in sorted(kb_dir.glob("*/_manifest.yaml")):
        manifest = _load_manifest_or_raise(man_path)
        hits += [
            f"{manifest.id} §{sec.id}"
            for sec in manifest.sections
            if _LEGACY_ID_RE.search(sec.id)
        ]
    if hits:
        logger.warning(
            "legacy synthetic section ids — re-ingest these docs with the "
            "current CLI to get readable ids: %s",
            ", ".join(hits),
        )
    return hits


def unreviewed_sections(kb_dir: Path) -> tuple[int, int]:
    """(sections whose status is not `reviewed`, docs that contain one).

    `hist.*` rows are excluded: they are machine-authored by `kb svc note`,
    which always leaves a fresh row `summarized`, and a whole-doc `kb
    approve` deliberately never flips them (F-L7) -- counting them here
    would re-trip `--require-reviewed` after every `kb svc note` with no
    way to clear it short of naming the section explicitly.
    """
    n_sections = n_docs = 0
    for man_path in sorted(kb_dir.glob("*/_manifest.yaml")):
        manifest = _load_manifest_or_raise(man_path)
        n = sum(
            1
            for s in manifest.sections
            if s.status != "reviewed" and not s.id.startswith(MACHINE_SECTION_PREFIX)
        )
        if n:
            n_sections += n
            n_docs += 1
    return n_sections, n_docs


@dataclass
class UnreviewedGate:
    """Result of `unreviewed_gate`: `line` is a ready-to-print `[warn]`/`[error]`
    message, or None when every section is reviewed; `blocked` means the
    caller must refuse (exit 1) before writing anything."""

    line: str | None
    blocked: bool = False


def unreviewed_gate(kb_dir: Path, require_reviewed: bool) -> UnreviewedGate:
    """Shared warn/refuse check for `kb publish` and `kb ci-publish` (R18):
    both call this — same message, same threshold — before any write/upload."""
    n_sec, n_docs = unreviewed_sections(kb_dir)
    if not n_sec:
        return UnreviewedGate(line=None)
    msg = f"{n_sec} section(s) in {n_docs} doc(s) are published without SME review"
    if require_reviewed:
        return UnreviewedGate(
            line=f"[error] {msg} — approve them or drop --require-reviewed",
            blocked=True,
        )
    return UnreviewedGate(line=f"[warn] {msg}", blocked=False)


def _governed_registry(
    handle: hub_mod.HubHandle, hub_label: str
) -> dict[str, str] | None:
    """{owner/repo: repo_id} when the hub carries a non-empty registry, else None.

    An unreadable registry is fatal here exactly as it is in intake.authorize:
    a hub whose registry cannot be parsed must never be treated as ungoverned.
    """
    try:
        registry = federation.load_registry(handle.federation_dir)
    except federation.RegistryError as exc:
        raise PublishError(
            f"{exc} -- fix the file on hub '{hub_label}', or ask the hub "
            "owner to fix it"
        ) from exc
    return federation.registry_map(registry) or None


def _existing_entry_names(handle: hub_mod.HubHandle) -> list[str]:
    """Entry directory names directly under federation/ on the hub."""
    fed = handle.federation_dir
    if not fed.is_dir():
        return []
    return sorted(
        p.name
        for p in fed.iterdir()
        if p.is_dir() and p.name not in _FED_TOP_EXCLUDE
    )


def _can_pr(explicit: str, has_remote: bool, root: Path) -> bool:
    """Ask `gh` only when decide_mode will actually read the answer.

    decide_mode reads can_pr only for a non-`direct` mode against a hub with
    a remote. Probing unconditionally made every local `--direct` publish
    wait on a network round-trip.
    """
    if explicit == "direct" or not has_remote:
        return False
    return ghio.can_open_pr(root)


def publish(
    kb_dir: Path,
    hub_ref: str,
    repo_id: str | None = None,
    max_retries: int = 3,
    mode: str = "auto",
    self_publish: bool = False,
) -> PublishReport:
    kb_abs = kb_dir.resolve()
    warn_legacy_ids(kb_abs)
    source_root = gitio.git_root(kb_abs)
    source_commit = gitio.head_commit(source_root)
    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise PublishError(f"could not reach hub '{gitio.redact_url(hub_ref)}'")
    hub_label = gitio.redact_url(hub_ref)
    # Self-publish -- a hub mirroring its own .kb/ into its own federation/ --
    # is exempt from governance: requiring the hub owner to register
    # themselves and open a PR against themselves would only break it.
    is_self = self_publish or handle.root.resolve() == source_root.resolve()
    registry_map = None if is_self else _governed_registry(handle, hub_label)
    rid = repo_id or source_root.name
    if registry_map is not None:
        rid = pubgate.resolve_identity(
            registry_map, gitio.remote_url(source_root), repo_id, hub_label
        )
    rid = pubgate.normalize_repo_id(rid, _existing_entry_names(handle))
    _neutralize_excludes(handle.root)

    has_remote = gitio.has_remote(handle.root)
    mode = pubgate.decide_mode(
        mode,
        has_remote=has_remote,
        can_pr=_can_pr(mode, has_remote, handle.root),
        governed=registry_map is not None,
        hub_label=hub_label,
    )
    if mode == "pr":
        return _publish_pr(kb_abs, handle, rid, source_commit)
    return _publish_direct(kb_abs, handle, rid, source_commit, max_retries)


def publish_federation(
    kb_dir: Path,
    hub_ref: str,
    repo_id: str | None = None,
    max_retries: int = 3,
    mode: str = "auto",
) -> PublishReport:
    """Hub trung gian đẩy federation/ của nó lên hub cấp trên.

    Chỉ federation/ được đẩy — .kb/ riêng của hub là bàn soạn thảo. Hub muốn
    share tri thức riêng: trỏ hub về chính nó (`hub: .` hoặc `--hub
    <đường-dẫn-chính-nó>`) — CLI sẽ mirror `.kb/` vào federation của chính nó
    như một entry thường (self-publish); hàm này chỉ đẩy federation/ khi đích
    là hub KHÁC. Cycle guard chạy trước khi ghi byte nào.

    Cycle guard xét các leaf entry đọc được; entry hỏng/slim-layout bị walk bỏ
    qua (kèm warning) nên không được guard nhìn thấy — kb doctor cảnh báo riêng.
    Self-entry (`federation/<rid>/` do hub tự publish) được miễn — nó không
    phải nội dung quay vòng.
    """
    from center_kb import config as config_mod

    kb_abs = kb_dir.resolve()
    source_root = gitio.git_root(kb_abs)
    fed_src = source_root / "federation"
    if not fed_src.is_dir():
        raise PublishError(
            "this hub has no federation/ directory — nothing to publish upstream"
        )
    source_commit = gitio.head_commit(source_root)
    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise PublishError(f"could not reach hub '{gitio.redact_url(hub_ref)}'")
    hub_label = gitio.redact_url(hub_ref)
    registry_map = _governed_registry(handle, hub_label)
    rid = repo_id or source_root.name
    if registry_map is not None:
        rid = pubgate.resolve_identity(
            registry_map, gitio.remote_url(source_root), repo_id, hub_label
        )
    rid = pubgate.normalize_repo_id(rid, _existing_entry_names(handle))
    try:
        dest_rid = config_mod.load_config(handle.kb_dir).repo_id or None
    except Exception as exc:
        # fail closed: a corrupt upstream config must not silently blind the
        # identity-based cycle guard below.
        raise PublishError(
            f"could not read the upstream hub's .kb/config.yaml: {exc}"
        ) from exc
    is_self = handle.root.resolve() == source_root.resolve()
    if not is_self and dest_rid is not None and dest_rid == rid:
        is_self = True
    if not is_self:
        # A hub whose upstream is itself reached by remote URL (e.g. the
        # upstream ref resolves to a fresh cache clone of this very repo)
        # resolves to a different path than source_root — path equality
        # above misses it. Compare remote URLs instead; any failure here
        # (no git binary, detached remote, etc.) is treated as not-self —
        # the forbidden-segment guard below still catches real cycles.
        try:
            if gitio.has_remote(handle.root) and gitio.has_remote(source_root):
                dest_url = gitio.remote_url(handle.root)
                src_url = gitio.remote_url(source_root)
                if dest_url and dest_url == src_url:
                    is_self = True
        except Exception:  # noqa: BLE001, S110 — see comment above
            pass
    if is_self:
        raise PublishError(
            "federation cycle detected: the upstream hub resolves to this repo itself"
        )
    forbidden = {rid}
    if dest_rid:
        forbidden.add(dest_rid)
    # dest_rid is never exempted — a self-entry at the DESTINATION's own id
    # is a real loop-back, not this hub's own self-publish entry.
    exempt_exact = {rid} if rid != dest_rid else set()
    hit = federation.find_cycle_segment(fed_src, forbidden, exempt_exact=exempt_exact)
    if hit is not None:
        raise PublishError(
            f"federation cycle detected: entry '{hit}' contains a hub id from this "
            "publish chain — publishing would loop content back on itself"
        )
    _neutralize_excludes(handle.root)
    has_remote = gitio.has_remote(handle.root)
    mode = pubgate.decide_mode(
        mode,
        has_remote=has_remote,
        can_pr=_can_pr(mode, has_remote, handle.root),
        governed=registry_map is not None,
        hub_label=hub_label,
    )
    if mode == "pr":
        return _publish_pr(
            fed_src, handle, rid, source_commit, snapshot_fn=_snapshot_federation
        )
    return _publish_direct(
        fed_src, handle, rid, source_commit, max_retries,
        snapshot_fn=_snapshot_federation,
    )


def _push_with_retry(handle: hub_mod.HubHandle, rid: str, max_retries: int) -> bool:
    """Push handle.root; on rejection (race), pull --rebase, regenerate the
    aggregate index against the now-current tree, commit that fix, and retry.
    """
    if not gitio.has_remote(handle.root):
        return False
    for attempt in range(max_retries):
        try:
            gitio.push(handle.root, handle.token)
            return True
        except gitio.GitError:
            if attempt == max_retries - 1:
                raise PublishError(
                    f"push to hub failed after {max_retries} attempts (race?)"
                )
            gitio.pull_rebase(handle.root, handle.token)
            # another repo just published — the aggregate index in our commit may
            # be missing their docs; regen (deterministic), then commit the fix
            federation.write_federation_index(handle.federation_dir)
            gitio.commit_paths(
                handle.root,
                f"publish: reindex after rebase ({rid})",
                ["federation/index.yaml"],
            )
    return False


def _reported_commit(
    handle: hub_mod.HubHandle, rid: str, source_commit: str, changed: bool
) -> str:
    """The commit the hub entry actually records.

    _snapshot deliberately leaves _meta.yaml alone when nothing changed, so
    reporting the source repo's current HEAD claims the hub holds a snapshot
    of a commit it has never seen. Most visible on a self-publish, where the
    previous publish's own commit moved HEAD.
    """
    if changed:
        return source_commit
    meta_path = handle.federation_dir / rid / "_meta.yaml"
    try:
        meta = models.load_yaml_model(meta_path, federation.FederationMeta)
    except (OSError, ValidationError, yaml.YAMLError, UnicodeDecodeError):
        # UnicodeDecodeError is a ValueError, not an OSError -- without it, a
        # non-UTF-8 _meta.yaml turned this best-effort fallback into a hard
        # failure instead of just reporting source_commit (finding 7).
        return source_commit
    return meta.source_commit or source_commit


def _publish_direct(
    kb_abs: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    max_retries: int,
    snapshot_fn=_snapshot,
) -> PublishReport:
    n_docs, changed, skipped = snapshot_fn(kb_abs, handle, rid, source_commit)
    # Commit the <rid>/ mirror on its own path first — rebasing this against
    # a concurrent publisher's commit never conflicts (disjoint paths), even
    # when both are populating federation/ for the very first time.
    entry_committed = gitio.commit_paths(
        handle.root, f"publish: {rid} @ {source_commit}", [f"federation/{rid}"]
    )
    pushed = _push_with_retry(handle, rid, max_retries) if entry_committed else False

    # Regenerate the aggregate index against the now-current tree (if a
    # rebase just happened above, this already includes any peer's entries)
    # and commit/push it separately — a plain modify, never an "add/add",
    # even on the very first publish to an empty hub.
    federation.write_federation_index(handle.federation_dir)
    idx_committed = gitio.commit_paths(
        handle.root, f"publish: reindex ({rid})", ["federation/index.yaml"]
    )
    if idx_committed:
        pushed = _push_with_retry(handle, rid, max_retries) or pushed
    from center_kb import searchdb
    from center_kb.embed import default_embedder

    try:
        searchdb.sync(handle, default_embedder())
    except Exception as exc:  # noqa: BLE001 -- eager refresh best-effort, query still rebuilds lazily
        logger.warning("search index refresh failed: %s", exc)
    return PublishReport(
        rid,
        _reported_commit(handle, rid, source_commit, changed),
        n_docs, pushed, mode="direct",
        skipped=skipped, remote=gitio.has_remote(handle.root),
    )


def _publish_pr(
    kb_abs: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    snapshot_fn=_snapshot,
) -> PublishReport:
    if not ghio.can_open_pr(handle.root):
        raise PublishError(
            "PR mode needs the GitHub CLI able to see the hub repo -- install "
            "`gh` (https://cli.github.com), authenticate it for the hub's host, "
            "or run `kb publish --direct` if direct pushes are allowed"
        )
    branch = f"publish/{rid}"
    original = gitio.current_branch(handle.root)
    try:
        gitio.checkout_branch(handle.root, branch, original)
        n_docs, changed, skipped = snapshot_fn(kb_abs, handle, rid, source_commit)
        federation.write_federation_index(handle.federation_dir)
        committed = gitio.commit_paths(
            handle.root, f"publish: {rid} @ {source_commit}", ["federation"]
        )
        if not committed:
            return PublishReport(
                rid,
                _reported_commit(handle, rid, source_commit, changed),
                n_docs, False, mode="pr", skipped=skipped, remote=True,
            )
        # Read _meta.yaml (when changed=False) while still checked out on
        # `branch` -- finding 7: computing this after the `finally` below has
        # already run `gitio.checkout(handle.root, original)` made it read
        # _meta.yaml off the original branch instead of the publish branch.
        reported_commit = _reported_commit(handle, rid, source_commit, changed)
        gitio.push_branch(handle.root, branch, handle.token)
        url = ghio.pr_url_for_branch(handle.root, branch)
        if not url:
            url = ghio.create_pr(
                handle.root,
                branch,
                title=f"publish: {rid} @ {source_commit}",
                body=PR_BODY_TEMPLATE.format(rid=rid, commit=source_commit),
            )
    finally:
        gitio.checkout(handle.root, original)
    return PublishReport(
        rid,
        reported_commit,
        n_docs, True, mode="pr", pr_url=url, skipped=skipped, remote=True,
    )


def _default_get_json(url: str) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 -- scheme validated by the only caller, publish_via_intake, before this is ever invoked
            import json as json_mod

            return resp.status, json_mod.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except OSError:
        return 0, {}


def publish_via_intake(
    kb_dir: Path,
    intake_url: str,
    repo_id: str | None,
    poll_interval: float = 5.0,
    timeout: float = 600.0,
    http_get_json=None,
) -> str:
    """Dev-machine intake flow: tag kb-publish/<ts>, push, poll for the PR URL.

    Zero secrets: the tag push uses the developer's normal child-repo git
    access; the child's CI (OIDC) does the actual upload.
    """
    import time as time_mod
    import urllib.parse

    # A bad scheme is permanent, not transient like the OSError branch
    # _default_get_json degrades to -- catching it there would be
    # indistinguishable from a network hiccup and the caller would poll the
    # full `timeout` before reporting the wrong thing (Actions logs, not the
    # real cause). Reject loudly here, before anything is tagged or pushed.
    if urllib.parse.urlparse(intake_url).scheme not in ("http", "https"):
        raise PublishError(f"refusing non-http(s) intake URL: {intake_url}")

    get_json = http_get_json or _default_get_json
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    if gitio.is_dirty(root, kb_abs):
        raise PublishError(
            ".kb/ has uncommitted changes — commit them first "
            "(the child CI publishes the tagged commit, not the working tree)"
        )
    rid = repo_id or root.name
    commit = gitio.head_commit(root)
    tag_name = f"kb-publish/{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    gitio.tag(root, tag_name)
    gitio.push_tag(root, tag_name)
    status_url = (
        f"{intake_url.rstrip('/')}/intake/status?"
        + urllib.parse.urlencode({"repo_id": rid, "commit": commit})
    )
    deadline = time_mod.monotonic() + timeout
    while time_mod.monotonic() <= deadline:
        status, data = get_json(status_url)
        if status == 200:
            if data.get("state") == "done":
                return data.get("pr_url", "")
            if data.get("state") == "error":
                raise PublishError(f"intake rejected the publish: {data.get('detail')}")
        if poll_interval:
            time_mod.sleep(poll_interval)
        elif status != 200:
            break  # test mode (poll_interval=0): one loop is enough while unknown
    raise PublishError(
        f"timed out waiting for the intake — check the Actions run for tag "
        f"'{tag_name}' in the child repo's GitHub Actions logs"
    )
