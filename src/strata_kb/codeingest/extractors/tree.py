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
pruning, and the section says which of the two applies.
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
    ".git", ".venv", "venv", "node_modules", "vendor", "__pycache__", "dist",
    "build", "target", "bin", "obj", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", ".idea", ".vscode", ".kb",
    # Someone else's source, checked out or committed into this tree —
    # same class as `vendor` and `node_modules`. Each of these carries a
    # full `Package.swift`/`pubspec.yaml` per dependency, which deps.py's
    # uncapped Swift/Dart walks (needed for multi-module and melos
    # layouts) would otherwise read as this repo's own direct
    # dependencies. `Pods/` in particular is routinely committed.
    ".build", "Pods", "Carthage", ".dart_tool",
})

_ENTRY_POINT_NAMES = frozenset({
    "main.py", "app.py", "manage.py", "index.js", "index.ts", "main.go",
    "Program.cs", "Application.java", "main.rs", "main.dart", "main.swift",
})

_L2_DEPTH = 2  # L2 directory listing depth
_L3_DEPTH = 4  # L3 full-tree listing depth

# Hard line cap on the L3 listing (≈ 5 000 tokens, C3's ceiling). Depth
# alone does not bound a wide directory — reviewer G grew a 27-file repo's
# L3 to 25 k tokens with one unignored vendor directory.
_L3_MAX_LINES = 600


def relposix(root: Path, path: Path) -> str:
    """Shared path helper: `path` relative to `root` as a `/`-separated
    string. B3-B7 import this rather than re-deriving it."""
    return path.relative_to(root).as_posix()


def _index_cache_key(root: Path) -> tuple[str, int, int] | None:
    """A cache key for `root`'s git index — `(resolved root, .git/index
    mtime_ns, size)` — or `None` when no stable key can be obtained, in
    which case the caller must never cache (I3). `None` covers: `root`
    has no `.git` at all; `.git/index` does not exist for some other
    reason (stat raises); and, deliberately, `root/.git` being a *file*
    rather than a directory — a linked worktree or a submodule's gitlink,
    where the real `.git` directory (and so the real index) lives
    somewhere else entirely. Resolving that indirection to find the real
    index is possible, but this function does not guess where it points —
    keying on the wrong file would either cache a wrong answer forever or
    silently ignore a change to the real index, either of which is worse
    than just not caching that root."""
    resolved = root.resolve()
    git_path = resolved / ".git"
    if not git_path.is_dir():
        return None
    try:
        st = (git_path / "index").stat()
    except OSError:
        return None
    return (str(resolved), st.st_mtime_ns, st.st_size)


# I3: `_git_ls_files` used to run fresh on every call — ~23 times in one
# self-ingest of this repository (walk_tree() is shared by every
# extractor, and `TreeExtractor.extract()` itself called it twice; see
# `_walk_tree_with_git_state` below for the second call). Memoised per
# process, keyed by `_index_cache_key()`: every test in this suite that
# changes what `git ls-files` would report does so through `git
# add`/`git commit`, both of which rewrite `.git/index` and so
# invalidate the key — this answers the spec's stated objection to
# caching ("tests mutate trees between calls in one process") directly,
# rather than working around it with a manual invalidation hook.
#
# R2-6 (re-review round 2): keyed by resolved root alone (not by the
# full `(root, mtime_ns, size)` key), holding only the newest
# `(full_key, result)` pair seen for that root -- one entry per root is
# all one ingest ever needs, since it never revisits an older index
# state of the same root, and it bounds this cache's memory in a
# long-lived process (this project ships an MCP server as a first-class
# entry point, so "the same root ingested repeatedly as its tree
# changes over the server's lifetime" is a real deployment, not a
# hypothetical). A dict keyed by the full `(root, mtime_ns, size)`
# tuple instead would retain one entry per distinct index state that
# root has ever been in, unbounded over the server's lifetime.
_LS_FILES_CACHE: dict[str, tuple[tuple[str, int, int], tuple[bool, list[str]]]] = {}


