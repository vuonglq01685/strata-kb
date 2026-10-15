"""Shared types of `kb code-ingest`: what an extractor receives and returns.

Every extractor imports these from here, never from `core`, so `core` can
import the extractor registry at the top of its module instead of at the
bottom, which would otherwise be an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CodeSection:
    id: str  # e.g. "svc.airspace-service" — no whitespace (mdutils._HEADING_RE)
    title: str  # e.g. "airspace-service"
    summary: str  # 1-2 deterministic sentences; MUST be non-empty (build invariant)
    group: str  # output file stem, e.g. "services" -> services.md + services.raw.md
    l2_md: str  # body under the "## <id> <title>" heading in the L2 file
    l3_md: str  # body under the same heading in the L3 file; fenced blocks only


@dataclass(frozen=True)
class CoverageRow:
    """One line of the `struct.coverage` table: how much of `area` was read."""

    area: str  # routes | pages | jobs | symbols | files | schema
    scope: str  # package/top-level directory the row covers, "." for the root
    framework: str  # framework or language the row covers
    status: str  # complete | partial | not scanned
    detail: str = ""  # e.g. "apps/api/src/x.ts:12"; empty when complete


@dataclass
class ExtractResult:
    sections: list[CodeSection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    coverage: list[CoverageRow] = field(default_factory=list)


@dataclass(frozen=True)
class CodeIngestOptions:
    repo_root: Path
    kb_dir: Path
    doc_id: str
    repo_id: str
    db_paths: tuple[Path, ...] = ()
    tags: tuple[str, ...] = ()
    scaffold_svc: bool = False

    def __post_init__(self) -> None:
        # A relative `kb_dir` is relative to the process CWD — the same
        # rule every other `kb` command's --kb-dir follows. Do not resolve
        # it against the repo root instead: no help text documented that,
        # and it wrote inside a repo the operator had not pointed at.
        # `tree.walk_tree()` prunes an absolute kb_dir only
        # when it lies inside repo_root, so a KB outside the repo is
        # simply not pruned — correct. `db_paths` keep resolving against
        # `repo_root`: a --db names a file inside the repository.
        root = self.repo_root.resolve()
        kb = self.kb_dir if self.kb_dir.is_absolute() else Path.cwd() / self.kb_dir
        db_paths = tuple(
            (p if p.is_absolute() else root / p).resolve() for p in self.db_paths
        )
        object.__setattr__(self, "repo_root", root)
        object.__setattr__(self, "kb_dir", kb.resolve())
        object.__setattr__(self, "db_paths", db_paths)


class Extractor(Protocol):
    name: str

    def detect(self, root: Path) -> bool: ...
    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult: ...
