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

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from strata_kb.codeingest.extractors import _symbols_lang, _ts
from strata_kb.codeingest.extractors._coverage import NOT_INSTALLED
from strata_kb.codeingest.extractors._mdcells import escape_cell
from strata_kb.codeingest.extractors._routes_jsresolve import ModuleResolver
from strata_kb.codeingest.extractors._routes_jsutil import (
    _EXTS,
    _error_line,
    _parse,
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

# (label in the coverage detail, pattern); a file counts under the first match.
_SKIP_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("*.d.ts", re.compile(r"\.d\.[cm]?ts$")),
    ("generated", re.compile(r"\.generated\.|(?:^|/)__generated__/")),
    ("test", re.compile(r"\.(?:test|spec)\.|(?:^|/)(?:__tests__|tests?)/")),
)
_HEADER = "| Name | Kind | File |"
_RULE = "| --- | --- | --- |"
_NOT_INSTALLED_WARNING = (
    "symbols not scanned: tree-sitter is not installed (install strata-kb[code])"
)
_ROOT_SLUG = "root"


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str  # function|class|interface|type|const|enum|member|css-var
    file: str


@dataclass
class _Surface:
    names: list[tuple[str, str]]
    reexports: tuple[Reexport, ...]
    sites: list[str]
    defaults: frozenset[str] = frozenset()  # own names only `export default` gave


def _skip_rule(rel: str) -> str | None:
    return next((label for label, pat in _SKIP_RULES if pat.search(rel)), None)


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
        self._public: dict[str, tuple[list[tuple[str, str]], set[str]]] = {}

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
            tree = _parse(rel, data)
            names = exporter(tree, data)
            extras = _symbols_lang.EXTRAS.get(lang)
            found = extras(tree, data) if extras is not None else None
        except Exception as exc:  # noqa: BLE001 -- degrade, never crash: one bad file must not abort the run
            self._warnings.append(f"symbols: {rel} could not be read: {exc!r}")
            return _Surface([], (), [f"{rel}:1"])
        sites = [f"{rel}:{n}" for n in (found.unreadable if found else ())]
        line = None if lang in _symbols_lang.LENIENT else _error_line(tree)
        if line is not None:
            sites.append(f"{rel}:{line}")
        default = found.default if found else None
        # a name also exported another way is a real named export too
        once = default is not None and sum(n == default for n, _k in names) == 1
        defaults = frozenset({default}) if once and default else frozenset()
        return _Surface(names, found.reexports if found else (), sites, defaults)

    def public(
        self, rel: str, seen: frozenset[str] = frozenset()
    ) -> tuple[list[tuple[str, str]], set[str]]:
        """Names `rel` exports (its own plus followed re-exports) and the
        sites that make that list uncertain. `seen` stops import cycles."""
        if not seen and rel in self._public:
            return self._public[rel]
        surface = self._surface(rel)
        names = list(surface.names)
        sites = set(surface.sites)
        for reexport in surface.reexports:
            more, extra = self._follow(rel, reexport, seen | {rel})
            names += more
            sites |= extra
        if not seen:
            self._public[rel] = (names, sites)
        return names, sites

    def _follow(
        self, rel: str, reexport: Reexport, seen: frozenset[str]
    ) -> tuple[list[tuple[str, str]], set[str]]:
        target = self._resolver.resolve(rel, reexport.spec)
        outside = target is None and self._resolver.is_external(rel, reexport.spec)
        site = f"{rel}:{reexport.line}"
        if reexport.kind == "star":
            if target is None:
                return [], {site}  # names unknown
            if target in seen:
                return [], set()
            names, sites = self.public(target, seen)
            skip = self._surface(target).defaults | {DEFAULT_NAME}
            return [(n, k) for n, k in names if n.split(".")[0] not in skip], sites
        sites = {site} if target is None and not outside else set()
        if reexport.kind == "ns":
            return [(exported, "const") for _star, exported in reexport.names], sites
        there = (
            self.public(target, seen)[0]
            if target is not None and target not in seen
            else []
        )
        kinds = dict(there)
        names: list[tuple[str, str]] = []
        for imported, exported in reexport.names:
            names.append((exported, kinds.get(imported, "const")))
            prefix = imported + "."
            names += [
                (f"{exported}.{n[len(prefix) :]}", k)
                for n, k in there
                if n.startswith(prefix)
            ]
        return names, sites

    def symbols(self, rel: str) -> tuple[list[Symbol], set[str]]:
        names, sites = self.public(rel)
        stem = PurePosixPath(rel).stem
        return [
            Symbol(stem if n == DEFAULT_NAME else n, k, rel) for n, k in names
        ], sites


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
    own = [_ROOT_SLUG if k == "." else assign_slugs([k])[0] for k in keys]
    # a directory literally named `root` must not take the root's id
    return [
        s if own.count(s) == 1 else f"{s}-{assign_slugs([k])[0][-6:]}"
        for s, k in zip(own, keys, strict=True)
    ]


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
