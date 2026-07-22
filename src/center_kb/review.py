from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from center_kb import gitio, models
from center_kb.diff import diff_doc


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

    report = ApproveReport(doc_id=doc_id)
    # Iterate sections directly rather than a {id: section} dict: section ids
    # are NOT unique (regulatory docs restart §-numbering inside each part), so
    # keying on id alone collapses every duplicate to one entry and strands the
    # rest in `summarized` forever. `wanted=None` means "every section".
    if section_ids is None:
        wanted: set[str] | None = None
    else:
        wanted = set(section_ids)
        present = {s.id for s in manifest.sections}
        report.missing = [
            sid for sid in dict.fromkeys(section_ids) if sid not in present
        ]

    for sec in manifest.sections:
        if wanted is not None and sec.id not in wanted:
            continue
        if sec.status == "summarized":
            sec.status = "reviewed"
            report.flipped.append(sec.id)
        elif sec.status == "pending":
            report.skipped_pending.append(sec.id)

    if report.flipped:
        models.save_yaml_model(manifest_path, manifest)
    return report


def changed_section_ids(kb_dir: Path, doc_id: str, against: str) -> list[str] | None:
    """Ids of sections added or changed (summary/prose/content) vs `against`.

    None means the doc does not exist at `against` at all (brand-new doc) —
    the caller should treat every section as changed.
    """
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    if gitio.read_at(root, against, kb_abs / doc_id / "_manifest.yaml") is None:
        return None
    report = diff_doc(kb_dir, doc_id, against=against)
    return [c.section_id for c in report.added] + [
        c.section_id for c in report.changed
    ]


def approve_all_changed(
    kb_dir: Path, against: str, doc_id: str | None = None
) -> list[ApproveReport]:
    """Approve the sections that differ from `against` (CI mode).

    doc_id=None scans every doc in index.yaml; docs whose manifest is
    missing in the worktree are skipped. Docs with no changes produce no
    report. Raises GitError on a bad rev, ValueError on a missing doc/index.
    """
    if doc_id is not None:
        doc_ids = [doc_id]
    else:
        index_path = kb_dir / "index.yaml"
        if not index_path.exists():
            raise ValueError(f"KB index not found ({index_path})")
        index = models.load_yaml_model(index_path, models.KBIndex)
        doc_ids = [
            e.id for e in index.docs if (kb_dir / e.id / "_manifest.yaml").exists()
        ]

    reports: list[ApproveReport] = []
    for did in doc_ids:
        changed = changed_section_ids(kb_dir, did, against)
        if changed is not None and not changed:
            continue  # doc untouched since `against`
        reports.append(approve_sections(kb_dir, did, changed))
    return reports
