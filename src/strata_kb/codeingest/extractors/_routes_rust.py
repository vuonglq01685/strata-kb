"""Rust route adapters: Actix Web, Axum, Rocket.

All three read the package through one `_rs_index.Index` (modules, `use`
paths, every function) and run the `_rs_interp` evaluator over its function
bodies, so a router built in one file and registered in another resolves
whatever the file order.

**Handlers that nothing registers.** `#[get("/p")]` on a fn does not by
itself serve anything in Actix or Rocket: it is a route where `.service(h)` /
`routes![h]` puts it, under that scope or mount prefix. An attributed handler
that no recognised registration reaches is therefore *not listed* (that would
be a false route, possibly with the wrong prefix) but is a `file:line` site
at its attribute (dropping a handler that is registered through code this
adapter cannot follow would be a false `complete`). Dead handlers make the
scope `partial`; that is the over-partial side of the trade, by design.

**Provenance.** A path is only the framework's when it resolves to it
(`actix_web::..`, `axum::routing::get`, `rocket::build`) through the file's
`use` items; a bare `get(h)` with no axum import is nobody's. A value whose
origin is not proven (an external crate's function, a sibling workspace
member, an unresolved type) is unknown, and a routing call on it is a site.
Skipped: top-level `tests/`, `benches/`, `examples/`, `build.rs`,
`#[cfg(test)]` / `#[test]` items.
"""

from __future__ import annotations

from pathlib import Path

from strata_kb.codeingest.extractors import (
    _routes_actix,
    _routes_axum,
    _routes_rocket,
)
from strata_kb.codeingest.extractors._routes_model import AdapterResult
from strata_kb.codeingest.extractors._rs_index import Index
from strata_kb.codeingest.extractors._scopes import Scope
from strata_kb.codeingest.extractors.tree import tracked_files

__all__ = ["ADAPTERS"]


def _bin_files(root: Path, scope: Scope) -> list[str]:
    """`src/bin/**.rs` of the package. The shared walker prunes every
    directory called `bin` (build output in other ecosystems), but cargo
    builds `src/bin/*.rs` as binaries, so they are read back here: the
    tracked ones in a git repository, else the ones on disk."""
    base = "" if scope.path == "." else scope.path + "/"
    prefix = f"{base}src/bin/"
    tracked = tracked_files(root)
    if tracked is not None:
        return [p for p in tracked if p.startswith(prefix) and p.endswith(".rs")]
    return sorted(p.relative_to(root).as_posix() for p in (root / prefix).rglob("*.rs"))


def _adapter(run):  # type: ignore[no-untyped-def]
    def adapter(
        root: Path, scope: Scope, scope_files: list[str], _repo_files: list[str]
    ) -> AdapterResult:
        files = sorted({*scope_files, *_bin_files(root, scope)})
        return run(Index(root, scope, files))

    return adapter


ADAPTERS = {
    "Actix Web": _adapter(_routes_actix.run),
    "Axum": _adapter(_routes_axum.run),
    "Rocket": _adapter(_routes_rocket.run),
}
