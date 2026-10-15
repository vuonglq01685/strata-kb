"""pages extractor -- `page.<app>` sections from UI page routes declared in
code, plus the `pages` rows of `struct.coverage`.

One section per front-end app (a scope whose manifest names a page
framework). L2 is the table `Path | File | Layout/group`, sorted by path,
with a closing `Middleware matcher:` row when a Next.js `middleware` file
declares literal `config.matcher` patterns. Route groups (`(admin)`) and
dynamic segments (`[id]`, `:id`, `[...slug]`) are kept as written.

**Adapters.** File-system routers (Next.js, Nuxt, SvelteKit) live in
`_pages_fs.py` and run without the `code` extra, except the Next.js
middleware matcher. Router-table frameworks (Angular, Vue, React in
`_pages_js.py`; Flutter in `_pages_dart.py`) parse source with tree-sitter
and report `not scanned` when it is missing. An adapter returns the pages it
could resolve and a `file:line` site for everything it recognised but could
not, which becomes a `partial` coverage row -- never dropped.

**Coverage.** One row per (scope, framework). A framework that is only a
transitive base (React under Next.js, Vue under Nuxt, Svelte without
SvelteKit) gets a row only when its router library is a dependency; with no
router usage it gets none (a missing row reads as not scanned downstream).
A router library no adapter supports (`@tanstack/react-router`, `wouter`,
`unplugin-vue-router`, `auto_route`, ...) makes the row `not scanned` and
names the library.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from strata_kb.codeingest.extractors import _ts, deps
from strata_kb.codeingest.extractors._coverage import NOT_INSTALLED
from strata_kb.codeingest.extractors._mdcells import escape_cell
from strata_kb.codeingest.extractors._pages_dart import flutter_pages
from strata_kb.codeingest.extractors._pages_fs import (
    next_pages,
    nuxt_pages,
    sveltekit_pages,
)
from strata_kb.codeingest.extractors._pages_js import (
    angular_pages,
    react_pages,
    vue_pages,
)
from strata_kb.codeingest.extractors._pages_model import Page, PageResult
from strata_kb.codeingest.extractors._routes_jsutil import _local
from strata_kb.codeingest.extractors._scopes import Scope, find_scopes, scope_of
from strata_kb.codeingest.extractors._slugs import assign_slugs
from strata_kb.codeingest.extractors.routes import _repo_files
from strata_kb.codeingest.types import (
    CodeIngestOptions,
    CodeSection,
    CoverageRow,
    ExtractResult,
)

__all__ = ["PAGE_FRAMEWORKS", "PagesExtractor"]

# Labels as `deps.FRAMEWORKS` spells them.
PAGE_FRAMEWORKS: tuple[str, ...] = (
    "Next.js",
    "Nuxt",
    "Svelte",
    "Angular",
    "Vue",
    "React",
    "Flutter",
)

Adapter = Callable[[Path, Scope, list[str], list[str]], PageResult]

# Router libraries no adapter reads. A name matches itself or `name/...`.
_UNSUPPORTED: dict[str, tuple[str, ...]] = {
    "React": (
        "@tanstack/react-router",
        "@tanstack/router",
        "@tanstack/start",
        "@reach/router",
        "@react-navigation",
        "@react-router",
        "@remix-run",
        "expo-router",
        "react-location",
        "react-navigation",
        "wouter",
    ),
    "Vue": ("unplugin-vue-router", "vite-plugin-pages"),
    "Angular": ("@analogjs/router",),
    "Svelte": (
        "@roxi/routify",
        "svelte-navigator",
        "svelte-routing",
        "svelte-spa-router",
        "tinro",
    ),
    "Flutter": ("auto_route", "beamer", "fluro", "get", "routemaster", "vrouter"),
}
# A framework that is only a base runs its adapter when one of these is used.
_ROUTER_LIBS: dict[str, frozenset[str]] = {
    "Vue": frozenset({"vue-router"}),
    "React": frozenset({"react-router", "react-router-dom"}),
}
_UNSUPPORTED_DETAIL = "unsupported router: "
_HEADER = "| Path | File | Layout/group |"
_RULE = "| --- | --- | --- |"


@dataclass(frozen=True)
class _Job:
    framework: str
    adapter: Adapter | None  # None: only an unsupported router is present
    parse: bool  # needs tree-sitter
    unsupported: tuple[str, ...] = ()
    # a router library is a dependency, so "found nothing" is not believable
    gated: bool = False


def _unsupported(framework: str, names: set[str]) -> tuple[str, ...]:
    libs = _UNSUPPORTED.get(framework, ())
    return tuple(
        sorted(n for n in names if any(n == p or n.startswith(p + "/") for p in libs))
    )


def _jobs(scope: Scope, names: set[str], local: list[str]) -> list[_Job]:
    fw = set(scope.frameworks)
    kit = "@sveltejs/kit" in names or any(f.startswith("src/routes/") for f in local)
    # (label, adapter, needs tree-sitter, adapter runs even without a router lib)
    table: list[tuple[str, Adapter, bool, bool]] = [
        ("Next.js", next_pages, False, True),
        ("Nuxt", nuxt_pages, False, True),
        ("Svelte", sveltekit_pages, False, kit),
        ("Angular", angular_pages, True, True),
        ("Vue", vue_pages, True, bool(names & _ROUTER_LIBS["Vue"])),
        ("React", react_pages, True, bool(names & _ROUTER_LIBS["React"])),
        ("Flutter", flutter_pages, True, True),
    ]
    jobs = []
    for label, adapter, parse, runs in table:
        if label not in fw:
            continue
        unsupported = _unsupported(label, names)
        if runs:
            gated = label in _ROUTER_LIBS or (
                label == "Flutter" and "go_router" in names
            )
            jobs.append(_Job(label, adapter, parse, unsupported, gated))
        elif unsupported:
            jobs.append(_Job(label, None, False, unsupported))
    return jobs


def _dep_names(root: Path, scope: Scope) -> set[str]:
    base = root if scope.path == "." else root / scope.path
    return {n.lower() for n in deps.manifest_dep_names(base / scope.manifest)}


def _manifest(scope: Scope) -> str:
    return scope.manifest if scope.path == "." else f"{scope.path}/{scope.manifest}"


def _scope_name(scope: Scope, opts: CodeIngestOptions) -> str:
    return opts.repo_id if scope.path == "." else scope.path


def _row(
    scope: Scope, job: _Job, result: PageResult | None, available: bool
) -> CoverageRow:
    # "; " separates sites in the coverage detail, so a file name containing
    # it must not leak through (lossy by one space); same rule as routes.py.
    sites = sorted(
        {s.replace("; ", ";") for s in (result.dynamic_sites if result else [])}
    )
    details = []
    if job.unsupported:
        details.append(_UNSUPPORTED_DETAIL + ", ".join(job.unsupported))
    if (job.adapter is not None and job.parse and not available) or (
        result is not None and result.not_installed
    ):
        details.append(NOT_INSTALLED)
    status = "not scanned" if details else ("partial" if sites else "complete")
    return CoverageRow(
        "pages", scope.path, job.framework, status, "; ".join(details + sites)
    )


def _cells(*cells: str) -> str:
    return "| " + " | ".join(escape_cell(c) for c in cells) + " |"


def _section(
    slug: str, name: str, pages: list[Page], matcher: tuple[str, list[str]] | None
) -> CodeSection:
    # one row per (path, file, group): `home:` and a `GoRoute('/')` both give "/"
    first = {(p.path, p.file, p.group): p for p in sorted(pages, key=lambda p: p.line)}
    ordered = sorted(first.values(), key=lambda p: (p.path, p.file, p.line, p.group))
    l2 = [_HEADER, _RULE, *(_cells(p.path, p.file, p.group) for p in ordered)]
    l3 = [
        f"{p.path}  {p.file}:{p.line}" + (f"  {p.group}" if p.group else "")
        for p in ordered
    ]
    count = len(ordered)
    summary = f"{count} UI page route{'s' * (count != 1)} in {name}."
    if matcher is not None:
        file, patterns = matcher
        text = "Middleware matcher: " + ", ".join(patterns)
        l2.append(_cells(text, file, ""))
        l3.append(f"{text}  {file}")
        summary += " Middleware matcher listed."
    return CodeSection(
        id=f"page.{slug}",
        title=f"Pages: {name}",
        summary=summary,
        group="pages",
        l2_md="\n".join(l2) + "\n",
        l3_md="```\n" + "\n".join(l3) + "\n```\n",
    )


def _slugs(names: list[str]) -> list[str]:
    own = [assign_slugs([n])[0] for n in names]
    return own if len(set(own)) == len(own) else assign_slugs(names)


class PagesExtractor:
    name = "pages"

    def detect(self, root: Path) -> bool:
        # `detect` never sees `opts`, so the default kb dir stands in --
        # the same structural exception the other extractors document.
        return any(
            fw in PAGE_FRAMEWORKS
            for sc in find_scopes(root, root / ".kb")
            for fw in sc.frameworks
        )

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        every = find_scopes(root, opts.kb_dir)
        scopes = [
            sc for sc in every if any(f in PAGE_FRAMEWORKS for f in sc.frameworks)
        ]
        if not scopes:
            return ExtractResult()
        files = _repo_files(root, opts)
        by_scope: dict[str, list[str]] = {}
        for rel in files:
            owner = scope_of(every, rel)
            if owner is not None:
                by_scope.setdefault(owner.path, []).append(rel)
        available = _ts.available()
        warnings: list[str] = []
        coverage: list[CoverageRow] = []
        gathered: list[tuple[Scope, list[Page], tuple[str, list[str]] | None]] = []
        for sc in scopes:
            scope_files = by_scope.get(sc.path, [])
            local = [_local(f, sc) for f in scope_files]
            pages: list[Page] = []
            matcher = None
            for job in _jobs(sc, _dep_names(root, sc), local):
                result: PageResult | None = None
                if job.adapter is not None and (available or not job.parse):
                    try:
                        result = job.adapter(root, sc, scope_files, files)
                    except Exception as exc:  # noqa: BLE001 -- degrade, never crash: one bad adapter must not abort the run
                        manifest = _manifest(sc)
                        warnings.append(
                            f"pages: {job.framework} adapter failed in {sc.path}: {exc!r}"
                        )
                        coverage.append(
                            CoverageRow(
                                "pages",
                                sc.path,
                                job.framework,
                                "partial",
                                f"{manifest}:1",
                            )
                        )
                        continue
                    if job.gated and not result.pages and not result.dynamic_sites:
                        result.dynamic_sites.append(f"{_manifest(sc)}:1")
                    pages += result.pages
                    matcher = result.matcher or matcher
                coverage.append(_row(sc, job, result, available))
            gathered.append((sc, pages, matcher))
        if any(r.detail.find(NOT_INSTALLED) >= 0 for r in coverage):
            warnings.append(
                "pages not scanned: tree-sitter is not installed (install strata-kb[code])"
            )
        with_pages = [(sc, p, m) for sc, p, m in gathered if p or m]
        names = [_scope_name(sc, opts) for sc, _p, _m in with_pages]
        sections = [
            _section(slug, name, pages, matcher)
            for slug, name, (_sc, pages, matcher) in zip(
                _slugs(names), names, with_pages, strict=True
            )
        ]
        return ExtractResult(sections=sections, warnings=warnings, coverage=coverage)
