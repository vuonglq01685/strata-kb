from pathlib import Path

import pytest

import strata_kb
from strata_kb.codeingest import sync
from strata_kb.config import load_config
from tests.fixtures_coderepo import build_code_repo


def _pin(root: Path, version: str) -> None:
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "kb-code.yml").write_text(
        f"jobs:\n  publish:\n    steps:\n      - run: pip install strata-kb=={version}\n",
        encoding="utf-8",
    )


def _config(root: Path, extra: str = "") -> Path:
    kb = root / ".kb"
    kb.mkdir(exist_ok=True)
    (kb / "config.yaml").write_text(f'kind: dev\nrepo_id: "demo"\n{extra}', encoding="utf-8")
    return kb


def test_config_without_the_block_has_empty_lists(tmp_path):
    cfg = load_config(_config(tmp_path)).code_ingest
    assert cfg.db == [] and cfg.tags == []


def test_ci_pin_reads_the_workflow_pin(tmp_path):
    _pin(tmp_path, "1.3.0")
    assert sync.ci_pin(tmp_path) == "1.3.0"


def test_ci_pin_is_none_without_the_workflow(tmp_path):
    assert sync.ci_pin(tmp_path) is None


def test_version_note_only_when_the_pin_differs(tmp_path, monkeypatch):
    _pin(tmp_path, "1.3.0")
    monkeypatch.setattr(strata_kb, "__version__", "1.3.0")
    assert sync.version_note(tmp_path) is None
    monkeypatch.setattr(strata_kb, "__version__", "1.4.0")
    note = sync.version_note(tmp_path)
    assert note is not None and "1.4.0" in note and "1.3.0" in note


def test_options_from_config_uses_the_code_ingest_block(tmp_path):
    kb = _config(tmp_path, "code_ingest:\n  db: [data/app.sqlite]\n  tags: [payments]\n")
    opts = sync.options_from_config(tmp_path, kb, "demo")
    assert opts.doc_id == "demo-code"
    assert opts.db_paths == ((tmp_path / "data" / "app.sqlite").resolve(),)
    assert opts.tags == ("payments",)


def test_flags_replace_the_config_lists(tmp_path):
    kb = _config(tmp_path, "code_ingest:\n  db: [data/app.sqlite]\n  tags: [payments]\n")
    opts = sync.options_from_config(
        tmp_path, kb, "demo", db=[Path("other.sqlite")], tags=["x"]
    )
    assert opts.db_paths == ((tmp_path / "other.sqlite").resolve(),)
    assert opts.tags == ("x",)


@pytest.fixture
def repo(tmp_path, run_git):
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    _config(root)
    (root / ".gitignore").write_text(".kb/*-code/\n", encoding="utf-8")
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    return root


def test_regenerates_when_missing_then_is_a_no_op(repo):
    first = sync.ensure_code_fresh(repo / ".kb", "demo")
    assert first.regenerated and first.reason == "missing"
    assert (repo / ".kb" / "demo-code" / "_manifest.yaml").is_file()
    assert not sync.ensure_code_fresh(repo / ".kb", "demo").regenerated


def test_regenerates_after_a_new_commit(repo, run_git):
    sync.ensure_code_fresh(repo / ".kb", "demo")
    (repo / "NOTES.txt").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "two")
    assert sync.ensure_code_fresh(repo / ".kb", "demo").reason == "revision"


def test_regenerates_on_a_tracked_change(repo):
    sync.ensure_code_fresh(repo / ".kb", "demo")
    (repo / "docker-compose.yml").write_text(
        (repo / "docker-compose.yml").read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    assert sync.ensure_code_fresh(repo / ".kb", "demo").reason == "dirty"


def test_an_untracked_file_or_a_kb_edit_does_not_trigger(repo):
    sync.ensure_code_fresh(repo / ".kb", "demo")
    (repo / "scratch.txt").write_text("x\n", encoding="utf-8")
    cfg = repo / ".kb" / "config.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    assert not sync.ensure_code_fresh(repo / ".kb", "demo").regenerated


def test_a_non_git_directory_always_regenerates(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    build_code_repo(root)
    _config(root)
    sync.ensure_code_fresh(root / ".kb", "demo")
    assert sync.ensure_code_fresh(root / ".kb", "demo").reason == "no git"


def test_has_code_doc(repo):
    assert not sync.has_code_doc(repo / ".kb", "demo")
    sync.ensure_code_fresh(repo / ".kb", "demo")
    assert sync.has_code_doc(repo / ".kb", "demo")


def test_extractor_warnings_are_appended_to_the_notes(repo):
    """Important 3: `ensure_code_fresh` is now the main local producer of
    `-code` -- an extractor warning (e.g. an unparseable compose file) must
    reach the operator the same way `kb code-ingest` prints it, not be
    silently discarded because this caller only read `result.notes`."""
    (repo / "compose.broken.yml").write_text("services: [unterminated\n", encoding="utf-8")
    result = sync.ensure_code_fresh(repo / ".kb", "demo")
    assert result.regenerated
    assert result.report is not None and result.report.warnings
    assert result.notes[0].startswith("refreshed demo-code")
    assert any(
        n == f"[warn] {w}" for n in result.notes for w in result.report.warnings
    )
