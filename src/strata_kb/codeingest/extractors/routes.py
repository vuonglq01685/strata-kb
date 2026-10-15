"""routes extractor -- `route.<module>` sections from HTTP routes declared
in code, plus the `routes` rows of `struct.coverage`.

One section per module file (the unit the framework itself uses: a
controller, a router file, a route file). L2 is the table
`Method | Path | Handler | File | Request type`, sorted by (path, method);
L3 lists every route with its `file:line` and, for each request type,
its declared fields when the type is a plain class/interface declared in
the same repo (else `request type declared outside the repo`).

**Adapters.** `ADAPTERS` maps a framework label (as `deps.FRAMEWORKS`
spells it) to `adapter(repo root, Scope, scope's source files) ->
AdapterResult`. Each `_routes_<lang>.py` exports its own `ADAPTERS` and is
merged below. An adapter returns the routes it could resolve and a
`file:line` site for everything it recognised but could not, which this
module turns into a `partial` coverage row -- never dropped.

**Coverage.** One row per (scope, route framework): `complete`, `partial`
with the sites, or `not scanned` (no adapter yet / the `code` extra is
missing). A scope whose manifest names no route framework gets no row.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from strata_kb.codeingest.extractors import (
    _jvm_ast,
    _jvm_fields,
    _routes_js,
    _routes_jvm,
    _ts,
)
from strata_kb.codeingest.extractors._coverage import NOT_INSTALLED
from strata_kb.codeingest.extractors._mdcells import escape_cell
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)
from strata_kb.codeingest.extractors._scopes import Scope, find_scopes, scope_of
from strata_kb.codeingest.extractors._slugs import assign_slugs
from strata_kb.codeingest.extractors.tree import walk_tree
from strata_kb.codeingest.types import (
    CodeIngestOptions,
    CodeSection,
    CoverageRow,
    ExtractResult,
)

__all__ = [
    "ADAPTERS",
    "FIELD_READERS",
    "ROUTE_FRAMEWORKS",
    "AdapterResult",
    "Route",
    "RoutesExtractor",
    "join_path",
]

# Spec 5.2, in table order.
ROUTE_FRAMEWORKS: tuple[str, ...] = (
    "NestJS",
    "Express",
    "Next.js",
    "Nuxt",
    "Spring Boot",
    "Quarkus",
    "Micronaut",
    "ASP.NET Core",
    "FastAPI",
    "Flask",
    "Django",
    "Gin",
    "Laravel",
    "Symfony",
    "Actix Web",
    "Axum",
    "Rocket",
    "Vapor",
)

Adapter = Callable[[Path, Scope, list[str], list[str]], AdapterResult]
ADAPTERS: dict[str, Adapter] = {**_routes_js.ADAPTERS, **_routes_jvm.ADAPTERS}

# `reader(root, repo files, type name, route file) -> [(name, type, required)]`
# or None when the type is not a plain declaration found in the repo.
FIELD_READERS: list[
    Callable[[Path, list[str], str, str], list[tuple[str, str, bool]] | None]
] = [_routes_js.declared_fields, _jvm_fields.declared_fields]

_OUTSIDE = "request type declared outside the repo"
_HEADER = "| Method | Path | Handler | File | Request type |"
_RULE = "| --- | --- | --- | --- | --- |"


def _route_targets(scopes: list[Scope]) -> list[tuple[Scope, str]]:
    return [(sc, fw) for sc in scopes for fw in sc.frameworks if fw in ROUTE_FRAMEWORKS]


def _repo_files(root: Path, opts: CodeIngestOptions) -> list[str]:
    return sorted(
        (rel / name).as_posix()
        for _depth, rel, names in walk_tree(root, opts.kb_dir)
        for name in names
    )


def _fields_block(root: Path, files: list[str], type_name: str, near: str) -> list[str]:
    for reader in FIELD_READERS:
        fields = reader(root, files, type_name, near)
        if fields is not None:
            return [
                f"{type_name}",
                "| name | type | required |",
                "| --- | --- | --- |",
                *(
                    f"| {escape_cell(n)} | {escape_cell(t)} | {'yes' if req else 'no'} |"
                    for n, t, req in fields
                ),
            ]
    return [f"{type_name}: {_OUTSIDE}"]


def _section(
    slug: str, file: str, routes: list[Route], root: Path, files: list[str]
) -> CodeSection:
    ordered = sorted(routes, key=lambda r: (r.path, r.method, r.line, r.handler))
    l2 = [_HEADER, _RULE]
    l3 = [f"{r.method} {r.path}  {r.handler}  {r.file}:{r.line}" for r in ordered]
    for r in ordered:
        cells = (r.method, r.path, r.handler, r.file, r.request_type)
        l2.append("| " + " | ".join(escape_cell(c) for c in cells) + " |")
    for type_name in sorted({r.request_type for r in ordered if r.request_type}):
        near = next(r.file for r in ordered if r.request_type == type_name)
        l3 += ["", *_fields_block(root, files, type_name, near)]
    count = len(ordered)
    return CodeSection(
        id=f"route.{slug}",
        title=file,
        summary=f"{count} HTTP route{'s' * (count != 1)} declared in {file}.",
        group="routes",
        l2_md="\n".join(l2) + "\n",
        l3_md="```\n" + "\n".join(l3) + "\n```\n",
    )


def _stem(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return path[: len(path) - len(name) + name.rfind(".")] if "." in name else path


def _sections(found: list[Route], root: Path, files: list[str]) -> list[CodeSection]:
    by_file: dict[str, list[Route]] = {}
    for route in found:
        by_file.setdefault(route.file, []).append(route)
    paths = sorted(by_file)
    # path without suffix; the full path when two files differ only by suffix
    stems = [_stem(p) for p in paths]
    names = [p if stems.count(s) > 1 else s for p, s in zip(paths, stems, strict=True)]
    return [
        _section(slug, path, by_file[path], root, files)
        for path, slug in zip(paths, assign_slugs(names), strict=True)
    ]


class RoutesExtractor:
    name = "routes"

    def detect(self, root: Path) -> bool:
        # `detect` never sees `opts`, so the default kb dir stands in --
        # the same structural exception the other extractors document.
        return bool(_route_targets(find_scopes(root, root / ".kb")))

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        try:
            return self._extract(root, opts)
        finally:
            _jvm_fields.clear_cache()  # source bytes read for request types
            _jvm_ast.clear_run_cache()

    def _extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        scopes = find_scopes(root, opts.kb_dir)
        targets = _route_targets(scopes)
        if not targets:
            return ExtractResult()
        if not _ts.available():
            return ExtractResult(
                warnings=[
                    "routes not scanned: tree-sitter is not installed "
                    "(install strata-kb[code])"
                ],
                coverage=[
                    CoverageRow("routes", sc.path, fw, "not scanned", NOT_INSTALLED)
                    for sc, fw in targets
                ],
            )
        files = _repo_files(root, opts)
        by_scope: dict[str, list[str]] = {}
        for rel in files:
            owner = scope_of(scopes, rel)
            if owner is not None and _ts.language_for(rel) is not None:
                by_scope.setdefault(owner.path, []).append(rel)

        found: set[Route] = set()
        warnings: list[str] = []
        coverage: list[CoverageRow] = []
        for sc, fw in targets:
            adapter = ADAPTERS.get(fw)
            if adapter is None:
                coverage.append(
                    CoverageRow(
                        "routes", sc.path, fw, "not scanned", f"no adapter for {fw} yet"
                    )
                )
                continue
            try:
                result = adapter(root, sc, by_scope.get(sc.path, []), files)
            except Exception as exc:  # noqa: BLE001 -- degrade, never crash: one bad adapter must not abort the run
                manifest = sc.manifest if sc.path == "." else f"{sc.path}/{sc.manifest}"
                warnings.append(f"routes: {fw} adapter failed in {sc.path}: {exc!r}")
                coverage.append(
                    CoverageRow("routes", sc.path, fw, "partial", f"{manifest}:1")
                )
                continue
            found.update(result.routes)
            # "; " separates sites in the coverage detail, so a file name
            # containing it must not leak through (lossy by one space).
            sites = sorted({s.replace("; ", ";") for s in result.dynamic_sites})
            coverage.append(
                CoverageRow(
                    "routes",
                    sc.path,
                    fw,
                    "partial" if sites else "complete",
                    "; ".join(sites),
                )
            )
        return ExtractResult(
            sections=_sections(
                sorted(found, key=lambda r: (r.file, r.path, r.method, r.line)),
                root,
                files,
            ),
            warnings=warnings,
            coverage=coverage,
        )
