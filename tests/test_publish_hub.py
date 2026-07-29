# tests/test_publish_hub.py
from pathlib import Path

import pytest

from center_kb import publish
from center_kb.hub import HubHandle
from tests.conftest import make_fed_entry


@pytest.fixture
def mid_fed(tmp_path: Path) -> Path:
    """federation/ của hub trung gian: 1 entry phẳng + 1 entry lồng + file tầng đỉnh."""
    fed = tmp_path / "mid" / "federation"
    make_fed_entry(fed, "repo-a", "doc-a")
    make_fed_entry(fed / "leaf-hub", "repo-b", "doc-b")
    (fed / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (fed / "registry.yaml").write_text("repos: {}\n", encoding="utf-8")
    (fed / ".gitkeep").write_text("", encoding="utf-8")
    return fed


@pytest.fixture
def upper(tmp_path: Path) -> HubHandle:
    root = tmp_path / "root-hub"
    (root / "federation").mkdir(parents=True)
    return HubHandle(root=root)


def test_snapshot_federation_mirrors_entries(mid_fed, upper):
    n_docs, changed = publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    assert changed is True
    assert n_docs == 2
    dest = upper.federation_dir / "mid"
    assert (dest / "repo-a" / "index.yaml").exists()
    assert (dest / "repo-a" / "_meta.yaml").exists()  # _meta của leaf mirror verbatim
    assert (dest / "leaf-hub" / "repo-b" / "doc-b" / "_manifest.yaml").exists()


def test_snapshot_federation_excludes_top_level_files(mid_fed, upper):
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    dest = upper.federation_dir / "mid"
    assert not (dest / "index.yaml").exists()      # aggregate index nguồn không đẩy
    assert not (dest / "registry.yaml").exists()
    assert not (dest / ".gitkeep").exists()
    assert not (dest / "_meta.yaml").exists()      # không viết meta gốc


def test_snapshot_federation_noop_when_unchanged(mid_fed, upper):
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    n_docs, changed = publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    assert changed is False
    assert n_docs == 2


def test_snapshot_federation_applies_deletions(mid_fed, upper):
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    import shutil

    shutil.rmtree(mid_fed / "repo-a")
    _, changed = publish._snapshot_federation(mid_fed, upper, "mid", "abc1235")
    assert changed is True
    assert not (upper.federation_dir / "mid" / "repo-a").exists()


def test_snapshot_federation_rejects_escaping_rid(mid_fed, upper):
    with pytest.raises(publish.PublishError):
        publish._snapshot_federation(mid_fed, upper, "../evil", "abc1234")
