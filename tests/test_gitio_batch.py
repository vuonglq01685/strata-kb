"""2026-10-10 review §6.2 F8: `kb resolve` started four git processes per
ref. `gitio.BatchReader` serves every (rev, path) read of one resolve from
one `git cat-file --batch` process, with `read_at`'s exact contract."""
from __future__ import annotations

import subprocess

import pytest

from strata_kb import gitio


@pytest.fixture
def repo(tmp_path, run_git):
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "user.name", "t")
    run_git(tmp_path, "config", "user.email", "t@t")
    run_git(tmp_path, "config", "core.autocrlf", "false")
    (tmp_path / "a.md").write_text("first\n", encoding="utf-8")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "crlf.md").write_bytes("x\r\ny é\r\n".encode())
    run_git(tmp_path, "add", "-A")
    run_git(tmp_path, "commit", "-m", "one")
    rev1 = run_git(tmp_path, "rev-parse", "HEAD").strip()
    (tmp_path / "a.md").write_text("second\n", encoding="utf-8")
    run_git(tmp_path, "commit", "-am", "two")
    return tmp_path, rev1


@pytest.mark.parametrize("rel", ["a.md", "d/crlf.md", "missing.md"])
@pytest.mark.parametrize("rev", ["HEAD", "HEAD~1"])
def test_batch_reads_equal_read_at(repo, rel, rev):
    root, _ = repo
    with gitio.BatchReader(root) as reader:
        assert reader.read_at(rev, root / rel) == gitio.read_at(root, rev, root / rel)


def test_a_directory_reads_as_absent(repo):
    """`git show` prints a tree listing for a directory; no caller reads one,
    and a listing is not file content -- the batch reader answers None."""
    root, _ = repo
    with gitio.BatchReader(root) as reader:
        assert reader.read_at("HEAD", root / "d") is None


def test_an_unknown_rev_raises_like_read_at(repo):
    root, _ = repo
    with gitio.BatchReader(root) as reader, pytest.raises(gitio.GitError, match="does not exist"):
        reader.read_at("0" * 40, root / "a.md")


def test_one_process_serves_every_read(repo, monkeypatch):
    root, rev1 = repo
    spawned = []
    real = subprocess.Popen

    def counting(*a, **k):
        spawned.append(a[0])
        return real(*a, **k)

    monkeypatch.setattr(gitio.subprocess, "Popen", counting)
    with gitio.BatchReader(root) as reader:
        for _ in range(3):
            for rev in ("HEAD", rev1):
                reader.read_at(rev, root / "a.md")
                reader.read_at(rev, root / "d" / "crlf.md")
    cat_files = [a for a in spawned if "cat-file" in a]
    assert cat_files == [["git", "cat-file", "--batch"]]
    assert len(spawned) == 3  # + one rev-parse per distinct rev


def test_resolve_runs_a_constant_number_of_git_processes(fed_hub, monkeypatch):
    """5 refs used to cost 22 git processes."""
    from strata_kb.hub import HubHandle
    from strata_kb import kbcontext
    from strata_kb.kbcontext import build_context_block
    from strata_kb.resolve import resolve_refs

    hub = HubHandle(root=fed_hub)
    refs = ["icao-kb:icao-annex-2 §1.1", "arinc-kb:arinc-424 §5.3"] * 3
    block, _ = build_context_block(hub, refs)
    ctx = kbcontext.parse(block)
    runs, popens = [], []
    real_run, real_popen = gitio._run, subprocess.Popen
    monkeypatch.setattr(gitio, "_run", lambda *a: runs.append(a[1:]) or real_run(*a))
    monkeypatch.setattr(
        gitio.subprocess, "Popen", lambda *a, **k: popens.append(a[0]) or real_popen(*a, **k)
    )
    results = resolve_refs(hub, ctx)
    assert {r.status for r in results} == {"ok"}
    assert [a for a in popens if "cat-file" in a] == [["git", "cat-file", "--batch"]]
    # git_root + the one rev-parse of the pinned version + cat-file, for 6 refs
    assert len(popens) <= 3
