"""Every rule that decides whether and how a publish may write to a hub.

Pure by design: no filesystem, no subprocess, no network. Callers read the
registry, the remote URL and the existing entry names, then pass them in.
That keeps each of these -- they are the security rules -- a table test
rather than something only a real hub can exercise.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Literal

from center_kb.errors import KbError

REPO_ID_MAX = 64
REPO_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# Round 3 (MEDIUM-2, review-waveH-fix2-verdict.md): CONIN$/CONOUT$ (the
# console-handle names git's own is_valid_win32_path also reserves), COM0/
# LPT0 (Win32 numbers ports from 0, not just 1-9) and the superscript-digit
# aliases COM¹²³/LPT¹²³ (NTFS treats them as
# COM1-3/LPT1-3) used to live in a second, LOCAL frozenset in intake.py,
# unioned with this one at its one call site because intake.py could edit
# this file but pubgate.py belonged to another implementer that round. The
# result was measured: normalize_repo_id("LPT0") accepted it as a repo-id
# while intake.py's member-name rule refused it as a tar member -- and a
# registry entry mapping a publisher to repo-id "LPT0" reached the hub tree
# through _dest_for_rid instead, breaking `git clone` for every tenant on
# the hub, not just that one. One set, used by both the repo-id rule below
# and intake.py's member-name rule, is what keeps that from recurring.
WIN32_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(0, 10)}
    | {f"LPT{i}" for i in range(0, 10)}
    | {f"COM{d}" for d in "¹²³"}
    | {f"LPT{d}" for d in "¹²³"}
)


# Round 4 (LOW, P30): the re-review's form question was "shipped as one
# device SET, not one predicate" -- close the form, or defend the set.
# Kept as a set, deliberately: this is a finite, externally-defined
# vocabulary (Win32's reserved DOS device names, including the NTFS
# superscript-digit aliases, which are not expressible as a `\d`-style
# digit pattern and would have to be spelled out character-by-character
# in a "predicate" too), not a computable rule family a regex would
# generalize better than a set already does -- and the set is proven
# correct (0 drift over 302,621 fuzz candidates). What genuinely was
# duplicated -- and is the real drift risk P30 is naming -- is the CHECK:
# `normalize_repo_id` below and intake.py's member-name shape rule each
# independently reimplemented "extract the stem, strip a trailing space,
# upper-case, test membership" against this one shared set, which is
# exactly the kind of two-independent-copies gap WIN32_DEVICES itself was
# unified to close for the SET in round 3 (MEDIUM-2's drift: LPT0 accepted
# as a repo-id, refused as a tar member). `is_reserved_device_name` below
# closes it for the check too -- one predicate, both call sites -- and
# "adding a platform" now means adding both its names to this set AND, if
# its stem-extraction rule ever differs from Windows' (trailing-space
# stripping), one clause to that one function, not auditing two
# independent copies of it.
def is_reserved_device_name(stem: str) -> bool:
    """True when `stem` (the part of a name before its first '.') names a
    reserved Windows device on any consumer platform, after stripping a
    trailing space and case-folding -- Windows silently strips a trailing
    space between a device name's stem and its extension ('NUL .txt' is
    still the NUL device), so the strip must happen before the compare,
    not just at the whole-component level."""
    return stem.rstrip(" ").upper() in WIN32_DEVICES


class GateError(KbError):
    """A publish was refused. The message is user-facing; callers exit 1."""


def normalize_repo_id(rid: str, existing: Iterable[str] = ()) -> str:
    """The repo-id, or GateError naming why it cannot become a hub directory.

    `existing` is the entry directory names already under federation/ on the
    hub. The byte-wise regex alone is not enough: Path.resolve() normalises
    a trailing dot and a case difference textually, so the escape guard in
    publish._snapshot passes and Win32 then folds the new directory onto a
    sibling entry -- overwriting it, and pushing an aggregate index that
    disagrees with the committed tree.
    """
    if not REPO_ID_RE.fullmatch(rid) or rid in {".", ".."}:
        raise GateError(
            f"repo-id '{rid}' is invalid -- only letters/digits/._- allowed, "
            "no path separators"
        )
    if len(rid) > REPO_ID_MAX:
        raise GateError(
            f"repo-id '{rid[:24]}...' is {len(rid)} characters -- the limit is "
            f"{REPO_ID_MAX}"
        )
    if rid.endswith("."):
        raise GateError(
            f"repo-id '{rid}' ends with a dot -- Windows strips it silently, "
            "which would fold this entry onto a sibling"
        )
    stem = rid.split(".", 1)[0]
    if is_reserved_device_name(stem):
        raise GateError(
            f"repo-id '{rid}' uses the reserved Windows device name '{stem}' -- "
            "pick another id"
        )
    for name in existing:
        if name != rid and name.casefold() == rid.casefold():
            raise GateError(
                f"repo-id '{rid}' collides with the existing entry '{name}' on a "
                "case-insensitive filesystem -- publishing would overwrite it"
            )
    return rid


# scp-style remote: [user@]host:path/to/repo.git
_SCP_RE = re.compile(r"^[^/@]+@(?P<host>[^:/]+):(?P<path>.+)$")


def owner_repo_from_remote(url: str) -> str | None:
    """'owner/repo' (or 'group/sub/repo') from a git remote URL.

    None for a local path, an empty remote, or a URL with no repo path --
    which is the caller's signal that this publisher cannot be identified.
    Embedded credentials are dropped: the URL shape the CI templates use is
    https://x-access-token:<token>@github.com/org/repo.git.
    """
    text = (url or "").strip()
    if not text:
        return None
    m = _SCP_RE.match(text)
    if m:
        path = m.group("path")
    elif "://" in text:
        rest = text.split("://", 1)[1]
        rest = rest.split("@", 1)[-1]  # drop user:token@
        if "/" not in rest:
            return None
        path = rest.split("/", 1)[1]  # drop host[:port]
    else:
        return None
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    return "/".join(parts)


def resolve_identity(
    registry_map: dict[str, str],
    remote_url: str,
    requested_rid: str | None,
    hub_label: str,
) -> str:
    """The repo-id a governed hub accepts from this publisher.

    `registry_map` is {owner/repo: repo_id}, flattened by the caller from
    federation/registry.yaml, and is never empty -- an ungoverned hub does
    not reach here.

    This is a MISTAKE guard, not an authentication boundary: the remote URL
    is self-asserted by the publisher. The boundary is the review route a
    governed hub forces (see decide_mode) plus branch protection on the hub.
    """
    owner_repo = owner_repo_from_remote(remote_url)
    if owner_repo is None:
        raise GateError(
            f"hub '{hub_label}' is governed by federation/registry.yaml but this "
            "repo has no git remote to identify it -- add a git remote pointing "
            "at the repo registered in federation/registry.yaml, or ask the hub "
            "owner to remove the registry"
        )
    lookup = {key.casefold(): (key, value) for key, value in registry_map.items()}
    hit = lookup.get(owner_repo.casefold())
    if hit is None:
        raise GateError(
            f"repo '{owner_repo}' is not registered on hub '{hub_label}' -- open a "
            f"PR on the hub adding `{owner_repo}: <repo-id>` under `repos:` in "
            "federation/registry.yaml"
        )
    registered_repo, mapped = hit
    if requested_rid and requested_rid != mapped:
        raise GateError(
            f"registry maps '{registered_repo.casefold()}' to repo-id '{mapped}', "
            f"not '{requested_rid}' -- drop --repo-id or the repo_id: entry in "
            ".kb/config.yaml, or ask the hub owner to change the registry"
        )
    return mapped


Mode = Literal["pr", "direct"]

_NO_PR_MESSAGE = (
    "hub '{hub}' has a git remote but `gh` cannot open a pull request on it "
    "(is `gh` installed and authenticated for that host?) -- either fix that "
    "and re-run with --pr, or re-run with --direct if you accept publishing "
    "without review"
)

_NO_PR_MESSAGE_GOVERNED = (
    "hub '{hub}' is governed by federation/registry.yaml and `gh` cannot open "
    "a pull request on it -- set `gh` up for that host (`GH_HOST` for GitHub "
    "Enterprise) until `gh repo view` succeeds, then re-run with --pr; or, "
    "from the child repo's own GitHub Actions job, run `kb ci-publish`, which "
    "needs GitHub on both the publisher and the hub -- if this hub is not on "
    "GitHub, neither route is available and the only way forward is asking "
    "the hub owner to remove federation/registry.yaml"
)


def decide_mode(
    explicit: str,
    has_remote: bool,
    can_pr: bool,
    governed: bool,
    hub_label: str,
) -> Mode:
    """"auto" | "pr" | "direct" -> the mode to run, or GateError.

    Replaces the `"github" in remote_url` substring test, which routed every
    GitLab/Gitea/Bitbucket/self-hosted hub -- and any GitHub hub on a machine
    without `gh` -- to a silent direct push onto the hub's default branch.
    `can_pr` is decided by asking `gh` (see ghio.can_open_pr), not by parsing
    the URL: a GitHub Enterprise hub reached through GH_HOST answers yes, and
    a hub at .../github-mirror-hub.git answers no.
    """
    if explicit == "direct":
        if governed and has_remote:
            raise GateError(
                f"hub '{hub_label}' is governed by federation/registry.yaml -- it "
                "takes contributions by PR (`kb publish --pr`, which needs `gh` "
                "able to open one on this host) or from the child repo's GitHub "
                "Actions job (`kb ci-publish`, which needs GitHub on both the "
                "publisher and the hub), not by direct push -- if neither is "
                "available for this hub, ask the hub owner to remove "
                "federation/registry.yaml"
            )
        return "direct"
    if explicit == "pr":
        if not has_remote:
            raise GateError(
                f"hub '{hub_label}' has no git remote -- there is nothing to open "
                "a PR against; publish without --pr to commit locally"
            )
        if not can_pr:
            message = _NO_PR_MESSAGE_GOVERNED if governed else _NO_PR_MESSAGE
            raise GateError(message.format(hub=hub_label))
        return "pr"
    if not has_remote:
        return "direct"
    if can_pr:
        return "pr"
    message = _NO_PR_MESSAGE_GOVERNED if governed else _NO_PR_MESSAGE
    raise GateError(message.format(hub=hub_label))


_KEEP_BASENAMES = frozenset({"index.yaml", "_meta.yaml", "_manifest.yaml"})

# Mirrors assetstore.RECORD_NAME's value. Not imported from assetstore --
# this module is pure (stdlib only, no filesystem/subprocess/network) and
# assetstore is not; the two are kept in sync by tests/test_pubgate.py.
_ASSET_RECORD_BASENAME = "_assets.yaml"


def is_kb_artifact(relpath: str, *, keep_records: bool = False) -> bool:
    """Is this posix relpath something a publish is allowed to mirror?

    The rule is depth-independent on purpose, so one definition serves the
    .kb/ source, the federation/ source of a hub-to-hub publish (nested
    tiers included) and the extracted tar of an intake upload.

    _assets.yaml is, by default, NOT an artefact: for a child's .kb/ (and
    an intake upload) it is hub-owned bookkeeping written by
    assetstore.divert_and_record, never copied in from that source.

    keep_records=True flips that for one caller only: publish's
    hub-to-hub path (_snapshot_federation), whose source is itself a
    hub's federation/ tree. There, `_assets.yaml` is hub-WRITTEN content
    being mirrored upward, not a source artefact being smuggled in --
    filtering it out anyway made the record absent on the source side of
    the diff every publish, while the destination (built with no filter)
    still had it, so diff_manifests classified it as deleted and the next
    hub-to-hub publish committed that deletion.

    Refuses an absolute path or a path containing a backslash before doing
    anything else, so this function guarantees containment, not just naming.
    """
    if PurePosixPath(relpath).is_absolute() or "\\" in relpath:
        return False
    parts = PurePosixPath(relpath).parts
    if not parts or any(p.startswith(".") for p in parts):
        return False
    name = parts[-1]
    if keep_records and name == _ASSET_RECORD_BASENAME:
        return True
    if name in _KEEP_BASENAMES or name.endswith(".md"):
        return True
    return len(parts) >= 2 and parts[-2] == "assets"


def split_allowlist(
    manifest: dict[str, str], *, keep_records: bool = False
) -> tuple[dict[str, str], list[str]]:
    """(kept, skipped) -- `skipped` is sorted, for the caller's [warn] line.

    keep_records: see is_kb_artifact -- pass True only from the hub-to-hub
    publish path, so `_assets.yaml` is kept rather than reported skipped.
    """
    kept = {
        rel: sha
        for rel, sha in manifest.items()
        if is_kb_artifact(rel, keep_records=keep_records)
    }
    skipped = sorted(set(manifest) - set(kept))
    return kept, skipped
