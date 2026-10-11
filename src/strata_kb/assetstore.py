"""Object-store seam for image assets (spec B).

Asset names are bare content-addressed filenames `<sha256>.<png|webp>`
(spec A); the store prepends the configured key prefix. `mode: none`
returns no store and leaves all existing behavior unchanged.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
from pathlib import Path, PurePosixPath

import yaml
from pydantic import ValidationError

from strata_kb import config as config_mod
from strata_kb import models
from strata_kb.errors import KbError

logger = logging.getLogger("strata_kb.assetstore")

_MEDIA = {".png": "image/png", ".webp": "image/webp"}
_IMMUTABLE = "private, max-age=31536000, immutable"

RECORD_NAME = "_assets.yaml"
_ASSET_NAME_RE = re.compile(r"^([0-9a-f]{64})\.(?:png|webp)$")

# Well-known nonexistent key for reachability probes (doctor, kb assets):
# a clean "not found" proves bucket + credentials + endpoint work.
PROBE_NAME = "0" * 64 + ".png"


class AssetStoreError(KbError):
    """Store unreachable / misconfigured / operation failed.

    Joins the KbError family (not a standalone RuntimeError sibling): every
    CLI guard downstream that already catches KbError for PublishError/
    GateError/CIPublishError needs no separate arm to also turn a store
    failure into a clean message -- see cli.py's hub-to-hub `except` tuple,
    which _snapshot_federation's asset-store calls now reach."""


