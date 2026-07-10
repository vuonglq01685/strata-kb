from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aero_kb import federation, gitio, models
from aero_kb import hub as hub_mod


class PublishError(RuntimeError):
    """Publish index lên hub thất bại."""


@dataclass
class PublishReport:
    repo_id: str
    source_commit: str
    n_docs: int
    pushed: bool


def publish(
    kb_dir: Path, hub_ref: str, repo_id: str | None = None, max_retries: int = 3
) -> PublishReport:
    """Snapshot L0+L1 của repo hiện tại → federation/<repo-id>/ trên hub.

    Commit tại clone cache (hoặc worktree hub nếu --hub là path); push nếu
    hub có remote origin. Push bị reject (race giữa 2 CI) → pull --rebase
    rồi thử lại, tối đa max_retries lần.
    """
    kb_abs = kb_dir.resolve()
    source_root = gitio.git_root(kb_abs)
    source_commit = gitio.head_commit(source_root)
    rid = repo_id or source_root.name

    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise PublishError(f"không truy cập được hub '{hub_ref}'")

    hub_index_path = handle.kb_dir / "index.yaml"
    if hub_index_path.exists():
        hub_index = models.load_yaml_model(hub_index_path, models.KBIndex)
        if rid in {d.id for d in hub_index.docs}:
            raise PublishError(
                f"repo-id '{rid}' trùng doc-id tài liệu domain trong hub — "
                "chọn --repo-id khác"
            )

    local_index = models.load_yaml_model(kb_abs / "index.yaml", models.KBIndex)
    dest = handle.federation_dir / rid
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

    committed = gitio.commit_all(handle.root, f"publish: {rid} @ {source_commit}")
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
                        f"push hub thất bại sau {max_retries} lần thử (race?)"
                    )
                gitio.pull_rebase(handle.root)
    return PublishReport(
        repo_id=rid,
        source_commit=source_commit,
        n_docs=len(local_index.docs),
        pushed=pushed,
    )
