import sys

import pytest
from starlette.testclient import TestClient

from strata_kb import gitio, intake
from strata_kb.hub import HubHandle


def test_a_clone_left_on_a_publish_branch_is_reported(hub_worktree, run_git, tmp_path):
    # hub_worktree has no remote, so gitio.default_branch falls back to
    # current_branch -- comparing that against itself after a checkout would
    # trivially always match (no bug could ever make this test fail). A real
    # remote with its origin/HEAD symref set gives default_branch an anchor
    # that is independent of what is currently checked out locally, matching
    # how a real hub cache (cloned via gitio.clone, which sets origin/HEAD
    # automatically) behaves.
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(hub_worktree, "remote", "add", "origin", str(origin))
    run_git(hub_worktree, "push", "-u", "origin", "HEAD")
    run_git(hub_worktree, "remote", "set-head", "origin", "-a")
    run_git(hub_worktree, "checkout", "-b", "publish/alpha")
    warnings = intake.check_serving_clone(HubHandle(root=hub_worktree))
    assert any("publish/alpha" in w for w in warnings)
    assert any("git -C" in w for w in warnings)


def test_a_healthy_clone_reports_nothing(hub_worktree):
    assert intake.check_serving_clone(HubHandle(root=hub_worktree)) == []


def test_a_clone_with_a_remote_but_no_origin_head_is_reported(hub_worktree, run_git, tmp_path):
    """I-1: default_branch() falls back to current_branch() when
    refs/remotes/origin/HEAD is unset, so the pre-fix check compared that
    fallback against itself and could never fire here -- exactly the shape
    tests/conftest.py's hub_with_origin fixture builds (a real bare origin,
    pushed to, but no `remote set-head` run against it), which is also what
    hub.resolve_hub's local-path branch hands back for a hub directory used
    directly. This is the exact scenario the earlier
    test_a_clone_left_on_a_publish_branch_is_reported above had to work
    around by adding `remote set-head origin -a`."""
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(hub_worktree, "remote", "add", "origin", str(origin))
    run_git(hub_worktree, "push", "-u", "origin", "HEAD")
    # deliberately no `remote set-head origin -a`
    warnings = intake.check_serving_clone(HubHandle(root=hub_worktree))
    assert any("origin/HEAD" in w for w in warnings)
    assert any("remote set-head origin -a" in w for w in warnings)


def test_startup_prunes_a_stale_worktree(hub_worktree, tmp_path, run_git):
    import shutil

    # Named "ghost-worktree", not "stale" -- pytest names this test's own
    # tmp_path directory "..._a_stale_wo0", which itself contains "stale"
    # and would make a bare "stale" substring check pass regardless of
    # whether pruning actually ran.
    wt = tmp_path / "ghost-worktree"
    gitio.worktree_add(
        hub_worktree, wt, "publish/ghost", gitio.default_branch(hub_worktree), reset=True
    )
    shutil.rmtree(wt)
    intake.check_serving_clone(HubHandle(root=hub_worktree))
    # git worktree list prints POSIX-style forward slashes even on Windows,
    # while str(wt) is backslash-separated there -- compare through
    # as_posix() so the check isn't vacuously true from a separator mismatch.
    listing = gitio._run(hub_worktree, "worktree", "list").stdout.replace("\\", "/")
    assert wt.as_posix() not in listing


def test_a_crashed_worktree_whose_directory_survives_is_reclaimed(hub_worktree, tmp_path):
    """I-5: unlike the stale-worktree case above, a crash between
    worktree_add and worktree_remove can leave the DIRECTORY in place --
    `git worktree prune` alone does not forget a worktree whose directory
    still exists, so the record (and the branch it holds) would otherwise
    be leaked forever, permanently 502-ing every future publish for that
    repo-id ("... is already used by worktree at ...")."""
    wt = tmp_path / "crashed-worktree"
    gitio.worktree_add(
        hub_worktree, wt, "publish/alpha", gitio.default_branch(hub_worktree), reset=True
    )
    assert wt.exists()  # the crash-with-surviving-directory shape

    intake.check_serving_clone(HubHandle(root=hub_worktree))

    listing = gitio._run(hub_worktree, "worktree", "list").stdout.replace("\\", "/")
    assert wt.as_posix() not in listing
    # and the branch is free again for a real publish to reuse
    wt2 = tmp_path / "second-worktree"
    gitio.worktree_add(
        hub_worktree, wt2, "publish/alpha", gitio.default_branch(hub_worktree), reset=True
    )
    gitio.worktree_remove(hub_worktree, wt2)


