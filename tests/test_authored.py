from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb import ingestcmd, models
from strata_kb.authored import AUTHORED_TAG, is_authored, set_authored
from strata_kb.cli import app
from strata_kb.config import KBConfig
from strata_kb.ingest import parser, scaffold

runner = CliRunner()
DOC = "demo-doc"


def _tags(kb: Path) -> list[str]:
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    return next(e.tags for e in index.docs if e.id == DOC)


def _snapshot(kb: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(kb)): p.read_bytes()
        for p in (kb / DOC).rglob("*")
        if p.is_file()
    }


def _forbid_parse(monkeypatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError("PDF parser must not run for an authored doc")

    monkeypatch.setattr(parser, "load_or_parse", _fail)


def _set_kind(kb: Path, kind: str) -> None:
    models.save_yaml_model(kb / "config.yaml", KBConfig(kind=kind))


def test_set_authored_adds_tag_once(fixture_kb):
    assert set_authored(fixture_kb, DOC, True) is True
    assert set_authored(fixture_kb, DOC, True) is False

    assert _tags(fixture_kb) == ["demo", "airspace", AUTHORED_TAG]
    assert is_authored(fixture_kb, DOC)


def test_set_authored_off_removes_tag(fixture_kb):
    set_authored(fixture_kb, DOC, True)

    assert set_authored(fixture_kb, DOC, False) is True
    assert set_authored(fixture_kb, DOC, False) is False

    assert _tags(fixture_kb) == ["demo", "airspace"]
    assert not is_authored(fixture_kb, DOC)


def test_set_authored_unknown_doc_raises(fixture_kb):
    with pytest.raises(ValueError, match="not in"):
        set_authored(fixture_kb, "nope", True)


@pytest.mark.parametrize("sections", ["", "1"])
def test_ingest_refuses_authored_doc(fixture_kb, tmp_path, monkeypatch, sections):
    set_authored(fixture_kb, DOC, True)
    before = _snapshot(fixture_kb)
    _forbid_parse(monkeypatch)
    opts = ingestcmd.IngestOptions(
        pdf=tmp_path / "x.pdf",
        doc_id=DOC,
        sections=sections,
        kb_dir=fixture_kb,
        work_dir=tmp_path / ".kb-work",
    )

    with pytest.raises(ValueError, match="authored"):
        ingestcmd.run_ingest(opts, echo=lambda _: None, warn=lambda _: None)

    assert _snapshot(fixture_kb) == before


def test_scaffold_doc_refuses_authored_doc(fixture_kb):
    set_authored(fixture_kb, DOC, True)
    before = _snapshot(fixture_kb)

    with pytest.raises(ValueError, match="authored"):
        scaffold.scaffold_doc(
            [],
            doc_id=DOC,
            title="Demo",
            tags=[],
            revision="",
            source_path=None,
            kb_dir=fixture_kb,
        )

    assert _snapshot(fixture_kb) == before


def test_summarize_redo_allowed_on_authored_doc(fixture_kb, monkeypatch):
    import strata_kb.llm as llm_mod

    # CI runners have no claude/copilot CLI; --dry-run never calls the runner.
    monkeypatch.setattr(llm_mod, "detect_runner", lambda choice, cfg: object())
    set_authored(fixture_kb, DOC, True)

    result = runner.invoke(
        app,
        [
            "summarize",
            DOC,
            "--redo",
            "--section",
            "1.1",
            "--dry-run",
            "--kb-dir",
            str(fixture_kb),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "will be reset" in result.output


def test_cli_authored_toggles(fixture_kb):
    _set_kind(fixture_kb, "hub")
    base = ["authored", DOC, "--kb-dir", str(fixture_kb)]

    marked = runner.invoke(app, base)
    again = runner.invoke(app, base)
    off = runner.invoke(app, [*base, "--off"])

    assert marked.exit_code == 0 and f"{DOC} marked" in marked.output
    assert again.exit_code == 0 and "already marked" in again.output
    assert off.exit_code == 0 and f"{DOC} unmarked" in off.output
    assert not is_authored(fixture_kb, DOC)


def test_cli_authored_rejects_non_hub(fixture_kb):
    _set_kind(fixture_kb, "child")

    result = runner.invoke(app, ["authored", DOC, "--kb-dir", str(fixture_kb)])

    assert result.exit_code == 1
    assert "hub" in result.output
    assert not is_authored(fixture_kb, DOC)


def test_cli_authored_unknown_doc_exits_1(fixture_kb):
    _set_kind(fixture_kb, "hub")

    result = runner.invoke(app, ["authored", "nope", "--kb-dir", str(fixture_kb)])

    assert result.exit_code == 1
    assert "not in" in result.output
