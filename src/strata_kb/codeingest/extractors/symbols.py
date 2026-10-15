"""symbols extractor -- `sym.<package>` sections of exported names, plus the
`symbols` rows of `struct.coverage`.

One section per package scope (a directory with its own manifest; files
under no manifest group by top-level directory, the repo root is
`sym.root`). The split level is fixed: never by size, never truncated. L2 is
the table `Name | Kind | File`, sorted by (file, name). Names only -- an enum
or object member is `X.KEY`; no value is ever read into the output.

This task covers JS/TS (`export` declarations, export lists, `export
default` named by its declaration or the file stem, `export ... from`
re-exports followed through the repo, enum and `const X = {..}` members)
and CSS/SCSS custom properties. `_symbols_lang.EXPORTERS` is the plug-in
point for the other languages.

**Coverage.** One row per (scope, language): `complete`, or `partial` with a
`file:line` site for a file that does not parse, an export list the reader
could not enumerate (an object member spread, a computed key, an unknown
declaration shape) and a re-export whose names are unknown (`export *` from
a module outside the repo, any re-export of a repo-looking path that does
not resolve). A language present in the scope without an exporter, or any
language without the `code` extra, is `not scanned`. Skipped files
(`*.d.ts`, generated, test) are counted in the row's prose detail
(`skipped N *.d.ts, N generated, N test`); `IGNORED_DIRS` are pruned by the
file walk before this extractor sees them, so they are not counted.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from strata_kb.codeingest.extractors import (
    _cs_ast,
    _kotlin_parse,
    _py_ast,
    _symbols_lang,
    _ts,
)
from strata_kb.codeingest.extractors._coverage import NOT_INSTALLED
from strata_kb.codeingest.extractors._mdcells import escape_cell
from strata_kb.codeingest.extractors._routes_jsresolve import ModuleResolver
from strata_kb.codeingest.extractors._routes_jsutil import (
    _EXTS,
    _read,
)
from strata_kb.codeingest.extractors._scopes import Scope, find_scopes, scope_of
from strata_kb.codeingest.extractors._slugs import assign_slugs
from strata_kb.codeingest.extractors._symbols_lang import DEFAULT_NAME, Reexport
from strata_kb.codeingest.extractors.routes import _repo_files
from strata_kb.codeingest.extractors.tree import walk_tree
from strata_kb.codeingest.types import (
    CodeIngestOptions,
    CodeSection,
    CoverageRow,
    ExtractResult,
)

__all__ = ["EXPORTERS", "Symbol", "SymbolsExtractor"]

# Same dict object as `_symbols_lang.EXPORTERS`: a language task adds its
# entry there, a test can drop one here.
EXPORTERS = _symbols_lang.EXPORTERS

# Tools whose `<tool>.config.*` is configuration, not product code; any other
# `*.config.*` (Angular `app.config.ts`, Nest `database.config.ts`) is source.
_TOOLS = [
    "next",
    "nuxt",
    "vite",
    "vitest",
    "jest",
    "webpack",
    "rollup",
    "tailwind",
    "postcss",
    "babel",
    "eslint",
    "prettier",
    "svelte",
    "astro",
    "playwright",
    "cypress",
    "tsup",
    "esbuild",
    "karma",
    "metro",
    "remix",
    "drizzle",
    "commitlint",
    "lint-staged",
    "stylelint",
    "turbo",
]

# (label in the coverage detail, pattern); a file counts under the first match.
_SKIP_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("*.d.ts", re.compile(r"\.d\.[cm]?ts$")),
    ("generated", re.compile(r"\.generated\.|(?:^|/)__generated__/")),
    ("test", re.compile(r"\.(?:test|spec)\.|(?:^|/)(?:__tests__|tests?)/")),
    # tool configuration (`vite.config.ts`, `.eslintrc.js`), not product code
    (
        "config",
        re.compile(
            r"(?:^|/)(?:"
            + "|".join(_TOOLS)
            + r")\.config(?:\.[\w-]+)?\.[cm]?[jt]s$|(?:^|/)\.[^/]*\.[cm]?[jt]s$"
        ),
    ),
)
_HEADER = "| Name | Kind | File |"
_RULE = "| --- | --- | --- |"
_NOT_INSTALLED_WARNING = (
    "symbols not scanned: tree-sitter is not installed (install strata-kb[code])"
)
_ROOT_SLUG = "root"
# Kind of a name re-exported around an import cycle before its target is
# known; `symbols()` replaces it with the concrete kind another path found,
# else `const`.
_UNKNOWN = "?"


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str  # function|class|interface|type|const|enum|member|css-var
    file: str


_Entry = tuple[str, str, bool]  # (name, kind, is the file's own default export)


@dataclass
class _Surface:
    names: list[tuple[str, str]]
    reexports: tuple[Reexport, ...]
    sites: list[str]
    defaults: frozenset[str] = frozenset()  # own names only `export default` gave
    default: str | None = None  # name the file's `export default` is listed under


def _skip_rule(rel: str) -> str | None:
    # C# test code is told by its project file only, Python test code by
    # pytest/unittest names; the generic `tests?/` and `.test.` rule is JS-only
    own = rel.endswith((".cs", ".py"))
    for label, pat in _SKIP_RULES:
        if not (own and label == "test") and pat.search(rel):
            return label
    return "test" if rel.endswith(".py") and _py_ast.is_test(rel) else None


def _bucket(scopes: list[Scope], rel: str) -> str:
    owner = scope_of(scopes, rel)
    if owner is not None:
        return owner.path
    top, sep, _rest = rel.partition("/")
    return top if sep else "."


class _Reader:
    """Reads files into symbols; caches each file's own surface so a barrel
    chain parses every file once."""

    def __init__(self, root: Path, files: list[str], warnings: list[str]):
        self._root = root
        self._warnings = warnings
        sources = frozenset(f for f in files if f.endswith(_EXTS))
        self._resolver = ModuleResolver(root, files, sources)
        self._surfaces: dict[str, _Surface] = {}
        self._memo: dict[str, tuple[list[_Entry], set[str]]] = {}

    def _surface(self, rel: str) -> _Surface:
        if rel not in self._surfaces:
            self._surfaces[rel] = self._read(rel)
        return self._surfaces[rel]

    def _read(self, rel: str) -> _Surface:
        lang = _ts.language_for(rel) or ""
        exporter = EXPORTERS.get(lang)
        data = _read(self._root, rel)
        if exporter is None or data is None:
            return _Surface([], (), [f"{rel}:1"])
        hint = _symbols_lang.HINTS.get(lang)
        if hint is not None and not hint.search(data):
            return _Surface([], (), [])
        try:
            tree = _kotlin_parse.parse(rel, data)
            names = exporter(tree, data)
            extras = _symbols_lang.EXTRAS.get(lang)
            found = extras(tree, data) if extras is not None else None
        except Exception as exc:  # noqa: BLE001 -- degrade, never crash: one bad file must not abort the run
            self._warnings.append(f"symbols: {rel} could not be read: {exc!r}")
            return _Surface([], (), [f"{rel}:1"])
        sites = [f"{rel}:{n}" for n in (found.unreadable if found else ())]
        line = (
            None
            if lang in _symbols_lang.LENIENT
            else _kotlin_parse.error_line(tree, lang)
        )
        if line is not None:
            sites.append(f"{rel}:{line}")
        default = found.default if found else None
        # a name also exported another way is a real named export too
        once = default is not None and sum(n == default for n, _k in names) == 1
        defaults = frozenset({default}) if once and default else frozenset()
        return _Surface(
            names, found.reexports if found else (), sites, defaults, default
        )

    def public(self, rel: str) -> tuple[list[_Entry], set[str]]:
        """Names `rel` exports (its own plus followed re-exports) and the
        sites that make that list uncertain."""
        names, sites, _cuts = self._public(rel, frozenset())
        return names, sites

    def _public(
        self, rel: str, seen: frozenset[str]
    ) -> tuple[list[_Entry], set[str], frozenset[str]]:
        """Third item: the ancestors in `seen` a cycle was cut at. A result
        that depended on such a cut is only valid under that `seen`, so only
        cut-free results are memoized."""
        if rel in self._memo:
            return *self._memo[rel], frozenset()
        surface = self._surface(rel)
        names = [(n, k, n.split(".")[0] in surface.defaults) for n, k in surface.names]
        sites = set(surface.sites)
        cuts: set[str] = set()
        for reexport in surface.reexports:
            more, extra, cut = self._follow(rel, reexport, seen | {rel})
            names += more
            sites |= extra
            cuts |= cut
        cuts.discard(rel)
        if not cuts:
            self._memo[rel] = (names, sites)
        return names, sites, frozenset(cuts)

    def _follow(
        self, rel: str, reexport: Reexport, seen: frozenset[str]
    ) -> tuple[list[_Entry], set[str], frozenset[str]]:
        target = self._resolver.resolve(rel, reexport.spec)
        outside = target is None and self._resolver.is_external(rel, reexport.spec)
        site = f"{rel}:{reexport.line}"
        if reexport.kind == "star":
            if target is None:
                return [], {site}, frozenset()  # names unknown
            if target in seen:
                return [], set(), frozenset({target})
            names, sites, cuts = self._public(target, seen)
            # `export *` never carries the target's own default
            return [e for e in names if not e[2]], sites, cuts
        sites = {site} if target is None and not outside else set()
        if reexport.kind == "ns":
            return (
                [
                    (exported, "const", exported == DEFAULT_NAME)
                    for _s, exported in reexport.names
                ],
                sites,
                frozenset(),
            )
        there: list[_Entry] = []
        cuts: frozenset[str] = frozenset()
        cycle = target is not None and target in seen
        if target is not None and target in seen:
            # a cycle: only the target's own declarations, for the kinds
            surface = self._surface(target)
            there = [
                (n, k, n.split(".")[0] in surface.defaults) for n, k in surface.names
            ]
            cuts = frozenset({target})
        elif target is not None:
            there, _sites, cuts = self._public(target, seen)
        own = self._surface(target).default if target is not None else None
        default = own or next((n for n, _k, d in there if d and "." not in n), None)
        names: list[_Entry] = []
        for imported, exported in reexport.names:
            from_default = imported == DEFAULT_NAME
            source = (default or DEFAULT_NAME) if from_default else imported
            kinds = [k for n, k, _d in there if n == source]
            concrete = list(dict.fromkeys(k for k in kinds if k != _UNKNOWN))
            if any(n.startswith(source + ".") for n, _k, _d in there):
                # declaration merging: the members belong to the value
                concrete = [
                    k for k in concrete if k not in ("type", "interface")
                ] or concrete
            guess = _UNKNOWN if cycle or cuts or _UNKNOWN in kinds else "const"
            is_default = exported == DEFAULT_NAME
            if is_default and from_default and target is not None:
                named = default if default and default != DEFAULT_NAME else None
                exported = named or PurePosixPath(target).stem
            elif is_default and not from_default:
                exported = imported  # `{ Foo as default }`: still called Foo
            # one row per concrete kind, as the declaring file lists them
            names += [(exported, kind, is_default) for kind in concrete or [guess]]
            prefix = source + "."
            names += [
                (f"{exported}.{n[len(prefix) :]}", k, is_default)
                for n, k, _d in there
                if n.startswith(prefix)
            ]
        return names, sites, cuts

    def symbols(self, rel: str) -> tuple[list[Symbol], set[str]]:
        names, sites = self.public(rel)
        stem = PurePosixPath(rel).stem
        known = {n for n, k, _d in names if k != _UNKNOWN}
        # a name only an import cycle vouches for is declared nowhere: a site
        orphans = {n for n, k, _d in names if k == _UNKNOWN and n not in known}
        found = [
            Symbol(stem if n == DEFAULT_NAME else n, k, rel)
            for n, k, _d in names
            if k != _UNKNOWN
        ]
        return found, sites | ({f"{rel}:1"} if orphans else set())


def _test_projects(root: Path, files: list[str], warnings: list[str]) -> frozenset[str]:
    """C# test project dirs; if detection itself fails, none (and a warning)."""
    try:
        return _cs_ast.test_project_dirs(root, files, warnings)
    except Exception as exc:  # noqa: BLE001 -- degrade, never abort the ingest
        warnings.append(f"symbols: C# test project detection failed: {exc!r}")
        return frozenset()


