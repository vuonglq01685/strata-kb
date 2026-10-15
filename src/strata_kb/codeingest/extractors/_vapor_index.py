"""Cross-file definition index of a Swift scope for the Vapor route adapter.

Everything the evaluator resolves by name is collected here from ALL files
before any route is read, so file order never matters: functions and methods
(including `init`), type declarations with their supertypes, extensions,
stored-property types, type aliases, and the top-level statements of each
file. Local declarations inside function bodies are not indexed; the
evaluator meets them as it walks the body.

Type names are short names (`Foo.Bar` is `Bar`). Two declarations of one name
are kept side by side; a caller that needs one answer treats two as ambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import (
    _error_line,
    _parse,
    _read,
    _text,
)
from strata_kb.codeingest.extractors._swift_ast import (
    decl_keyword,
    decl_name,
    first_of,
    kids,
    pattern_names,
    type_name,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tree_sitter import Node, Tree

__all__ = ["Fn", "Index", "Param", "TypeDecl"]

_DECLARATIONS = frozenset(
    {
        "import_declaration", "class_declaration", "protocol_declaration",
        "function_declaration", "typealias_declaration", "init_declaration",
        "deinit_declaration", "subscript_declaration", "operator_declaration",
        "precedence_group_declaration", "macro_declaration",
    }
)  # fmt: skip
_BODIES = ("class_body", "enum_class_body", "protocol_body")
_MAX_CHAIN = 12  # supertype hops followed


@dataclass(frozen=True)
class Param:
    external: str  # label at the call site, `_` for none
    internal: str
    type_node: Node | None


@dataclass(frozen=True)
class Fn:
    node: Node
    file: str
    owner: str  # short name of the enclosing type, "" for a free function
    name: str  # `init` for an initializer

    @property
    def key(self) -> int:
        return self.node.id

    @property
    def line(self) -> int:
        return self.node.start_point[0] + 1

    @property
    def body(self) -> Node | None:
        return self.node.child_by_field_name("body")

    def params(self) -> list[Param]:
        out = []
        for p in kids(self.node):
            if p.type != "parameter":
                continue
            idents = [c for c in kids(p) if c.type == "simple_identifier"]
            if not idents:
                continue
            kind = next(
                (
                    c
                    for c in kids(p)
                    if c.type not in ("simple_identifier", "parameter_modifiers")
                ),
                None,
            )
            internal = _text(idents[-1])
            external = _text(idents[0]) if len(idents) > 1 else internal
            out.append(Param(external, internal, kind))
        return out

    def bounds(self) -> dict[str, str]:
        """Generic parameter -> the protocol it must conform to."""
        found: dict[str, str] = {}
        for tp in kids(self.node):
            if tp.type == "type_parameters":
                for item in kids(tp):
                    name = first_of(item, "type_identifier")
                    bound = first_of(item, "user_type")
                    if name is not None and bound is not None:
                        found[_text(name)] = type_name(bound)
        for con in kids(self.node):
            if con.type != "type_constraints":
                continue
            for item in kids(con):
                inner = first_of(item, "inheritance_constraint")
                if inner is None:
                    continue
                target = first_of(inner, "identifier")
                bound = first_of(inner, "user_type")
                if target is not None and bound is not None:
                    found.setdefault(_text(target), type_name(bound))
        return found


@dataclass(frozen=True)
class TypeDecl:
    name: str
    kind: str  # struct | class | enum | actor | protocol | extension
    node: Node
    file: str
    supers: tuple[str, ...]


@dataclass
class Index:
    root: Path
    files: dict[str, Tree] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)  # file -> first error line
    unreadable: list[str] = field(default_factory=list)
    funcs: dict[str, list[Fn]] = field(default_factory=dict)  # free functions
    methods: dict[tuple[str, str], list[Fn]] = field(default_factory=dict)
    types: dict[str, list[TypeDecl]] = field(default_factory=dict)
    extensions: dict[str, list[TypeDecl]] = field(default_factory=dict)
    # every type a stored property / alias is declared with; two disagreeing
    # declarations (same-named types in two modules) are ambiguous
    props: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    aliases: dict[str, set[str]] = field(default_factory=dict)
    all_fns: list[Fn] = field(default_factory=list)
    members: list[tuple[str, str, Node]] = field(
        default_factory=list
    )  # (file, owner, node)
    top_level: dict[str, list[Node]] = field(default_factory=dict)

    # -- building ---------------------------------------------------------

    def add_file(self, rel: str) -> None:
        data = _read(self.root, rel)
        if data is None:
            self.unreadable.append(f"{rel}:1")
            return
        tree = _parse(rel, data)
        self.files[rel] = tree
        line = _error_line(tree)
        if line is not None:
            self.errors[rel] = line
        self._scan(rel, tree)

    def finish(self) -> None:
        """Call once after the last `add_file`."""
        self.all_fns.sort(key=lambda f: (f.file, f.node.start_byte))

    def _scan(self, rel: str, tree: Tree) -> None:
        stack = [(kids(tree.root_node), "", True)]
        while stack:
            children, owner, at_top = stack.pop()
            for node in children:
                self._declare(rel, node, owner, at_top, stack)

    def _declare(self, rel, node, owner, at_top, stack) -> None:
        kind = node.type
        if kind in ("class_declaration", "protocol_declaration"):
            self._type(rel, node, stack)
        elif kind == "function_declaration":
            name = first_of(node, "simple_identifier")
            fn = Fn(node, rel, owner, _text(name) if name is not None else "")
            self.all_fns.append(fn)
            if fn.name:
                key = (
                    self.methods.setdefault((owner, fn.name), [])
                    if owner
                    else self.funcs.setdefault(fn.name, [])
                )
                key.append(fn)
        elif kind == "init_declaration":
            fn = Fn(node, rel, owner, "init")
            self.all_fns.append(fn)
            self.methods.setdefault((owner, "init"), []).append(fn)
        elif kind == "typealias_declaration":
            name = first_of(node, "type_identifier")
            target = [c for c in kids(node) if c.type != "type_identifier"][-1:]
            if name is not None and target:
                self.aliases.setdefault(_text(name), set()).add(type_name(target[0]))
        elif kind in ("deinit_declaration", "subscript_declaration"):
            self.members.append((rel, owner, node))
        elif kind == "property_declaration" and owner:
            self._property(rel, node, owner)
        elif at_top and kind not in _DECLARATIONS:
            self.top_level.setdefault(rel, []).append(node)

    def _type(self, rel: str, node: Node, stack) -> None:
        keyword = decl_keyword(node)
        short = decl_name(node).split(".")[-1]
        supers = tuple(
            name
            for spec in kids(node)
            if spec.type == "inheritance_specifier"
            for name in [type_name(spec.child_by_field_name("inherits_from"))]
            if name
        )
        decl = TypeDecl(short, keyword, node, rel, supers)
        table = self.extensions if keyword == "extension" else self.types
        table.setdefault(short, []).append(decl)
        body = next((c for c in kids(node) if c.type in _BODIES), None)
        if body is not None:
            stack.append((kids(body), short, False))

    def _property(self, rel: str, node: Node, owner: str) -> None:
        names = pattern_names(node)
        annotation = first_of(node, "type_annotation")
        value = node.child_by_field_name("value")
        declared = (
            type_name(annotation.child_by_field_name("name"))
            if annotation is not None
            else ""
        )
        if not declared and value is not None and value.type == "call_expression":
            callee = kids(value)[0]
            declared = _text(callee) if callee.type == "simple_identifier" else ""
        if len(names) == 1 and declared:
            self.props.setdefault((owner, names[0]), set()).add(declared)
        if (
            value is not None
            or first_of(node, "computed_property") is not None
            or node.child_by_field_name("computed_value") is not None
        ):
            self.members.append((rel, owner, node))

    # -- queries ----------------------------------------------------------

    def supertypes(self, name: str) -> list[str]:
        """Transitive supertypes of `name` declared or extended in the repo."""
        seen: list[str] = []
        todo = [name]
        while todo and len(seen) < _MAX_CHAIN * 4:
            current = todo.pop()
            for decl in [
                *self.types.get(current, []),
                *self.extensions.get(current, []),
            ]:
                for sup in decl.supers:
                    if sup not in seen and sup != name:
                        seen.append(sup)
                        todo.append(sup)
        return seen

    def has_unknown_super(self, name: str, known: frozenset[str]) -> bool:
        """A supertype that is neither declared in the repo nor in `known`."""
        return any(
            s not in self.types and s not in known for s in self.supertypes(name)
        )

    def conforms_any(self, name: str, protocols: frozenset[str]) -> bool:
        return name in protocols or any(s in protocols for s in self.supertypes(name))

    def conforms(self, name: str, protocol: str) -> bool:
        return name == protocol or protocol in self.supertypes(name)

    def find_methods(self, owner: str, name: str) -> list[Fn]:
        """Methods called `name` of `owner`, its extensions and (transitively)
        its superclasses; the nearest type that has one wins."""
        for current in [owner, *self.supertypes(owner)]:
            found = self.methods.get((current, name), [])
            if found:
                return found
        return []

    def prop_type(self, owner: str, name: str) -> str:
        """The one type `owner` (or a supertype) declares `name` with, else ''."""
        declared: set[str] = set()
        for current in [owner, *self.supertypes(owner)]:
            declared |= self.props.get((current, name), set())
        return next(iter(declared)) if len(declared) == 1 else ""

    def has_type(self, name: str) -> bool:
        return name in self.types

    def resolve_alias(self, name: str) -> str:
        """`name` with type aliases followed; '' when an alias is ambiguous."""
        for _ in range(4):
            targets = self.aliases.get(name)
            if not targets:
                break
            if len(targets) != 1:
                return ""
            name = next(iter(targets))
        return name
