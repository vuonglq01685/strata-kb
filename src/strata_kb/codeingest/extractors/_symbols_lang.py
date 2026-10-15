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


def _imports(root: Node) -> dict[str, tuple[str, str]]:
    """local name -> (module specifier, imported name; `*` for a namespace)."""
    table: dict[str, tuple[str, str]] = {}
    for stmt in root.named_children:
        if stmt.type != "import_statement":
            continue
        spec = _ts.string_literal(stmt.child_by_field_name("source") or stmt)
        clause = next(
            (c for c in stmt.named_children if c.type == "import_clause"), None
        )
        if spec is None or clause is None:
            continue
        for part in clause.named_children:
            if part.type == "identifier":
                table[_ts.node_text(part)] = (spec, DEFAULT_NAME)
            elif part.type == "namespace_import" and part.named_children:
                table[_ts.node_text(part.named_children[-1])] = (spec, "*")
            elif part.type == "named_imports":
                for item in part.named_children:
                    name = _export_name(item.child_by_field_name("name"))
                    alias = item.child_by_field_name("alias")
                    local = _export_name(alias) if alias is not None else name
                    if name is not None and local is not None:
                        table[local] = (spec, name)
    return table


def _is_module_exports(node: Node | None) -> bool:
    return (
        node is not None
        and node.type == "member_expression"
        and _ts.node_text(node.child_by_field_name("object") or node) == "module"
        and _ts.node_text(node.child_by_field_name("property") or node) == "exports"
    )


def _cjs_slot(left: Node | None) -> tuple[str, str | None] | None:
    """("whole", None) for `module.exports =`, ("prop", name|None) for
    `exports.x =` / `module.exports.x =` (None: computed name), else None."""
    if left is None:
        return None
    if _is_module_exports(left):
        return "whole", None
    if left.type not in ("member_expression", "subscript_expression"):
        return None
    target = left.child_by_field_name("object")
    if not (
        target is not None
        and (
            (target.type == "identifier" and _ts.node_text(target) == "exports")
            or _is_module_exports(target)
        )
    ):
        return None
    if left.type == "member_expression":
        return "prop", _ts.node_text(left.child_by_field_name("property") or left)
    index = left.child_by_field_name("index")
    return "prop", _ts.string_literal(index) if index is not None else None


def _value_kind(value: Node | None) -> str:
    if value is not None and value.type in _FUNCTION_VALUES:
        return "function"
    if value is not None and value.type == "class":
        return "class"
    return "const"


class _Reader:
    def __init__(self, root: Node):
        self.locals = _locals(root)
        self.imports = _imports(root)
        self.imported: list[Reexport] = []
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
        for spec_node in clause.named_children:
            if spec_node.type != "export_specifier":
                continue
            name = spec_node.child_by_field_name("name")
            alias = spec_node.child_by_field_name("alias")
            local = _export_name(name)
            exported = _export_name(alias) if alias is not None else local
            if local is None or exported is None:
                self.unreadable.append(_ts.line_of(spec_node))
                continue
            if local not in self.locals and local in self.imports:
                spec, imported = self.imports[local]
                kind = "ns" if imported == "*" else "named"
                pair = ("*" if kind == "ns" else imported, exported)
                self.imported.append(
                    Reexport(kind, spec, (pair,), _ts.line_of(spec_node))
                )
                continue
            if exported == DEFAULT_NAME:
                self.default_name = DEFAULT_NAME
            typed = type_only or any(c.type == "type" for c in spec_node.children)
            self.local(local, exported, "type" if typed else "const")

    def cjs(self, root: Node) -> None:
        stack = [root]
        while stack:
            node = stack.pop()
            stack.extend(reversed(node.children))
            if node.type != "assignment_expression":
                continue
            slot = _cjs_slot(node.child_by_field_name("left"))
            if slot is None:
                continue
            value = _unwrap(node.child_by_field_name("right"))
            if slot[0] == "prop":
                if slot[1] is None:
                    self.unreadable.append(_ts.line_of(node))
                else:
                    object_ = (
                        value if value is not None and value.type == "object" else None
                    )
                    self.emit(slot[1], _value_kind(value), object_)
            else:
                self.module_exports(node, value)

    def module_exports(self, node: Node, value: Node | None) -> None:
        if value is not None and value.type == "identifier":
            name = _ts.node_text(value)
            self.local(name, name, "const")
        elif value is not None and value.type == "object":
            for child in value.named_children:
                self.cjs_member(child)
        elif (
            value is not None
            and value.type in ("function_expression", "class", "generator_function")
            and value.child_by_field_name("name") is not None
        ):
            self.emit(
                _ts.node_text(value.child_by_field_name("name") or value),
                _value_kind(value),
                None,
            )
        else:  # require(..), a call, an anonymous function/class, a chain
            self.unreadable.append(_ts.line_of(node))

    def cjs_member(self, child: Node) -> None:
        if child.type == "comment":
            return
        if child.type == "shorthand_property_identifier":
            name = _ts.node_text(child)
            self.emit(name, self.locals.get(name, ("const", None))[0], None)
        elif child.type in ("pair", "method_definition"):
            is_pair = child.type == "pair"
            name = _prop_name(child.child_by_field_name("key" if is_pair else "name"))
            value = _unwrap(child.child_by_field_name("value")) if is_pair else None
            if name is None:
                self.unreadable.append(_ts.line_of(child))
            elif not is_pair:
                self.emit(name, "function", None)
            elif value is not None and value.type == "identifier":
                self.emit(
                    name,
                    self.locals.get(_ts.node_text(value), ("const", None))[0],
                    None,
                )
            else:
                self.emit(name, _value_kind(value), None)
        else:  # spread_element, anything unknown
            self.unreadable.append(_ts.line_of(child))

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