def _row_detail(skipped: Counter[str], sites: set[str]) -> str:
    # "; " separates sites in the coverage detail, so a file name containing
    # it must not leak through (lossy by one space); same rule as routes.py.
    parts = (
        [
            "skipped "
            + ", ".join(
                f"{skipped[label]} {label}"
                for label, _p in _SKIP_RULES
                if skipped[label]
            )
        ]
        if skipped
        else []
    )
    return "; ".join(parts + sorted(s.replace("; ", ";") for s in sites))


def _slugs(keys: list[str]) -> list[str]:
    """One unique id slug per key. Normalization maps `a-b` and `a_b` to the
    same slug, so a collision re-slugs the whole set (same pattern as pages);
    the repo root is always `root`, and a directory that would take that id
    gets a suffix instead."""
    others = [k for k in keys if k != "."]
    own = [assign_slugs([k])[0] for k in others]
    slugs = own if len(set(own)) == len(own) else assign_slugs(others)
    by_key = {
        k: f"{s}-{hashlib.sha256(k.encode()).hexdigest()[:6]}" if s == _ROOT_SLUG else s
        for k, s in zip(others, slugs, strict=True)
    }
    return [_ROOT_SLUG if k == "." else by_key[k] for k in keys]


def _section(slug: str, label: str, found: set[Symbol]) -> CodeSection:
    ordered = sorted(found, key=lambda s: (s.file, s.name, s.kind))
    kinds = Counter(s.kind for s in ordered)
    count = len(ordered)
    return CodeSection(
        id=f"sym.{slug}",
        title=f"Symbols: {label}",
        summary=(
            f"{count} exported symbol{'s' * (count != 1)} in {label} ("
            + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
            + ")."
        ),
        group="symbols",
        l2_md="\n".join(
            [
                _HEADER,
                _RULE,
                *(
                    "| "
                    + " | ".join(escape_cell(c) for c in (s.name, s.kind, s.file))
                    + " |"
                    for s in ordered
                ),
            ]
        )
        + "\n",
        l3_md="```\n"
        + "\n".join(f"{s.name}  {s.kind}  {s.file}" for s in ordered)
        + "\n```\n",
    )


