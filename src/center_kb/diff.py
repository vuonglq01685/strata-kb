from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from center_kb import gitio, models
from center_kb.mdutils import slice_section


@dataclass
class SectionChange:
    section_id: str
    title: str
    summary_changed: bool = False
    prose_changed: bool = False
    content_changed: bool = False


@dataclass
class DiffReport:
    doc_id: str
    against: str
    added: list[SectionChange] = field(default_factory=list)
    removed: list[SectionChange] = field(default_factory=list)
    changed: list[SectionChange] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def _raw_section(text: str | None, section_id: str) -> str | None:
    if text is None:
        return None
    return slice_section(text, section_id)


def _level_changed(
    root: Path,
    against: str,
    doc_dir: Path,
    sec_id: str,
    new_file: str,
    old_file: str,
    suffix: str,
    cache_new: dict[str, str | None],
    cache_old: dict[str, str | None],
) -> bool:
    """Compare one section's slice of a level file (worktree vs `against`)."""
    if new_file not in cache_new:
        path = doc_dir / f"{new_file}{suffix}"
        cache_new[new_file] = (
            path.read_text(encoding="utf-8") if path.exists() else None
        )
    new_text = _raw_section(cache_new[new_file], sec_id)
    if old_file not in cache_old:
        cache_old[old_file] = gitio.read_at(
            root, against, doc_dir / f"{old_file}{suffix}"
        )
    old_text = _raw_section(cache_old[old_file], sec_id)
    return (new_text or "").strip() != (old_text or "").strip()


def diff_doc(kb_dir: Path, doc_id: str, against: str = "HEAD") -> DiffReport:
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    doc_dir = kb_abs / doc_id

    new_path = doc_dir / "_manifest.yaml"
    if not new_path.exists():
        raise ValueError(f"doc '{doc_id}' is not in the worktree ({new_path})")
    new = models.load_yaml_model(new_path, models.Manifest)

    old_text = gitio.read_at(root, against, new_path)
    if old_text is None:
        raise ValueError(f"doc '{doc_id}' does not exist at rev '{against}'")
    old = models.Manifest.model_validate(yaml.safe_load(old_text) or {})

    old_by_id = {s.id: s for s in old.sections}
    new_by_id = {s.id: s for s in new.sections}
    report = DiffReport(doc_id=doc_id, against=against)

    report.added = [
        SectionChange(s.id, s.title) for s in new.sections if s.id not in old_by_id
    ]
    report.removed = [
        SectionChange(s.id, s.title) for s in old.sections if s.id not in new_by_id
    ]

    raw_cache_old: dict[str, str | None] = {}
    raw_cache_new: dict[str, str | None] = {}
    prose_cache_old: dict[str, str | None] = {}
    prose_cache_new: dict[str, str | None] = {}
    for sec in new.sections:
        old_sec = old_by_id.get(sec.id)
        if old_sec is None:
            continue
        summary_changed = old_sec.summary.strip() != sec.summary.strip()
        prose_changed = _level_changed(
            root, against, doc_dir, sec.id, sec.file, old_sec.file,
            ".md", prose_cache_new, prose_cache_old,
        )
        content_changed = _level_changed(
            root, against, doc_dir, sec.id, sec.file, old_sec.file,
            ".raw.md", raw_cache_new, raw_cache_old,
        )
        if summary_changed or prose_changed or content_changed:
            report.changed.append(
                SectionChange(
                    sec.id,
                    sec.title,
                    summary_changed=summary_changed,
                    prose_changed=prose_changed,
                    content_changed=content_changed,
                )
            )
    return report


def render_diff(report: DiffReport) -> str:
    if not report.has_changes:
        return f"{report.doc_id}: no changes since {report.against}"
    lines = [f"{report.doc_id} — changes since {report.against}:"]
    for c in report.added:
        lines.append(f"+ §{c.section_id} {c.title}")
    for c in report.removed:
        lines.append(f"- §{c.section_id} {c.title}")
    for c in report.changed:
        kinds = [
            k
            for k, on in (
                ("summary", c.summary_changed),
                ("prose", c.prose_changed),
                ("content", c.content_changed),
            )
            if on
        ]
        lines.append(f"~ §{c.section_id} {c.title} ({', '.join(kinds)})")
    return "\n".join(lines)
