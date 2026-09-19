from __future__ import annotations

import gzip
import io
import json
import logging
import re
import tarfile
import tempfile
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from strata_kb import assetstore, federation, ghapp, gitio, hashsync, models
from strata_kb import hub as hub_mod
from strata_kb.pubgate import REPO_ID_MAX, is_reserved_device_name
from strata_kb.web import ratelimit

logger = logging.getLogger("strata_kb.intake")

GITHUB_ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = GITHUB_ISSUER + "/.well-known/jwks"
TAG_REF_PREFIX = "refs/tags/kb-publish/"
DEFAULT_MAX_TAR = 50 * 1024 * 1024
# LOW-5 (round 4): this bounds DECOMPRESSED STREAM bytes read while
# extracting, not just the member content bytes a publisher thinks of as
# "the archive" -- see _BoundedTarStream's docstring for the mechanism and
# the measured before/after numbers for a many-small-files archive.
# HIGH-2: total *content* bytes were capped but member *count* was not -- a
# legitimate 50 MiB archive can carry ~11.1M zero-byte members (measured),
# which starves the extraction threadpool and the container filesystem
# creating inodes. A real KB entry's file count is small: a document
# contributes two files per section group (an L2 .md and its L3 .raw.md,
# sharing one `file:` stem) plus at most a few hundred `assets/` images,
# and `_manifest.yaml`/`index.yaml` bookkeeping -- even an unusually large
# multi-document repo-id plausibly tops out in the low thousands of files
# per publish (kb ci-publish uploads only the changed set; a first publish
# uploads the whole current .kb/, the largest case). 10,000 gives roughly an
# order of magnitude of headroom over that, while bounding worst-case
# extraction cost: the security review measured 20,000 members at 13.5s of
# pure extraction, so 10,000 keeps a single request's worst case in the
# single-digit seconds the 30-requests/60s-per-IP limiter already expects,
# rather than the hours a 50 MiB, all-headers archive would otherwise cost.
MAX_TAR_MEMBERS = 10_000
# HIGH-2 round 2: tarfile consumes a pax 'path=' extended header (or a GNU
# long-name header) INSIDE tf.next(), before this module's loop ever sees
# the member -- the member it yields carries the merged name, member.size
# is only the file's own content size, and the header's real length was
# charged a flat tarfile.BLOCKSIZE (512) regardless of how large it truly
# was. The per-character scans in safe_extract (_reject_path_shape, and
# _reject_display_spoofing added by round 1) then ran their full
# O(len(name)) cost against that unbounded name: measured, a 97 KB gzip
# upload carrying a 100 MB pax name cost 6.57s of CPU -- 5.35s of it in
# _reject_display_spoofing alone -- for a nominal 512-byte charge against
# a 50 MiB budget, a 26x increase in per-name-byte cost over the pre-round
# baseline. A name longer than any real path can be is refused before any
# of those scans run; the check is O(1) (Python caches str length), so it
# costs nothing proportional to a name tarfile has already fully parsed by
# the time `member` is yielded.
MAX_MEMBER_NAME = 4096  # POSIX PATH_MAX; no real repo-relative path is longer

# N-3 (round 3): MAX_MEMBER_NAME bounds what the per-character scans below
# cost, not what a Windows CLIENT can check out -- measured, a 390-char and
# a 3000-char member path (both far under 4096) each give `git clone`
# rc=128 with only 1 of 4 files checked out, on stock git for Windows;
# `-c core.longpaths=true` clones the identical tree cleanly, which is the
# only reason this is a bound rather than a refusal folded into
# _reject_path_shape's HIGH-1 set. Sized off classic Windows MAX_PATH
# (260 -- the limit a clone without core.longpaths hits), minus the
# worst-case published prefix this member's own name cannot control:
# "federation/" (11) + the longest legal repo-id (pubgate.REPO_ID_MAX) +
# "/" (1). Computed from REPO_ID_MAX rather than a repeated literal so the
# two cannot drift the way the device-name sets did (round 3's MEDIUM-2).
#
# LOW-7 (round 4): a re-review flagged this check as unreachable, reasoning
# that `_reject_path_length` -- with its much smaller MAX_MEMBER_PATH_LEN
# bound -- "runs on the very next line" and so would always refuse first.
# Measured against this tree (a real tar member with a 5,003-character pax
# `path=` name, no monkeypatching): false. This check runs in the loop
# BEFORE `_reject_path_length` (see the "Bound the name before doing any
# work" comment above the call site) and independently refuses it with
# ITS OWN message ("longer than 4096 characters"); `_reject_path_length`
# never runs. The two bounds guard different things -- this one bounds the
# per-character-scan COST below, that one bounds what a Windows checkout
# can survive -- and neither one's threshold shadows the other's check at
# any name length, regardless of what MAX_MEMBER_PATH_LEN happens to be.
# Kept unchanged; already pinned at the real (unpatched) 4096 threshold by
# test_oversized_member_name_is_refused_before_any_per_character_scan,
# which asserts on THIS check's own message, not a path-length one.
#
# MEDIUM-1 (round 4, P45): the pre-round-4 derivation above allocated the
# ENTIRE Windows path budget to "federation/<repo-id>/<rel>" and left ZERO
# characters for the client's OWN clone root, which sits in front of all of
# it on disk. Reproduced on git 2.45.1.windows.1 with a FULLY COMPLIANT
# publish (repo-id 64 = REPO_ID_MAX, member path 184 = the pre-round-4
# bound, published path exactly 260 characters) cloned into
# `C:\Users\Admin\kbt\c3`: `git clone` rc=128, 1 of 2 files checked out,
# "Filename too long"; only `-c core.longpaths=true` clones it. That part
# of round 4 was right and stands.
#
# M1 (round 5, P45/P59): round 4's replacement CEILING of 214 does not
# reproduce and is withdrawn. Round 4 searched four clone-destination
# lengths and read a convergence at 214 -- a number it could not explain,
# 46 short of the textbook Windows MAX_PATH, and flagged as unexplained.
# Re-measured here with a FULL INTEGER SWEEP of the total absolute checkout
# path over [250, 266] at FIVE destination lengths (12, 24, 48, 72, 100
# characters), repo built by `git update-index --cacheinfo` plumbing so the
# source repo's own working tree never holds the long path, and
# `core.longpaths=false` forced on the clone command line with its value at
# every config scope printed (all unset here):
#
#     ALL FIVE destination lengths: 259 -> rc=0, deep file present
#                                   260 -> rc=128, "Filename too long"
#
# i.e. exactly classic MAX_PATH (260) minus its terminating NUL, agreeing
# with the round-3 verdict and the round-4 re-review. Round 4's 214 was a
# harness artifact: its cleanup used `shutil.rmtree(..., ignore_errors=True)`
# on a clone directory whose git pack files are read-only on Windows, so the
# directory survived and every subsequent iteration failed with "destination
# path already exists" -- a failure that reads exactly like the ceiling. The
# same artifact appeared in this round's first sweep (every destination
# length "converging" on the LOW end of the sweep window) and vanished once
# cleanup chmod'd before unlinking and each iteration got its own
# destination name. See the round-5 report for both logs.
#
# The reserve, re-derived from 259, term by term -- what is reserved, for
# what, and which terms are guesses:
#
#   259  measured ceiling (above): the largest total absolute checkout path
#        that clones rc=0 without core.longpaths. Not a guess.
#    -9  margin. A GUESS, and its size is 9 characters. It buys tolerance
#        for a git build, Windows edition or locale that lands a few
#        characters differently from the one measured here; nothing observed
#        in this round needs it. 250 is also a round number, which makes the
#        subtraction below legible.
#  = 250 SAFE_MAX_PATH -- the total absolute path this module budgets for.
#   -64  CLIENT_PREFIX_RESERVE, the client's own clone root plus the
#        separator joining it to the repo-relative path. `kb`'s primary
#        access path -- "the tool keeps a local hub clone fresh -- no manual
#        git clone" (README) -- puts that root at
#        `Path.home()/".strata-kb"/"hub"/<12-hex cache key>`. Worst
#        realistic length on Windows, measured: "C:\Users\" (9) + a
#        20-character username (the Windows local SAM account-name limit) +
#        "\.strata-kb\hub\" (16) + the 12-character cache key = 57, plus 1
#        for the separator = 58. Rounded up to 64: a GUESS of 6 characters'
#        margin, for a STRATA_KB_HUB_CACHE override one level deeper or a
#        longer drive/mount prefix.
#   -11  len("federation/"), the published tree's fixed prefix.
#   -64  REPO_ID_MAX -- the longest repo-id pubgate will accept. Computed
#        from the constant rather than a repeated literal so the two cannot
#        drift the way the device-name sets did (round 3's MEDIUM-2). Not a
#        guess; it is a hard bound enforced at registration.
#    -1  the "/" between the repo-id and the member's own path.
#  = 110 MAX_MEMBER_PATH_LEN.
#
# Checked against the shape this bound most has to admit, not only against
# the break point (round 5, coordinator finding): on the DOCUMENTED DEFAULT
# (`asset_store: mode: none`, so `assets_will_divert` is False and the
# exemption at the call site below does not apply), a content-addressed
# asset basename is `<64-hex-sha256>.png` = 68 characters, and
# ingestcmd always nests assets under `<doc-id>/assets/`, so the SHORTEST
# member path the product can produce is `d/assets/<sha>.png` = 77 and a
# realistic one is `arinc-424/assets/<sha>.png` = 85. The round-4 bound of
# 70 was BELOW the shortest producible one: `kb ci-publish` could not upload
# any image at all on the default configuration, and the whole archive was
# refused 400. At 110 both fit -- 85 with 25 characters to spare, which is
# every doc-id up to 34 characters (110 - 1 - len("assets/") - 68).
#
# The EXEMPTION GATE is deliberately left as it is. `assets_will_divert`
# is the right condition: when no asset store is configured the file is not
# diverted, it lands in the published git tree as a real tracked path, and
# a Windows client really does have to check it out -- so the Windows
# constraint genuinely applies and exempting it would manufacture the
# false-accept this bound exists to prevent (a long enough doc-id would
# still push a content-addressed asset past the budget). The defect was
# never the gate; it was that the number under it was smaller than the
# smallest thing the gate had to let through.
#
# The guarantee is scoped to the `kb` clone location above, not to an
# arbitrary manual `git clone` destination a user might choose deeper still
# -- no finite reserve can cover every possible one, and a manual clone
# beyond this reserve still has `core.longpaths` as a real workaround, named
# in the refusal message. Pinned end to end by
# test_maximal_compliant_publish_clones_without_longpaths.
SAFE_MAX_PATH = 250  # measured ceiling 259 (260 fails), minus a 9-char margin
CLIENT_PREFIX_RESERVE = 64
MAX_MEMBER_PATH_LEN = (
    SAFE_MAX_PATH - CLIENT_PREFIX_RESERVE - len("federation/") - REPO_ID_MAX - 1
)  # 110

