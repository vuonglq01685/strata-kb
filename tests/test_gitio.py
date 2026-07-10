from pathlib import Path

import pytest

from aero_kb import gitio


def test_git_root_finds_repo_from_kb_dir(git_kb):
    assert gitio.git_root(git_kb["kb"]) == git_kb["root"]


def test_git_root_raises_outside_repo(tmp_path: Path):
    with pytest.raises(gitio.GitError):
        gitio.git_root(tmp_path)


def test_head_commit_returns_short_hash(git_kb):
    assert gitio.head_commit(git_kb["root"]) == git_kb["rev2"]


def test_rev_exists(git_kb):
    assert gitio.rev_exists(git_kb["root"], git_kb["rev1"])
    assert not gitio.rev_exists(git_kb["root"], "deadbeef")


def test_read_at_returns_old_content(git_kb):
    path = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    old = gitio.read_at(git_kb["root"], git_kb["rev1"], path)
    assert "designation and type fields" in old
    new = gitio.read_at(git_kb["root"], git_kb["rev2"], path)
    assert "NEW multiple code field" in new


def test_read_at_missing_file_returns_none(git_kb):
    path = git_kb["kb"] / "demo-doc" / "khong-ton-tai.md"
    assert gitio.read_at(git_kb["root"], git_kb["rev1"], path) is None


def test_read_at_bad_rev_raises(git_kb):
    path = git_kb["kb"] / "index.yaml"
    with pytest.raises(gitio.GitError):
        gitio.read_at(git_kb["root"], "deadbeef", path)


def test_read_at_path_outside_repo_raises(git_kb, tmp_path_factory):
    outside = tmp_path_factory.mktemp("ngoai") / "x.md"
    with pytest.raises(gitio.GitError):
        gitio.read_at(git_kb["root"], git_kb["rev1"], outside)


def test_is_dirty(git_kb):
    assert not gitio.is_dirty(git_kb["root"], git_kb["kb"])
    (git_kb["kb"] / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    assert gitio.is_dirty(git_kb["root"], git_kb["kb"])
