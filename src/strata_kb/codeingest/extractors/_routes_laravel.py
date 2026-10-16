"""Laravel route adapter for `routes.py`.

`_laravel_build` reads each PHP file of the scope once into a context-free
program; this module decides under which prefix each program is played.
Collect first, resolve after, so the result never depends on file order:

1. Every PHP file of the scope that mentions the facade, a router variable
   or a route-shaped call is parsed (a syntax error is a site).
2. A file is *included* when another file's `->group(base_path('routes/x.php'))`,
   `require __DIR__.'/x.php'`, `loadRoutesFrom` or `withRouting(web:, api:)`
   names it; it is played under the including chain's prefix (an
   `apiPrefix:` or `->prefix('api')` shows up here, which is what
   `RouteServiceProvider` and `bootstrap/app.php` do).
3. A route file nobody includes is played from the top: `routes/api.php`
   under `/api` and `routes/web.php` under no prefix (the framework
   defaults), any other name is a site (how it is registered is unknown).
   A file that registers routes from code (a provider, `bootstrap/app.php`)
   is played under no prefix.

Shortcuts: `singleton` resources, `Auth::routes()`, Volt and Folio are
sites; `scoped()` bindings keep the plain `{param}`; a resource parameter is
singularised by a few English rules (`Str::singular` is the real one).
Route macros, variable-held groups (`$g = Route::prefix('a'); $g->get(...)`)
and test directories are not followed: macros and groups are sites, tests
are skipped.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from strata_kb.codeingest.extractors import _laravel_build as lb
from strata_kb.codeingest.extractors import _php_ast as php
from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._laravel_paths import resolve_path
from strata_kb.codeingest.extractors._routes_jsutil import _error_line, _read
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)
from strata_kb.codeingest.extractors._scopes import Scope

__all__ = ["ADAPTERS"]

# a file is parsed only when it could hold a routing statement
_HINT = re.compile(
    rb"\bRoute\b|\$router\b|\brouter\b|loadRoutesFrom|withRouting"
    rb"|::\s*routes\b|\bVolt\s*::\s*route|\bFolio\s*::\s*path"
    rb"|(?:->|::)\s*(?:get|post|put|patch|delete|options|any|match)\s*\("
)
_MAX_DEPTH = 40
_DEFAULTS = {"api.php": ("api",), "web.php": ()}


class _Run:
    def __init__(self, root: Path, scope: Scope, repo_files: list[str]):
        self.root = root
        self.scope_root = "" if scope.path == "." else scope.path
        self.files = frozenset(php.source_files(repo_files))
        self.result = AdapterResult()
        self.sites: set[str] = set()
        self.routes: set[Route] = set()
        self.programs: dict[str, lb.Program] = {}
        self.played: set[str] = set()

    def find(self, kind: str, fragment: str, source: str) -> list[str] | None:
        return resolve_path(kind, fragment, source, self.scope_root, self.files)

    def program(self, rel: str) -> lb.Program:
        if rel not in self.programs:
            self.programs[rel] = self._read(rel)
        return self.programs[rel]

    def _read(self, rel: str) -> lb.Program:
        data = _read(self.root, rel)
        if data is None:
            self.sites.add(f"{rel}:1")
            return lb.Program()
        if not _HINT.search(data):
            return lb.Program()
        tree = _ts.parse("php", data)
        line = _error_line(tree)
        if line is not None:
            self.sites.add(f"{rel}:{line}")
        try:
            return lb.build(rel, tree.root_node, self)
        except RecursionError:
            self.sites.add(f"{rel}:1")
            return lb.Program()

    # -- playing -----------------------------------------------------------

    def play(self, rel: str, prefix: tuple[str, ...]) -> None:
        self.played.add(rel)
        stack: list[tuple[list[lb.Item], lb.Delta, str, tuple[str, ...]]] = [
            (self.program(rel).items, lb.Delta(prefix), rel, (rel,))
        ]
        while stack:
            items, ctx, here, chain = stack.pop()
            for item in items:
                if isinstance(item, lb.RouteItem):
                    self._emit(item, ctx, here)
                elif isinstance(item, lb.GroupItem):
                    stack.append((item.items, _compose(ctx, item.delta), here, chain))
                elif isinstance(item, lb.IncludeItem):
                    inner = _compose(ctx, item.delta)
                    for target in item.targets:
                        if target in chain or len(chain) >= _MAX_DEPTH:
                            self.sites.add(f"{here}:{item.line}")
                            continue
                        self.played.add(target)
                        stack.append(
                            (
                                self.program(target).items,
                                inner,
                                target,
                                (*chain, target),
                            )
                        )
                else:
                    self.sites.add(f"{here}:{item.line}")

    def _emit(self, item: lb.RouteItem, ctx: lb.Delta, rel: str) -> None:
        handler = item.handler
        if item.bare is not None:
            controller = item.delta.controller or ctx.controller
            handler = f"{controller}@{item.bare}" if controller else lb.INLINE
        path = join_path(*ctx.parts, *item.delta.parts, item.uri)
        self.routes.add(Route(item.method, path, handler, rel, item.line))


def _compose(ctx: lb.Delta, delta: lb.Delta) -> lb.Delta:
    return lb.Delta((*ctx.parts, *delta.parts), delta.controller or ctx.controller)


def _included(programs: dict[str, lb.Program]) -> set[str]:
    out: set[str] = set()
    for program in programs.values():
        todo = list(program.items)
        while todo:
            item = todo.pop()
            if isinstance(item, lb.GroupItem):
                todo.extend(item.items)
            elif isinstance(item, lb.IncludeItem):
                out.update(item.targets)
    return out


def adapter(
    root: Path, scope: Scope, scope_files: list[str], repo_files: list[str]
) -> AdapterResult:
    run = _Run(root, scope, repo_files)
    candidates = php.source_files(scope_files)
    programs = {rel: run.program(rel) for rel in candidates}
    included = _included(programs)
    for rel in candidates:
        program = programs[rel]
        if not program.content or rel in included:
            continue
        prefix: tuple[str, ...] = ()
        if program.script and program.routing:
            name = PurePosixPath(rel).name
            if name in _DEFAULTS:
                prefix = _DEFAULTS[name]
            else:
                run.sites.add(f"{rel}:1")  # who registers this file is unknown
        try:
            run.play(rel, prefix)
        except RecursionError:
            run.sites.add(f"{rel}:1")
    run.sites.update(
        f"{rel}:1"
        for rel in candidates
        if programs[rel].content and rel not in run.played
    )
    result = run.result
    result.routes = sorted(run.routes, key=lambda r: (r.file, r.path, r.method, r.line))
    result.dynamic_sites = sorted(run.sites)
    return result


ADAPTERS: dict[str, Callable[[Path, Scope, list[str], list[str]], AdapterResult]] = {
    "Laravel": adapter
}
