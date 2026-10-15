"""Laravel route statements of one PHP file, as a context-free program.

`build()` reads a file once into a tree of items that do not depend on where
the file is reached from: routes (with the prefix and controller written on
their own chain), groups (a prefix, a controller and the routes inside the
closure), file includes (`->group(base_path('routes/x.php'))`, `require`,
`loadRoutesFrom`, `withRouting(web:, api:)`) and sites. `_routes_laravel`
plays the program under the prefix its caller gives it, so the result does
not depend on which file is read first.

**Default to a site, never drop.** A chain on the `Route` facade (or on
`$router`) that does not become a route is a site: a computed path, verb or
prefix, an unknown method (a macro), a prefix set after the route, a
resource option that changes paths (`parameters`, `shallow`), a singleton
resource, an include this scan cannot resolve. A route-shaped call on a
receiver that cannot be resolved (`$app->get('/x', fn () => 1)`) is a site
too; an ordinary `->get('key')` is not (collections, HTTP clients, caches).
Everything below is iterative, so a deeply nested or very long file cannot
exhaust the stack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _laravel_resource as resource
from strata_kb.codeingest.extractors import _php_ast as php
from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._laravel_paths import (
    Finder,
    path_spec,
    resolve_path,
)
from strata_kb.codeingest.extractors._routes_jsutil import _text

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = [
    "Delta",
    "Finder",
    "GroupItem",
    "IncludeItem",
    "Item",
    "Program",
    "RouteItem",
    "SiteItem",
    "build",
    "resolve_path",
]

INLINE = "(inline)"
_VERBS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "options": "OPTIONS",
    "any": "ANY",
}
# macros of common packages that register one GET route, like `Route::get()`
_GET_MACROS = frozenset({"inertia", "livewire", "volt"})
_HTTP = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
# chain links that only configure the routes after them
_MODIFIERS = frozenset(
    {
        "middleware", "name", "as", "domain", "namespace", "scopeBindings",
        "withoutScopedBindings", "withoutMiddleware", "can", "block", "defaults",
        "withTrashed", "missing", "excludeMiddleware", "setWheres", "where",
        "lazy", "soft",
    }
)  # fmt: skip
_TERMINALS = frozenset(
    {
        *_VERBS, *_GET_MACROS, "match", "view", "redirect", "permanentRedirect", "fallback",
        "resource", "apiResource", "resources", "apiResources", "singleton",
        "apiSingleton", "group",
    }
)  # fmt: skip
# `Route::x()` calls that register nothing
_PLAIN_STATIC = frozenset(
    {
        "pattern", "model", "bind", "has", "is", "current", "currentRouteName",
        "currentRouteAction", "currentRouteNamed", "currentRouteUses", "input",
        "getRoutes", "getCurrentRoute", "getCurrentRequest", "middlewareGroup",
        "aliasMiddleware", "substituteBindings", "uses", "dispatch", "hasMacro",
        "macro", "mixin", "flushMiddlewareGroups", "pushMiddlewareToGroup",
        "prependMiddlewareToGroup", "singularResourceParameters",
        "resourceParameters", "matched", "respondWithRoute", "named",
    }
)  # fmt: skip
_CODE = frozenset(
    {
        "class_declaration", "trait_declaration", "enum_declaration",
        "interface_declaration", "method_declaration", "function_definition",
        "anonymous_function", "arrow_function",
    }
)  # fmt: skip
_CALLS = (
    "member_call_expression",
    "nullsafe_member_call_expression",
    "scoped_call_expression",
)
_INCLUDES = (
    "require_expression",
    "require_once_expression",
    "include_expression",
    "include_once_expression",
)
_FACADES = frozenset({"Route", "Illuminate\\Support\\Facades\\Route"})
# route registrations of other packages, which this scan does not expand
_FOREIGN_ROUTES = frozenset(
    {
        ("Auth", "routes"), ("Volt", "route"), ("Folio", "path"),
        ("Passport", "routes"), ("Broadcast", "routes"),
    }
)  # fmt: skip
_BROADCAST_AUTH = "/broadcasting/auth"

_STRING_HANDLER = re.compile(
    r"\\?(?:[A-Z][A-Za-z0-9]*\\)*([A-Z][A-Za-z0-9]*)@([A-Za-z_]\w*)"
)
_CONTROLLER_NAME = re.compile(r"\\?(?:[A-Z][A-Za-z0-9]*\\)*[A-Z][A-Za-z0-9]*Controller")
_BARE_METHOD = re.compile(r"[a-z_][A-Za-z0-9_]*")
_IDENT = re.compile(r"[A-Za-z_]\w*")
_CLASS_AT = re.compile(r"[A-Z][\w\\]*@\w+")
# resource options that leave the paths alone
_RESOURCE_OPTIONS = frozenset({"names", "middleware", "where", "as", "missing"})


@dataclass(frozen=True)
class Delta:
    parts: tuple[str, ...] = ()
    controller: str | None = None


@dataclass(frozen=True)
class RouteItem:
    method: str
    uri: str
    handler: str
    bare: str | None  # `'method'` of a controller group, resolved when played
    delta: Delta
    line: int


@dataclass
class GroupItem:
    delta: Delta
    items: list[Item] = field(default_factory=list)


@dataclass(frozen=True)
class IncludeItem:
    delta: Delta
    targets: tuple[str, ...]
    line: int


@dataclass(frozen=True)
class SiteItem:
    line: int
    soft: bool = False  # only counts when the file has other routing content


Item = RouteItem | GroupItem | IncludeItem | SiteItem


@dataclass
class Program:
    items: list[Item] = field(default_factory=list)
    script: bool = True  # every routing statement is at the file's top level
    routing: bool = False  # registers routes or includes other route files
    syntax_line: int | None = None

    @property
    def content(self) -> bool:
        return bool(self.items)


def _elements(node: Node) -> list[tuple[Node | None, Node]]:
    out: list[tuple[Node | None, Node]] = []
    for element in node.named_children:
        parts = [c for c in element.named_children if c.type != "comment"]
        if element.type != "array_element_initializer" or not parts:
            out.append((None, element))
        elif len(parts) == 1:
            out.append((None, parts[0]))
        else:
            out.append((parts[0], parts[1]))
    return out


def _arg(args: tuple[php.Arg, ...], index: int, name: str = "") -> Node | None:
    for a in args:
        if (name and a.name == name) or (a.name is None and a.index == index):
            return a.value
    return None


class _Builder:
    def __init__(self, rel: str, root: Node, finder: Finder):
        self.rel = rel
        self.root = root
        self.finder = finder
        self.uses = php.use_map(root)
        self.program = Program()
        self.stack: list[tuple[Node, list[Item], bool]] = []

    # -- traversal ---------------------------------------------------------

    def run(self) -> Program:
        out = self.program.items
        self.stack.append((self.root, out, True))
        while self.stack:
            node, items, top = self.stack.pop()
            if node.type in _CALLS:
                self.call(node, items, top)
            elif node.type in _INCLUDES:
                self.require(node, items, top)
            else:
                nested = top and node.type not in _CODE
                self.stack.extend(
                    (c, items, nested) for c in reversed(node.named_children)
                )
        self._drop_soft(self.program.items)
        return self.program

    def add(self, items: list[Item], item: Item, top: bool) -> None:
        items.append(item)
        if not top:
            self.program.script = False
        if not isinstance(item, SiteItem):
            self.program.routing = True

    def site(self, items: list[Item], top: bool, line: int, soft: bool = False) -> None:
        self.add(items, SiteItem(line, soft), top)

    def _drop_soft(self, root: list[Item]) -> None:
        def hard(items: list[Item]) -> bool:
            todo = list(items)
            while todo:
                item = todo.pop()
                if isinstance(item, GroupItem):
                    todo.extend(item.items)
                elif not (isinstance(item, SiteItem) and item.soft):
                    return True
            return False

        if hard(root):
            return
        todo = [root]
        while todo:
            items = todo.pop()
            items[:] = [i for i in items if not (isinstance(i, SiteItem) and i.soft)]
            todo.extend(i.items for i in items if isinstance(i, GroupItem))

    # -- classification ----------------------------------------------------

    def call(self, node: Node, items: list[Item], top: bool) -> None:
        base, links = php.chain(node)
        kind = self.classify(base, links)
        if kind == "route":
            self.route_chain(node, links, items, top)
        elif kind == "foreign":
            self.foreign(node, base, links, items, top)
        else:
            self.other_chain(base, links, items, top)

    def foreign(
        self,
        node: Node,
        base: Node,
        links: list[php.Link],
        items: list[Item],
        top: bool,
    ) -> None:
        # `Broadcast::routes()` registers the channel authorisation endpoint
        if (
            php.short(self._facade(base)) == "Broadcast"
            and len(links) == 1
            and not links[0].args
        ):
            for method in ("GET", "POST"):
                row = RouteItem(
                    method, _BROADCAST_AUTH, INLINE, None, Delta(), links[0].line
                )
                self.add(items, row, top)
        else:
            self.site(items, top, _ts.line_of(node))

    def _facade(self, scope: Node) -> str:
        return php.resolve(_text(scope), self.uses)

    def classify(self, base: Node, links: list[php.Link]) -> str:
        if not links:
            return "other"
        if base.type in ("name", "qualified_name", "relative_name"):
            full = self._facade(base)
            if full in _FACADES:
                return "route"
            if (php.short(full), links[0].name) in _FOREIGN_ROUTES:
                return "foreign"
            return "other"
        return "route" if self._is_router(base) else "other"

    def _known_class(self, base: Node) -> bool:
        """A static call on a class the file imports (or spells in full) is
        that class's own API, not a route registration."""
        if base.type not in ("name", "qualified_name", "relative_name"):
            return False
        written = _text(base).replace(" ", "")
        return written.startswith("\\") or written.split("\\")[0] in self.uses

    def _is_router(self, node: Node) -> bool:
        if node.type == "variable_name":
            return _text(node) == "$router"
        if node.type == "subscript_expression":
            return any(php.literal(c) == "router" for c in node.named_children[1:])
        if node.type == "function_call_expression":
            fn = node.child_by_field_name("function")
            args = php.call_args(node.child_by_field_name("arguments"))
            return (
                fn is not None
                and _text(fn) in ("app", "resolve")
                and bool(args)
                and (
                    php.literal(args[0].value) == "router"
                    or php.class_ref(args[0].value) == "Router"
                )
            )
        return False

    # -- chains that are not the Route facade ---------------------------------

    def other_chain(
        self, base: Node, links: list[php.Link], items: list[Item], top: bool
    ) -> None:
        for link in links:
            if link.name == "withRouting":
                self.with_routing(link, items, top)
                continue
            if link.name == "loadRoutesFrom" and len(link.args) == 1:
                self.include(link.args[0].value, Delta(), link.line, items, top)
                continue
            if _shaped(link) and not self._known_class(base):
                self.site(items, top, link.line)
            self.stack.extend((a.value, items, top) for a in reversed(link.args))
        self.stack.append((base, items, top))

    def with_routing(self, link: php.Link, items: list[Item], top: bool) -> None:
        prefix = "api"
        rest: list[php.Arg] = []
        for a in link.args:
            if a.name == "apiPrefix":
                value = php.literal(a.value)
                if value is None:
                    self.site(items, False, _ts.line_of(a.value))
                else:
                    prefix = value.strip("/")
            else:
                rest.append(a)
        for a in rest:
            if a.name in ("web", "api"):
                delta = Delta((prefix,) if a.name == "api" and prefix else ())
                value = php.unwrap(a.value)
                exprs = (
                    [v for _k, v in _elements(value)]
                    if value is not None and value.type == "array_creation_expression"
                    else [a.value]
                )
                for expr in exprs:
                    self.include(expr, delta, _ts.line_of(expr), items, False)
            elif a.name == "health":
                health = php.literal(a.value)
                if health is None:
                    self.site(items, False, _ts.line_of(a.value))
                else:
                    self.add(
                        items,
                        RouteItem(
                            "GET", health, INLINE, None, Delta(), _ts.line_of(a.value)
                        ),
                        False,
                    )
            else:
                self.stack.append((a.value, items, False))

    # -- the Route facade ----------------------------------------------------

    def route_chain(
        self, node: Node, links: list[php.Link], items: list[Item], top: bool
    ) -> None:
        parts: list[str] = []
        controller: str | None = None
        i = 0
        while i < len(links) and _is_modifier(links[i].name):
            link = links[i]
            if link.name == "prefix":
                value = php.literal(_arg(link.args, 0, "prefix"))
                if value is None:
                    self.site(items, top, link.line)
                else:
                    parts.append(value)
            elif link.name == "controller":
                controller = php.class_ref(_arg(link.args, 0, "controller"))
            i += 1
        if i == len(links):
            first = links[0]
            if not (len(links) == 1 and first.name in _PLAIN_STATIC):
                self.site(items, top, _ts.line_of(node))
            return
        term = links[i]
        if term.name not in _TERMINALS:
            if not (i == 0 and term.name in _PLAIN_STATIC):
                self.site(items, top, term.line)  # a macro, or a computed method
            return
        delta = Delta(tuple(parts), controller)
        trailing = links[i + 1 :]
        if any(t.name == "prefix" for t in trailing):
            self.site(items, top, term.line)
        self.terminal(term, trailing, delta, items, top)

    def terminal(
        self,
        term: php.Link,
        trailing: list[php.Link],
        delta: Delta,
        items: list[Item],
        top: bool,
    ) -> None:
        name, args = term.name, term.args
        if name in _VERBS:
            self.verb(
                _VERBS[name],
                _arg(args, 0, "uri"),
                _arg(args, 1, "action"),
                term,
                delta,
                items,
                top,
            )
        elif name in _GET_MACROS:
            self.verb(
                "GET",
                _arg(args, 0, "uri"),
                _arg(args, 1, "action"),
                term,
                delta,
                items,
                top,
            )
        elif name == "match":
            verbs = php.literal_list(_arg(args, 0, "methods"))
            upper = [v.upper() for v in verbs or []]
            if not upper or any(v not in _HTTP for v in upper):
                self.site(items, top, term.line)
                return
            for verb in upper:
                self.verb(
                    verb,
                    _arg(args, 1, "uri"),
                    _arg(args, 2, "action"),
                    term,
                    delta,
                    items,
                    top,
                )
        elif name == "view":
            self.verb("GET", _arg(args, 0, "uri"), None, term, delta, items, top)
        elif name in ("redirect", "permanentRedirect"):
            self.verb("ANY", _arg(args, 0, "uri"), None, term, delta, items, top)
        elif name == "fallback":
            self.add(
                items,
                RouteItem(
                    "GET", "{fallbackPlaceholder}", INLINE, None, delta, term.line
                ),
                top,
            )
        elif name in ("resource", "apiResource"):
            self.resource(term, trailing, delta, items, top)
        elif name in ("resources", "apiResources"):
            self.resources(term, delta, items, top)
        elif name == "group":
            self.group(term, delta, items, top)
        else:  # singleton, apiSingleton
            self.site(items, top, term.line)

    def verb(
        self,
        method: str,
        uri_node: Node | None,
        action: Node | None,
        term: php.Link,
        delta: Delta,
        items: list[Item],
        top: bool,
    ) -> None:
        uri = php.literal(uri_node)
        if uri is None:
            self.site(items, top, term.line)
            return
        handler, bare = _handler(action)
        self.add(items, RouteItem(method, uri, handler, bare, delta, term.line), top)

    def group(self, term: php.Link, delta: Delta, items: list[Item], top: bool) -> None:
        args = term.args
        target = args[-1].value if args else None
        parts = list(delta.parts)
        controller = delta.controller
        if len(args) == 2:
            attrs = php.unwrap(args[0].value)
            if attrs is None or attrs.type != "array_creation_expression":
                self.site(items, top, term.line)
            else:
                for key, value in _elements(attrs):
                    name = php.literal(key)
                    if name == "prefix":
                        text = php.literal(value)
                        if text is None:
                            self.site(items, top, term.line)
                        else:
                            parts.append(text)
                    elif name == "controller":
                        controller = php.class_ref(value) or controller
        merged = Delta(tuple(parts), controller)
        closure = php.unwrap(target)
        if closure is not None and closure.type in php.CLOSURES:
            body = closure.child_by_field_name("body")
            group = GroupItem(merged)
            self.add(items, group, top)
            if body is not None:
                self.stack.append((body, group.items, top))
        elif target is not None and len(args) in (1, 2):
            self.include(target, merged, term.line, items, top)
        else:
            self.site(items, top, term.line)

    # -- resources ----------------------------------------------------------

    def resource(
        self,
        term: php.Link,
        trailing: list[php.Link],
        delta: Delta,
        items: list[Item],
        top: bool,
    ) -> None:
        name = php.literal(_arg(term.args, 0, "name"))
        if name is None:
            self.site(items, top, term.line)
            return
        actions = list(resource.API if term.name == "apiResource" else resource.FULL)
        filters: list[tuple[str, list[Node]]] = []
        for link in trailing:
            if link.name in ("parameters", "shallow"):
                self.site(items, top, link.line)
            elif link.name in ("only", "except"):
                filters.append((link.name, [a.value for a in link.args]))
        options = _arg(term.args, 2, "options")
        if options is not None:
            self.options(options, term, filters, items, top)
        for kind, values in filters:
            named: set[str] = set()
            for value in values:
                found = php.literal_list(value)
                if found is None:
                    self.site(items, top, term.line)
                    break
                named.update(found)
            else:
                actions = [x for x in actions if (x in named) == (kind == "only")]
        controller = _controller(_arg(term.args, 1, "controller"))
        self.expand(name, controller, actions, term.line, delta, items, top)

    def options(
        self,
        node: Node,
        term: php.Link,
        filters: list[tuple[str, list[Node]]],
        items: list[Item],
        top: bool,
    ) -> None:
        """`['only' => [...], 'except' => [...]]`; any other option that
        changes the paths is a site."""
        listing = php.unwrap(node)
        if listing is None or listing.type != "array_creation_expression":
            self.site(items, top, term.line)
            return
        for key, value in _elements(listing):
            name = php.literal(key)
            if name in ("only", "except"):
                filters.append((name, [value]))
            elif name not in _RESOURCE_OPTIONS:
                self.site(items, top, term.line)

    def resources(
        self, term: php.Link, delta: Delta, items: list[Item], top: bool
    ) -> None:
        listing = php.unwrap(_arg(term.args, 0, "resources"))
        if (
            listing is None
            or listing.type != "array_creation_expression"
            or len(term.args) > 1
        ):
            self.site(items, top, term.line)
            return
        actions = list(resource.API if term.name == "apiResources" else resource.FULL)
        for key, value in _elements(listing):
            name = php.literal(key)
            if name is None:
                self.site(items, top, term.line)
                continue
            self.expand(
                name, php.class_ref(value), actions, term.line, delta, items, top
            )

    def expand(
        self,
        name: str,
        controller: str | None,
        actions: list[str],
        line: int,
        delta: Delta,
        items: list[Item],
        top: bool,
    ) -> None:
        rows = resource.expand(name, actions)
        if rows is None:
            self.site(items, top, line)
            return
        for action, method, uri in rows:
            handler = f"{controller}@{action}" if controller else INLINE
            self.add(items, RouteItem(method, uri, handler, None, delta, line), top)

    # -- includes ------------------------------------------------------------

    def require(self, node: Node, items: list[Item], top: bool) -> None:
        target = next((c for c in node.named_children if c.type != "comment"), None)
        if target is not None:
            self.include(target, Delta(), _ts.line_of(node), items, top, soft=True)

    def include(
        self,
        expr: Node,
        delta: Delta,
        line: int,
        items: list[Item],
        top: bool,
        soft: bool = False,
    ) -> None:
        spec = path_spec(expr)
        found = self.finder.find(spec[0], spec[1], self.rel) if spec else None
        if found:
            self.add(items, IncludeItem(delta, tuple(found), line), top)
        else:
            self.site(items, top, line, soft)