def _git_ls_files_uncached(root: Path) -> tuple[bool, list[str]]:
    """The actual `git ls-files -z` subprocess call — `_git_ls_files`'s
    memoised wrapper is the only caller other than tests that need to
    instrument the real call count."""
    proc = _git(root, "ls-files", "-z")
    if proc.returncode != 0:
        return False, []
    paths = [p for p in proc.stdout.split("\0") if p]
    return True, sorted(set(paths))


def _git_ls_files(root: Path) -> tuple[bool, list[str]]:
    """Runs `git ls-files -z` under `root`, memoised (see
    `_index_cache_key`/`_LS_FILES_CACHE` above). Returns `(is_git_repo,
    paths)`: `is_git_repo` is whether git succeeded (`root` is inside a
    git worktree); `paths` is the sorted, de-duplicated `/`-separated
    tracked paths, empty when git succeeded but nothing is tracked.
    Deduplicated because an unresolved merge conflict makes `git
    ls-files` print a conflicted path once per index stage
    (base/ours/theirs) — without this, that path would be listed (and
    counted, and re-parsed by every consuming extractor) 3x. `-z` keeps
    non-ASCII names unquoted.

    Split out from `tracked_files()` so `_walk_tree_with_git_state()` (and
    through it, `TreeExtractor.extract()`) can tell "not a repository"
    apart from "a repository with nothing tracked" for its summary/
    warning wording, while `tracked_files()` keeps returning a single
    `None` for both (R2-5, re-review round 2: `tracked_files()` itself
    has had no `src/` caller since `_walk_tree_with_git_state()` started
    calling this function directly — see `tracked_files()`'s own
    docstring)."""
    key = _index_cache_key(root)
    if key is None:
        return _git_ls_files_uncached(root)
    root_key = key[0]
    entry = _LS_FILES_CACHE.get(root_key)
    if entry is not None and entry[0] == key:
        return entry[1]
    result = _git_ls_files_uncached(root)
    _LS_FILES_CACHE[root_key] = (key, result)
    return result


def tracked_files(root: Path) -> list[str] | None:
    """`git ls-files` under `root`, as sorted, de-duplicated `/`-separated
    paths relative to `root` — or `None` when that listing cannot stand in
    for the tree: git failed (not a repository) or listed nothing (a
    repository with no tracked file under `root`: a brand-new checkout, or
    the wrong root — an empty tree would be a lie). See `_git_ls_files` for
    the dedup rationale and the `-z` note.

    R2-5 (re-review round 2): this has no `src/` caller — `walk_tree()`
    was rewritten to call `_walk_tree_with_git_state()`, which calls
    `_git_ls_files()` directly (it needs `is_repo` and "has tracked
    paths" as two separate facts, which this function's single collapsed
    `None` can't give it) — so this function is now a test/diagnostic
    entry point only: `tests/test_codeingest_extractors.py` calls it
    directly to assert the merge-conflict dedup independently of the
    rest of the tree-building pipeline. Kept rather than deleted because
    that assertion reads more clearly against this function's own
    simple, direct contract than against `_git_ls_files`'s two-tuple one,
    and removing a still-tested, still-documented public function for a
    docstring fix alone is not worth the churn."""
    is_repo, paths = _git_ls_files(root)
    if not is_repo:
        return None
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


def _os_walk_entries(
    root: Path, resolved_kb_dir: Path | None
) -> list[tuple[int, Path, list[str]]]:
    """The `os.walk`-based fallback tree — used both when `root` is not a
    git repository at all and when it is one with nothing tracked yet —
    pruned exactly like the `git ls-files` branch. Factored out so
    `_walk_tree_with_git_state()`'s two non-tracked-file branches share
    one copy of this loop rather than two."""
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


