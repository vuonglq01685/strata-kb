import os
import shutil
import stat
import time
from pathlib import Path

from aero_kb import hub


def _force_rmtree(path: Path) -> None:
    """shutil.rmtree, nhưng bỏ qua flag read-only mà git đặt trên
    .git/objects/** — trên Windows, rmtree thường thất bại với
    PermissionError khi xóa các file này (không xảy ra trên POSIX)."""

    def _clear_readonly(func, target, _exc_info):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onerror=_clear_readonly)


def _use_cache(monkeypatch, tmp_path: Path) -> Path:
    cache = tmp_path / "hub-cache"
    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(cache))
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
    # origin có commit mới ngay sau đó
    (hub_worktree / "new.txt").write_text("x", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "new")
    run_git(hub_worktree, "push", "origin", "HEAD")
    h2 = hub.resolve_hub(str(bare))  # marker còn tươi → không pull
    assert not (h2.root / "new.txt").exists()
    assert h1.root == h2.root


def test_expired_ttl_pulls(monkeypatch, tmp_path, hub_worktree, run_git):
    _use_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("AERO_KB_HUB_TTL", "0")
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
    monkeypatch.setenv("AERO_KB_HUB_TTL", "0")
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    hub.resolve_hub(str(bare))
    _force_rmtree(bare)  # "offline"
    h2 = hub.resolve_hub(str(bare))
    assert h2 is not None
    assert h2.stale is True
    assert (h2.kb_dir / "index.yaml").exists()


def test_unreachable_without_cache_returns_none(monkeypatch, tmp_path):
    _use_cache(monkeypatch, tmp_path)
    assert hub.resolve_hub(str(tmp_path / "khong-ton-tai.git")) is None