def _controller(node: Node | None) -> str | None:
    """`X::class`, or the legacy `'XController'` string. Only a string that
    is spelled like a controller class counts: any other literal stays out
    of the Handler column."""
    named = php.class_ref(node)
    if named is not None:
        return named
    text = php.literal(node)
    if text is not None and _CONTROLLER_NAME.fullmatch(text):
        return php.short(text)
    return None


def _is_modifier(name: str) -> bool:
    return (
        name in _MODIFIERS
        or name in ("prefix", "controller")
        or name.startswith("where")
    )


def _handler(node: Node | None) -> tuple[str, str | None]:
    """(handler column text, bare method awaiting a controller group)."""
    node = php.unwrap(node)
    if node is None or php.is_closure(node):
        return INLINE, None
    cls = php.class_ref(node)
    if cls is not None:
        return cls, None
    text = php.literal(node)
    if text is not None:
        match = _STRING_HANDLER.fullmatch(text)
        if match:
            return f"{match.group(1)}@{match.group(2)}", None
        return (INLINE, text) if _BARE_METHOD.fullmatch(text) else (INLINE, None)
    if node.type == "array_creation_expression":
        elements = _elements(node)
        if len(elements) == 2 and all(k is None for k, _v in elements):
            owner = php.class_ref(elements[0][1])
            method = php.literal(elements[1][1])
            if owner and method and _IDENT.fullmatch(method):
                return f"{owner}@{method}", None
        for key, value in elements:
            if php.literal(key) == "uses":
                return _handler(value)
    return INLINE, None


def _shaped(link: php.Link) -> bool:
    """Whether a call on an unresolved receiver reads like a route
    registration: `->get('/path', <closure | [X::class, 'm'] | 'X@m'>)`."""
    name = link.name
    if name == "match":
        verbs = php.literal_list(_arg(link.args, 0))
        if (
            not verbs
            or len(link.args) < 3
            or any(v.upper() not in _HTTP for v in verbs)
        ):
            return False
        uri, action = _arg(link.args, 1), _arg(link.args, 2)
    elif name in _VERBS and len(link.args) >= 2:
        uri, action = _arg(link.args, 0), _arg(link.args, 1)
    else:
        return False
    path = php.literal(uri)
    if path is None or not path.startswith("/"):
        return False
    action = php.unwrap(action)
    if action is None:
        return False
    if php.is_closure(action):
        return True
    text = php.literal(action)
    if text is not None:
        return _CLASS_AT.fullmatch(text) is not None
    if action.type == "array_creation_expression":
        return any(php.class_ref(v) for k, v in _elements(action) if k is None)
    return False


def build(rel: str, root: Node, finder: Finder) -> Program:
    return _Builder(rel, root, finder).run()
