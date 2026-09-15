from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import ValidationError

from center_kb import gitio, kbcontext, models
from center_kb.mdutils import slice_section
from center_kb.resolve import ResolvedRef, resolve_refs

if TYPE_CHECKING:
    from center_kb.hub import HubHandle


@dataclass
class Issue:
    level: Literal["error", "warning"]
    message: str
    # A stable machine tag for the checks a caller needs to tell apart —
    # today only "stale-ref", so `kb ticket lint --fail-on-stale` can
    # report exit code 2 ("only staleness failed") the way `kb resolve`
    # does. Defaulted, so every existing construction is unchanged.
    code: str = ""


def _flatten(exc: Exception) -> str:
    """Collapse a (possibly multi-line) exception message to one scannable line."""
    return " ".join(str(exc).split())


def _check_doc(kb_dir: Path, doc_id: str) -> list[Issue]:
    doc_dir = kb_dir / doc_id
    try:
        manifest = models.load_yaml_model(doc_dir / "_manifest.yaml", models.Manifest)
    except (yaml.YAMLError, ValidationError) as exc:
        return [
            Issue(
                "error",
                f"{doc_id}: _manifest.yaml is corrupt — fix or regenerate it: "
                f"{_flatten(exc)}",
            )
        ]

    issues: list[Issue] = []
    pending = 0
    referenced: set[str] = {"_manifest.yaml"}
    for sec in manifest.sections:
        if sec.status == "pending":
            pending += 1
        for suffix, layer in ((".md", "L2"), (".raw.md", "L3")):
            name = f"{sec.file}{suffix}"
            referenced.add(name)
            path = doc_dir / name
            if not path.exists():
                issues.append(
                    Issue("error", f"{doc_id} §{sec.id}: missing {layer} file '{name}'")
                )
            elif slice_section(path.read_text(encoding="utf-8"), sec.id) is None:
                issues.append(
                    Issue(
                        "error",
                        f"{doc_id} §{sec.id}: could not slice section in '{name}'",
                    )
                )
    if pending:
        issues.append(Issue("warning", f"{doc_id}: {pending} section pending"))
    for f in sorted(doc_dir.glob("*.md")):
        if f.name not in referenced:
            issues.append(
                Issue("warning", f"{doc_id}: orphan file '{f.name}' not in manifest")
            )
    return issues


def check_kb(kb_dir: Path) -> list[Issue]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return [Issue("error", f"no index.yaml in '{kb_dir}'")]
    try:
        index = models.load_yaml_model(index_path, models.KBIndex)
    except (yaml.YAMLError, ValidationError) as exc:
        return [
            Issue(
                "error",
                f"index.yaml in '{kb_dir}' is corrupt — fix or regenerate it: "
                f"{_flatten(exc)}",
            )
        ]
    index_ids = {d.id for d in index.docs}

    issues: list[Issue] = []
    for entry in index.docs:
        if not (kb_dir / entry.id / "_manifest.yaml").exists():
            issues.append(
                Issue(
                    "error",
                    f"doc '{entry.id}' is in the index but missing _manifest.yaml",
                )
            )
            continue
        issues += _check_doc(kb_dir, entry.id)

    for child in sorted(p for p in kb_dir.iterdir() if p.is_dir()):
        if (child / "_manifest.yaml").exists() and child.name not in index_ids:
            issues.append(
                Issue(
                    "error",
                    f"doc '{child.name}' has a manifest but is not in index.yaml",
                )
            )
    return issues


def check_kind(kb_dir: Path) -> list[Issue]:
    """Warn when the repo's hub|child kind is not recorded in config.yaml."""
    from center_kb.config import load_config

    try:
        kind = load_config(kb_dir).kind
    except (yaml.YAMLError, ValidationError) as exc:
        return [Issue("error", f"config.yaml is invalid: {_flatten(exc)}")]
    if not kind:
        return [
            Issue(
                "warning",
                "repo kind is not recorded in .kb/config.yaml — run `kb init` "
                "to record kind: hub|child",
            )
        ]
    return []


ASSET_SIZE_WARN_BYTES = 100 * 1024 * 1024