class SymbolsExtractor:
    name = "symbols"

    def detect(self, root: Path) -> bool:
        # `detect` never sees `opts`, so the default kb dir stands in --
        # the same structural exception the other extractors document.
        return any(
            _ts.language_for(name) is not None
            for _depth, _rel, names in walk_tree(root, root / ".kb")
            for name in names
        )

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        scopes = find_scopes(root, opts.kb_dir)
        files = _repo_files(root, opts)
        buckets: dict[str, dict[str, list[str]]] = {}
        for rel in files:
            lang = _ts.language_for(rel)
            if lang is not None:
                buckets.setdefault(_bucket(scopes, rel), {}).setdefault(
                    lang, []
                ).append(rel)
        if not buckets:
            return ExtractResult()
        if not _ts.available():
            return ExtractResult(
                warnings=[_NOT_INSTALLED_WARNING],
                coverage=[
                    CoverageRow("symbols", key, lang, "not scanned", NOT_INSTALLED)
                    for key in sorted(buckets)
                    for lang in sorted(buckets[key])
                ],
            )
        warnings: list[str] = []
        reader = _Reader(root, files, warnings)
        # C# test projects are told by their project file, not by a name
        test_projects = _test_projects(root, files, warnings)
        coverage: list[CoverageRow] = []
        found: dict[str, set[Symbol]] = {}
        for key in sorted(buckets):
            symbols = found.setdefault(key, set())
            for lang in sorted(buckets[key]):
                if lang not in EXPORTERS:
                    coverage.append(
                        CoverageRow(
                            "symbols",
                            key,
                            lang,
                            "not scanned",
                            f"no exporter for {lang} yet",
                        )
                    )
                    continue
                skipped: Counter[str] = Counter()
                sites: set[str] = set()
                for rel in buckets[key][lang]:
                    rule = _skip_rule(rel)
                    if rule is None and lang == _cs_ast.LANG:
                        rule = "test" if _cs_ast.is_test(rel, test_projects) else None
                    if rule is not None:
                        skipped[rule] += 1
                        continue
                    syms, more = reader.symbols(rel)
                    symbols.update(syms)
                    sites |= more
                coverage.append(
                    CoverageRow(
                        "symbols",
                        key,
                        lang,
                        "partial" if sites else "complete",
                        _row_detail(skipped, sites),
                    )
                )
        keys = [k for k in sorted(found) if found[k]]
        sections = [
            _section(slug, opts.repo_id if key == "." else key, found[key])
            for slug, key in zip(_slugs(keys), keys, strict=True)
        ]
        return ExtractResult(sections=sections, warnings=warnings, coverage=coverage)
