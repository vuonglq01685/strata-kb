import json

from typer.testing import CliRunner

from strata_kb import models
from strata_kb.cli import app
from strata_kb.l3check import report, spans
from strata_kb.l3check.spans import SpansFile, UnitSpan
from tests.test_ingest_cli import (
    NOISY_ITEMS,
    _ingest_args,
    _stub_parser,
    _write_pdf,
)

runner = CliRunner()


def test_roundtrip(tmp_path):
    data = SpansFile(
        doc_id="d",
        units=[UnitSpan(id="1", file="ch1", chapter="1", page=2, end_page=3)],
        fallback_units=["x1"],
    )
    spans.save(tmp_path, "d", data)
    assert (tmp_path / "d" / spans.FILE_NAME).is_file()
    assert spans.load(tmp_path, "d") == data
    assert spans.load(tmp_path, "other") is None


def test_section_input_carries_span():
    sec = spans.section_input(
        UnitSpan(id="1", file="f", chapter="1", page=2, end_page=4), "body"
    )
    assert (sec.id, sec.chapter, sec.page, sec.end_page, sec.l3) == (
        "1",
        "1",
        2,
        4,
        "body",
    )


def _ingest(tmp_path, monkeypatch, page_texts):
    from strata_kb.ingest import parser, pdftext

    _stub_parser(monkeypatch, NOISY_ITEMS)
    monkeypatch.setattr(parser, "furniture_by_page", lambda doc: {})
    monkeypatch.setattr(pdftext, "page_texts", lambda pdf: page_texts)
    _write_pdf(tmp_path)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none"]))
    assert result.exit_code == 0, result.output


def test_ingest_writes_sections_json(tmp_path, monkeypatch):
    _ingest(tmp_path, monkeypatch, {1: "intro", 2: "field", 3: "value"})

    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    loaded = spans.load(tmp_path / ".kb-work", "arinc-424")
    assert loaded is not None
    assert [u.id for u in loaded.units] == [s.id for s in manifest.sections]
    assert [u.file for u in loaded.units] == [s.file for s in manifest.sections]
    assert [(u.page, u.end_page) for u in loaded.units] == [(1, 2), (2, 3)]
    check = report.load(tmp_path / ".kb" / "arinc-424")
    flagged = sorted(
        s.id for s in check.sections for f in s.findings if f.kind == "fallback"
    )
    assert loaded.fallback_units == flagged != []


def test_ingest_writes_sections_json_without_text_layer(tmp_path, monkeypatch):
    _ingest(tmp_path, monkeypatch, {})

    raw = json.loads(
        (tmp_path / ".kb-work" / "arinc-424" / spans.FILE_NAME).read_text()
    )
    assert [(u["page"], u["end_page"]) for u in raw["units"]] == [
        (1, 2),
        (2, None),
    ]
    assert raw["fallback_units"] == ["5.6"]