def test_reclaim_only_touches_publish_branch_worktrees(hub_worktree, tmp_path, run_git):
    """The reclaim pass scopes to `publish/*` -- a worktree on some other
    branch (not this system's shape, but the porcelain parse must not
    assume it) is left alone, and the main worktree (handle.root itself,
    always porcelain entry 0) is never a candidate at all."""
    run_git(hub_worktree, "branch", "not-a-publish-branch")
    wt = tmp_path / "other-branch-worktree"
    gitio.worktree_add(hub_worktree, wt, "not-a-publish-branch", "not-a-publish-branch", reset=False)
    try:
        intake._reclaim_leaked_worktrees(hub_worktree)
        listing = gitio._run(hub_worktree, "worktree", "list").stdout.replace("\\", "/")
        assert wt.as_posix() in listing
        assert hub_worktree.resolve().as_posix() in listing.replace("\\", "/")
    finally:
        gitio.worktree_remove(hub_worktree, wt)


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="reproduces a locked-cache GitError via an open file handle "
    "shutil.rmtree cannot remove -- POSIX permits deleting an open file, "
    "so this shape does not reproduce there; nothing to pin on Linux "
    "without a different locking mechanism",
)
def test_create_app_boots_degraded_on_a_locked_intake_hub_cache(
    hub_worktree, tmp_path, run_git, caplog, monkeypatch
):
    """Appended-section fix (round 4), the most urgent single item: web/app.py's
    create_app used to call hub_mod.resolve_hub(intake_cfg.hub_ref) with no
    guard at all -- a raised gitio.GitError (stale/legacy intake hub cache it
    cannot discard, e.g. a locked file) crashed create_app ITSELF, so the
    WHOLE SERVER failed to boot (/api, /ui and /mcp too, none of which touch
    this cache) over a problem that every per-request resolve_hub call site
    elsewhere already degrades to a clean 503 for. Chosen fix: log and keep
    booting degraded, not refuse to start -- pinned here by asserting
    create_app returns an app (does not raise), logs the cache problem, and
    that app still serves an unrelated route (/api/docs) normally.

    `config` (the /api, /ui, /mcp side) points at the healthy hub_worktree;
    `intake_cfg.hub_ref` (the /intake side) points at a SEPARATE, deliberately
    broken bare+legacy+locked cache -- proving the two are independent and a
    broken intake hub does not take the rest of the app down with it. Same
    locked-cache construction as
    test_resolve_hub_or_503_converts_a_locked_cache_into_a_503_not_a_500 in
    test_intake_core.py and test_manifest_and_status_503_not_500_on_a_locked_hub_cache
    in test_intake_http.py, driven through create_app's boot path instead."""
    from strata_kb import ghapp, hub as hub_mod
    from strata_kb.mcp import ServerConfig
    from strata_kb.web.app import create_app

    bare = tmp_path / "hub.git"
    run_git(tmp_path, "init", "--bare", str(bare))
    seed = tmp_path / "seed"
    seed.mkdir()
    run_git(seed, "init", "-b", "main")
    run_git(seed, "config", "user.email", "t@t")
    run_git(seed, "config", "user.name", "t")
    (seed / ".kb").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "init")
    run_git(seed, "remote", "add", "origin", str(bare))
    run_git(seed, "push", "-u", "origin", "HEAD")

    cache_base = tmp_path / "cache"
    key = hub_mod.cache_key(str(bare))
    legacy = cache_base / key
    run_git(tmp_path, "clone", str(bare), str(legacy))
    run_git(legacy, "config", "core.autocrlf", "true")  # legacy -- needs re-clone

    locked = legacy / "locked.txt"
    locked.write_text("x", encoding="utf-8")
    fp = open(locked, "r", encoding="utf-8")
    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(cache_base))
    try:
        config = ServerConfig(kb_dir=hub_worktree / ".kb", hub=str(hub_worktree))
        intake_cfg = intake.IntakeConfig(
            hub_ref=str(bare),
            audience="https://kb.test",
            creds=ghapp.AppCreds(app_id="1", private_key_pem="unused"),
            status_path=tmp_path / "status.json",
        )
        with caplog.at_level("WARNING", logger="strata_kb.web.app"):
            app = create_app(config, "secret-token", intake_cfg=intake_cfg)
    finally:
        fp.close()

    warnings = "\n".join(r.message for r in caplog.records)
    assert "intake hub cache unusable at startup" in warnings

    client = TestClient(app)
    resp = client.get("/api/docs", headers={"Authorization": "Bearer secret-token"})
    assert resp.status_code == 200, resp.text
