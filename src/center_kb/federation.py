from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import yaml
from pydantic import BaseModel, ValidationError

from center_kb import models

logger = logging.getLogger("center_kb.federation")

FEDERATION_INDEX_NAME = "index.yaml"
REGISTRY_NAME = "registry.yaml"

# Files that belong at the very top of a hub's OWN federation/ (its aggregate
# index, its governance registry, the placeholder that keeps an otherwise-
# empty federation/ tracked by git) -- never mirrored content, so a
# hub-to-hub publish's source-side manifest excludes them (publish.py's
# _snapshot_federation) and doctor's stray-file sweep (check_hub) exempts
# them at every level it inspects. Was publish.py's own _FED_TOP_EXCLUDE;
# moved here so both publish.py and doctor.py share one definition instead
# of doctor.py reaching into a private name in a sibling module.
FED_TOP_EXCLUDE = ("index.yaml", "registry.yaml", ".gitkeep")


class RegistryError(RuntimeError):
    """federation/registry.yaml is unreadable — intake must fail closed.

    Deliberately stays out of the KbError family (Wave G fix round 2, item
    7): not CLI-reachable -- both callers (publish's _governed_registry,
    intake's authorize path) already convert it to their own message/HTTP
    response themselves, fail-closed by design.
    """


def load_registry(federation_dir: Path) -> models.Registry:
    path = federation_dir / REGISTRY_NAME
    if not path.exists():
        return models.Registry()
    try:
        return models.load_yaml_model(path, models.Registry)
    except (yaml.YAMLError, ValidationError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError is a ValueError, not a yaml.YAMLError/
        # ValidationError -- a non-UTF-8 registry.yaml must fail closed here
        # too, not escape as a raw traceback (F-D9 finding 2's exact gap,
        # one call deeper).
        raise RegistryError(f"federation/{REGISTRY_NAME} is invalid: {exc}") from exc


def registry_map(registry: models.Registry) -> dict[str, str]:
    """{owner/repo: repo_id} -- the one accessor both write paths read through.

    A registry entry may be the plain repo-id string or a {repo_id,
    workflow} mapping (the workflow pin only matters to intake.authorize,
    which reads the entry itself via Registry.resolve) -- this flattens
    either shape to the repo-id so callers see one flat dict either way.
    """
    out: dict[str, str] = {}
    for repo in registry.repos:
        entry = registry.resolve(repo)
        if entry is not None:
            out[repo] = entry.repo_id
    return out


class FederationMeta(BaseModel):
    repo_id: str
    source_url: str = ""
    source_commit: str
    published_at: str = ""


@dataclass
class FederatedRepo:
    meta: FederationMeta
    index: models.KBIndex
    kb_dir: Path  # federation/<repo-id>/ — a full .kb mirror (L0→L3)


ENTRY_INDEX_NAME = "index.yaml"
ENTRY_META_NAME = "_meta.yaml"


def iter_entry_dirs(federation_dir: Path) -> list[tuple[str, Path]]:
    """(path-id, dir) của mọi leaf entry, DFS theo tên tăng dần.

    Leaf = thư mục có cả _meta.yaml lẫn index.yaml (một mirror .kb đầy đủ).
    Thư mục phía trên leaf là namespace thuần (một tầng cho mỗi hub publish lên).
    Entry slim cũ (Phase 3, thư mục 'manifests/') và entry thiếu một trong hai
    file bị bỏ qua kèm cảnh báo — republish từ repo nguồn để nâng cấp.
    """
    out: list[tuple[str, Path]] = []

    def _walk(cur: Path, rel: str) -> None:
        for child in sorted(p for p in cur.iterdir() if p.is_dir()):
            if child.is_symlink():
                # Regular files/dirs only (mirrors hashsync's invariant) —
                # a symlinked dir could point back up the tree and loop
                # _walk forever, or duplicate an entry that already has a
                # real path-id elsewhere.
                continue
            child_rel = f"{rel}/{child.name}" if rel else child.name
            if (child / "manifests").is_dir():
                logger.warning(
                    "federation/%s uses the old slim layout — skipping; "
                    "run `kb publish` from that repo to upgrade it",
                    child_rel,
                )
                continue
            has_meta = (child / ENTRY_META_NAME).exists()
            has_index = (child / ENTRY_INDEX_NAME).exists()
            if has_meta and has_index:
                out.append((child_rel, child))
            elif has_meta or has_index:
                logger.warning(
                    "federation/%s missing _meta.yaml or index.yaml — skipping",
                    child_rel,
                )
            else:
                _walk(child, child_rel)

    if federation_dir.is_dir():
        _walk(federation_dir, "")
    return out


def iter_namespace_dirs(federation_dir: Path) -> list[tuple[str, Path]]:
    """(path-id, dir) of every NON-leaf directory in the mirror layout, DFS
    in ascending-name order -- federation_dir itself first (path-id ""),
    then every directory iter_entry_dirs's walk recurses into on its way to
    each leaf.

    iter_entry_dirs only ever returns leaves, so nothing inspects a file
    dropped directly under federation/ itself or under an intermediate
    namespace directory (e.g. federation/<mid>/ after a hub-to-hub publish)
    -- doctor's stray-file sweep (check_hub) uses this to reach those levels
    too (F-D9 batch finding 5).

    Diverges from iter_entry_dirs on ONE of its three stop conditions on
    purpose (M3): a broken entry (exactly one of _meta.yaml/index.yaml) is
    still walked and reported as a namespace directory here, not skipped.
    iter_entry_dirs is right to skip it as unusable content -- but "unusable
    as an entry" must not mean "unscanned": a half-written entry is exactly
    what an interrupted publish leaves behind, and skipping the walk here
    left the whole subtree beneath it -- including a stray credential-
    bearing file dropped directly inside it -- entirely invisible to
    doctor's stray-file sweep, with no issue raised about the broken entry
    either to signal that anything had gone unscanned. The other two stop
    conditions (old slim layout, leaf) still match iter_entry_dirs exactly.
    """
    out: list[tuple[str, Path]] = []

    def _walk(cur: Path, rel: str) -> None:
        for child in sorted(p for p in cur.iterdir() if p.is_dir()):
            if child.is_symlink():
                continue
            child_rel = f"{rel}/{child.name}" if rel else child.name
            if (child / "manifests").is_dir():
                continue  # old slim layout -- iter_entry_dirs already warns
            has_meta = (child / ENTRY_META_NAME).exists()
            has_index = (child / ENTRY_INDEX_NAME).exists()
            if has_meta and has_index:
                continue  # leaf entry, not a namespace directory
            # Neither, or exactly one (a broken entry, M3) -- either way this
            # is a directory doctor's stray-file sweep must still look inside.
            out.append((child_rel, child))
            _walk(child, child_rel)

    if federation_dir.is_dir():
        out.append(("", federation_dir))
        _walk(federation_dir, "")
    return out


class BrokenEntryScan(NamedTuple):
    broken: list[tuple[str, Path]]
    nested_leaves: list[tuple[str, Path]]


def scan_broken_entries(federation_dir: Path) -> BrokenEntryScan:
    """(broken, nested_leaves) -- additive, doctor-only (Ruling P36, Wave G
    fix round 3): iter_entry_dirs keeps its `elif has_meta or has_index:`
    stop and does not recurse past a broken entry (exactly one of
    _meta.yaml/index.yaml); iter_namespace_dirs (M3) now walks in but
    `continue`s at a leaf without sweeping its contents. Net: a fully valid
    leaf entry nested beneath a broken entry is reached by NEITHER sweep,
    and nothing signals that the broken subtree was skipped at all.

    Does not widen what iter_entry_dirs itself yields -- load_federation
    consumes that exact yield as the definition of a published entry, and a
    real hub-to-hub publish never produces this shape (two tiers of nesting
    with a broken outer tier), so changing that definition is a semantic
    change with unmeasured blast radius for a case doctor alone needs to
    see.

    broken: every directory holding exactly one of _meta.yaml/index.yaml,
    at any depth -- so doctor.check_hub can raise an Issue naming each one
    (previously only a logger.warning inside iter_entry_dirs's own walk,
    which never reached doctor's output).

    nested_leaves: every fully valid leaf entry (_meta.yaml AND
    index.yaml) whose path passes through a broken ancestor -- exactly the
    leaves iter_entry_dirs's stop condition never reaches. A leaf NOT
    beneath a broken ancestor is never included here (iter_entry_dirs
    already finds it), so a caller appending this list to
    iter_entry_dirs's own output sweeps each leaf exactly once.
    """
    broken: list[tuple[str, Path]] = []
    nested_leaves: list[tuple[str, Path]] = []

    def _walk(cur: Path, rel: str, under_broken: bool) -> None:
        for child in sorted(p for p in cur.iterdir() if p.is_dir()):
            if child.is_symlink():
                continue
            child_rel = f"{rel}/{child.name}" if rel else child.name
            if (child / "manifests").is_dir():
                continue  # old slim layout -- iter_entry_dirs already warns
            has_meta = (child / ENTRY_META_NAME).exists()
            has_index = (child / ENTRY_INDEX_NAME).exists()
            if has_meta and has_index:
                if under_broken:
                    nested_leaves.append((child_rel, child))
                continue  # leaf entry -- nothing beneath it to recurse into
            if has_meta or has_index:
                broken.append((child_rel, child))
                _walk(child, child_rel, True)
            else:
                _walk(child, child_rel, under_broken)

    if federation_dir.is_dir():
        _walk(federation_dir, "", False)
    return BrokenEntryScan(broken, nested_leaves)


def find_cycle_segment(
    federation_dir: Path,
    forbidden: set[str],
    exempt_exact: frozenset[str] | set[str] = frozenset(),
) -> str | None:
    """Path-id entry đầu tiên chứa một segment bị cấm — dấu hiệu nội dung đã
    đi vòng qua hub đó quay lại; publish tiếp sẽ tạo vòng lặp phình vô hạn.

    exempt_exact: các path-id được miễn khi trùng CHÍNH XÁC (một segment) —
    dùng cho self-entry của hub (hub tự publish .kb/ của nó vào chính nó).
    Lưu ý: loop-back DƯỚI ID CỦA CHÍNH REPO NGUỒN luôn lồng >=2 segment (vì
    self-entry 1-segment của chính nó luôn nằm trong exempt_exact); nhưng
    loop-back từ HUB ĐÍCH có thể chỉ là 1 segment — nó vẫn bị chặn vì
    caller (publish_federation) không bao giờ đưa dest_rid vào exempt_exact.
    """
    for path_id, _ in iter_entry_dirs(federation_dir):
        if path_id in exempt_exact:
            continue
        if any(seg in forbidden for seg in path_id.split("/")):
            return path_id
    return None


def load_federation(federation_dir: Path) -> list[FederatedRepo]:
    """Đọc mọi entry (phẳng lẫn lồng) trong layout mirror.

    meta.repo_id được đè bằng path-id tương đối (vd 'mid/repo-x') — file
    _meta.yaml mirror từ tầng dưới chỉ biết tên cụt của chính nó.
    """
    repos: list[FederatedRepo] = []
    for path_id, child in iter_entry_dirs(federation_dir):
        try:
            meta = models.load_yaml_model(child / ENTRY_META_NAME, FederationMeta)
            index = models.load_yaml_model(child / ENTRY_INDEX_NAME, models.KBIndex)
        except (yaml.YAMLError, ValidationError, UnicodeDecodeError) as exc:
            # UnicodeDecodeError is a ValueError, not a yaml.YAMLError/
            # ValidationError -- a non-UTF-8 _meta.yaml/index.yaml must skip
            # like any other broken entry, not escape as a raw traceback out
            # of build_federation_index/write_federation_index (reindex,
            # publish's own aggregate-index rebuild).
            logger.warning("federation/%s is broken — skipping: %s", path_id, exc)
            continue
        repos.append(
            FederatedRepo(
                meta=meta.model_copy(update={"repo_id": path_id}),
                index=index,
                kb_dir=child,
            )
        )
    return repos


def build_federation_index(federation_dir: Path) -> models.FederationIndex:
    """The aggregate index — 100% deterministic from the sub-snapshots.

    Order: DFS theo tên tăng dần từng cấp (deterministic; KHÔNG phải sort
    lexicographic toàn cục của path-id), docs in the order of each repo's
    own index.
    """
    entries: list[models.FedIndexEntry] = []
    for repo in load_federation(federation_dir):
        for doc in repo.index.docs:
            entries.append(
                models.FedIndexEntry(
                    repo_id=repo.meta.repo_id,
                    doc_id=doc.id,
                    title=doc.title,
                    revision=doc.revision,
                    tags=doc.tags,
                    summary=doc.summary,
                    source_commit=repo.meta.source_commit,
                    published_at=repo.meta.published_at,
                )
            )
    return models.FederationIndex(docs=entries)


def write_federation_index(federation_dir: Path) -> Path:
    index_path = federation_dir / FEDERATION_INDEX_NAME
    models.save_yaml_model(index_path, build_federation_index(federation_dir))
    return index_path
