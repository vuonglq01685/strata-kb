from pathlib import Path

from typer.testing import CliRunner

from center_kb import models
from center_kb.cli import app
from center_kb.ingest.sectioner import DocItem

runner = CliRunner()

FAKE_ITEMS = [
    DocItem("heading", "5.0 NAVIGATION DATA", 1),
    DocItem("text", "Chapter intro. " * 60),
    DocItem("heading", "5.3 Restrictive Airspace", 2),
    DocItem("text", "Airspace body. " * 60),
]


def _fake_parse(monkeypatch):
    from center_kb.ingest import parser

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
