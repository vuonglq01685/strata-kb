import subprocess
from pathlib import Path

from strata_kb.publish import publish


def _seed_hub(tmp_path, run_git, gitattributes: str | None = None):
    origin = tmp_path / "hub-origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    seed = tmp_path / "hub-seed"
    (seed / ".kb").mkdir(parents=True)
    (seed / "federation").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")
    (seed / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    if gitattributes is not None:
        (seed / ".gitattributes").write_text(
            gitattributes, encoding="utf-8", newline="\n"
        )
    run_git(tmp_path, "init", str(seed))
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "hub v0")
    run_git(seed, "remote", "add", "origin", str(origin))
    run_git(seed, "push", "-u", "origin", "HEAD")
    return origin


def _force_windows_autocrlf(tmp_path, monkeypatch):
    """Simulate Git for Windows' default (core.autocrlf=true) without
    touching the runner's real global config."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global.gitconfig"))
    subprocess.run(
        ["git", "config", "--global", "core.autocrlf", "true"], check=True
    )
    # The isolated GIT_CONFIG_GLOBAL above has no identity in it (unlike the
    # runner's real global config) -- publish() commits inside the hub cache
    # clone via gitio.commit_paths, which carries no -c user.name/email of
    # its own (unlike the run_git test fixture). Without this, the commit
    # inside publish() fails with "Author identity unknown" regardless of
    # the CRLF behaviour under test.
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.local")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.local")


def test_second_publish_from_a_fresh_cache_is_a_no_op_under_global_autocrlf(
    git_kb, tmp_path, run_git, monkeypatch
):
    """I2: the original version of this test reused ONE hub cache clone for
    both publishes (STRATA_KB_HUB_CACHE set once), so the second checkout --
    the only thing able to rewrite line endings -- never happened. Green
    with the clone-time core.autocrlf=false/core.eol=lf fix
    (gitio.py:136-154) deleted, and green with it inverted to
    core.autocrlf=true/core.eol=crlf. Point STRATA_KB_HUB_CACHE at a
    genuinely fresh directory for the second publish (do not shutil.rmtree
    the first -- git's read-only object files raise PermissionError on
    Windows)."""
    origin = _seed_hub(tmp_path, run_git)
    _force_windows_autocrlf(tmp_path, monkeypatch)

    # The Linux-authored-child case F-D10 is actually about: content is LF
    # on disk (as the tool always writes it) -- it is the FRESH cache
    # clone's own checkout that must not silently convert it to CRLF.
    for p in git_kb["kb"].rglob("*.md"):
        data = p.read_bytes()
        if b"\r\n" in data:
            p.write_bytes(data.replace(b"\r\n", b"\n"))

    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(tmp_path / "cache1"))
    publish(git_kb["kb"], str(origin), repo_id="child", mode="direct")
    head1 = run_git(origin, "rev-parse", "HEAD")

    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(tmp_path / "cache2"))
    publish(git_kb["kb"], str(origin), repo_id="child", mode="direct")
    head2 = run_git(origin, "rev-parse", "HEAD")

    assert head2 == head1, "fresh clone caused a spurious re-publish (F-D10)"


def test_gitattributes_exempts_federation_from_normalisation_for_a_crlf_child(
    git_kb, tmp_path, run_git, monkeypatch
):
    """I1: `* text=auto eol=lf` alone in the hub's .gitattributes forces
    every hub checkout back to LF -- for a child whose .kb/ is CRLF on disk
    (any child that predates this fix, checked out on Windows with no
    .gitattributes of its own), that reopens F-D10 on every fresh cache
    clone: a whole-tree diff, a spurious commit, every publish, forever.
    `federation/** -text` (appended last -- git uses the last matching
    pattern) exempts the byte-for-byte mirror from normalisation."""
    gitattrs_path = (
        Path(__file__).resolve().parent.parent
        / "src" / "strata_kb" / "templates" / "init" / "gitattributes.txt"
    )
    origin = _seed_hub(
        tmp_path, run_git, gitattributes=gitattrs_path.read_text(encoding="utf-8")
    )
    _force_windows_autocrlf(tmp_path, monkeypatch)

    # Any child that predates this fix, checked out on Windows: .kb/ is
    # CRLF on disk regardless of what the tool itself would have written.
    for p in git_kb["kb"].rglob("*.md"):
        data = p.read_bytes()
        p.write_bytes(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))

    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(tmp_path / "cache1"))
    publish(git_kb["kb"], str(origin), repo_id="child", mode="direct")
    head1 = run_git(origin, "rev-parse", "HEAD")

    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(tmp_path / "cache2"))
    publish(git_kb["kb"], str(origin), repo_id="child", mode="direct")
    head2 = run_git(origin, "rev-parse", "HEAD")

    assert head2 == head1, (
        "fresh clone caused a spurious re-publish (F-D10 reopened by "
        "text=auto eol=lf normalising the federation/ mirror)"
    )