class AssetIntegrityError(AssetStoreError):
    """A store object's bytes do not hash to its content-addressed name.

    Distinct from the base AssetStoreError so callers can tell "this object
    is corrupt" apart from "the store is unreachable" — a transport failure
    must not be reported as corruption (or silenced as one)."""


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
                import boto3  # pyright: ignore[reportMissingImports]
            except ImportError as exc:
                raise AssetStoreError(
                    'S3 asset store needs boto3 — run: pip install "strata-kb[s3]"'
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
        except Exception as exc:  # classify, then wrap
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
        except Exception as exc:
            raise AssetStoreError(f"asset store PUT failed: {exc}") from exc

    def get(self, name: str) -> bytes | None:
        try:
            resp = self._c().get_object(Bucket=self._cfg.bucket, Key=self._key(name))
            return resp["Body"].read()
        except AssetStoreError:
            raise
        except Exception as exc:
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
        with contextlib.suppress(OSError):
            path.parent.rmdir()  # only succeeds when now empty
    return sorted(diverted)


def asset_sha(entry: str) -> str | None:
    """The sha256 an ASSETS-RECORD ENTRY's basename encodes, or None when
    that basename is not a content-addressed asset name.

    PurePosixPath, never bare `Path` -- and that is the whole point of this
    function existing: the property is platform-independent, so the mechanism
    must not be. `Path` binds to WindowsPath or PosixPath depending on which
    interpreter happens to be running, and the two disagree about exactly one
    input: an entry spelled with backslashes.
    `Path("doc-a\\\\assets\\\\<sha>.png").name` is `"<sha>.png"` on Windows and
    the WHOLE STRING on Linux. A caller keyed on `Path(a).name` therefore
    ACCEPTS a backslash-spelled hub record on a Windows hub and HARD-FAILS the
    publish on a Linux one, and merges the same upstream name on Windows while
    silently dropping it on Linux -- two operators getting different answers
    out of the same bytes.

    A backslash in a record entry is therefore an ORDINARY CHARACTER IN A
    FILENAME, not a separator. That is the rule this codebase already
    follows in two places:

    * divert_assets below computes `path.relative_to(tree_root).as_posix()`
      for every diverted asset -- forward slashes, always, on every host --
      and this tree's two actual record writers, divert_and_record below
      and publish._reconcile_asset_records, persist names in exactly that
      shape; both fence their inputs through is_asset_name (or the
      equivalent _ASSET_NAME_RE match) before writing. A record holds
      POSIX-spelled relative paths by construction.
    * pubgate.is_kb_artifact refuses any relpath containing a backslash
      outright (`if PurePosixPath(relpath).is_absolute() or "\\\\" in
      relpath: return False`), so a backslash-spelled entry could never be
      mirrored by a publish even if a reader here did accept it.

    So `"doc-a\\\\assets\\\\<sha>.png"` names one single component whose
    name contains backslashes, which _ASSET_NAME_RE cannot match -- and a
    record containing it is mangled, on Windows exactly as much as on Linux.
    Do not treat the Windows behaviour as the contract.
    """
    m = _ASSET_NAME_RE.match(PurePosixPath(entry).name)
    return m.group(1) if m else None


def is_asset_name(entry: str) -> bool:
    """Is this record entry's basename a content-addressed asset name?

    The one shared answer for all four readers of that question -- this
    module's load_record and synthesized_asset_entries, and publish's
    _dest_record_assets and _inheritable_assets. Do not let a reader reach
    for the private _ASSET_NAME_RE and apply its own `Path(a).name`: that
    reintroduces the platform split asset_sha exists to close.
    Depth-independent, exactly like divert_assets' `assets/*` scan and
    pubgate.is_kb_artifact's asset rule.
    """
    return asset_sha(entry) is not None


BAD_NAMES_SHOWN = 3


def not_a_regular_file_clause(record_path: Path) -> str:
    """`<path> exists but is not a regular file -- it may be a directory, or
    a link whose target is gone` -- the subject of both readers' refusal
    when something that is not a file is sitting at the record path (an
    existing record path is evidence names existed, so it never reads as
    absent).

    Shared between load_record and publish._dest_record_assets so the two
    messages cannot drift apart (the "or a link whose target is gone" half
    covers the os.path.lexists branch); both dangling-link tests assert it.
    """
    return (
        f"{record_path} exists but is not a regular file -- it may be a "
        "directory, or a link whose target is gone"
    )


def restore_clause(record_path: Path) -> str:
    """`restore it from its last known-good commit -- <the commands that
    actually do that>`: the way-forward every hard refusal in both readers
    ends with.

    Do not offer `git checkout -- <path>` as the example: that command cannot
    recover the shape the messages are about. It restores the working tree from
    the INDEX, and by the time a publish refuses a record the corruption is in
    the index too -- an interrupted publish's own `git add -A`, or any routine
    one, puts it there, and it is what a hub looks like after the failure this
    message reports. Measured end to end through the real CLI: rc=0, no output,
    `record now == corrupt? True`, and the next publish fails with the
    identical message. The operator loops, silently. In the other branch --
    corruption never staged -- the publish's own abort-and-restore has already
    repaired the file before the message is ever read, so the command is
    unnecessary there too. It does no useful work in either branch, and a
    command that silently does nothing costs more than no command at all: it
    spends the trust the next message needs.

    Names the commit-scoped form instead, plus the `git log` that finds the
    commit, plus why not to reach for the short form out of habit. Shared
    for the same reason bad_name_clause is: eight messages across two
    modules end this way and must not drift apart.
    """
    return (
        "restore it from its last known-good commit -- `git log --oneline "
        f"-- {record_path}` lists them, then `git checkout <commit> -- "
        f"{record_path}` (NOT plain `git checkout -- {record_path}`, which "
        "restores from the index, where the corruption itself is once it "
        "has been staged or committed, so it exits 0 and changes nothing)"
    )


def bad_name_clause(bad: list[str]) -> str:
    """`names <entries>, which is/none of which is a content-addressed asset
    name` -- the subject of both readers' name-shape refusal, for one mangled
    entry or many.

    Names several entries, not just `bad[0]`, so a hand-edited or
    multiply-mangled record does not leave the operator to find its bad entries
    one failed retry at a time. Capped at BAD_NAMES_SHOWN so a wholly-garbled
    record cannot turn one error line into a dump of its entire contents.

    Shared with publish._dest_record_assets (which decides what counts as
    bad through is_asset_name above) so the two readers of this same file
    cannot drift into describing the same corruption two different ways.
    """
    shown = ", ".join(repr(a) for a in bad[:BAD_NAMES_SHOWN])
    if len(bad) > BAD_NAMES_SHOWN:
        shown += f" (and {len(bad) - BAD_NAMES_SHOWN} more)"
    if len(bad) == 1:
        return f"names {shown}, which is not a content-addressed asset name"
    return f"names {shown} -- none of which is a content-addressed asset name"


def load_record(dest: Path) -> models.AssetsRecord:
    """`.assets` at dest's RECORD_NAME; empty only when the file is
    genuinely absent — a present-but-unreadable (OSError) or
    present-but-corrupt (bad YAML / bad schema) record raises instead of
    self-healing to empty. This is the one shared reader every
    hub-owned-record caller goes through, applying the same dest-side rule
    as publish._dest_record_assets; do not loosen it back to a bare
    `except Exception` that returns empty.

    This file may be the hub's only index of what the object store holds:
    lose it and the bytes are orphaned — still on disk, referenced by
    nothing, invisible to every later publish. A caller that derives a
    write (a merge, an overwrite) from a self-healed-empty read can delete
    or truncate that index while the store still holds the only copy —
    measured end to end at both assetcmd.migrate_assets (a re-run over an
    unreadable record unlinked it while the store still held the only
    copy of what it named) and intake.intake_publish (an incremental
    upload over an unreadable record replaced it with just the current
    upload, dropping every earlier name). Both now call this directly as
    a pre-flight check before divert_and_record, and abort loudly on the
    raise rather than let divert_and_record's own lenient read (below)
    paper over it.

    Corrupt YAML/schema is folded into the same raise as an unreadable
    file, not treated as absent: publish._dest_record_assets has drawn
    that line since it was written, and nothing measured in this tree
    depends on a corrupt hub-owned record silently reading back empty (the
    one test that exercised a corrupt record,
    test_divert_and_record_corrupt_record_treated_as_empty, does so
    through divert_and_record's own lenient read below, not this
    function).

    Present-but-EMPTY is folded in too: models.load_yaml_model is
    `yaml.safe_load(...) or {}`, so a zero-byte file, a whitespace-only
    one, or literal `{}` all parse as a *successful* read of an
    AssetsRecord with no assets -- the except above never fires, and the
    caller derives "nothing to preserve" from a read that never actually
    failed. Measured end to end at both call sites below
    (assetcmd.migrate_assets and intake._publish_in_worktree): a re-run
    over a zero-byte committed record unlinked it, and an incremental
    intake upload over one replaced it with just the current upload --
    the exact signature the OSError/YAMLError guard above exists to
    prevent, reached through a shape neither unreadable nor corrupt.

    The distinguishing property this leans on: nothing in this codebase
    ever WRITES a record with an empty assets list. divert_and_record
    below deletes the file outright once the merged set is empty instead
    of writing `assets: []`, and publish._reconcile_asset_records' Case A
    write only runs when there is something to merge in. So the only way
    for an EXISTING file to parse back with no assets is a shape none of
    this tree's own writers produce -- most plausibly models.save_yaml_model
    (path.write_text, truncate-then-write, no temp-file-and-rename)
    truncated by an interrupted publish, a full disk, or a crash. A
    legitimately empty entry (every asset removed) therefore still works
    exactly as before: divert_and_record already deletes its record on the
    write that empties it, so "legitimately empty" already means "record
    absent" by the time anything reads it again -- the `not record_path.
    is_file()` branch above, unchanged.

    A record truncated mid-list to a shorter but still non-empty list is
    NOT indistinguishable from a genuinely shorter list written on purpose
    (that claim was measured false). Truncation lands mid-path, not on an
    entry boundary, because save_yaml_model's write is not atomic and a
    truncated file simply stops wherever the interrupting failure landed.
    Measured on a real 5-asset record (423 bytes), truncated at every one
    of its 423 byte offsets and fed back through this function: 18 already
    raise (bad YAML/schema), 1 is caught by the empty check above, and of
    the 404 that survive both, 395 are caught exactly by is_asset_name
    above -- _ASSET_NAME_RE applied to each entry's POSIX basename, the
    same module-owned regex divert_assets already uses to decide what
    counts as a recorded name, not a new heuristic -- and a further 5 (400
    of 404) are caught by requiring the file's own text to end with a
    trailing newline, which every write through save_yaml_model's
    yaml.safe_dump produces and a truncation almost never leaves intact.
    4 of the 423 offsets (91, 174, 257, 340) are caught by neither check,
    and they are irreducible in a stronger sense than "ambiguous": each of
    those truncations is BYTE-IDENTICAL to save_yaml_model's own output
    for the correspondingly shorter list -- verified for all four -- so
    there is no content difference for any check to find, and NO
    content-based detector can ever exist for them. Making save_yaml_model
    atomic (temp-file-and-rename) removes the CAUSE; it does not enable a
    detector, because there is nothing left to detect. The residue is also
    structural rather than incidental: an N-entry record has exactly N-1
    such boundary offsets out of roughly 83N, so the ratio improves as
    records grow.

    Made public (not left `_load_record`) because assetcmd.py and
    intake.py reach across modules to call it as that pre-flight check.
    publish._dest_record_assets is left uncollapsed on purpose: collapsing
    it to call this function would change what it raises from a plain
    OSError to AssetStoreError, and _reconcile_asset_records' own
    read_failed detection (the flag deciding whether the record is
    protected from the restore's `git clean` half) only watches for
    OSError at that inner boundary -- collapsing without also widening
    that except would quietly stop protecting an untracked
    unreadable/empty/dir-shaped record during the exact restore that flag
    exists for. _dest_record_assets instead carries the same checks in
    place, keeping its OSError contract exactly as every existing caller
    and test already expects it. See that function's docstring.

    Those checks must stay symmetric across the two readers. If
    _dest_record_assets lacked the name-shape and trailing-newline checks,
    a truncated or newline-stripped DESTINATION record would sail past it
    in a real hub-to-hub publish, so nothing aborts and nothing is
    restored, and then divert_and_record's deliberate self-heal below
    turns THIS function's raise into `existing = []` and unlinks the
    hub-owned record outright -- exit 0, store holding the only copy (this
    was measured end to end). The two readers of this one file must never
    disagree about what counts as readable.

    divert_and_record's own read of this file, and synthesized_asset_
    entries' below, deliberately do NOT let this raise escape — see their
    docstrings for why self-healing is still correct there.
    """
    record_path = dest / RECORD_NAME
    # is_file(), not exists() -- but not because of a failed stat. exists()
    # and is_file() share the same OSError handling for a failed stat
    # (CPython's _ignore_error re-raises through either; a
    # permission-denied stat raises either way), so a failed stat is not
    # the divergence between them. The real divergence is a record path
    # that EXISTS but is not a regular file (in practice, a directory) --
    # there exists() is True and is_file() is False. An EXISTING record
    # path is evidence names existed; only its ABSENCE may read as
    # "nothing to preserve" -- so that shape must raise, not silently
    # return absent. Reading it as absent here would let divert_and_record
    # upload a new asset, unlink the raw bytes from the hub tree, then hit
    # an uncaught PermissionError writing the directory-shaped record path
    # -- past migrate's own AssetStoreError-only restore guard, leaving an
    # uncommitted deletion sitting in the hub clone with nothing to undo it.
    #
    # os.path.lexists(), not Path.exists(): both is_file() and exists()
    # FOLLOW a link, so a link at the record path whose target is gone
    # reads as exists()=False -- absent -- when something is in fact
    # sitting there. Measured with a broken NTFS junction: exists=False,
    # is_file=False, lexists=True, and the record "absent" answer flows
    # straight on into the same delete-on-a-failed-read this branch exists
    # to prevent. lexists() is exactly the "is anything at this name"
    # question to ask, and it strictly widens the raise: it is True
    # everywhere exists() was (an lstat that succeeds for a directory
    # succeeds for a link too) and additionally where only the link entry
    # survives. It cannot narrow the ABSENT answer either --
    # os.path.lexists swallows the OSError from a failed lstat, but this
    # branch is only reached once is_file() has already returned cleanly,
    # and is_file() re-raises a failed stat (measured, CPython 3.11.15's
    # _ignore_error) rather than reaching here at all.
    if not record_path.is_file():
        if os.path.lexists(record_path):
            raise AssetStoreError(
                f"{not_a_regular_file_clause(record_path)}, and this file "
                "may be the hub's only index of what the object store "
                "holds; refusing to treat it as absent. remove or restore "
                "whatever is at that path so it is either a regular record "
                "file or genuinely absent, then retry."
            )
        return models.AssetsRecord()
    try:
        raw_text = record_path.read_text(encoding="utf-8")
        record = models.load_yaml_model(record_path, models.AssetsRecord)
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        raise AssetStoreError(
            f"{record_path} exists but could not be read ({exc}) -- it may "
            "name the only surviving copy of some assets in the object "
            "store; refusing to treat it as empty. "
            f"{restore_clause(record_path)}, or fix the permissions/lock/"
            "YAML, then retry."
        ) from exc
    if not record.assets:
        raise AssetStoreError(
            f"{record_path} exists but names no assets -- nothing in this "
            "codebase writes that shape (an entry with nothing left to "
            "divert has its record deleted, not written empty; see "
            "divert_and_record below), so a present-but-empty record is "
            "evidence of a truncated or interrupted write (models."
            "save_yaml_model truncates the file before writing it), not "
            "evidence the assets are gone. refusing to treat it as empty. "
            f"{restore_clause(record_path)}, or confirm the assets really "
            "were removed and delete the file outright, then retry."
        )
    bad = [a for a in record.assets if not is_asset_name(a)]
    if bad:
        raise AssetStoreError(
            f"{record_path} {bad_name_clause(bad)} "
            "(<sha256>.png or .webp) -- "
            "evidence of a write truncated mid-path, not a legitimate "
            "shorter list (this tree's record writers, divert_and_record "
            "below and publish._reconcile_asset_records, are both "
            "is_asset_name-fenced and only ever persist names matching "
            "that shape). refusing to treat "
            "it as this entry's complete set. "
            f"{restore_clause(record_path)}, or confirm the record really "
            "is this short and rewrite it, then retry."
        )
    if not raw_text.endswith("\n"):
        raise AssetStoreError(
            f"{record_path} does not end with a trailing newline -- every "
            "record this codebase writes does (models.save_yaml_model's "
            "yaml.safe_dump always terminates one), so a missing one is "
            "evidence of a truncated write, not a complete list. "
            "refusing to treat it as this entry's "
            f"complete set. {restore_clause(record_path)}, or confirm the "
            "record really is complete and rewrite it, then retry."
        )
    return record


def divert_and_record(dest: Path, store, deletes: list[str] | None = None) -> list[str]:
    """Divert assets under dest, then merge the record: existing ∪ new − deletes.
    Intake uploads are incremental, so a plain overwrite would drop
    previously-diverted assets from the record.

    Its own read of the existing record self-heals a present-but-unreadable
    or present-but-corrupt file to empty instead of letting load_record's
    AssetStoreError escape — deliberately, not an oversight. This is the
    function publish._snapshot calls directly, with no pre-check, for every
    plain child publish; measured across the full readable / unreadable /
    corrupt × kept / dropped matrix, that call site comes out byte-identical
    regardless, because apply_sync has already rewritten dest from the
    source's live .kb/ (which always holds the raw bytes) before this runs
    — divert_assets' own scan of dest (above) reconstructs `diverted`
    correctly either way, so self-healing the old record to empty here
    never loses a name the tree itself does not already account for.
    Do not "fix" this into raising — it would turn that benign, already-
    correct call site into a spurious hard failure.

    Callers for whom that is NOT true — where this record may be the only
    surviving index of a name nothing else in the tree still holds — must
    call load_record(dest) themselves BEFORE calling this, and abort on
    its raise rather than reach this point at all. assetcmd.migrate_assets
    and intake.intake_publish do exactly that."""
    diverted = divert_assets(dest, store)
    try:
        existing = load_record(dest).assets
    except AssetStoreError as exc:
        logger.warning(
            "%s unreadable (%s) — treating as empty", dest / RECORD_NAME, exc
        )
        existing = []
    merged = sorted((set(existing) | set(diverted)) - set(deletes or []))
    record_path = dest / RECORD_NAME
    if merged:
        models.save_yaml_model(record_path, models.AssetsRecord(assets=merged))
    elif record_path.exists():
        record_path.unlink()
    return diverted


def synthesized_asset_entries(dest: Path) -> dict[str, str]:
    """Manifest entries for diverted assets: {relpath: sha}, sha taken from
    the filename — exact by spec A construction, no bytes needed.

    Self-heals a present-but-unreadable/corrupt record to empty instead of
    letting load_record's AssetStoreError escape (same reasoning as
    divert_and_record above) — this feeds a hashsync manifest diff
    (publish._snapshot, intake.hub_manifest), never a write. An empty
    result just makes every asset the record would have named look
    "changed" to that diff, forcing a fresh divert that rebuilds the
    record from the tree's own current bytes; it never causes a delete or
    an overwrite on its own."""
    entries: dict[str, str] = {}
    try:
        assets = load_record(dest).assets
    except AssetStoreError as exc:
        logger.warning(
            "%s unreadable (%s) — treating as empty", dest / RECORD_NAME, exc
        )
        assets = []
    # The `if sha` guard is belt-and-braces and no mutant can kill it
    # (measured: replacing it with `entries[rel] = asset_sha(rel) or ""`
    # leaves every test passing). load_record above raises if ANY entry
    # fails is_asset_name, and the except turns that into assets = [], so
    # by the time this loop runs every entry has already passed the same
    # check -- it is unreachable-as-false while load_record keeps its
    # name-shape check. Kept rather than dropped: it is the only thing
    # standing between a future narrowing of load_record's checks and a
    # manifest entry carrying an empty sha, and it costs one branch. Stated
    # here rather than left as an unexplained unkilled line.
    for rel in assets:
        sha = asset_sha(rel)
        if sha:
            entries[rel] = sha
    return entries


def verify_bytes(name: str, data: bytes) -> bool:
    """Do these bytes hash to the sha256 in this content-addressed filename?

    AssetsRecord's contract is that the filename's sha256 IS the content's
    sha256 -- synthesized_asset_entries takes the hash straight from the name
    without ever reading a byte. Nothing checked it, so one bad object in the
    store was served with `max-age=31536000, immutable` and cached on disk.
    """
    m = _ASSET_NAME_RE.match(name)
    if not m:
        return False
    return hashlib.sha256(data).hexdigest() == m.group(1)


def get_verified(store, name: str) -> bytes | None:
    """store.get(name), refusing bytes that do not match the name."""
    data = store.get(name)
    if data is None:
        return None
    if not verify_bytes(name, data):
        raise AssetIntegrityError(
            f"asset '{name}' does not match its name -- the object store holds "
            "content whose sha256 differs from the content-addressed key"
        )
    return data
