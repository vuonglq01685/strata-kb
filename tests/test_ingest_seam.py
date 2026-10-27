"""Pin tests-gate/fixtures/pending-kb/ to the REAL output of scaffold_doc().

The e2e journey cannot run `kb ingest` (it needs docling ~2GB + a copyrighted
PDF), so it starts from a fixture that simulates ingest's output. This test is
what keeps that fixture from drifting away from the truth: regenerate into tmp,
compare against the committed tree.

WHAT RED MEANS: ingest's output has changed. Do not fix the test. Re-run
`python scripts/gen_e2e_fixture.py`, read the diff carefully, then commit the
new fixture — and check whether tests-gate/e2e/test_journey.py is still correct
against the new shape.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.l3check import report as l3report
from tests.test_parser import _StubDoc, _StubItem, _StubLabel, _StubProv

REPO = Path(__file__).parent.parent
FIXTURE = REPO / "tests-gate" / "fixtures" / "pending-kb"

sys.path.insert(0, str(REPO / "scripts"))
from gen_e2e_fixture import generate

PIL = pytest.importorskip("PIL")
from PIL import Image

runner = CliRunner()


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def test_fixture_file_tree_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    assert _tree(tmp_path / ".kb") == _tree(FIXTURE)


def test_fixture_markdown_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    # Do not hardcode the file names: scaffold_doc().chapter_stem() slugifies the
    # title of the chapter's first unit, so the name is ch1-airspace-records.*.
    # Walk the real tree instead of guessing — the set of names is already pinned
    # by test_fixture_file_tree_matches_scaffold_output.
    names = sorted(p.name for p in (FIXTURE / "demo-doc").glob("*.md"))
    assert names, "the fixture has no .md files"

    for name in names:
        fresh = (tmp_path / ".kb" / "demo-doc" / name).read_text(encoding="utf-8")
        committed = (FIXTURE / "demo-doc" / name).read_text(encoding="utf-8")
        assert fresh == committed, f"{name} has drifted from scaffold_doc()'s output"


def test_fixture_manifest_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    fresh = yaml.safe_load(
        (tmp_path / ".kb" / "demo-doc" / "_manifest.yaml").read_text(encoding="utf-8")
    )
    committed = yaml.safe_load(
        (FIXTURE / "demo-doc" / "_manifest.yaml").read_text(encoding="utf-8")
    )
    # scaffold_doc sets ingested=date.today() → it drifts every day, not a signal.
    fresh.pop("ingested", None)
    committed.pop("ingested", None)

    assert fresh == committed


def test_fixture_index_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    fresh = yaml.safe_load(
        (tmp_path / ".kb" / "index.yaml").read_text(encoding="utf-8")
    )
    committed = yaml.safe_load((FIXTURE / "index.yaml").read_text(encoding="utf-8"))
    # No field here drifts with the date/time (unlike ingested in _manifest.yaml)
    # — pop nothing, compare the whole document.

    assert fresh == committed, "index.yaml has drifted from scaffold_doc()'s output"


def test_ingest_writes_assets_and_l3_ref(tmp_path, monkeypatch):
    """End-to-end seam: `kb ingest` must thread assets_dir through to the real
    parser.doc_to_items() so a picture item lands as a saved asset file AND
    an image markdown reference in the section's raw L3. Only load_or_parse
    is stubbed here — doc_to_items runs for real, unlike test_ingest_cli.py
    which stubs doc_to_items itself and never touches the assets seam."""
    from strata_kb.ingest import parser

    fake_doc = _StubDoc(
        items=[
            _StubItem(
                _StubLabel("section_header"),
                text="5.0 NAVIGATION DATA",
                level=1,
                prov=[_StubProv(page_no=1)],
            ),
            _StubItem(
                _StubLabel("text"),
                text="Chapter intro text.",
                prov=[_StubProv(page_no=1)],
            ),
            _StubItem(
                _StubLabel("picture"),
                prov=[_StubProv(page_no=1)],
                image=Image.new("RGB", (32, 32), (0, 0, 0)),
                caption="Figure 5-1. Holding pattern",
            ),
        ]
    )
    monkeypatch.setattr(parser, "load_or_parse", lambda pdf, work: fake_doc)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-fake")
    kb_dir = tmp_path / ".kb"
    result = runner.invoke(
        app,
        [
            "ingest",
            str(pdf),
            "--id",
            "demo",
            "--kb-dir",
            str(kb_dir),
            "--work-dir",
            str(tmp_path / ".kb-work"),
            "--no-summarize",
        ],
    )
    assert result.exit_code == 0, result.output

    assets = list((kb_dir / "demo" / "assets").iterdir())
    assert len(assets) == 1
    l3 = next((kb_dir / "demo").glob("*.raw.md")).read_text(encoding="utf-8")
    assert f"](assets/{assets[0].name})" in l3


BODY = "Holding patterns keep aircraft in a defined airspace while awaiting clearance."
DROPPED = "Radius limits for the holding fixes are listed in the annex tables."


def _l3_fake(monkeypatch, tmp_path, page_text: dict[int, str]):
    """Fake docling doc (one section, page 1) + a stubbed PDF text layer."""
    from strata_kb.ingest import parser, pdftext

    fake_doc = _StubDoc(
        items=[
            _StubItem(
                _StubLabel("section_header"),
                text="5.0 NAVIGATION DATA",
                level=1,
                prov=[_StubProv(page_no=1)],
            ),
            _StubItem(_StubLabel("text"), text=BODY, prov=[_StubProv(page_no=1)]),
        ]
    )
    monkeypatch.setattr(parser, "load_or_parse", lambda pdf, work: fake_doc)
    monkeypatch.setattr(pdftext, "page_texts", lambda pdf: page_text)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-fake")
    return tmp_path / ".kb"


def _ingest_demo(tmp_path, *extra):
    return runner.invoke(
        app,
        [
            "ingest",
            str(tmp_path / "doc.pdf"),
            "--id",
            "demo",
            "--kb-dir",
            str(tmp_path / ".kb"),
            "--work-dir",
            str(tmp_path / ".kb-work"),
            "--no-summarize",
            *extra,
        ],
    )


def test_ingest_writes_l3check_for_missing_text(tmp_path, monkeypatch):
    kb_dir = _l3_fake(
        monkeypatch, tmp_path, {1: f"5.0 NAVIGATION DATA\n{BODY}\n{DROPPED}"}
    )

    result = _ingest_demo(tmp_path)

    assert result.exit_code == 0, result.output
    check = l3report.load(kb_dir / "demo")
    assert check is not None
    assert [s.id for s in check.sections] == ["5"]
    assert [f.kind for f in check.sections[0].findings] == ["content"]
    assert check.sections[0].l3_sha256 == l3report.current_digests(kb_dir, "demo")["5"]
    assert (
        "L3 check: 1 section(s) flagged (fallback 0, order 0, content 1, break 0, "
        "unverifiable 0) — review: kb l3 report demo" in result.output
    )


def test_ingest_clean_doc_writes_no_file(tmp_path, monkeypatch):
    kb_dir = _l3_fake(monkeypatch, tmp_path, {1: f"5.0 NAVIGATION DATA\n{BODY}"})

    result = _ingest_demo(tmp_path)

    assert result.exit_code == 0, result.output
    assert "L3 check: clean" in result.output
    assert not (kb_dir / "demo" / l3report.FILE_NAME).exists()


def test_ingest_unreadable_text_layer_skips_check(tmp_path, monkeypatch):
    kb_dir = _l3_fake(monkeypatch, tmp_path, {})

    result = _ingest_demo(tmp_path)

    assert result.exit_code == 0, result.output
    assert "L3 check skipped: PDF text layer unreadable" in result.output
    assert not (kb_dir / "demo" / l3report.FILE_NAME).exists()


def test_reingest_unchanged_keeps_confirmation(tmp_path, monkeypatch):
    kb_dir = _l3_fake(
        monkeypatch, tmp_path, {1: f"5.0 NAVIGATION DATA\n{BODY}\n{DROPPED}"}
    )
    assert _ingest_demo(tmp_path).exit_code == 0
    l3report.confirm(kb_dir, "demo", None, by="tester")

    result = _ingest_demo(tmp_path)

    assert result.exit_code == 0, result.output
    assert "L3 check: clean" in result.output
    check = l3report.load(kb_dir / "demo")
    assert check is not None and check.sections[0].confirmed is not None


def test_sections_reingest_keeps_other_chapters_and_flags_nothing_new(
    tmp_path, monkeypatch
):
    from strata_kb.ingest import parser, pdftext

    other = "Route segments connect the published waypoints in the listed order."
    fake_doc = _StubDoc(
        items=[
            _StubItem(
                _StubLabel("section_header"),
                text="5.0 NAVIGATION DATA",
                level=1,
                prov=[_StubProv(page_no=1)],
            ),
            _StubItem(_StubLabel("text"), text=BODY, prov=[_StubProv(page_no=1)]),
            _StubItem(
                _StubLabel("section_header"),
                text="6.0 ROUTES",
                level=1,
                prov=[_StubProv(page_no=2)],
            ),
            _StubItem(_StubLabel("text"), text=other, prov=[_StubProv(page_no=2)]),
        ]
    )
    monkeypatch.setattr(parser, "load_or_parse", lambda pdf, work: fake_doc)
    monkeypatch.setattr(
        pdftext,
        "page_texts",
        lambda pdf: {
            1: f"5.0 NAVIGATION DATA\n{BODY}",
            2: f"6.0 ROUTES\n{other}\n{DROPPED}",  # lost sentence, flagged on 5 (span 1-2)
        },
    )
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-fake")
    kb_dir = tmp_path / ".kb"
    assert _ingest_demo(tmp_path).exit_code == 0
    assert [s.id for s in l3report.load(kb_dir / "demo").sections] == ["5"]
    l3report.confirm(kb_dir, "demo", None, by="tester")

    result = _ingest_demo(tmp_path, "--sections", "6")

    assert result.exit_code == 0, result.output
    assert "L3 check: clean" in result.output
    check = l3report.load(kb_dir / "demo")
    assert [s.id for s in check.sections] == ["5"]
    assert check.sections[0].confirmed is not None
