from pathlib import Path

import pytest

from center_kb import gitio


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
    path = git_kb["kb"] / "demo-doc" / "does-not-exist.md"
    assert gitio.read_at(git_kb["root"], git_kb["rev1"], path) is None


def test_read_at_bad_rev_raises(git_kb):
    path = git_kb["kb"] / "index.yaml"
    with pytest.raises(gitio.GitError):
        gitio.read_at(git_kb["root"], "deadbeef", path)


def test_read_at_path_outside_repo_raises(git_kb, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "x.md"
    with pytest.raises(gitio.GitError):
        gitio.read_at(git_kb["root"], git_kb["rev1"], outside)


def test_is_dirty(git_kb):
    assert not gitio.is_dirty(git_kb["root"], git_kb["kb"])
    (git_kb["kb"] / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    assert gitio.is_dirty(git_kb["root"], git_kb["kb"])


# --- Phase 3: clone/pull/commit/push ---


@pytest.fixture
def bare_origin(tmp_path, run_git):
    """Bare repo used as origin + a 'seed' clone that has committed 1 file."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    seed = tmp_path / "seed"
    run_git(tmp_path, "clone", str(bare), "seed")
    (seed / "a.txt").write_text("v1", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "v1")
    run_git(seed, "push", "origin", "HEAD")
    return {"bare": bare, "seed": seed}


def test_clone_and_pull_roundtrip(tmp_path, run_git, bare_origin):
    dest = tmp_path / "clone2"
    gitio.clone(str(bare_origin["bare"]), dest)
    assert (dest / "a.txt").read_text(encoding="utf-8") == "v1"
    # origin has a new commit → pull picks it up
    seed = bare_origin["seed"]
    (seed / "a.txt").write_text("v2", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "v2")
    run_git(seed, "push", "origin", "HEAD")
    gitio.pull(dest)
    assert (dest / "a.txt").read_text(encoding="utf-8") == "v2"


def test_clone_bad_url_raises(tmp_path):
    with pytest.raises(gitio.GitError):
        gitio.clone(str(tmp_path / "does-not-exist"), tmp_path / "dest")


def test_commit_all_returns_false_when_clean(bare_origin, run_git):
    seed = bare_origin["seed"]
    run_git(seed, "config", "user.name", "test")
    run_git(seed, "config", "user.email", "test@test.local")
    assert gitio.commit_all(seed, "no-op") is False


def test_commit_all_and_push(bare_origin, run_git, tmp_path):
    seed = bare_origin["seed"]
    run_git(seed, "config", "user.name", "test")
    run_git(seed, "config", "user.email", "test@test.local")
    (seed / "b.txt").write_text("new", encoding="utf-8")
    assert gitio.commit_all(seed, "add b") is True
    gitio.push(seed)
    check = tmp_path / "check"
    gitio.clone(str(bare_origin["bare"]), check)
    assert (check / "b.txt").exists()


def test_push_rejected_then_pull_rebase_recovers(tmp_path, run_git, bare_origin):
    # clone2 lags behind origin → push fails → pull_rebase → push OK
    dest = tmp_path / "clone2"
    gitio.clone(str(bare_origin["bare"]), dest)
    run_git(dest, "config", "user.name", "test")
    run_git(dest, "config", "user.email", "test@test.local")
    seed = bare_origin["seed"]
    (seed / "a.txt").write_text("upstream", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "upstream")
    run_git(seed, "push", "origin", "HEAD")
    (dest / "c.txt").write_text("local", encoding="utf-8")
    gitio.commit_all(dest, "add c")
    with pytest.raises(gitio.GitError):
        gitio.push(dest)
    gitio.pull_rebase(dest)
    gitio.push(dest)


def test_commit_paths_excludes_files_outside_paths(bare_origin, run_git):
    seed = bare_origin["seed"]
    run_git(seed, "config", "user.name", "test")
    run_git(seed, "config", "user.email", "test@test.local")
    (seed / "federation").mkdir()
    (seed / "federation" / "f.txt").write_text("in", encoding="utf-8")
    (seed / "outside.txt").write_text("out", encoding="utf-8")
    assert gitio.commit_paths(seed, "add federation", ["federation"]) is True
    status = run_git(seed, "status", "--porcelain")
    assert "outside.txt" in status  # still untracked, not committed by mistake
    assert "federation" not in status  # committed, clean


def test_commit_paths_returns_false_when_clean(bare_origin, run_git):
    seed = bare_origin["seed"]
    run_git(seed, "config", "user.name", "test")
    run_git(seed, "config", "user.email", "test@test.local")
    # a.txt is already committed (bare_origin fixture) → nothing changed in scope
    assert gitio.commit_paths(seed, "no-op", ["a.txt"]) is False


def test_has_remote_and_remote_url(bare_origin, fixture_kb, run_git):
    assert gitio.has_remote(bare_origin["seed"]) is True
    assert gitio.remote_url(bare_origin["seed"]).endswith("origin.git")
    root = fixture_kb.parent
    run_git(root, "init")
    assert gitio.has_remote(root) is False
    assert gitio.remote_url(root) == ""
