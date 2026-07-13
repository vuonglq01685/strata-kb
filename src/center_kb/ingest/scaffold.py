from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from center_kb import models
from center_kb.ingest.sectioner import HeadingConfig, SectionUnit
from center_kb.mdutils import count_tokens, slugify

__all__ = ["ScaffoldReport", "chapter_stem", "scaffold_doc", "slugify"]


def chapter_stem(chapter: str, title: str) -> str:
    prefix = f"ch{chapter}" if chapter and chapter[0].isdigit() else chapter
    slug = slugify(title)[:40].rstrip("-")
    return f"{prefix}-{slug}" if slug and slug != prefix else prefix


@dataclass
class ScaffoldReport:
    doc_id: str
    files: list[str]
    n_sections: int


def scaffold_doc(
    units: list[SectionUnit],
    *,
    doc_id: str,
    title: str,
    tags: list[str],
    revision: str,
    source_path: Path | None,
    kb_dir: Path,
    chapters: set[str] | None = None,
    heading_config: HeadingConfig | None = None,
    part_titles: dict[str, str] | None = None,
    used_bookmarks: bool = False,
) -> ScaffoldReport:
    if chapters is not None:
        units = [u for u in units if u.chapter in chapters]

    doc_dir = kb_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    for stale in doc_dir.glob("*.md"):  # re-ingest may change the file split
        stale.unlink()

    groups: dict[str, list[SectionUnit]] = {}
    for unit in units:
        groups.setdefault(unit.chapter, []).append(unit)

    sections: list[models.SectionEntry] = []
    files: list[str] = []
    for chapter, chapter_units in groups.items():
        head = next((u for u in chapter_units if u.id == chapter), chapter_units[0])
        stem_title = (part_titles or {}).get(chapter) or head.title
        stem = chapter_stem(chapter, stem_title)

        l3_lines: list[str] = []
        l2_lines: list[str] = []
        for unit in chapter_units:
            l3_lines += [f"## {unit.id} {unit.title}", "", unit.body_md, ""]
            l2_lines += [
                f"## {unit.id} {unit.title}",
                "",
                f"<!-- TODO:summarize {unit.id} -->",
                "",
            ]
            for table in unit.tables:
                l2_lines += [table, ""]
            sections.append(
                models.SectionEntry(
                    id=unit.id,
                    title=unit.title,
                    file=stem,
                    tokens=models.SectionTokens(l3=count_tokens(unit.body_md)),
                )
            )

        (doc_dir / f"{stem}.raw.md").write_text(
            "\n".join(l3_lines), encoding="utf-8", newline="\n"
        )
        (doc_dir / f"{stem}.md").write_text(
            "\n".join(l2_lines), encoding="utf-8", newline="\n"
        )
        files += [f"{stem}.md", f"{stem}.raw.md"]

    sha = (
        hashlib.sha256(source_path.read_bytes()).hexdigest()
        if source_path and source_path.exists()
        else ""
    )
    cfg = heading_config or HeadingConfig()
    manifest = models.Manifest(
        id=doc_id,
        title=title,
        revision=revision,
        ingested=date.today(),
        source_sha256=sha,
        sections=sections,
        ingest=models.IngestConfig(
            chapter_pattern=cfg.chapter_pattern,
            appendix_pattern=cfg.appendix_pattern,
            attachment_pattern=cfg.attachment_pattern,
            used_bookmarks=used_bookmarks,
        ),
    )
    models.save_yaml_model(doc_dir / "_manifest.yaml", manifest)

    index_path = kb_dir / "index.yaml"
    index = (
        models.load_yaml_model(index_path, models.KBIndex)
        if index_path.exists()
        else models.KBIndex()
    )
    kept = [d for d in index.docs if d.id != doc_id]
    entry = models.IndexEntry(id=doc_id, title=title, revision=revision, tags=tags)
    models.save_yaml_model(index_path, models.KBIndex(docs=kept + [entry]))

    return ScaffoldReport(doc_id=doc_id, files=files, n_sections=len(sections))
