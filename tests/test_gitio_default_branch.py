from __future__ import annotations

import subprocess
from pathlib import Path

from strata_kb import gitio


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _init(root: Path, branch: str) -> None:
    root.mkdir()
    _git(root, "init", "-b", branch)
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("x", encoding="utf-8", newline="\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")


def test_default_branch_asks_the_remote_when_origin_head_is_missing(tmp_path):
    # Arrange: bare remote whose HEAD is main; clone without origin/HEAD, off a feature branch
    seed = tmp_path / "seed"
    _init(seed, "main")
    bare = tmp_path / "remote.git"
    _git(tmp_path, "clone", "--bare", str(seed), str(bare))
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(bare), str(clone))
    _git(clone, "remote", "set-head", "origin", "-d")
    _git(clone, "switch", "-c", "claude/x")

    # Act / Assert
    assert gitio.default_branch(clone) == "main"
    assert _git(clone, "symbolic-ref", "refs/remotes/origin/HEAD").endswith("/main")


def test_default_branch_without_remote_is_current_branch(tmp_path):
    repo = tmp_path / "repo"
    _init(repo, "trunk")

    assert gitio.default_branch(repo) == "trunk"
