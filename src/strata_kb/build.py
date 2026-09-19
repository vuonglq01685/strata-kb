from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from center_kb import models, quality
from center_kb.mdutils import (
    count_tokens,
    extract_tables,
    heading_occurrences,
    normalize_table,
    orphan_heading_ids,
    slice_section,
)

TODO_MARKER = "<!-- TODO:summarize"


@dataclass
class BuildReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quality: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def build_kb(
    kb_dir: Path,
    allow_pending: bool = False,
    strict: bool = False,
    write_tokens: bool = True,
) -> BuildReport:
    report = BuildReport()
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        report.errors.append(f"not found: {index_path}")
        return report
    index = models.load_yaml_model(index_path, models.KBIndex)
    for entry in index.docs:
        _build_doc(kb_dir, entry, report, allow_pending, strict, write_tokens)
    l0_tokens = count_tokens(index_path.read_text(encoding="utf-8"))
    if l0_tokens > 1000:
        report.warnings.append(
            f"L0 index.yaml = {l0_tokens} tokens (> 1000, review the spec target)"
        )
    return report


def _build_doc(
    kb_dir: Path,
    entry: models.IndexEntry,
    report: BuildReport,
    allow_pending: bool,
    strict: bool,
    write_tokens: bool = True,
) -> None:
    manifest_path = kb_dir / entry.id / "_manifest.yaml"
    if not manifest_path.exists():
        report.errors.append(f"{entry.id}: missing _manifest.yaml")
        return
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    errors_before = len(report.errors)
    _add_findings(report, quality.check_doc(entry), strict)
    file_cache: dict[str, str] = {}
    _check_orphan_headings(report, kb_dir, entry.id, manifest, file_cache)
    occurrences = heading_occurrences(manifest.sections)
    tokens: dict[int, models.SectionTokens] = {}
    for row, sec in enumerate(manifest.sections):
        l2_text = _read_cached(kb_dir / entry.id / f"{sec.file}.md", file_cache)
        l3_text = _read_cached(kb_dir / entry.id / f"{sec.file}.raw.md", file_cache)
        ref = f"{entry.id} §{sec.id}"
        occ = occurrences[row]
        l2_slice = slice_section(l2_text, sec.id, occurrence=occ) if l2_text else None
        l3_slice = slice_section(l3_text, sec.id, occurrence=occ) if l3_text else None
        if l2_slice is None or l3_slice is None:
            report.errors.append(f"{ref}: section not found in the L2/L3 file")
            continue
        is_pending = TODO_MARKER in l2_slice or not sec.summary.strip()
        if is_pending:
            msg = f"{ref}: still has a TODO marker or an empty summary"
            (report.warnings if allow_pending else report.errors).append(msg)
        _check_tables(report.errors, ref, l2_slice, l3_slice)
        _check_hashes(report.errors, ref, sec, l2_slice, l3_slice)
        if not is_pending:
            _add_findings(report, quality.check_section(ref, sec, l2_slice, l3_slice), strict)
        tokens[row] = models.SectionTokens(
            l2=count_tokens(l2_slice), l3=count_tokens(l3_slice)
        )
    if len(report.errors) != errors_before:
        return  # a validate command must not persist state it just rejected
    if not write_tokens:
        return  # validation-only build (e.g. the approval gate): never dirty the tree
    for row, tk in tokens.items():
        manifest.sections[row].tokens = tk
    models.save_yaml_model(manifest_path, manifest)


def _add_findings(report: BuildReport, findings: list[quality.Finding], strict: bool) -> None:
    for f in findings:
        if f.level == "error" or strict:
            report.errors.append(f.text)
        else:
            report.quality.append(f.text)


def _check_hashes(
    errors: list[str], ref: str, sec: models.SectionEntry, l2_slice: str, l3_slice: str
) -> None:
    if sec.l3_sha256 and sec.l3_sha256 != quality.digest(l3_slice):
        errors.append(
            f"{ref}: L3 changed since it was summarized; run "
            f"kb summarize --redo <doc> --section {sec.id}"
        )
    if sec.reviewed is not None and sec.reviewed.l2_sha256 != quality.digest(l2_slice):
        errors.append(f"{ref}: L2 changed after review; approve again or redo the section")


def _check_orphan_headings(
    report: BuildReport, kb_dir: Path, doc_id: str, manifest: models.Manifest,
    cache: dict[str, str],
) -> None:
    """Every real `## <id> …` heading in a doc's L2/L3 files must be a known
    manifest id (Ruling R16) -- see `mdutils.orphan_heading_ids` for the
    shared per-file predicate (also used by doctor's `_check_doc`, and it
    must stay the single source of the fence/title-less exemptions)."""
    ids = {s.id for s in manifest.sections}
    for stem in sorted({s.file for s in manifest.sections}):
        for suffix in (".md", ".raw.md"):
            text = _read_cached(kb_dir / doc_id / f"{stem}{suffix}", cache)
            for sid in orphan_heading_ids(text, suffix, ids):
                report.errors.append(
                    f"{doc_id}: heading '{sid}' in {stem}{suffix} is not in the manifest"
                )


def _check_tables(errors: list[str], ref: str, l2_slice: str, l3_slice: str) -> None:
    """L2 tables must be exactly the L3 tables: same multiset, same order."""
    l2 = [normalize_table(t) for t in extract_tables(l2_slice)]
    l3 = [normalize_table(t) for t in extract_tables(l3_slice)]
    if not l3:
        # L3 uses no markdown tables at all (e.g. a code-ingested section
        # whose verbatim form is a fenced code block) -- there is no
        # source-of-truth table to check L2 against, so an L2 table here
        # is a rendering choice, not a copy that could have drifted.
        return
    if l2 == l3:
        return
    c2, c3 = Counter(l2), Counter(l3)
    if c2 == c3:
        errors.append(f"{ref}: tables reordered within the section (table integrity fail)")
        return
    missing = sum((c3 - c2).values())
    surplus = c2 - c3
    extra = sum(n for t, n in surplus.items() if t not in c3)
    dup = sum(n for t, n in surplus.items() if t in c3)
    parts = []
    if missing:
        parts.append(f"{missing} L3 table(s) missing or altered in L2")
    if extra:
        parts.append(f"{extra} table(s) in L2 that are not in L3")
    if dup:
        parts.append(f"{dup} table(s) duplicated in L2")
    errors.append(f"{ref}: {'; '.join(parts)} (table integrity fail)")


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
