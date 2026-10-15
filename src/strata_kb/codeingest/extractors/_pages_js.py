"""Angular, Vue and React page adapters for `pages.py`.

Angular: arrays typed `Routes` / `Route[]`, or passed to
`RouterModule.forRoot/forChild` / `provideRouter`. Vue: the `routes` of
`createRouter({...})` / `new VueRouter({...})`, or arrays typed
`RouteRecordRaw[]`. React: `<Route path>` JSX trees and the arrays given to
`createBrowserRouter` / `useRoutes` (or typed `RouteObject[]`). Nested
`children` join paths; the rest of the contract is in `_pages_tree.py`.

All three need tree-sitter; `pages.py` reports `not scanned` without it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._pages_model import Page, PageResult
from strata_kb.codeingest.extractors._pages_tree import (
    ANGULAR,
    REACT,
    VUE,
    Flavor,
    Source,
    Walker,
    _imported,
    label,
    unwrap,
    walk_roots,
)
from strata_kb.codeingest.extractors._routes_jsutil import (
    _args,
    _lit,
    _scan,
    _site,
    _text,
    _walk,
)
from strata_kb.codeingest.extractors._routes_model import AdapterResult
from strata_kb.codeingest.extractors._scopes import Scope
from strata_kb.codeingest.extractors._ts import line_of

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["angular_pages", "react_pages", "vue_pages"]

_ANGULAR_HINT = re.compile(rb"\b(?:Routes|Route|RouterModule|provideRouter|ROUTES)\b")
_ANGULAR_TYPE = re.compile(r"^(?:Readonly)?(?:Routes|Route\[\]|Array<Route>)$")
_ANGULAR_CALLS = frozenset(
    {"RouterModule.forRoot", "RouterModule.forChild", "provideRouter"}
)
_VUE_HINT = re.compile(rb"vue-router|createRouter|new VueRouter|RouteRecordRaw")
_VUE_TYPE = re.compile(
    r"^(?:Readonly)?(?:RouteRecordRaw|RouteConfig)(?:\[\]|>)$|^Array<"
)
_VUE_TYPE_ITEM = re.compile(r"(?:RouteRecordRaw|RouteConfig)")
_VUE_CTORS = frozenset({"VueRouter", "Router"})
_REACT_HINT = re.compile(
    rb"react-router|<[\w.]*Route\b|createBrowserRouter|createHashRouter"
    rb"|createMemoryRouter|useRoutes|RouteObject"
)
_REACT_TYPE = re.compile(r"^(?:Readonly)?(?:RouteObject\[\]|Array<RouteObject>)$")
_REACT_CALLS = frozenset(
    {
        "createBrowserRouter",
        "createHashRouter",
        "createMemoryRouter",
        "createStaticRouter",
        "useRoutes",
    }
)
_CUSTOM_ROUTE = re.compile(r"(?:^|\.)\w*Route$")


def _declared_type(node: Node) -> str:
    annotation = node.child_by_field_name("type")
    inner = (
        annotation.named_children[0]
        if annotation and annotation.named_children
        else None
    )
    return _text(inner)


def _typed_tables(
    rel: str,
    tree: Tree,
    type_re: re.Pattern[str],
    src: Source,
    result: PageResult,
    out: list[tuple[str, Node]],
) -> None:
    """Arrays declared with a route-table type (`x: Routes = [...]`,
    `[...] as Routes`, `[...] satisfies Routes`)."""
    for node in _walk(tree.root_node):
        if node.type in ("variable_declarator", "public_field_definition"):
            if not type_re.match(_declared_type(node)):
                continue
            _add(rel, node.child_by_field_name("value"), src, result, out)
        elif node.type in ("as_expression", "satisfies_expression", "type_assertion"):
            kids = node.named_children
            asserted = node.type == "type_assertion"  # `<Routes>[...]`
            if len(kids) == 2 and type_re.match(
                _text(kids[0]).strip("<>") if asserted else _text(kids[1])
            ):
                _add(rel, kids[1 if asserted else 0], src, result, out)


def _add(
    rel: str,
    node: Node | None,
    src: Source,
    result: PageResult,
    out: list[tuple[str, Node]],
) -> bool:
    """Queue the array `node` is (or names); a site when it is neither."""
    found = src.value(rel, node)
    if found is not None and found[1].type == "array":
        out.append(found)
        return True
    if node is not None:
        result.dynamic_sites.append(_site(rel, node))
    return False


def _load(
    root: Path,
    files: list[str],
    repo_files: list[str],
    hint: re.Pattern[bytes],
    result: PageResult,
) -> tuple[Source, list[tuple[str, Tree]]]:
    """Parse the scope's files that match `hint` (unreadable or broken ones
    become sites on `result`) into a `Source` that can also follow imports."""
    scratch = AdapterResult()
    loaded = _scan(root, files, hint, scratch)
    result.dynamic_sites.extend(scratch.dynamic_sites)
    src = Source(root, repo_files, result)
    for rel, tree in loaded:
        src.put(rel, tree)
    return src, loaded


def _run(
    root: Path,
    scope_files: list[str],
    repo_files: list[str],
    hint: re.Pattern[bytes],
    flavor: Flavor,
    collect,
) -> PageResult:
    result = PageResult()
    src, loaded = _load(root, scope_files, repo_files, hint, result)
    tables: list[tuple[str, Node]] = []
    for rel, tree in loaded:
        collect(rel, tree, src, result, tables)
    walk_roots(src, flavor, tables, result)
    return result


# --- Angular ----------------------------------------------------------------


def _angular_collect(rel, tree, src, result, tables):
    _typed_tables(rel, tree, _ANGULAR_TYPE, src, result, tables)
    for node in _walk(tree.root_node):
        if node.type == "call_expression":
            if _text(node.child_by_field_name("function")) in _ANGULAR_CALLS:
                args = _args(node)
                if args:
                    _add(rel, args[0], src, result, tables)
        elif node.type in (
            "function_declaration",
            "method_definition",
            "arrow_function",
            "function_expression",
        ):
            ret = node.child_by_field_name("return_type")
            if ret is not None and _ANGULAR_TYPE.match(_text(ret).lstrip(": ")):
                result.dynamic_sites.append(_site(rel, node))  # table is computed
        elif node.type == "pair":
            key = _text(node.child_by_field_name("key"))
            if (
                key == "provide"
                and _text(node.child_by_field_name("value")) == "ROUTES"
            ):
                result.dynamic_sites.append(_site(rel, node))


def angular_pages(
    root: Path, scope: Scope, files: list[str], repo_files: list[str]
) -> PageResult:
    return _run(root, files, repo_files, _ANGULAR_HINT, ANGULAR, _angular_collect)


# --- Vue --------------------------------------------------------------------


def _router_options(
    rel: str,
    call: Node,
    src: Source,
    result: PageResult,
    tables: list[tuple[str, Node]],
) -> None:
    args = _args(call)
    found = src.value(rel, args[0]) if args else None
    if found is None or found[1].type != "object":
        result.dynamic_sites.append(_site(rel, call))
        return
    for pair in found[1].named_children:
        key = pair.child_by_field_name("key") if pair.type == "pair" else pair
        if (
            pair.type in ("pair", "shorthand_property_identifier")
            and key is not None
            and (_lit(key) or _text(key)) == "routes"
        ):
            value = pair.child_by_field_name("value") if pair.type == "pair" else pair
            _add(found[0], value, src, result, tables)
            return
    result.dynamic_sites.append(_site(rel, call))  # routes added later


def _vue_collect(rel, tree, src, result, tables):
    for node in _walk(tree.root_node):
        if node.type in ("variable_declarator", "public_field_definition"):
            typ = _declared_type(node)
            if _VUE_TYPE.match(typ) and _VUE_TYPE_ITEM.search(typ):
                _add(rel, node.child_by_field_name("value"), src, result, tables)
        elif node.type in ("as_expression", "satisfies_expression"):
            kids = node.named_children
            typ = _text(kids[1]) if len(kids) == 2 else ""
            if _VUE_TYPE.match(typ) and _VUE_TYPE_ITEM.search(typ):
                _add(rel, kids[0], src, result, tables)
        elif node.type == "call_expression":
            fn = node.child_by_field_name("function")
            name = _text(fn)
            if name == "createRouter":
                _router_options(rel, node, src, result, tables)
            elif name.endswith((".addRoute", ".addRoutes")):
                result.dynamic_sites.append(_site(rel, node))
        elif node.type == "new_expression":
            if _text(node.child_by_field_name("constructor")) in _VUE_CTORS:
                _router_options(rel, node, src, result, tables)


def vue_pages(
    root: Path, scope: Scope, files: list[str], repo_files: list[str]
) -> PageResult:
    return _run(root, files, repo_files, _VUE_HINT, VUE, _vue_collect)


# --- React ------------------------------------------------------------------


def _route_names(tree: Tree) -> frozenset[str]:
    """Local names of react-router's `Route` (`Route as R`, `RR.Route`)."""
    names = {
        local
        for local, (spec, imported) in _imported(tree).items()
        if spec.startswith("react-router") and imported == "Route"
    }
    names |= {
        f"{local}.Route"
        for local, (spec, imported) in _imported(tree).items()
        if spec.startswith("react-router") and imported == "*"
    }
    return frozenset(names or {"Route"})