def check_asset_store(kb_dir: Path, handle, store=None) -> list[Issue]:
    """Storage health per asset_store mode; [] when the block is absent."""
    from center_kb import assetstore
    from center_kb.config import load_config

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
    try:
        store.exists(assetstore.PROBE_NAME)
    except assetstore.AssetStoreError as exc:
        return [Issue("error", f"asset store unreachable: {_flatten(exc)}")]
    return []


def check_context(
    text: str,
    hub: "HubHandle",
    *,
    stale_level: Literal["error", "warning"] = "warning",
) -> tuple[list[Issue], list[ResolvedRef]]:
    try:
        ctx = kbcontext.parse(text)
    except kbcontext.KBContextError as exc:
        return [Issue("error", str(exc))], []
    try:
        results = resolve_refs(hub, ctx)
    except gitio.GitError as exc:
        return [Issue("error", str(exc))], []

    issues: list[Issue] = []
    for r in results:
        if r.status == "broken":
            issues.append(Issue("error", f"{r.ref}: {r.reason}"))
        elif r.status == "stale":
            # Unconditional — applies whether `stale_level` promoted this to
            # an error or left it a warning, so both phrasings name the same
            # fix. Mirrors `render_resolved`'s own remedy (resolve.py), which
            # names the same `kb diff` command; re-pinning is offered first
            # since it is the fix the BA usually wants once amendment is
            # confirmed, not just a way to inspect it.
            remedy = (
                "re-pin with the current hub commit, or run `kb diff "
                f"{r.ref.doc_id} --against {r.pinned_rev}` to review the "
                "amendment first"
            )
            issues.append(
                Issue(stale_level, f"{r.ref}: {r.reason} — {remedy}", "stale-ref")
            )
    return issues, results