# MEDIUM-3 (round 3): MAX_TAR_MEMBERS bounds *files*; the byte budget below
# bounds *declared bytes*; neither bounds how many directory LEVELS a
# member's own path creates. Measured: 10,000 members x 8-deep paths -- a
# 344 KB upload -- creates 80,000 directories (90,000 inodes with the
# files) and ~50s of one worker, entirely inside both existing caps. A real
# KB publish's directory count tracks its DOCUMENT count, not its file
# count: each doc-id contributes at most a couple of directories (the
# doc-id itself, an `assets/` child) no matter how many section files it
# holds, so even an unusually large multi-document repo-id plausibly stays
# in the low hundreds of directories -- 2,000 gives the same
# order-of-magnitude headroom over that which MAX_TAR_MEMBERS gives over a
# realistic file count.
MAX_TAR_DIRECTORIES = 2_000

# HIGH-1 (round 4) -- the round-3 fix bounded bytes READ from the stream,
# not the memory those bytes cause once tarfile decodes them. A pax 'x'
# (per-member extended) or 'g' (GLOBAL) header's body is fetched in ONE
# `fileobj.read(self._block(size))` call and then parsed into a Python
# dict by CPython's `_proc_pax` -- one dict ENTRY per record, at roughly
# 20x the record's own wire bytes in CPython dict/str overhead. For a
# GLOBAL header this dict is `TarFile.pax_headers` itself, retained for
# the life of the archive; for an extended header it is a fresh copy of
# the running global dict, but a single oversized one still costs the
# same peak while it is being built. Measured (harness quoted in full in
# the round-4 report): a 9.49 MB upload carrying one pax GLOBAL header of
# 4,032,308 distinct tiny records is ACCEPTED by the round-3 fix at peak
# RSS 1,038 MB against a 32.5 MB child-process baseline -- the stream
# bound charges the header's ~9 MB wire size once, correctly, and stops
# there; nothing bounds what parsing it builds.
#
# The stream bound cannot see this from the read() size alone: a
# legitimate GNU long-name ('L') header -- the ONLY extension header type
# `kb ci-publish`/`kb publish` ever emit, since `_build_archive` calls
# `tarfile.open(..., mode="w:gz")` with no `format=`, i.e. GNU_FORMAT, not
# PAX_FORMAT -- and a malicious pax 'x'/'g' header both arrive as one big
# `read(n)` call indistinguishable by size. What DOES distinguish them:
# `_proc_gnulong` never touches `TarFile.pax_headers` at all (it just sets
# `next.name`/`next.linkname`, ~1x amplification, already bounded by the
# stream charge above); only `_proc_pax` (pax 'x'/'g', never emitted by
# this codebase's own publisher) builds the ~20x dict. And empirically,
# for THIS repo's real archive shape, a pax/GNU header body read only ever
# exceeds one 512-byte block (`tarfile.BLOCKSIZE`) when it is carrying
# more than a bare long name: measured building the worst realistic
# LEGITIMATE archive -- MAX_TAR_MEMBERS members, every single one at
# MAX_MEMBER_PATH_LEN (forcing a GNU 'L' header on every member, the
# maximum extension-header load `kb ci-publish` can ever produce) -- every
# non-block-header read tarfile issues while parsing it is exactly 512
# bytes; NOT ONE exceeds that. So charging a SEPARATE, much smaller
# cumulative budget against only the header-phase reads whose *single*
# requested size is over `tarfile.BLOCKSIZE` costs this codebase's real
# publisher nothing (measured 0 bytes charged against it for that
# maximal-legitimate archive) while bounding what any pax 'x'/'g' header
# -- one huge one, or many small-but->512-byte ones, chained or not, since
# the charge is inside `read()` itself and fires on every qualifying call,
# not only when control returns to the member loop -- can make CPython
# allocate. 1 MiB gives roughly 2,000 headers' worth of slack over the
# zero this pipeline needs, while capping the worst case at ~1 MiB x 20 =
# ~20 MiB decoded, independent of `max_bytes`: see
# test_pax_metadata_bomb_is_bounded_independent_of_max_bytes.
MAX_PAX_METADATA_BYTES = 1024 * 1024

# HIGH-1 (round 5, P43) -- the round-4 budget above charges the READ, and a
# 512-byte header slips under it by construction: `_charge_metadata` returns
# early on `n <= tarfile.BLOCKSIZE`, and a pax header body of 512 bytes or
# less is fetched by exactly one `read(self._block(size))` = `read(512)`.
# That early return is CORRECT and has to stay -- an ordinary member's own
# ustar header block is also exactly one 512-byte header-phase read, so
# charging those against a small cumulative budget would refuse every
# legitimate multi-thousand-member archive (10,000 members x 512 = 5 MiB,
# five times the budget above). The hole is not the early return; it is
# that a read counter was the only bound.
#
# The input it misses: MANY pax-GLOBAL ('g') headers, each body <= 512 bytes,
# each carrying DISTINCT record keys, interleaved with real members (a bare
# chain of globals instead hits the RecursionError guard and a clean 400; one
# real member between each resets the recursion). CPython's `_proc_pax`
# accumulates a GLOBAL header's records into `TarFile.pax_headers` itself --
# shared and retained for the life of the archive -- and then EVERY ordinary
# member runs `_proc_builtin` -> `_apply_pax_info(tarfile.pax_headers, ...)`
# -> `self.pax_headers = pax_headers.copy()`, with every member's TarInfo
# retained in `TarFile.members`. Member p copies a dict of R*p entries, so
# retained entries total R*(1+2+...+P) = O(P^2) -- quadratic in member count,
# from an upload that stays a few hundred KB. Measured on this tree before
# this bound (harness and full search space in the round-5 report): 2,000
# (global, member) pairs = a 239 KB upload -> 2,853 MB peak RSS, ACCEPTED,
# with ZERO bytes charged against MAX_PAX_METADATA_BYTES and no single
# header-phase read above 512; 3,000 pairs -> 6,703 MB. Controls isolate the
# cause: 2,000 plain members with no pax at all peak at 37 MB, and 2,000
# GLOBAL headers repeating the SAME keys at 41 MB -- it is distinct keys
# ACCUMULATING, not header count or member count.
#
# So bound the decoded pax-header POPULATION, observed from the member loop:
# `member.pax_headers` is the dict this member actually retained, and it is
# always a superset of `TarFile.pax_headers` (a plain member gets a copy of
# it; a member with its own 'x' header gets that copy plus its own records).
# Bounding it makes the per-member copy O(1) instead of O(P), so total
# retained memory becomes linear in member count for every input shape.
#
# MAX_PAX_RECORDS is the load-bearing half. 64 because: this codebase's own
# publisher emits NONE (`_build_archive` opens with mode="w:gz" and no
# format=, i.e. GNU_FORMAT, which has no pax records at all); POSIX.1-2008
# defines twelve pax keywords in total (atime, charset, comment, gid, gname,
# hdrcharset, linkpath, mtime, path, size, uid, uname); and the vendor
# extensions actually seen in the wild -- GNU.sparse.* (eight distinct keys
# across all three sparse formats, counted from this CPython's own
# tarfile.py, and no single member uses more than about half of them),
# SCHILY.*, LIBARCHIVE.* -- keep a real member's header comfortably under
# twenty. 64 is roughly 3x the largest header this repo can name, and
# infinitely more than the zero its own publisher needs,
# while capping worst-case retained cost at MAX_TAR_MEMBERS x 64 entries --
# measured, not estimated: the maximal ACCEPTED shape (MAX_TAR_MEMBERS
# members, every one inheriting exactly 64 records) peaks at 56.9 MB
# against a 35.3 MB do-nothing baseline, i.e. ~21.7 MB for 640,000
# retained dict entries (~34 bytes each -- the cost of a dict copy whose
# key/value strings are shared with the global dict, not re-allocated).
#
# MAX_PAX_RECORD_BYTES is defence in depth, not the load-bearing half: the
# per-member copy shares its key/value STRING objects with the global dict,
# so a few huge values cost one copy of themselves, not one per member, and
# the summed decoded length is already bounded indirectly (values arriving
# in headers over 512 bytes are charged against MAX_PAX_METADATA_BYTES;
# values arriving in headers under it are count-bounded by MAX_PAX_RECORDS).
# It is checked anyway so that P43's "count OR summed length" is explicit and
# observable rather than implied by two other budgets, and so a future change
# to `_charge_metadata` cannot quietly reopen the value side. 64 KiB is ~1000
# characters per record at the record cap -- far past any legitimate header,
# far under the ~1 MiB the read charge alone would permit.
MAX_PAX_RECORDS = 64
MAX_PAX_RECORD_BYTES = 64 * 1024


class IntakeError(RuntimeError):
    """Publish intake rejected the request; maps to an HTTP status.

    Deliberately stays out of the KbError family (Wave G fix round 2, item
    7): server-side only, carries (status, detail) and maps to an HTTP
    response, not a CLI one-liner -- folding it in would make a CLI guard
    claim a contract it does not have.
    """

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


_jwks_client = None
_jwks_lock = threading.Lock()


def _default_key_resolver(token: str):
    """PyJWKClient resolves + caches GitHub's signing keys by `kid`."""
    global _jwks_client
    import jwt

    with _jwks_lock:
        if _jwks_client is None:
            _jwks_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True)
    return _jwks_client.get_signing_key_from_jwt(token).key


def verify_oidc(token: str, audience: str, key_resolver=None) -> dict:
    import jwt

    resolver = key_resolver or _default_key_resolver
    try:
        key = resolver(token)
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=GITHUB_ISSUER,
        )
    except jwt.PyJWTError as exc:
        raise IntakeError(401, f"OIDC token rejected: {exc}") from exc


_TAG_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def authorize(claims: dict, registry: models.Registry) -> str:
    """claims -> repo_id. The registry -- never the payload -- decides the write path."""
    from strata_kb.pubgate import GateError, normalize_repo_id

    ref = claims.get("ref", "")
    if not ref.startswith(TAG_REF_PREFIX):
        raise IntakeError(
            403, f"ref '{ref}' is not a {TAG_REF_PREFIX}* tag -- run `kb publish`"
        )
    # Exact segments, not a bare prefix: 'refs/tags/kb-publish/../../heads/main'
    # passes startswith() above and is the shape that becomes a hole the
    # moment the ref namespace grows.
    tail = ref[len(TAG_REF_PREFIX):]
    segments = tail.split("/")
    if not tail or not all(_TAG_SEGMENT_RE.fullmatch(s) for s in segments):
        raise IntakeError(403, f"ref '{ref}' is not a well-formed publish tag")
    repo = claims.get("repository", "")
    entry = registry.resolve(repo)
    if entry is None or not entry.repo_id:
        raise IntakeError(
            403,
            f"repo '{repo}' is not registered -- open a PR on the hub adding "
            f"`{repo}: <repo-id>` under `repos:` in federation/registry.yaml",
        )
    if entry.workflow and claims.get("job_workflow_ref", "") != entry.workflow:
        raise IntakeError(
            403,
            f"repo '{repo}' is pinned to workflow '{entry.workflow}' in "
            "federation/registry.yaml, but this token was minted by "
            f"'{claims.get('job_workflow_ref', '')}'",
        )
    try:
        return normalize_repo_id(entry.repo_id)
    except GateError as exc:
        raise IntakeError(500, f"registry maps '{repo}' to an unusable repo-id: {exc}")


