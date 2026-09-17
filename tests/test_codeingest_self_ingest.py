"""Reviewer G's acceptance, automated: `kb code-ingest` on the framework's
own repository must be right about it, and two clones of the same commit
— one carrying git-ignored directories — must produce byte-identical
documents. Skipped outside a git checkout of this repository."""
from pathlib import Path

import pytest

from center_kb import models
from center_kb.codeingest import core

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not (REPO / ".git").exists(), reason="needs the framework's own git checkout"
)


def _ingest(root: Path, kb_dir: Path) -> Path:
    core.run(core.CodeIngestOptions(repo_root=root, kb_dir=kb_dir, doc_id="aero-code", repo_id="aero"))
    return kb_dir / "aero-code"


def _section(text: str, heading: str) -> str:
    return text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]


def test_self_ingest_is_accurate_about_this_repository(tmp_path):
    doc = _ingest(REPO, tmp_path / "kb")

    commands = (doc / "commands.md").read_text(encoding="utf-8")
    assert "**Primary:** `ruff check .`" in _section(commands, "cmd.lint")
    assert "**Primary:** `python -m build`" in _section(commands, "cmd.build")
    assert "/dev/null" not in commands
    assert "bash scripts/gate.sh" in commands

    structure = (doc / "structure.raw.md").read_text(encoding="utf-8")
    assert ".venv" not in structure and ".worktrees" not in structure
    assert structure.count("\n") <= 610
    manifest = models.load_yaml_model(doc / "_manifest.yaml", models.Manifest)
    tree_summary = next(s.summary for s in manifest.sections if s.id == "struct.tree")
    assert "tracked files" in tree_summary

    services = (doc / "services.md").read_text(encoding="utf-8")
    assert "| Technology | Python |" in _section(services, "svc.hub")
    assert "FROM python:3.12-slim" in _section(services, "svc.hub")

    deps = (doc / "deps.md").read_text(encoding="utf-8")
    python_l2 = _section(deps, "dep.python")
    assert python_l2.count("| mcp |") == 1
    assert "| extra:dev |" in python_l2 and "| extra:ingest |" in python_l2
    assert "| requirements-gate.txt |" in python_l2


def test_same_commit_with_and_without_ignored_dirs_is_byte_identical(tmp_path, run_git):
    a, b = tmp_path / "a", tmp_path / "b"
    run_git(tmp_path, "clone", "-q", str(REPO), str(a))
    run_git(tmp_path, "clone", "-q", str(REPO), str(b))
    junk = b / ".venv-artifact" / "Lib" / "site-packages" / "x"
    junk.mkdir(parents=True)
    (junk / "main.py").write_text("", encoding="utf-8")
    (b / ".worktrees" / "t").mkdir(parents=True)
    (b / ".worktrees" / "t" / "app.py").write_text("", encoding="utf-8")

    doc_a = _ingest(a, tmp_path / "ka")
    doc_b = _ingest(b, tmp_path / "kb")
    names = sorted(p.name for p in doc_a.iterdir())
    assert names == sorted(p.name for p in doc_b.iterdir())
    for name in names:
        assert (doc_a / name).read_bytes() == (doc_b / name).read_bytes(), name
