import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from center_kb import gitio, hub


def _force_rmtree(path: Path) -> None:
    """shutil.rmtree, but ignoring the read-only flag git sets on
    .git/objects/** — on Windows, rmtree usually fails with
    PermissionError when deleting these files (doesn't happen on POSIX)."""

    def _clear_readonly(func, target, _exc_info):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onerror=_clear_readonly)


def _use_cache(monkeypatch, tmp_path: Path) -> Path:
    cache = tmp_path / "hub-cache"
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(cache))
    return cache


def test_direct_path_with_kb_used_as_is(hub_worktree):
    handle = hub.resolve_hub(str(hub_worktree))
    assert handle is not None
    assert handle.root == hub_worktree.resolve()
    assert handle.kb_dir == hub_worktree.resolve() / ".kb"
    assert handle.stale is False


def test_url_cloned_into_cache(monkeypatch, tmp_path, hub_worktree, run_git):
    cache = _use_cache(monkeypatch, tmp_path)
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    handle = hub.resolve_hub(str(bare))
    assert handle is not None
    assert str(handle.root).startswith(str(cache))
    assert (handle.kb_dir / "index.yaml").exists()


def test_fresh_cache_skips_pull(monkeypatch, tmp_path, hub_worktree, run_git):
    _use_cache(monkeypatch, tmp_path)
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    h1 = hub.resolve_hub(str(bare))
    # origin gets a new commit right after
    (hub_worktree / "new.txt").write_text("x", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "new")
    run_git(hub_worktree, "push", "origin", "HEAD")
    h2 = hub.resolve_hub(str(bare))  # marker is still fresh → no pull
    assert not (h2.root / "new.txt").exists()
    assert h1.root == h2.root


def test_expired_ttl_pulls(monkeypatch, tmp_path, hub_worktree, run_git):
    _use_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("CENTER_KB_HUB_TTL", "0")
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    hub.resolve_hub(str(bare))
    (hub_worktree / "new.txt").write_text("x", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "new")
    run_git(hub_worktree, "push", "origin", "HEAD")
    h2 = hub.resolve_hub(str(bare))
    assert (h2.root / "new.txt").exists()
    assert h2.stale is False


def test_offline_uses_stale_cache(monkeypatch, tmp_path, hub_worktree, run_git):
    _use_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("CENTER_KB_HUB_TTL", "0")
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    hub.resolve_hub(str(bare))
    _force_rmtree(bare)  # simulate "offline"
    h2 = hub.resolve_hub(str(bare))
    assert h2 is not None
    assert h2.stale is True
    assert (h2.kb_dir / "index.yaml").exists()


def test_unreachable_without_cache_returns_none(monkeypatch, tmp_path):
    _use_cache(monkeypatch, tmp_path)
    assert hub.resolve_hub(str(tmp_path / "does-not-exist.git")) is None


def test_legacy_cache_without_local_autocrlf_false_is_discarded_and_recloned(
    monkeypatch, tmp_path, hub_worktree, run_git
):
    """I6: neutralize_line_endings/core.autocrlf=false is reached only from
    gitio.clone -- nothing healed a cache a pre-Task-12 version left behind,
    so F-D10 stayed open on every existing install. Build one by hand: a
    plain `git clone` with no local core.autocrlf override, under the SAME
    cache_key a credential-free hub ref always hashes to (unchanged by this
    fix)."""
    cache_base = _use_cache(monkeypatch, tmp_path)
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")

    key = hub.cache_key(str(bare))
    legacy = cache_base / key
    run_git(tmp_path, "clone", str(bare), str(legacy))
    # Simulate a pre-Task-12 clone regardless of this machine's own global
    # git config (which may itself already say core.autocrlf=false).
    run_git(legacy, "config", "core.autocrlf", "true")
    # An untracked marker: git clone refuses a non-empty destination, so its
    # disappearance is direct proof the directory was actually replaced, not
    # merely reconfigured in place.
    sentinel = legacy / "sentinel-from-legacy-clone.txt"
    sentinel.write_text("x", encoding="utf-8")

    handle = hub.resolve_hub(str(bare))
    assert handle is not None
    assert handle.root == legacy
    assert not sentinel.exists(), "legacy cache dir was reused, not discarded"
    assert gitio.config_value(legacy, "core.autocrlf") == "false"


