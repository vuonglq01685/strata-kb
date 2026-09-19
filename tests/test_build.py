from pathlib import Path

from strata_kb import models
from strata_kb.build import build_kb


def test_build_ok_on_valid_kb(fixture_kb: Path):
    report = build_kb(fixture_kb)
    assert report.ok, report.errors
    manifest = models.load_yaml_model(
        fixture_kb / "demo-doc" / "_manifest.yaml", models.Manifest
    )
    sec = manifest.sections[0]
    assert sec.tokens.l2 > 0
    assert sec.tokens.l3 > sec.tokens.l2
    # pins the tokens[row] -> manifest.sections[row] mapping: row 1 (not
    # just row 0) must also have received its own real, non-zero counts.
    sec2 = manifest.sections[1]
    assert sec2.tokens.l2 > 0
    assert sec2.tokens.l3 > 0


def test_build_write_tokens_false_never_persists(fixture_kb: Path):
    """R8: a validation-only build (e.g. the approval gate) must not dirty
    the tree — not even to write real token counts into a passing manifest."""
    manifest_path = fixture_kb / "demo-doc" / "_manifest.yaml"
    before = manifest_path.read_bytes()
    before_tokens = models.load_yaml_model(manifest_path, models.Manifest).sections[0].tokens
    report = build_kb(fixture_kb, write_tokens=False)
    assert report.ok, report.errors
    assert manifest_path.read_bytes() == before
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    assert manifest.sections[0].tokens == before_tokens


def test_build_fails_on_todo_marker(fixture_kb: Path):
    l2_path = fixture_kb / "demo-doc" / "ch1-records.md"
    text = l2_path.read_text().replace(
        "Condensed: airspace record structure with designation and type fields.",
        "<!-- TODO:summarize 1.1 -->",
    )
    l2_path.write_text(text)
    report = build_kb(fixture_kb)
    assert not report.ok
    assert any("TODO" in e for e in report.errors)


def test_build_allow_pending_downgrades_to_warning(fixture_kb: Path):
    l2_path = fixture_kb / "demo-doc" / "ch1-records.md"
    text = l2_path.read_text().replace(
        "Condensed: airspace record structure with designation and type fields.",
        "<!-- TODO:summarize 1.1 -->",
    )
    l2_path.write_text(text)
    report = build_kb(fixture_kb, allow_pending=True)
    assert report.ok
    assert any("TODO" in w for w in report.warnings)


def test_build_fails_on_empty_summary(fixture_kb: Path):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(mpath, models.Manifest)
    manifest.sections[0].summary = ""
    models.save_yaml_model(mpath, manifest)
    report = build_kb(fixture_kb)
    assert not report.ok


def test_build_fails_when_l3_table_missing_from_l2(fixture_kb: Path):
    l2_path = fixture_kb / "demo-doc" / "ch1-records.md"
    text = l2_path.read_text().replace("| P    | Prohibited |", "| P    | Permitted |")
    # edit the table in L2 -> differs from L3 -> table integrity fails
    l2_path.write_text(text.replace("| P | Prohibited |", "| P | Permitted |"))
    report = build_kb(fixture_kb)
    assert not report.ok
    assert any("table" in e.lower() for e in report.errors)


def test_build_fails_when_section_missing_in_l2(fixture_kb: Path):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(mpath, models.Manifest)
    manifest.sections.append(
        models.SectionEntry(
            id="1.9",
            title="Ghost Section",
            summary="x",
            status="summarized",
            file="ch1-records",
        )
    )
    models.save_yaml_model(mpath, manifest)
    report = build_kb(fixture_kb)
    assert not report.ok


import pytest

from tests.conftest import TABLE

EXTRA_TABLE = "| X | Y |\n|---|---|\n| 1 | 2 |"


def _l2(fixture_kb):
    return fixture_kb / "demo-doc" / "ch1-records.md"


def _l3(fixture_kb):
    return fixture_kb / "demo-doc" / "ch1-records.raw.md"


def _errors(fixture_kb, **kw):
    return build_kb(fixture_kb, **kw).errors