# MEDIUM-2 (round 3): round 2's CONIN$/CONOUT$/COM0/LPT0/superscript-alias
# superset lived here as a local frozenset, unioned with pubgate.WIN32_DEVICES
# at the one call site below, because pubgate.py belonged to another
# implementer that round. It is in this round's scope, so the superset is
# folded directly into pubgate.WIN32_DEVICES itself instead -- the drift this
# was always meant to avoid (normalize_repo_id accepted 'LPT0' while this
# module's member check refused it; a registry entry mapping a publisher to
# that repo-id broke every Windows clone of the whole hub, measured) cannot
# recur if there is only one set to drift from.

# LOW-6 (round 3): '.git' (and the NTFS 8.3 short-name alias 'git~1' that
# aliases it on a filesystem old enough to generate 8.3 names) reach the
# hub's own `git add` and fail THERE -- a raw git stderr 502 instead of a
# clean 400 naming the component -- because Windows/NTFS is not the only
# consumer that refuses these; git itself does (core.protectNTFS), on every
# platform this service could run on. A git rule, not a Windows one, so it
# is checked unconditionally here rather than gated behind the Win32 set.
_GIT_DOTGIT_ALIASES = frozenset({".git", "git~1"})

# Every character Windows refuses to put in a filename, other than ':'
# (kept as its own check below for a more specific message) and '\'
# (checked separately, on the whole string, before this ever splits on '/').
_WIN32_ILLEGAL_CHARS = frozenset('<>"|?*')


def _reject_path_shape(label: str, rel: str) -> None:
    """Refuse a filesystem shape some consumer platform cannot represent.

    Applied per '/'-separated component, never anchored at position 0: the
    original guard here was `^[A-Za-z]:` matched against the whole string,
    so 'doc1/C:evil.md' passed (the drive shape was not in the leading
    segment) and, on the Linux host this service actually ships on
    (Dockerfile / docker-compose.yml), was committed to the hub verbatim --
    a name every Windows clone then fails to check out, for the WHOLE
    repository, not just that entry. A hostile shape buried in a
    non-leading segment reaches the same Path()/join the leading one does,
    and reaches a committed git path exactly the same way, so this checks
    every component.

    The refusal set is the union of what any consumer platform's
    filesystem cannot represent, not the shape rule of whichever OS this
    process happens to run on -- the hub is a Linux service writing a git
    repository that Windows, macOS and Linux clients all clone.

    Round 2: enumerated by property, not by example. Round 1's list was
    built from the review's own illustrations ('CON.md', 'NUL.md', a
    trailing dot/space at the very END of a component) rather than the
    rule those illustrations were showing, and that gap reproduced the
    identical measured outcome -- git clone rc=128, 0 files checked out,
    every repo-id on the hub -- for shapes the list did not happen to
    name: 'NUL .txt' (Windows strips a trailing space between a device
    name and its extension, so the device check must strip it too, not
    just the whole-component trailing-dot/space check, which only looks
    at the component's end); 'CONIN$'/'CONOUT$' (reserved names
    pubgate.WIN32_DEVICES did not carry); 30 of the 31 non-NUL C0 control
    characters (only NUL itself was refused); and '< > " | ? *'
    (Windows-illegal, POSIX-legal, in no clause at all). The predicate
    below is now the property itself: a component is refused when, on any
    consumer platform, it cannot be created or does not round-trip to
    itself -- every C0 control character (0x00-0x1F) and DEL (0x7F),
    every character Windows cannot put in a filename, every reserved
    device name in any case with a trailing space stripped from its stem
    first, and any component that differs from itself after Windows'
    trailing-dot-and-space stripping. Adding a platform's shape rule here
    means adding one predicate to this loop, not auditing a list of
    examples for coverage.

    Refuses, never rewrites: this only raises, it never hands back a
    modified name. Silently renaming a publisher's path would mean the hub
    serves content under a name the publisher never chose, and the
    publisher's next publish would then see a whole-tree diff.

    Does not judge an empty, '.' or '..' component here -- that is a
    traversal/degenerate-name question (see `_reject_traversal`), not a
    cross-platform-shape one: a caller-supplied delete path legitimately
    spells a leading './x', and this function must not refuse that shape
    outright, only normalize past it.

    Round 3: device names are read straight from `pubgate.WIN32_DEVICES`
    now (MEDIUM-2) -- the local superset that used to live only here is
    folded into pubgate's own set instead of unioned with it, so the
    member-name rule and the repo-id rule (`pubgate.normalize_repo_id`)
    share one definition and cannot drift apart again. `.git`/`git~1`
    (LOW-6) are refused here too, on every platform, since it is git's own
    core.protectNTFS rule this prevents from firing on the hub's commit,
    not a Windows-only concern.
    """
    if "\\" in rel:
        raise IntakeError(
            400, f"{label} '{rel}' uses a backslash -- use posix paths"
        )
    for part in rel.split("/"):
        if part in ("", ".", ".."):
            continue
        if part.casefold() in _GIT_DOTGIT_ALIASES:
            raise IntakeError(
                400,
                f"{label} '{rel}': component '{part}' is a git-reserved name "
                "on any platform",
            )
        for ch in part:
            cp = ord(ch)
            if cp < 0x20 or cp == 0x7F:
                # Covers NUL along with the other 31 C0 controls (and DEL)
                # in one predicate, rather than special-casing NUL alone.
                raise IntakeError(
                    400,
                    f"{label} '{rel}': component '{part}' contains a control "
                    "character -- rename it",
                )
            if ch == ":":
                raise IntakeError(
                    400,
                    f"{label} '{rel}': component '{part}' contains ':' -- "
                    "Windows reads it as a drive letter or an alternate "
                    "data stream",
                )
            if ch in _WIN32_ILLEGAL_CHARS:
                raise IntakeError(
                    400,
                    f"{label} '{rel}': component '{part}' contains a "
                    "character Windows cannot put in a filename",
                )
        if part != part.rstrip(". "):
            raise IntakeError(
                400,
                f"{label} '{rel}': component '{part}' ends in a dot or space "
                "-- Windows strips it silently",
            )
        # round 4 (P30): the stem-extraction + trailing-space-strip +
        # case-fold + membership check is now `pubgate.is_reserved_device_
        # name`, the one shared predicate `normalize_repo_id` also calls --
        # see its own comment for why two independent copies of this
        # check (against the one shared WIN32_DEVICES set) was the actual
        # drift risk, not the set's shape.
        stem = part.split(".", 1)[0]
        if is_reserved_device_name(stem):
            raise IntakeError(
                400,
                f"{label} '{rel}': component '{part}' is a reserved Windows "
                "device name",
            )


def _reject_traversal(label: str, rel: str) -> list[str]:
    """The non-empty, non-'.' components of `rel`, or IntakeError if it is
    absolute, escapes upward ('..'), or is empty/'.' once stripped.

    Works on the raw string, split on '/', before any `Path()` parse --
    the pre-fix escape check ran `".." in Path(rel).parts`, and on this
    Windows Python `Path("doc1/C:../evil.md").parts` does not contain '..'
    at all (pathlib's Windows flavour discards everything before a drive
    component when parsing, the exact mechanism HIGH-1 closes), so the
    parsed check was blind to a traversal riding a drive-shaped segment.
    Banning ':' in `_reject_path_shape` above already closes that specific
    case, but this stays raw-string-based rather than trusting a parse to
    agree with what was actually written on the wire.

    N-9: with ':' and '\\' both banned by `_reject_path_shape`, a mutant
    reverting this to `".." in Path(rel).parts` is very likely an
    equivalent mutant today -- no drive-shaped or backslash-shaped
    traversal can reach here anymore either way. Left undocumented before,
    this is exactly the "defense-in-depth claim no test can prove" this
    round's re-review flagged; recorded here rather than pretending a test
    could distinguish the two.

    One function, called from both `safe_extract`'s tar-member check and
    `intake_publish`'s delete-path check, so the two cannot drift the way
    they did before (member checked `Path(...).parts`, deletes checked a
    separately-typed `Path(...).parts` too).
    """
    if rel.startswith("/"):
        raise IntakeError(400, f"{label} '{rel}' is an absolute path")
    raw_parts = rel.split("/")
    if ".." in raw_parts:
        raise IntakeError(400, f"{label} '{rel}' escapes dest")
    parts = [p for p in raw_parts if p not in ("", ".")]
    if not parts:
        raise IntakeError(400, f"{label} '{rel}' is empty")
    return parts


def _reject_path_length(label: str, rel: str) -> None:
    """Refuse a name whose PUBLISHED path (federation/<repo-id>/<rel>),
    once checked out under the client's own clone root, cannot be checked
    out on Windows without `core.longpaths`.

    N-3 (round 3): MAX_MEMBER_NAME (4096) bounds what the per-character
    scans below cost, not what a Windows client can check out -- measured,
    both a 390-char and a 3000-char member path (far under 4096) give
    `git clone` rc=128 with only 1 of 4 files checked out on stock git for
    Windows. `-c core.longpaths=true` clones the identical tree cleanly,
    which is why this is a bound (MEDIUM) rather than a HIGH refusal
    folded into `_reject_path_shape`'s cross-platform-shape set -- unlike
    those shapes, a real client-side workaround exists and is named in the
    message below.

    MEDIUM-1 (round 4, P45): measures `len(rel.encode("utf-16-le")) // 2`
    -- Windows' own MAX_PATH counts UTF-16 CODE UNITS, not Python
    characters. `len(rel)` undercounts by half for any astral character
    (outside the Basic Multilingual Plane, encoded as a UTF-16 surrogate
    PAIR) -- exactly the kind of real writing-system content this
    predicate must not silently under-budget, the same class of gap P44
    closes for the display-spoofing predicate.

    `errors="surrogatepass"`: a lone/unpaired surrogate (reachable here --
    this runs before `_reject_path_shape`'s own unpaired-surrogate check
    further down the member loop) is not valid UTF-16 and plain
    `.encode("utf-16-le")` raises UnicodeEncodeError on it, which would
    escape as an uncaught 500 instead of this function's clean 400.
    surrogatepass round-trips it as its raw 16-bit unit instead -- still
    exactly one code unit, so the count stays accurate -- and lets control
    fall through to the later check that names this shape specifically.
    """
    utf16_len = len(rel.encode("utf-16-le", errors="surrogatepass")) // 2
    if utf16_len > MAX_MEMBER_PATH_LEN:
        raise IntakeError(
            400,
            f"{label} '{rel[:60]}...' is {utf16_len} UTF-16 code units -- "
            f"once published under federation/<repo-id>/, a path this "
            f"long cannot be checked out on Windows without `git -c "
            f"core.longpaths=true`; the limit here is {MAX_MEMBER_PATH_LEN} "
            "UTF-16 code units",
        )