def _tag(el: Node) -> Node | None:
    head = el.child_by_field_name("open_tag") if el.type == "jsx_element" else el
    return head


def _tag_name(el: Node) -> str:
    head = _tag(el)
    return _text(head.child_by_field_name("name")) if head is not None else ""


def _attrs(el: Node) -> dict[str, Node | None]:
    head = _tag(el)
    out: dict[str, Node | None] = {}
    for attr in head.named_children if head is not None else []:
        if attr.type != "jsx_attribute":
            continue
        name = _text(attr.named_children[0]) if attr.named_children else ""
        out[name] = attr.named_children[1] if len(attr.named_children) > 1 else None
    return out


def _attr_literal(value: Node | None) -> str | None:
    if value is not None and value.type == "jsx_expression" and value.named_children:
        value = value.named_children[0]
    return _lit(value)


def _jsx_kids(el: Node) -> list[Node]:
    return (
        [
            c
            for c in el.named_children
            if c.type not in ("jsx_opening_element", "jsx_closing_element")
        ]
        if el.type == "jsx_element"
        else []
    )


def _jsx_walk(
    walker: Walker,
    rel: str,
    el: Node,
    names: frozenset[str],
    prefix: str,
    layout: str,
) -> None:
    attrs = _attrs(el)
    path: str | None = None
    if "path" in attrs:
        path = _attr_literal(attrs["path"])
        if path is None:
            walker.site(rel, el)
            return
    elif "index" in attrs:
        path = ""
    if path and walker.splat(path):
        walker.site(rel, el)
    full = walker.full(prefix, path or "")
    kids = _jsx_kids(el)
    routes = [k for k in kids if k.type.startswith("jsx_") and _tag_name_of(k) in names]
    content = [k for k in kids if k not in routes and k.type != "jsx_text"]
    for stray in content:
        if any(_tag_name_of(n) in names for n in _walk(stray) if n is not stray):
            walker.site(rel, stray)  # Routes under a wrapper or a condition
    is_page = any(k in attrs for k in REACT.page_keys) or any(
        k.type != "comment" for k in content
    )
    if is_page and path is not None:
        walker.result.pages.append(Page(full, rel, line_of(el), layout))
    elif not (is_page or routes):
        walker.site(rel, el)
    here = next(
        (label(attrs[k]) for k in ("element", "Component", "component") if k in attrs),
        "",
    )
    for child in routes:
        _jsx_walk(walker, rel, child, names, full, here or layout)


