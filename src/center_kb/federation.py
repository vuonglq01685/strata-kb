from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from center_kb import models

logger = logging.getLogger("center_kb.federation")

FEDERATION_INDEX_NAME = "index.yaml"


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


def load_federation(federation_dir: Path) -> list[FederatedRepo]:
    """Read every federation/<repo>/ entry in the new mirror layout.

    Entries in the old format (Phase 3, a 'manifests/' directory) and broken
    entries are skipped with a warning — republish from the source repo to
    upgrade them.
    """
    if not federation_dir.is_dir():
        return []
    repos: list[FederatedRepo] = []
    for child in sorted(p for p in federation_dir.iterdir() if p.is_dir()):
        if (child / "manifests").is_dir():
            logger.warning(
                "federation/%s uses the old slim layout — skipping; "
                "run `kb publish` from that repo to upgrade it",
                child.name,
            )
            continue
        meta_path = child / "_meta.yaml"
        index_path = child / "index.yaml"
        if not meta_path.exists() or not index_path.exists():
            logger.warning(
                "federation/%s missing _meta.yaml or index.yaml — skipping", child.name
            )
            continue
        try:
            meta = models.load_yaml_model(meta_path, FederationMeta)
            index = models.load_yaml_model(index_path, models.KBIndex)
        except (yaml.YAMLError, ValidationError) as exc:
            logger.warning("federation/%s is broken — skipping: %s", child.name, exc)
            continue
        repos.append(FederatedRepo(meta=meta, index=index, kb_dir=child))
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
