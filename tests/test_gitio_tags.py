from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from center_kb import gitio


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("x", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    return root


@pytest.fixture
def remote(tmp_path, repo):
    bare = tmp_path / "remote.git"
    _git(tmp_path, "clone", "--bare", str(repo), str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    return bare


def test_tag_and_push_tag(repo, remote):
    gitio.tag(repo, "kb-publish/20260715-000000")
    gitio.push_tag(repo, "kb-publish/20260715-000000")
    out = _git(remote, "tag", "--list")
    assert "kb-publish/20260715-000000" in out


def test_tag_duplicate_raises(repo):
    gitio.tag(repo, "dup")
    with pytest.raises(gitio.GitError):
        gitio.tag(repo, "dup")
