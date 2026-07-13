from pathlib import Path

from center_kb import gitio, kbcontext, models
from center_kb.doctor import check_context, check_kb
from center_kb.hub import HubHandle


def _errors(issues):
    return [i.message for i in issues if i.level == "error"]


def _warnings(issues):
    return [i.message for i in issues if i.level == "warning"]


def test_clean_kb_no_issues(fixture_kb: Path):
    assert check_kb(fixture_kb) == []


def test_missing_index(tmp_path: Path):
    issues = check_kb(tmp_path)
    assert any("index.yaml" in m for m in _errors(issues))


def test_doc_in_index_without_manifest(fixture_kb: Path):
    (fixture_kb / "demo-doc" / "_manifest.yaml").unlink()
    issues = check_kb(fixture_kb)
    assert any("_manifest.yaml" in m for m in _errors(issues))


def test_manifest_dir_not_in_index(fixture_kb: Path):
    orphan = fixture_kb / "doc-x"
    orphan.mkdir()
    models.save_yaml_model(
        orphan / "_manifest.yaml", models.Manifest(id="doc-x", title="Unknown")
    )
    issues = check_kb(fixture_kb)
    assert any("doc-x" in m for m in _errors(issues))


def test_section_file_missing(fixture_kb: Path):
    (fixture_kb / "demo-doc" / "ch1-records.raw.md").unlink()
    issues = check_kb(fixture_kb)
    assert any("ch1-records.raw.md" in m for m in _errors(issues))


def test_section_not_sliceable(fixture_kb: Path):
    l2 = fixture_kb / "demo-doc" / "ch1-records.md"
    l2.write_text("## 9.9 Other\n\nother content", encoding="utf-8")
    issues = check_kb(fixture_kb)
    assert any("1.1" in m for m in _errors(issues))


def test_orphan_md_file_warns(fixture_kb: Path):
    (fixture_kb / "demo-doc" / "orphaned.md").write_text("## x", encoding="utf-8")
    issues = check_kb(fixture_kb)
    assert any("orphaned.md" in m for m in _warnings(issues))


def test_pending_sections_warn(fixture_kb: Path):
    manifest_path = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].status = "pending"
    models.save_yaml_model(manifest_path, manifest)
    issues = check_kb(fixture_kb)
    assert any("pending" in m for m in _warnings(issues))


def test_check_context_stale_is_warning(fed_hub):
    hub = HubHandle(root=fed_hub)
    block, _ = kbcontext.build_context_block(hub, ["arinc-kb:arinc-424 §5.3"])
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8") + "\nEdited after publish.\n", encoding="utf-8"
    )
    issues, results = check_context(block, hub)
    assert results[0].status == "stale"
    assert _warnings(issues) and not _errors(issues)


def test_check_context_broken_is_error(fed_hub):
    hub = HubHandle(root=fed_hub)
    rev = gitio.head_commit(gitio.git_root(fed_hub))
    block = f"kb-context:\n  version: {rev}\n  refs:\n    - arinc-kb:arinc-424 §9.9\n"
    issues, results = check_context(block, hub)
    assert results[0].status == "broken"
    assert _errors(issues)


def test_check_context_bad_block_is_error(fed_hub):
    hub = HubHandle(root=fed_hub)
    issues, results = check_context("no block here", hub)
    assert _errors(issues) and results == []
