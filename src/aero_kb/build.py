from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from aero_kb import models
from aero_kb.mdutils import (
    count_tokens,
    extract_tables,
    normalize_table,
    slice_section,
)

TODO_MARKER = "<!-- TODO:summarize"


@dataclass
class BuildReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def build_kb(kb_dir: Path, allow_pending: bool = False) -> BuildReport:
    report = BuildReport()
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        report.errors.append(f"not found: {index_path}")
        return report
    index = models.load_yaml_model(index_path, models.KBIndex)

    for entry in index.docs:
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            report.errors.append(f"{entry.id}: missing _manifest.yaml")
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        file_cache: dict[str, str] = {}

        for sec in manifest.sections:
            l2_text = _read_cached(kb_dir / entry.id / f"{sec.file}.md", file_cache)
            l3_text = _read_cached(
                kb_dir / entry.id / f"{sec.file}.raw.md", file_cache
            )
            ref = f"{entry.id} §{sec.id}"

            l2_slice = slice_section(l2_text, sec.id) if l2_text else None
            l3_slice = slice_section(l3_text, sec.id) if l3_text else None
            if l2_slice is None or l3_slice is None:
                report.errors.append(f"{ref}: section not found in the L2/L3 file")
                continue

            is_pending = TODO_MARKER in l2_slice or not sec.summary.strip()
            if is_pending:
                msg = f"{ref}: still has a TODO marker or an empty summary"
                if allow_pending:
                    report.warnings.append(msg)
                else:
                    report.errors.append(msg)

            l2_tables = {normalize_table(t) for t in extract_tables(l2_slice)}
            for table in extract_tables(l3_slice):
                if normalize_table(table) not in l2_tables:
                    report.errors.append(
                        f"{ref}: table in L3 doesn't match L2 verbatim "
                        f"(table integrity fail)"
                    )
                    break

            sec.tokens = models.SectionTokens(
                l2=count_tokens(l2_slice), l3=count_tokens(l3_slice)
            )

        models.save_yaml_model(manifest_path, manifest)

    l0_tokens = count_tokens(index_path.read_text(encoding="utf-8"))
    if l0_tokens > 1000:
        report.warnings.append(
            f"L0 index.yaml = {l0_tokens} tokens (> 1000, review the spec target)"
        )
    return report


def _read_cached(path: Path, cache: dict[str, str]) -> str:
    key = str(path)
    if key not in cache:
        cache[key] = path.read_text(encoding="utf-8") if path.exists() else ""
    return cache[key]


@dataclass
class DocStats:
    doc_id: str
    n_sections: int
    l1_tokens: int
    l2_tokens: int
    l3_tokens: int

    @property
    def saving_pct(self) -> float:
        if self.l3_tokens == 0:
            return 0.0
        return 100.0 * (1 - self.l2_tokens / self.l3_tokens)


def kb_stats(kb_dir: Path) -> tuple[int, list[DocStats]]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return 0, []
    l0_tokens = count_tokens(index_path.read_text(encoding="utf-8"))
    index = models.load_yaml_model(index_path, models.KBIndex)
    stats: list[DocStats] = []
    for entry in index.docs:
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        stats.append(
            DocStats(
                doc_id=entry.id,
                n_sections=len(manifest.sections),
                l1_tokens=count_tokens(manifest_path.read_text(encoding="utf-8")),
                l2_tokens=sum(s.tokens.l2 for s in manifest.sections),
                l3_tokens=sum(s.tokens.l3 for s in manifest.sections),
            )
        )
    return l0_tokens, stats
