import shutil
from pathlib import Path

from typer.testing import CliRunner

from strata_kb import cli
from strata_kb.cli import app
from strata_kb.codeingest import core
from strata_kb.federation import write_federation_index
from tests.fixtures_coderepo import build_code_repo

runner = CliRunner()

_BILLING = "services:\n  billing-service:\n    image: billing:1\n"


def _hub_dir(tmp_path: Path) -> Path:
    """A local hub target `resolve_hub` accepts directly (a directory with
    `.kb/`), with an empty federation so `check_hub`/`check_federation_publish`
    have nothing to complain about — the point of these tests is the -code
    refresh ordering in `kb doctor`, not hub content."""
    hub = tmp_path / "hub"
    (hub / ".kb").mkdir(parents=True)
    (hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    fed = hub / "federation"
    fed.mkdir()
    write_federation_index(fed)
    return hub


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


def test_build_regenerates_code_when_only_the_index_lists_it(tmp_path, run_git):
    """`has_code_doc`'s index-only branch (a fresh clone of a migrated dev
    repo: index.yaml lists <repo_id>-code but the gitignored directory was
    never checked out) -- currently untested at the `kb build` layer."""
    root = _dev_repo(tmp_path, run_git)
    shutil.rmtree(root / ".kb" / "demo-code")
    result = runner.invoke(app, ["build", "--kb-dir", str(root / ".kb"), "--allow-pending"])
    assert result.exit_code == 0, result.output
    assert (root / ".kb" / "demo-code" / "_manifest.yaml").is_file()


def test_doctor_refreshes_a_migrated_dev_repos_missing_code_dir(tmp_path, run_git):
    """Important 1: after migration, .kb/index.yaml still lists
    <repo_id>-code but the directory is absent on a fresh clone (or a
    teammate's pull of the `git rm --cached` commit) — `check_kb` used to
    report "missing _manifest.yaml" and `kb doctor` never refreshed."""
    root = _dev_repo(tmp_path, run_git)
    shutil.rmtree(root / ".kb" / "demo-code")
    hub = _hub_dir(tmp_path)

    result = runner.invoke(
        app, ["doctor", "--kb-dir", str(root / ".kb"), "--hub", str(hub)]
    )

    assert "missing _manifest.yaml" not in result.output, result.output
    assert (root / ".kb" / "demo-code" / "_manifest.yaml").is_file()


def test_doctor_no_refresh_still_reports_the_missing_code_dir(tmp_path, run_git):
    root = _dev_repo(tmp_path, run_git)
    shutil.rmtree(root / ".kb" / "demo-code")
    hub = _hub_dir(tmp_path)

    result = runner.invoke(
        app,
        ["doctor", "--kb-dir", str(root / ".kb"), "--hub", str(hub), "--no-refresh"],
    )

    assert "demo-code' is in the index but missing _manifest.yaml" in result.output
    assert not (root / ".kb" / "demo-code").exists()


def test_svc_note_before_the_seed_does_not_create_code(tmp_path):
    """Important 2: svc_note used to refresh before svcnote.add_note ever
    checks that <repo_id>-svc exists, so a repo that has not run
    `/dev-code-seed` got a -code document and an index.yaml entry as a
    side effect of a command that was always going to fail anyway."""
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text('kind: dev\nrepo_id: "demo"\n', encoding="utf-8")
    (kb / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    result = runner.invoke(app, [
        "svc", "note", "billing-service", "--ticket", "T-1", "--title", "Billing",
        "--kb-dir", str(kb),
    ])
    assert result.exit_code == 1
    assert "demo-svc does not exist" in result.output
    assert "refreshed" not in result.stderr
    assert not (kb / "demo-code").exists()
    assert (kb / "index.yaml").read_text(encoding="utf-8") == "docs: []\n"


def test_publish_refreshes_before_anything_else(tmp_path, monkeypatch):
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text('kind: dev\nrepo_id: "demo"\nhub: ""\n', encoding="utf-8")
    seen: list[Path] = []
    monkeypatch.setattr(cli, "_refresh_dev_code", lambda kb_dir: seen.append(kb_dir))
    runner.invoke(app, ["publish", "--kb-dir", str(kb)])  # fails later: no hub
    assert seen == [kb]
