"""Route-table walker shared by the Angular, Vue and React page adapters.

A route table is an array of route objects (`{ path, component, children }`).
`Source` parses files on demand and follows an identifier to its value
(same-file declaration, or a relative / tsconfig-path / workspace import, via
`ModuleResolver`); `Walker` turns arrays into `Page`s, joining nested
`children` and following Angular `loadChildren: () => import(...)`.

**Default to a site, never drop.** An element it cannot read (call, spread of
something it cannot follow, non-literal `path`, `matcher`), an object with no
key it knows, a lazy import it cannot resolve: each is a `file:line` site.

**Roots.** An array reached from another one (spread, identifier, lazy
import) is walked in that parent's context so its paths carry the parent
prefix; only arrays nobody reaches start at the top (`walk_roots`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._pages_model import Page, PageResult
from strata_kb.codeingest.extractors._routes_jsresolve import ModuleResolver
from strata_kb.codeingest.extractors._routes_jsutil import (
    _JS_LANGS,
    _args,
    _error_line,
    _lit,
    _parse,
    _read,
    _site,
    _text,
    _walk,
)
from strata_kb.codeingest.extractors._routes_model import join_path

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

_MAX_HOPS = 6
_WRAPPERS = ("as_expression", "satisfies_expression", "parenthesized_expression")
_NON_NULL = "non_null_expression"
_COMPONENT_KEYS = (
    "component",
    "loadComponent",
    "element",
    "Component",
    "components",
    "lazy",
)


@dataclass(frozen=True)
class Flavor:
    page_keys: frozenset[str]
    redirect_keys: frozenset[str] = frozenset()
    lazy_children: bool = False  # Angular `loadChildren`
    absolute_child: bool = True  # a leading "/" ignores the parent prefix
    # React Router `path="/app/*"` hands the rest to a nested <Routes> whose
    # parent prefix a static read cannot know
    descendant_splat: bool = False


ANGULAR = Flavor(
    frozenset({"component", "loadComponent"}),
    frozenset({"redirectTo"}),
    lazy_children=True,
    absolute_child=False,
)
VUE = Flavor(frozenset({"component", "components"}), frozenset({"redirect"}))
REACT = Flavor(
    frozenset({"element", "Component", "component", "lazy", "render"}),
    descendant_splat=True,
)


def unwrap(node: Node | None) -> Node | None:
    while node is not None and (node.type in _WRAPPERS or node.type == _NON_NULL):
        node = node.named_children[0] if node.named_children else None
    return node


class Source:
    """Trees by repo-relative path, parsed once; identifier -> value."""

    def __init__(self, root: Path, repo_files: list[str], result: PageResult):
        self._root = root
        self._result = result
        self._trees: dict[str, Tree | None] = {}
        sources = frozenset(f for f in repo_files if _ts.language_for(f) in _JS_LANGS)
        self.resolver = ModuleResolver(root, repo_files, sources)

    def put(self, rel: str, tree: Tree) -> None:
        self._trees[rel] = tree

    def tree(self, rel: str) -> Tree | None:
        if rel not in self._trees:
            data = _read(self._root, rel)
            tree = _parse(rel, data) if data is not None else None
            line = _error_line(tree) if tree is not None else 1
            if line is not None:
                self._result.dynamic_sites.append(f"{rel}:{line}")
            self._trees[rel] = tree
        return self._trees[rel]

    # -- identifier -> value ---------------------------------------------------

    def value(self, rel: str, node: Node | None) -> tuple[str, Node] | None:
        """`node` itself, or what an identifier it names is declared as."""
        node = unwrap(node)
        for _hop in range(_MAX_HOPS):
            if node is None:
                return None
            if node.type not in ("identifier", "shorthand_property_identifier"):
                return rel, node
            found = self._bind(rel, _text(node))
            if found is None:
                return None
            rel, node = found[0], unwrap(found[1])
        return None

    def _bind(self, rel: str, name: str) -> tuple[str, Node] | None:
        tree = self.tree(rel)
        if tree is None:
            return None
        # a top-level declaration wins over a same-named one in a function
        top = [d for stmt in tree.root_node.named_children for d in _declarators(stmt)]
        for node in [*top, *_walk(tree.root_node)]:
            if (
                node.type == "variable_declarator"
                and _text(node.child_by_field_name("name")) == name
                and node.child_by_field_name("value") is not None
            ):
                value = node.child_by_field_name("value")
                return (rel, value) if value is not None else None
        spec = _imported(tree).get(name)
        if spec is None:
            return None
        target = self.resolver.resolve(rel, spec[0])
        return self.exported(target, spec[1]) if target else None

    def exported(self, rel: str, name: str) -> tuple[str, Node] | None:
        tree = self.tree(rel)
        if tree is None:
            return None
        if name == "default":
            for stmt in tree.root_node.named_children:
                value = stmt.child_by_field_name("value")
                if stmt.type == "export_statement" and value is not None:
                    return rel, value
            return None
        return self._bind(rel, name)

    def classes(self, rel: str, name: str) -> list[Node]:
        tree = self.tree(rel)
        return [
            n
            for n in (_walk(tree.root_node) if tree is not None else [])
            if n.type in ("class_declaration", "abstract_class_declaration")
            and _text(n.child_by_field_name("name")) == name
        ]


def _declarators(stmt: Node) -> list[Node]:
    decl = stmt.child_by_field_name("declaration") or stmt
    return [c for c in decl.named_children if c.type == "variable_declarator"]


def _imported(tree: Tree) -> dict[str, tuple[str, str]]:
    """local name -> (specifier, imported name | "default")."""
    out: dict[str, tuple[str, str]] = {}
    for stmt in tree.root_node.named_children:
        if stmt.type != "import_statement":
            continue
        spec = _lit(stmt.child_by_field_name("source"))
        if spec is None:
            continue
        for clause in (c for c in stmt.named_children if c.type == "import_clause"):
            for part in clause.named_children:
                if part.type == "identifier":
                    out[_text(part)] = (spec, "default")
                elif part.type == "namespace_import" and part.named_children:
                    out[_text(part.named_children[0])] = (spec, "*")
                elif part.type == "named_imports":
                    for item in part.named_children:
                        name = _text(item.child_by_field_name("name"))
                        out[_text(item.child_by_field_name("alias")) or name] = (
                            spec,
                            name,
                        )
    return out


def label(node: Node | None) -> str:
    """Short, human text for a component expression (the layout column)."""
    node = unwrap(node)
    if node is None:
        return ""
    if node.type in ("identifier", "member_expression"):
        return _text(node)
    if node.type == "jsx_expression" and node.named_children:
        return label(node.named_children[0])
    if node.type in ("jsx_self_closing_element", "jsx_element"):
        head = node.child_by_field_name("open_tag") or node
        tag = head.child_by_field_name("name")
        return _text(tag)
    if node.type == "call_expression" and not _is_import(node):
        args = _args(node)
        return label(args[0]) if args else ""
    spec = next((s for s in (_import_spec(n) for n in _walk(node)) if s), "")
    return spec


def _is_import(call: Node) -> bool:
    fn = call.child_by_field_name("function")
    return fn is not None and fn.type == "import"


def _import_spec(node: Node) -> str | None:
    if node.type != "call_expression" or not _is_import(node):
        return None
    args = _args(node)
    return _lit(args[0]) if args else None


class Walker:
    def __init__(self, src: Source, flavor: Flavor, result: PageResult):
        self.src = src
        self.flavor = flavor
        self.result = result
        self.seen: set[tuple[str, int]] = set()
        self.lazy_failed = False  # a `loadChildren` could not be followed
        self._stack: list[tuple[str, int]] = []

    def site(self, rel: str, node: Node) -> None:
        self.result.dynamic_sites.append(_site(rel, node))

    def splat(self, path: str) -> bool:
        return self.flavor.descendant_splat and path.endswith("/*") and path != "/*"

    def full(self, prefix: str, path: str) -> str:
        if self.flavor.absolute_child and path.startswith("/"):
            return join_path(path)
        return join_path(prefix, path)

    # -- arrays and objects ----------------------------------------------------

    def array(self, rel: str, arr: Node, prefix: str, layout: str) -> None:
        key = (rel, arr.start_byte)
        if key in self._stack:  # a table that reaches itself
            self.site(rel, arr)
            return
        self.seen.add(key)
        self._stack.append(key)
        for el in arr.named_children:
            if el.type != "comment":
                self._element(rel, el, prefix, layout)
        self._stack.pop()

    def _element(self, rel: str, el: Node, prefix: str, layout: str) -> None:
        if el.type == "object":
            self.route(rel, el, prefix, layout)
            return
        target = el.named_children[0] if el.type == "spread_element" else el
        found = self.src.value(rel, target) if target is not None else None
        if found is not None and found[1].type == "array":
            self.array(found[0], found[1], prefix, layout)
        elif (
            found is not None
            and found[1].type == "object"
            and el.type != "spread_element"
        ):
            self.route(found[0], found[1], prefix, layout)
        else:
            self.site(rel, el)

    def _pairs(self, rel: str, obj: Node) -> dict[str, Node]:
        pairs: dict[str, Node] = {}
        for ch in obj.named_children:
            if ch.type == "pair":
                key = ch.child_by_field_name("key")
                name = (
                    None
                    if key is None or key.type == "computed_property_name"
                    else (_lit(key) if key.type == "string" else _text(key))
                )
                value = ch.child_by_field_name("value")
                if name is None or value is None:
                    self.site(rel, ch)
                else:
                    pairs[name] = value
            elif ch.type == "shorthand_property_identifier":
                pairs[_text(ch)] = ch
            elif ch.type not in ("comment", "method_definition"):
                self.site(rel, ch)  # spread or other: keys we cannot see
        return pairs

    def route(self, rel: str, obj: Node, prefix: str, layout: str) -> None:
        pairs = self._pairs(rel, obj)
        flavor = self.flavor
        path: str | None = None
        if "path" in pairs:
            path = _lit(pairs["path"])
            if path is None:  # prefix of every child unknown too
                self.site(rel, obj)
                return
        elif "matcher" in pairs:
            self.site(rel, obj)
            return
        elif "index" in pairs and _text(pairs["index"]) == "true":
            path = ""
        if "alias" in pairs or (path and self.splat(path)):
            self.site(rel, obj)  # a second URL / a nested router below here
        full = self.full(prefix, path or "")
        is_page = any(k in pairs for k in flavor.page_keys)
        children = pairs.get("children")
        lazy = pairs.get("loadChildren") if flavor.lazy_children else None
        if is_page and path is not None:
            self.result.pages.append(Page(full, rel, _ts.line_of(obj), layout))
        elif not (
            is_page
            or children is not None
            or lazy is not None
            or any(k in pairs for k in flavor.redirect_keys)
        ):
            self.site(rel, obj)
        here = next((label(pairs[k]) for k in _COMPONENT_KEYS if k in pairs), "")
        if children is not None:
            self.children(rel, children, full, here or layout)
        if lazy is not None:
            self._lazy(rel, lazy, full, here or layout)

    def children(self, rel: str, node: Node, prefix: str, layout: str) -> None:
        found = self.src.value(rel, node)
        if found is not None and found[1].type == "array":
            self.array(found[0], found[1], prefix, layout)
        else:
            self.site(rel, node)

    # -- Angular loadChildren --------------------------------------------------

    def _lazy(self, rel: str, node: Node, prefix: str, layout: str) -> None:
        specs = [s for s in (_import_spec(n) for n in _walk(node)) if s]
        target = self.src.resolver.resolve(rel, specs[0]) if len(specs) == 1 else None
        if target is None or not self._lazy_target(
            target, _then_name(node), prefix, layout
        ):
            self.lazy_failed = True
            self.site(rel, node)

    def _lazy_target(self, rel: str, name: str, prefix: str, layout: str) -> bool:
        found = self.src.exported(rel, name)
        value = self.src.value(*found) if found is not None else None
        if value is not None and value[1].type == "array":
            self.array(value[0], value[1], prefix, layout)
            return True
        # an NgModule: `RouterModule.forChild(<routes>)` in its own file, or
        # in a routing module it imports (`ng g module --route`)
        tree = self.src.tree(rel)
        classes = self.src.classes(rel, name)
        if tree is None or not classes:
            return False
        if self._for_child(rel, prefix, layout):
            return True
        imported = _imported(tree)
        targets = []
        for cls in classes:
            for dec in _decorators(cls):
                for pair in (n for n in _walk(dec) if n.type == "pair"):
                    if _text(pair.child_by_field_name("key")) != "imports":
                        continue
                    value = pair.child_by_field_name("value")
                    for item in value.named_children if value is not None else []:
                        spec = imported.get(_text(item))
                        found = (
                            self.src.resolver.resolve(rel, spec[0]) if spec else None
                        )
                        if found is not None:
                            targets.append(found)
        # every imported module is walked (no short-circuit): a module may
        # have several routing modules
        return any([self._for_child(t, prefix, layout) for t in dict.fromkeys(targets)])

    def _for_child(self, rel: str, prefix: str, layout: str) -> bool:
        """Walk every `RouterModule.forChild(<routes>)` table of `rel`."""
        tree = self.src.tree(rel)
        calls = [
            n
            for n in (_walk(tree.root_node) if tree is not None else [])
            if n.type == "call_expression"
            and _text(n.child_by_field_name("function")) == "RouterModule.forChild"
        ]
        for call in calls:
            args = _args(call)
            value = self.src.value(rel, args[0]) if args else None
            if value is not None and value[1].type == "array":
                self.array(value[0], value[1], prefix, layout)
            else:
                self.site(rel, call)
        return bool(calls)


def _decorators(cls: Node) -> list[Node]:
    decs = [c for c in cls.children if c.type == "decorator"]
    if cls.parent is not None and cls.parent.type == "export_statement":
        decs += [c for c in cls.parent.children if c.type == "decorator"]
    return decs


def _then_name(node: Node) -> str:
    """Export a `import(...).then(m => m.NAME)` takes; "default" otherwise."""
    for call in _walk(node):
        fn = (
            call.child_by_field_name("function")
            if call.type == "call_expression"
            else None
        )
        if (
            fn is None
            or fn.type != "member_expression"
            or _text(fn.child_by_field_name("property")) != "then"
        ):
            continue
        args = _args(call)
        body = args[0].child_by_field_name("body") if args else None
        if body is not None and body.type == "member_expression":
            return _text(body.child_by_field_name("property"))
        if body is not None and body.type == "identifier":
            return _text(body)
    return "default"


def walk_roots(
    src: Source,
    flavor: Flavor,
    candidates: list[tuple[str, Node]],
    result: PageResult,
    mounted: list[tuple[str, Node]] | None = None,
) -> None:
    """Walk every candidate table that no other candidate reaches; a cycle
    (nobody left as a root) falls back to walking the table with a site.

    `mounted` tables (`RouterModule.forChild`) are children of some module.
    When a lazy import could not be followed, one that nobody reached may
    hang below it, so it is a site, not a root with a wrong prefix."""
    unique = {(rel, node.start_byte): (rel, node) for rel, node in candidates}
    child = {(rel, node.start_byte) for rel, node in mounted or []}
    keys = sorted(unique)
    reached: set[tuple[str, int]] = set()
    for key in keys:  # dry run: which tables does each one reach?
        dry = Walker(src, flavor, PageResult())
        dry.array(*unique[key], "", "")
        reached |= dry.seen - {key}
    walker = Walker(src, flavor, result)
    roots = [k for k in keys if k not in reached]
    for key in (k for k in roots if k not in child):
        walker.array(*unique[key], "", "")
    held: set[tuple[str, int]] = set()
    for key in (k for k in roots if k in child and k not in walker.seen):
        if walker.lazy_failed:
            walker.site(*unique[key])
            held.add(key)
        else:
            walker.array(*unique[key], "", "")
    for key in (k for k in keys if k not in walker.seen | held):
        walker.site(*unique[key])
        walker.array(*unique[key], "", "")