def test_legacy_cache_is_discarded_even_when_global_autocrlf_is_already_false(
    monkeypatch, tmp_path, hub_worktree, run_git
):
    """Important 2: _cache_needs_reclone read MERGED git config (no
    --local), so a legacy (pre-Task-12) cache -- whose own local config
    never set core.autocrlf=false -- looked healthy whenever the machine's
    GLOBAL default already read core.autocrlf=false. That is precisely the
    state an operator lands in after applying the F-D10 workaround by hand
    (`git config --global core.autocrlf false`) -- exactly the population
    this fix exists to heal, and the one the old merged read could never
    see was still broken."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global.gitconfig"))
    subprocess.run(
        ["git", "config", "--global", "core.autocrlf", "false"], check=True
    )
    cache_base = _use_cache(monkeypatch, tmp_path)
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")

    key = hub.cache_key(str(bare))
    legacy = cache_base / key
    # plain clone -- does NOT set core.autocrlf locally (the pre-Task-12
    # shape); the machine's global default (set above) is "false" already.
    run_git(tmp_path, "clone", str(bare), str(legacy))
    assert gitio.config_value(legacy, "core.autocrlf", local=True) == ""
    sentinel = legacy / "sentinel-from-legacy-clone.txt"
    sentinel.write_text("x", encoding="utf-8")

    handle = hub.resolve_hub(str(bare))
    assert handle is not None
    assert handle.root == legacy
    assert not sentinel.exists(), "legacy cache was reused instead of discarded"
    assert gitio.config_value(legacy, "core.autocrlf", local=True) == "false"


def test_discard_cache_failure_names_the_cache_and_the_fix(
    monkeypatch, tmp_path, hub_worktree, run_git, undiscardable_hub_cache
):
    """Important 3: before this fix, an OSError from _discard_cache's
    shutil.rmtree escaped resolve_hub raw for the first time ever -- `kb
    publish` printed a bare [WinError 32] naming no way forward. Make a real
    legacy cache genuinely undiscardable (the common Windows cause: a `kb
    query`/MCP/web process still has .kb-work/search.sqlite3 open) and
    confirm the message that reaches the caller names the cache path and
    says to delete it.

    Ruling P49 (round 5): the recipe is the shared `undiscardable_hub_cache`
    fixture, not an open handle hand-rolled here, so this runs on Linux too
    -- the platform the Dockerfile targets and three of _gate.yml T1's five
    legs. See tests/conftest.py for the per-platform mechanism and for the
    one case (POSIX as root) that has none."""
    cache_base = _use_cache(monkeypatch, tmp_path)
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")

    key = hub.cache_key(str(bare))
    legacy = cache_base / key
    run_git(tmp_path, "clone", str(bare), str(legacy))
    run_git(legacy, "config", "core.autocrlf", "true")  # legacy -- needs re-clone

    with undiscardable_hub_cache(legacy):
        with pytest.raises(gitio.GitError) as exc_info:
            hub.resolve_hub(str(bare))
        message = str(exc_info.value)
        assert str(legacy) in message
        assert "delete" in message


def test_discard_cache_passes_the_rmtree_callback_kwarg_this_python_accepts(
    monkeypatch, tmp_path
):
    """Minor 6 (Wave G fix rounds 3-5): `shutil.rmtree`'s `onerror=` is
    deprecated from 3.12 and removed in 3.14; `onexc=` does not exist
    before 3.12. `_discard_cache` therefore picks between them by
    `sys.version_info` -- and round 3's re-review measured that NO test in
    the tree mentioned `onexc` at all, so the whole version gate could be
    deleted (or inverted) with the suite still green. Round 4 declined the
    item for the wrong reason ("it lives in hub.py, outside scope"): it
    needs no hub.py change, only this assertion, and tests/test_hub.py is
    the file it belongs in.

    Asserted against the RUNNING interpreter's own `shutil.rmtree`
    signature as well as against the version rule, so this is live on every
    CI leg rather than dead until 3.12: the version rule catches an
    inverted or deleted gate today (_gate.yml T1 runs 3.11, 3.12 and 3.13),
    and the signature check is what goes red on 3.14, where passing
    `onerror=` stops being a warning and becomes a TypeError.
    """
    import inspect
    import sys

    expected = "onexc" if sys.version_info >= (3, 12) else "onerror"
    # Read the real signature BEFORE monkeypatching rmtree away.
    assert expected in inspect.signature(shutil.rmtree).parameters

    seen: dict = {}

    def fake_rmtree(path, **kwargs):
        seen["path"] = path
        seen["kwargs"] = kwargs

    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)
    cache = tmp_path / "some-cache"
    hub._discard_cache(cache)

    assert seen["path"] == cache
    assert list(seen["kwargs"]) == [expected]
    assert seen["kwargs"][expected] is hub._clear_readonly_and_retry