def test_build_rejects_extra_table_in_l2(fixture_kb):          # case a
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(TABLE, TABLE + "\n\n" + EXTRA_TABLE), encoding="utf-8")
    errs = _errors(fixture_kb)
    assert any("not in L3" in e and "table" in e for e in errs)


def test_build_rejects_duplicated_table_in_l2(fixture_kb):     # case b
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(TABLE, TABLE + "\n\n" + TABLE), encoding="utf-8")
    assert any("duplicated" in e for e in _errors(fixture_kb))


def test_build_rejects_missing_single_row_table(fixture_kb):   # cases d, s
    one_row = "| Only | Header |"
    for p in (_l2(fixture_kb), _l3(fixture_kb)):
        p.write_text(p.read_text(encoding="utf-8").replace("## 1.2 Airway Records", f"{one_row}\n\n## 1.2 Airway Records"), encoding="utf-8")
    assert build_kb(fixture_kb).ok
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(one_row, "| Rewritten | Header |"), encoding="utf-8")
    assert any("missing or altered" in e for e in _errors(fixture_kb))


def test_build_rejects_tables_reordered_within_section(fixture_kb):   # case q
    for p in (_l2(fixture_kb), _l3(fixture_kb)):
        p.write_text(p.read_text(encoding="utf-8").replace(TABLE, TABLE + "\n\n" + EXTRA_TABLE), encoding="utf-8")
    assert build_kb(fixture_kb).ok
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(TABLE + "\n\n" + EXTRA_TABLE, EXTRA_TABLE + "\n\n" + TABLE), encoding="utf-8")
    assert any("reordered" in e for e in _errors(fixture_kb))


def test_build_rejects_orphan_heading(fixture_kb):             # case m
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8") + "\n## 1.9 Ghost\n\nInvented.\n", encoding="utf-8")
    assert any("heading '1.9'" in e and "not in the manifest" in e for e in _errors(fixture_kb))


def test_build_allows_titleless_subheading_in_l2(fixture_kb):
    """R16: a human's own free-form subheading in L2 ('## Ownership' --
    a single token, no title, codeingest-shaped) is not a scaffold
    section break and must not be flagged as an orphan heading."""
    p = _l2(fixture_kb)
    p.write_text(
        p.read_text(encoding="utf-8") + "\n## Ownership\n\nTeam notes.\n",
        encoding="utf-8",
    )
    errs = _errors(fixture_kb)
    assert not any("Ownership" in e for e in errs)


def test_build_allows_fenced_heading_line_in_l3(fixture_kb):
    """R16: a '## ' line quoted inside a fenced code block in .raw.md
    (e.g. codeingest embedding a source file's own Markdown heading) is
    never a document heading, in either fence style."""
    p = _l3(fixture_kb)
    p.write_text(
        p.read_text(encoding="utf-8") + "\n```text\n## deploy\n```\n",
        encoding="utf-8",
    )
    errs = _errors(fixture_kb)
    assert not any("deploy" in e for e in errs)


def test_build_still_rejects_real_orphan_heading_in_both_files(fixture_kb):
    """R16: a real, TITLED heading absent from the manifest is still an
    error in both the L2 .md and the L3 .raw.md -- the fence-aware and
    title-less-subheading exceptions must not swallow a genuine orphan."""
    for p in (_l2(fixture_kb), _l3(fixture_kb)):
        p.write_text(
            p.read_text(encoding="utf-8") + "\n## 9.9 Lost\n\nInvented.\n",
            encoding="utf-8",
        )
    errs = _errors(fixture_kb)
    assert any("heading '9.9' in ch1-records.md" in e for e in errs)
    assert any("heading '9.9' in ch1-records.raw.md" in e for e in errs)


def test_build_does_not_write_manifest_on_failure(fixture_kb):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    before = mpath.read_text(encoding="utf-8")
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace("| P | Prohibited |", "| P | Permitted |"), encoding="utf-8")
    assert not build_kb(fixture_kb).ok
    assert mpath.read_text(encoding="utf-8") == before        # tokens not persisted


