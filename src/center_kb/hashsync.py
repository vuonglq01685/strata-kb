# src/center_kb/hashsync.py
from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path


class HashSyncError(RuntimeError):
    """A sync path escapes the destination root."""


def build_manifest(root: Path, exclude: tuple[str, ...] = ()) -> dict[str, str]:
    """{posix relpath → sha256 hex} of every regular file under root, keys sorted.

    Hashes raw bytes (no newline normalization) — deterministic per content.
    Symlinks are skipped: federation snapshots hold regular files only.
    """
    if not root.is_dir():
        return {}
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel in exclude:
            continue
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        out[rel] = h.hexdigest()
    return out


def diff_manifests(
    local: dict[str, str], remote: dict[str, str]
) -> tuple[list[str], list[str]]:
    changed = sorted(p for p, h in local.items() if remote.get(p) != h)
    deleted = sorted(p for p in remote if p not in local)
    return changed, deleted


def _guard(dest_root: Path, rel: str) -> Path:
    target = (dest_root / rel).resolve()
    if not target.is_relative_to(dest_root.resolve()):
        raise HashSyncError(f"path '{rel}' escapes '{dest_root}' — refusing")
    return target


def _unlink_force(path: Path) -> None:
    try:
        path.unlink()
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)
        path.unlink()


def apply_sync(
    src_root: Path, dest_root: Path, changed: list[str], deleted: list[str]
) -> None:
    dest_root.mkdir(parents=True, exist_ok=True)
    for rel in changed:
        target = _guard(dest_root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            _unlink_force(target)  # Windows: copy2 onto read-only fails
        shutil.copy2(src_root / rel, target)
    for rel in deleted:
        target = _guard(dest_root, rel)
        if target.exists():
            _unlink_force(target)
    for d in sorted((p for p in dest_root.rglob("*") if p.is_dir()), reverse=True):
        try:
            d.rmdir()  # only succeeds when empty
        except OSError:
            pass
