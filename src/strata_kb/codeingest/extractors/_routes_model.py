"""Shapes shared by `routes.py` and the per-language `_routes_<lang>.py`
adapters.

Kept apart from `routes.py` so an adapter module can import `Route` and
`AdapterResult` without importing the module that imports it. `routes.py`
re-exports both names; that is where callers import them from.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Route:
    method: str  # upper-case HTTP verb, or "ANY"
    path: str  # full joined path, starts with "/"
    handler: str
    file: str  # repo-relative posix path of the declaring file
    line: int
    request_type: str = ""


@dataclass
class AdapterResult:
    routes: list[Route] = field(default_factory=list)
    # "file:line" of every recognised routing form that did not become a
    # Route (dynamic path or prefix, unfollowable mount, unknown shape).
    # `routes.py` turns each into a `partial` coverage detail; never drop one.
    dynamic_sites: list[str] = field(default_factory=list)


def join_path(*parts: str) -> str:
    """Join route path fragments: one leading "/", no empty or doubled
    segments, no trailing "/" (except the bare root)."""
    segments = [seg for part in parts for seg in part.split("/") if seg]
    return "/" + "/".join(segments)
