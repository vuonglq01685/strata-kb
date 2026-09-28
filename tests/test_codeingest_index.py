from strata_kb import models
from strata_kb.codeingest import core
from strata_kb.federation import FederationMeta, load_federation
from tests.fixtures_coderepo import build_code_repo


def test_code_index_entry_is_identical_across_commits(tmp_path, run_git):
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "one")
    opts = core.CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="demo-code", repo_id="demo"
    )
    core.run(opts)
    first = (root / ".kb" / "index.yaml").read_bytes()
    (root / "NOTES.txt").write_text("changed\n", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "two")
    core.run(opts)
    assert (root / ".kb" / "index.yaml").read_bytes() == first
    manifest = models.load_yaml_model(
        root / ".kb" / "demo-code" / "_manifest.yaml", models.Manifest
    )
    assert manifest.revision == run_git(root, "rev-parse", "--short=7", "HEAD")


def _entry(tmp_path, index_revision: str):
    entry = tmp_path / "federation" / "demo"
    (entry / "demo-code").mkdir(parents=True)
    models.save_yaml_model(
        entry / "demo-code" / "_manifest.yaml",
        models.Manifest(id="demo-code", title="t", revision="abc1234"),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id="demo-code", title="t", revision=index_revision)]),
    )
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(repo_id="demo", source_commit="abc1234",
                       published_at="2026-09-25T00:00:00+00:00"),
    )
    return tmp_path / "federation"


def test_load_federation_fills_an_empty_revision_from_the_manifest(tmp_path):
    [repo] = load_federation(_entry(tmp_path, ""))
    assert repo.index.docs[0].revision == "abc1234"


def test_load_federation_keeps_a_recorded_revision(tmp_path):
    [repo] = load_federation(_entry(tmp_path, "fff0000"))
    assert repo.index.docs[0].revision == "fff0000"
