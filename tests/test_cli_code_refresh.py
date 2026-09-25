from pathlib import Path

from typer.testing import CliRunner

from strata_kb import cli
from strata_kb.cli import app
from strata_kb.codeingest import core
from tests.fixtures_coderepo import build_code_repo

runner = CliRunner()

_BILLING = "services:\n  billing-service:\n    image: billing:1\n"


def _dev_repo(tmp_path: Path, run_git) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    kb = root / ".kb"
    kb.mkdir(exist_ok=True)
    (kb / "config.yaml").write_text(
        'kind: dev\nhub: ""\nrepo_id: "demo"\nintake: ""\n', encoding="utf-8"
    )
    (root / ".gitignore").write_text(".kb/*-code/\n", encoding="utf-8")
    core.run(core.CodeIngestOptions(
        repo_root=root, kb_dir=kb, doc_id="demo-code", repo_id="demo", scaffold_svc=True,
    ))
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    return root


def _add_billing(root: Path, run_git) -> None:
    (root / "compose.billing.yml").write_text(_BILLING, encoding="utf-8")
    run_git(root, "add", "compose.billing.yml")


def _note(root: Path, *extra: str):
    return runner.invoke(app, [
        "svc", "note", "billing-service", "--ticket", "T-1", "--title", "Billing",
        "--kb-dir", str(root / ".kb"), *extra,
    ])


def test_svc_note_finds_a_service_the_ticket_just_added(tmp_path, run_git):
    root = _dev_repo(tmp_path, run_git)
    _add_billing(root, run_git)
    result = _note(root)
    assert result.exit_code == 0, result.output
    assert "refreshed demo-code" in result.stderr


def test_svc_note_no_refresh_reads_the_document_as_it_is(tmp_path, run_git):
    root = _dev_repo(tmp_path, run_git)
    _add_billing(root, run_git)
    result = _note(root, "--no-refresh")
    assert result.exit_code == 1
    assert "unknown service 'billing-service'" in result.output
    assert "git add" in result.output


def test_build_refreshes_code_in_a_dev_repo(tmp_path, run_git):
    root = _dev_repo(tmp_path, run_git)
    _add_billing(root, run_git)
    result = runner.invoke(app, ["build", "--kb-dir", str(root / ".kb"), "--allow-pending"])
    assert result.exit_code == 0, result.output
    assert "refreshed demo-code" in result.stderr
    assert "svc.billing-service" in (root / ".kb" / "demo-code" / "services.md").read_text(encoding="utf-8")


def test_build_before_the_seed_does_not_ingest(tmp_path):
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text('kind: dev\nrepo_id: "demo"\n', encoding="utf-8")
    (kb / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    result = runner.invoke(app, ["build", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "refreshed" not in result.stderr
    assert not (kb / "demo-code").exists()


def test_publish_refreshes_before_anything_else(tmp_path, monkeypatch):
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text('kind: dev\nrepo_id: "demo"\nhub: ""\n', encoding="utf-8")
    seen: list[Path] = []
    monkeypatch.setattr(cli, "_refresh_dev_code", lambda kb_dir: seen.append(kb_dir))
    runner.invoke(app, ["publish", "--kb-dir", str(kb)])  # fails later: no hub
    assert seen == [kb]
