"""A route as the Rust adapters build it: relative to the container (scope,
router, mount) it was registered in, joined to its parents' prefixes as the
containers are absorbed."""

from __future__ import annotations

from dataclasses import dataclass

from strata_kb.codeingest.extractors._routes_model import Route, join_path

__all__ = ["Frag", "emit", "prefixed"]


@dataclass(frozen=True)
class Frag:
    method: str
    path: str
    handler: str
    file: str
    line: int


def prefixed(frags: list[Frag], prefix: str) -> list[Frag]:
    return [
        Frag(f.method, join_path(prefix, f.path), f.handler, f.file, f.line)
        for f in frags
    ]


def emit(frags: list[Frag]) -> list[Route]:
    found = {
        Route(f.method, join_path(f.path), f.handler, f.file, f.line) for f in frags
    }
    return sorted(found, key=lambda r: (r.file, r.path, r.method, r.line))