# round-4 LOW (M9/M9b/M21): a separate Bidi_Control=Yes range table
# (Unicode 17.0.0 PropList.txt) used to live here, feeding an
# `_is_bidi_control(cp) or _is_default_ignorable(cp)` check below. Checked
# range-for-range against _DEFAULT_IGNORABLE_RANGES just below: all twelve
# Bidi_Control code points (U+061C, U+200E-200F, U+202A-202E, U+2066-2069)
# already fall inside it (U+200E-200F within 200B-200F, U+202A-202E and
# U+2066-2069 transcribed there verbatim). Bidi_Control characters carry no
# visible glyph of their own -- the same reason they are Default_Ignorable
# -- and that inclusion is a property of the Unicode Character Database
# itself, not an accident of this transcription, so `_is_bidi_control(cp)
# or` never changed which characters this predicate refused: a mutation
# deleting that disjunct passed every test in this file. Deleted rather
# than kept as an unexercised safety net -- an unused code path that LOOKS
# load-bearing (two clauses, docstring explaining why "two, not one") is
# worse than no code path, because a future reader has no way to tell it
# apart from a real one without doing this same audit again. If a future
# Unicode version ever adds a Bidi_Control character that is NOT also
# Default_Ignorable, `test_arabic_letter_mark_is_refused` and its
# siblings below will not catch that on their own -- re-derive and re-add
# the clause then, against the property tables current at the time.

# Unicode 17.0.0 DerivedCoreProperties.txt, Default_Ignorable_Code_Point=Yes
# -- characters with no visible glyph of their own, transcribed range-for-
# range from the property (adjacent source ranges merged where contiguous,
# e.g. 2060..2064 + 2065 + 2066..206F -> 2060..206F) rather than
# re-derived. Round 3 (N-4 correction iii): `unicodedata.category(ch) ==
# "Cf"` -- what shipped before this round -- is both too broad (it also
# refuses Cf characters that are NOT default-ignorable, e.g. the Arabic
# number-sign controls U+0600-0605) and too narrow (it misses
# default-ignorable characters outside category Cf, e.g. U+034F COMBINING
# GRAPHEME JOINER and the FE00-FE0F variation selectors, both category Mn
# -- measured accepted today, and both invisible enough to spoof a
# display name exactly as ZWSP does).
_DEFAULT_IGNORABLE_RANGES: tuple[tuple[int, int], ...] = (
    (0x00AD, 0x00AD),  # SOFT HYPHEN
    (0x034F, 0x034F),  # COMBINING GRAPHEME JOINER
    (0x061C, 0x061C),  # ARABIC LETTER MARK
    (0x115F, 0x1160),  # HANGUL CHOSEONG/JUNGSEONG FILLER
    (0x17B4, 0x17B5),  # KHMER VOWEL INHERENT AQ/AA
    (0x180B, 0x180F),  # MONGOLIAN FREE VARIATION SELECTOR 1-4 + VOWEL SEPARATOR
    (0x200B, 0x200F),  # ZERO WIDTH SPACE..RTL MARK (incl. ZWNJ/ZWJ)
    (0x202A, 0x202E),  # LEFT-TO-RIGHT EMBEDDING..RIGHT-TO-LEFT OVERRIDE
    (0x2060, 0x206F),  # WORD JOINER..NOMINAL DIGIT SHAPES
    (0x3164, 0x3164),  # HANGUL FILLER
    (0xFE00, 0xFE0F),  # VARIATION SELECTOR-1..16 (incl. VS16)
    (0xFEFF, 0xFEFF),  # ZERO WIDTH NO-BREAK SPACE / BOM
    (0xFFA0, 0xFFA0),  # HALFWIDTH HANGUL FILLER
    (0xFFF0, 0xFFF8),  # <reserved>
    (0x1BCA0, 0x1BCA3),  # SHORTHAND FORMAT LETTER OVERLAP..UP STEP
    (0x1D173, 0x1D17A),  # MUSICAL SYMBOL BEGIN BEAM..END PHRASE
    (0xE0000, 0xE0FFF),  # TAG characters + Variation Selectors Supplement
)

# N-4 correction (ii): ZWNJ/ZWJ are part of a word's spelling in Persian,
# Hindi, emoji ZWJ sequences and elsewhere -- they are Default_Ignorable
# (invisible) but are carved out of the invisible-character refusal below,
# the one explicit allowlist the ruling asks for.
_ZWNJ = 0x200C
_ZWJ = 0x200D

# P44 (round 4): the ZWJ/ZWNJ carve-out above is an instance of one test,
# not a special case of its own -- "a character a user legitimately needs
# in order to write the name they mean must be allowed; the collision key
# (which already strips every Default_Ignorable code point before
# comparing, see `_collision_key`), not the refusal, is what makes
# allowing it safe. Refuse a character whose only function is to alter
# how a sequence is DISPLAYED or ORDERED against what it says." Applying
# that test to the rest of Default_Ignorable:
#
# RULED IN:
#   - VARIATION SELECTOR-1..16 (U+FE00-FE0F) and the Variation Selectors
#     Supplement (U+E0100-E01EF, the astral continuation of the same
#     property): an emoji PRESENTATION sequence -- e.g. U+2764 U+FE0F,
#     the red-heart emoji -- is how that name is spelled, exactly as ZWNJ
#     is in Persian. Refusing VS16 does not prevent a spoof (the base
#     character alone still publishes); it just makes a name containing
#     a heart emoji unpublishable, which is a data-loss outcome, not a
#     spoof-prevention one.
#   - MONGOLIAN FREE VARIATION SELECTOR 1-4 (U+180B-180D, U+180F): the
#     identical mechanism as the emoji case above, for a different
#     script -- Mongolian has letterforms that are genuinely ambiguous in
#     plain text, and FVS is the standard way an author selects which
#     written form they mean. It selects a glyph variant of the
#     PRECEDING real letter, the same job a variation selector does.
#     U+180E MONGOLIAN VOWEL SEPARATOR is a different character with a
#     different function (a word-internal spacing control, not a glyph
#     selector) and is deliberately NOT included here.
#
# STAY REFUSED:
#   - COMBINING GRAPHEME JOINER (U+034F): its only job is to change
#     canonical-reordering/collation behavior. It does not select how any
#     character is displayed and is never itself part of what a name
#     says -- it is an ORDER-affecting control, the thing this predicate
#     exists to refuse, not a spelling.
#   - The Hangul fillers (U+115F, U+1160, U+3164, U+FFA0): they render as
#     blank width -- a placeholder for an ABSENT jamo in an otherwise-
#     incomplete syllable block, not a rendering of any real one. A name
#     built from fillers alone spells nothing; that is exactly the
#     all-invisible-name risk LOW-5 exists to close, not a script this
#     refusal would erase.
#   - The Khmer inherent vowel signs (U+17B4, U+17B5): ordinary Khmer
#     orthography never writes them -- the inherent vowel is implicit --
#     so they exist for internal/technical representation, not for
#     spelling a name a person would actually choose.
_VARIATION_SELECTORS: tuple[tuple[int, int], ...] = (
    (0xFE00, 0xFE0F),  # VARIATION SELECTOR-1..16
    (0xE0100, 0xE01EF),  # VARIATION SELECTOR-17..256 (supplement)
)
# L1 (round 5, P44): the second range is the Variation Selectors Supplement
# only. The surrounding Default_Ignorable block (U+E0000..U+E0FFF) ALSO holds
# the TAG characters (U+E0020..U+E007F) that spell emoji subdivision flags
# such as the England flag, and those are deliberately NOT exempted, so such
# a name is refused while the VS16 heart `❤️.md` publishes. That asymmetry is
# a decision, not an oversight: a variation selector only chooses a
# presentation for a character that is already there, whereas the general TAG
# mechanism was deprecated by Unicode precisely because it can carry
# arbitrary invisible ASCII inside any string -- the single highest-value
# spoofing primitive in this predicate's whole range -- and its one
# non-deprecated use, RGI subdivision flags, has no realistic presence in a
# published document filename. The cost of getting this wrong is asymmetric
# too: refusing a flag emoji costs a publisher one rename, with the refusal
# naming the character; admitting the TAG block would re-open invisible-text
# smuggling for every name. Pinned by
# test_an_emoji_tag_sequence_is_refused_while_a_variation_selector_publishes.
_MONGOLIAN_FVS = frozenset({0x180B, 0x180C, 0x180D, 0x180F})
_SPELLING_EXCEPTIONS = frozenset(
    {_ZWNJ, _ZWJ}
    | {cp for lo, hi in _VARIATION_SELECTORS for cp in range(lo, hi + 1)}
    | _MONGOLIAN_FVS
)


def _is_default_ignorable(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _DEFAULT_IGNORABLE_RANGES)


def _reject_display_spoofing(label: str, rel: str) -> None:
    """Refuse a bidi/formatting control character or a lone surrogate.

    LOW-5: an RTL override or a zero-width character in a member name is
    accepted verbatim today and makes a '.md' render as something else in
    the hub PR diff a maintainer reviews to merge it -- a display-spoofing
    risk independent of Unicode normalization (see `_collision_key`).

    Round 3 (N-4, corrected): refuses a character that has no visible
    glyph (Default_Ignorable), minus an explicit allowlist. Round 3
    originally also refused order-altering (Bidi_Control) characters as a
    second, separate clause; round 4 removed it as dead code (see
    `_DEFAULT_IGNORABLE_RANGES`'s comment above) once auditing it found
    every Bidi_Control code point already inside Default_Ignorable, which
    a lone-glyph-visibility rule was always going to catch on its own.

    Round 4 (P44): the allowlist is `_SPELLING_EXCEPTIONS` -- ZWNJ/ZWJ
    (N-4 correction ii) plus variation selectors and the Mongolian free
    variation selectors (see that set's own comment for the one-line test
    applied to each Default_Ignorable character and why CGJ, the Hangul
    fillers and the Khmer inherent vowel signs stay refused).

    U+00AD SOFT HYPHEN is deliberately NOT allowlisted alongside them: it
    is invisible and Default_Ignorable like they are, but unlike them it
    only hints an OPTIONAL hyphenation point -- no filesystem path needs a
    discretionary hyphen, dropping it loses no real content the way
    refusing ZWNJ would lose Persian/Hindi/emoji names, and refusing it
    matches what shipped before this round (it was already inside the
    blanket `Cf` refusal). See the round-3 report for the fuller
    reasoning.
    """
    for ch in rel:
        cp = ord(ch)
        if cp not in _SPELLING_EXCEPTIONS and _is_default_ignorable(cp):
            raise IntakeError(
                400,
                f"{label} '{rel}' contains a bidi/formatting control "
                "character -- refused to prevent a spoofed display name",
            )
        if 0xD800 <= cp <= 0xDFFF:
            raise IntakeError(400, f"{label} '{rel}' contains an unpaired surrogate")


