from dataclasses import dataclass, field

from center_kb.ingest import parser


@dataclass
class _StubLabel:
    value: str


@dataclass
class _StubProv:
    page_no: int


@dataclass
class _StubItem:
    label: _StubLabel
    text: str = ""
    level: int = 1
    table_md: str = ""
    prov: list = None

    def export_to_markdown(self, doc=None):
        return self.table_md


@dataclass
class _StubDoc:
    items: list = field(default_factory=list)

    def iterate_items(self):
        for it in self.items:
            yield it, 0


def test_doc_to_items_maps_labels():
    doc = _StubDoc(
        items=[
            _StubItem(_StubLabel("section_header"), text="5.3 Restrictive Airspace", level=2),
            _StubItem(_StubLabel("text"), text="Body paragraph."),
            _StubItem(
                _StubLabel("table"),
                table_md="| A | B |\n|---|---|\n| 1 | 2 |",
            ),
            _StubItem(_StubLabel("page_footer"), text="Page 5"),  # ignored
            _StubItem(_StubLabel("text"), text="   "),  # empty -> ignored
        ]
    )
    items = parser.doc_to_items(doc)
    assert [i.kind for i in items] == ["heading", "text", "table"]
    assert items[0].level == 2
    assert "| A | B |" in items[2].text


def test_doc_to_items_carries_page_numbers():
    doc = _StubDoc(
        items=[
            _StubItem(
                _StubLabel("section_header"),
                text="1.0 INTRO",
                prov=[_StubProv(page_no=21)],
            ),
            _StubItem(_StubLabel("text"), text="Body."),  # no prov -> page None
        ]
    )
    items = parser.doc_to_items(doc)
    assert items[0].page == 21
    assert items[1].page is None


def test_crosscheck_reports_missing_bookmark():
    warnings = parser.crosscheck(
        unit_ids={"5", "5.3"}, bm_ids={"5", "5.3", "5.4"}
    )
    assert len(warnings) == 1
    assert "5.4" in warnings[0]


def test_crosscheck_covered_by_prefix_not_reported():
    # 5.3.2 is within unit 5.3 (folded together) -> no warning
    warnings = parser.crosscheck(unit_ids={"5", "5.3"}, bm_ids={"5.3.2"})
    assert warnings == []


def test_crosscheck_ignores_bookmarks_deeper_than_max_depth():
    warnings = parser.crosscheck(unit_ids={"5"}, bm_ids={"5.1.2.3"})
    assert warnings == []


def test_crosscheck_covered_by_dash_namespaced_units():
    warnings = parser.crosscheck(unit_ids={"attachment-4-2.1", "attachment-4-2.2"}, bm_ids={"attachment-4"})
    assert warnings == []


