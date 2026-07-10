from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from aero_kb import models

logger = logging.getLogger("aero_kb.federation")


class FederationMeta(BaseModel):
    repo_id: str
    source_url: str = ""
    source_commit: str
    published_at: str = ""


@dataclass
class FederatedRepo:
    meta: FederationMeta
    index: models.KBIndex
    manifests: dict[str, models.Manifest] = field(default_factory=dict)


def load_federation(federation_dir: Path) -> list[FederatedRepo]:
    """Read every federation/<repo>/ entry — broken entries are skipped with a warning."""
    if not federation_dir.is_dir():
        return []
    repos: list[FederatedRepo] = []
    for child in sorted(p for p in federation_dir.iterdir() if p.is_dir()):
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
        manifests: dict[str, models.Manifest] = {}
        for mf in sorted((child / "manifests").glob("*.yaml")):
            try:
                manifest = models.load_yaml_model(mf, models.Manifest)
            except (yaml.YAMLError, ValidationError) as exc:
                logger.warning(
                    "federation/%s manifest '%s' is broken — skipping: %s",
                    child.name,
                    mf.name,
                    exc,
                )
                continue
            manifests[manifest.id] = manifest
        repos.append(FederatedRepo(meta=meta, index=index, manifests=manifests))
    return repos