def _kb_tree_digest(root: Path, synthesized: dict[str, str] | None = None) -> str:
    """Deterministic digest of a .kb tree, over exactly what a publish mirrors.

    `root` is the root the two sides are compared AT -- the local `.kb/`
    directory on one side, the hub's `federation/<rid>/` entry on the other.
    That is the same pair of roots `publish._snapshot` builds its two
    manifests against, which is what makes the relative paths below
    comparable, and what makes handing them to `is_kb_artifact` correct
    (Ruling P40: the path must be relative to the entry whose artefacts are
    being judged, never to some other root).

    Two exclusions, for two different reasons:

    * `_meta.yaml` is snapshot-only -- written by `_snapshot` on the hub
      side, never present locally -- so it would differ on every healthy
      pair.
    * Ruling P54: everything `pubgate.is_kb_artifact()` refuses. `_snapshot`
      filters the local manifest through exactly that predicate before
      diffing, so a file it refuses can never reach the hub -- `config.yaml`
      above all, which this batch's own credential-leak fix stopped
      publishing, and which `kb init` writes into every real KB. Hashing it
      here made the two sides permanently unequal and produced a warning no
      operator could ever clear, on advice ("run `kb publish`") naming the
      command they had just run. Calling the predicate rather than keeping a
      second hand-maintained exclusion list beside it is the point: the next
      change to what publish strips cannot desynchronise the two again.
      (`_assets.yaml` falls out of the same call -- it is hub-owned
      bookkeeping `divert_and_record` writes, and `_snapshot` excludes it
      from the destination manifest by name for that reason.)

    A file on the hub that a publish would never have written is NOT drift
    this check should report -- the stray sweep in `check_hub` above reports
    it, with the "delete them on the hub, and rotate any credential they
    contain" advice that shape actually needs.

    Item 7's second, milder finding (wave L1 brief): that advice is stale
    for a stray inside a recognized entry -- a republish from that entry's
    own source repo already deletes it (the same diff/apply_sync mechanism
    this digest mirrors), so "kb doctor: OK" beside that warning does not
    mean the next publish is a no-op. The slim-layout stray sweep's
    message was corrected (it says so and names the remedy: republish
    upgrades the entry and clears the stray automatically, rotate the
    credential regardless). The leaf-entry stray sweep's message was
    measured to be exactly `tests-gate/conftest.py`'s
    LEGACY_CONFIG_MIRROR_WARNING golden-fixture string -- a real, currently
    running regression assertion this wave does not own and must not touch
    -- so it is left with the stale wording rather than reached into
    forbidden territory; the finding is real and reported, not silently
    dropped.

    `synthesized` (item 7, wave L1 brief -- ruling P54's other half):
    caller-supplied {relpath: sha256hex}, merged in on top of the files
    actually found on disk under `root`, exactly the way
    publish._snapshot's `dest_man.update(assetstore.synthesized_asset_
    entries(dest))` merges into its own destination manifest before
    diffing. Without this, an asset diverted to an object store -- its
    real bytes gone from `federation/<rid>/`, only `_assets.yaml` naming
    it -- is simply absent from this function's walk of the hub-side
    root, so the hub-side digest permanently differs from the local one
    (which still holds the real bytes on disk) on any hub with an asset
    store: `_snapshot` and this check agreed on the *predicate* for what
    counts (`is_kb_artifact`) but not on *what a diverted asset's
    physical absence means*, so the earlier P54 fix left this half open
    and reproduced P54's own symptom -- a warning that never clears, on
    advice naming the command the operator just ran.

    This is WHY the digest is now built as a {relpath: sha256-of-content}
    manifest (hashed once more, aggregated, at the end) rather than a
    single running hash over raw bytes read in file order: `synthesized`
    only ever knows a diverted asset's sha (asset_sha, read from its
    content-addressed filename -- spec A guarantees filename sha ==
    sha256(bytes), so this is exact, not an approximation), never its
    raw bytes (they are gone from this tree by construction), so there
    is no way to fold it into a single ongoing byte-stream hash the way
    the previous version did. A manifest entry is comparable on equal
    footing whether its sha256 came from hashing real bytes or from
    reading a content-addressed filename -- hashsync.build_manifest /
    diff_manifests already rely on exactly that equivalence for
    `_snapshot`'s own diff, so this mirrors it rather than inventing a
    second notion of "what should be there". `synthesized` is caller-
    supplied, not computed here, because it must come from the SAME
    store `_snapshot` itself would resolve (assetstore.store_for_hub)
    and only ever applies to the hub-side call -- the local `.kb/` side
    has no asset store of its own to synthesize against.
    """
    import hashlib

    from center_kb import pubgate

    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "_meta.yaml":
            continue
        rel = path.relative_to(root).as_posix()
        if not pubgate.is_kb_artifact(rel):
            continue
        manifest[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    if synthesized:
        manifest.update(synthesized)
    h = hashlib.sha256()
    for rel in sorted(manifest):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(manifest[rel].encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def check_hub(
    kb_dir: Path,
    handle: "HubHandle | None",
    repo_id: str | None = None,
    *,
    warn_untracked_index: bool = False,
) -> tuple[list[Issue], bool]:
    """Hub-first health. Returns (issues, hub_stale).

    ``warn_untracked_index`` gates the F-C17 ``.kb-work/`` warning: only the
    hub maintainer's own checkout can act on "add it to the hub's
    .gitignore", so child/dev/ba callers (who reach a hub or its cache clone
    read-only) must leave it off.
    """
    from center_kb.federation import build_federation_index, load_federation

    if handle is None:
        return (
            [
                Issue(
                    "error",
                    "could not reach hub — the federation is the only read "
                    "source; check the network or the hub path",
                )
            ],
            False,
        )
    issues: list[Issue] = []
    hub_stale = False
    if handle.stale:
        age = f"~{handle.age_seconds:.0f}s" if handle.age_seconds else "unknown"
        issues.append(
            Issue("warning", f"hub cache is stale (pull failed, age {age})")
        )
        hub_stale = True

    # The URL itself is never put in the message -- gitio.redact_url exists
    # for that, and here the config key alone is enough to find it. --local
    # scopes this to handle.root's own .git/config: without it, a
    # remote.*.url defined in the operator's global/system gitconfig is
    # misreported as living in this clone's own config (M3).
    for line in gitio._run(
        handle.root, "config", "--local", "--get-regexp", r"^remote\..*\.url$"
    ).stdout.splitlines():
        name, _, url = line.partition(" ")
        if gitio.split_credentials(url)[1] is not None:
            issues.append(
                Issue(
                    "warning",
                    f"the clone at {handle.root} still stores a credential in "
                    f"its own .git/config ({name}) -- rotate that token, then "
                    "either delete the managed cache so it is re-cloned "
                    "without one, or run `git remote set-url` yourself if "
                    "this is a direct hub checkout",
                )
            )

    # GIT_CONFIG_COUNT/KEY/VALUE (how credential_env hands git a token
    # without putting it in argv) needs git >= 2.31 -- on an older git the
    # env is silently ignored and the operator gets git's own opaque auth
    # error instead of a message naming the way forward (M4). Only worth
    # checking when this hub ref actually carries a credential.
    if handle.token is not None:
        proc = gitio._run(handle.root, "--version")
        match = re.search(r"(\d+)\.(\d+)", proc.stdout)
        if match and (int(match.group(1)), int(match.group(2))) < (2, 31):
            issues.append(
                Issue(
                    "warning",
                    f"git {match.group(0)} is older than 2.31 -- credential "
                    "injection (GIT_CONFIG_COUNT) is silently ignored on this "
                    "version, so pushes to this token-bearing hub will fail "
                    "with git's own authentication error; upgrade git",
                )
            )

    if warn_untracked_index:
        work = handle.root / ".kb-work"
        if work.is_dir():
            ignore = handle.root / ".gitignore"
            try:
                ignored = ".kb-work" in ignore.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # A `.gitignore` this tool doesn't own — missing, unreadable,
                # or written by something that isn't UTF-8 (e.g. PowerShell
                # 5.1's `echo x > .gitignore`, which is UTF-16LE) — counts as
                # not-ignored so the warning fires instead of `kb doctor`
                # crashing.
                ignored = False
            if not ignored:
                issues.append(
                    Issue(
                        "warning",
                        "the search index at .kb-work/ is neither ignored "
                        "nor meant to be committed — add '.kb-work/' to the "
                        "hub's .gitignore before someone runs `git add -A` "
                        "(F-C17)",
                    )
                )

    fed = handle.federation_dir
    if fed.is_dir():
        from center_kb import assetstore, pubgate
        from center_kb.federation import (
            FED_TOP_EXCLUDE,
            iter_entry_dirs,
            iter_namespace_dirs,
            scan_broken_entries,
        )

        # Important 3 (Wave G fix round 2 re-review), Ruling P36: a fully
        # valid leaf entry nested beneath a broken one (exactly one of
        # _meta.yaml/index.yaml) is reached by neither iter_entry_dirs
        # (stops at the broken ancestor) nor iter_namespace_dirs
        # (`continue`s at a leaf without sweeping it) -- scan_broken_entries
        # is an additive walk that finds exactly those leaves, plus every
        # broken entry directory itself, without changing what
        # iter_entry_dirs yields (load_federation still sees exactly that).
        broken_entries, nested_leaves = scan_broken_entries(fed)

        def _enclosing_entry(ns_rel: str) -> Path | None:
            """The innermost broken-entry root at or above `ns_rel`, or None.

            The only `broken_rel`s that match a given `ns_rel` are its own
            ancestors, which are strict path prefixes of one another, so
            string length is a correct innermost-wins key. `iter_namespace_
            dirs` `continue`s at a valid leaf and at a slim entry, so an
            `ns_dir` can never sit inside either -- "nearest enclosing
            BROKEN entry" is therefore equivalent to "nearest enclosing
            entry" for both loops below.
            """
            found = None
            found_len = -1
            for broken_rel, broken_dir in broken_entries:
                if ns_rel == broken_rel or ns_rel.startswith(f"{broken_rel}/"):
                    if len(broken_rel) > found_len:
                        found = broken_dir
                        found_len = len(broken_rel)
            return found
        for broken_rel, _broken_dir in broken_entries:
            issues.append(
                Issue(
                    "warning",
                    f"federation/{broken_rel} is missing _meta.yaml or "
                    "index.yaml -- treated as a broken entry (an interrupted "
                    "publish leaves exactly this shape); its own subtree is "
                    "still scanned for strays, but the entry itself will not "
                    "appear in federation/index.yaml until it is republished "
                    "from that repo",
                )
            )

        # nested_leaves are leaves scan_broken_entries found only by
        # recursing past a broken ancestor -- iter_entry_dirs never yields
        # them (see above), so appending here sweeps each leaf exactly once.
        for entry_rel, entry_dir in [*iter_entry_dirs(fed), *nested_leaves]:
            strays = sorted(
                p.relative_to(entry_dir).as_posix()
                for p in entry_dir.rglob("*")
                if p.is_file()
                and p.name != assetstore.RECORD_NAME
                and not pubgate.is_kb_artifact(p.relative_to(entry_dir).as_posix())
            )
            if strays:
                issues.append(
                    Issue(
                        "warning",
                        f"federation/{entry_rel} holds file(s) a publish would "
                        f"never write: {', '.join(strays)} -- an older version "
                        "mirrored them; delete them on the hub, and rotate any "
                        "credential they contain",
                    )
                )

        # N-4 (Wave G fix round 4, review-waveG-fix3-verdict.md): every one
        # of the three federation.py walkers `continue`s past a directory
        # using the old slim layout (Phase 3, a 'manifests/' subdirectory)
        # -- so nothing above ever looked at what sits directly beside a
        # slim entry's manifests/, which is exactly the shape a leaked
        # credential takes there, at ANY depth (a slim entry nested inside
        # a broken one included -- this is what makes the broken-entry
        # message above's "its own subtree is still scanned for strays"
        # true for that shape instead of false). Reuses
        # iter_namespace_dirs's own walk as the traversal frontier -- it
        # already visits every namespace directory at every depth,
        # federation/ itself included (ns_rel "") -- instead of a second
        # recursive walk: checking each ns_dir's OWN direct children for
        # the slim-layout shape catches one wherever it sits, replacing
        # the old federation/-only (depth-1) check this loop supersedes.
        # manifests/'s own contents are left alone on purpose -- that is
        # legitimate old-format payload a slim publish DID write, not
        # something "a publish would never write"; is_kb_artifact has no
        # opinion on that format and would false-positive on it.
        for ns_rel, ns_dir in iter_namespace_dirs(fed):
            for slim_dir in sorted(c for c in ns_dir.iterdir() if c.is_dir()):
                if not (slim_dir / "manifests").is_dir():
                    continue
                # Minor 1 (round-4 re-review), Ruling P39: holding
                # manifests/ is a structural heuristic, and a directory that
                # merely LOOKS like an entry to one is not an entry. A
                # directory named `assets` INSIDE an entry is an asset
                # directory by is_kb_artifact's own rule -- `parts[-2] ==
                # "assets"` makes its direct children artefacts -- so it can
                # never be an entry root, and calling it one cost twice: the
                # slim-layout Issue was wrong, and resolving the stray sweep
                # against it stripped its own contents of exactly the asset
                # exemption P40 restored (a legitimate <entry>/<doc>/assets/
                # pic.png reported as a leaked stray). With NO entry above
                # it there is no asset directory to confuse it with -- P40's
                # "assets only exist inside an entry" -- and `assets` is a
                # legal repo-id, so federation/assets stays reportable.
                if slim_dir.name == "assets" and _enclosing_entry(ns_rel) is not None:
                    continue
                slim_rel = f"{ns_rel}/{slim_dir.name}" if ns_rel else slim_dir.name
                issues.append(
                    Issue(
                        "warning",
                        f"federation/{slim_rel} uses the old slim layout — "
                        "run `kb publish` from that repo to upgrade it",
                    )
                )
                slim_strays = sorted(
                    p.relative_to(slim_dir).as_posix()
                    for p in slim_dir.rglob("*")
                    if p.is_file()
                    and p.name != assetstore.RECORD_NAME
                    and p.relative_to(slim_dir).parts[0] != "manifests"
                    and not pubgate.is_kb_artifact(
                        p.relative_to(slim_dir).as_posix()
                    )
                )
                if slim_strays:
                    issues.append(
                        Issue(
                            "warning",
                            f"federation/{slim_rel} holds file(s) a publish "
                            f"would never write: {', '.join(slim_strays)} -- "
                            "republishing from that repo (see the slim-layout "
                            "warning above) removes them automatically, but "
                            "rotate any credential they contain now",
                        )
                    )

        # F-D9 finding 5: iter_entry_dirs only ever yields leaves, so nothing
        # above looks at a file dropped directly under federation/ itself or
        # under an intermediate namespace directory (e.g. federation/<mid>/
        # after a hub-to-hub publish) -- exactly where a mid hub's own
        # top-level federation/ files land under _snapshot_federation, so
        # the credential-leak case this warning exists for was the one case
        # it missed. Same predicate as the leaf sweep above, plus
        # FED_TOP_EXCLUDE (a hub's own index.yaml/registry.yaml/.gitkeep) --
        # M2: legitimate only directly under federation/ itself (ns_rel ==
        # ""), so it must not be exempted at a nested namespace directory
        # too, where those same names are just as suspicious as any other
        # stray.
        #
        # P40 (Wave G fix round 4, superseding Ruling P35's ambiguous
        # "entry-relative"): the path handed to is_kb_artifact must be
        # relative to THE ENTRY WHOSE ARTIFACTS ARE BEING JUDGED -- and if
        # there is no entry above the file, no asset exemption applies at
        # all, because assets only exist inside an entry. ns_dir here may
        # be a genuine namespace directory with no entry above it at all
        # (federation/ itself, or a plain grouping directory -- including
        # one that happens to be named "assets", or to start with a dot),
        # or it may BE a broken entry's own root, or a directory NESTED
        # inside one (e.g. <broken-entry>/doc-a/assets/). The round-3 fix
        # passed the fed-relative path unconditionally, which put the
        # wrong thing in is_kb_artifact's parts[-2] slot for the first
        # case -- the namespace directory's OWN basename, not a real
        # "assets" parent -- silently exempting a stray sitting directly
        # inside any non-leaf directory named "assets" (N-1), and put a
        # dot-prefixed namespace segment where is_kb_artifact's dotfile
        # check looks, wrongly rejecting a legitimate asset beneath one
        # (N-7). Find the nearest enclosing broken-entry root, if any (the
        # innermost match, for a broken entry nested inside another), and
        # resolve against THAT; with none, resolve against nothing -- pass
        # the bare basename, which can never satisfy is_kb_artifact's
        # `len(parts) >= 2` asset rule, so no exemption applies, exactly as
        # P40 requires.
        for ns_rel, ns_dir in iter_namespace_dirs(fed):
            top_exclude = FED_TOP_EXCLUDE if not ns_rel else ()
            entry_root = _enclosing_entry(ns_rel)
            ns_strays = sorted(
                p.name
                for p in ns_dir.iterdir()
                if p.is_file()
                and p.name != assetstore.RECORD_NAME
                and p.name not in top_exclude
                and not pubgate.is_kb_artifact(
                    p.relative_to(entry_root).as_posix() if entry_root else p.name
                )
            )
            if ns_strays:
                label = f"federation/{ns_rel}" if ns_rel else "federation/"
                issues.append(
                    Issue(
                        "warning",
                        f"{label} holds file(s) a publish would never write: "
                        f"{', '.join(ns_strays)} -- delete them on the hub, "
                        "and rotate any credential they contain",
                    )
                )

    index_path = fed / "index.yaml"
    if not index_path.exists():
        issues.append(
            Issue("error", "federation/index.yaml is missing — run `kb reindex`")
        )
    else:
        try:
            stored = models.load_yaml_model(index_path, models.FederationIndex)
        except (yaml.YAMLError, ValidationError) as exc:
            issues.append(
                Issue(
                    "error",
                    f"federation/index.yaml is corrupt — run `kb reindex`: "
                    f"{_flatten(exc)}",
                )
            )
        else:
            if stored != build_federation_index(fed):
                issues.append(
                    Issue(
                        "error",
                        "federation/index.yaml is out of sync with the snapshots — "
                        "run `kb reindex`",
                    )
                )

    if repo_id:
        entry = fed / repo_id
        if not entry.is_dir():
            issues.append(
                Issue(
                    "warning",
                    f"repo '{repo_id}' has not published to the hub yet — run `kb publish`",
                )
            )
        else:
            from center_kb import assetstore

            # Item 7 (wave L1 brief), ruling P54's other half: the hub-side
            # digest must see a diverted asset the same way publish._snapshot
            # does -- assetstore.store_for_hub reads the HUB's own config
            # (handle.kb_dir), the exact source _snapshot itself resolves
            # from when no store override is passed. A corrupt/unreachable
            # config is reported separately by check_asset_store; here it
            # just means "no store known" -- no synthesis, same as before.
            synthesized: dict[str, str] = {}
            try:
                active_store = assetstore.store_for_hub(handle)
            except (yaml.YAMLError, ValidationError, assetstore.AssetStoreError):
                active_store = None
            if active_store is not None:
                synthesized = assetstore.synthesized_asset_entries(entry)
            if _kb_tree_digest(kb_dir.resolve()) != _kb_tree_digest(entry, synthesized):
                issues.append(
                    Issue(
                        "warning",
                        f"local .kb differs from the published snapshot "
                        f"federation/{repo_id} — run `kb publish`",
                    )
                )

    counts = Counter(
        d.id for r in load_federation(fed) for d in r.index.docs
    )
    for doc_id, n in sorted(counts.items()):
        if n > 1:
            issues.append(
                Issue(
                    "warning",
                    f"doc-id '{doc_id}' appears in {n} federation repos — "
                    "refs must be repo-qualified (repo:doc)",
                )
            )
    return issues, hub_stale


_ENTRY_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_FED_TOP_SKIP = {"index.yaml", "registry.yaml", ".gitkeep"}


def _fed_tree_digest(root: Path) -> str:
    """Digest deterministic của một cây federation — bỏ file tầng đỉnh mà
    publish không mirror (index/registry/.gitkeep). KHÔNG bỏ _meta.yaml ở
    đây (khác _kb_tree_digest): _snapshot_federation mirror leaf _meta.yaml
    verbatim từ nguồn sang đích — không có bước ghi lại meta như _snapshot
    của .kb/ — nên cả hai phía đều mang cùng bytes khi thật sự đồng bộ;
    bỏ _meta.yaml khỏi digest sẽ che mất drift thật (vd. child republish
    chỉ đổi source_commit của một leaf mà không đổi nội dung nào khác)."""
    import hashlib

    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in _FED_TOP_SKIP:
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def check_federation_publish(
    source_root: Path, handle: "HubHandle | None", repo_id: str | None
) -> list[Issue]:
    """Health hub phân tầng: id entry hợp lệ, cảnh báo cycle, trạng thái đã
    publish lên upstream. handle = hub CẤP TRÊN (None khi root hub / offline)."""
    from center_kb.federation import find_cycle_segment, iter_entry_dirs

    fed_src = source_root / "federation"
    issues: list[Issue] = []
    for path_id, _ in iter_entry_dirs(fed_src):
        if not all(_ENTRY_SEGMENT_RE.fullmatch(s) for s in path_id.split("/")):
            issues.append(
                Issue(
                    "error",
                    f"federation entry '{path_id}' has an invalid path segment — "
                    "only letters/digits/._- per segment",
                )
            )
    if repo_id:
        hit = find_cycle_segment(fed_src, {repo_id}, exempt_exact={repo_id})
        if hit is not None:
            issues.append(
                Issue(
                    "warning",
                    f"own repo id '{repo_id}' appears inside federation entry "
                    f"'{hit}' — this is a cycle: content has looped back; "
                    "`kb publish` will refuse",
                )
            )
    if handle is not None and repo_id:
        dest = handle.federation_dir / repo_id
        if not dest.is_dir():
            issues.append(
                Issue(
                    "warning",
                    f"hub '{repo_id}' has not published to the upstream hub yet — "
                    "run `kb publish`",
                )
            )
        elif _fed_tree_digest(fed_src) != _fed_tree_digest(dest):
            issues.append(
                Issue(
                    "warning",
                    f"local federation/ differs from the published snapshot "
                    f"federation/{repo_id} on the upstream hub — run `kb publish`",
                )
            )
    return issues
