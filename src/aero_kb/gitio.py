from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """Lỗi khi gọi git: không phải repo, rev không tồn tại, path ngoài repo."""


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True
    )


def git_root(start: Path) -> Path:
    cwd = start if start.is_dir() else start.parent
    proc = _run(cwd, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        raise GitError(
            f"'{start}' không nằm trong git repo — resolve/diff/doctor --context cần KB được version bằng Git"
        )
    return Path(proc.stdout.strip()).resolve()


def head_commit(root: Path) -> str:
    proc = _run(root, "rev-parse", "--short", "HEAD")
    if proc.returncode != 0:
        raise GitError(f"không lấy được HEAD: {proc.stderr.strip()}")
    return proc.stdout.strip()


def rev_exists(root: Path, rev: str) -> bool:
    proc = _run(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return proc.returncode == 0


def _relpath(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise GitError(f"'{path}' nằm ngoài git repo '{root}'") from exc


def read_at(root: Path, rev: str, path: Path) -> str | None:
    """Nội dung file tại một rev; None nếu file không tồn tại ở rev đó.

    Raise GitError nếu rev không tồn tại (phân biệt với file thiếu —
    git show trả cùng exit code cho cả hai).
    """
    rel = _relpath(root, path)
    if not rev_exists(root, rev):
        raise GitError(f"rev '{rev}' không tồn tại trong repo (force-push hoặc shallow clone?)")
    proc = _run(root, "show", f"{rev}:{rel}")
    if proc.returncode != 0:
        return None
    return proc.stdout


def is_dirty(root: Path, subpath: Path) -> bool:
    rel = _relpath(root, subpath)
    proc = _run(root, "status", "--porcelain", "--", rel)
    return bool(proc.stdout.strip())