def _collision_key(parts: list[str]) -> str:
    """The string two member names collide on if both were extracted --
    never what gets written (the write always uses the publisher's exact
    spelling; see `safe_extract`).

    Built as `NFC(casefold(name minus Default_Ignorable))`, folding three
    findings into one key instead of three separate checks that could
    drift apart:

    - N-11 caveat / LOW-1: built from `parts` -- the components
      `_reject_traversal` already normalized (dropped '' and '.',
      checked '..') -- not the raw member name, so a leading './' or a
      doubled '/' (which `Path()` already treats as the identical write
      target) cannot dodge the check that exists to catch exactly that:
      ['cafe.md', './cafe.md'] used to be accepted, silently overwriting
      one with the other.
    - LOW-2: casefolded, so ['A.md', 'a.md'] collides here too, instead of
      silently losing one file on any case-folding consumer filesystem
      (Windows, default macOS) with no refusal at intake time at all.
    - N-4 correction (iii): Default_Ignorable code points are stripped
      before casefolding. The only default-ignorable characters that can
      still reach this point are `_SPELLING_EXCEPTIONS` (round 4, P44:
      ZWNJ/ZWJ, the variation selectors and the Mongolian free variation
      selectors -- every other Default_Ignorable character is refused
      outright by `_reject_display_spoofing` above) -- stripping them
      here is what makes the collision rule the anti-spoof control N-4's
      original ruling assumed it already was, and stripping the SAME
      property this function refuses by (rather than an enumerated
      subset of it) is what keeps a future addition to
      `_SPELLING_EXCEPTIONS` closed by construction instead of needing a
      second, separately-maintained list here. Measured: NFC and NFKC
      both PRESERVE every invisible character, so 'report.md' and
      'repor<ZWNJ>t.md' never collided on NFC alone; the premise had to
      be made true, not assumed.
    """
    joined = "/".join(parts)
    stripped = "".join(ch for ch in joined if not _is_default_ignorable(ord(ch)))
    return unicodedata.normalize("NFC", stripped.casefold())


def _escape_for_log(name: str, limit: int = 200) -> str:
    """`name`, safe to place in a log line.

    LOW-2: a tar member name is attacker-controlled and may contain a
    newline, CR or ANSI escape -- unicode_escape renders all of those (and
    the C0/DEL characters _reject_path_shape already refuses before this
    is ever needed) as a literal, printable escape sequence rather than
    letting them forge a fake log line. Length is capped independently so
    one upload cannot flood the log.

    LOW-8 (round 3): the parenthetical above used to claim the NUL/control
    characters the other two guards refuse can never reach here -- false
    for C1 controls (0x80-0x9F) and U+2028/U+2029, neither of which either
    guard refuses, and exactly the characters a terminal or a line-oriented
    log reader treats specially. The escaping itself already handles them
    correctly; only the claim was wrong.
    """
    text = name.encode("unicode_escape").decode("ascii")
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


class _BoundedTarStream:
    """Wraps the DECOMPRESSED stream tarfile reads from, so nothing tarfile
    does with it -- parsing a ustar/GNU-longname/pax-extended/pax-GLOBAL
    header, or seeking past unconsumed data -- can pull more than `limit`
    decompressed bytes out of gzip before this raises. Everything else
    (`.tell()`, `.close()`) passes straight through.

    HIGH-1 (round 3): the round-2 fix charged a member its real header
    span (`offset_data - offset`) and refused a name over MAX_MEMBER_NAME
    -- both AFTER `tf.next()` had already returned a fully-materialized,
    fully-decoded member. But `tf.next()` itself, for a pax extended OR
    global header, calls `tarfile.fileobj.read(self._block(self.size))`
    for the HEADER'S OWN declared size -- attacker-controlled, unrelated
    to any name-length bound -- before this module's loop body, or
    MAX_MEMBER_NAME, or the byte budget, ever runs. Measured: a pax
    GLOBAL ('g') header is charged a flat 512 regardless of real size (the
    round-2 fix patches `next.offset` only for XHDTYPE/SOLARIS_XHDTYPE,
    never XGLTYPE); a 4.75 MB upload can carry 5 GB of 'g' header,
    ACCEPTED, uncharged, uncounted, 9.59s CPU; and a 1.94 MB upload drives
    peak RSS to 8.0 GB doing it -- on BOTH the 'x' path round 2 already
    charges correctly and the 'g' path it does not, because charging
    after the read cannot bound the allocation the read already made.
    Charging correctly-but-late fixes the accounting; it cannot fix the
    memory. Only bounding the STREAM every header type reads from, before
    tarfile is ever handed a read request it can act on, bounds both --
    for whichever header type comes next, not an enumerated set of them.

    `read()` charges the REQUESTED size before ever calling the inner
    stream, not the bytes actually returned: a `tarfile.fileobj.read(n)`
    for a huge `n` must never even be attempted once `n` alone would
    exceed the remaining budget, because attempting it is the allocation
    this exists to prevent. `seek()` charges a forward skip the same way,
    since GzipFile.seek() satisfies one by reading (and discarding)
    exactly that many decompressed bytes internally -- the same cost as a
    read, through a different call.

    Must wrap the stream `TarFile.__init__` itself reads from, not
    `TarFile.fileobj` after `tarfile.open()` returns: for mode "r", the
    constructor reads the FIRST member eagerly
    (`self.firstmember = self.next()`, still inside `open()`) -- exactly
    where this HIGH's own PoC (one pax GLOBAL header, then one ordinary
    member) sits. Measured: wrapping `tf.fileobj` after `tarfile.open()`
    returns leaves that first read completely unbounded -- the fix has to
    be handed to `tarfile.open()` as the `fileobj` argument itself, which
    is why `safe_extract` decompresses with `gzip.GzipFile` itself and
    opens tarfile in mode "r:" (already-decompressed bytes) rather than
    "r:gz" (tarfile does its own gzip wrapping internally, too late to
    intercept).

    LOW-5 (round 4): `_charge()` runs on every `read()`/`seek()` this class
    services, which is every byte tarfile pulls from the stream for a
    member -- its header block AND its content, block-padded to
    `tarfile.BLOCKSIZE` (tar never stores a partial trailing block; the
    padding bytes are real, still have to be read off the gzip stream, and
    so are real decompressed bytes this charge is correct to count). For a
    sub-block (<512-byte) file this roughly DOUBLES the effective per-
    member cost against `max_bytes` versus the older, pre-round-3
    accounting: measured, 10 members went from ~541 B/member of budget
    (5,410 B total) to ~1,024 B/member (10,752 B total, header block plus
    one padded content block each). This is correct -- those are real
    bytes CPython allocates copying off the stream -- but it means a
    publisher with many small files sitting near `max_tar_bytes` can newly
    get a 413 that a purely "upload size vs. max_tar_bytes" mental model
    would not predict; recorded here since neither the README nor any
    other doc said so before this round.

    HIGH-1 (round 4): the bound above charges bytes READ, not memory
    ALLOCATED once tarfile decodes them -- a pax 'x'/'g' header's body is
    fetched in one `read(n)` call and then parsed into a Python dict at
    ~20x its wire size (measured; see MAX_PAX_METADATA_BYTES). `read()`
    now ALSO charges any header-phase call requesting more than one
    `tarfile.BLOCKSIZE` against a second, much smaller, cumulative budget
    -- "header-phase" meaning `reading_content` is False, which
    `safe_extract` sets True only around its own explicit
    `tf.extractfile(member).read()` call, so a legitimate member's actual
    content (arbitrarily large, already governed by the budget above) is
    never charged against it. The charge happens inside `read()` itself,
    the same call CPython's `_proc_pax` makes for every header in a
    chain -- including ones that never return control to `safe_extract`'s
    member loop because they are still being resolved recursively inside
    a single `tf.next()` call -- so it bounds one giant header AND a chain
    of smaller ones the same way, not only whatever the loop can see
    after the fact.
    """

    def __init__(
        self,
        inner,
        limit: int,
        metadata_limit: int = MAX_PAX_METADATA_BYTES,
    ) -> None:
        self._inner = inner
        self._limit = limit
        self._consumed = 0
        self._metadata_limit = metadata_limit
        self._metadata_consumed = 0
        # Toggled by safe_extract around its own content read; False
        # (header-phase) for everything else, including the eager first
        # read `tarfile.open()` makes before safe_extract ever gets this
        # object back.
        self.reading_content = False

    def _charge(self, n: int) -> None:
        if n <= 0:
            return
        if self._consumed + n > self._limit:
            raise IntakeError(413, f"archive content exceeds {self._limit} bytes")
        self._consumed += n

    def _charge_metadata(self, n: int) -> None:
        if n <= tarfile.BLOCKSIZE:
            return
        if self._metadata_consumed + n > self._metadata_limit:
            raise IntakeError(
                413,
                f"archive header metadata exceeds {self._metadata_limit} bytes",
            )
        self._metadata_consumed += n

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            # No caller on this path ever asks tarfile.fileobj to read to
            # EOF (every header parser passes an explicit block-aligned
            # size) -- refuse the request rather than trust that holds.
            raise IntakeError(413, "archive requested an unbounded read")
        self._charge(size)
        if not self.reading_content:
            self._charge_metadata(size)
        return self._inner.read(size)

    def seek(self, position: int, whence: int = 0) -> int:
        if whence != 0:
            raise IntakeError(400, "archive stream seek: unsupported whence")
        current = self._inner.tell()
        if position > current:
            self._charge(position - current)
        return self._inner.seek(position, whence)

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._inner.tell()

    def close(self) -> None:
        self._inner.close()


def _is_diverted_asset_name(name: str) -> bool:
    """True for a member whose shape matches what `assetstore.divert_assets`
    actually diverts: immediate parent directory literally named "assets",
    basename a bare `<64-hex-sha256>.png`/`.webp` (`assetstore._ASSET_NAME_RE`
    -- referenced directly rather than duplicated, so the two can't drift
    apart). Used only to decide whether `_reject_path_length` applies (see
    its call site's comment) -- every other check in the member loop still
    runs on these members unchanged."""
    p = Path(name)
    return p.parent.name == "assets" and bool(assetstore._ASSET_NAME_RE.match(p.name))


