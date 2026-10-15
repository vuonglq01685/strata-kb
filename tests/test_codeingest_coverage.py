"""Coverage rows: merge rule, deterministic rendering, and core.run() wiring."""

from pathlib import Path

from strata_kb.codeingest import core
from strata_kb.codeingest.extractors import _coverage
from strata_kb.codeingest.extractors._coverage import (
    CoverageRow,
    merge_rows,
    render_section,
)
from strata_kb.codeingest.types import ExtractResult


def test_merge_worst_status_wins():
    rows = [
        CoverageRow("routes", "apps/api", "NestJS", "complete"),
        CoverageRow("routes", "apps/api", "NestJS", "partial", "apps/api/src/x.ts:12"),
    ]
    assert merge_rows(rows) == [
        CoverageRow("routes", "apps/api", "NestJS", "partial", "apps/api/src/x.ts:12")
    ]


def test_merge_not_scanned_beats_partial():
    rows = [
        CoverageRow("pages", ".", "Next.js", "partial", "a"),
        CoverageRow("pages", ".", "Next.js", "not scanned", "b"),
    ]
    (row,) = merge_rows(rows)
    assert row.status == "not scanned"
    assert row.detail == "a; b"


def test_merge_details_sorted_deduped_and_not_truncated():
    rows = [
        CoverageRow("files", ".", "python", "partial", f"f{n:02d}.py:1")
        for n in range(25)
    ] + [CoverageRow("files", ".", "python", "partial", "f00.py:1")]
    (row,) = merge_rows(rows)
    assert row.detail.split("; ") == [f"f{n:02d}.py:1" for n in range(25)]


def test_constants():
    assert _coverage.NOT_INSTALLED == "not scanned — install strata-kb[code]"
    assert (
        _coverage.JOBS_DETAIL == "jobs outside framework schedulers are not detectable"
    )


def test_render_is_deterministic_and_sorted():
    rows = [
        CoverageRow("routes", "b", "NestJS", "complete"),
        CoverageRow("jobs", ".", "-", "partial", _coverage.JOBS_DETAIL),
        CoverageRow("routes", "a", "Express", "partial", "a/x.ts:3"),
        CoverageRow("routes", "a", "Express", "partial", "a/y.ts:4"),
    ]
    shuffled = rows[::-1]
    first = render_section(merge_rows(rows))
    second = render_section(merge_rows(shuffled))
    assert first == second
    assert first.id == "struct.coverage"
    assert first.group == "structure"
    assert first.title == "Coverage"
    assert first.summary
    assert "| Area | Scope | Framework/language | Status | Detail |" in first.l2_md
    assert first.l2_md.index("| jobs |") < first.l2_md.index("| routes | a |")
    assert first.l2_md.index("| routes | a |") < first.l2_md.index("| routes | b |")
    assert first.l3_md.startswith("```\n") and first.l3_md.endswith("```\n")


def test_render_l2_caps_at_twenty_sites_l3_does_not():
    rows = [
        CoverageRow("files", ".", "python", "partial", f"f{n:02d}.py:1")
        for n in range(25)
    ]
    sec = render_section(merge_rows(rows))
    assert "+5 more" in sec.l2_md and "f20.py:1" not in sec.l2_md
    assert "f24.py:1" in sec.l3_md and "more" not in sec.l3_md


class _RowExtractor:
    name = "routes"

    def detect(self, root: Path) -> bool:
        return True

    def extract(self, root: Path, opts) -> ExtractResult:
        return ExtractResult(
            coverage=[CoverageRow("routes", ".", "Express", "partial", "x.ts:1")]
        )


class _SvcExtractor:
    name = "stub"

    def detect(self, root: Path) -> bool:
        return True

    def extract(self, root: Path, opts) -> ExtractResult:
        return ExtractResult(
            sections=[
                core.CodeSection(
                    id="svc.a",
                    title="a",
                    summary="Service a.",
                    group="services",
                    l2_md="A.\n",
                    l3_md="```\na\n```\n",
                )
            ]
        )


def _opts(tmp_path: Path):
    return core.CodeIngestOptions(
        repo_root=tmp_path,
        kb_dir=tmp_path / ".kb",
        doc_id="demo-code",
        repo_id="demo",
    )


def test_core_emits_struct_coverage_from_extractor_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_SvcExtractor(), _RowExtractor()])
    core.run(_opts(tmp_path))
    text = (tmp_path / ".kb" / "demo-code" / "structure.md").read_text()
    assert "## struct.coverage Coverage" in text
    assert "| routes | . | Express | partial | x.ts:1 |" in text


def test_coverage_rows_alone_do_not_satisfy_zero_detection(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_RowExtractor()])
    import pytest

    with pytest.raises(core.CodeIngestError):
        core.run(_opts(tmp_path))


def test_no_rows_no_coverage_section(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_SvcExtractor()])
    core.run(_opts(tmp_path))
    assert not (tmp_path / ".kb" / "demo-code" / "structure.md").exists()


def test_generated_document_with_coverage_builds_clean(tmp_path, monkeypatch):
    from strata_kb.build import build_kb

    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_SvcExtractor(), _RowExtractor()])
    core.run(_opts(tmp_path))
    report = build_kb(tmp_path / ".kb")
    assert report.errors == [], report.errors
    assert report.ok


def test_prose_details_sort_first_and_are_never_capped_or_hidden():
    rows = [
        CoverageRow("jobs", ".", "-", "partial", f"a/f{n:02d}.ts:1") for n in range(25)
    ] + [CoverageRow("jobs", ".", "-", "partial", _coverage.JOBS_DETAIL)]
    (row,) = merge_rows(rows)
    assert row.detail.startswith(f"{_coverage.JOBS_DETAIL}; a/f00.ts:1")
    l2 = render_section([row]).l2_md
    assert _coverage.JOBS_DETAIL in l2
    assert "a/f19.ts:1" in l2 and "a/f20.ts:1" not in l2
    assert "+5 more" in l2