def _tag_name_of(node: Node) -> str:
    if node.type not in ("jsx_element", "jsx_self_closing_element"):
        return ""
    return _tag_name(node)


def _react_collect(rel, tree, src, result, tables):
    _typed_tables(rel, tree, _REACT_TYPE, src, result, tables)
    for node in _walk(tree.root_node):
        if node.type != "call_expression":
            continue
        if _text(node.child_by_field_name("function")) in _REACT_CALLS:
            args = _args(node)
            first = unwrap(args[0]) if args else None
            if (
                first is not None
                and _text(first.child_by_field_name("function"))
                == "createRoutesFromElements"
            ):
                continue  # JSX tree, walked below
            if args:
                _add(rel, args[0], src, result, tables)


def react_pages(
    root: Path, scope: Scope, files: list[str], repo_files: list[str]
) -> PageResult:
    result = PageResult()
    src, loaded = _load(root, files, repo_files, _REACT_HINT, result)
    tables: list[tuple[str, Node]] = []
    for rel, tree in loaded:
        _react_collect(rel, tree, src, result, tables)
    walk_roots(src, REACT, tables, result)
    walker = Walker(src, REACT, result)
    for rel, tree in loaded:
        names = _route_names(tree)
        for node in _walk(tree.root_node):
            name = _tag_name_of(node)
            if name in names:
                if not _inside_route(node, names):
                    _jsx_walk(walker, rel, node, names, "", "")
            elif name and _CUSTOM_ROUTE.search(name) and "path" in _attrs(node):
                walker.site(rel, node)  # a Route wrapper (PrivateRoute, ...)
    return result


def _inside_route(node: Node, names: frozenset[str]) -> bool:
    parent = node.parent
    while parent is not None:
        if _tag_name_of(parent) in names:
            return True
        parent = parent.parent
    return False
