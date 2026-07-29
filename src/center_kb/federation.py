from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from center_kb import models

logger = logging.getLogger("center_kb.federation")

FEDERATION_INDEX_NAME = "index.yaml"
REGISTRY_NAME = "registry.yaml"


class RegistryError(RuntimeError):
    """federation/registry.yaml is unreadable — intake must fail closed."""


def load_registry(federation_dir: Path) -> models.Registry:
    path = federation_dir / REGISTRY_NAME
    if not path.exists():
        return models.Registry()
    try:
        return models.load_yaml_model(path, models.Registry)
    except (yaml.YAMLError, ValidationError) as exc:
        raise RegistryError(f"federation/{REGISTRY_NAME} is invalid: {exc}") from exc


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


def find_cycle_segment(
    federation_dir: Path,
    forbidden: set[str],
    exempt_exact: frozenset[str] | set[str] = frozenset(),
) -> str | None:
    """Path-id entry đầu tiên chứa một segment bị cấm — dấu hiệu nội dung đã
    đi vòng qua hub đó quay lại; publish tiếp sẽ tạo vòng lặp phình vô hạn.

    exempt_exact: các path-id được miễn khi trùng CHÍNH XÁC (một segment) —
    dùng cho self-entry của hub (hub tự publish .kb/ của nó vào chính nó);
    nội dung quay vòng thật luôn về dạng lồng >=2 segment.
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
        except (yaml.YAMLError, ValidationError) as exc:
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

    Order: repo_id ascending (load_federation already sorts), docs in the order
    of each repo's own index.
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
