"""testcover — which tester repo covers which story, and which BA repo owns it.

Kept apart from `testflow` because `kb doctor` needs it and `testflow` reads
reports through `testreport`, which imports `doctor`: this module imports
only the federation layer, so the doctor hub check can use it at module level.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from strata_kb import kinds, models, query
from strata_kb.federation import load_federation

if TYPE_CHECKING:
    from collections.abc import Mapping

    from strata_kb.hub import HubHandle


def _sections(folder, entry_id: str) -> list[models.SectionEntry]:
    try:
        manifest = models.load_yaml_model(folder / "_manifest.yaml", models.Manifest)
    except (OSError, yaml.YAMLError, UnicodeDecodeError, ValidationError):
        return []
    return manifest.sections if manifest.id == entry_id else []


def tester_coverage(hub: HubHandle) -> dict[str, frozenset[str]]:
    """Tester repo id -> story ids its generated `-test` docs hold groups for."""
    out: dict[str, set[str]] = {}
    for fed in load_federation(hub.federation_dir):
        for entry in fed.index.docs:
            folder = query.doc_dir(fed.kb_dir, entry.id)
            if folder is None or not kinds.is_test_doc(entry.title, entry.tags):
                continue
            stories = {s.file for s in _sections(folder, entry.id)}
            out.setdefault(fed.meta.repo_id, set()).update(stories)
    return {repo: frozenset(stories) for repo, stories in out.items()}


def _ba_repo_of(hub: HubHandle) -> dict[str, str]:
    """Story id -> BA repo id, by the plan section that lists it."""
    out: dict[str, str] = {}
    for fed in load_federation(hub.federation_dir):
        for entry in fed.index.docs:
            folder = query.doc_dir(fed.kb_dir, entry.id)
            if folder is None or not kinds.is_plan(entry.title, entry.tags):
                continue
            for sec in _sections(folder, entry.id):
                out.setdefault(sec.id, fed.meta.repo_id)
    return out


def duplicate_testers(
    hub: HubHandle, covered: Mapping[str, frozenset[str]]
) -> list[str]:
    """One message per BA repo whose stories are covered by `-test` docs of
    more than one tester repo (spec D1: one tester repo per BA repo)."""
    ba_of = _ba_repo_of(hub)
    testers: dict[str, set[str]] = {}
    for tester, stories in covered.items():
        for story in stories:
            if (ba := ba_of.get(story)) is not None:
                testers.setdefault(ba, set()).add(tester)
    return [
        f"BA repo {ba} is covered by more than one tester repo "
        f"({', '.join(sorted(t))}) — keep one tester repo per BA repo"
        for ba, t in sorted(testers.items())
        if len(t) > 1
    ]
