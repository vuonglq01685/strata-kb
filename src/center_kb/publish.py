from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from center_kb import federation, gitio, models
from center_kb import hub as hub_mod

_REPO_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class PublishError(RuntimeError):
    """Publishing the index to the hub failed."""


@dataclass
class PublishReport:
    repo_id: str
    source_commit: str
    n_docs: int
    pushed: bool


def publish(
    kb_dir: Path, hub_ref: str, repo_id: str | None = None, max_retries: int = 3
) -> PublishReport:
    """Snapshot the current repo's L0+L1 → federation/<repo-id>/ on the hub.

    Commits in the clone cache (or the hub worktree if --hub is a path); pushes
    if the hub has a remote origin. If the push is rejected (race between two
    CI runs) → pull --rebase and retry, up to max_retries times.
    """
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

    hub_index_path = handle.kb_dir / "index.yaml"
    if hub_index_path.exists():
        hub_index = models.load_yaml_model(hub_index_path, models.KBIndex)
        if rid in {d.id for d in hub_index.docs}:
            raise PublishError(
                f"repo-id '{rid}' collides with a domain document's doc-id on the hub — "
                "pick a different --repo-id"
            )

    local_index = models.load_yaml_model(kb_abs / "index.yaml", models.KBIndex)
    dest = handle.federation_dir / rid
    fed_root = handle.federation_dir.resolve()
    if not dest.resolve().is_relative_to(fed_root):
        raise PublishError(
            f"repo-id '{rid}' escapes the federation/ directory on the hub — refusing to publish"
        )
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "manifests").mkdir(parents=True)
    models.save_yaml_model(dest / "index.yaml", local_index)
    for doc in local_index.docs:
        manifest_path = kb_abs / doc.id / "_manifest.yaml"
        if manifest_path.exists():
            shutil.copyfile(manifest_path, dest / "manifests" / f"{doc.id}.yaml")
    meta = federation.FederationMeta(
        repo_id=rid,
        source_url=gitio.remote_url(source_root),
        source_commit=source_commit,
        published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    models.save_yaml_model(dest / "_meta.yaml", meta)

    committed = gitio.commit_paths(
        handle.root, f"publish: {rid} @ {source_commit}", ["federation"]
    )
    pushed = False
    if committed and gitio.has_remote(handle.root):
        for attempt in range(max_retries):
            try:
                gitio.push(handle.root)
                pushed = True
                break
            except gitio.GitError:
                if attempt == max_retries - 1:
                    raise PublishError(
                        f"push to hub failed after {max_retries} attempts (race?)"
                    )
                gitio.pull_rebase(handle.root)
    return PublishReport(
        repo_id=rid,
        source_commit=source_commit,
        n_docs=len(local_index.docs),
        pushed=pushed,
    )