def safe_extract(
    data: bytes,
    dest: Path,
    max_bytes: int = DEFAULT_MAX_TAR,
    assets_will_divert: bool = False,
) -> None:
    if len(data) > max_bytes:
        raise IntakeError(413, f"archive exceeds {max_bytes} bytes")
    # HIGH-1: decompress ourselves and hand tarfile.open() the WRAPPED,
    # already-decompressed stream (mode "r:") instead of the raw
    # compressed bytes (mode "r:gz", where tarfile builds its own GzipFile
    # internally) -- TarFile.__init__ reads the first member eagerly, as
    # PART OF tarfile.open() itself, so wrapping tf.fileobj after open()
    # returns would leave exactly that first read (where this HIGH's own
    # PoC sits) unbounded. See _BoundedTarStream's docstring.
    gz = gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb")
    bounded = _BoundedTarStream(gz, max_bytes)
    try:
        tf = tarfile.open(fileobj=bounded, mode="r:")
    except (tarfile.TarError, OSError, EOFError, RecursionError) as exc:
        # OSError/EOFError: opening tarfile no longer routes through
        # tarfile's own gzopen(), which used to translate a GzipFile
        # construction/read failure (bad magic bytes, truncated CRC
        # trailer) into a TarError itself -- replicated here so an invalid
        # or truncated archive still maps to this function's clean 400,
        # not an uncaught exception from the eager first read. RecursionError
        # here is the LOW-5 case (chained headers) landing during that same
        # eager first read rather than during later iteration.
        raise IntakeError(400, f"archive is not a valid tar.gz: {exc}") from exc
    dest_resolved = dest.resolve()
    with tf:
        total = 0
        count = 0
        seen_dirs: set[str] = set()
        seen_keys: dict[str, str] = {}
        try:
            # Lazy iteration: `for member in tf` reads one header at a time,
            # so the cumulative cap below aborts after ~max_bytes
            # decompressed. getmembers() would walk (decompress) the ENTIRE
            # archive up front just to list headers -- a crafted tar bomb
            # could force tens of GB of decompression before the cap ever
            # ran.
            for member in tf:
                count += 1
                if count > MAX_TAR_MEMBERS:
                    raise IntakeError(
                        413, f"archive holds more than {MAX_TAR_MEMBERS} members"
                    )
                # Bound the name before doing any work proportional to its
                # length: this check and the byte-budget charge just below
                # are both O(1)/cheap arithmetic on data tarfile already
                # parsed, so both run before _reject_path_shape /
                # _reject_display_spoofing -- the two per-character scans a
                # long pax/GNU name previously made expensive (see
                # MAX_MEMBER_NAME's comment above).
                if len(member.name) > MAX_MEMBER_NAME:
                    raise IntakeError(
                        400,
                        f"tar member name is longer than {MAX_MEMBER_NAME} "
                        "characters -- shorten it",
                    )
                # HIGH-1 (round 5, P43): bound the DECODED pax-header
                # population this member inherited, not the bytes the
                # header was read in -- see MAX_PAX_RECORDS's comment for
                # why a read counter cannot see the input that matters
                # (every header read is exactly one 512-byte block) and
                # for the quadratic mechanism behind it. This is the
                # quantity that drives retained memory: tarfile has
                # already handed this member its own `pax_headers.copy()`
                # and retained the TarInfo in `TarFile.members`, so
                # bounding it HERE, once per member, is what keeps the
                # next member's copy O(1) and the archive's total retained
                # cost linear in member count. `len()` is O(1) and the
                # summed length is O(MAX_PAX_RECORDS) once the count check
                # above has passed, so a legitimate archive (empty dict)
                # pays nothing. Deliberately placed after the name bound
                # above so an over-long pax `path=` name still gets its own
                # message rather than this one.
                pax = member.pax_headers
                if pax:
                    if len(pax) > MAX_PAX_RECORDS:
                        raise IntakeError(
                            413,
                            f"tar member '{_escape_for_log(member.name, 60)}' "
                            f"inherits {len(pax)} pax header records, more "
                            f"than the {MAX_PAX_RECORDS} allowed -- re-create "
                            "the archive with GNU tar format (`tar --format="
                            "gnu`), which writes no pax headers at all",
                        )
                    # Values are always `str`: CPython's `_proc_pax` stores
                    # only `_decode_pax_field` results, and `_apply_pax_info`
                    # copies that dict unmodified (its numeric conversion
                    # writes to a local, not back into the dict).
                    decoded = sum(len(k) + len(v) for k, v in pax.items())
                    if decoded > MAX_PAX_RECORD_BYTES:
                        raise IntakeError(
                            413,
                            f"tar member '{_escape_for_log(member.name, 60)}' "
                            f"inherits {decoded} bytes of decoded pax header "
                            f"records, more than the {MAX_PAX_RECORD_BYTES} "
                            "allowed -- re-create the archive with GNU tar "
                            "format (`tar --format=gnu`), which writes no "
                            "pax headers at all",
                        )
                # MEDIUM-1 exemption: a content-addressed asset
                # (doc/.../assets/<sha256>.png|webp) that this publish will
                # actually divert to the configured asset store never lands
                # in the published git tree a Windows client checks out --
                # divert_and_record strips it back out and replaces it with
                # a name-only reference in _assets.yaml before anything is
                # committed. Its basename length is fixed by the hash
                # function (not attacker-chosen), and its full path can
                # legitimately run past MAX_MEMBER_PATH_LEN simply from
                # normal doc/section nesting, so binding it to the
                # Windows-checkout bound would refuse real uploads for a
                # constraint that does not apply to them. When no store is
                # configured for this publish, the same-shaped file is NOT
                # diverted and stays a real tracked path -- the bound must
                # still apply, so the exemption is gated on
                # `assets_will_divert`, which the caller sets from the same
                # resolved store used later to decide whether diversion
                # actually happens (see intake_publish).
                #
                # Round 5 (M1): re-examined and KEPT as `assets_will_divert`,
                # not widened to "the name is content-addressed". At the
                # round-4 bound of 70 this gate looked like the bug -- on the
                # documented default (`asset_store: mode: none`) it is always
                # False, and the shortest asset path the product can produce
                # is 77, so no image could be published at all. But widening
                # the gate would drop the Windows bound for a file that
                # really does get committed and checked out; the number was
                # what was wrong, and MAX_MEMBER_PATH_LEN is now 110. See its
                # comment for the arithmetic and
                # test_content_addressed_assets_publish_on_the_default_store,
                # which pins both halves (77 and 85 accepted undiverted, a
                # genuinely over-long asset path still refused).
                if not (assets_will_divert and _is_diverted_asset_name(member.name)):
                    _reject_path_length("tar member", member.name)
                # Headers are not free (HIGH-2): a member's declared content
                # may be 0 bytes, but tarfile still spent header bytes
                # decompressing and parsing it, so a bomb of all-zero-byte
                # members must count against the byte budget too, not just
                # the member-count cap above. `offset_data - offset` is the
                # REAL span every header block for this member consumed --
                # the ustar/GNU header, plus any pax extended header that
                # preceded it -- not a flat tarfile.BLOCKSIZE that charged a
                # multi-megabyte pax name the same nominal 512 bytes as an
                # ordinary short one (round-2 HIGH-2: measured 26x CPU
                # amplification from that gap, closed here plus the length
                # bound above). This is now belt-and-suspenders with
                # _BoundedTarStream above for ordinary/pax/GNU headers --
                # kept because it also charges a GNU sparse member's
                # EXPANDED size, which the stream bound cannot see (sparse
                # "holes" are synthesized zero-fill, never actually read
                # from the stream), so it catches a declared-size bomb the
                # stream-read bound does not. Round-4 LOW (M20): this claim
                # was unproven -- pinned by
                # test_sparse_member_is_charged_by_its_expanded_size_not_its_wire_size
                # (a 40-byte-on-the-wire pax GNU.sparse.realsize member
                # declaring 10,000,020 bytes real size is refused at a
                # 1,000,000-byte cap purely from `member.size`).
                total += member.size + (member.offset_data - member.offset)
                if total > max_bytes:
                    raise IntakeError(
                        413, f"archive content exceeds {max_bytes} bytes"
                    )
                if not member.isreg():
                    raise IntakeError(
                        400, f"tar member '{member.name}' is not a regular file"
                    )
                _reject_path_shape("tar member", member.name)
                parts = _reject_traversal("tar member", member.name)
                # MEDIUM-3: bound the number of DISTINCT directory paths this
                # archive would create, not just the number of files or
                # declared bytes -- see MAX_TAR_DIRECTORIES's comment.
                for i in range(1, len(parts)):
                    seen_dirs.add("/".join(parts[:i]))
                if len(seen_dirs) > MAX_TAR_DIRECTORIES:
                    raise IntakeError(
                        413,
                        f"archive would create more than {MAX_TAR_DIRECTORIES} "
                        "directories",
                    )
                _reject_display_spoofing("tar member", member.name)
                # LOW-5 / N-11 caveat (LOW-1) / LOW-2 / N-4(iii): one
                # collision key now covers normalization, traversal-
                # equivalence, case-folding and invisible-character
                # stripping together -- see _collision_key's docstring.
                key = _collision_key(parts)
                if key in seen_keys and seen_keys[key] != member.name:
                    raise IntakeError(
                        400,
                        f"tar member '{member.name}' collides with "
                        f"'{seen_keys[key]}' once normalized -- rename one",
                    )
                seen_keys[key] = member.name
                rel = Path(member.name)
                try:
                    # N-5: resolve() itself can raise. MAX_MEMBER_NAME (4096
                    # characters) bounds the scans above, but it is still
                    # well past classic Windows path-length limits once
                    # joined to `dest`'s own prefix -- a long member name can
                    # raise ValueError('path too long for Windows') right
                    # here, and this used to sit OUTSIDE the translation
                    # below, so that one shape reached the route's generic
                    # backstop as a 500 instead of this function's own clean
                    # 400. Everything from here through the write is one
                    # translated region now.
                    target = (dest / rel).resolve()
                    if not target.is_relative_to(dest_resolved):
                        raise IntakeError(
                            400, f"tar member '{member.name}' escapes dest"
                        )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = tf.extractfile(member)
                    assert src is not None  # noqa: S101 -- type narrowing, isreg() checked above
                    # HIGH-1 (round 4): this is the one place a read of the
                    # member's own (already-budgeted) content is expected
                    # to be large -- exempt it from the header-metadata
                    # budget, which exists to bound tarfile's OWN internal
                    # pax/GNU header parsing, not a legitimate file's
                    # bytes. See _BoundedTarStream's docstring.
                    bounded.reading_content = True
                    try:
                        payload = src.read()
                    finally:
                        bounded.reading_content = False
                    target.write_bytes(payload)
                except (OSError, ValueError) as exc:
                    # MEDIUM-2: a member shape that reaches here unrejected
                    # -- e.g. one member named 'assets' (a file) followed by
                    # 'assets/x.png' -- raises PermissionError/
                    # FileExistsError/NotADirectoryError depending on OS and
                    # order, and a resolve() on an embedded-NUL name raises
                    # ValueError. Unhandled, this was an uncaught 500 with
                    # the job's status left at "processing" forever (the
                    # route catches only IntakeError, GitError and
                    # GHAppError). Every path out of extraction must reach a
                    # terminal state.
                    raise IntakeError(
                        400, f"tar member '{member.name}' cannot be written: {exc}"
                    ) from exc
        except RecursionError as exc:
            # Round 3, review-waveH-fix2-verdict.md's LOW-5 (a distinct
            # finding from this module's own pre-existing "LOW-5" label a
            # few lines above, which is about NFC/case/traversal
            # collisions, not recursion): CPython's tar header parser
            # recurses once per chained extended/GNU-longname header
            # (`_proc_pax`/`_proc_gnulong` each fetch the NEXT header via a
            # recursive call). Measured: 1,200 chained 'g' headers -- a
            # 6.4 KB upload -- hits
            # RecursionError inside `tf.next()`, which is neither OSError
            # nor ValueError nor tarfile.TarError, so it used to escape
            # this function entirely and reach the route's generic 500
            # backstop -- an attacker-chosen 500 on a surface whose whole
            # point is that attacker-chosen input gets a 400.
            raise IntakeError(
                400, "archive contains pathologically nested extended headers"
            ) from exc
        except tarfile.TarError as exc:
            # A malformed/truncated archive can also fail mid-iteration,
            # not just at tarfile.open() -- the pre-round-3 code only
            # wrapped open() itself, leaving this the same kind of
            # uncaught-500 gap RecursionError above has.
            raise IntakeError(400, f"archive is not a valid tar.gz: {exc}") from exc


