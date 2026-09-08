from pathlib import Path

from typer.testing import CliRunner

from center_kb import models
from center_kb.cli import app
from center_kb.ingest.sectioner import DocItem, Part

runner = CliRunner()

FAKE_ITEMS = [
    DocItem("heading", "5.0 NAVIGATION DATA", 1),
    DocItem("text", "Chapter intro. " * 60),
    DocItem("heading", "5.3 Restrictive Airspace", 2),
    DocItem("text", "Airspace body. " * 60),
]

BOOKMARK_ITEMS = [
    DocItem("heading", "5.0 NAVIGATION DATA", 1, page=1),
    DocItem("text", "Chapter intro. " * 60, page=1),
    DocItem("text", "Flow body. " * 60, page=5),
]


def _fake_parse(monkeypatch):
    from center_kb.ingest import parser

    monkeypatch.setattr(parser, "load_or_parse", lambda pdf, work: object())
    monkeypatch.setattr(parser, "doc_to_items", lambda doc, assets_dir=None, pdf_path=None: FAKE_ITEMS)
    monkeypatch.setattr(
        parser, "bookmark_ids", lambda pdf, config=None: {"5", "5.3", "5.9"}
    )


def _fake_parse_with_bookmark_parts(monkeypatch):
    from center_kb.ingest import parser

    monkeypatch.setattr(parser, "load_or_parse", lambda pdf, work: object())
    monkeypatch.setattr(parser, "doc_to_items", lambda doc, assets_dir=None, pdf_path=None: BOOKMARK_ITEMS)
    monkeypatch.setattr(parser, "bookmark_ids", lambda pdf, config=None: set())
    monkeypatch.setattr(
        parser,
        "outline_parts",
        lambda pdf, config=None: [Part("1", "INTRO", 1), Part("attachment-1", "FLOW", 5)],
    )


def _fake_parse_outline_forbidden(monkeypatch):
    from center_kb.ingest import parser

    monkeypatch.setattr(parser, "load_or_parse", lambda pdf, work: object())
    monkeypatch.setattr(parser, "doc_to_items", lambda doc, assets_dir=None, pdf_path=None: BOOKMARK_ITEMS)
    monkeypatch.setattr(parser, "bookmark_ids", lambda pdf, config=None: set())

    def _forbidden(pdf, config=None):
        raise AssertionError("outline_parts must not be called with --no-bookmarks")

    monkeypatch.setattr(parser, "outline_parts", _forbidden)


def test_ingest_rejects_traversal_doc_id_before_touching_paths(
    tmp_path: Path, monkeypatch
):
    _fake_parse(monkeypatch)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-fake")
    result = runner.invoke(
        app,
        [
            "ingest", str(pdf),
            "--id", "../evil",
            "--kb-dir", str(tmp_path / ".kb"),
            "--work-dir", str(tmp_path / ".kb-work"),
            "--llm", "none",
        ],
    )
    assert result.exit_code == 1
    assert "invalid" in result.output
    assert not (tmp_path / "evil").exists()


