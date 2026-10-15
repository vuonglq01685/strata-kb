"""Package scopes: one per directory that holds a dependency manifest.

A scope is where a package's own code lives (`apps/api`, `.`), labelled
with the frameworks its manifest declares. Later extractors use
`scope_of()` to attribute a source file to its package.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from strata_kb.codeingest.extractors import deps
from strata_kb.codeingest.extractors.tree import walk_tree

_MANIFEST_NAMES = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "go.mod",
        "composer.json",
        "Cargo.toml",
        "Package.swift",
        "pubspec.yaml",
    }
)


@dataclass(frozen=True)
class Scope:
    path: str  # repo-relative posix dir, or "."
    manifest: str  # first manifest file name in the dir (sorted)
    frameworks: tuple[str, ...]


def _is_manifest(name: str) -> bool:
    return (
        name in _MANIFEST_NAMES
        or name.endswith(".csproj")
        or fnmatch.fnmatch(name, "requirements*.txt")
    )


def find_scopes(root: Path, kb_dir: Path) -> list[Scope]:
    """One `Scope` per manifest directory, sorted by path; several
    manifests in one directory merge into a single scope."""
    # `walk_tree` is `tracked_files` with the `os.walk` fallback, both
    # already pruned of `IGNORED_DIRS` and `kb_dir`.
    by_dir: dict[str, list[str]] = {}
    for _depth, rel, names in walk_tree(root, kb_dir):
        found = [n for n in names if _is_manifest(n)]
        if found:
            by_dir[rel.as_posix()] = found
    scopes = []
    for directory in sorted(by_dir):
        names = sorted(by_dir[directory])
        base = root if directory == "." else root / directory
        dep_names = [n for name in names for n in deps.manifest_dep_names(base / name)]
        scopes.append(
            Scope(directory, names[0], tuple(deps.detect_frameworks(dep_names)))
        )
    return scopes


def scope_of(scopes: list[Scope], rel_path: str) -> Scope | None:
    """The scope with the longest path prefix of `rel_path` (`.` matches all)."""
    inside = [
        sc for sc in scopes if sc.path == "." or rel_path.startswith(sc.path + "/")
    ]
    # root ("." has length 1) must rank below any real dir, even a 1-char one
    return max(
        inside, key=lambda sc: -1 if sc.path == "." else len(sc.path), default=None
    )
