"""Route attribute macros of Actix Web and Rocket: `#[get("/p")]`,
`#[route("/p", method = "GET")]` (Actix), `#[route(GET, uri = "/p")]`
(Rocket).

`#[get]` is a verb of both frameworks, so the attribute's provenance is
decided first: a path through `actix_web` / `rocket` (written out, imported,
glob-imported, or `#[macro_use] extern crate rocket`). A name that does not
resolve is *unknown* and claimed by whichever web framework the scope has;
one from any other crate is not claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._rs_syntax import elements, string_of, text

if TYPE_CHECKING:
    from tree_sitter import Node

    from strata_kb.codeingest.extractors._rs_index import Fn, Index, Mod
    from strata_kb.codeingest.extractors._rs_syntax import Attr

__all__ = ["ATTR_NAMES", "RouteAttr", "attr_framework", "route_attrs"]

VERBS = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options", "connect", "trace"}
)
ATTR_NAMES = VERBS | {"route"}
_ROOTS = {
    "actix_web": "actix",
    "actix_web_codegen": "actix",
    "rocket": "rocket",
    "rocket_codegen": "rocket",
}
_METHODS = frozenset(v.upper() for v in VERBS)


@dataclass(frozen=True)
class RouteAttr:
    methods: tuple[str, ...] | None  # None: unreadable
    path: str | None  # None: not a plain literal
    line: int
    framework: str | None  # actix | rocket | other | None (unknown)


def attr_framework(idx: Index, mod: Mod, attr: Attr) -> str | None:
    """Whose macro is this attribute? A written path or an explicit `use` is
    authoritative; a bare name is looked up through glob imports of the web
    crates only (`use diesel::prelude::*` exports a `delete` *function*, not
    the macro), then `#[macro_use] extern crate`."""
    segs = attr.segs
    res = None
    if len(segs) > 1:
        res = idx.resolve(mod, segs)
    elif segs and segs[0] in mod.uses:
        res = idx.resolve(mod, mod.uses[segs[0]])
    elif segs:
        for glob in mod.globs:
            hit = next((_ROOTS[g] for g in glob[:2] if g in _ROOTS), None)
            if hit is not None:
                return hit
    if res is not None and res.kind == "ext":
        return next((_ROOTS[g] for g in res.segs[:2] if g in _ROOTS), "other")
    if res is not None:
        return "other"  # an in-repo item of that name is not the web macro
    for crate, label in (("rocket", "rocket"), ("actix_web", "actix")):
        if crate in idx.macro_use:
            return label
    return None


def _kv(element: list[Node]) -> tuple[str, Node] | None:
    if len(element) == 3 and text(element[1]) == "=":
        return text(element[0]), element[2]
    return None


def _read(
    attr: Attr, framework: str | None
) -> tuple[tuple[str, ...] | None, str | None]:
    elems = elements(attr.args)
    path: str | None = None
    methods: list[str] = []
    first_is_path = (
        bool(elems)
        and len(elems[0]) == 1
        and elems[0][0].type
        in (
            "string_literal",
            "raw_string_literal",
        )
    )
    if first_is_path:
        path = string_of(elems[0][0])
    for i, elem in enumerate(elems):
        pair = _kv(elem)
        if pair is not None:
            key, value = pair
            if key in ("uri", "path") and path is None:
                path = string_of(value)
            elif key == "method":
                lit = string_of(value)
                if lit is None or lit.upper() not in _METHODS:
                    return None, path
                methods.append(lit.upper())
        elif i == 0 and not first_is_path:
            names = [text(n) for n in elem if n.type == "identifier"]
            if not names or any(n.upper() not in _METHODS for n in names):
                return None, path
            methods.extend(n.upper() for n in names)
    if attr.name in VERBS:
        return (attr.name.upper(),), path
    if not methods and framework == "rocket" and path is not None:
        return ("ANY",), path  # Rocket's `#[route("/<_..>")]` takes every method
    return (tuple(methods) or None), path


def route_attrs(idx: Index, fn: Fn) -> list[RouteAttr]:
    out: list[RouteAttr] = []
    for attr in fn.attrs:
        if attr.name not in ATTR_NAMES or attr.args is None:
            continue
        framework = attr_framework(idx, fn.mod, attr)
        methods, path = _read(attr, framework)
        if path is not None and framework == "rocket":
            path = path.split("?", 1)[0]
        out.append(RouteAttr(methods, path, attr.line, framework))
    return out