class StatusStore:
    """(repo_id, commit) -> {state, pr_url, detail}; thread-safe; optional JSON persistence."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if path is not None and path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("intake status file unreadable -- starting empty")

    @staticmethod
    def _key(repo_id: str, commit: str) -> str:
        return f"{repo_id}@{commit}"

    def set(
        self, repo_id: str, commit: str, state: str, pr_url: str = "", detail: str = ""
    ) -> None:
        with self._lock:
            self._data[self._key(repo_id, commit)] = {
                "state": state, "pr_url": pr_url, "detail": detail,
            }
            if self._path is not None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                # newline-exempt: server-side PR-state file under
                # ~/.strata-kb/hub (IntakeConfig.status_path), never committed.
                self._path.write_text(json.dumps(self._data), encoding="utf-8")

    def get(self, repo_id: str, commit: str) -> dict | None:
        with self._lock:
            return self._data.get(self._key(repo_id, commit))


_repo_locks: dict[str, threading.Lock] = {}
_repo_locks_guard = threading.Lock()


def repo_lock(repo_id: str) -> threading.Lock:
    with _repo_locks_guard:
        return _repo_locks.setdefault(repo_id, threading.Lock())


# One hub, one set of refs: worktree add/remove and the ref updates around it
# are serialised process-wide. repo_lock(rid) still owns same-rid
# idempotence; this owns the shared repository state underneath it.
_hub_write_lock = threading.Lock()


@dataclass
class IntakeConfig:
    hub_ref: str
    audience: str
    creds: ghapp.AppCreds
    status_path: Path | None = None
    max_tar_bytes: int = DEFAULT_MAX_TAR
    key_resolver: object = None  # test seam -- None = real PyJWKClient
    http: object = None  # test seam -- None = real urllib
    push_via_token_url: bool = True  # False in tests: push plain origin, no token URL
    trusted_proxies: int = 0  # X-Forwarded-For hops to trust; 0 = ignore the header
    pr_hook: object = None  # test seam -- None = ghapp.create_or_get_pr


def intake_config_from_env(hub_ref: str) -> IntakeConfig | None:
    """Build IntakeConfig from env; None (intake disabled, read server still runs)
    when any of STRATA_KB_GH_APP_ID/STRATA_KB_GH_APP_KEY/STRATA_KB_INTAKE_AUDIENCE
    is missing or the PEM is unreadable. Raises SystemExit (no traceback, same
    convention as mcp.py's other operator-config errors) when
    STRATA_KB_TRUSTED_PROXIES is set but not a valid non-negative integer."""
    import os

    app_id = os.environ.get("STRATA_KB_GH_APP_ID", "")
    key_path = os.environ.get("STRATA_KB_GH_APP_KEY", "")
    audience = os.environ.get("STRATA_KB_INTAKE_AUDIENCE", "")
    if not (app_id and key_path and audience):
        logger.info(
            "intake disabled -- set STRATA_KB_GH_APP_ID, STRATA_KB_GH_APP_KEY, "
            "STRATA_KB_INTAKE_AUDIENCE to enable /intake/publish"
        )
        return None
    try:
        pem = Path(key_path).read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("intake disabled -- cannot read App key '%s': %s", key_path, exc)
        return None
    # STRATA_KB_TRUSTED_PROXIES governs both this route's rate limiter and
    # the web UI's login limiter (web.ui.login_post) -- ratelimit.py owns
    # the one parser and the loud-failure rules (SystemExit, no traceback,
    # same convention as mcp.py's other operator-config errors) so the two
    # limiters cannot drift out of sync. See trusted_proxies_from_env's
    # docstring for the full rationale.
    trusted_proxies = ratelimit.trusted_proxies_from_env()
    return IntakeConfig(
        hub_ref=hub_ref,
        audience=audience,
        creds=ghapp.AppCreds(app_id=app_id, private_key_pem=pem),
        status_path=hub_mod._cache_base() / "intake-status.json",
        trusted_proxies=trusted_proxies,
    )


def _resolve_hub_or_503(hub_ref: str) -> hub_mod.HubHandle:
    # resolve_hub can now raise gitio.GitError (Important 3, hub.py's
    # _discard_cache) when a stale cache cannot be removed -- e.g. Windows
    # holding a lock on <cache>/.kb-work/search.sqlite3 while a request is
    # served. Before that guard, this was an unhandled 500; a locked cache
    # is exactly the transient, recoverable condition 503 exists for.
    try:
        handle = hub_mod.resolve_hub(hub_ref)
    except gitio.GitError as exc:
        raise IntakeError(503, f"hub cache is unusable right now: {exc}") from exc
    if handle is None:
        raise IntakeError(503, "hub unreachable from the intake server")
    return handle


def check_serving_clone(handle: hub_mod.HubHandle) -> list[str]:
    """Warning lines about a hub clone that is not fit to serve from.

    Before intake_publish wrote in its own worktree, a crashed or concurrent
    publish could leave the serving clone checked out on publish/<rid>
    permanently -- and the read side (kb query, MCP tools, web UI) then
    served that unmerged branch until someone fixed it by hand. This is how
    an operator finds out at startup.

    Also prunes worktree records for directories that no longer exist on
    disk (crash cleanup), the same call intake_publish makes before adding
    a new one -- a stale record here is otherwise only discovered the next
    time something tries to reuse its branch.
    """
    gitio.worktree_prune(handle.root)
    _reclaim_leaked_worktrees(handle.root)
    warnings: list[str] = []
    try:
        current = gitio.current_branch(handle.root)
    except gitio.GitError as exc:
        return [f"could not read the hub clone's branch: {exc}"]
    if gitio.has_remote(handle.root):
        head_check = gitio._run(
            handle.root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"
        )
        if head_check.returncode != 0:
            # I-1: default_branch() falls back to current_branch() when
            # origin/HEAD is unset, so `current != default` below can never
            # be true here -- comparing a value against itself and finding
            # it always equal is not the same as the clone being healthy.
            # This is exactly the shape tests/conftest.py's hub_with_origin
            # builds (a real bare origin pushed to, but no `remote set-head`
            # run against it), and the same shape resolve_hub's local-path
            # branch (hub.py) produces for any hub directory used directly.
            return [
                f"the hub clone at {handle.root} has no origin/HEAD, so its "
                "default branch cannot be determined; fix with: git -C "
                f"{handle.root} remote set-head origin -a"
            ]
    default = gitio.default_branch(handle.root)
    if current != default:
        warnings.append(
            f"the hub clone at {handle.root} is on branch '{current}', not "
            f"'{default}' -- it is serving content that may not be merged; fix "
            f"with: git -C {handle.root} checkout {default}"
        )
    return warnings


def _reclaim_leaked_worktrees(root: Path) -> None:
    """Force-remove any registered `publish/*` worktree, other than the main
    one, whose directory still exists.

    I-5: `git worktree prune` (called just before this) only forgets a
    worktree record once its directory is gone. A crash between
    `worktree_add` and `worktree_remove` in `intake_publish` can leave the
    directory in place -- `tempfile.TemporaryDirectory` cannot guarantee
    cleanup after a hard kill -- so the record survives forever and the
    next publish for that repo-id fails with "already used by worktree at
    ...", a permanent 502 for that one repo-id until an operator removes it
    by hand. This is the automatic version of that removal, run at the
    same startup check that already prunes the gone-directory case.
    """
    proc = gitio._run(root, "worktree", "list", "--porcelain")
    if proc.returncode != 0:
        return
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current.setdefault(key, value)
    if current:
        entries.append(current)
    leaked = False
    for entry in entries[1:]:  # entries[0] is the main worktree (handle.root)
        if entry.get("branch", "").startswith("refs/heads/publish/"):
            path = entry.get("worktree", "")
            if path:
                gitio._run(root, "worktree", "remove", "--force", path)
                leaked = True
    if leaked:
        gitio.worktree_prune(root)


def _dest_for_rid(federation_dir: Path, rid: str) -> Path:
    """Validate `rid` before treating it as a federation/ subpath.

    authorize() already validates rid via the registry in the normal intake
    flow, but intake_publish/hub_manifest are callable directly (tests,
    tooling) -- re-validate rather than trust the caller.

    LOW-3: this used to re-implement a weaker check (`REPO_ID_RE.fullmatch`
    plus a literal '.'/'..' check) instead of calling
    `pubgate.normalize_repo_id` the way authorize() does -- so a rid that
    normalize_repo_id would refuse (over the length cap, ending in a dot,
    a reserved Windows device name) passed here, and -- because this is the
    check that unconditionally runs on every intake_publish call, not just
    authorize()'s -- the case-collision guard never ran on the real HTTP
    path at all. `existing` is best-effort (the directories already on
    disk under handle.root's federation/, not a lock-held read), matching
    normalize_repo_id's own "mistake guard, not exhaustive" scope.
    """
    from strata_kb.pubgate import GateError, normalize_repo_id

    existing = (
        [p.name for p in federation_dir.iterdir() if p.is_dir()]
        if federation_dir.is_dir()
        else []
    )
    try:
        normalize_repo_id(rid, existing=existing)
    except GateError as exc:
        raise IntakeError(400, str(exc)) from exc
    dest = federation_dir / rid
    if not dest.resolve().is_relative_to(federation_dir.resolve()):
        raise IntakeError(400, f"repo-id '{rid}' escapes the federation/ directory")
    return dest


def hub_manifest(hub_ref: str, rid: str) -> dict[str, str]:
    handle = _resolve_hub_or_503(hub_ref)
    dest = _dest_for_rid(handle.federation_dir, rid)
    man = hashsync.build_manifest(
        dest, exclude=("_meta.yaml", assetstore.RECORD_NAME)
    )
    # Gate synthesis on the hub's own configured store, same rule
    # publish._snapshot applies (active_store is not None) -- a hub with no
    # asset_store block has no diverted assets to synthesize entries for.
    store = assetstore.store_for_hub(handle)
    if store is not None:
        man.update(assetstore.synthesized_asset_entries(dest))
    return man


_HUB_OWNED_BASENAMES = frozenset(
    name.casefold() for name in ("_meta.yaml", assetstore.RECORD_NAME)
)


def _clean_deletes(deletes: list[str]) -> list[str]:
    """Validate every caller-supplied delete path, and drop the hub-owned
    ones -- comparing (and returning) the NORMALIZED spelling.

    MEDIUM-1: the filter this replaces compared the raw attacker string for
    EXACT equality against ("_meta.yaml", assetstore.RECORD_NAME), while
    the deletion this list drives (hashsync._guard, later) resolves a
    NORMALIZED path -- so a leading './', a trailing space/dot, or a case
    difference on a case-folding filesystem all read the same file on disk
    but compared unequal here, and each one let a publish erase the hub's
    own '_assets.yaml' bookkeeping for its own entry (measured: './',
    './/', and, filesystem-dependent, a case difference). Comparing on the
    normalized basename -- and passing that same normalized spelling
    onward, so divert_and_record subtracts the identical string -- closes
    every one of those spellings in the one place this list is built,
    rather than requiring the exact same spelling to be re-derived at each
    downstream consumer.
    """
    clean: list[str] = []
    for rel in deletes:
        _reject_path_shape("delete path", rel)
        parts = _reject_traversal("delete path", rel)
        # N-10: hub-owned bookkeeping lives ONLY at the rid root --
        # assetstore.py writes RECORD_NAME as `dest / RECORD_NAME` and
        # intake.py writes `_meta.yaml` the same way, never nested -- so
        # matching on `parts[-1]` regardless of depth silently dropped a
        # child's own, legitimately nested `doc1/_assets.yaml` or
        # `doc1/_meta.yaml` delete too. len(parts) == 1 keeps exactly
        # MEDIUM-1's protection (every normalized spelling of the
        # top-level file: '_assets.yaml', './_assets.yaml', '_ASSETS.yaml'
        # all normalize to a single-part list) without over-refusing a
        # nested file that merely shares the same name.
        if len(parts) == 1 and parts[0].rstrip(". ").casefold() in _HUB_OWNED_BASENAMES:
            continue  # hub-owned bookkeeping; silently ignored, never deleted
        clean.append("/".join(parts))
    return clean


def intake_publish(
    cfg: IntakeConfig,
    rid: str,
    source_commit: str,
    source_repo_full: str,
    deletes: list[str],
    archive: bytes,
    store=None,
) -> str:
    """Apply an uploaded snapshot on branch publish/<rid>, in its own git
    worktree, and open the hub PR.

    Returns the PR URL, or "" when the snapshot changes nothing.

    The write happens in a fresh `git worktree`, never in the hub's own
    serving checkout (`handle.root`) -- that checkout is what `kb query`,
    the MCP tools and the web UI read from. Checking `handle.root` itself
    out onto publish/<rid> (the old approach) meant two concurrent publishes
    for different repo-ids shared one working tree: whichever checkout ran
    last decided both what the read side served and what the next publish's
    PR was based on, and a crash could leave the clone stuck off its default
    branch for good (F-D3, F-D4). A worktree per publish means handle.root's
    own checkout is never touched here.

    `store` is a test seam -- None means use the hub's own configured store
    (`assetstore.store_for_hub`), which is None (spec A behavior, unchanged)
    when the hub declares no `asset_store` block.
    """
    from strata_kb import publish as publish_mod

    http = cfg.http or ghapp._default_http
    # deletes is caller-supplied: reject escapes before any lock/clone/write
    # (hashsync._guard would also catch this later, but fail-fast keeps the
    # hub clone untouched and maps to a clean 400).
    deletes = _clean_deletes(deletes)
    with repo_lock(rid):
        handle = _resolve_hub_or_503(cfg.hub_ref)
        # Resolved once, here, rather than inside _publish_in_worktree: the
        # extraction step below (safe_extract) needs to know whether asset
        # diversion is active for THIS publish too, to exempt content-
        # addressed asset paths from the Windows-checkout length bound
        # (round 4, P45) -- they only get exempt when they will actually be
        # diverted out of the published tree, which this same resolved
        # value also governs later. store_for_hub is a plain config read
        # off the already-resolved handle, so resolving it here instead of
        # later changes no behavior.
        active_store = store if store is not None else assetstore.store_for_hub(handle)
        _dest_for_rid(handle.federation_dir, rid)  # validate before any write
        publish_mod._neutralize_excludes(handle.root)
        gitio.neutralize_line_endings(handle.root)
        try:
            # base the PR on the freshest main when possible -- handle.root's
            # origin is credential-stripped (strip_remote_credentials), so the
            # token has to come from the handle, not from the remote's own URL.
            gitio.pull(handle.root, token=handle.token)
        except gitio.GitError:
            logger.warning("hub pull failed -- publishing against cached main")
        # The base is a ref, never the serving tree's current branch: reading
        # current_branch() is what let a concurrent publish's checkout become
        # beta's PR base, and left the tree on publish/alpha for good.
        base = gitio.default_branch(handle.root)
        branch = f"publish/{rid}"
        dest_on_main = gitio.path_exists_at(handle.root, base, f"federation/{rid}")
        # Hybrid worktree rule:
        # - rid already on main (PR merged), or no local branch yet:
        #   reset -B from main. Post-merge, a stale publish/<rid>
        #   would predate the merge -- reusing it makes the next PR
        #   diff show already-merged content against an old merge
        #   base and invites add/add conflicts under
        #   "require branches up to date" protection.
        # - rid NOT on main + branch exists (PR still pending):
        #   reuse the branch, so an unmerged PR accumulates
        #   snapshots and a byte-identical re-publish diffs against
        #   its own prior write and stays a true no-op ("").
        # Accepted trade-off: once the rid exists on main, a resend
        # of identical *pending* (unmerged-PR) content is no longer
        # detected as a no-op -- it re-commits on the fresh branch
        # and converges via create_or_get_pr's 422 reuse path.
        reset = dest_on_main or not gitio.rev_exists(handle.root, branch)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_kb = Path(tmp) / "kb"
            tmp_kb.mkdir()
            safe_extract(
                archive, tmp_kb, cfg.max_tar_bytes,
                assets_will_divert=active_store is not None,
            )
            work = Path(tmp) / "hub"
            with _hub_write_lock:
                gitio.worktree_prune(handle.root)
                gitio.worktree_add(handle.root, work, branch, base, reset=reset)
            try:
                return _publish_in_worktree(
                    cfg, handle, work, rid, branch, base,
                    source_commit, source_repo_full, deletes, tmp_kb,
                    active_store, http,
                )
            finally:
                with _hub_write_lock:
                    gitio.worktree_remove(handle.root, work)


def _restore_worktree_federation(work: Path) -> None:
    """`git checkout -- federation` + `git clean -fd -- federation` on the
    intake worktree, best-effort. Shared by every abort path in
    _publish_in_worktree below that runs after apply_sync has already
    written into `work` but before anything is committed."""
    gitio._run(work, "checkout", "--", "federation")
    gitio._run(work, "clean", "-fd", "--", "federation")


def _publish_in_worktree(
    cfg: IntakeConfig,
    handle: hub_mod.HubHandle,
    work: Path,
    rid: str,
    branch: str,
    base: str,
    source_commit: str,
    source_repo_full: str,
    deletes: list[str],
    tmp_kb: Path,
    active_store,
    http,
) -> str:
    """Apply the extracted snapshot inside `work` (a worktree already checked
    out onto `branch`, rooted at `base`) and open the PR against `base`.

    Split out of intake_publish so the worktree's lifetime (add/remove) stays
    entirely in the caller -- this function never touches handle.root's own
    checkout, only `work`.

    `active_store` is already resolved by the caller (the `store` test seam
    if given, else `assetstore.store_for_hub(handle)`) -- resolved once,
    before `safe_extract` ran, so that call and this one agree on whether
    diversion is active for this publish (round 4, P45's asset-path length
    exemption depends on the two staying in sync).
    """
    from strata_kb import publish as publish_mod
    from strata_kb import pubgate

    dest = work / "federation" / rid
    # upload is incremental -- every file in the archive counts as changed
    local_man = hashsync.build_manifest(tmp_kb)
    # _assets.yaml is a hub-owned record (merged: existing ∪ new −
    # deletes in divert_and_record below) -- a child-supplied
    # _assets.yaml in the uploaded tar must never be synced
    # verbatim, or a malicious/stale upload could overwrite the
    # hub's own bookkeeping of what was diverted to the store.
    local_man.pop(assetstore.RECORD_NAME, None)
    child_record = tmp_kb / assetstore.RECORD_NAME
    if child_record.exists():
        child_record.unlink()

    local_man, skipped = pubgate.split_allowlist(local_man)
    for rel in skipped:
        stray = tmp_kb / rel
        if stray.is_file():
            stray.unlink()
    if skipped:
        # LOW-2: `skipped` names are attacker-controlled (an uploaded tar
        # member name) and may carry a newline/CR/ANSI escape that could
        # forge a fake log line -- escape each one, and cap both the
        # per-name and the joined-list length so one upload cannot flood
        # the log either.
        _LOG_SHOWN = 50
        shown = ", ".join(_escape_for_log(rel) for rel in skipped[:_LOG_SHOWN])
        more = (
            f" (+{len(skipped) - _LOG_SHOWN} more)" if len(skipped) > _LOG_SHOWN else ""
        )
        logger.warning(
            "intake: %d uploaded file(s) are not KB artefacts and were "
            "not published: %s%s", len(skipped), shown, more
        )
    try:
        hashsync.apply_sync(tmp_kb, dest, sorted(local_man), deletes)
    except hashsync.HashSyncError as exc:
        # A partial sync must not leave uncommitted content on the branch --
        # the worktree is removed right after this either way, but a clean
        # federation/ keeps the error path's intent obvious and cheap.
        _restore_worktree_federation(work)
        raise IntakeError(400, str(exc)) from exc
    if active_store is not None:
        # P32: read this rid's committed record BEFORE divert_and_record
        # runs. Intake is explicitly incremental -- only files that
        # actually changed in this upload get diverted -- so the names of
        # everything diverted by an EARLIER publish live only in this
        # record; divert_and_record's own read of it self-heals a failure
        # to empty (needed elsewhere, see its docstring), and on that
        # self-heal its merge degrades to a plain overwrite: "nothing new
        # to divert" would unlink the record outright, and "one new asset
        # uploaded" would replace it with just that one name, dropping
        # every earlier one -- while the store still holds all of them.
        # Pre-checking here means neither ever happens: load_record raises
        # before divert_and_record is ever called, so nothing is derived
        # from the failed read.
        try:
            assetstore.load_record(dest)
        except assetstore.AssetStoreError as exc:
            _restore_worktree_federation(work)
            raise IntakeError(
                500,
                f"this hub's own asset record for '{rid}' could not be read "
                f"({exc}) -- it may name the only surviving copy of some "
                "assets in the object store; refusing to publish over it. "
                "an operator must restore or fix the file on the hub before "
                "this rid can be published again.",
            ) from exc
        try:
            assetstore.divert_and_record(dest, active_store, deletes)
        except assetstore.AssetStoreError as exc:
            # Same restore as the HashSyncError path above: apply_sync
            # already wrote uncommitted changes under federation/ in this
            # worktree, and nothing has been committed yet.
            _restore_worktree_federation(work)
            raise IntakeError(502, f"asset store upload failed: {exc}")
    dirty = gitio._run(work, "status", "--porcelain", "--", "federation").stdout.strip()
    if not dirty:
        return ""  # nothing changed
    meta = federation.FederationMeta(
        repo_id=rid,
        source_url=f"https://github.com/{source_repo_full}",
        source_commit=source_commit,
        published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    models.save_yaml_model(dest / "_meta.yaml", meta)
    federation.write_federation_index(work / "federation")
    gitio.commit_paths(work, f"publish: {rid} @ {source_commit}", ["federation"])
    hub_url = gitio.remote_url(handle.root)
    hub_full = ghapp.repo_full_from_url(hub_url)
    token = ghapp.mint_installation_token(cfg.creds, hub_full, http=http)
    if cfg.push_via_token_url:
        gitio.push_branch_with_token(
            work, f"https://github.com/{hub_full}.git", token, branch
        )
    else:
        gitio.push_branch(work, branch, handle.token)
    create_pr = cfg.pr_hook or ghapp.create_or_get_pr
    return create_pr(
        hub_full,
        token,
        branch,
        title=f"publish: {rid} @ {source_commit}",
        body=publish_mod.PR_BODY_TEMPLATE.format(rid=rid, commit=source_commit),
        base=base,
        http=http,
    )
