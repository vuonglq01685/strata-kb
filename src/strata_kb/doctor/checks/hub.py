"""Checks on the hub and on federation publishing."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from strata_kb import gitio, models
from strata_kb.doctor.issues import Issue, _flatten
from strata_kb.federation import (  # noqa: F401 -- _FED_TOP_SKIP re-exported
    _FED_TOP_SKIP,
    _fed_tree_digest,
)

if TYPE_CHECKING:
    from strata_kb.hub import HubHandle


def _kb_tree_digest(
    root: Path,
    synthesized: dict[str, str] | None = None,
    exclude_docs: frozenset[str] = frozenset(),
) -> str:
    """Deterministic digest of a .kb tree, over exactly what a publish mirrors.

    `root` is the root the two sides are compared AT -- the local `.kb/`
    directory on one side, the hub's `federation/<rid>/` entry on the other.
    That is the same pair of roots `publish._snapshot` builds its two
    manifests against, which is what makes the relative paths below
    comparable, and what makes handing them to `is_kb_artifact` correct
    (the path must be relative to the entry whose artefacts are being
    judged, never to some other root).

    Two exclusions, for two different reasons:

    * `_meta.yaml` is snapshot-only -- written by `_snapshot` on the hub
      side, never present locally -- so it would differ on every healthy
      pair.
    * Everything `pubgate.is_kb_artifact()` refuses. `_snapshot` filters
      the local manifest through exactly that predicate before diffing, so
      a file it refuses can never reach the hub -- `config.yaml` above
      all, which publish never mirrors (it can hold credentials) and which
      `kb init` writes into every real KB. Hashing it here would make the
      two sides permanently unequal and produce a warning no operator
      could ever clear, on advice ("run `kb publish`") naming the command
      they had just run. Calling the predicate rather than keeping a
      second hand-maintained exclusion list beside it is the point: the
      next change to what publish strips cannot desynchronise the two
      again. (`_assets.yaml` falls out of the same call -- it is hub-owned
      bookkeeping `divert_and_record` writes, and `_snapshot` excludes it
      from the destination manifest by name for that reason.)

    A file on the hub that a publish would never have written is NOT drift
    this check should report -- the stray sweep in `check_hub` above reports
    it, with the "delete them on the hub, and rotate any credential they
    contain" advice that shape actually needs.

    That advice is stale for a stray inside a recognized entry: a republish
    from that entry's own source repo already deletes it (the same
    diff/apply_sync mechanism this digest mirrors), so "kb doctor: OK"
    beside that warning does not mean the next publish is a no-op. The
    slim-layout stray sweep's message says so and names the remedy
    (republish upgrades the entry and clears the stray automatically;
    rotate the credential regardless). The leaf-entry stray sweep's message
    still has the older wording because it is pinned verbatim by
    `tests-gate/conftest.py`'s LEGACY_CONFIG_MIRROR_WARNING golden fixture;
    change the two together.

    `synthesized`: caller-supplied {relpath: sha256hex}, merged in on top
    of the files actually found on disk under `root`, exactly the way
    publish._snapshot's `dest_man.update(assetstore.synthesized_asset_
    entries(dest))` merges into its own destination manifest before
    diffing. Without this, an asset diverted to an object store -- its
    real bytes gone from `federation/<rid>/`, only `_assets.yaml` naming
    it -- is simply absent from this function's walk of the hub-side
    root, so the hub-side digest permanently differs from the local one
    (which still holds the real bytes on disk) on any hub with an asset
    store. Agreeing with `_snapshot` on the *predicate* for what counts
    (`is_kb_artifact`) is not enough; the two must also agree on *what a
    diverted asset's physical absence means*, or the check reproduces the
    same symptom -- a warning that never clears, on advice naming the
    command the operator just ran.

    This is WHY the digest is built as a {relpath: sha256-of-content}
    manifest (hashed once more, aggregated, at the end) rather than a
    single running hash over raw bytes read in file order: `synthesized`
    only ever knows a diverted asset's sha (asset_sha, read from its
    content-addressed filename -- spec A guarantees filename sha ==
    sha256(bytes), so this is exact, not an approximation), never its
    raw bytes (they are gone from this tree by construction), so there
    is no way to fold it into a single ongoing byte-stream hash. A
    manifest entry is comparable on equal footing whether its sha256 came
    from hashing real bytes or from reading a content-addressed filename
    -- hashsync.build_manifest / diff_manifests already rely on exactly
    that equivalence for `_snapshot`'s own diff, so this mirrors it rather
    than inventing a second notion of "what should be there".
    `synthesized` is caller-supplied, not computed here, because it must
    come from the SAME store `_snapshot` itself would resolve
    (assetstore.store_for_hub) and only ever applies to the hub-side call
    -- the local `.kb/` side has no asset store of its own to synthesize
    against.
    """
    import hashlib

    from strata_kb import pubgate

    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "_meta.yaml":
            continue
        rel = path.relative_to(root).as_posix()
        if exclude_docs and rel.split("/", 1)[0] in exclude_docs:
            continue  # a dev repo's -code is branch-local
        if not pubgate.is_kb_artifact(rel):
            continue
        # Legacy self-heal: a hub cache cloned before clones forced
        # core.autocrlf=false and shipped .gitattributes still has a CRLF
        # working tree, and neutralize_line_endings runs on clone, never on
        # pull. Normalising here keeps a byte-identical tree from reading as
        # drift until the TTL re-clone.
        manifest[rel] = hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
    if synthesized:
        manifest.update(synthesized)
    h = hashlib.sha256()
    for rel in sorted(manifest):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(manifest[rel].encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def _ignoring_digests(idx: models.FederationIndex) -> models.FederationIndex:
    """`content_sha256` is live (recomputed on every call to
    build_federation_index), so comparing it as part of "is the stored
    aggregate index in sync with the snapshots" makes that check fire on every
    hub that predates 0.25 (stored defaults to "") and on every tampered
    snapshot (stored is the old digest, rebuilt is the new one) -- the latter
    also means `kb reindex` would silently launder the tamper by overwriting
    the stored digest with the live one. That verdict belongs to
    check_published_digests alone; strip the field before this equality."""
    return idx.model_copy(
        update={"docs": [d.model_copy(update={"content_sha256": ""}) for d in idx.docs]}
    )


def check_hub(
    kb_dir: Path,
    handle: HubHandle | None,
    repo_id: str | None = None,
    *,
    warn_untracked_index: bool = False,
    code_doc: str | None = None,
) -> tuple[list[Issue], bool]:
    """Hub-first health. Returns (issues, hub_stale).

    ``warn_untracked_index`` gates the ``.kb-work/`` warning: only the
    hub maintainer's own checkout can act on "add it to the hub's
    .gitignore", so child/dev/ba callers (who reach a hub or its cache clone
    read-only) must leave it off.

    ``code_doc`` (a dev repo's ``<repo_id>-code``) is left out of the
    published-snapshot digest: it is regenerated per branch and CI publishes
    it.
    """
    from strata_kb.federation import build_federation_index, load_federation

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
        issues.append(Issue("warning", f"hub cache is stale (pull failed, age {age})"))
        hub_stale = True

    # The URL itself is never put in the message -- gitio.redact_url exists for
    # that, and here the config key alone is enough to find it. --local scopes
    # this to handle.root's own .git/config: without it, a remote.*.url defined
    # in the operator's global/system gitconfig is misreported as living in this
    # clone's own config.
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

    # GIT_CONFIG_COUNT/KEY/VALUE (how credential_env hands git a token without
    # putting it in argv) needs git >= 2.31 -- on an older git the env is
    # silently ignored and the operator gets git's own opaque auth error instead
    # of a message naming the way forward. Only worth checking when this hub ref
    # actually carries a credential.
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
                        "hub's .gitignore before someone runs `git add -A`",
                    )
                )

    fed = handle.federation_dir
    if fed.is_dir():
        from strata_kb import assetstore, pubgate
        from strata_kb.federation import (
            FED_TOP_EXCLUDE,
            iter_entry_dirs,
            iter_namespace_dirs,
            scan_broken_entries,
        )

        # A fully valid leaf entry nested beneath a broken one (exactly one of
        # _meta.yaml/index.yaml) is reached by neither iter_entry_dirs (stops at
        # the broken ancestor) nor iter_namespace_dirs (`continue`s at a leaf
        # without sweeping it) -- scan_broken_entries is an additive walk that
        # finds exactly those leaves, plus every broken entry directory itself,
        # without changing what iter_entry_dirs yields (load_federation still
        # sees exactly that).
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
                if (
                    ns_rel == broken_rel or ns_rel.startswith(f"{broken_rel}/")
                ) and len(broken_rel) > found_len:
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

        # Every one of the three federation.py walkers `continue`s past a
        # directory using the old slim layout (Phase 3, a 'manifests/'
        # subdirectory) -- so nothing above ever looked at what sits directly
        # beside a slim entry's manifests/, which is exactly the shape a leaked
        # credential takes there, at ANY depth (a slim entry nested inside a
        # broken one included -- this is what makes the broken-entry message
        # above's "its own subtree is still scanned for strays" true for that
        # shape instead of false). Reuses iter_namespace_dirs's own walk as the
        # traversal frontier -- it already visits every namespace directory at
        # every depth, federation/ itself included (ns_rel "") -- instead of a
        # second recursive walk: checking each ns_dir's OWN direct children for
        # the slim-layout shape catches one wherever it sits, not only at depth
        # 1 under federation/. manifests/'s own contents are left alone on
        # purpose -- that is legitimate old-format payload a slim publish DID
        # write, not something "a publish would never write"; is_kb_artifact has
        # no opinion on that format and would false-positive on it.
        for ns_rel, ns_dir in iter_namespace_dirs(fed):
            for slim_dir in sorted(c for c in ns_dir.iterdir() if c.is_dir()):
                if not (slim_dir / "manifests").is_dir():
                    continue
                # Holding manifests/ is a structural heuristic, and a directory
                # that merely LOOKS like an entry to one is not an entry. A
                # directory named `assets` INSIDE an entry is an asset directory
                # by is_kb_artifact's own rule -- `parts[-2] == "assets"` makes
                # its direct children artefacts -- so it can never be an entry
                # root, and calling it one costs twice: the slim-layout Issue is
                # wrong, and resolving the stray sweep against it strips its own
                # contents of the asset exemption (a legitimate
                # <entry>/<doc>/assets/pic.png reported as a leaked stray). With
                # NO entry above it there is no asset directory to confuse it
                # with -- assets only exist inside an entry -- and `assets` is a
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
                    and not pubgate.is_kb_artifact(p.relative_to(slim_dir).as_posix())
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

        # iter_entry_dirs only ever yields leaves, so nothing above looks at a
        # file dropped directly under federation/ itself or under an
        # intermediate namespace directory (e.g. federation/<mid>/ after a
        # hub-to-hub publish) -- exactly where a mid hub's own top-level
        # federation/ files land under _snapshot_federation, so without this
        # sweep the credential-leak case this warning exists for would be the
        # one case it misses. Same predicate as the leaf sweep above, plus
        # FED_TOP_EXCLUDE (a hub's own index.yaml/registry.yaml/.gitkeep) --
        # legitimate only directly under federation/ itself (ns_rel == ""), so
        # it must not be exempted at a nested namespace directory too, where
        # those same names are just as suspicious as any other stray.
        #
        # The path handed to is_kb_artifact must be relative to THE ENTRY WHOSE
        # ARTIFACTS ARE BEING JUDGED -- and if there is no entry above the file,
        # no asset exemption applies at all, because assets only exist inside an
        # entry. ns_dir here may be a genuine namespace directory with no entry
        # above it at all (federation/ itself, or a plain grouping directory --
        # including one that happens to be named "assets", or to start with a
        # dot), or it may BE a broken entry's own root, or a directory NESTED
        # inside one (e.g. <broken-entry>/doc-a/assets/). Do not pass the
        # fed-relative path unconditionally: that puts the wrong thing in
        # is_kb_artifact's parts[-2] slot for the first case -- the namespace
        # directory's OWN basename, not a real "assets" parent -- silently
        # exempting a stray sitting directly inside any non-leaf directory named
        # "assets", and puts a dot-prefixed namespace segment where
        # is_kb_artifact's dotfile check looks, wrongly rejecting a legitimate
        # asset beneath one. Find the nearest enclosing broken-entry root, if
        # any (the innermost match, for a broken entry nested inside another),
        # and resolve against THAT; with none, resolve against nothing -- pass
        # the bare basename, which can never satisfy is_kb_artifact's
        # `len(parts) >= 2` asset rule, so no exemption applies.
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
            # Hoisted once: build_federation_index hashes every published
            # entry's content to fill content_sha256 -- computing it again
            # inside check_published_digests would hash the whole hub tree a
            # second time on every `kb doctor` run.
            rebuilt = build_federation_index(fed)
            if _ignoring_digests(stored) != _ignoring_digests(rebuilt):
                issues.append(
                    Issue(
                        "error",
                        "federation/index.yaml is out of sync with the snapshots — "
                        "run `kb reindex`",
                    )
                )
            # Last-wins here, first-wins in check_published_digests's own
            # `expected.setdefault(...)` -- identical today only because
            # build_federation_index hoists one digest per repo and stamps every
            # entry (one per doc) with it; if that ever becomes per-doc, the two
            # must be reconciled.
            issues += check_published_digests(
                fed, {d.repo_id: d.content_sha256 for d in rebuilt.docs}
            )

    if repo_id:
        entry = fed / repo_id
        # A self-hub (its own configured hub resolves to itself -- handle.kb_dir
        # IS kb_dir) does not ordinarily publish itself into its own
        # federation/<repo_id>/; "has not published to the hub yet — run `kb
        # publish`" is meaningless there (you cannot publish a hub to itself in
        # the usual sense), and
        # test_cli_doctor_hub_kind_self_hub_no_false_warnings asserts this
        # warning must not appear for that shape. A CHILD, or a mid-hub pointed
        # at a genuinely different upstream, still gets the warning -- only
        # identity with the configured hub suppresses it. Checked here (not by
        # the cli.py call site) because check_hub already has both pieces of
        # identity it needs (kb_dir, handle) and needs no git lookup to compare
        # them, unlike cli.py's own source_root/upstream computation a few lines
        # down its own call site, which requires a real git repo and has its own
        # error path when there isn't one.
        is_self_hub = handle.kb_dir.resolve() == kb_dir.resolve()
        if not entry.is_dir():
            if not is_self_hub:
                issues.append(
                    Issue(
                        "warning",
                        f"repo '{repo_id}' has not published to the hub yet — run `kb publish`",
                    )
                )
        else:
            from strata_kb import assetstore

            # The hub-side digest must see a diverted asset the same way
            # publish._snapshot does -- assetstore.store_for_hub reads the HUB's
            # own config (handle.kb_dir), the exact source _snapshot itself
            # resolves from when no store override is passed. A
            # corrupt/unreachable config is reported separately by
            # check_asset_store; here it just means "no store known" -- no
            # synthesis, same as before.
            synthesized: dict[str, str] = {}
            try:
                active_store = assetstore.store_for_hub(handle)
            except (yaml.YAMLError, ValidationError, assetstore.AssetStoreError):
                active_store = None
            if active_store is not None:
                synthesized = assetstore.synthesized_asset_entries(entry)
            skip = frozenset({code_doc}) if code_doc else frozenset()
            if _kb_tree_digest(kb_dir.resolve(), exclude_docs=skip) != _kb_tree_digest(
                entry, synthesized, exclude_docs=skip
            ):
                # dev's -code is published by CI on push to the default branch;
                # a ba repo's -plan only goes out when the BA runs `kb publish`.
                advice = (
                    "merge to the default branch; CI publishes it"
                    if code_doc and code_doc.endswith("-code")
                    else "run `kb publish`"
                )
                issues.append(
                    Issue(
                        "warning",
                        f"local .kb differs from the published snapshot "
                        f"federation/{repo_id} — {advice}",
                    )
                )

    counts = Counter(d.id for r in load_federation(fed) for d in r.index.docs)
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


