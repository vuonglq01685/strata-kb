from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from aero_kb import models


@dataclass
class ApproveReport:
    doc_id: str
    flipped: list[str] = field(default_factory=list)
    skipped_pending: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def approve_sections(
    kb_dir: Path, doc_id: str, section_ids: list[str] | None = None
) -> ApproveReport:
    """Flip status summarized → reviewed in <doc>/_manifest.yaml.

    section_ids=None targets every section of the doc. `pending` sections
    are skipped and reported (cannot approve what isn't summarized yet);
    `reviewed` sections are left untouched, so re-running is safe.
    """
    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        raise ValueError(f"doc '{doc_id}' is not in the worktree ({manifest_path})")
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    by_id = {s.id: s for s in manifest.sections}

    report = ApproveReport(doc_id=doc_id)
    if section_ids is None:
        targets = [s.id for s in manifest.sections]
    else:
        report.missing = [sid for sid in section_ids if sid not in by_id]
        targets = [sid for sid in section_ids if sid in by_id]

    for sid in targets:
        sec = by_id[sid]
        if sec.status == "summarized":
            sec.status = "reviewed"
            report.flipped.append(sid)
        elif sec.status == "pending":
            report.skipped_pending.append(sid)

    if report.flipped:
        models.save_yaml_model(manifest_path, manifest)
    return report
