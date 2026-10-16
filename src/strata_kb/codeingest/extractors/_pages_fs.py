"""File-system page routers for `pages.py`: Next.js (`app/**/page.*`,
`pages/**`, `middleware` matcher), Nuxt (`pages/**`) and SvelteKit
(`src/routes/**/+page.svelte`).

Each adapter takes `(repo root, Scope, that scope's tracked files, all tracked
repo files)` -- every file, not only source files -- and returns a
`PageResult`. Only the Next.js middleware matcher needs tree-sitter; the rest
runs without the `code` extra.

**Default to a site, never drop.** A config option that moves the pages
directory or rewrites served paths (Next `basePath` / `pageExtensions` /
`i18n`, Nuxt `srcDir` / `dir.pages` / `pages:extend`, SvelteKit
`kit.files.routes` / `paths`, `reroute` hook), an intercepting route, a page whose path a
`definePageMeta` overrides, a non-literal middleware matcher: each is a
`file:line` site, so the scope reads `partial`.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._pages_model import Page, PageResult, line_at
from strata_kb.codeingest.extractors._routes_jsutil import (
    _SUFFIX_RE,
    _config_sites,
    _error_line,
    _lit,
    _local,
    _parse,
    _read,
    _text,
)
from strata_kb.codeingest.extractors._routes_model import join_path
from strata_kb.codeingest.extractors._scopes import Scope

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["next_pages", "nuxt_pages", "sveltekit_pages"]

_GROUP_RE = re.compile(r"^\(.*\)$")
_INTERCEPT_RE = re.compile(r"^\(\.{1,3}\)")
_NEXT_EXT = r"(?:tsx|ts|jsx|js)"  # `pageExtensions` changes are a site
_NEXT_APP_FILE = re.compile(rf"^page\.{_NEXT_EXT}$")
_NEXT_PAGES_FILE = re.compile(rf"^(?P<stem>.+)\.{_NEXT_EXT}$")
_NEXT_SPECIAL = frozenset({"_app", "_document", "_error", "_middleware"})
_NEXT_CONFIGS = frozenset(f"next.config.{e}" for e in ("js", "mjs", "cjs", "ts"))
_MIDDLEWARE = frozenset(
    f"{base}{ext}" for base in ("middleware", "proxy") for ext in (".ts", ".js", ".mjs")
)
_NUXT_LAYER = re.compile(r"^layers/[^/]+/(?:app/)?pages/(?P<inner>.+)$")
_NUXT_FILE = re.compile(r"^(?P<stem>.+)\.(?:vue|[cm]?[jt]sx?)$")
_NUXT_CONFIGS = frozenset(f"nuxt.config.{e}" for e in ("js", "mjs", "cjs", "ts"))
_SVELTE_PAGE = re.compile(r"^\+page(?:@[^.]*)?\.svelte$")
_SVELTE_HOOKS = tuple(
    f"src/{name}.{ext}" for name in ("hooks", "hooks/index") for ext in ("ts", "js")
)
_SVELTE_CONFIGS = frozenset(f"svelte.config.{e}" for e in ("js", "mjs", "cjs", "ts"))


def _base(locals_: list[str], *candidates: str) -> str | None:
    """The first of `candidates` (`app`, `src/app`) that holds a file."""
    return next(
        (c for c in candidates if any(f.startswith(c + "/") for f in locals_)), None
    )


def _split_groups(dirs: list[str]) -> tuple[list[str], str]:
    """(path segments, group text): `(group)` and `@slot` dirs are not URL
    segments; they are shown as written, joined by "/"."""
    segments = [d for d in dirs if not _GROUP_RE.match(d) and not d.startswith("@")]
    groups = [d for d in dirs if _GROUP_RE.match(d) or d.startswith("@")]
    return segments, "/".join(groups)


# --- Next.js ----------------------------------------------------------------


def next_pages(
    root: Path, scope: Scope, files: list[str], repo_files: list[str]
) -> PageResult:
    result = PageResult()
    local = {_local(f, scope): f for f in files}
    names = sorted(local)
    app = _base(names, "app", "src/app")
    pages = _base(names, "pages", "src/pages")
    for loc in names:
        parts = loc.split("/")
        if app and loc.startswith(app + "/") and _NEXT_APP_FILE.match(parts[-1]):
            _next_app_page(local[loc], parts[len(app.split("/")) : -1], result)
        elif pages and loc.startswith(pages + "/") and not loc.endswith(".d.ts"):
            _next_pages_file(local[loc], parts[len(pages.split("/")) :], result)
    result.dynamic_sites.extend(
        _config_sites(
            root, scope, files, _NEXT_CONFIGS, b"basePath|pageExtensions|i18n"
        )
    )
    _next_middleware(root, scope, names, local, result)
    return result


def _next_app_page(rel: str, dirs: list[str], result: PageResult) -> None:
    if any(d.startswith("_") for d in dirs):  # private folder: never routed
        return
    if any(_INTERCEPT_RE.match(d) for d in dirs):
        result.dynamic_sites.append(f"{rel}:1")  # serves another URL
        return
    segments, group = _split_groups(dirs)
    result.pages.append(Page(join_path(*segments), rel, 1, group))


def _next_pages_file(rel: str, parts: list[str], result: PageResult) -> None:
    match = _NEXT_PAGES_FILE.match(parts[-1])
    if match is None or (parts[0] == "api" and len(parts) > 1):
        return
    stem = match.group("stem")
    if stem in _NEXT_SPECIAL:
        return
    segments = [*parts[:-1], "" if stem == "index" else stem]
    result.pages.append(Page(join_path(*segments), rel, 1))


def _next_middleware(
    root: Path,
    scope: Scope,
    names: list[str],
    local: dict[str, str],
    result: PageResult,
) -> None:
    found = [
        n for n in names if n in {*_MIDDLEWARE, *("src/" + m for m in _MIDDLEWARE)}
    ]
    if not found:
        return
    if not _ts.available():
        result.not_installed = True
        return
    rel = local[found[0]]
    data = _read(root, rel)
    if data is None:
        result.dynamic_sites.append(f"{rel}:1")
        return
    tree = _parse(rel, data)
    line = _error_line(tree)
    if line is not None:
        result.dynamic_sites.append(f"{rel}:{line}")
    patterns, dynamic = _matcher(tree)
    if dynamic is not None:
        result.dynamic_sites.append(f"{rel}:{dynamic}")
    if patterns:
        result.matcher = (rel, patterns)


def _matcher(tree: Tree) -> tuple[list[str], int | None]:
    """(literal matcher patterns, line of whatever could not be read)."""
    for stmt in tree.root_node.named_children:
        if stmt.type != "export_statement":
            continue
        clauses = [c for c in stmt.children if c.type == "export_clause"]
        if any(
            _text(s.child_by_field_name("name")) == "config"
            for c in clauses
            for s in c.named_children
        ):
            return [], _ts.line_of(stmt)
        decl = stmt.child_by_field_name("declaration")
        for var in decl.named_children if decl is not None else []:
            if (
                var.type == "variable_declarator"
                and _text(var.child_by_field_name("name")) == "config"
            ):
                return _config_matcher(var.child_by_field_name("value"), var)
    return [], None


def _unwrap(node: Node | None) -> Node | None:
    while node is not None and node.type in (
        "as_expression",
        "satisfies_expression",
        "parenthesized_expression",
    ):
        node = node.named_children[0] if node.named_children else None
    return node


def _config_matcher(value: Node | None, at: Node) -> tuple[list[str], int | None]:
    config = _unwrap(value)
    if config is None or config.type != "object":
        return [], _ts.line_of(at)
    matcher: Node | None = None
    for pair in config.named_children:
        key = pair.child_by_field_name("key") if pair.type == "pair" else None
        if pair.type == "comment":
            continue
        if key is None:  # spread, method, shorthand: could hide `matcher`
            return [], _ts.line_of(pair)
        if (_lit(key) or _text(key)) == "matcher":
            matcher = pair.child_by_field_name("value")
    if matcher is None:
        return [], None
    matcher = _unwrap(matcher)
    items = matcher.named_children if matcher and matcher.type == "array" else [matcher]
    patterns: list[str] = []
    dynamic: int | None = None
    for item in items:
        if item is None:
            return patterns, _ts.line_of(at)
        if item.type == "comment":
            continue
        text = _lit(item)
        if text is None and item.type == "object":
            source = next(
                (
                    p.child_by_field_name("value")
                    for p in item.named_children
                    if p.type == "pair"
                    and _text(p.child_by_field_name("key")).strip("'\"") == "source"
                ),
                None,
            )
            text = _lit(source)
            if any(
                p.type == "pair"
                and _text(p.child_by_field_name("key")).strip("'\"")
                in ("has", "missing", "locale")
                for p in item.named_children
            ):
                dynamic = dynamic or _ts.line_of(item)  # conditions narrow it
        if text is None:
            dynamic = dynamic or _ts.line_of(item)
        else:
            patterns.append(text)
    return patterns, dynamic


# --- Nuxt -------------------------------------------------------------------


def nuxt_pages(
    root: Path, scope: Scope, files: list[str], repo_files: list[str]
) -> PageResult:
    result = PageResult()
    local = {_local(f, scope): f for f in files}
    names = sorted(local)
    base = _base(names, "pages", "app/pages")
    for loc in names:
        layer = _NUXT_LAYER.match(loc)  # local layers/* are auto-registered
        if base and loc.startswith(base + "/"):
            _nuxt_page(root, local[loc], loc[len(base) + 1 :], result)
        elif layer:
            _nuxt_page(root, local[loc], layer.group("inner"), result)
        if PurePosixPath(loc).name.startswith("router.options."):
            result.dynamic_sites.append(f"{local[loc]}:1")  # custom route table
    result.dynamic_sites.extend(
        _config_sites(
            root,
            scope,
            files,
            _NUXT_CONFIGS,
            b"srcDir|extendPages|pages:extend|dir(?=\\s*:)|extends|i18n",
        )
    )
    return result


def _nuxt_page(root: Path, rel: str, inner: str, result: PageResult) -> None:
    *dirs, filename = inner.split("/")
    match = _NUXT_FILE.match(filename)
    # Nitro's ignore list also applies to pages: tests, stories, `-x` files
    if (
        match is None
        or filename.endswith(".d.ts")
        or _SUFFIX_RE.search(filename)
        or ".stories." in filename
        or filename.startswith("-")
    ):
        return
    stem = re.sub(r"\.(?:client|server)$", "", match.group("stem"))
    segments, group = _split_groups(dirs)
    path = join_path(*segments, "" if stem == "index" else stem)
    result.pages.append(Page(path, rel, 1, group))
    data = _read(root, rel) or b""
    meta = re.search(rb"definePageMeta\s*\(", data)
    if meta and re.search(rb"\b(?:path|alias)\s*:", data):
        line = line_at(data, meta.start())
        result.dynamic_sites.append(f"{rel}:{line}")


# --- SvelteKit --------------------------------------------------------------


def sveltekit_pages(
    root: Path, scope: Scope, files: list[str], repo_files: list[str]
) -> PageResult:
    result = PageResult()
    prefix = "src/routes/"
    for rel in sorted(files):
        loc = _local(rel, scope)
        if not loc.startswith(prefix):
            continue
        *dirs, filename = loc[len(prefix) :].split("/")
        if _SVELTE_PAGE.match(filename):
            segments, group = _split_groups(dirs)
            result.pages.append(Page(join_path(*segments), rel, 1, group))
    result.dynamic_sites.extend(
        _config_sites(root, scope, files, _SVELTE_CONFIGS, b"files|routes|paths")
    )
    for hooks in _SVELTE_HOOKS:  # `reroute` remaps URLs
        rel = hooks if scope.path == "." else f"{scope.path}/{hooks}"
        data = _read(root, rel) or b""
        match = re.search(rb"\breroute\b", data)
        if match:
            result.dynamic_sites.append(f"{rel}:{line_at(data, match.start())}")
    return result