def check_published_digests(
    fed: Path, live: dict[str, str] | None = None
) -> list[Issue]:
    """Compare each snapshot's content against the digest stored for it in
    federation/index.yaml. This is the only tamper check available at the
    hub: there is no local .kb there to diff against.

    `live` is {repo_id: content_sha256} from a build_federation_index(fed)
    the caller already ran (check_hub hoists one for its own out-of-sync
    compare and passes it through here) -- avoids hashing every entry's
    content a second time. Left optional (recomputed via
    build_federation_index when omitted) so this check still works called on
    its own, e.g. from a test."""
    from strata_kb.federation import FEDERATION_INDEX_NAME, build_federation_index

    index_path = fed / FEDERATION_INDEX_NAME
    if not index_path.exists():
        return []  # missing index is reported by check_hub
    try:
        stored = models.load_yaml_model(index_path, models.FederationIndex)
    except (yaml.YAMLError, ValidationError):
        return []  # corruption is reported by check_hub
    if live is None:
        live = {d.repo_id: d.content_sha256 for d in build_federation_index(fed).docs}
    expected: dict[str, str] = {}
    for doc in stored.docs:
        expected.setdefault(doc.repo_id, doc.content_sha256)

    issues: list[Issue] = []
    for repo_id, digest in sorted(expected.items()):
        if repo_id not in live:
            continue  # missing/broken entry -- reported by check_hub
        if not digest:
            issues.append(
                Issue(
                    "warning",
                    f"federation/{repo_id} was published before 0.25 — content "
                    "digest not verified; run `kb reindex` on the hub to record it",
                )
            )
            continue
        if live[repo_id] != digest:
            issues.append(
                Issue(
                    "error",
                    f"federation/{repo_id} content does not match its published "
                    "digest — the snapshot was modified outside `kb publish`",
                )
            )
    return issues


def check_federation_publish(
    source_root: Path, handle: HubHandle | None, repo_id: str | None
) -> list[Issue]:
    """Health hub phân tầng: id entry hợp lệ, cảnh báo cycle, trạng thái đã
    publish lên upstream. handle = hub CẤP TRÊN (None khi root hub / offline)."""
    from strata_kb.federation import find_cycle_segment, iter_entry_dirs

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
