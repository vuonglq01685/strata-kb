"""Module-specifier resolution for the JS/TS route adapters: which tracked
repo file does `import ... from '<spec>'` name?

Handles, in order: relative paths; `tsconfig.json` `compilerOptions.paths` and
`baseUrl` (nearest config up from the importing file, `extends` followed one
level); workspace packages (a `package.json` `name` -> its directory, entry
from `exports["."]` / `types` / `main`, else `src/index.ts` / `index.ts`).
Anything else (a registry package) resolves to None.

shortcut: `extends` is followed one level and only as a relative path;
`exports` conditions are searched depth-first for the first string, and
subpath exports other than "." are not read (a `<pkg>/sub` import tries
`<dir>/sub` and `<dir>/src/sub`).
"""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path

from strata_kb.codeingest.extractors._routes_jsutil import (
    _EXTS,
    _SCRIPT_EXT_RE,
    _read,
)

_STRING_OR_COMMENT = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.S)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_ENTRY_KEYS = ("types", "import", "require", "default")


def _jsonc(data: bytes | None) -> dict:
    if data is None:
        return {}
    text = _STRING_OR_COMMENT.sub(
        lambda m: m.group(1) or "", data.decode("utf-8", "replace")
    )
    try:
        loaded = json.loads(_TRAILING_COMMA.sub(r"\1", text))
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _first_string(node: object) -> str | None:
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        for key in (*_ENTRY_KEYS, *node):
            found = _first_string(node.get(key))
            if found:
                return found
    return None


class ModuleResolver:
    def __init__(self, root: Path, repo_files: list[str], sources: frozenset[str]):
        self._root = root
        self._sources = sources  # JS/TS files a specifier may resolve to
        self._all = frozenset(repo_files)
        self._paths: dict[str, tuple[str, dict[str, list[str]]] | None] = {}
        self._packages: dict[str, str] | None = None

    def resolve(self, rel: str, spec: str) -> str | None:
        if spec.startswith("."):
            return self._file(posixpath.join(posixpath.dirname(rel), spec))
        return self._tsconfig(rel, spec) or self._package(spec)

    # -- files ---------------------------------------------------------------

    def _file(self, base: str) -> str | None:
        base = posixpath.normpath(base)
        stem = _SCRIPT_EXT_RE.sub("", base)
        candidates = [
            base,
            *(stem + e for e in _EXTS),
            *(f"{base}/index{e}" for e in _EXTS),
            # a typings-only module, last so a real source file wins
            stem + ".d.ts",
            f"{base}/index.d.ts",
        ]
        return next((c for c in candidates if c in self._sources), None)

    # -- tsconfig ------------------------------------------------------------

    def _config(self, directory: str) -> tuple[str, dict[str, list[str]]] | None:
        """(base dir, paths patterns) of the tsconfig in `directory`."""
        if directory not in self._paths:
            name = posixpath.join(directory, "tsconfig.json")
            self._paths[directory] = (
                self._read_config(name, 1) if name in self._all else None
            )
        return self._paths[directory]

    def _read_config(
        self, name: str, extends_left: int
    ) -> tuple[str, dict[str, list[str]]] | None:
        config = _jsonc(_read(self._root, name))
        here = posixpath.dirname(name)
        options = config.get("compilerOptions")
        options = options if isinstance(options, dict) else {}
        parent = config.get("extends")
        inherited = None
        if extends_left and isinstance(parent, str) and parent.startswith("."):
            target = posixpath.normpath(posixpath.join(here, parent))
            target = target if target.endswith(".json") else target + ".json"
            inherited = self._read_config(target, 0) if target in self._all else None
        if "baseUrl" in options or "paths" in options:
            paths = (
                options.get("paths") if isinstance(options.get("paths"), dict) else None
            )
            base = posixpath.normpath(
                posixpath.join(here, options.get("baseUrl") or ".")
            )
            if paths is None and inherited is not None:
                return base, inherited[1]
            return base, _clean_paths(paths or {})
        return inherited

    def _tsconfig(self, rel: str, spec: str) -> str | None:
        directory = posixpath.dirname(rel)
        while True:
            config = self._config(directory)
            if config is not None:
                base, patterns = config
                for pattern, targets in patterns.items():
                    middle = _pattern_middle(pattern, spec)
                    if middle is None:
                        continue
                    for target in targets:
                        found = self._file(
                            posixpath.join(base, target.replace("*", middle))
                        )
                        if found:
                            return found
                return self._file(posixpath.join(base, spec))  # plain baseUrl import
            if directory in ("", "."):
                return None
            directory = posixpath.dirname(directory)

    # -- workspace packages --------------------------------------------------

    def _workspace(self) -> dict[str, str]:
        if self._packages is None:
            self._packages = {}
            for name in sorted(
                f for f in self._all if posixpath.basename(f) == "package.json"
            ):
                pkg = _jsonc(_read(self._root, name)).get("name")
                if isinstance(pkg, str):
                    self._packages.setdefault(pkg, posixpath.dirname(name))
        return self._packages

    def is_external(self, rel: str, spec: str) -> bool:
        """True for a bare specifier no repo mapping claims (no relative
        form, tsconfig alias or workspace package name): a registry package,
        so a failed `resolve` means "not in the repo", not "broken"."""
        if spec.startswith((".", "/", "#", "~", "@/")):
            return False
        directory = posixpath.dirname(rel)
        while True:
            config = self._config(directory)
            if config is not None:
                if any(_pattern_middle(p, spec) is not None for p in config[1]):
                    return False
                break
            if directory in ("", "."):
                break
            directory = posixpath.dirname(directory)
        return not any(spec == p or spec.startswith(p + "/") for p in self._workspace())

    def _package(self, spec: str) -> str | None:
        packages = self._workspace()
        pkg = max(
            (p for p in packages if spec == p or spec.startswith(p + "/")),
            key=len,
            default=None,
        )
        if pkg is None:
            return None
        directory = packages[pkg]
        sub = spec[len(pkg) + 1 :]
        if sub:
            return self._file(posixpath.join(directory, sub)) or self._file(
                posixpath.join(directory, "src", sub)
            )
        manifest = _jsonc(_read(self._root, posixpath.join(directory, "package.json")))
        exports = manifest.get("exports")
        entries = [
            _first_string(
                exports.get(".")
                if isinstance(exports, dict) and "." in exports
                else exports
            ),
            manifest.get("types"),
            manifest.get("main"),
            "src/index",
            "index",
        ]
        for entry in entries:
            if isinstance(entry, str):
                found = self._file(posixpath.join(directory, entry))
                if found:
                    return found
        return None


def _pattern_middle(pattern: str, spec: str) -> str | None:
    """What a tsconfig `paths` pattern's `*` captured in `spec` (empty for an
    exact pattern), or None when the pattern does not match."""
    star = pattern.find("*")
    if star < 0:
        return "" if spec == pattern else None
    head, tail = pattern[:star], pattern[star + 1 :]
    if (
        spec.startswith(head)
        and spec.endswith(tail)
        and len(spec) >= len(head) + len(tail)
    ):
        return spec[len(head) : len(spec) - len(tail)]
    return None


def _clean_paths(paths: dict) -> dict[str, list[str]]:
    return {
        k: [t for t in v if isinstance(t, str)]
        for k, v in paths.items()
        if isinstance(v, list)
    }
