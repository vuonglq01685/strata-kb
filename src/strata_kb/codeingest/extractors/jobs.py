"""jobs extractor -- `job.<file>` sections from scheduled jobs declared by
framework schedulers, plus the `jobs` rows of `struct.coverage`.

One section per declaring file or manifest. L2 is the table
`Name | Schedule | Handler | File`: Name is the method or function name (or
the decorator's own name, or the k8s `metadata.name`), Schedule the literal
expression as written (`0 3 * * *`, `every 5m`, `interval 60000ms`,
`hosted`) or `(dynamic)` with its `file:line` listed as a coverage site.

**Sources.** NestJS, Spring / Quarkus / Micronaut, Hangfire, Quartz, .NET
hosted services, Celery, Laravel, Symfony, node-cron, BullMQ, robfig/cron,
tokio-cron-scheduler (scanners in `_jobs_adapters.py` and its siblings) and
k8s CronJob YAML (`_jobs_k8s.py`, PyYAML only). GitHub Actions
`on.schedule` is not a job of the product and is excluded.

**Coverage.** One `jobs` row per scope that holds any scanned source or k8s
CronJob manifest, framework `-`, status ALWAYS `partial`: a job outside a
framework scheduler (OS cron, a hand-rolled loop) cannot be detected. The
detail is `JOBS_DETAIL`, then `NOT_INSTALLED` when the scope's sources
could not be parsed (no `code` extra; k8s manifests still work), then every
dynamic or unparseable site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from strata_kb.codeingest.extractors import _jobs_k8s, _ts
from strata_kb.codeingest.extractors._coverage import JOBS_DETAIL, NOT_INSTALLED
from strata_kb.codeingest.extractors._jobs_adapters import SCANNERS
from strata_kb.codeingest.extractors._jobs_model import Ctx, Job
from strata_kb.codeingest.extractors._mdcells import escape_cell
from strata_kb.codeingest.extractors._routes_jsutil import _error_line, _parse, _read
from strata_kb.codeingest.extractors._scopes import find_scopes, scope_of
from strata_kb.codeingest.extractors._slugs import assign_slugs
from strata_kb.codeingest.extractors.routes import _repo_files, _stem
from strata_kb.codeingest.extractors.tree import walk_tree
from strata_kb.codeingest.types import (
    CodeIngestOptions,
    CodeSection,
    CoverageRow,
    ExtractResult,
)

__all__ = ["JobsExtractor"]

_YAML = (".yaml", ".yml")
_STYLE_LANGS = frozenset({"css", "scss"})
# Only unambiguous test markers (same stance as routes).
_TEST_RE = re.compile(
    r"(?:^|/)(?:__tests__|__mocks__)/|(?:^|/)src/test/"
    r"|\.(?:test|spec|e2e-spec)\.[A-Za-z]+$|_test\.(?:go|py)$|(?:^|/)test_[^/]*\.py$"
)
_HEADER = "| Name | Schedule | Handler | File |"
_RULE = "| --- | --- | --- | --- |"
_NOT_PARSED_WARNING = (
    "jobs not scanned: tree-sitter is not installed (install strata-kb[code])"
)


def _is_source(rel: str) -> bool:
    lang = _ts.language_for(rel)
    return (
        lang is not None
        and lang not in _STYLE_LANGS
        and not rel.endswith(".d.ts")
        and not _TEST_RE.search(rel)
    )


def _is_yaml(rel: str) -> bool:
    return rel.lower().endswith(_YAML)


@dataclass
class _ScopeState:
    sources: int = 0
    manifests: int = 0
    sites: set[str] = field(default_factory=set)


def _scan_source(
    root: Path, rel: str, warnings: list[str]
) -> tuple[list[Job], list[str]]:
    scanners = SCANNERS.get(_ts.language_for(rel) or "", [])
    data = _read(root, rel)
    if data is None:
        return [], [f"{rel}:1"]
    active = [s for s in scanners if s.gate.search(data)]
    if not active:
        return [], []
    sites: list[str] = []
    try:
        tree = _parse(rel, data)
    except Exception as exc:  # noqa: BLE001 -- degrade, never crash: one bad file must not abort the run
        warnings.append(f"jobs: {rel} could not be parsed: {exc!r}")
        return [], [f"{rel}:1"]
    line = _error_line(tree)
    if line is not None:
        sites.append(f"{rel}:{line}")
    ctx = Ctx(rel, tree.root_node)
    for scanner in active:
        try:
            scanner.run(ctx)
        except Exception as exc:  # noqa: BLE001 -- degrade, never crash: one bad scanner must not abort the run
            warnings.append(f"jobs: scanner failed in {rel}: {exc!r}")
            sites.append(f"{rel}:1")
    return ctx.jobs, [*sites, *ctx.sites]


def _cells(*cells: str) -> str:
    return "| " + " | ".join(escape_cell(c) for c in cells) + " |"


def _section(slug: str, file: str, found: list[Job]) -> CodeSection:
    ordered = sorted(set(found), key=lambda j: (j.name, j.schedule, j.handler, j.line))
    l2 = [
        _HEADER,
        _RULE,
        *(_cells(j.name, j.schedule, j.handler, j.file) for j in ordered),
    ]
    l3 = [f"{j.name}  {j.schedule}  {j.handler}  {j.file}:{j.line}" for j in ordered]
    count = len(ordered)
    return CodeSection(
        id=f"job.{slug}",
        title=file,
        summary=f"{count} scheduled job{'s' * (count != 1)} declared in {file}.",
        group="jobs",
        l2_md="\n".join(l2) + "\n",
        l3_md="```\n" + "\n".join(l3) + "\n```\n",
    )


def _sections(by_file: dict[str, list[Job]]) -> list[CodeSection]:
    paths = sorted(p for p, found in by_file.items() if found)
    # path without suffix; the full path when two files differ only by suffix
    stems = [_stem(p) for p in paths]
    names = [p if stems.count(s) > 1 else s for p, s in zip(paths, stems, strict=True)]
    return [
        _section(slug, path, by_file[path])
        for path, slug in zip(paths, assign_slugs(names), strict=True)
    ]


class JobsExtractor:
    name = "jobs"

    def detect(self, root: Path) -> bool:
        # `detect` never sees `opts`, so the default kb dir stands in --
        # the same structural exception the other extractors document.
        return any(
            _is_source((rel / name).as_posix()) or _is_yaml(name)
            for _depth, rel, names in walk_tree(root, root / ".kb")
            for name in names
        )

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        scopes = find_scopes(root, opts.kb_dir)
        available = _ts.available()
        state: dict[str, _ScopeState] = {}
        by_file: dict[str, list[Job]] = {}
        warnings: list[str] = []
        for rel in _repo_files(root, opts):
            owner = scope_of(scopes, rel)
            key = owner.path if owner is not None else "."
            if _is_source(rel):
                entry = state.setdefault(key, _ScopeState())
                entry.sources += 1
                if not available:
                    continue
                scan = partial(_scan_source, root, rel, warnings)
            elif _is_yaml(rel):
                data = _read(root, rel)
                if data is None or b"CronJob" not in data:
                    continue
                entry = state.setdefault(key, _ScopeState())
                entry.manifests += 1
                scan = partial(
                    _jobs_k8s.scan, rel, data.decode("utf-8", errors="replace")
                )
            else:
                continue
            try:
                found, sites = scan()
            except Exception as exc:  # noqa: BLE001 -- degrade, never crash: no single file may abort the run
                warnings.append(f"jobs: {rel} failed: {exc!r}")
                found, sites = [], [f"{rel}:1"]
            if found:
                by_file.setdefault(rel, []).extend(found)
            # "; " separates sites in the coverage detail, so a file name
            # containing it must not leak through (lossy by one space).
            entry.sites.update(s.replace("; ", ";") for s in sites)

        coverage = []
        for path in sorted(state):
            entry = state[path]
            details = [JOBS_DETAIL]
            if entry.sources and not available:
                details.append(NOT_INSTALLED)
            coverage.append(
                CoverageRow(
                    "jobs",
                    path,
                    "-",
                    "partial",
                    "; ".join([*details, *sorted(entry.sites)]),
                )
            )
        if not available and any(s.sources for s in state.values()):
            warnings.append(_NOT_PARSED_WARNING)
        return ExtractResult(
            sections=_sections(by_file), warnings=warnings, coverage=coverage
        )
