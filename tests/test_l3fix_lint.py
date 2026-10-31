from __future__ import annotations

from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.l3check import lint, spans
from strata_kb.l3check.spans import SpansFile, UnitSpan

runner = CliRunner()


def _ctx(sid, *, fallback=False, furniture=(), pdf_pages=None, page=1, end=1):
    span = UnitSpan(id=sid, file="ch1", chapter="1", page=page, end_page=end)
    return lint.UnitContext(span, fallback, list(furniture), pdf_pages or {})


def _rules(md, ctx):
    return [(i.rule, i.line) for i in lint.lint_unit(md, ctx)]


def test_clean_unit_has_no_issues():
    md = (
        "## 4.2 NGHỈ PHÉP NĂM\n\nĐoạn.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "### 4.2.1 X\n\n1. a\n   - b\n"
    )
    assert lint.lint_unit(md, _ctx("4.2")) == []


def test_r1_fallback():
    assert _rules("## 1 T\n\nx\n", _ctx("1", fallback=True)) == [("R1", 1)]


def test_r2_duplicate_id_in_file():
    raw = "## 1 A\n\nx\n\n## 1 B\n\ny\n"
    issues = lint.lint_file(raw, {"1": _ctx("1")})
    assert [(i.section, i.rule) for i in issues] == [("1", "R2")]


def test_lint_file_runs_each_unit():
    raw = "## 1 A\n\nx\n\n## 2 B\n\n#### y\n"
    issues = lint.lint_file(raw, {"1": _ctx("1"), "2": _ctx("2")})
    assert [(i.section, i.rule, i.line) for i in issues] == [("2", "R3", 3)]


def test_r3_heading_jump():
    assert _rules("## 4.2 A\n\n#### 4.2.1 B\n", _ctx("4.2")) == [("R3", 3)]


def test_r3_level_one_empty_and_deep():
    md = "## 1 A\n\n# top\n\n###\n\n### ok\n\n#### d\n\n##### e\n"
    assert _rules(md, _ctx("1")) == [("R3", 3), ("R3", 5), ("R3", 11)]


def test_r3_ignores_headings_inside_fence():
    assert _rules("## 1 A\n\n```\n# comment\n```\n", _ctx("1")) == []


def test_r4_duplicate_block():
    body = "## 1 T\n\nmột hai ba bốn năm sáu\n\nmột hai ba bốn năm sáu\n"
    assert _rules(body, _ctx("1")) == [("R4", 5)]


def test_r4_ignores_short_blocks():
    assert _rules("## 1 T\n\nmột hai\n\nmột hai\n", _ctx("1")) == []


def test_r5_furniture_line():
    ctx = _ctx("1", furniture=["Quy chế nhân sự · Trang 12/40"])
    md = "## 1 T\n\nQuy chế nhân sự · Trang 12/40\n"
    assert [i.rule for i in lint.lint_unit(md, ctx)] == ["R5"]


def test_r6_blockquote_and_deep_list():
    md = "## 1 T\n\n> quote\n\n- a\n      - deep\n\n~~~\ncode\n~~~\n"
    assert _rules(md, _ctx("1")) == [("R6", 3), ("R6", 6), ("R6", 8), ("R6", 10)]


def test_r6_tab_counts_as_four_spaces():
    assert _rules("## 1 T\n\n- a\n\t- b\n", _ctx("1")) == [("R6", 4)]


def test_r7_unclosed_fence():
    assert _rules("## 1 T\n\n```\ncode\n", _ctx("1")) == [("R7", 3)]


def test_r8_break():
    ctx = _ctx("1", pdf_pages={1: "the aircraft shall remain clear of"})
    issues = lint.lint_unit("## 1 T\n\nthe aircraft shall\n\nremain clear of\n", ctx)
    assert [(i.rule, i.line) for i in issues] == [("R8", 5)]
    assert len(issues[0].evidence) <= 80


def test_lint_doc_reads_chapter_files(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "ch1.raw.md").write_text("## 1 A\n\n#### x\n", encoding="utf-8")
    data = SpansFile(
        doc_id="d",
        units=[UnitSpan(id="1", file="ch1", chapter="1", page=1, end_page=1)],
        fallback_units=["1"],
    )
    issues = lint.lint_doc(tmp_path, "d", data, {}, {})
    assert [(i.rule, i.line) for i in issues] == [("R1", 1), ("R3", 3)]


def _setup(tmp_path, monkeypatch, body):
    kb, work = tmp_path / ".kb", tmp_path / ".kb-work"
    (kb / "d").mkdir(parents=True)
    (kb / "d" / "ch1.raw.md").write_text(body, encoding="utf-8")
    spans.save(
        work,
        "d",
        SpansFile(
            doc_id="d",
            units=[UnitSpan(id="1", file="ch1", chapter="1", page=1, end_page=1)],
            fallback_units=[],
        ),
    )
    monkeypatch.setattr(lint, "load_pdf_context", lambda *a: ({}, {}))
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    return [
        "l3",
        "lint",
        "d",
        "--pdf",
        str(pdf),
        "--kb-dir",
        str(kb),
        "--work-dir",
        str(work),
    ]


def test_cli_lint_exit_codes(tmp_path, monkeypatch):
    args = _setup(tmp_path, monkeypatch, "## 1 A\n\ntext.\n")
    ok = runner.invoke(app, args)
    assert ok.exit_code == 0 and "L3 lint: clean" in ok.output
    (tmp_path / ".kb" / "d" / "ch1.raw.md").write_text("## 1 A\n\n#### x\n")
    bad = runner.invoke(app, args)
    assert bad.exit_code == 1
    assert "§1 R3 line 3:" in bad.output and "1 issue(s)" in bad.output


def test_cli_lint_without_sections_json(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    result = runner.invoke(
        app,
        ["l3", "lint", "d", "--pdf", str(pdf), "--work-dir", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "no sections.json for d — re-ingest" in result.output


def test_unit_without_context_still_gets_pdf_free_rules():
    raw = "## 9 A\n\n#### x\n\n```\ncode\n"
    issues = lint.lint_file(raw, {})
    assert [(i.section, i.rule, i.line) for i in issues] == [
        ("9", "R3", 3),
        ("9", "R7", 5),
    ]


def test_text_before_first_unit_is_flagged():
    issues = lint.lint_file("stray text\n\n## 1 A\n\nx\n", {"1": _ctx("1")})
    assert [(i.section, i.rule, i.line) for i in issues] == [("", "R6", 1)]
    assert issues[0].evidence.startswith("text outside a ## unit")


def test_text_under_rejected_heading_is_flagged():
    issues = lint.lint_file("## 1 A\n\nx\n\n## \n\nlost\n", {"1": _ctx("1")})
    assert [(i.section, i.rule, i.line) for i in issues] == [("1", "R6", 5)]


def test_cli_lint_rejects_missing_pdf(tmp_path):
    result = runner.invoke(
        app, ["l3", "lint", "d", "--pdf", str(tmp_path / "nope.pdf")]
    )
    assert result.exit_code == 2