def test_load_or_parse_without_docling_raises_helpful_error(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("docling"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        parser.load_or_parse(tmp_path / "x.pdf", tmp_path / "work")
    except RuntimeError as e:
        assert "ingest" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_load_or_parse_pins_rapidocr_backend_and_language(tmp_path, monkeypatch):
    # CI installs [dev] only (no docling). Stub the import graph so we can
    # assert the OCR pin without the ingest extra.
    # docling's "auto" OCR mode picks rapidocr+torch in this install
    # (onnxruntime/easyocr/nemotron are not installed) but never forwards a
    # configured language to it, so English text is silently OCR'd with the
    # Chinese recognition model (drops inter-word spaces) unless pinned
    # explicitly here. See docs/superpowers (2026-07-12 ingest fix) for the
    # separate Dockerfile step that pre-bakes this exact engine's assets so
    # nothing needs downloading at runtime (root-owned site-packages dir is
    # not writable by the non-root runtime user).
    import sys
    import types

    captured = {}

    class _FakeDoc:
        def export_to_dict(self):
            return {}

    class _FakeResult:
        document = _FakeDoc()

    class _FakeDoclingDocument:
        @staticmethod
        def model_validate_json(text):
            return _FakeDoc()

    class _InputFormat:
        PDF = object()

    class _RapidOcrOptions:
        def __init__(self, backend=None, lang=None, **kwargs):
            self.backend = backend
            self.lang = lang

    class _PdfPipelineOptions:
        def __init__(self, ocr_options=None, artifacts_path=None, **kwargs):
            self.ocr_options = ocr_options
            self.artifacts_path = artifacts_path

    class _PdfFormatOption:
        def __init__(self, pipeline_options=None, **kwargs):
            self.pipeline_options = pipeline_options

    class _FakeConverter:
        def __init__(self, format_options=None, **kwargs):
            captured["format_options"] = format_options

        def convert(self, path):
            return _FakeResult()

    stubs = {
        "docling_core": types.ModuleType("docling_core"),
        "docling_core.types": types.ModuleType("docling_core.types"),
        "docling_core.types.doc": types.ModuleType("docling_core.types.doc"),
        "docling": types.ModuleType("docling"),
        "docling.datamodel": types.ModuleType("docling.datamodel"),
        "docling.datamodel.base_models": types.ModuleType("docling.datamodel.base_models"),
        "docling.datamodel.pipeline_options": types.ModuleType(
            "docling.datamodel.pipeline_options"
        ),
        "docling.document_converter": types.ModuleType("docling.document_converter"),
    }
    stubs["docling_core.types.doc"].DoclingDocument = _FakeDoclingDocument
    stubs["docling.datamodel.base_models"].InputFormat = _InputFormat
    stubs["docling.datamodel.pipeline_options"].PdfPipelineOptions = _PdfPipelineOptions
    stubs["docling.datamodel.pipeline_options"].RapidOcrOptions = _RapidOcrOptions
    stubs["docling.document_converter"].DocumentConverter = _FakeConverter
    stubs["docling.document_converter"].PdfFormatOption = _PdfFormatOption
    for name, mod in stubs.items():
        monkeypatch.setitem(sys.modules, name, mod)

    parser.load_or_parse(tmp_path / "x.pdf", tmp_path / "work")

    pdf_options = captured["format_options"][_InputFormat.PDF]
    pipeline_options = pdf_options.pipeline_options
    ocr_options = pipeline_options.ocr_options
    assert isinstance(ocr_options, _RapidOcrOptions)
    assert ocr_options.backend == "torch"
    assert ocr_options.lang == ["en"]
    assert pipeline_options.artifacts_path is None


def _pdf_with_outline(tmp_path):
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(12):
        w.add_blank_page(width=200, height=200)
    w.add_outline_item("COVER PAGE", 0)
    toc = w.add_outline_item("TABLE OF CONTENTS", 1)
    w.add_outline_item("1.0 INTRODUCTION", 2, parent=toc)
    w.add_outline_item("1.1 Sub Section", 3, parent=toc)     # sub-bookmark: not a part
    w.add_outline_item("2.0 DATA", 4, parent=toc)
    w.add_outline_item("ATTACHMENT 1 FLOW DIAGRAM", 6, parent=toc)
    w.add_outline_item("SUPPLEMENT 22", 8)
    w.add_outline_item("ERRATA", 10)
    path = tmp_path / "outlined.pdf"
    with path.open("wb") as f:
        w.write(f)
    return path


def test_outline_parts_extracts_and_orders_parts(tmp_path):
    path = _pdf_with_outline(tmp_path)
    parts = parser.outline_parts(path)
    assert parts is not None
    assert [(p.id, p.page) for p in parts] == [
        ("front-matter", 1),   # COVER PAGE + TABLE OF CONTENTS grouped
        ("1", 3),
        ("2", 5),
        ("attachment-1", 7),
        ("supplement-22", 9),
        ("errata", 11),
    ]
    titles = {p.id: p.title for p in parts}
    assert titles["attachment-1"] == "FLOW DIAGRAM"
    assert titles["front-matter"] == "Front Matter"


def test_outline_parts_returns_none_without_outline(tmp_path):
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    path = tmp_path / "plain.pdf"
    with path.open("wb") as f:
        w.write(f)
    assert parser.outline_parts(path) is None


def test_outline_parts_returns_none_for_missing_file(tmp_path):
    assert parser.outline_parts(tmp_path / "nope.pdf") is None
