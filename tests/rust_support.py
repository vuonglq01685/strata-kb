"""Shared helpers of the Rust (Actix Web / Axum / Rocket) codeingest tests."""

from __future__ import annotations

from pathlib import Path

from strata_kb.codeingest.extractors import routes, symbols
from strata_kb.codeingest.types import CodeIngestOptions
from strata_kb.lintcore import table_rows

MAIN = "src/main.rs"


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def cargo(root: Path, *deps: str, app: str = ".", name: str = "app") -> None:
    base = "" if app == "." else f"{app}/"
    lines = "".join(f'{dep} = "1"\n' for dep in deps)
    write(
        root,
        f"{base}Cargo.toml",
        f'[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n\n'
        f"[dependencies]\n{lines}",
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


def verdict(result, scope: str = ".") -> tuple[str, str]:
    return row(result, scope).status, row(result, scope).detail


def triples(result) -> list[tuple[str, str, str]]:
    """(method, path, handler) of every route, in path order."""
    found = [r for s in result.sections for r in table_rows(s.l2_md)[1:]]
    return [(r[0], r[1], r[2]) for r in sorted(found, key=lambda r: (r[1], r[0]))]


def pairs(result) -> list[tuple[str, str]]:
    return [(m, p) for m, p, _h in triples(result)]


def at(text: str, needle: str) -> int:
    """1-based line of the first line holding `needle`."""
    return next(n for n, ln in enumerate(text.splitlines(), 1) if needle in ln)


def everything(result) -> str:
    return "\n".join(
        s.l2_md + s.l3_md + s.summary for s in result.sections
    ) + "\n".join(r.detail for r in result.coverage)


def app(root: Path, dep: str, text: str, rel: str = MAIN) -> None:
    cargo(root, dep)
    write(root, rel, text)


def sym_rows(result) -> list[tuple[str, str, str]]:
    return sorted(
        (r[0], r[1], r[2]) for s in result.sections for r in table_rows(s.l2_md)[1:]
    )
