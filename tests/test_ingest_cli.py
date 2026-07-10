from pathlib import Path

from typer.testing import CliRunner

from aero_kb import models
from aero_kb.cli import app
from aero_kb.ingest.sectioner import DocItem

runner = CliRunner()

FAKE_ITEMS = [
    DocItem("heading", "5.0 NAVIGATION DATA", 1),
    DocItem("text", "Chapter intro. " * 60),
    DocItem("heading", "5.3 Restrictive Airspace", 2),
    DocItem("text", "Airspace body. " * 60),
]


def _fake_parse(monkeypatch):
    from aero_kb.ingest import parser

    monkeypatch.setattr(parser, "load_or_parse", lambda pdf, work: object())
    monkeypatch.setattr(parser, "doc_to_items", lambda doc: FAKE_ITEMS)
    monkeypatch.setattr(
        parser, "bookmark_ids", lambda pdf, config=None: {"5", "5.3", "5.9"}
    )


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
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert [s.id for s in manifest.sections] == ["5", "5.3"]
    assert "5.9" in result.output  # canh bao bookmark khong duoc cover


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
        ],
    )
    result = runner.invoke(app, ["status", "--kb-dir", str(tmp_path / ".kb")])
    assert result.exit_code == 0
    assert "arinc-424" in result.output
    assert "5.3" in result.output
    assert "pending" in result.output.lower()