def _walk_tree_with_git_state(
    root: Path, kb_dir: Path | None = None
) -> tuple[list[tuple[int, Path, list[str]]], bool, bool]:
    """Does everything `walk_tree()` (below) does, but also returns
    `(is_repo, has_tracked)` — the two facts `TreeExtractor.extract()`
    needs to word its "not a git repository" vs. "repository with
    nothing tracked" summary/warning (see `_git_ls_files`'s docstring).
    Giving `extract()` this function directly, instead of it calling
    `walk_tree()` and then separately calling `_git_ls_files()` again
    (I3), means the whole ingest run's very first `walk_tree`-family call
    is the only one that can ever miss `_git_ls_files`'s cache — every
    other extractor's own `walk_tree()` call below hits it. `walk_tree()`
    itself just discards the extra two values; every other caller is
    unaffected."""
    resolved_kb_dir: Path | None = None
    if kb_dir is not None:
        resolved_root = root.resolve()
        candidate = (kb_dir if kb_dir.is_absolute() else root / kb_dir).resolve()
        if resolved_root in candidate.parents:
            resolved_kb_dir = candidate

    is_repo, tracked_paths = _git_ls_files(root)
    if is_repo and tracked_paths:
        entries = _entries_from_tracked(root.resolve(), tracked_paths, resolved_kb_dir)
        return entries, True, True
    return _os_walk_entries(root, resolved_kb_dir), is_repo, False


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
    repository with at least one tracked file (see `_walk_tree_with_git_state`,
    which this function is a thin wrapper over); otherwise from
    `os.walk`. Both branches apply the same prunes and return the same
    shape.

    Returns `(depth, dir_relpath, sorted_filenames)` for every directory —
    root included, at depth 0 — in a stable preorder: `os.walk` recurses in
    the order of `dirnames`, which is sorted (then filtered) in place before
    each recursive step, so the traversal itself is already alphabetical at
    every level regardless of OS or underlying filesystem order.
    """
    entries, _is_repo, _has_tracked = _walk_tree_with_git_state(root, kb_dir)
    return entries


def _detect_entry_points(
    root: Path, entries: list[tuple[int, Path, list[str]]]
) -> tuple[list[str], list[str]]:
    """(file entry points, console scripts). Files are repo-relative paths
    whose basename is in `_ENTRY_POINT_NAMES`; console scripts are the
    `[project.scripts]` entries rendered `name = module:attr` — kept
    apart because a script *name* is not a path."""
    found: set[str] = set()
    for _depth, rel, filenames in entries:
        for name in filenames:
            if name in _ENTRY_POINT_NAMES:
                found.add(relposix(root, root / rel / name))

    console: list[str] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
            data = {}
        project = data.get("project", {})
        scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
        if isinstance(scripts, dict):
            console = [f"{k} = {scripts[k]}" for k in sorted(scripts)]

    return sorted(found), console


def _render_l2(root: Path, entries: list[tuple[int, Path, list[str]]]) -> str:
    lines = [
        f"{'  ' * (depth - 1)}- {relposix(root, root / rel)}/"
        for depth, rel, _filenames in entries
        if rel != Path(".") and depth <= _L2_DEPTH
    ]
    return "\n".join(lines)


def _render_l3(root: Path, entries: list[tuple[int, Path, list[str]]]) -> str:
    """Rendered listing capped at `_L3_MAX_LINES` lines. When truncated, a
    trailing marker line names the first dropped entry
    (`lines[_L3_MAX_LINES]`) so a reader can tell *where* the real tree
    kept going, not just how much was lost — entries arrive in a stable
    alphabetical preorder (`walk_tree`), so the entry named here is
    deterministic across machines. (M6: this used to also return the
    `omitted` count for a caller that only ever discarded it — the marker
    line above already carries that number for anyone reading the
    rendered text, so there was nothing left for a second, dead return
    value to do.)"""
    lines: list[str] = []
    for depth, rel, filenames in entries:
        if depth > _L3_DEPTH:
            continue
        if rel != Path("."):
            lines.append(f"{'  ' * (depth - 1)}- {relposix(root, root / rel)}/")
        file_indent = "  " * depth
        lines.extend(f"{file_indent}- {name}" for name in filenames)
    omitted = max(0, len(lines) - _L3_MAX_LINES)
    body = "\n".join(lines[:_L3_MAX_LINES])
    if omitted:
        first_dropped = lines[_L3_MAX_LINES].strip().removeprefix("- ")
        noun = "entry" if omitted == 1 else "entries"
        body += (
            f"\n# … {omitted} more {noun} omitted from `{first_dropped}` "
            f"onward (capped at {_L3_MAX_LINES} lines)"
        )
    return body


class TreeExtractor:
    name = "tree"

    def detect(self, root: Path) -> bool:
        # Always fires — a bare directory listing alone is never, by
        # itself, evidence that this is a codebase, which is exactly why
        # core.run()'s zero-detection rule excludes "tree" from its check.
        return True

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        # Calls `_walk_tree_with_git_state()` directly, not the public
        # `walk_tree()` followed by its own separate `_git_ls_files()`
        # call (I3) -- the `(is_repo, tracked)` pair below used to cost a
        # second `git ls-files` subprocess purely to distinguish "not a
        # repository" from "a repository with nothing tracked" for the
        # wording further down, information the entries-building call
        # already had.
        entries, is_repo, tracked = _walk_tree_with_git_state(root, opts.kb_dir)
        n_dirs = sum(1 for _depth, rel, _filenames in entries if rel != Path("."))
        n_files = sum(len(filenames) for _depth, _rel, filenames in entries)
        entry_points, console_scripts = _detect_entry_points(root, entries)

        l2_md = (
            "Directory layout (depth 2):\n\n"
            f"{_render_l2(root, entries)}\n\n"
            "Detected entry points:\n\n"
            + ("\n".join(f"- {ep}" for ep in entry_points) or "- none detected")
            + "\n\nConsole scripts (pyproject [project.scripts]):\n\n"
            + ("\n".join(f"- {cs}" for cs in console_scripts) or "- none detected")
            + "\n"
        )
        # Two markers keep the fenced block from silently disagreeing with
        # the summary's whole-tree counts: one names the depth-4 cut (it
        # only names its cap — entries it drops are never counted, here or
        # anywhere else); the other names the _L3_MAX_LINES cut along with
        # how many lines and which entry it dropped first. Both live inside
        # the fence so neither can register as a pipe table.
        body = _render_l3(root, entries)
        l3_md = "```\n# tree, capped at depth 4\n" + body + "\n```\n"

        # `is_repo`/`tracked` (from `_walk_tree_with_git_state` above) tell
        # apart "not a repository" from "a repository with nothing
        # tracked" for the wording below -- the same distinction
        # `tracked_files(root) is not None` alone can't make, since that
        # function collapses both causes into one `None`. See
        # `_git_ls_files`'s docstring.
        warnings: list[str] = []
        if not is_repo:
            files_phrase = f"{n_files} files (not a git repository — listing unfiltered)"
            warnings.append(
                f"{root} is not a git repository — the tree is an unfiltered "
                "directory walk, not the tracked files"
            )
        elif not tracked:
            files_phrase = f"{n_files} files (no tracked files — listing unfiltered)"
            warnings.append(
                f"{root} is inside a git repository with no tracked files "
                "under it — the tree is an unfiltered directory walk, not "
                "the tracked files"
            )
        else:
            files_phrase = f"{n_files} tracked files"

        summary = (
            f"Repository layout: {n_dirs} directories, {files_phrase}, "
            f"entry points: {', '.join(entry_points) or 'none detected'}; "
            f"console scripts: "
            f"{', '.join(cs.split(' = ', 1)[0] for cs in console_scripts) or 'none detected'}."
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
