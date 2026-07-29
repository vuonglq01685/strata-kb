from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from center_kb import federation, ghio, gitio, models
from center_kb import hub as hub_mod

logger = logging.getLogger("center_kb.publish")

_REPO_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_LEGACY_ID_RE = re.compile(r"(^|-)x\d+$")

PR_BODY_TEMPLATE = (
    "Publish snapshot of repo '{rid}' @ {commit}.\n\n"
    "Merging this PR makes the content searchable across the federation."
)


class PublishError(RuntimeError):
    """Publishing the snapshot to the hub failed."""


@dataclass
class PublishReport:
    repo_id: str
    source_commit: str
    n_docs: int
    pushed: bool
    mode: str = "direct"  # "direct" | "pr"
    pr_url: str = ""


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
    )


def _snapshot(
    kb_abs: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    source_url: str | None = None,
    store=None,
) -> tuple[int, bool]:
    """Sync .kb/ → federation/<rid>/ by hash-diff; return (n_docs, changed).

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
    active_store = store if store is not None else assetstore.store_for_hub(handle)
    local_index = models.load_yaml_model(kb_abs / "index.yaml", models.KBIndex)
    local_man = hashsync.build_manifest(kb_abs)
    dest_man = hashsync.build_manifest(
        dest, exclude=("_meta.yaml", assetstore.RECORD_NAME)
    )
    if active_store is not None:
        dest_man.update(assetstore.synthesized_asset_entries(dest))
    changed, deleted = hashsync.diff_manifests(local_man, dest_man)
    if not changed and not deleted:
        return len(local_index.docs), False
    hashsync.apply_sync(kb_abs, dest, changed, deleted)
    if active_store is not None:
        try:
            assetstore.divert_and_record(dest, active_store, deleted)
        except assetstore.AssetStoreError:
            # apply_sync above already wrote asset bytes (and any other
            # changed/deleted files) into the hub clone's working tree
            # before this failed. Left uncleaned, a retry with a healthy
            # store would build_manifest(dest) == the child's manifest
            # (bytes already match) and early-return "unchanged" BEFORE
            # ever reaching divert again -- and _publish_direct/_publish_pr
            # would then git-add + commit those leftover binaries straight
            # into hub git. Restore federation/ to its last committed
            # state before re-raising (mirrors intake.intake_publish's
            # matching guard for the same failure mode).
            co = gitio._run(handle.root, "checkout", "--", "federation")
            if co.returncode != 0:
                logger.warning(
                    "git checkout -- federation failed while restoring "
                    "after an asset store failure: %s", co.stderr.strip()
                )
            cl = gitio._run(handle.root, "clean", "-fd", "--", "federation")
            if cl.returncode != 0:
                logger.warning(
                    "git clean -fd -- federation failed while restoring "
                    "after an asset store failure: %s", cl.stderr.strip()
                )
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
    return len(local_index.docs), True


_FED_TOP_EXCLUDE = ("index.yaml", "registry.yaml", ".gitkeep")


def _snapshot_federation(
    fed_src: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    source_url: str | None = None,
    store=None,
) -> tuple[int, bool]:
    """Sync federation/ (hub trung gian) → federation/<rid>/ trên hub cấp trên.

    Khác _snapshot: nguồn là cả cây federation (leaf entries lồng nhau, mỗi leaf
    tự mang _meta.yaml); index.yaml/registry.yaml tầng đỉnh là sản phẩm riêng
    của hub nguồn — không đẩy; KHÔNG viết _meta.yaml ở gốc đích (gốc entry hub
    là namespace, không phải leaf — walk đệ quy phải đi xuyên qua nó).
    Assets (kể cả record S3-divert _assets.yaml) mirror verbatim.
    """
    from center_kb import hashsync

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
    src_man = hashsync.build_manifest(fed_src, exclude=_FED_TOP_EXCLUDE)
    dest_man = hashsync.build_manifest(dest)
    if not src_man and dest_man:
        raise PublishError(
            "source federation/ is empty but the hub already holds entries under "
            f"'{rid}' — refusing to wipe them; delete federation/{rid} on the hub "
            "manually if that is really intended"
        )
    n_docs = len(federation.build_federation_index(fed_src).docs)
    changed, deleted = hashsync.diff_manifests(src_man, dest_man)
    if not changed and not deleted:
        return n_docs, False
    hashsync.apply_sync(fed_src, dest, changed, deleted)
    return n_docs, True


def warn_legacy_ids(kb_dir: Path) -> list[str]:
    """x{n} ids are the opaque fallback of the old CLI (< 2debcbc) or of headings
    that could not be slugged — warn so the repo re-ingests with the new CLI.
    No reject: old data is still valid, just less readable (spec §6b)."""
    hits: list[str] = []
    for man_path in sorted(kb_dir.glob("*/_manifest.yaml")):
        manifest = models.load_yaml_model(man_path, models.Manifest)
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


def publish(
    kb_dir: Path,
    hub_ref: str,
    repo_id: str | None = None,
    max_retries: int = 3,
    mode: str = "auto",
) -> PublishReport:
    kb_abs = kb_dir.resolve()
    warn_legacy_ids(kb_abs)
    source_root = gitio.git_root(kb_abs)
    source_commit = gitio.head_commit(source_root)
    rid = repo_id or source_root.name
    if not _REPO_ID_RE.fullmatch(rid) or rid in {".", ".."}:
        raise PublishError(
            f"repo-id '{rid}' is invalid — only letters/digits/._- allowed, no path separators"
        )
    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise PublishError(f"could not reach hub '{gitio.redact_url(hub_ref)}'")
    _neutralize_excludes(handle.root)

    if mode == "auto":
        use_pr = (
            gitio.has_remote(handle.root)
            and "github" in gitio.remote_url(handle.root)
            and ghio.gh_available()
        )
        mode = "pr" if use_pr else "direct"
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
    rid = repo_id or source_root.name
    if not _REPO_ID_RE.fullmatch(rid) or rid in {".", ".."}:
        raise PublishError(
            f"repo-id '{rid}' is invalid — only letters/digits/._- allowed, no path separators"
        )
    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise PublishError(f"could not reach hub '{gitio.redact_url(hub_ref)}'")
    if handle.root.resolve() == source_root.resolve():
        raise PublishError(
            "federation cycle detected: the upstream hub resolves to this repo itself"
        )
    forbidden = {rid}
    dest_rid = config_mod.load_config(handle.kb_dir).repo_id
    if dest_rid:
        forbidden.add(dest_rid)
    hit = federation.find_cycle_segment(fed_src, forbidden)
    if hit is not None:
        raise PublishError(
            f"federation cycle detected: entry '{hit}' contains a hub id from this "
            "publish chain — publishing would loop content back on itself"
        )
    _neutralize_excludes(handle.root)
    if mode == "auto":
        use_pr = (
            gitio.has_remote(handle.root)
            and "github" in gitio.remote_url(handle.root)
            and ghio.gh_available()
        )
        mode = "pr" if use_pr else "direct"
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
            gitio.push(handle.root)
            return True
        except gitio.GitError:
            if attempt == max_retries - 1:
                raise PublishError(
                    f"push to hub failed after {max_retries} attempts (race?)"
                )
            gitio.pull_rebase(handle.root)
            # another repo just published — the aggregate index in our commit may
            # be missing their docs; regen (deterministic), then commit the fix
            federation.write_federation_index(handle.federation_dir)
            gitio.commit_paths(
                handle.root,
                f"publish: reindex after rebase ({rid})",
                ["federation/index.yaml"],
            )
    return False


def _publish_direct(
    kb_abs: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    max_retries: int,
    snapshot_fn=_snapshot,
) -> PublishReport:
    n_docs, changed = snapshot_fn(kb_abs, handle, rid, source_commit)
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
    except Exception as exc:  # eager refresh best-effort — query sau rebuild lazy
        logger.warning("search index refresh failed: %s", exc)
    return PublishReport(rid, source_commit, n_docs, pushed, mode="direct")


def _publish_pr(
    kb_abs: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    snapshot_fn=_snapshot,
) -> PublishReport:
    if not ghio.gh_available():
        raise PublishError(
            "PR mode needs the GitHub CLI — install `gh` (https://cli.github.com) "
            "or run `kb publish --direct` if direct pushes are allowed"
        )
    branch = f"publish/{rid}"
    original = gitio.current_branch(handle.root)
    try:
        gitio.checkout_branch(handle.root, branch, original)
        n_docs, changed = snapshot_fn(kb_abs, handle, rid, source_commit)
        federation.write_federation_index(handle.federation_dir)
        committed = gitio.commit_paths(
            handle.root, f"publish: {rid} @ {source_commit}", ["federation"]
        )
        if not committed:
            return PublishReport(rid, source_commit, n_docs, False, mode="pr")
        gitio.push_branch(handle.root, branch)
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
    return PublishReport(rid, source_commit, n_docs, True, mode="pr", pr_url=url)


def _default_get_json(url: str) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
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