def _js_read(tree: Tree, source: bytes) -> _Reader:
    reader = _Reader(tree.root_node)
    for stmt in tree.root_node.named_children:
        if stmt.type == "export_statement":
            reader.statement(stmt)
    if b"exports" in source:
        reader.cjs(tree.root_node)
    return reader


def _js_exports(tree: Tree, source: bytes) -> list[tuple[str, str]]:
    return _js_read(tree, source).out


def _js_extras(tree: Tree, source: bytes) -> Extras:
    reader = _js_read(tree, source)
    reexports: list[Reexport] = list(reader.imported)
    unreadable = list(reader.unreadable)
    for stmt in tree.root_node.named_children:
        from_node = (
            stmt.child_by_field_name("source")
            if stmt.type == "export_statement"
            else None
        )
        if from_node is None:
            continue
        spec = _ts.string_literal(from_node)
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
_STRING = re.compile(rb""""(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'""")
_URL = re.compile(rb"url\([^)\n]*\)", re.I)
_SUPPORTS = re.compile(rb"@supports[^{;]*")
_LINE_COMMENT = re.compile(rb"//[^\n]*")
_CUSTOM_PROP = re.compile(rb"(?<![\w-])(--[\w-]+)\s*:")
_PROPERTY_AT_RULE = re.compile(rb"@property\s+(--[\w-]+)")
_DYNAMIC_PROP = re.compile(rb"(?<![\w-])--[\w-]*#\{")


def _blank(pattern: re.Pattern[bytes], text: bytes) -> bytes:
    # same line count, so line numbers survive
    return pattern.sub(lambda m: re.sub(rb"[^\n]", b" ", m.group(0)), text)


def _clean_style(source: bytes, scss: bool) -> bytes:
    """`source` with everything that can hold a `--x:` lookalike blanked:
    comments, strings, `url(..)`, `@supports (..)` conditions."""
    text = _blank(_BLOCK_COMMENT, source)
    for pattern in (_STRING, _URL, _SUPPORTS, *([_LINE_COMMENT] if scss else [])):
        text = _blank(pattern, text)
    return text


def _css_reader(scss: bool) -> Exporter:
    def exports(_tree: Tree, source: bytes) -> list[tuple[str, str]]:
        # shortcut: regex, not the tree -- the SCSS grammar loses every
        # declaration after `--x: #{$v}`.
        text = _clean_style(source, scss)
        names = {m.group(1) for m in _CUSTOM_PROP.finditer(text)}
        names |= {m.group(1) for m in _PROPERTY_AT_RULE.finditer(text)}
        return sorted((n.decode("utf-8", "replace"), "css-var") for n in names)

    return exports


def _css_extras(scss: bool) -> Callable[[Tree, bytes], Extras]:
    def extras(_tree: Tree, source: bytes) -> Extras:
        # a custom property named by interpolation (`--#{$k}: v`) has no static name
        text = _clean_style(source, scss)
        lines = {
            text.count(b"\n", 0, m.start()) + 1 for m in _DYNAMIC_PROP.finditer(text)
        }
        return Extras((), tuple(sorted(lines)))

    return extras


EXPORTERS: dict[str, Exporter] = {
    **dict.fromkeys(_JS_LANGS, _js_exports),
    "css": _css_reader(False),
    "scss": _css_reader(True),
}
EXTRAS: dict[str, Callable[[Tree, bytes], Extras]] = {
    **dict.fromkeys(_JS_LANGS, _js_extras),
    "css": _css_extras(False),
    "scss": _css_extras(True),
}
HINTS: dict[str, re.Pattern[bytes]] = {
    **dict.fromkeys(_JS_LANGS, re.compile(rb"\bexports?\b")),
    "css": re.compile(rb"--"),
    "scss": re.compile(rb"--"),
}
LENIENT: frozenset[str] = frozenset({"css", "scss"})
