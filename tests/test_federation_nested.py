# tests/test_federation_nested.py
from pathlib import Path

from center_kb import federation
from tests.conftest import make_fed_entry


def _make_nested_hub(tmp_path: Path) -> Path:
    """federation/ có 1 entry phẳng + 2 entry lồng dưới namespace mid/."""
    fed = tmp_path / "hub" / "federation"
    make_fed_entry(fed, "repo-flat", "flat-doc")
    make_fed_entry(fed / "mid", "repo-x", "doc-x")
    make_fed_entry(fed / "mid", "repo-y", "doc-y")
    return fed


def test_iter_entry_dirs_finds_flat_and_nested(tmp_path):
    fed = _make_nested_hub(tmp_path)
    ids = [pid for pid, _ in federation.iter_entry_dirs(fed)]
    assert ids == ["mid/repo-x", "mid/repo-y", "repo-flat"]


def test_load_federation_uses_path_id_for_nested_entries(tmp_path):
    fed = _make_nested_hub(tmp_path)
    repos = federation.load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["mid/repo-x", "mid/repo-y", "repo-flat"]
    # kb_dir trỏ đúng thư mục lồng
    assert repos[0].kb_dir == fed / "mid" / "repo-x"


def test_build_federation_index_includes_nested(tmp_path):
    fed = _make_nested_hub(tmp_path)
    idx = federation.build_federation_index(fed)
    assert {(e.repo_id, e.doc_id) for e in idx.docs} == {
        ("mid/repo-x", "doc-x"),
        ("mid/repo-y", "doc-y"),
        ("repo-flat", "flat-doc"),
    }


def test_namespace_dir_without_meta_is_not_an_entry(tmp_path):
    fed = _make_nested_hub(tmp_path)
    # thư mục mid/ không có _meta.yaml/index.yaml → namespace, không phải entry
    assert all(pid != "mid" for pid, _ in federation.iter_entry_dirs(fed))


def test_half_broken_entry_is_skipped_with_warning(tmp_path, caplog):
    fed = _make_nested_hub(tmp_path)
    broken = fed / "mid" / "repo-broken"
    broken.mkdir()
    (broken / "index.yaml").write_text("docs: []\n", encoding="utf-8")  # thiếu _meta.yaml
    ids = [pid for pid, _ in federation.iter_entry_dirs(fed)]
    assert "mid/repo-broken" not in ids
    assert any("mid/repo-broken" in r.message for r in caplog.records)


def test_old_slim_layout_still_skipped(tmp_path, caplog):
    fed = _make_nested_hub(tmp_path)
    slim = fed / "repo-old"
    (slim / "manifests").mkdir(parents=True)
    assert all(pid != "repo-old" for pid, _ in federation.iter_entry_dirs(fed))
    assert any("slim layout" in r.message for r in caplog.records)
