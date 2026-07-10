from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """Error calling git: not a repo, rev doesn't exist, path outside the repo."""


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True
    )


def git_root(start: Path) -> Path:
    cwd = start if start.is_dir() else start.parent
    proc = _run(cwd, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        raise GitError(
            f"'{start}' is not inside a git repo — resolve/diff/doctor --context need a KB versioned with Git"
        )
    return Path(proc.stdout.strip()).resolve()


def head_commit(root: Path) -> str:
    proc = _run(root, "rev-parse", "--short", "HEAD")
    if proc.returncode != 0:
        raise GitError(f"could not get HEAD: {proc.stderr.strip()}")
    return proc.stdout.strip()


def rev_exists(root: Path, rev: str) -> bool:
    proc = _run(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return proc.returncode == 0


def _relpath(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise GitError(f"'{path}' is outside git repo '{root}'") from exc


def read_at(root: Path, rev: str, path: Path) -> str | None:
    """File content at a given rev; None if the file doesn't exist at that rev.

    Raises GitError if the rev doesn't exist (distinguishes it from a missing
    file — git show returns the same exit code for both).
    """
    rel = _relpath(root, path)
    if not rev_exists(root, rev):
        raise GitError(f"rev '{rev}' does not exist in the repo (force-push or shallow clone?)")
    proc = _run(root, "show", f"{rev}:{rel}")
    if proc.returncode != 0:
        return None
    return proc.stdout


def is_dirty(root: Path, subpath: Path) -> bool:
    rel = _relpath(root, subpath)
    proc = _run(root, "status", "--porcelain", "--", rel)
    return bool(proc.stdout.strip())


def clone(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "clone", url, str(dest)], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise GitError(f"clone '{url}' failed: {proc.stderr.strip()}")


def pull(root: Path) -> None:
    proc = _run(root, "pull", "--ff-only")
    if proc.returncode != 0:
        raise GitError(f"pull failed: {proc.stderr.strip()}")


def pull_rebase(root: Path) -> None:
    proc = _run(root, "pull", "--rebase")
    if proc.returncode != 0:
        raise GitError(f"pull --rebase failed: {proc.stderr.strip()}")


def commit_all(root: Path, message: str) -> bool:
    """`git add -A` + commit; False if the working tree is clean (nothing to commit)."""
    _run(root, "add", "-A")
    if not _run(root, "status", "--porcelain").stdout.strip():
        return False
    proc = _run(root, "commit", "-m", message)
    if proc.returncode != 0:
        raise GitError(f"commit failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return True


def commit_paths(root: Path, message: str, paths: list[str]) -> bool:
    """`git add -- <paths>` + commit limited to those paths (other paths untouched).

    False if the working tree is clean within the `paths` scope (nothing to commit).
    Use when only a subdirectory (e.g. federation/) should be staged, to avoid
    accidentally committing stray files outside that scope (e.g. the .kb-work/
    cache in a hub clone).
    """
    _run(root, "add", "--", *paths)
    if not _run(root, "status", "--porcelain", "--", *paths).stdout.strip():
        return False
    proc = _run(root, "commit", "-m", message, "--", *paths)
    if proc.returncode != 0:
        raise GitError(f"commit failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return True


def push(root: Path) -> None:
    proc = _run(root, "push", "origin", "HEAD")
    if proc.returncode != 0:
        raise GitError(f"push failed: {proc.stderr.strip()}")


def has_remote(root: Path) -> bool:
    return _run(root, "remote", "get-url", "origin").returncode == 0


def remote_url(root: Path) -> str:
    proc = _run(root, "remote", "get-url", "origin")
    return proc.stdout.strip() if proc.returncode == 0 else ""
