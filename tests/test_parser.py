from dataclasses import dataclass, field

from aero_kb.ingest import parser


@dataclass
class _StubLabel:
    value: str


@dataclass
class _StubItem:
    label: _StubLabel
    text: str = ""
    level: int = 1
    table_md: str = ""

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