def test_ingest_creates_kb_and_reports_warnings(tmp_path: Path, monkeypatch):
    _fake_parse(monkeypatch)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-fake")
    result = runner.invoke(
        app,
        [
            "ingest", str(pdf),
            "--id", "arinc-424",
            "--tags", "arinc424,navdata",
            "--revision", "Supplement 22",
            "--kb-dir", str(tmp_path / ".kb"),
            "--work-dir", str(tmp_path / ".kb-work"),
            "--llm", "none",
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert [s.id for s in manifest.sections] == ["5", "5.3"]
    assert "5.9" in result.output  # bookmark-not-covered warning


def test_status_lists_pending_sections(tmp_path: Path, monkeypatch):
    _fake_parse(monkeypatch)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-fake")
    runner.invoke(
        app,
        [
            "ingest", str(pdf),
            "--id", "arinc-424",
            "--tags", "arinc424",
            "--kb-dir", str(tmp_path / ".kb"),
            "--work-dir", str(tmp_path / ".kb-work"),
            "--llm", "none",
        ],
    )
    result = runner.invoke(app, ["status", "--kb-dir", str(tmp_path / ".kb")])
    assert result.exit_code == 0
    assert "arinc-424" in result.output
    assert "5.3" in result.output
    assert "pending" in result.output.lower()


def _ingest_args(tmp_path, extra=()):
    return [
        "ingest", str(tmp_path / "doc.pdf"),
        "--id", "arinc-424",
        "--kb-dir", str(tmp_path / ".kb"),
        "--work-dir", str(tmp_path / ".kb-work"),
        *extra,
    ]


def _write_pdf(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-fake")


def test_ingest_auto_summarizes_by_default(tmp_path, monkeypatch):
    _fake_parse(monkeypatch)
    _write_pdf(tmp_path)
    from tests.test_summarize import FakeRunner
    import center_kb.llm as llm_mod
    monkeypatch.setattr(llm_mod, "detect_runner", lambda c, cfg: FakeRunner())
    # index.yaml is created by scaffold during ingest; default runner=auto
    result = runner.invoke(app, _ingest_args(tmp_path))
    assert result.exit_code == 0, result.output
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert all(s.status == "summarized" for s in manifest.sections)
    assert "summarized" in result.output


def test_ingest_no_summarize_flag_skips_llm(tmp_path, monkeypatch):
    _fake_parse(monkeypatch)
    _write_pdf(tmp_path)
    import center_kb.llm as llm_mod
    monkeypatch.setattr(
        llm_mod, "detect_runner",
        lambda c, cfg: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    result = runner.invoke(app, _ingest_args(tmp_path, ["--no-summarize"]))
    assert result.exit_code == 0, result.output
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert all(s.status == "pending" for s in manifest.sections)
    assert "kb-summarize" in result.output  # manual-path hint preserved


def test_ingest_without_runner_stays_pending_exit_0(tmp_path, monkeypatch):
    _fake_parse(monkeypatch)
    _write_pdf(tmp_path)
    import center_kb.llm as llm_mod
    monkeypatch.setattr(llm_mod, "detect_runner", lambda c, cfg: None)
    result = runner.invoke(app, _ingest_args(tmp_path))
    assert result.exit_code == 0, result.output
    assert "No LLM CLI found" in result.output
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert all(s.status == "pending" for s in manifest.sections)


def test_ingest_failed_sections_still_exit_0(tmp_path, monkeypatch):
    _fake_parse(monkeypatch)
    _write_pdf(tmp_path)
    from tests.test_summarize import FakeRunner
    import center_kb.llm as llm_mod
    monkeypatch.setattr(
        llm_mod, "detect_runner", lambda c, cfg: FakeRunner(fail_ids={"5.3"})
    )
    result = runner.invoke(app, _ingest_args(tmp_path))
    assert result.exit_code == 0, result.output
    assert "failed" in result.output
    assert "kb summarize" in result.output  # re-run hint


def test_ingest_uses_bookmark_parts_when_available(tmp_path: Path, monkeypatch):
    _fake_parse_with_bookmark_parts(monkeypatch)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none"]))
    assert result.exit_code == 0, result.output
    assert "sectioning: bookmarks (2 parts)" in result.output
    doc_dir = tmp_path / ".kb" / "arinc-424"
    assert any(f.name.startswith("attachment-1-") for f in doc_dir.glob("*.md"))
    manifest = models.load_yaml_model(doc_dir / "_manifest.yaml", models.Manifest)
    assert manifest.ingest.used_bookmarks is True


def test_ingest_no_bookmarks_flag_forces_regex_mode(tmp_path: Path, monkeypatch):
    _fake_parse_outline_forbidden(monkeypatch)
    _write_pdf(tmp_path)
    result = runner.invoke(
        app, _ingest_args(tmp_path, ["--llm", "none", "--no-bookmarks"])
    )
    assert result.exit_code == 0, result.output
    assert "sectioning: heading patterns" in result.output
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert manifest.ingest.used_bookmarks is False


def test_ingest_warns_when_content_never_reaches_l3(tmp_path: Path, monkeypatch):
    from center_kb.ingest import parser

    # Text with no heading anywhere above it lands on the tree root, which is
    # never rendered into a section. L3 is the complete-content layer, so
    # ingest must say so out loud instead of losing it silently.
    orphan = "Stranded preamble sentence."
    monkeypatch.setattr(parser, "load_or_parse", lambda pdf, work: object())
    monkeypatch.setattr(
        parser, "doc_to_items", lambda doc, assets_dir=None, pdf_path=None: [DocItem("text", orphan)]
    )
    monkeypatch.setattr(parser, "bookmark_ids", lambda pdf, config=None: set())
    monkeypatch.setattr(parser, "outline_parts", lambda pdf, config=None: None)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    result = runner.invoke(
        app, ["ingest", str(pdf), "--id", "demo", "--kb-dir", str(tmp_path / ".kb")]
    )

    assert "Stranded preamble sentence." in result.output


def test_ingest_is_quiet_when_every_item_reaches_l3(tmp_path: Path, monkeypatch):
    _fake_parse(monkeypatch)
    monkeypatch.setattr(
        __import__("center_kb.ingest.parser", fromlist=["parser"]),
        "bookmark_ids",
        lambda pdf, config=None: set(),
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    result = runner.invoke(
        app, ["ingest", str(pdf), "--id", "demo", "--kb-dir", str(tmp_path / ".kb")]
    )

    assert "never reached" not in result.output


def _stub_parser(monkeypatch, items, bookmark_ids=frozenset()):
    from center_kb.ingest import parser

    monkeypatch.setattr(parser, "load_or_parse", lambda pdf, work: object())
    monkeypatch.setattr(parser, "doc_to_items", lambda doc, assets_dir=None, pdf_path=None: items)
    monkeypatch.setattr(parser, "bookmark_ids", lambda pdf, config=None: bookmark_ids)
    monkeypatch.setattr(parser, "outline_parts", lambda pdf, config=None: None)


BIG = "Body text. " * 70

NOISY_ITEMS = [
    DocItem("heading", "5.0 NAVIGATION DATA", 1, page=1),
    DocItem("text", "Chapter intro. " + BIG, page=1),
    DocItem("heading", "5.6 Identifier", 2, page=2),
    DocItem("text", "Field body. " + BIG, page=2),
    DocItem("heading", "Table 5-6 Airport SID Record", 2, page=2),
    DocItem("table", "| a | b |\n|---|---|\n| 1 | 2 |", page=2),
    DocItem("heading", "NDB Navaid Record", 2, page=3),
    DocItem("text", "Value body. " + BIG, page=3),
]

INVERTED_ITEMS = [
    DocItem("heading", "5.0 NAVIGATION DATA", 1, page=1),
    DocItem("text", "Chapter intro. " + BIG, page=1),
    DocItem("heading", "5.84 RUNWAY TRANS", 2, page=212),
    DocItem("text", "para-a. " + BIG, page=212),
    DocItem("heading", "5.83 To FIX", 2, page=212),
    DocItem("text", "para-b. " + BIG, page=212),
]


def test_ingest_report_names_demotions_fallbacks_and_token_stats(tmp_path: Path, monkeypatch):
    _stub_parser(monkeypatch, NOISY_ITEMS)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none"]))
    assert result.exit_code == 0, result.output
    assert "[warn] heading demoted to text (caption, page 2): 'Table 5-6 Airport SID Record'" in result.output
    assert "[warn] fallback id '5.6-ndb-navaid-record' for unparsed heading 'NDB Navaid Record' (page 3)" in result.output
    assert "sections: 3 · L3 tokens min/median/max " in result.output
    assert "below 300, 0 above 5000 · 1 fallback ids" in result.output


def test_ingest_report_names_a_page_inversion_without_layout_data(tmp_path: Path, monkeypatch):
    _stub_parser(monkeypatch, INVERTED_ITEMS)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none"]))
    assert result.exit_code == 0, result.output
    assert (
        "[warn] heading order inverted on page 212: 5.84 before 5.83 — "
        "no layout data, body attribution may be wrong"
    ) in result.output


def test_ingest_report_carries_parser_logger_warnings_and_detaches(tmp_path: Path, monkeypatch):
    import logging

    from center_kb.ingest import parser

    def _items(doc, assets_dir=None, pdf_path=None):
        logging.getLogger("center_kb.ingest.parser").warning("picture on page 7 skipped: boom")
        return FAKE_ITEMS

    _stub_parser(monkeypatch, FAKE_ITEMS)
    monkeypatch.setattr(parser, "doc_to_items", _items)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none"]))
    assert result.exit_code == 0, result.output
    assert "[warn] picture on page 7 skipped: boom" in result.output
    assert logging.getLogger("center_kb.ingest").handlers == []


def test_ingest_warns_when_the_outline_is_unreadable(tmp_path: Path, monkeypatch):
    _stub_parser(monkeypatch, FAKE_ITEMS, bookmark_ids=None)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none"]))
    assert "[warn] PDF outline unreadable — bookmark cross-check skipped" in result.output


def test_ingest_warns_when_sections_filter_matches_nothing(tmp_path: Path, monkeypatch):
    _stub_parser(monkeypatch, FAKE_ITEMS)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none", "--sections", "9"]))
    assert result.exit_code == 0, result.output
    assert (
        "[warn] --sections 9 matched no headings this run — existing files "
        "and manifest entries for those chapters were removed"
    ) in result.output


def test_warn_notes_renders_every_line_class_and_the_capped_tail():
    """The spec asked for a test naming 'each [warn] line class'. Four of
    the eight report line formats had zero coverage anywhere on the
    branch: the duplicate-id line, the reordered=True inversion line, the
    'repeated on N pages' rendering, and the _warn_capped 'N more … not
    shown' tail. This exercises all four directly against _warn_notes,
    with >20 demotions to trigger the cap."""
    from center_kb.ingest.sectioner import Demotion, Duplicate, Inversion, SectioningNotes
    from center_kb.ingestcmd import _warn_notes

    repeated = Demotion(
        heading="5.6 Identifier",
        reason="repeated",
        pages=(None, 61, 88),  # M-7: the printed count must match the printed list
    )
    padding = [
        Demotion(heading=f"Caption {i}", reason="caption", pages=(2,))
        for i in range(20)
    ]
    notes = SectioningNotes(
        demoted=[repeated, *padding],  # 21 total -> exceeds the 20-line cap
        fallbacks=[],
        inversions=[
            Inversion(page=212, first_id="5.84", second_id="5.83", reordered=True)
        ],
        duplicates=[Duplicate(original="5.3", renamed="5.3-2", chapter="6")],
    )

    lines: list[str] = []
    _warn_notes(notes, lines.append)

    assert (
        "heading demoted to text (repeated on 2 pages: 61, 88): '5.6 Identifier'"
    ) in lines
    assert "heading demoted to text (caption, page 2): 'Caption 0'" in lines
    assert "1 more demoted headings not shown" in lines
    assert (
        "heading order inverted on page 212: 5.84 before 5.83 — "
        "page re-ordered by layout, check both sections"
    ) in lines
    assert "duplicate section id '5.3' in part 6 renamed to '5.3-2'" in lines
