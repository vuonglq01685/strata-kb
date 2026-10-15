"""Shared helpers of the Go (Gin) codeingest tests."""

from __future__ import annotations

from pathlib import Path

from strata_kb.codeingest.extractors import routes, symbols
from strata_kb.codeingest.types import CodeIngestOptions
from strata_kb.lintcore import table_rows

GIN = "github.com/gin-gonic/gin"
MAIN = "main.go"


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def gomod(root: Path, app: str = ".", module: str = "example.com/app") -> None:
    base = "" if app == "." else f"{app}/"
    write(
        root,
        f"{base}go.mod",
        f"module {module}\n\ngo 1.22\n\nrequire {GIN} v1.9.1\n",
    )


def opts(root: Path) -> CodeIngestOptions:
    return CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="d", repo_id="r"
    )


def run_routes(root: Path):
    return routes.RoutesExtractor().extract(root, opts(root))


def run_symbols(root: Path):
    return symbols.SymbolsExtractor().extract(root, opts(root))


def section(result, file: str):
    (found,) = [s for s in result.sections if s.title == file]
    return found


def rows_of(result, file: str) -> list[list[str]]:
    return table_rows(section(result, file).l2_md)[1:]


def row(result, scope: str = "."):
    (found,) = [r for r in result.coverage if r.scope == scope and r.area == "routes"]
    return found


def pairs(result) -> list[tuple[str, str]]:
    """(method, path) of every route, in path order."""
    found = [r for s in result.sections for r in table_rows(s.l2_md)[1:]]
    return [(r[0], r[1]) for r in sorted(found, key=lambda r: (r[1], r[0]))]


def triples(result) -> list[tuple[str, str, str]]:
    found = [r for s in result.sections for r in table_rows(s.l2_md)[1:]]
    return [(r[0], r[1], r[2]) for r in sorted(found, key=lambda r: (r[1], r[0]))]


def at(text: str, needle: str) -> int:
    """1-based line of the first line holding `needle`."""
    return next(n for n, ln in enumerate(text.splitlines(), 1) if needle in ln)


def everything(result) -> str:
    return "\n".join(
        s.l2_md + s.l3_md + s.summary for s in result.sections
    ) + "\n".join(r.detail for r in result.coverage)


def gin_app(root: Path, text: str, rel: str = MAIN) -> None:
    gomod(root)
    write(root, rel, text)


def verdict(result, scope: str = ".") -> tuple[str, str]:
    return row(result, scope).status, row(result, scope).detail