@pytest.mark.parametrize("mutation", [
    ("| P | Prohibited |", "| P    | Prohibited |"),   # e2/e3 whitespace
    ("|---|---|", "|:--|--:|"),                          # e1 alignment
])
def test_build_folds_harmless_table_normalisation(fixture_kb, mutation):
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(*mutation), encoding="utf-8")
    assert build_kb(fixture_kb).ok


def test_build_allows_l2_table_when_l3_has_no_tables(fixture_kb):
    """R6 guard, direction 1: L3 has no table at all for this section (§1.2,
    table-free in both files) -- an L2 table added on top of it must not be
    flagged, since there is no L3 table to have diverged from."""
    from strata_kb.mdutils import extract_tables, slice_section

    l3_text = _l3(fixture_kb).read_text(encoding="utf-8")
    l3_slice = slice_section(l3_text, "1.2")
    assert extract_tables(l3_slice) == []  # non-vacuous: really no L3 table

    p = _l2(fixture_kb)
    p.write_text(
        p.read_text(encoding="utf-8").replace(
            "Condensed: airway record structure, route identifiers.",
            "Condensed: airway record structure, route identifiers.\n\n"
            + EXTRA_TABLE,
        ),
        encoding="utf-8",
    )
    errs = _errors(fixture_kb)
    assert not any("§1.2" in e for e in errs)


def test_build_rejects_l2_missing_the_l3_table(fixture_kb):
    """R6 guard, direction 2: L3 §1.1 has a table (non-empty), so deleting
    that table from L2 outright must still be caught -- pins that the guard
    is exactly 'L3 has zero tables', not 'either side is empty'."""
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(TABLE, ""), encoding="utf-8")
    errs = _errors(fixture_kb)
    assert any("§1.1" in e and "missing or altered in L2" in e for e in errs)


from strata_kb import quality

LONG = " ".join(f"Sentence number {i} explains the record layout in detail." for i in range(10))


def _make_long_l3(fixture_kb):
    """Turn §1.2 into a > 200-char prose section so ratio/overlap rules apply."""
    p = _l3(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(
        "Full raw text about airway records and route identifiers.", LONG), encoding="utf-8")


def test_quality_findings_are_warnings_by_default(fixture_kb):
    _make_long_l3(fixture_kb)
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(
        "Condensed: airway record structure, route identifiers.", LONG), encoding="utf-8")   # 1.0×
    report = build_kb(fixture_kb)
    assert report.ok
    assert any("§1.2" in q and "budget" in q and q.endswith("(quality)") for q in report.quality)


def test_quality_findings_are_errors_under_strict_and_block_the_write(fixture_kb):
    _make_long_l3(fixture_kb)
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(
        "Condensed: airway record structure, route identifiers.", LONG), encoding="utf-8")
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    before = mpath.read_text(encoding="utf-8")
    report = build_kb(fixture_kb, strict=True)
    assert not report.ok and any("(quality)" in e for e in report.errors)
    assert mpath.read_text(encoding="utf-8") == before


def test_pending_sections_are_not_quality_checked(fixture_kb):
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(
        "Condensed: airway record structure, route identifiers.", "<!-- TODO:summarize 1.2 -->"), encoding="utf-8")
    report = build_kb(fixture_kb, allow_pending=True, strict=True)
    assert not any("§1.2" in e and "(quality)" in e for e in report.errors)


def test_l3_hash_drift_is_an_error(fixture_kb):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    m.sections[1].l3_sha256 = quality.digest("something else")
    models.save_yaml_model(mpath, m)
    errs = build_kb(fixture_kb).errors
    assert any("§1.2" in e and "L3 changed since it was summarized" in e for e in errs)


def test_l3_hash_matching_is_silent(fixture_kb):
    from strata_kb.mdutils import slice_section
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    l3 = _l3(fixture_kb).read_text(encoding="utf-8")
    m.sections[1].l3_sha256 = quality.digest(slice_section(l3, "1.2"))
    models.save_yaml_model(mpath, m)
    assert build_kb(fixture_kb).ok


