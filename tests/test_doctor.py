from pathlib import Path

from center_kb import doctor, gitio, kbcontext, models
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


def test_corrupt_index_errors(fixture_kb: Path):
    (fixture_kb / "index.yaml").write_text("docs: [1, 2\n", encoding="utf-8")
    issues = check_kb(fixture_kb)
    assert any(
        i.level == "error" and "index.yaml" in i.message and "corrupt" in i.message
        for i in issues
    )
    # multi-line ParserError text must be collapsed to a single scannable line
    assert all("\n" not in i.message for i in issues)


def test_corrupt_manifest_does_not_abort_other_docs(fixture_kb: Path):
    # A second, otherwise-clean doc with a real (unrelated) problem, so we can
    # prove check_kb keeps checking docs after the corrupt manifest instead
    # of aborting the whole run.
    second_dir = fixture_kb / "second-doc"
    second_dir.mkdir()
    (second_dir / "ch1.md").write_text("## 2.1 Foo\n\nCondensed.\n", encoding="utf-8")
    models.save_yaml_model(
        second_dir / "_manifest.yaml",
        models.Manifest(
            id="second-doc",
            title="Second Doc",
            sections=[
                models.SectionEntry(
                    id="2.1", title="Foo", file="ch1", status="summarized"
                )
            ],
        ),
    )  # no ch1.raw.md -> a genuine "missing L3 file" issue
    index_path = fixture_kb / "index.yaml"
    index = models.load_yaml_model(index_path, models.KBIndex)
    index.docs.append(models.IndexEntry(id="second-doc", title="Second Doc"))
    models.save_yaml_model(index_path, index)

    (fixture_kb / "demo-doc" / "_manifest.yaml").write_text(
        "id: [1, 2\n", encoding="utf-8"
    )

    issues = check_kb(fixture_kb)
    errors = _errors(issues)
    assert any("demo-doc" in m and "corrupt" in m for m in errors)
    assert any("second-doc" in m and "ch1.raw.md" in m for m in errors)
    assert all("\n" not in m for m in errors)


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


def test_check_kind_warns_when_missing(tmp_path):
    from center_kb.doctor import check_kind

    # no config at all -> warn
    issues = check_kind(tmp_path)
    assert [i.level for i in issues] == ["warning"]
    assert "kind" in issues[0].message

    # kind present -> clean
    (tmp_path / "config.yaml").write_text("kind: hub\nhub: '.'\n", encoding="utf-8")
    assert check_kind(tmp_path) == []

    # invalid kind value -> error, not a crash
    (tmp_path / "config.yaml").write_text("kind: server\n", encoding="utf-8")
    issues = check_kind(tmp_path)
    assert [i.level for i in issues] == ["error"]


def _hub_cfg(tmp_path, block: str) -> Path:
    kb = tmp_path / ".kb"
    kb.mkdir(parents=True, exist_ok=True)
    (kb / "config.yaml").write_text("kind: hub\n" + block, encoding="utf-8")
    return kb


def test_asset_store_none_mode_no_issues(tmp_path):
    kb = _hub_cfg(tmp_path, "asset_store:\n  mode: none\n")
    assert doctor.check_asset_store(kb, None) == []


def test_asset_store_missing_block_no_issues(tmp_path):
    kb = _hub_cfg(tmp_path, "")
    assert doctor.check_asset_store(kb, None) == []


def test_asset_store_s3_empty_bucket_errors(tmp_path):
    kb = _hub_cfg(tmp_path, "asset_store:\n  mode: s3\n")
    issues = doctor.check_asset_store(kb, None)
    assert any(i.level == "error" and "bucket" in i.message for i in issues)


def test_asset_store_s3_probe_ok(tmp_path):
    from center_kb import assetstore

    kb = _hub_cfg(tmp_path, "asset_store:\n  mode: s3\n  bucket: b\n")
    assert doctor.check_asset_store(kb, None, store=assetstore.MemoryStore()) == []


def test_asset_store_s3_probe_failure_errors(tmp_path):
    from center_kb import assetstore

    class _Down(assetstore.MemoryStore):
        def exists(self, name):
            raise assetstore.AssetStoreError("connect timeout")

    kb = _hub_cfg(tmp_path, "asset_store:\n  mode: s3\n  bucket: b\n")
    issues = doctor.check_asset_store(kb, None, store=_Down())
    assert any(i.level == "error" and "connect timeout" in i.message for i in issues)


def test_asset_store_none_mode_size_warning(tmp_path, monkeypatch):
    kb = _hub_cfg(tmp_path, "asset_store:\n  mode: none\n")
    assets = kb / "doc1" / "assets"
    assets.mkdir(parents=True)
    (assets / ("a" * 64 + ".png")).write_bytes(b"x" * 2048)
    monkeypatch.setattr(doctor, "ASSET_SIZE_WARN_BYTES", 1024)
    issues = doctor.check_asset_store(kb, None)
    assert any(i.level == "warning" and "s3" in i.message for i in issues)
