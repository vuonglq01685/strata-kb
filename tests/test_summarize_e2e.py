import json
import stat
from pathlib import Path

from typer.testing import CliRunner

from center_kb import models
from center_kb.cli import app
from tests.test_summarize import make_kb

runner = CliRunner()

INNER = json.dumps({"l2_summary": "Condensed via stub.", "l1_summary": "Stub line."})
ENVELOPE = json.dumps({"type": "result", "result": INNER})
DOC_INNER = json.dumps(
    {"l2_summary": "Condensed via stub.", "l1_summary": "Stub line.",
     "summary": "Stub doc summary."}
)
DOC_ENVELOPE = json.dumps({"type": "result", "result": DOC_INNER})


def _install_stub_claude(tmp_path: Path, monkeypatch, body: str) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "claude"
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bindir), prepend=":")


def test_kb_summarize_end_to_end_with_stub_claude(tmp_path, monkeypatch):
    kb = make_kb(tmp_path, {})
    # stub replies with a payload valid for BOTH section and doc prompts
    _install_stub_claude(tmp_path, monkeypatch, f"cat > /dev/null\necho '{DOC_ENVELOPE}'")
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb), "--llm", "claude"])
    assert result.exit_code == 0, result.output
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "summarized" for s in manifest.sections)
    l2 = (kb / "d1" / "ch1.md").read_text(encoding="utf-8")
    assert "Condensed via stub." in l2 and "TODO:summarize" not in l2
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].summary == "Stub doc summary."


def test_kb_summarize_end_to_end_garbage_reply_fails_cleanly(tmp_path, monkeypatch):
    kb = make_kb(tmp_path, {})
    _install_stub_claude(tmp_path, monkeypatch, "cat > /dev/null\necho 'not json'")
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb), "--llm", "claude"])
    assert result.exit_code == 1
    assert "2 failed" in result.output
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "pending" for s in manifest.sections)


def test_kb_summarize_parallel_many_sections_manifest_consistent(tmp_path, monkeypatch):
    kb = tmp_path / ".kb"
    doc = kb / "big"
    doc.mkdir(parents=True)
    n = 12
    raw, l2, sections = [], [], []
    for i in range(1, n + 1):
        raw += [f"## {i}.0 Sec{i}", "", f"Body {i}.", ""]
        l2 += [f"## {i}.0 Sec{i}", "", f"<!-- TODO:summarize {i}.0 -->", ""]
        sections.append(models.SectionEntry(id=f"{i}.0", title=f"Sec{i}", file="ch"))
    (doc / "ch.raw.md").write_text("\n".join(raw), encoding="utf-8")
    (doc / "ch.md").write_text("\n".join(l2), encoding="utf-8")
    models.save_yaml_model(
        doc / "_manifest.yaml", models.Manifest(id="big", title="Big", sections=sections)
    )
    models.save_yaml_model(
        kb / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id="big", title="Big")]),
    )
    _install_stub_claude(tmp_path, monkeypatch, f"cat > /dev/null\necho '{DOC_ENVELOPE}'")
    result = runner.invoke(
        app, ["summarize", "--kb-dir", str(kb), "--llm", "claude", "--max-workers", "5"]
    )
    assert result.exit_code == 0, result.output
    manifest = models.load_yaml_model(doc / "_manifest.yaml", models.Manifest)
    assert sum(1 for s in manifest.sections if s.status == "summarized") == n
    assert "TODO:summarize" not in (doc / "ch.md").read_text(encoding="utf-8")
