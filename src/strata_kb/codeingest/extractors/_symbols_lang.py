"""Per-language exported-name readers behind the `symbols` extractor.

`EXPORTERS` maps a `_ts` language id to `exporter(tree, source) ->
[(name, kind)]`: the names the file exports itself, nothing from the rest
of the repo. Later language tasks add one entry each. Names only -- an
enum or object member is `X.KEY`, its value is never read into the result.

Three optional companions keep the exporter signature small:

- `EXTRAS[lang](tree, source)` returns what only the repo can answer
  (`export ... from` re-exports, resolved by `symbols.py`) and the lines
  whose exports this module could not read exactly (each becomes a
  partial-coverage site).
- `HINTS[lang]` is a cheap byte pattern; a file without a match exports
  nothing and is never parsed.
- `LENIENT` names languages whose grammar is too weak for a syntax error
  to mean anything (SCSS interpolation breaks it); their errors are not
  sites.

shortcut: `module.exports` / `exports.x =` (CommonJS) is not read -- the
spec's "exported" for JS/TS is `export` syntax; revisit with a CJS repo.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = [
    "DEFAULT_NAME",
    "EXPORTERS",
    "EXTRAS",
    "HINTS",
    "LENIENT",
    "Extras",
    "Reexport",
]

Exporter = Callable[["Tree", bytes], list[tuple[str, str]]]

# Name an anonymous `export default` carries until `symbols.py` swaps in the
# file stem (the exporter has no file name).
DEFAULT_NAME = "default"

_FUNCTION_VALUES = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function"}
)
_WRAPPERS = frozenset(
    {
        "as_expression",
        "satisfies_expression",
        "parenthesized_expression",
        "non_null_expression",
        "type_assertion",
    }
)
_DECL_KIND = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "function_signature": "function",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
    "internal_module": "const",
    "module": "const",
}
_VARIABLE_DECLS = frozenset({"lexical_declaration", "variable_declaration"})
_JS_LANGS = ("typescript", "tsx", "javascript")


@dataclass(frozen=True)
class Reexport:
    kind: str  # star | named | ns
    spec: str
    names: tuple[tuple[str, str], ...]  # (imported, exported); ns: ("*", name)
    line: int


@dataclass(frozen=True)
class Extras:
    reexports: tuple[Reexport, ...]
    unreadable: tuple[int, ...]  # lines whose exports are not fully known
    # name the file's `export default` was listed under (`export *` skips it)
    default: str | None = None


# (name, kind, member source) per name a declaration binds.
_Binding = tuple[str, str, "Node | None"]


# -- JS / TS -----------------------------------------------------------------


def _unwrap(node: Node | None) -> Node | None:
    while node is not None:
        if node.type in _WRAPPERS:
            named = node.named_children
            node = named[-1 if node.type == "type_assertion" else 0] if named else None
        elif (
            node.type == "call_expression"
            and _ts.node_text(node.child_by_field_name("function") or node)
            == "Object.freeze"
        ):
            args = node.child_by_field_name("arguments")
            named = args.named_children if args is not None else []
            node = named[0] if len(named) == 1 else None
            if node is None:
                return None
        else:
            return node
    return None


def _prop_name(node: Node | None) -> str | None:
    """Key of an object/enum member, or None when it is computed."""
    if node is None:
        return None
    if node.type == "string":
        return _ts.string_literal(node)
    if node.type == "computed_property_name":
        named = node.named_children
        return (
            _prop_name(named[0])
            if len(named) == 1 and named[0].type == "string"
            else None
        )
    if node.type in (
        "property_identifier",
        "identifier",
        "number",
        "private_property_identifier",
    ):
        return _ts.node_text(node)
    return None


def _members(source: Node) -> tuple[list[str], list[int]]:
    """Keys of an enum body or object literal, plus the lines of members
    whose key is not a plain name (spread, computed): the list is then
    incomplete."""
    keys: list[str] = []
    bad: list[int] = []
    if source.type == "enum_declaration":
        body = source.child_by_field_name("body")
        children = body.named_children if body is not None else []
        pairs = [
            (c.child_by_field_name("name") if c.type == "enum_assignment" else c, c)
            for c in children
            if c.type != "comment"
        ]
    else:
        pairs = []
        for child in source.named_children:
            if child.type == "comment":
                continue
            if child.type in ("pair", "method_definition"):
                key = child.child_by_field_name(
                    "key" if child.type == "pair" else "name"
                )
                pairs.append((key, child))
            elif child.type == "shorthand_property_identifier":
                pairs.append((child, child))
            else:  # spread_element, anything unknown
                pairs.append((None, child))
    for key, child in pairs:
        name = _prop_name(key)
        if name is None:
            bad.append(_ts.line_of(child))
        else:
            keys.append(name)
    return keys, bad


def _pattern_names(node: Node | None) -> list[str]:
    if node is None:
        return []
    if node.type in ("identifier", "shorthand_property_identifier_pattern"):
        return [_ts.node_text(node)]
    if node.type == "pair_pattern":
        return _pattern_names(node.child_by_field_name("value"))
    if node.type in ("assignment_pattern", "object_assignment_pattern"):
        return _pattern_names(node.child_by_field_name("left"))
    if node.type in ("object_pattern", "array_pattern", "rest_pattern"):
        return [n for c in node.named_children for n in _pattern_names(c)]
    return []


def _variable_bindings(decl: Node) -> list[_Binding]:
    is_const = any(c.type == "const" for c in decl.children)
    out: list[_Binding] = []
    for declarator in decl.named_children:
        if declarator.type != "variable_declarator":
            continue
        target = declarator.child_by_field_name("name")
        if target is not None and target.type == "identifier":
            value = _unwrap(declarator.child_by_field_name("value"))
            kind = "const"
            if value is not None and value.type in _FUNCTION_VALUES:
                kind = "function"
            elif value is not None and value.type == "class":
                kind = "class"
            source = (
                value
                if is_const and value is not None and value.type == "object"
                else None
            )
            out.append((_ts.node_text(target), kind, source))
        else:
            out += [(n, "const", None) for n in _pattern_names(target)]
    return out


def _bindings(decl: Node) -> list[_Binding] | None:
    """What a declaration binds; None for a shape this reader does not know."""
    if decl.type == "ambient_declaration":
        inner = [c for c in decl.named_children if c.type != "comment"]
        return _bindings(inner[0]) if inner else None
    if decl.type in _VARIABLE_DECLS:
        return _variable_bindings(decl)
    if decl.type == "import_alias":
        first = decl.named_children[0] if decl.named_children else None
        return [(_ts.node_text(first), "const", None)] if first is not None else None
    kind = _DECL_KIND.get(decl.type)
    name = decl.child_by_field_name("name")
    if kind is None or name is None or name.type == "string":
        return None
    return [(_ts.node_text(name).split(".")[0], kind, decl if kind == "enum" else None)]


def _locals(root: Node) -> dict[str, tuple[str, Node | None]]:
    table: dict[str, tuple[str, Node | None]] = {}
    for stmt in root.named_children:
        decl = (
            stmt.child_by_field_name("declaration")
            if stmt.type == "export_statement"
            else stmt
        )
        for name, kind, source in (_bindings(decl) or []) if decl is not None else []:
            table.setdefault(name, (kind, source))
    return table


class _Reader:
    def __init__(self, root: Node):
        self.locals = _locals(root)
        self.out: list[tuple[str, str]] = []
        self.unreadable: list[int] = []
        self.default_name: str | None = None

    def emit(self, name: str, kind: str, source: Node | None) -> None:
        self.out.append((name, kind))
        if source is not None:
            keys, bad = _members(source)
            self.out += [(f"{name}.{k}", "member") for k in keys]
            self.unreadable += bad

    def local(self, local: str, exported: str, fallback: str) -> None:
        kind, source = self.locals.get(local, (fallback, None))
        self.emit(exported, kind, source)

    def default(self, stmt: Node) -> None:
        node = stmt.child_by_field_name("declaration")
        if node is not None:
            name = node.child_by_field_name("name")
            kind = _DECL_KIND.get(node.type, "const")
            self.default_name = (
                _ts.node_text(name) if name is not None else DEFAULT_NAME
            )
            self.emit(self.default_name, kind, None)
            return
        value = _unwrap(stmt.child_by_field_name("value"))
        if value is not None and value.type == "identifier":
            name = self.default_name = _ts.node_text(value)
            self.local(name, name, "const")
        else:
            self.default_name = DEFAULT_NAME
            kind = "const"
            if value is not None and value.type in _FUNCTION_VALUES:
                kind = "function"
            elif value is not None and value.type == "class":
                kind = "class"
            self.emit(DEFAULT_NAME, kind, None)

    def clause(self, clause: Node, type_only: bool) -> None:
        for spec in clause.named_children:
            if spec.type != "export_specifier":
                continue
            name = spec.child_by_field_name("name")
            alias = spec.child_by_field_name("alias")
            local = _export_name(name)
            exported = _export_name(alias) if alias is not None else local
            if local is None or exported is None:
                self.unreadable.append(_ts.line_of(spec))
                continue
            if exported == DEFAULT_NAME:
                self.default_name = DEFAULT_NAME
            typed = type_only or any(c.type == "type" for c in spec.children)
            self.local(local, exported, "type" if typed else "const")

    def statement(self, stmt: Node) -> None:
        kinds = {c.type for c in stmt.children}
        if stmt.child_by_field_name("source") is not None:
            return  # re-export: resolved in symbols.py
        if "default" in kinds or "=" in kinds:
            if "=" in kinds:  # `export = x`
                ident = next(
                    (c for c in stmt.named_children if c.type == "identifier"), None
                )
                if ident is not None:
                    self.local(_ts.node_text(ident), _ts.node_text(ident), "const")
                else:
                    self.unreadable.append(_ts.line_of(stmt))
            else:
                self.default(stmt)
            return
        clause = next(
            (c for c in stmt.named_children if c.type == "export_clause"), None
        )
        if clause is not None:
            self.clause(clause, "type" in kinds)
            return
        decl = stmt.child_by_field_name("declaration")
        if decl is not None:
            bound = _bindings(decl)
            if bound is None:
                self.unreadable.append(_ts.line_of(stmt))
            for name, kind, source in bound or []:
                self.emit(name, kind, source)
            return
        if "namespace" not in kinds:  # `export as namespace X` exports nothing
            self.unreadable.append(_ts.line_of(stmt))


def _export_name(node: Node | None) -> str | None:
    if node is None:
        return None
    return _ts.string_literal(node) if node.type == "string" else _ts.node_text(node)


def _js_read(tree: Tree) -> _Reader:
    reader = _Reader(tree.root_node)
    for stmt in tree.root_node.named_children:
        if stmt.type == "export_statement":
            reader.statement(stmt)
    return reader


def _js_exports(tree: Tree, _source: bytes) -> list[tuple[str, str]]:
    return _js_read(tree).out


def _js_extras(tree: Tree, _source: bytes) -> Extras:
    reexports: list[Reexport] = []
    reader = _js_read(tree)
    unreadable = list(reader.unreadable)
    for stmt in tree.root_node.named_children:
        source = (
            stmt.child_by_field_name("source")
            if stmt.type == "export_statement"
            else None
        )
        if source is None:
            continue
        spec = _ts.string_literal(source)
        line = _ts.line_of(stmt)
        if spec is None:
            unreadable.append(line)
            continue
        ns = next(
            (c for c in stmt.named_children if c.type == "namespace_export"), None
        )
        clause = next(
            (c for c in stmt.named_children if c.type == "export_clause"), None
        )
        if ns is not None:
            names = [_ts.node_text(c) for c in ns.named_children]
            reexports.append(
                Reexport("ns", spec, (("*", names[0]),) if names else (), line)
            )
        elif clause is not None:
            pairs = []
            for item in clause.named_children:
                if item.type != "export_specifier":
                    continue
                name = _export_name(item.child_by_field_name("name"))
                alias = item.child_by_field_name("alias")
                exported = _export_name(alias) if alias is not None else name
                if name is None or exported is None:
                    unreadable.append(_ts.line_of(item))
                else:
                    pairs.append((name, exported))
            reexports.append(Reexport("named", spec, tuple(pairs), line))
        else:
            reexports.append(Reexport("star", spec, (), line))
    return Extras(tuple(reexports), tuple(sorted(set(unreadable))), reader.default_name)


# -- CSS / SCSS --------------------------------------------------------------

_BLOCK_COMMENT = re.compile(rb"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(rb"^[ \t]*//[^\n]*", re.M)
_CUSTOM_PROP = re.compile(rb"(?<![\w-])(--[\w-]+)\s*:")
_PROPERTY_AT_RULE = re.compile(rb"@property\s+(--[\w-]+)")
_DYNAMIC_PROP = re.compile(rb"(?<![\w-])--[\w-]*#\{")


def _strip_comments(source: bytes) -> bytes:
    # replaced by blanks of the same line count so line numbers survive
    keep = lambda m: re.sub(rb"[^\n]", b" ", m.group(0))  # noqa: E731
    return _LINE_COMMENT.sub(keep, _BLOCK_COMMENT.sub(keep, source))


def _css_exports(_tree: Tree, source: bytes) -> list[tuple[str, str]]:
    # shortcut: regex, not the tree -- the SCSS grammar loses every
    # declaration after `--x: #{$v}`; a `--x:` inside a string is listed too.
    text = _strip_comments(source)
    names = {m.group(1) for m in _CUSTOM_PROP.finditer(text)}
    names |= {m.group(1) for m in _PROPERTY_AT_RULE.finditer(text)}
    return sorted((n.decode("utf-8", "replace"), "css-var") for n in names)


def _css_extras(_tree: Tree, source: bytes) -> Extras:
    # a custom property named by interpolation (`--#{$k}: v`) has no static name
    text = _strip_comments(source)
    lines = {text.count(b"\n", 0, m.start()) + 1 for m in _DYNAMIC_PROP.finditer(text)}
    return Extras((), tuple(sorted(lines)))


EXPORTERS: dict[str, Exporter] = {
    **dict.fromkeys(_JS_LANGS, _js_exports),
    "css": _css_exports,
    "scss": _css_exports,
}
EXTRAS: dict[str, Callable[[Tree, bytes], Extras]] = {
    **dict.fromkeys(_JS_LANGS, _js_extras),
    "css": _css_extras,
    "scss": _css_extras,
}
HINTS: dict[str, re.Pattern[bytes]] = {
    **dict.fromkeys(_JS_LANGS, re.compile(rb"\bexport\b")),
    "css": re.compile(rb"--"),
    "scss": re.compile(rb"--"),
}
LENIENT: frozenset[str] = frozenset({"css", "scss"})
