from pathlib import Path

from typer.testing import CliRunner

from strata_kb import models, summarize
from strata_kb.cli import app
from strata_kb.codeingest import core
from tests.fixtures_coderepo import build_code_repo

runner = CliRunner()


def _kb(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    core.run(core.CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="demo-code", repo_id="demo",
        scaffold_svc=True,
    ))
    return root / ".kb"


def test_generated_doc_ids(tmp_path):
    assert summarize.generated_doc_ids(_kb(tmp_path)) == {"demo-code"}


def test_plan_redo_all_skips_generated_documents(tmp_path):
    # The route that put an LLM summary into MyFlix's -code (2026-09-22):
    # `kb summarize --redo --all` reset code-ingest's `summarized` rows.
    plan = summarize.plan_redo(_kb(tmp_path), None)
    assert plan.items and all(i.doc_id != "demo-code" for i in plan.items)


def test_collect_pending_skips_generated_documents(tmp_path):
    kb = _kb(tmp_path)
    path = kb / "demo-code" / "_manifest.yaml"
    manifest = models.load_yaml_model(path, models.Manifest)
    manifest.sections[0].status = "pending"
    models.save_yaml_model(path, manifest)
    assert all(p.doc_id != "demo-code" for p in summarize.collect_pending(kb))


def test_cli_refuses_a_generated_document(tmp_path):
    result = runner.invoke(app, ["summarize", "demo-code", "--kb-dir", str(_kb(tmp_path)),
                                 "--llm", "none"])
    assert result.exit_code == 1
    assert "never summarized" in result.output


def test_cli_notes_the_skip_on_an_all_documents_run(tmp_path):
    result = runner.invoke(app, ["summarize", "--redo", "--all", "--dry-run",
                                 "--kb-dir", str(_kb(tmp_path))])
    assert "skipped generated document(s): demo-code" in result.stderr