def test_reviewed_l2_hash_drift_is_an_error(fixture_kb):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    m.sections[0].status = "reviewed"
    m.sections[0].reviewed = models.ReviewRecord(by="x", at="t", l2_sha256=quality.digest("old"))
    models.save_yaml_model(mpath, m)
    assert any("L2 changed after review" in e for e in build_kb(fixture_kb).errors)


def test_reviewed_l2_hash_matching_is_silent(fixture_kb):
    from strata_kb.mdutils import slice_section

    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    l2_text = _l2(fixture_kb).read_text(encoding="utf-8")
    m.sections[0].status = "reviewed"
    m.sections[0].reviewed = models.ReviewRecord(
        by="x", at="t", l2_sha256=quality.digest(slice_section(l2_text, "1.1"))
    )
    models.save_yaml_model(mpath, m)
    report = build_kb(fixture_kb)
    assert report.ok, report.errors
    assert not any("L2 changed after review" in e for e in report.errors)


def test_empty_l0_summary_is_an_error(fixture_kb):
    ipath = fixture_kb / "index.yaml"
    idx = models.load_yaml_model(ipath, models.KBIndex)
    idx.docs[0].summary = ""
    models.save_yaml_model(ipath, idx)
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    before = mpath.read_text(encoding="utf-8")
    assert any("index.yaml summary is empty" in e for e in build_kb(fixture_kb).errors)
    # Ruling R2: check_doc's l0-empty error is added AFTER errors_before is
    # captured, so it must count as a new error for this doc and block the
    # manifest write (tokens must not get persisted alongside the error).
    assert mpath.read_text(encoding="utf-8") == before


def test_l3_hash_drift_respects_occurrence_for_duplicate_ids(fixture_kb):
    """Ruling R5: two manifest rows can share an id (duplicate '## 1.2 ...'
    headings in the same file). Each row's l3_sha256 must be checked against
    the slice at its OWN occurrence, not always occurrence 0 -- otherwise
    duplicate-id sections produce spurious drift errors."""
    from strata_kb.mdutils import heading_occurrences, slice_section

    dup_l2 = "\n\n## 1.2 Airway Records\n\nSecond airway paragraph, continued route identifiers.\n"
    dup_l3 = "\n\n## 1.2 Airway Records\n\nSecond full airway paragraph, continued route identifiers text.\n"
    _l2(fixture_kb).write_text(
        _l2(fixture_kb).read_text(encoding="utf-8") + dup_l2, encoding="utf-8"
    )
    _l3(fixture_kb).write_text(
        _l3(fixture_kb).read_text(encoding="utf-8") + dup_l3, encoding="utf-8"
    )

    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    m.sections.append(
        models.SectionEntry(
            id="1.2",
            title="Airway Records",
            summary="Second airway paragraph, continued route identifiers.",
            status="summarized",
            file="ch1-records",
        )
    )
    occ = heading_occurrences(m.sections)
    l3_text = _l3(fixture_kb).read_text(encoding="utf-8")
    for row, sec in enumerate(m.sections):
        if sec.id == "1.2":
            sec.l3_sha256 = quality.digest(slice_section(l3_text, "1.2", occurrence=occ[row]))
    models.save_yaml_model(mpath, m)

    # Correct per-occurrence hashes -> no drift error at all.
    report = build_kb(fixture_kb)
    assert report.ok, report.errors
    assert not any("L3 changed since it was summarized" in e for e in report.errors)

    # Swap row 2's (the appended duplicate's) hash for row 1's occurrence-0
    # digest -> row 2 (occurrence 1) now drifts; row 1 (occurrence 0) stays clean.
    m2 = models.load_yaml_model(mpath, models.Manifest)
    m2.sections[2].l3_sha256 = m2.sections[1].l3_sha256
    models.save_yaml_model(mpath, m2)
    errs = build_kb(fixture_kb).errors
    drift_errs = [e for e in errs if "L3 changed since it was summarized" in e]
    assert len(drift_errs) == 1
    assert "§1.2" in drift_errs[0]
