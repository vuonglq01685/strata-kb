"""tree extractor — the repository's directory layout and entry points.

Always detects (it is the reason `core.run()`'s zero-detection rule counts
extractors *other than* `tree`: a bare directory listing is never, on its
own, evidence that this is a codebase). Emits exactly one section,
`struct.tree` in the `structure` group, built by `walk_tree()` below — the
files `git ls-files` reports under the root (so a git-ignored virtualenv,
worktree or previous run's output never appears, and two checkouts of the
same commit list the same tree), with `IGNORED_DIRS` (and the caller's
`kb_dir`) pruned on top. A root that is not a git repository, or has no
tracked file, falls back to one deterministic `os.walk` with the same
pruning, and the section says so.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from center_kb.codeingest.core import CodeIngestOptions, CodeSection, ExtractResult, _git

# Shared with every other tree-walking extractor (B3-B7): each of them must
# prune these directories too, or output would depend on whether
# dependencies happen to be installed (a vendored node_modules/package.json,
# .kb/ describing itself on a re-run, ...). `.kb` is excluded here so the KB
# never describes itself — but this only covers the *default* KB directory
# name; a non-default `--kb-dir` is handled by `walk_tree()`'s `kb_dir`
# argument instead, since the actual directory could be named anything.
IGNORED_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    "target", "bin", "obj", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", ".idea", ".vscode", ".kb",
})

_ENTRY_POINT_NAMES = frozenset({
    "main.py", "app.py", "manage.py", "index.js", "index.ts", "main.go",
    "Program.cs", "Application.java",
})

_L2_DEPTH = 2  # L2 directory listing depth
_L3_DEPTH = 4  # L3 full-tree listing depth


def relposix(root: Path, path: Path) -> str:
    """Shared path helper: `path` relative to `root` as a `/`-separated
    string. B3-B7 import this rather than re-deriving it."""
    return path.relative_to(root).as_posix()


def tracked_files(root: Path) -> list[str] | None:
    """`git ls-files` under `root`, as `/`-separated paths relative to
    `root` — or `None` when that listing cannot stand in for the tree:
    git failed (not a repository, git not installed) or listed nothing
    (a repository with no tracked file under `root`: a brand-new
    checkout, or the wrong root — an empty tree would be a lie). `-z`
    keeps non-ASCII names unquoted."""
    proc = _git(root, "ls-files", "-z")
    if proc.returncode != 0:
        return None
    paths = [p for p in proc.stdout.split("\0") if p]
    return paths or None


def _entries_from_tracked(
    resolved_root: Path, tracked: list[str], resolved_kb_dir: Path | None
) -> list[tuple[int, Path, list[str]]]:
    """The same `(depth, rel_dir, sorted_filenames)` preorder `walk_tree`'s
    os.walk branch produces, rebuilt from a tracked-file list. Git does
    not track empty directories, so none appear; every ancestor of a
    kept file does. A file is dropped when any directory component is
    in `IGNORED_DIRS` or its directory is (or lies under) `kb_dir` —
    exactly the two prunes the os.walk branch applies."""
    files_by_dir: dict[tuple[str, ...], list[str]] = {(): []}
    for posix in tracked:
        parts = tuple(posix.split("/"))
        dir_parts, name = parts[:-1], parts[-1]
        if any(part in IGNORED_DIRS for part in dir_parts):
            continue
        if resolved_kb_dir is not None:
            candidate = resolved_root.joinpath(*dir_parts)
            if candidate == resolved_kb_dir or resolved_kb_dir in candidate.parents:
                continue
        for i in range(1, len(dir_parts) + 1):
            files_by_dir.setdefault(dir_parts[:i], [])
        files_by_dir[dir_parts].append(name)
    entries: list[tuple[int, Path, list[str]]] = []
    for dir_parts in sorted(files_by_dir):
        rel = Path(*dir_parts) if dir_parts else Path(".")
        entries.append((len(dir_parts), rel, sorted(files_by_dir[dir_parts])))
    return entries


def walk_tree(
    root: Path, kb_dir: Path | None = None
) -> list[tuple[int, Path, list[str]]]:
    """The one deterministic, pruned tree walk shared by every extractor
    (B3-B7 import this rather than re-implementing the loop).

    Prunes `IGNORED_DIRS` and, when given, the caller's `kb_dir` — resolved
    against `root` if it's relative — provided it actually lies inside
    `root`. Without this, a non-default `--kb-dir` (e.g. `docs/kb`) would
    leak its own generated output into a later run's tree, exactly what the
    `.kb` entry in `IGNORED_DIRS` prevents for the default location. The
    comparison uses `Path.resolve()` + `Path.__eq__`, which is
    case-insensitive on Windows and separator-agnostic everywhere, so it
    isn't defeated by a `--kb-dir` spelled with different case or slashes
    than the directory actually on disk.

    The file list comes from `git ls-files` when `root` is inside a git
    repository with at least one tracked file (see `tracked_files`);
    otherwise from `os.walk`. Both branches apply the same prunes and
    return the same shape.

    Returns `(depth, dir_relpath, sorted_filenames)` for every directory —
    root included, at depth 0 — in a stable preorder: `os.walk` recurses in
    the order of `dirnames`, which is sorted (then filtered) in place before
    each recursive step, so the traversal itself is already alphabetical at
    every level regardless of OS or underlying filesystem order.
    """
    resolved_kb_dir: Path | None = None
    if kb_dir is not None:
        resolved_root = root.resolve()
        candidate = (kb_dir if kb_dir.is_absolute() else root / kb_dir).resolve()
        if resolved_root in candidate.parents:
            resolved_kb_dir = candidate

    tracked = tracked_files(root)
    if tracked is not None:
        return _entries_from_tracked(root.resolve(), tracked, resolved_kb_dir)

    entries: list[tuple[int, Path, list[str]]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames.sort()
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORED_DIRS
            and (resolved_kb_dir is None or (current / d).resolve() != resolved_kb_dir)
        ]
        filenames.sort()
        rel = current.relative_to(root)
        depth = 0 if rel == Path(".") else len(rel.parts)
        entries.append((depth, rel, filenames))
    return entries


def _detect_entry_points(root: Path, entries: list[tuple[int, Path, list[str]]]) -> list[str]:
    found: set[str] = set()
    for _depth, rel, filenames in entries:
        for name in filenames:
            if name in _ENTRY_POINT_NAMES:
                found.add(relposix(root, root / rel / name))

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            data = {}
        scripts = data.get("project", {}).get("scripts", {})
        if isinstance(scripts, dict):
            found.update(scripts.keys())

    return sorted(found)


def _render_l2(root: Path, entries: list[tuple[int, Path, list[str]]]) -> str:
    lines = [
        f"{'  ' * (depth - 1)}- {relposix(root, root / rel)}/"
        for depth, rel, _filenames in entries
        if rel != Path(".") and depth <= _L2_DEPTH
    ]
    return "\n".join(lines)


def _render_l3(root: Path, entries: list[tuple[int, Path, list[str]]]) -> str:
    lines: list[str] = []
    for depth, rel, filenames in entries:
        if depth > _L3_DEPTH:
            continue
        if rel != Path("."):
            lines.append(f"{'  ' * (depth - 1)}- {relposix(root, root / rel)}/")
        file_indent = "  " * depth
        lines.extend(f"{file_indent}- {name}" for name in filenames)
    return "\n".join(lines)


class TreeExtractor:
    name = "tree"

    def detect(self, root: Path) -> bool:
        # Always fires — a bare directory listing alone is never, by
        # itself, evidence that this is a codebase, which is exactly why
        # core.run()'s zero-detection rule excludes "tree" from its check.
        return True

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        entries = walk_tree(root, opts.kb_dir)
        n_dirs = sum(1 for _depth, rel, _filenames in entries if rel != Path("."))
        n_files = sum(len(filenames) for _depth, _rel, filenames in entries)
        entry_points = _detect_entry_points(root, entries)

        l2_md = (
            "Directory layout (depth 2):\n\n"
            f"{_render_l2(root, entries)}\n\n"
            "Detected entry points:\n\n"
            + ("\n".join(f"- {ep}" for ep in entry_points) or "- none detected")
            + "\n"
        )
        # The marker line keeps the fenced block honest about its own cap —
        # without it the summary's whole-tree counts and this listing's
        # depth-4 truncation would silently contradict each other on any
        # repo nested deeper than 4 levels. Kept inside the fence so it can
        # never register as a pipe table.
        l3_md = "```\n# tree, capped at depth 4\n" + _render_l3(root, entries) + "\n```\n"

        warnings: list[str] = []
        if tracked_files(root) is not None:
            files_phrase = f"{n_files} tracked files"
        else:
            files_phrase = f"{n_files} files (not a git repository — listing unfiltered)"
            warnings.append(
                f"{root} is not a git repository — the tree is an unfiltered "
                "directory walk, not the tracked files"
            )

        summary = (
            f"Repository layout: {n_dirs} directories, {files_phrase}, "
            f"entry points: {', '.join(entry_points) or 'none detected'}."
        )

        section = CodeSection(
            id="struct.tree",
            title="Repository tree",
            summary=summary,
            group="structure",
            l2_md=l2_md,
            l3_md=l3_md,
        )
        return ExtractResult(sections=[section], warnings=warnings)
