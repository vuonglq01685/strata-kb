from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from center_kb import federation, ghio, gitio, models
from center_kb import hub as hub_mod

_REPO_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

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
    )


def _snapshot(
    kb_abs: Path, handle: hub_mod.HubHandle, rid: str, source_commit: str
) -> int:
    """Mirror the whole of .kb/ → federation/<rid>/.

    The aggregate index.yaml is NOT written here — see publish()/_publish_direct():
    index.yaml is committed separately from the <rid>/ commit so that two repos
    publishing for the first time into one empty hub (federation/index.yaml does
    not exist yet) can never hit an "add/add" conflict on rebase (two branches
    each newly creating one file at the same path with different content is a
    conflict that cannot be auto-merged, whatever the rebase strategy).
    """
    dest = handle.federation_dir / rid
    fed_root = handle.federation_dir.resolve()
    if not dest.resolve().is_relative_to(fed_root):
        raise PublishError(
            f"repo-id '{rid}' escapes the federation/ directory on the hub — refusing to publish"
        )
    local_index = models.load_yaml_model(kb_abs / "index.yaml", models.KBIndex)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(kb_abs, dest)
    meta = federation.FederationMeta(
        repo_id=rid,
        source_url=gitio.remote_url(gitio.git_root(kb_abs)),
        source_commit=source_commit,
        published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    models.save_yaml_model(dest / "_meta.yaml", meta)
    return len(local_index.docs)


def publish(
    kb_dir: Path,
    hub_ref: str,
    repo_id: str | None = None,
    max_retries: int = 3,
    mode: str = "auto",
) -> PublishReport:
    kb_abs = kb_dir.resolve()
    source_root = gitio.git_root(kb_abs)
    source_commit = gitio.head_commit(source_root)
    rid = repo_id or source_root.name
    if not _REPO_ID_RE.fullmatch(rid) or rid in {".", ".."}:
        raise PublishError(
            f"repo-id '{rid}' is invalid — only letters/digits/._- allowed, no path separators"
        )
    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise PublishError(f"could not reach hub '{hub_ref}'")
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
) -> PublishReport:
    n_docs = _snapshot(kb_abs, handle, rid, source_commit)
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
    return PublishReport(rid, source_commit, n_docs, pushed, mode="direct")


def _publish_pr(
    kb_abs: Path, handle: hub_mod.HubHandle, rid: str, source_commit: str
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
        n_docs = _snapshot(kb_abs, handle, rid, source_commit)
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
